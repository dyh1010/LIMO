import ast
from pathlib import Path
import sys
import threading
import unittest
import xml.etree.ElementTree as ET


PACKAGE_ROOT = Path(__file__).parents[1]
SCRIPT = PACKAGE_ROOT / 'scripts' / 'v1_localization_manager.py'
sys.path.insert(0, str(PACKAGE_ROOT / 'scripts'))

import v1_localization_manager as wrapper  # noqa: E402


class LocalizationManagerSourceTest(unittest.TestCase):

    def test_wrapper_has_no_velocity_or_goal_publication_api(self):
        source = SCRIPT.read_text(encoding='utf-8')
        tree = ast.parse(source)
        imported = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        self.assertNotIn('Twist', imported)
        self.assertNotIn('move_base_msgs', source)
        self.assertNotIn('/cmd_vel', source)
        self.assertNotIn('SimpleActionClient', source)
        self.assertIn("'/request_nomotion_update'", source)
        self.assertIn("'/initialpose'", source)
        self.assertIn("'/amcl_pose'", source)
        self.assertIn("'/v1/private_move_base/status'", source)
        self.assertNotIn("'/move_base/status'", source)
        self.assertIn('self.state_lock = threading.RLock()', source)
        self.assertIn('self.nomotion_lock = threading.Lock()', source)
        self.assertIn('self._invalidate_nomotion_call()', source)
        self.assertIn('nomotion_generation', source)
        self.assertIn('generation != self.nomotion_generation', source)
        self.assertIn('not self.nomotion_call_active', source)
        self.assertIn("for canonical in ('/map_server', '/amcl')", source)
        self.assertIn("node.startswith(canonical + '_')", source)
        for forbidden in (
                '/slam_gmapping', '/cartographer_node', '/robot_pose_ekf'):
            self.assertIn(forbidden, source)
        self.assertIn('forbidden_localization_owner_present', source)

    def test_yaw_conversion_is_planar_and_finite(self):
        class Quaternion:
            x = 0.0
            y = 0.0
            z = 2.0 ** -0.5
            w = 2.0 ** -0.5

        from limo_v1_navigation.localization_policy import planar_yaw
        self.assertAlmostEqual(planar_yaw(
            Quaternion.x, Quaternion.y, Quaternion.z, Quaternion.w),
            1.57079632679)

    def test_both_localization_launch_paths_start_the_manager(self):
        for name in ('v1_localization.launch', 'v1_navigation.launch'):
            root = ET.parse(PACKAGE_ROOT / 'launch' / name).getroot()
            nodes = root.findall(
                ".//node[@type='v1_localization_manager.py']")
            self.assertEqual(len(nodes), 1, name)
            node = nodes[0]
            self.assertEqual(node.attrib.get('required'), 'true')
            params = {
                item.attrib.get('name'): item.attrib.get('value')
                for item in node.findall('param')}
            self.assertEqual(params['map_file'], '$(arg map_file)')
            self.assertEqual(params['active_map_id'], '$(arg active_map_id)')
        localization = ET.parse(
            PACKAGE_ROOT / 'launch' / 'v1_localization.launch').getroot()
        amcl = localization.find(".//node[@name='amcl']")
        self.assertEqual(amcl.find('remap').attrib, {
            'from': 'initialpose', 'to': '/v1/validated_initialpose'})

    def test_timed_out_nomotion_response_cannot_reenter_new_generation(self):
        class Manager:
            def __init__(self):
                self.results = []

            def record_nomotion_result(self, success, error=''):
                self.results.append((success, error))

        node = object.__new__(wrapper.V1LocalizationManager)
        node.manager = Manager()
        node.nomotion_lock = threading.Lock()
        node.nomotion_generation = 4
        node.nomotion_call_active = True
        node.nomotion_call_started = 10.0
        node.nomotion_result = None
        node.nomotion_service_timeout_s = 0.5

        node._poll_nomotion_result(10.5)
        self.assertEqual(node.nomotion_generation, 5)
        self.assertEqual(
            node.manager.results, [(False, 'service_call_timeout')])
        self.assertFalse(node._store_nomotion_result(4, True, 'late'))
        self.assertIsNone(node.nomotion_result)

        node.nomotion_call_active = True
        node.nomotion_call_started = 11.0
        self.assertTrue(node._store_nomotion_result(5, True, ''))
        node._poll_nomotion_result(11.1)
        self.assertEqual(
            node.manager.results,
            [(False, 'service_call_timeout'), (True, '')])

    def test_chain_loss_invalidates_inflight_nomotion_response(self):
        class Manager:
            def __init__(self):
                self.chain = wrapper.ChainEvidence(True, 'ok', 1.0)
                self.results = []

            def update_chain(self, evidence, _now):
                self.chain = evidence

            def record_nomotion_result(self, success, error=''):
                self.results.append((success, error))

            def nomotion_due(self, _now, navigation_active=None):
                return False

            def tick(self, _now):
                return None

        node = object.__new__(wrapper.V1LocalizationManager)
        node.manager = Manager()
        node.state_lock = threading.RLock()
        node.nomotion_lock = threading.Lock()
        node.nomotion_generation = 7
        node.nomotion_call_active = True
        node.nomotion_call_started = 1.0
        node.nomotion_result = (7, True, '')
        node.navigation_active = False
        node._chain_evidence = lambda now: wrapper.ChainEvidence(
            False, 'scan_receive_stale', now)
        node._publish_status = lambda _now, _event: None

        node._timer(None)

        self.assertEqual(node.nomotion_generation, 8)
        self.assertFalse(node.nomotion_call_active)
        self.assertIsNone(node.nomotion_result)
        self.assertEqual(node.manager.results, [])
        self.assertFalse(node.manager.chain.ok)

    def test_pose_epoch_invalidation_rejects_old_nomotion_response(self):
        node = object.__new__(wrapper.V1LocalizationManager)
        node.nomotion_lock = threading.Lock()
        node.nomotion_generation = 12
        node.nomotion_call_active = True
        node.nomotion_call_started = 2.0
        node.nomotion_result = None

        node._invalidate_nomotion_call()

        self.assertEqual(node.nomotion_generation, 13)
        self.assertFalse(node._store_nomotion_result(12, True, 'late'))
        self.assertIsNone(node.nomotion_result)


if __name__ == '__main__':
    unittest.main()

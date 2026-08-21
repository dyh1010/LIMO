import json
import math
from pathlib import Path
import sys
import unittest


WORKSPACE = Path(__file__).resolve().parents[2]
PACKAGE = WORKSPACE / 'ros1_overlay_src' / 'limo_v1_navigation'
sys.path.insert(0, str(PACKAGE / 'src'))

from limo_v1_navigation.tag_docking_policy import (  # noqa: E402
    ACTION_GOAL_SCHEMA,
    DockingPolicyError,
    FINAL_DOCKING,
    PREAPPROACH,
    compute_base_goal,
    compute_preapproach_goal,
    validate_action_goal,
    validate_config,
)


TEMPLATE = PACKAGE / 'config' / 'v1_apriltag_docking.template.json'
SCHEMA = PACKAGE / 'config' / 'v1_apriltag_docking.schema.json'
ACTION = PACKAGE / 'config' / 'v1_tag_docking_action_contract.json'
SOURCE = PACKAGE / 'src' / 'limo_v1_navigation' / 'tag_docking_policy.py'


def _template():
    return json.loads(TEMPLATE.read_text(encoding='utf-8'))


def valid_payload():
    payload = _template()
    payload['template_only'] = False
    payload['measurement_status'] = 'MEASURED_VERIFIED'
    field_positions = (
        (0.5, 2.0, 0.5), (3.0, 0.0, 0.5),
        (0.5, -2.0, 0.5), (-2.0, 0.0, 0.5))
    for record, position in zip(payload['field_tags'], field_positions):
        record['measured'] = True
        record['pose_map']['position_xyz'] = list(position)
        record['pose_map']['orientation_xyzw'] = [0.0, 0.0, 0.0, 1.0]
    payload['geofence'].update({
        'measured': True,
        'polygon_map': [
            {'x': -2.0, 'y': -2.0}, {'x': 3.0, 'y': -2.0},
            {'x': 3.0, 'y': 2.0}, {'x': -2.0, 'y': 2.0}],
        'boundary_margin_m': 0.20,
        'base_footprint_radius_m': 0.30,
    })
    for record in payload['objects']:
        record['dimensions_m'] = {
            'length': 0.40, 'width': 0.30, 'height': 0.50}
        record['mount_verified'] = True
    payload['calibration']['base_link_to_camera_optical'].update({
        'measured_verified': True,
        'translation_xyz': [0.10, 0.0, 0.20],
        'rotation_xyzw': [-0.5, 0.5, -0.5, 0.5],
    })
    return payload


def tag_pose(x=2.0, y=0.0, z=0.2):
    return {
        'frame_id': 'map',
        'position_xyz': [x, y, z],
        'orientation_xyzw': [-0.5, -0.5, 0.5, 0.5],
    }


def assert_code(test, code, function, *args, **kwargs):
    with test.assertRaises(DockingPolicyError) as caught:
        function(*args, **kwargs)
    test.assertEqual(caught.exception.code, code)


class TagDockingPolicyTest(unittest.TestCase):

    def test_01_unfilled_template_is_fail_closed(self):
        assert_code(
            self, 'CONFIG_TEMPLATE_INCOMPLETE', validate_config, _template())

    def test_02_completed_config_has_exact_tag_mapping(self):
        config = validate_config(valid_payload())
        self.assertEqual(set(config['tag_map']), set(range(12)))
        self.assertEqual(
            config['tag_map'][7],
            {'object_id': 1, 'side_index': 3, 'side_label': 'side_3'})

    def test_03_missing_field_measurement_is_rejected(self):
        payload = valid_payload()
        payload['field_tags'][2]['pose_map']['position_xyz'][0] = None
        assert_code(self, 'INVALID_FIELD_TAGS', validate_config, payload)

    def test_04_duplicate_field_id_is_rejected(self):
        payload = valid_payload()
        payload['field_tags'][3]['id'] = 2
        assert_code(self, 'INVALID_FIELD_TAGS', validate_config, payload)

    def test_05_clockwise_geofence_is_rejected(self):
        payload = valid_payload()
        payload['geofence']['polygon_map'].reverse()
        assert_code(self, 'INVALID_GEOFENCE', validate_config, payload)

    def test_06_unmeasured_footprint_is_rejected(self):
        payload = valid_payload()
        payload['geofence']['base_footprint_radius_m'] = None
        assert_code(self, 'INVALID_GEOFENCE', validate_config, payload)

    def test_07_wrong_object_tag_mapping_is_rejected(self):
        payload = valid_payload()
        payload['objects'][1]['tags'][0]['id'] = 8
        assert_code(self, 'INVALID_OBJECT_MAP', validate_config, payload)

    def test_08_unverified_extrinsic_is_rejected(self):
        payload = valid_payload()
        payload['calibration']['base_link_to_camera_optical'][
            'measured_verified'] = False
        assert_code(self, 'EXTRINSIC_UNVERIFIED', validate_config, payload)

    def test_09_preapproach_goal_geometry(self):
        config = validate_config(valid_payload())
        goal = compute_preapproach_goal(
            config, 'tag52h13', 0, tag_pose(), 0.95, 0.05)
        self.assertEqual(goal.phase, PREAPPROACH)
        self.assertAlmostEqual(goal.camera_standoff_m, 0.90)
        self.assertAlmostEqual(goal.camera_x, 1.10, places=7)
        self.assertAlmostEqual(goal.base_x, 1.00, places=7)
        self.assertAlmostEqual(goal.base_y, 0.0, places=7)
        self.assertAlmostEqual(goal.base_yaw, 0.0, places=7)
        self.assertGreaterEqual(goal.geofence_clearance_m, 0.5)

    def test_10_camera_standoff_is_optical_center_to_tag_plane(self):
        config = validate_config(valid_payload())
        goal = compute_base_goal(
            config, 'tag52h13', 3, tag_pose(), 0.95, 0.01,
            0.40, FINAL_DOCKING)
        tag = tag_pose()['position_xyz']
        camera = (goal.camera_x, goal.camera_y, goal.camera_z)
        self.assertAlmostEqual(math.dist(tag, camera), 0.40, places=7)
        self.assertAlmostEqual(goal.base_x, 1.50, places=7)

    def test_11_invalid_family_is_rejected(self):
        config = validate_config(valid_payload())
        assert_code(
            self, 'INVALID_FAMILY', compute_preapproach_goal,
            config, 'tag36h11', 0, tag_pose(), 0.95, 0.01)

    def test_12_invalid_target_id_is_rejected(self):
        config = validate_config(valid_payload())
        assert_code(
            self, 'INVALID_TAG_ID', compute_preapproach_goal,
            config, 'tag52h13', 12, tag_pose(), 0.95, 0.01)

    def test_13_missing_tag_pose_field_is_rejected(self):
        config = validate_config(valid_payload())
        pose = tag_pose()
        del pose['orientation_xyzw']
        assert_code(
            self, 'TAG_POSE_INVALID', compute_preapproach_goal,
            config, 'tag52h13', 0, pose, 0.95, 0.01)

    def test_14_low_confidence_is_rejected(self):
        config = validate_config(valid_payload())
        assert_code(
            self, 'LOW_CONFIDENCE', compute_preapproach_goal,
            config, 'tag52h13', 0, tag_pose(), 0.79, 0.01)

    def test_15_stale_or_future_tag_is_rejected(self):
        config = validate_config(valid_payload())
        for age in (-0.01, 0.251):
            with self.subTest(age=age):
                assert_code(
                    self, 'TAG_STALE', compute_preapproach_goal,
                    config, 'tag52h13', 0, tag_pose(), 0.95, age)

    def test_16_outside_geofence_is_rejected(self):
        config = validate_config(valid_payload())
        assert_code(
            self, 'GEOFENCE_REJECTED', compute_preapproach_goal,
            config, 'tag52h13', 0, tag_pose(x=-1.5), 0.95, 0.01)

    def test_17_footprint_clearance_is_rejected(self):
        config = validate_config(valid_payload())
        assert_code(
            self, 'GEOFENCE_REJECTED', compute_preapproach_goal,
            config, 'tag52h13', 0, tag_pose(x=-0.6), 0.95, 0.01)

    def test_18_nonplanar_base_goal_is_rejected(self):
        payload = valid_payload()
        payload['calibration']['base_link_to_camera_optical'][
            'rotation_xyzw'] = [0.0, 0.0, 0.0, 1.0]
        config = validate_config(payload)
        assert_code(
            self, 'UNREACHABLE_BASE_POSE', compute_preapproach_goal,
            config, 'tag52h13', 0, tag_pose(), 0.95, 0.01)

    def test_19_unapproved_final_standoff_is_rejected(self):
        config = validate_config(valid_payload())
        assert_code(
            self, 'STANDOFF_NOT_ALLOWED', compute_base_goal,
            config, 'tag52h13', 0, tag_pose(), 0.95, 0.01,
            0.30, FINAL_DOCKING)

    def test_20_action_goal_contract_maps_object_side(self):
        config = validate_config(valid_payload())
        goal = validate_action_goal(config, {
            'schema': ACTION_GOAL_SCHEMA,
            'request_id': 'demo-001',
            'target_family': 'tag52h13',
            'target_id': 10,
            'standoff_m': 0.40,
        })
        self.assertEqual(goal['mapping']['object_id'], 2)
        self.assertEqual(goal['mapping']['side_index'], 2)

    def test_21_action_goal_rejects_family_and_missing_fields(self):
        config = validate_config(valid_payload())
        wrong = {
            'schema': ACTION_GOAL_SCHEMA, 'request_id': 'x',
            'target_family': 'tag36h11', 'target_id': 0,
            'standoff_m': 0.40}
        assert_code(self, 'INVALID_FAMILY', validate_action_goal, config, wrong)
        del wrong['request_id']
        assert_code(
            self, 'ACTION_GOAL_INVALID', validate_action_goal, config, wrong)

    def test_22_unsafe_limits_are_rejected(self):
        for name, value in (
                ('max_linear_speed_mps', 0.151),
                ('max_angular_speed_rad_s', 0.351),
                ('motion_output_enabled', True)):
            payload = valid_payload()
            payload['safety'][name] = value
            with self.subTest(name=name):
                assert_code(
                    self, 'INVALID_SAFETY_LIMIT', validate_config, payload)

    def test_23_schema_template_and_action_are_strict_json(self):
        schema = json.loads(SCHEMA.read_text(encoding='utf-8'))
        action = json.loads(ACTION.read_text(encoding='utf-8'))
        template = _template()
        self.assertFalse(schema['additionalProperties'])
        self.assertEqual(template['planning']['default_final_standoff_m'], 0.4)
        self.assertEqual(action['goal']['field_contract']['target_family'],
                         'exactly tag52h13')
        self.assertFalse(action['transport']['ros_runtime_implemented'])
        self.assertTrue(action['transport']['direct_move_base_client_forbidden'])
        self.assertTrue(action['transport']['direct_cmd_vel_or_twist_output_forbidden'])

    def test_24_policy_source_has_no_ros_or_motion_surface(self):
        source = SOURCE.read_text(encoding='utf-8')
        for forbidden in (
                'import rospy', 'Publisher(', 'ServiceProxy(',
                'SimpleActionClient(', 'geometry_msgs', 'Twist(',
                'cmd_vel', 'send_goal('):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)


if __name__ == '__main__':
    unittest.main()

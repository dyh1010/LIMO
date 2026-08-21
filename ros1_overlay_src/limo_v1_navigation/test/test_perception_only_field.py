import io
from pathlib import Path
import sys
import unittest
from unittest import mock


PACKAGE_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / 'scripts'))

import v1_perception_only_field as FIELD  # noqa: E402


class Arguments:
    authorization_id = 'field-auth-20260812'
    confirm_exact = FIELD.CONFIRMATION


class TtyInput(io.StringIO):
    def isatty(self):
        return True


class PerceptionOnlyFieldTest(unittest.TestCase):

    def test_default_source_contract_is_dry_run_and_has_no_publish_api(self):
        source = (PACKAGE_ROOT / 'scripts' / 'v1_perception_only_field.py').read_text(
            encoding='utf-8')
        self.assertIn('V1_PERCEPTION_ONLY_DRY_RUN', source)
        self.assertNotIn('rospy.Publisher', source)
        self.assertNotIn('.publish(', source)
        self.assertNotIn('rospy.ServiceProxy', source)
        self.assertNotIn('SimpleActionClient', source)
        self.assertNotIn('actionlib', source)
        self.assertNotIn('Twist', source)
        self.assertIn("callback_args='/tf'", source)
        self.assertIn("callback_args='/tf_static'", source)
        self.assertIn('validate_tf_edge_evidence(', source)
        self.assertIn("parser.add_argument('--vendor-tf-rules-file'", source)
        self.assertIn(
            "parser.add_argument('--vendor-source-manifest-file'", source)
        self.assertIn(
            "parser.add_argument('--vendor-publisher-pin-file'", source)
        self.assertIn('load_verified_vendor_tf_rules(', source)
        self.assertIn('TF_VENDOR_RUNTIME_BINDING_UNVERIFIED', source)
        self.assertIn("'vendor_contract':", source)
        self.assertIn('_resolve_package_root', source)
        self.assertNotIn('blocker_file=', source)
        self.assertIn("mode.add_argument('--execute-hardware'", source)
        self.assertIn("mode.add_argument('--read-only-precheck'", source)

    @mock.patch.object(FIELD.os, 'name', 'posix')
    def test_hardware_authorization_requires_all_exact_factors(self):
        arguments = Arguments()
        FIELD.authorize_hardware_action(
            arguments, TtyInput(FIELD.CONFIRMATION + '\n'))

        arguments.confirm_exact = 'wrong'
        with self.assertRaises(RuntimeError):
            FIELD.authorize_hardware_action(
                arguments, TtyInput(FIELD.CONFIRMATION + '\n'))
        arguments.confirm_exact = FIELD.CONFIRMATION
        arguments.authorization_id = 'short'
        with self.assertRaises(RuntimeError):
            FIELD.authorize_hardware_action(
                arguments, TtyInput(FIELD.CONFIRMATION + '\n'))
        arguments.authorization_id = 'field-auth-20260812'
        with self.assertRaises(RuntimeError):
            FIELD.authorize_hardware_action(arguments, io.StringIO(
                FIELD.CONFIRMATION + '\n'))
        with self.assertRaises(RuntimeError):
            FIELD.authorize_hardware_action(arguments, TtyInput('wrong\n'))

    def test_exact_sensing_contract_constants(self):
        self.assertEqual((FIELD.SCAN_MIN_HZ, FIELD.SCAN_MAX_HZ), (4.8, 7.2))
        self.assertAlmostEqual(FIELD.math.degrees(FIELD.ANGLE_MIN), -100.0)
        self.assertAlmostEqual(FIELD.math.degrees(FIELD.ANGLE_MAX), 100.0)
        self.assertEqual(FIELD.SCAN_FRAME, 'laser_link')
        self.assertEqual(FIELD.SCAN_SAMPLES, 30)
        self.assertEqual(FIELD.ODOM_SAMPLES, 10)
        message = mock.Mock()
        message._connection_header = {
            'callerid': '/base_link_to_laser_link', 'latching': '1'}
        transform = mock.Mock()
        transform.header.frame_id = 'base_link'
        transform.child_frame_id = 'laser_link'
        transform.header.stamp.to_sec.return_value = 0.0
        transform.transform.translation.x = 0.1
        transform.transform.translation.y = 0.0
        transform.transform.translation.z = 0.08
        transform.transform.rotation.x = 0.0
        transform.transform.rotation.y = 0.0
        transform.transform.rotation.z = 0.0
        transform.transform.rotation.w = 1.0
        observation = FIELD._tf_observation(
            message, transform, '/tf_static', 7, 12.5)
        self.assertEqual(observation.message_id, 7)
        self.assertEqual(observation.authority, '/base_link_to_laser_link')
        self.assertEqual(observation.topic, '/tf_static')
        self.assertTrue(observation.latching)

    @mock.patch.object(FIELD.Path, 'exists', return_value=True)
    @mock.patch.object(FIELD, '_run')
    def test_uart_owner_check_distinguishes_free_owned_and_audit_error(
            self, run, _exists):
        run.return_value = mock.Mock(
            returncode=1, stdout='', stderr='')
        self.assertTrue(FIELD._device_state('/dev/ttyTHS0')['free'])
        run.return_value = mock.Mock(
            returncode=0, stdout='/dev/ttyTHS0: 1234\n', stderr='')
        owned = FIELD._device_state('/dev/ttyTHS0')
        self.assertFalse(owned['free'])
        self.assertEqual(owned['owners'], ['1234'])
        run.return_value = mock.Mock(
            returncode=2, stdout='', stderr='permission denied')
        failed = FIELD._device_state('/dev/ttyTHS0')
        self.assertFalse(failed['free'])
        self.assertEqual(failed['error'], 'permission denied')

    def test_cleanup_and_forbidden_stage_guards_are_present(self):
        source = (PACKAGE_ROOT / 'scripts' / 'v1_perception_only_field.py').read_text(
            encoding='utf-8')
        for token in (
                '/dev/ttyTHS0', '/dev/ydlidar', '/slam_gmapping', '/amcl',
                '/move_base', '/map_server', '/robot_pose_ekf',
                '/cleanup_ros1_navigation_adapter', '/v1_cmd_guard'):
            self.assertIn(token, source)
        self.assertIn("os.killpg(group, signal.SIGINT)", source)
        self.assertIn("stage='scan'", source)
        self.assertIn('validate_tf_edge_evidence(', source)
        self.assertIn('TF publisher graph changed during evidence capture', source)
        self.assertIn('tf_observations', source)
        self.assertIn("if 'cmd_vel' in topic and owners", source)

    def test_hardware_result_target_must_be_new_absolute_file(self):
        with self.assertRaises(FIELD.TfEdgeValidationError) as raised:
            FIELD._load_vendor_tf_rules('', '', '')
        self.assertEqual(
            raised.exception.code, 'TF_VENDOR_CONTRACT_UNVERIFIED')
        with self.assertRaises(ValueError):
            FIELD._validate_result_target('relative.json')
        with self.assertRaises(ValueError):
            FIELD._validate_result_target('')
        with mock.patch.object(FIELD.Path, 'is_absolute', return_value=True), \
                mock.patch.object(FIELD.Path, 'exists', return_value=True), \
                mock.patch.object(FIELD.Path, 'is_dir', return_value=True):
            with self.assertRaises(ValueError):
                FIELD._validate_result_target('/tmp/existing.json')

        arguments = mock.Mock(
            result_file='/tmp/new-result.json',
            vendor_tf_rules_file='/tmp/rules.json',
            vendor_source_manifest_file='/tmp/source.json',
            vendor_publisher_pin_file='/tmp/pin.json')
        verified_rules = mock.Mock()
        verified_rules.evidence_summary.return_value = {'status': 'VERIFIED'}
        with mock.patch.object(FIELD, '_validate_result_target'), \
                mock.patch.object(
                    FIELD, '_load_vendor_tf_rules',
                    return_value=verified_rules), \
                mock.patch.object(FIELD, 'authorize_hardware_action') as auth, \
                mock.patch.object(FIELD, 'read_only_precheck') as precheck, \
                mock.patch.object(FIELD.subprocess, 'Popen') as popen, \
                self.assertRaises(FIELD.TfEdgeValidationError) as raised:
            FIELD.execute_hardware(arguments)
        self.assertEqual(
            raised.exception.code, 'TF_VENDOR_CONTRACT_UNVERIFIED')
        self.assertIn(
            'TF_VENDOR_RUNTIME_BINDING_UNVERIFIED', str(raised.exception))
        auth.assert_not_called()
        precheck.assert_not_called()
        popen.assert_not_called()


if __name__ == '__main__':
    unittest.main()

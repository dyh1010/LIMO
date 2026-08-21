import json
from pathlib import Path
import unittest


PACKAGE_ROOT = Path(__file__).parents[1]
DOCUMENT = PACKAGE_ROOT / 'docs' / 'V1_FIELD_AUTHORIZATION_STATE_MACHINE.md'
TEMPLATE = (
    PACKAGE_ROOT / 'docs' / 'examples'
    / 'v1_field_authorization_checklist_template.json')


class FieldAuthorizationContractTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.source = TEMPLATE.read_text(encoding='utf-8')
        cls.payload = json.loads(cls.source)
        cls.document = DOCUMENT.read_text(encoding='utf-8')

    def test_template_is_not_authority_or_field_evidence(self):
        self.assertEqual(
            self.payload['schema'],
            'limo_v1_field_authorization_checklist/v1')
        self.assertTrue(self.payload['template_only'])
        self.assertTrue(self.payload['approval_packet_only'])
        self.assertFalse(self.payload['runtime_authorization_validator'])
        self.assertFalse(self.payload['real_machine_evidence'])
        self.assertEqual(self.payload['status'], 'NOT_RUN')
        self.assertFalse(self.payload['execution_ready'])
        self.assertEqual(self.payload['decision'], 'BLOCKED')
        self.assertFalse(
            self.payload['current_boundary'][
                'dedicated_field_orchestrator_present'])
        self.assertFalse(
            self.payload['current_boundary'][
                'manual_edit_can_set_execution_ready'])
        self.assertIn(
            'checklist is an offline approval packet',
            self.document)
        self.assertIn(
            'It is not a runtime authorization validator',
            self.document)

    def test_three_grants_are_independent_and_upgrade_is_never_inherited(self):
        policy = self.payload['grant_policy']
        classes = [
            'hardware_read_only',
            'zero_motion_localization',
            'real_motion',
        ]
        self.assertEqual(policy['classes'], classes)
        self.assertEqual(set(self.payload['grants']), set(classes))
        self.assertEqual(set(self.payload['stage_contracts']), set(classes))
        self.assertTrue(policy['independent_grants_required'])
        self.assertFalse(policy['upgrade_inheritance_allowed'])
        self.assertFalse(policy['class_substitution_allowed'])
        self.assertTrue(
            policy['fresh_bundle_required_for_every_stage_entry'])
        self.assertFalse(
            self.payload['current_boundary'][
                'prior_stage_pass_is_field_authority'])
        self.assertEqual(
            policy['required_grants_by_requested_stage'], {
                'hardware_read_only': ['hardware_read_only'],
                'zero_motion_localization': [
                    'hardware_read_only', 'zero_motion_localization'],
                'real_motion': classes,
            })

    def test_every_grant_has_identity_scope_time_and_one_use_fields(self):
        required = set(self.payload['grant_policy']['required_grant_fields'])
        expected = {
            'authorization_class', 'authorization_id', 'approval_reference',
            'boot_id', 'session_id', 'robot_id', 'operator',
            'observer_at_physical_stop', 'scope', 'issued_at_utc',
            'expires_at_utc', 'one_use', 'consumed', 'revoked', 'fresh',
        }
        self.assertEqual(required, expected)
        self.assertTrue(self.payload['grant_policy']['one_use_required'])
        self.assertTrue(self.payload['grant_policy']['atomic_consume_required'])
        self.assertTrue(
            self.payload['grant_policy'][
                'recheck_before_boundary_required'])
        freshness_fields = {
            'issued_not_in_future', 'not_expired', 'boot_matches',
            'session_matches', 'robot_matches', 'scope_matches',
        }
        for name, grant in self.payload['grants'].items():
            self.assertTrue(required.issubset(grant))
            self.assertEqual(grant['authorization_class'], name)
            self.assertEqual(set(grant['freshness_checks']), freshness_fields)
            self.assertIsNone(grant['one_use'])
            self.assertIsNone(grant['consumed'])
            self.assertIsNone(grant['revoked'])
            self.assertFalse(grant['fresh'])
            self.assertFalse(grant['record_complete'])
            self.assertFalse(grant['grant_valid'])
            self.assertEqual(grant['decision'], 'BLOCKED')

    def test_fail_closed_reasons_cover_missing_expiry_reuse_and_drift(self):
        reasons = set(self.payload['grant_policy']['fail_closed_reasons'])
        required = {
            'missing_required_field',
            'approval_reference_missing_or_unverified',
            'issued_in_future',
            'expired',
            'boot_mismatch',
            'session_mismatch',
            'robot_mismatch',
            'operator_missing',
            'observer_missing',
            'scope_mismatch',
            'one_use_not_true',
            'already_consumed',
            'revoked',
            'lower_stage_pass_substitution',
            'grant_class_substitution',
            'physical_boundary_incomplete',
            'dedicated_field_orchestrator_missing',
        }
        self.assertEqual(reasons, required)

    def test_all_stage_contracts_remain_not_run_and_blocked(self):
        for name, stage in self.payload['stage_contracts'].items():
            self.assertEqual(
                stage['required_grant_classes'],
                self.payload['grant_policy'][
                    'required_grants_by_requested_stage'][name])
            self.assertTrue(stage['allowed_operation_ids'])
            self.assertTrue(stage['forbidden_operation_ids'])
            self.assertTrue(stage['physical_requirements'])
            self.assertEqual(stage['current_status'], 'NOT_RUN')
            self.assertFalse(stage['execution_ready'])
            self.assertEqual(stage['decision'], 'BLOCKED')
        summary = self.payload['validation_summary']
        self.assertTrue(all(
            value is False
            for key, value in summary.items()
            if key not in {'decision'}))
        self.assertEqual(summary['decision'], 'BLOCKED')

    def test_physical_stop_is_independent_of_software(self):
        boundary = self.payload['physical_boundary']
        self.assertIn('observer_at_physical_stop_present', boundary)
        self.assertIn('physical_estop_or_main_switch_identified', boundary)
        self.assertIn('physical_stop_path_checked_for_session', boundary)
        self.assertIn('energy_isolation_path_known', boundary)
        self.assertFalse(boundary['software_stop_replaces_physical_estop'])
        self.assertFalse(boundary['complete'])
        self.assertIn(
            'Software stop, cancellation,\nzero output, READY loss, or '
            'process shutdown supplements but never replaces',
            self.document)

    def test_existing_local_gates_are_explicitly_not_grant_validators(self):
        normalized = ' '.join(self.document.split())
        for token in (
                '`hardware_authorization_id` is a launch argument',
                'does not validate issuer',
                '`/v1_localization_manager/authorize_initial_pose` is a ROS '
                'Trigger',
                'launch/runtime booleans',
                'A true value is not evidence of user approval',
                'a prior field PASS',
                'not an authorization'):
            self.assertIn(token, normalized)
        self.assertIn(
            'No such orchestrator exists in the current release',
            normalized)

    def test_template_has_no_ros_or_movement_invocation_surface(self):
        lowered = self.source.lower()
        for forbidden in (
                'twist', 'cmd_vel', 'publisher', 'service', 'action',
                '/v1/navigation/goal', 'roslaunch', 'rosrun',
                'rosservice call', 'simpleactionclient'):
            self.assertNotIn(forbidden, lowered)


if __name__ == '__main__':
    unittest.main()

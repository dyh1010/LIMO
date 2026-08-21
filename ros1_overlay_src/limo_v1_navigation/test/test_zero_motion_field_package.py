import csv
import json
from pathlib import Path
import unittest


PACKAGE_ROOT = Path(__file__).parents[1]
DOCUMENT = PACKAGE_ROOT / 'docs' / 'V1_ZERO_MOTION_FIELD_PREPARATION.md'
CONVERGENCE_TEMPLATE = (
    PACKAGE_ROOT / 'docs' / 'examples'
    / 'v1_zero_motion_convergence_template.csv')
ENDPOINT_TEMPLATE = (
    PACKAGE_ROOT / 'docs' / 'examples'
    / 'v1_endpoint_measurement_template.json')
ENDPOINT_EVIDENCE_TEMPLATE = (
    PACKAGE_ROOT / 'docs' / 'examples'
    / 'v1_endpoint_evidence_manifest_template.json')
REPEATABILITY_PROVENANCE_TEMPLATE = (
    PACKAGE_ROOT / 'docs' / 'examples'
    / 'v1_repeatability_provenance_manifest_template.json')
AVOIDANCE_TEMPLATE = (
    PACKAGE_ROOT / 'docs' / 'examples'
    / 'v1_avoidance_evidence_worksheet_template.json')
ABSOLUTE_LOCALIZATION_TEMPLATE = (
    PACKAGE_ROOT / 'docs' / 'examples'
    / 'v1_zero_motion_absolute_localization_evidence_template.json')


class ZeroMotionFieldPackageTest(unittest.TestCase):

    def test_document_keeps_hardware_and_motion_authority_separate(self):
        source = DOCUMENT.read_text(encoding='utf-8')
        self.assertIn('does not authorize connecting to the\nrobot', source)
        self.assertIn('no physical motion', source)
        self.assertIn('Fresh hardware/read-only authorization', source)
        self.assertIn('A separate explicit authorization for that exact run',
                      source)
        self.assertIn('do not replace the\nphysical e-stop', source)
        self.assertIn('Lift the wheels/tracks clear of the floor', source)
        self.assertIn('Do not issue `2D Nav Goal`', source)
        self.assertIn(
            'Do not manually call or loop `/request_nomotion_update`',
            source)
        self.assertIn('manager is the sole scheduler', source)
        self.assertIn('isolated sensing-only procedure', source)
        self.assertIn('Start localization-only', source)
        self.assertIn('allow_nonzero=false', source)
        self.assertIn('enable_goal_gateway=false', source)
        self.assertIn('allow_goal_forwarding=false', source)

    def test_document_freezes_capture_and_accuracy_boundaries(self):
        source = DOCUMENT.read_text(encoding='utf-8')
        self.assertIn('subscribers only', source)
        self.assertIn('exclusive new timestamped', source)
        self.assertIn('does not provide an authoritative timestamp/latency',
                      source)
        self.assertIn('derive a separately checksummed `x,y,yaw` CSV', source)
        self.assertIn('V1_DIAGNOSTIC_CAPTURE_PASS', source)
        self.assertIn('--duration-s 120', source)
        self.assertIn('`3/3` reach READY within `45 s`', source)
        self.assertIn('cov_xx/cov_yy/cov_yawyaw <= 0.010', source)
        self.assertIn('READY is a convergence/chain gate', source)
        self.assertIn('Repeatability is spread', source)
        self.assertIn('AMCL estimation error', source)
        self.assertIn('navigation control endpoint error', source)
        self.assertIn('physical total endpoint error', source)
        self.assertIn('v1_endpoint_evidence_manifest_template.json', source)
        self.assertIn(
            'v1_repeatability_provenance_manifest_template.json', source)
        self.assertIn(
            'v1_avoidance_evidence_worksheet_template.json', source)
        self.assertIn(
            'v1_zero_motion_absolute_localization_evidence_template.json',
            source)
        self.assertIn('yaw_not_thresholded=true', source)
        self.assertIn('PASS in any one class implies', source)
        self.assertIn('no PASS in another', source)
        self.assertIn('response_s = t1 - t0', source)
        self.assertIn('one rosbag recorder', source)

    def test_zero_motion_absolute_localization_is_independent_and_provenanced(self):
        source = ABSOLUTE_LOCALIZATION_TEMPLATE.read_text(encoding='utf-8')
        payload = json.loads(source)
        self.assertEqual(
            payload['schema'],
            'limo_v1_zero_motion_absolute_localization_evidence/v1')
        self.assertTrue(payload['template_only'])
        self.assertFalse(payload['real_machine_evidence'])
        self.assertEqual(payload['status'], 'NOT_RUN')
        self.assertTrue(payload['zero_motion_required'])
        self.assertEqual(payload['records'], [])
        contract = payload['measurement_contract']
        self.assertEqual(
            contract['error_definition'],
            'absolute_localization_error = surveyed_truth_pose - '
            'stationary_amcl_pose')
        self.assertEqual(contract['position_threshold_m'], 0.1)
        self.assertTrue(contract['yaw_not_thresholded'])
        self.assertFalse(contract['covariance_proves_absolute_accuracy'])
        self.assertFalse(contract['repeatability_proves_absolute_accuracy'])
        self.assertTrue(all(
            value is False
            for value in payload['pass_independence'].values()))
        record = payload['record_template']
        self.assertNotIn('request_id', record)
        self.assertIn('surveyed_mark', record)
        self.assertIn('robot_reference_point', record['surveyed_mark'])
        self.assertIn('heading_fixture', record['surveyed_mark'])
        self.assertEqual(record['ground_truth']['frame_id'], 'map')
        for field in (
                'instrument', 'instrument_serial', 'measurement_method',
                'raw_survey_path', 'raw_survey_sha256'):
            self.assertIn(field, record['ground_truth'])
        self.assertIn('record_sha256', record['instrument_calibration'])
        self.assertEqual(record['frame_transform']['target_frame_id'], 'map')
        self.assertIn(
            'transform_record_sha256', record['frame_transform'])
        self.assertEqual(set(record['raw_capture']), {
            'jsonl_path', 'jsonl_sha256',
        })
        self.assertIn('ready_remained_true', record['ready_window'])
        self.assertIn(
            'chain_health_remained_valid', record['ready_window'])
        self.assertIn('status_evidence_sha256', record['ready_window'])
        self.assertEqual(record['stationary_amcl_pose']['frame_id'], 'map')
        self.assertIn(
            'sample_artifact_sha256', record['stationary_amcl_pose'])
        error = record['absolute_localization_error']
        self.assertEqual(error['position_threshold_m'], 0.1)
        self.assertTrue(error['yaw_not_thresholded'])
        lowered = source.lower()
        for forbidden in (
                'geometry_msgs/posestamped', 'twist', 'cmd_vel',
                '/v1/navigation/goal', 'rosservice call', 'roslaunch'):
            self.assertNotIn(forbidden, lowered)

    def test_convergence_template_has_reproducible_provenance_and_metrics(self):
        with CONVERGENCE_TEMPLATE.open(
                newline='', encoding='utf-8') as stream:
            reader = csv.reader(stream)
            header = next(reader)
        self.assertEqual(header, [
            'session_id', 'run_id', 'robot_id', 'operator',
            'authorization_id', 'authorization_scope', 'overlay_revision',
            'active_map_id', 'map_yaml_sha256', 'amcl_sha256',
            'preflight_evidence_path', 'preflight_sha256', 'capture_path',
            'capture_sha256',
            'initial_pose_accepted_wall_time',
            'first_new_amcl_wall_time', 'ready_wall_time', 'convergence_s',
            'nomotion_successes', 'nomotion_failures', 'max_covariance_x',
            'max_covariance_y', 'max_covariance_yaw', 'stable_samples',
            'stable_duration_s', 'repeatability_csv_path',
            'repeatability_report_path', 'repeatability_report_sha256',
            'final_state', 'final_reason', 'result',
        ])

    def test_endpoint_template_matches_offline_report_input_without_evidence_claim(self):
        payload = json.loads(ENDPOINT_TEMPLATE.read_text(encoding='utf-8'))
        self.assertEqual(set(payload), {
            'schema', 'active_map_id', 'goal', 'amcl_final',
            'ground_truth_final',
        })
        self.assertEqual(
            payload['schema'], 'limo_v1_endpoint_measurement/v1')
        self.assertEqual(
            set(payload['goal']), {'x', 'y', 'yaw'})
        source = ENDPOINT_TEMPLATE.read_text(encoding='utf-8').lower()
        self.assertNotIn('real_machine_evidence', source)
        self.assertNotIn('overall_passed', source)

    def test_endpoint_companion_binds_trial_truth_stop_and_report_evidence(self):
        payload = json.loads(
            ENDPOINT_EVIDENCE_TEMPLATE.read_text(encoding='utf-8'))
        self.assertEqual(
            payload['schema'], 'limo_v1_endpoint_evidence_manifest/v1')
        self.assertTrue(payload['template_only'])
        self.assertFalse(payload['real_machine_evidence'])
        self.assertEqual(payload['status'], 'NOT_RUN')
        self.assertTrue(payload['yaw_not_thresholded'])
        self.assertEqual(payload['trials'], [])
        trial = payload['trial_template']
        for field in ('session_id', 'trial_id', 'request_id'):
            self.assertIn(field, trial)
        self.assertEqual(trial['goal_evidence']['frame_id'], 'map')
        self.assertEqual(trial['amcl_final_evidence']['frame_id'], 'map')
        self.assertEqual(trial['ground_truth_evidence']['frame_id'], 'map')
        for field in (
                'instrument', 'calibration_id', 'measurement_method',
                'robot_reference_point', 'raw_sha256'):
            self.assertIn(field, trial['ground_truth_evidence'])
        self.assertIn('start_time', trial['stationary_stop_window'])
        self.assertIn('end_time', trial['stationary_stop_window'])
        self.assertIn(
            'command_evidence_sha256', trial['stationary_stop_window'])
        self.assertEqual(
            trial['derived_report']['schema'],
            'limo_v1_endpoint_error_report/v1')
        self.assertTrue(trial['yaw_not_thresholded'])
        self.assertTrue(all(
            value is False
            for value in payload['pass_independence'].values()))

    def test_repeatability_manifest_preserves_source_and_conversion_chain(self):
        payload = json.loads(
            REPEATABILITY_PROVENANCE_TEMPLATE.read_text(encoding='utf-8'))
        self.assertEqual(
            payload['schema'],
            'limo_v1_repeatability_provenance_manifest/v1')
        self.assertEqual(payload['records'], [])
        self.assertFalse(payload['absolute_accuracy_proven'])
        self.assertEqual(set(payload['allowed_measurement_classes']), {
            'within_run_stationary_jitter',
            'cross_relocalization_repeatability',
        })
        record = payload['record_template']
        self.assertEqual(set(record['source_capture']), {
            'jsonl_path', 'jsonl_sha256',
        })
        for field in ('tool', 'version', 'tool_sha256', 'exact_command'):
            self.assertIn(field, record['conversion'])
        self.assertEqual(record['derived_csv']['header'], 'x,y,yaw')
        self.assertIn('sha256', record['derived_csv'])
        self.assertIn('id', record['fixed_mark'])
        self.assertIn('ready_remained_true', record['ready_evidence'])
        self.assertIn('status_sha256', record['ready_evidence'])
        self.assertTrue(all(
            value is False
            for value in payload['pass_independence'].values()))

    def test_avoidance_worksheet_separates_static_and_dynamic_evidence(self):
        payload = json.loads(
            AVOIDANCE_TEMPLATE.read_text(encoding='utf-8'))
        self.assertEqual(
            payload['schema'], 'limo_v1_avoidance_evidence_worksheet/v1')
        self.assertTrue(payload['motion_authorization_required'])
        self.assertFalse(payload['software_stop_is_physical_estop'])
        self.assertEqual(payload['static_avoidance']['trials'], [])
        self.assertEqual(payload['dynamic_avoidance']['trials'], [])
        self.assertEqual(
            payload['static_avoidance']['required_valid_trials'], 3)
        self.assertEqual(
            payload['dynamic_avoidance']['required_valid_trials'], 5)
        self.assertEqual(
            payload['dynamic_avoidance']['acceptance'][
                'maximum_response_s'], 0.8)
        timing = payload['dynamic_avoidance']['timing_contract']
        self.assertEqual(timing['clock_domain'], 'single_rosbag_record_time')
        self.assertIn('full-scan geometry', timing['t0_definition'])
        self.assertTrue(timing['pre_t0_nonzero_command_required'])
        self.assertEqual(timing['pre_t0_nonzero_window_s'], 0.25)
        self.assertIn('finite planar nonzero',
                      timing['t0_eligibility_definition'])
        self.assertIn('exactly planar zero', timing['t1_definition'])
        self.assertEqual(timing['response_formula'], 'response_s = t1 - t0')
        self.assertEqual(timing['zero_hold_s'], 0.25)
        self.assertEqual(timing['clock_mismatch_result'], 'BLOCKED')
        mode_topics = payload['mode_specific_required_rosbag_topics']
        self.assertIn('/v1/driver_cmd_vel', mode_topics['native'])
        self.assertIn('/v1/navigation/status', mode_topics['native'])
        self.assertNotIn('/v1/cmd_guard/stop_latched',
                         mode_topics['integrated'])
        self.assertEqual(mode_topics['integrated'], [
            '/cleanup/navigation/bridge_status',
            '/cleanup/base/driver_cmd_vel',
        ])
        self.assertEqual(
            payload['dynamic_avoidance']['allowed_driver_command_topics'], {
                'native': '/v1/driver_cmd_vel',
                'integrated': '/cleanup/base/driver_cmd_vel',
            })
        for section in ('static_avoidance', 'dynamic_avoidance'):
            trial = payload[section]['trial_template']
            for field in (
                    'session_id', 'trial_id', 'request_id',
                    'raw_rosbag_sha256', 'contact_detected',
                    'minimum_clearance_m', 'result', 'block_reason'):
                self.assertIn(field, trial)
        static_trial = payload['static_avoidance']['trial_template']
        self.assertIn('goal_active_during_encounter', static_trial)
        self.assertIn('robot_approached_obstacle', static_trial)
        dynamic_trial = payload['dynamic_avoidance']['trial_template']
        self.assertIn('request_active_at_t0', dynamic_trial)
        self.assertIn('pre_t0_command_nonzero', dynamic_trial)
        self.assertIn('pre_t0_command_evidence_sha256', dynamic_trial)
        self.assertTrue(all(
            value is False
            for value in payload['pass_independence'].values()))


if __name__ == '__main__':
    unittest.main()

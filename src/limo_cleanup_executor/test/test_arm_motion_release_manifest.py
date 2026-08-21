import ast
import copy
import hashlib
import json
import math
import tempfile
import unittest
from pathlib import Path

import limo_cleanup_executor.arm_motion_release_manifest as manifest_module
from limo_cleanup_executor.arm_motion_release_manifest import (
    ArmMotionManifestError,
    REQUIRED_POSE_ROLES,
    evaluate_manifest,
    load_manifest,
    loads_manifest,
)


ROOT = Path(__file__).parents[1]
MODULE = (
    ROOT / 'limo_cleanup_executor' / 'arm_motion_release_manifest.py')
EXAMPLE = ROOT / 'config' / 'arm_motion_release.example.json'
HASH = 'A' * 64


def complete_manifest():
    joint_limits = [[-170.0, 170.0] for unused in range(6)]
    project_limits = [[-160.0, 160.0] for unused in range(6)]
    poses = []
    for index, role in enumerate(REQUIRED_POSE_ROLES):
        poses.append({
            'name': '{}_pose'.format(role),
            'role': role,
            'joint_angles_deg': [float(index)] * 6,
            'tool_revision': 'tool-r1',
            'purpose': 'fixed V3 {} endpoint'.format(role),
            'minimum_limit_margin_deg': 10.0,
            'collision_review_sha256': HASH,
            'cable_envelope_review_sha256': HASH,
        })
    return {
        'schema_version': 2,
        'arm_model': 'myCobot 280 M5',
        'release_binding': {
            'runtime_release_id': 'arm-runtime-release-r1',
            'release_manifest_sha256': HASH,
        },
        'source_binding': {
            'interface_contract_sha256': HASH,
            'acceptance_contract_sha256': HASH,
            'gateway_policy_sha256': HASH,
            'collision_model_sha256': HASH,
        },
        'tool': {
            'model': 'final-tool',
            'revision': 'tool-r1',
            'assembly_sha256': HASH,
            'mass_kg': 0.25,
            'center_of_mass_mm': [0.0, 0.0, 40.0],
            'inertia_kg_m2': [0.01, 0.01, 0.01, 0.0, 0.0, 0.0],
        },
        'coordinate_contract': {
            'reference_frame': 0,
            'reference_frame_id': 'arm_base_link',
            'end_type': 1,
            'endpoint_frame_id': 'gripper_tcp',
            'controller_tool_reference': [
                0.0, 0.0, 80.0, 0.0, 0.0, 0.0],
            'flange_to_tcp': [0.0, 0.0, 80.0, 0.0, 0.0, 0.0],
            'translation_uncertainty_mm': 0.5,
            'rotation_uncertainty_deg': 0.2,
            'controller_readback_sha256': HASH,
            'tcp_measurement_sha256': HASH,
            'base_extrinsic_sha256': HASH,
        },
        'controller_state': {
            'controller_connected': 1,
            'power_on': 1,
            'moving': 0,
            'paused': 0,
            'error_code': 0,
            'all_servos_enabled': 1,
            'fresh_mode': 0,
            'stationary_samples': 3,
            'stationary_dwell_s': 0.2,
            'stationary_joint_tolerance_deg': 0.01,
            'state_max_age_s': 0.25,
            'readback_sha256': HASH,
        },
        'motion_profile': {
            'profile_id': 'profile-r1',
            'tool_revision': 'tool-r1',
            'acceleration_profile_manifest_sha256': HASH,
            'acceleration_profile_runtime_release_id': (
                'arm-runtime-release-r1'),
            'max_speed_grade': 5,
            'approved_speed_grades': [5],
            'approved_tcp_modes': [0],
            'max_joint_speed_deg_s': 10.0,
            'max_tcp_speed_mm_s': 25.0,
            'max_joint_acceleration_deg_s2': 20.0,
            'max_tcp_acceleration_mm_s2': 50.0,
            'max_joint_stop_distance_deg': 2.0,
            'max_tcp_stop_distance_mm': 3.0,
            'path_mode_review_sha256': HASH,
            'approval_sha256': HASH,
            'cases': [{
                'case_id': 'grade5-load1-fixed-poses',
                'speed_grade': 5,
                'tcp_mode': 0,
                'load_case': 'final tool plus approved empty bottle',
                'pose_set': 'fixed V3 pose set r1',
                'measured_joint_speed_deg_s': 8.0,
                'measured_tcp_speed_mm_s': 20.0,
                'measured_joint_acceleration_deg_s2': 15.0,
                'measured_tcp_acceleration_mm_s2': 40.0,
                'measured_joint_stop_distance_deg': 1.0,
                'measured_tcp_stop_distance_mm': 2.0,
                'sample_count': 3,
                'evidence_sha256': HASH,
            }],
        },
        'real_backend_gate': {
            'bounded_call_capability': {
                'enforced': True,
                'artifact': 'execution_safety.json',
                'artifact_sha256': HASH,
            },
            'deadline_enforcement_capability': {
                'enforced': True,
                'artifact': 'execution_safety.json',
                'artifact_sha256': HASH,
            },
            'native_cancel_capability': {
                'enforced': True,
                'artifact': 'execution_safety.json',
                'artifact_sha256': HASH,
            },
            'independent_stop_channel_capability': {
                'enforced': True,
                'artifact': 'execution_safety.json',
                'artifact_sha256': HASH,
            },
            'persistent_safety_latch_capability': {
                'enforced': True,
                'artifact': 'execution_safety.json',
                'artifact_sha256': HASH,
            },
        },
        'joint_limits': {
            'required_fresh_mode': 0,
            'controller_deg': joint_limits,
            'project_deg': project_limits,
            'required_named_pose_margin_deg': 10.0,
            'controller_readback_sha256': HASH,
            'collision_review_sha256': HASH,
        },
        'cartesian_limits': {
            'reference_frame_id': 'arm_base_link',
            'endpoint_frame_id': 'gripper_tcp',
            'bounds': [
                [50.0, 250.0],
                [-150.0, 150.0],
                [100.0, 350.0],
                [-170.0, 170.0],
                [-170.0, 170.0],
                [-170.0, 170.0],
            ],
            'workspace_review_sha256': HASH,
            'ik_collision_review_sha256': HASH,
        },
        'named_poses': poses,
        'review': {
            'review_id': 'review-r1',
            'reviewer': 'safety-reviewer',
            'reviewed_at_utc': '2026-08-14T12:00:00Z',
            'approval_sha256': HASH,
        },
        'artifacts': [{
            'path': 'placeholder.txt',
            'sha256': HASH,
            'claims': ['manifest.review.approval_sha256'],
        }],
    }


def execution_safety_evidence():
    command_id = 'cmd-001'
    return {
        'schema_version': 1,
        'runtime_release_id': 'arm-runtime-release-r1',
        'release_manifest_sha256': HASH.lower(),
        'acceleration_profile_manifest_sha256': HASH.lower(),
        'approved_speed_grades': [5],
        'vendor_call_deadlines': {
            'deadline_enforced': True,
            'call_deadlines_s': {
                'close': 0.5,
                'get_angles': 0.5,
                'get_coords': 0.5,
                'get_end_type': 0.5,
                'get_error_information': 0.5,
                'get_fresh_mode': 0.5,
                'get_joint_max': 0.5,
                'get_joint_min': 0.5,
                'get_reference_frame': 0.5,
                'get_tool_reference': 0.5,
                'is_all_servo_enable': 0.5,
                'is_controller_connected': 0.5,
                'is_moving': 0.5,
                'is_paused': 0.5,
                'is_power_on': 0.5,
                'send_angles': 1.0,
                'send_coords': 1.0,
                'stop': 0.25,
            },
        },
        'execution_domains': {
            'motion_domain': 'motion-worker',
            'stop_domain': 'stop-worker',
            'independent_lock_domains': True,
        },
        'cancellation_capability': {
            'native_transport_cancel_enforced': True,
            'python_timeout_thread_used': False,
            'cancel_deadline_s': 0.25,
            'cancel_completed': True,
            'cancel_elapsed_s': 0.1,
            'cancelled_send_cannot_commit': True,
        },
        'hung_motion_send_probe': {
            'command_id': command_id,
            'send_hung': True,
            'stop_completed': True,
            'stop_elapsed_s': 0.1,
            'stop_deadline_s': 0.25,
            'stop_completed_before_send_release': True,
        },
        'persistent_safety_latch': {
            'exclusive_create_enforced': True,
            'atomic_update_enforced': True,
            'generation_chain_enforced': True,
            'restart_restored_active_latch': True,
            'old_session_clear_rejected': True,
            'external_clearance_validator_required': True,
            'local_hashes_claim_authenticity': False,
        },
        'trace': {
            'command_id': command_id,
            'result_command_id': command_id,
            'timeout_command_id': command_id,
            'stop_command_id': command_id,
            'stationary_command_id': command_id,
            'ack_command_id': command_id,
            'interrupted_result_success': False,
            'stop_return_used_as_stationary_evidence': False,
            'stationary_samples': [
                {'sample_id': 'stationary-1', 'time_s': 1.0},
                {'sample_id': 'stationary-2', 'time_s': 1.1},
                {'sample_id': 'stationary-3', 'time_s': 1.2},
            ],
            'stationary_dwell_s': 0.2,
            'command_started_at_s': 0.0,
            'timeout_at_s': 0.5,
            'stop_requested_at_s': 0.5,
            'stop_completed_at_s': 0.6,
            'stationary_proven_at_s': 1.2,
            'ack_at_s': 1.3,
            'result_at_s': 1.4,
        },
    }


def acceleration_profile_evidence():
    return {
        'schema_version': 1,
        'runtime_release_id': 'arm-runtime-release-r1',
        'profile_id': 'profile-r1',
        'tool_revision': 'tool-r1',
        'max_speed_grade': 5,
        'approved_speed_grades': [5],
        'approved_tcp_modes': [0],
        'max_joint_speed_deg_s': 10.0,
        'max_tcp_speed_mm_s': 25.0,
        'max_joint_acceleration_deg_s2': 20.0,
        'max_tcp_acceleration_mm_s2': 50.0,
        'max_joint_stop_distance_deg': 2.0,
        'max_tcp_stop_distance_mm': 3.0,
    }


def runtime_release_evidence(acceleration_hash):
    return {
        'schema_version': 1,
        'runtime_release_id': 'arm-runtime-release-r1',
        'arm_model': 'myCobot 280 M5',
        'motion_profile_id': 'profile-r1',
        'acceleration_profile_manifest_sha256': acceleration_hash,
        'acceleration_profile_runtime_release_id': 'arm-runtime-release-r1',
        'bounded_call_capability': True,
        'deadline_enforcement_capability': True,
        'native_cancel_capability': True,
        'independent_stop_channel_capability': True,
        'persistent_safety_latch_capability': True,
    }


def _json_bytes(value):
    return json.dumps(
        value, sort_keys=True, separators=(',', ':')).encode('utf-8')


def write_bound_release_fixture(root, evidence=None):
    artifact_root = Path(root) / 'artifacts'
    artifact_root.mkdir()
    acceleration_path = artifact_root / 'acceleration_profile.json'
    acceleration_bytes = _json_bytes(acceleration_profile_evidence())
    acceleration_path.write_bytes(acceleration_bytes)
    acceleration_hash = hashlib.sha256(acceleration_bytes).hexdigest()
    runtime_path = artifact_root / 'runtime_release.json'
    runtime_bytes = _json_bytes(runtime_release_evidence(acceleration_hash))
    runtime_path.write_bytes(runtime_bytes)
    runtime_hash = hashlib.sha256(runtime_bytes).hexdigest()
    evidence_path = artifact_root / 'execution_safety.json'
    if evidence is None:
        evidence = execution_safety_evidence()
    evidence['release_manifest_sha256'] = runtime_hash
    evidence['acceleration_profile_manifest_sha256'] = acceleration_hash
    evidence['approved_speed_grades'] = [5]
    evidence_bytes = _json_bytes(evidence)
    evidence_path.write_bytes(evidence_bytes)
    evidence_hash = hashlib.sha256(evidence_bytes).hexdigest()
    ordinary_path = artifact_root / 'review.txt'
    ordinary_path.write_bytes(b'reviewed offline artifact\n')
    ordinary_hash = hashlib.sha256(ordinary_path.read_bytes()).hexdigest()

    manifest = complete_manifest()

    def declared_hash_paths(value, label='manifest'):
        paths = []
        if type(value) is dict:
            for key, item in value.items():
                child = '{}.{}'.format(label, key)
                if key.endswith('_sha256'):
                    paths.append(child)
                paths.extend(declared_hash_paths(item, child))
        elif type(value) is list:
            for index, item in enumerate(value):
                paths.extend(declared_hash_paths(
                    item, '{}[{}]'.format(label, index)))
        return paths
    def replace_hashes(value):
        if type(value) is dict:
            for key, item in value.items():
                if key.endswith('_sha256'):
                    value[key] = ordinary_hash
                else:
                    replace_hashes(item)
        elif type(value) is list:
            for item in value:
                replace_hashes(item)

    replace_hashes(manifest)
    for capability in manifest['real_backend_gate'].values():
        capability.update({
            'artifact': 'execution_safety.json',
            'artifact_sha256': evidence_hash,
        })
    manifest['motion_profile'][
        'acceleration_profile_manifest_sha256'] = acceleration_hash
    manifest['release_binding']['release_manifest_sha256'] = runtime_hash
    manifest['artifacts'] = [
        {
            'path': 'review.txt',
            'sha256': ordinary_hash,
            'claims': [
                path for path in declared_hash_paths(manifest)
                if not path.startswith('manifest.artifacts[')
                and not path.startswith('manifest.real_backend_gate.')
                and path != (
                    'manifest.motion_profile.'
                    'acceleration_profile_manifest_sha256')
                and path != (
                    'manifest.release_binding.release_manifest_sha256')
            ],
        },
        {
            'path': 'execution_safety.json',
            'sha256': evidence_hash,
            'claims': [
                'manifest.real_backend_gate.{}.artifact_sha256'.format(key)
                for key in (
                    'bounded_call_capability',
                    'deadline_enforcement_capability',
                    'native_cancel_capability',
                    'independent_stop_channel_capability',
                    'persistent_safety_latch_capability',
                )
            ],
        },
        {
            'path': 'acceleration_profile.json',
            'sha256': acceleration_hash,
            'claims': [
                'manifest.motion_profile.'
                'acceleration_profile_manifest_sha256',
            ],
        },
        {
            'path': 'runtime_release.json',
            'sha256': runtime_hash,
            'claims': [
                'manifest.release_binding.release_manifest_sha256',
            ],
        },
    ]
    return manifest, artifact_root


def rewrite_execution_safety_artifact(manifest, artifact_root, evidence_bytes):
    evidence_path = artifact_root / 'execution_safety.json'
    evidence_path.write_bytes(evidence_bytes)
    old_hash = manifest['real_backend_gate'][
        'bounded_call_capability']['artifact_sha256']
    new_hash = hashlib.sha256(evidence_bytes).hexdigest()
    for capability in manifest['real_backend_gate'].values():
        capability['artifact_sha256'] = new_hash
    for record in manifest['artifacts']:
        if record['sha256'] == old_hash:
            record['sha256'] = new_hash
            break
    return new_hash


def rewrite_acceleration_profile_artifact(
        manifest, artifact_root, evidence_bytes):
    path = artifact_root / 'acceleration_profile.json'
    path.write_bytes(evidence_bytes)
    old_hash = manifest['motion_profile'][
        'acceleration_profile_manifest_sha256']
    new_hash = hashlib.sha256(evidence_bytes).hexdigest()
    manifest['motion_profile'][
        'acceleration_profile_manifest_sha256'] = new_hash
    for record in manifest['artifacts']:
        if record['sha256'] == old_hash:
            record['sha256'] = new_hash
            break
    return new_hash


def rewrite_runtime_release_artifact(
        manifest, artifact_root, evidence_bytes):
    path = artifact_root / 'runtime_release.json'
    path.write_bytes(evidence_bytes)
    old_hash = manifest['release_binding']['release_manifest_sha256']
    new_hash = hashlib.sha256(evidence_bytes).hexdigest()
    manifest['release_binding']['release_manifest_sha256'] = new_hash
    for record in manifest['artifacts']:
        if record['sha256'] == old_hash:
            record['sha256'] = new_hash
            break
    return new_hash


class ArmMotionReleaseManifestTest(unittest.TestCase):
    def test_module_uses_python38_syntax(self):
        ast.parse(
            MODULE.read_text(encoding='utf-8'),
            filename=str(MODULE),
            feature_version=(3, 8),
        )

    def test_checked_in_example_is_strictly_blocked(self):
        report = evaluate_manifest(load_manifest(EXAMPLE), artifact_root=None)
        self.assertFalse(report['release_ready'])
        self.assertGreaterEqual(len(report['blocking_issues']), 25)
        joined = '\n'.join(report['blocking_issues'])
        for token in (
                'acceleration', 'joint_limits', 'coordinate_contract',
                'named_poses', 'review.'):
            self.assertIn(token, joined)

    def test_complete_manifest_passes_and_normalizes_hashes(self):
        with tempfile.TemporaryDirectory() as root:
            manifest, artifact_root = write_bound_release_fixture(root)
            report = evaluate_manifest(
                manifest, artifact_root=artifact_root)
            self.assertTrue(report['release_ready'])
            self.assertEqual(report['blocking_issues'], [])
            self.assertEqual(
                report['normalized_manifest']['tool']['assembly_sha256'],
                manifest['tool']['assembly_sha256'].lower(),
            )

    def test_release_ready_is_derived_and_cannot_be_asserted(self):
        manifest = complete_manifest()
        manifest['release_ready'] = True
        with self.assertRaisesRegex(
                ArmMotionManifestError, 'unknown=.*release_ready'):
            evaluate_manifest(manifest)

    def test_unknown_nested_fields_are_rejected(self):
        manifest = complete_manifest()
        manifest['motion_profile']['acceleration_is_reviewed'] = True
        with self.assertRaisesRegex(ArmMotionManifestError, 'unknown='):
            evaluate_manifest(manifest)

    def test_duplicate_keys_and_nonfinite_json_are_rejected(self):
        with self.assertRaisesRegex(ArmMotionManifestError, 'duplicate'):
            loads_manifest('{"schema_version":1,"schema_version":1}')
        for token in ('NaN', 'Infinity', '-Infinity'):
            with self.subTest(token=token):
                with self.assertRaisesRegex(
                        ArmMotionManifestError, 'non-finite'):
                    loads_manifest('{"value":' + token + '}')

    def test_in_memory_input_rejects_non_json_objects_without_hooks(self):
        class Hostile:
            def __deepcopy__(self, unused_memo):
                raise AssertionError('must not invoke object hooks')

        with self.assertRaisesRegex(
                ArmMotionManifestError, 'non-JSON value'):
            evaluate_manifest({'schema_version': 1, 'hostile': Hostile()})

    def test_boolean_and_nonfinite_numeric_values_are_rejected(self):
        cases = (
            ('schema_version', True),
            ('tool.mass_kg', True),
            ('motion_profile.max_speed_grade', True),
            ('named_poses.margin', math.inf),
        )
        for label, value in cases:
            with self.subTest(label=label):
                manifest = complete_manifest()
                if label == 'schema_version':
                    manifest['schema_version'] = value
                elif label == 'tool.mass_kg':
                    manifest['tool']['mass_kg'] = value
                elif label == 'motion_profile.max_speed_grade':
                    manifest['motion_profile']['max_speed_grade'] = value
                else:
                    manifest['named_poses'][0][
                        'minimum_limit_margin_deg'] = value
                with self.assertRaises(ArmMotionManifestError):
                    evaluate_manifest(manifest)

    def test_hashes_require_exact_hex_but_accept_either_case(self):
        manifest = complete_manifest()
        manifest['review']['approval_sha256'] = 'g' * 64
        with self.assertRaisesRegex(ArmMotionManifestError, '64 hexadecimal'):
            evaluate_manifest(manifest)
        manifest = complete_manifest()
        manifest['review']['approval_sha256'] = 'aB' * 32
        report = evaluate_manifest(manifest)
        self.assertEqual(
            report['normalized_manifest']['review']['approval_sha256'],
            'ab' * 32,
        )

    def test_review_timestamp_must_be_canonical_and_calendar_valid(self):
        for timestamp in (
                '2026-08-14 12:00:00Z',
                '2026-99-99T12:00:00Z'):
            with self.subTest(timestamp=timestamp):
                manifest = complete_manifest()
                manifest['review']['reviewed_at_utc'] = timestamp
                with self.assertRaisesRegex(
                        ArmMotionManifestError, 'UTC timestamp|must use'):
                    evaluate_manifest(manifest)

    def test_acceleration_profile_needs_cases_coverage_and_repeatability(self):
        manifest = complete_manifest()
        manifest['motion_profile']['approved_speed_grades'] = [4, 5]
        manifest['motion_profile']['cases'][0]['sample_count'] = 2
        report = evaluate_manifest(manifest)
        self.assertFalse(report['release_ready'])
        joined = '\n'.join(report['blocking_issues'])
        self.assertIn('repeatability', joined)
        self.assertIn('grade 4 has no measured case', joined)

    def test_measured_dynamics_must_stay_within_approved_physical_limits(self):
        manifest = complete_manifest()
        case = manifest['motion_profile']['cases'][0]
        case['measured_joint_acceleration_deg_s2'] = 21.0
        case['measured_tcp_stop_distance_mm'] = 3.1
        report = evaluate_manifest(manifest)
        joined = '\n'.join(report['blocking_issues'])
        self.assertIn('max_joint_acceleration_deg_s2', joined)
        self.assertIn('max_tcp_stop_distance_mm', joined)

    def test_every_approved_grade_and_tcp_mode_needs_a_measured_case(self):
        manifest = complete_manifest()
        manifest['motion_profile']['approved_tcp_modes'] = [0, 1]
        report = evaluate_manifest(manifest)
        self.assertIn(
            'approved speed grade 5 / TCP mode 1 has no measured case',
            report['blocking_issues'],
        )

    def test_profile_name_alone_cannot_pass_acceleration_gate(self):
        manifest = complete_manifest()
        manifest['motion_profile']['cases'] = []
        report = evaluate_manifest(manifest)
        self.assertFalse(report['release_ready'])
        self.assertIn(
            'motion_profile.cases is unresolved',
            report['blocking_issues'],
        )

    def test_motion_profile_and_pose_bind_to_final_tool_revision(self):
        manifest = complete_manifest()
        manifest['motion_profile']['tool_revision'] = 'stale-tool'
        manifest['named_poses'][0]['tool_revision'] = 'stale-tool'
        report = evaluate_manifest(manifest)
        joined = '\n'.join(report['blocking_issues'])
        self.assertIn('motion profile tool revision', joined)
        self.assertIn('named_poses[0] tool revision', joined)

    def test_tcp_frame_endpoint_and_tool_reference_must_agree(self):
        manifest = complete_manifest()
        manifest['coordinate_contract']['reference_frame'] = 1
        manifest['coordinate_contract']['endpoint_frame_id'] = 'arm_flange'
        manifest['coordinate_contract']['controller_tool_reference'][2] = 70.0
        manifest['cartesian_limits']['reference_frame_id'] = 'world'
        report = evaluate_manifest(manifest)
        joined = '\n'.join(report['blocking_issues'])
        self.assertIn('base reference frame', joined)
        self.assertIn('tool end type must use gripper_tcp', joined)
        self.assertIn('does not match flange_to_tcp', joined)
        self.assertIn('reference frames disagree', joined)

    def test_controller_state_requires_exact_health_and_stationary_evidence(self):
        manifest = complete_manifest()
        manifest['controller_state']['controller_connected'] = True
        with self.assertRaisesRegex(ArmMotionManifestError, 'native integer'):
            evaluate_manifest(manifest)
        manifest = complete_manifest()
        manifest['controller_state']['power_on'] = 0
        manifest['controller_state']['moving'] = 1
        manifest['controller_state']['paused'] = 1
        manifest['controller_state']['stationary_samples'] = 2
        report = evaluate_manifest(manifest)
        joined = '\n'.join(report['blocking_issues'])
        self.assertIn('power_on must be exact integer 1', joined)
        self.assertIn('moving must be exact integer 0', joined)
        self.assertIn('paused must be exact integer 0', joined)
        self.assertIn('stationary_samples must be at least 3', joined)

    def test_fresh_mode_must_match_limits_and_controller_state(self):
        manifest = complete_manifest()
        manifest['joint_limits']['required_fresh_mode'] = 1
        report = evaluate_manifest(manifest)
        self.assertIn(
            'joint_limits.required_fresh_mode disagrees with controller state',
            report['blocking_issues'],
        )

    def test_flange_endpoint_requires_explicit_zero_controller_tcp(self):
        manifest = complete_manifest()
        manifest['coordinate_contract']['end_type'] = 0
        manifest['coordinate_contract']['endpoint_frame_id'] = 'arm_flange'
        report = evaluate_manifest(manifest)
        self.assertIn(
            'flange end type requires an explicit zero controller TCP',
            report['blocking_issues'],
        )

    def test_project_joint_limits_must_be_strict_controller_subset(self):
        manifest = complete_manifest()
        manifest['joint_limits']['project_deg'][0] = [-170.0, 160.0]
        report = evaluate_manifest(manifest)
        self.assertIn(
            'joint 1 project limits are not a strict controller subset',
            report['blocking_issues'],
        )

    def test_cartesian_bounds_require_six_finite_ordered_pairs(self):
        manifest = complete_manifest()
        manifest['cartesian_limits']['bounds'][0] = [50.0, 50.0]
        with self.assertRaisesRegex(ArmMotionManifestError, 'ordered'):
            evaluate_manifest(manifest)

    def test_named_poses_need_every_unique_role_and_limit_margin(self):
        manifest = complete_manifest()
        manifest['named_poses'].pop()
        manifest['named_poses'][0]['joint_angles_deg'][0] = 159.0
        manifest['named_poses'][0]['minimum_limit_margin_deg'] = 5.0
        report = evaluate_manifest(manifest)
        joined = '\n'.join(report['blocking_issues'])
        self.assertIn('does not satisfy its declared limit margin', joined)
        self.assertIn('required named pose role is missing: retreat', joined)

    def test_named_pose_declared_margin_cannot_understate_global_minimum(self):
        manifest = complete_manifest()
        manifest['named_poses'][0]['minimum_limit_margin_deg'] = 9.0
        report = evaluate_manifest(manifest)
        self.assertIn(
            'named_poses[0] declares less than the required named-pose margin',
            report['blocking_issues'],
        )

    def test_duplicate_named_pose_roles_are_rejected(self):
        manifest = complete_manifest()
        manifest['named_poses'][1]['role'] = 'pre_grasp'
        with self.assertRaisesRegex(ArmMotionManifestError, 'roles'):
            evaluate_manifest(manifest)

    def test_release_requires_explicit_absolute_local_artifact_root(self):
        manifest = complete_manifest()
        report = evaluate_manifest(manifest)
        self.assertFalse(report['release_ready'])
        self.assertIn(
            'an explicit local artifact_root is required',
            report['blocking_issues'],
        )
        with self.assertRaisesRegex(ArmMotionManifestError, 'absolute'):
            evaluate_manifest(manifest, artifact_root='relative/artifacts')
        with self.assertRaisesRegex(
                ArmMotionManifestError, 'device|special namespace'):
            evaluate_manifest(manifest, artifact_root='/dev')

    def test_bound_artifacts_reject_tamper_missing_and_undeclared_hash(self):
        with tempfile.TemporaryDirectory() as root:
            manifest, artifact_root = write_bound_release_fixture(root)
            (artifact_root / 'review.txt').write_bytes(b'tampered')
            report = evaluate_manifest(manifest, artifact_root=artifact_root)
            self.assertIn('SHA-256 does not match', '\n'.join(
                report['blocking_issues']))
        with tempfile.TemporaryDirectory() as root:
            manifest, artifact_root = write_bound_release_fixture(root)
            (artifact_root / 'review.txt').unlink()
            report = evaluate_manifest(manifest, artifact_root=artifact_root)
            self.assertIn('is missing', '\n'.join(report['blocking_issues']))
        with tempfile.TemporaryDirectory() as root:
            manifest, artifact_root = write_bound_release_fixture(root)
            manifest['review']['approval_sha256'] = 'b' * 64
            report = evaluate_manifest(manifest, artifact_root=artifact_root)
            self.assertIn(
                'manifest.review.approval_sha256 is not declared by artifacts',
                report['blocking_issues'],
            )

    def test_artifact_bytes_are_not_reopened_after_hash_verification(self):
        with tempfile.TemporaryDirectory() as root:
            manifest, artifact_root = write_bound_release_fixture(root)
            evidence_path = artifact_root / 'execution_safety.json'
            altered = loads_manifest(evidence_path.read_text(encoding='utf-8'))
            for key in (
                    'command_id', 'result_command_id', 'timeout_command_id',
                    'stop_command_id', 'stationary_command_id',
                    'ack_command_id'):
                altered['trace'][key] = 'replacement-command'
            altered['hung_motion_send_probe'][
                'command_id'] = 'replacement-command'
            altered_bytes = _json_bytes(altered)
            original_read = manifest_module._read_bound_artifact

            def replace_after_read(path, label):
                payload = original_read(path, label)
                if path.name == 'execution_safety.json':
                    path.write_bytes(altered_bytes)
                return payload

            manifest_module._read_bound_artifact = replace_after_read
            try:
                report = evaluate_manifest(
                    manifest, artifact_root=artifact_root)
            finally:
                manifest_module._read_bound_artifact = original_read

            self.assertTrue(report['release_ready'])
            self.assertEqual(report['blocking_issues'], [])

    def test_bound_artifacts_reject_unsafe_path_and_symlink(self):
        with tempfile.TemporaryDirectory() as root:
            manifest, artifact_root = write_bound_release_fixture(root)
            manifest['artifacts'][0]['path'] = '../review.txt'
            with self.assertRaisesRegex(
                    ArmMotionManifestError, 'inside artifact_root'):
                evaluate_manifest(manifest, artifact_root=artifact_root)
        with tempfile.TemporaryDirectory() as root:
            manifest, artifact_root = write_bound_release_fixture(root)
            review_path = artifact_root / 'review.txt'
            target = artifact_root / 'review-target.txt'
            target.write_bytes(review_path.read_bytes())
            review_path.unlink()
            try:
                review_path.symlink_to(target)
            except (OSError, NotImplementedError):
                self.skipTest('symbolic links are unavailable')
            report = evaluate_manifest(manifest, artifact_root=artifact_root)
            self.assertIn(
                'must not be a symbolic link',
                '\n'.join(report['blocking_issues']),
            )

    def test_capability_path_hash_must_match_artifact_index(self):
        with tempfile.TemporaryDirectory() as root:
            manifest, artifact_root = write_bound_release_fixture(root)
            manifest['real_backend_gate'][
                'bounded_call_capability']['artifact'] = 'review.txt'
            report = evaluate_manifest(manifest, artifact_root=artifact_root)
            self.assertIn(
                'real_backend_gate.bounded_call_capability artifact path '
                'does not match '
                'artifacts[]',
                report['blocking_issues'],
            )
        with tempfile.TemporaryDirectory() as root:
            manifest, artifact_root = write_bound_release_fixture(root)
            review = manifest['artifacts'][0]
            capability = manifest['real_backend_gate'][
                'bounded_call_capability']
            capability['artifact'] = review['path']
            capability['artifact_sha256'] = review['sha256']
            review['claims'].append(
                'manifest.real_backend_gate.bounded_call_capability.'
                'artifact_sha256')
            manifest['artifacts'][1]['claims'].remove(
                'manifest.real_backend_gate.bounded_call_capability.'
                'artifact_sha256')
            report = evaluate_manifest(manifest, artifact_root=artifact_root)
            self.assertIn(
                'real backend capabilities must bind one '
                'execution-safety artifact',
                report['blocking_issues'],
            )

    def test_artifact_claim_scope_is_exact_and_unique(self):
        with tempfile.TemporaryDirectory() as root:
            manifest, artifact_root = write_bound_release_fixture(root)
            evidence_hash = manifest['artifacts'][1]['sha256']
            manifest['review']['approval_sha256'] = evidence_hash
            report = evaluate_manifest(manifest, artifact_root=artifact_root)
            self.assertIn(
                'manifest.review.approval_sha256 is not explicitly claimed '
                'by its artifact',
                report['blocking_issues'],
            )
        with tempfile.TemporaryDirectory() as root:
            manifest, artifact_root = write_bound_release_fixture(root)
            claims = manifest['artifacts'][0]['claims']
            review_claim = 'manifest.review.approval_sha256'
            source_claim = (
                'manifest.source_binding.interface_contract_sha256')
            claims.remove(review_claim)
            claims.remove(source_claim)
            claims.extend([source_claim, review_claim])
            # Swapping list order alone is harmless; swap the claimed owners by
            # moving one exact path to the execution artifact instead.
            claims.remove(review_claim)
            manifest['artifacts'][1]['claims'].append(review_claim)
            report = evaluate_manifest(manifest, artifact_root=artifact_root)
            self.assertFalse(report['release_ready'])
            self.assertIn(
                'manifest.review.approval_sha256 is not explicitly claimed '
                'by its artifact',
                report['blocking_issues'],
            )
        with tempfile.TemporaryDirectory() as root:
            manifest, artifact_root = write_bound_release_fixture(root)
            duplicate = manifest['artifacts'][0]['claims'][0]
            manifest['artifacts'][1]['claims'].append(duplicate)
            with self.assertRaisesRegex(
                    ArmMotionManifestError, 'globally unique'):
                evaluate_manifest(manifest, artifact_root=artifact_root)

    def test_runtime_release_ids_and_capability_booleans_are_enforced(self):
        with tempfile.TemporaryDirectory() as root:
            manifest, artifact_root = write_bound_release_fixture(root)
            manifest['motion_profile'][
                'acceleration_profile_runtime_release_id'] = 'stale-release'
            report = evaluate_manifest(manifest, artifact_root=artifact_root)
            self.assertIn(
                'does not match release_binding.runtime_release_id',
                '\n'.join(report['blocking_issues']),
            )
        for capability in (
                'bounded_call_capability',
                'deadline_enforcement_capability',
                'native_cancel_capability',
                'independent_stop_channel_capability',
                'persistent_safety_latch_capability'):
            with self.subTest(capability=capability), \
                    tempfile.TemporaryDirectory() as root:
                manifest, artifact_root = write_bound_release_fixture(root)
                manifest['real_backend_gate'][capability]['enforced'] = False
                report = evaluate_manifest(
                    manifest, artifact_root=artifact_root)
                self.assertIn(
                    'real_backend_gate.{}.enforced must be true'.format(
                        capability),
                    report['blocking_issues'],
                )

    def test_acceleration_profile_artifact_is_machine_bound(self):
        mutations = (
            ('runtime_release_id', 'stale-release'),
            ('profile_id', 'stale-profile'),
            ('max_joint_acceleration_deg_s2', 1.0e12),
        )
        for key, value in mutations:
            with self.subTest(key=key):
                with tempfile.TemporaryDirectory() as root:
                    manifest, artifact_root = write_bound_release_fixture(root)
                    evidence = acceleration_profile_evidence()
                    evidence[key] = value
                    rewrite_acceleration_profile_artifact(
                        manifest, artifact_root, _json_bytes(evidence))
                    report = evaluate_manifest(
                        manifest, artifact_root=artifact_root)
                    self.assertFalse(report['release_ready'])
                    self.assertIn(
                        'acceleration profile artifact {} does not match '
                        'motion_profile'.format(key),
                        report['blocking_issues'],
                    )

    def test_runtime_release_artifact_is_machine_bound(self):
        mutations = (
            ('runtime_release_id', 'stale-release'),
            ('motion_profile_id', 'stale-profile'),
            ('bounded_call_capability', False),
            ('native_cancel_capability', False),
            ('persistent_safety_latch_capability', False),
        )
        for key, value in mutations:
            with self.subTest(key=key):
                with tempfile.TemporaryDirectory() as root:
                    manifest, artifact_root = write_bound_release_fixture(root)
                    evidence = runtime_release_evidence(
                        manifest['motion_profile'][
                            'acceleration_profile_manifest_sha256'])
                    evidence[key] = value
                    rewrite_runtime_release_artifact(
                        manifest, artifact_root, _json_bytes(evidence))
                    report = evaluate_manifest(
                        manifest, artifact_root=artifact_root)
                    self.assertFalse(report['release_ready'])
                    self.assertIn(
                        'runtime release artifact {} does not match '
                        'manifest'.format(key),
                        report['blocking_issues'],
                    )

    def test_execution_evidence_rejects_schema_size_and_encoding(self):
        with tempfile.TemporaryDirectory() as root:
            evidence = execution_safety_evidence()
            evidence['schema_version'] = 2
            manifest, artifact_root = write_bound_release_fixture(
                root, evidence=evidence)
            with self.assertRaisesRegex(
                    ArmMotionManifestError, 'unsupported.*schema_version'):
                evaluate_manifest(manifest, artifact_root=artifact_root)
        with tempfile.TemporaryDirectory() as root:
            manifest, artifact_root = write_bound_release_fixture(root)
            rewrite_execution_safety_artifact(
                manifest, artifact_root, b'x' * (1024 * 1024 + 1))
            with self.assertRaisesRegex(
                    ArmMotionManifestError, 'size limit'):
                evaluate_manifest(manifest, artifact_root=artifact_root)
        with tempfile.TemporaryDirectory() as root:
            manifest, artifact_root = write_bound_release_fixture(root)
            rewrite_execution_safety_artifact(
                manifest, artifact_root, b'\xff\xfe')
            with self.assertRaisesRegex(ArmMotionManifestError, 'UTF-8'):
                evaluate_manifest(manifest, artifact_root=artifact_root)

    def test_execution_evidence_deadline_fail_closed_matrix(self):
        cases = (
            ('deadline-enforcement', False, 'not enforced'),
            ('zero-call-deadline', 0.0, 'must be positive'),
        )
        for name, value, expected in cases:
            with self.subTest(name=name):
                with tempfile.TemporaryDirectory() as root:
                    evidence = execution_safety_evidence()
                    if name == 'deadline-enforcement':
                        evidence['vendor_call_deadlines'][
                            'deadline_enforced'] = value
                    else:
                        evidence['vendor_call_deadlines'][
                            'call_deadlines_s']['get_angles'] = value
                    manifest, artifact_root = write_bound_release_fixture(
                        root, evidence=evidence)
                    if name == 'zero-call-deadline':
                        with self.assertRaisesRegex(
                                ArmMotionManifestError, expected):
                            evaluate_manifest(
                                manifest, artifact_root=artifact_root)
                    else:
                        report = evaluate_manifest(
                            manifest, artifact_root=artifact_root)
                        self.assertIn(
                            expected, '\n'.join(report['blocking_issues']))
        with tempfile.TemporaryDirectory() as root:
            evidence = execution_safety_evidence()
            evidence['hung_motion_send_probe']['stop_elapsed_s'] = 0.3
            manifest, artifact_root = write_bound_release_fixture(
                root, evidence=evidence)
            report = evaluate_manifest(manifest, artifact_root=artifact_root)
            self.assertIn(
                'did not satisfy the declared deadline',
                '\n'.join(report['blocking_issues']),
            )

    def test_execution_evidence_cancel_capability_fail_closed_matrix(self):
        mutations = (
            ('native-false', lambda evidence: evidence[
                'cancellation_capability'].__setitem__(
                    'native_transport_cancel_enforced', False),
             'native transport cancellation is not enforced'),
            ('python-thread', lambda evidence: evidence[
                'cancellation_capability'].__setitem__(
                    'python_timeout_thread_used', True),
             'Python timeout thread'),
            ('cancel-false', lambda evidence: evidence[
                'cancellation_capability'].__setitem__(
                    'cancel_completed', False),
             'did not complete'),
            ('late-cancel', lambda evidence: evidence[
                'cancellation_capability'].__setitem__(
                    'cancel_elapsed_s', 0.3),
             'missed its deadline'),
            ('late-commit', lambda evidence: evidence[
                'cancellation_capability'].__setitem__(
                    'cancelled_send_cannot_commit', False),
             'still commit'),
        )
        for name, mutate, expected in mutations:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as root:
                evidence = execution_safety_evidence()
                mutate(evidence)
                manifest, artifact_root = write_bound_release_fixture(
                    root, evidence=evidence)
                report = evaluate_manifest(
                    manifest, artifact_root=artifact_root)
                self.assertIn(expected, '\n'.join(report['blocking_issues']))

    def test_execution_evidence_exact_release_bindings_fail_closed(self):
        mutations = (
            (
                'forged-runtime-hash',
                lambda evidence: evidence.__setitem__(
                    'release_manifest_sha256', '0' * 64),
                'release_manifest_sha256 does not match',
            ),
            (
                'forged-acceleration-hash',
                lambda evidence: evidence.__setitem__(
                    'acceleration_profile_manifest_sha256', '1' * 64),
                'acceleration_profile_manifest_sha256 does not match',
            ),
            (
                'stale-approved-speed-set',
                lambda evidence: evidence.__setitem__(
                    'approved_speed_grades', [4, 5]),
                'approved speed grades do not exactly match',
            ),
            (
                'unapproved-speed-grade',
                lambda evidence: evidence.__setitem__(
                    'approved_speed_grades', [6]),
                'approved speed grades do not exactly match',
            ),
        )
        for name, mutate, expected in mutations:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as root:
                manifest, artifact_root = write_bound_release_fixture(root)
                evidence = loads_manifest(
                    (artifact_root / 'execution_safety.json').read_text(
                        encoding='utf-8'))
                mutate(evidence)
                rewrite_execution_safety_artifact(
                    manifest, artifact_root, _json_bytes(evidence))
                report = evaluate_manifest(
                    manifest, artifact_root=artifact_root)
                self.assertFalse(report['release_ready'])
                self.assertIn(expected, '\n'.join(report['blocking_issues']))

    def test_execution_evidence_binding_fields_are_exact_and_required(self):
        cases = (
            (
                'missing-runtime-hash',
                lambda evidence: evidence.pop('release_manifest_sha256'),
                'keys mismatch',
            ),
            (
                'uppercase-runtime-hash',
                lambda evidence: evidence.__setitem__(
                    'release_manifest_sha256',
                    evidence['release_manifest_sha256'].upper()),
                'exact lowercase SHA-256',
            ),
            (
                'missing-approved-grades',
                lambda evidence: evidence.pop('approved_speed_grades'),
                'keys mismatch',
            ),
            (
                'duplicate-approved-grade',
                lambda evidence: evidence.__setitem__(
                    'approved_speed_grades', [5, 5]),
                'must be unique and increasing',
            ),
        )
        for name, mutate, expected in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as root:
                manifest, artifact_root = write_bound_release_fixture(root)
                evidence = loads_manifest(
                    (artifact_root / 'execution_safety.json').read_text(
                        encoding='utf-8'))
                mutate(evidence)
                rewrite_execution_safety_artifact(
                    manifest, artifact_root, _json_bytes(evidence))
                with self.assertRaisesRegex(ArmMotionManifestError, expected):
                    evaluate_manifest(manifest, artifact_root=artifact_root)

    def test_execution_evidence_persistent_latch_fail_closed_matrix(self):
        mutations = (
            ('exclusive_create_enforced', False, 'exclusive create'),
            ('atomic_update_enforced', False, 'atomic update'),
            ('generation_chain_enforced', False, 'generation chain'),
            ('restart_restored_active_latch', False, 'not restored'),
            ('old_session_clear_rejected', False, 'old session'),
            ('external_clearance_validator_required', False,
             'external validator'),
            ('local_hashes_claim_authenticity', True,
             'must not claim cryptographic authenticity'),
        )
        for key, value, expected in mutations:
            with self.subTest(key=key), tempfile.TemporaryDirectory() as root:
                evidence = execution_safety_evidence()
                evidence['persistent_safety_latch'][key] = value
                manifest, artifact_root = write_bound_release_fixture(
                    root, evidence=evidence)
                report = evaluate_manifest(
                    manifest, artifact_root=artifact_root)
                self.assertIn(expected, '\n'.join(report['blocking_issues']))

    def test_execution_evidence_domain_and_hung_send_matrix(self):
        mutations = (
            ('same-domain', lambda evidence: evidence[
                'execution_domains'].__setitem__(
                    'stop_domain', evidence['execution_domains'][
                        'motion_domain']), 'domains must be different'),
            ('shared-lock', lambda evidence: evidence[
                'execution_domains'].__setitem__(
                    'independent_lock_domains', False), 'not independent'),
            ('stop-false', lambda evidence: evidence[
                'hung_motion_send_probe'].__setitem__(
                    'stop_completed', False), 'STOP did not complete'),
            ('not-before-release', lambda evidence: evidence[
                'hung_motion_send_probe'].__setitem__(
                    'stop_completed_before_send_release', False),
             'blocked STOP completion'),
        )
        for name, mutate, expected in mutations:
            with self.subTest(name=name):
                with tempfile.TemporaryDirectory() as root:
                    evidence = execution_safety_evidence()
                    mutate(evidence)
                    manifest, artifact_root = write_bound_release_fixture(
                        root, evidence=evidence)
                    report = evaluate_manifest(
                        manifest, artifact_root=artifact_root)
                    self.assertIn(
                        expected, '\n'.join(report['blocking_issues']))

    def test_execution_evidence_trace_and_stationary_matrix(self):
        mutations = (
            ('id-mismatch', lambda evidence: evidence['trace'].__setitem__(
                'ack_command_id', 'other-command'), 'share one command_id'),
            ('success-result', lambda evidence: evidence['trace'].__setitem__(
                'interrupted_result_success', True), 'must be unsuccessful'),
            ('stop-as-stationary', lambda evidence: evidence[
                'trace'].__setitem__(
                    'stop_return_used_as_stationary_evidence', True),
             'must not be used as stationary'),
            ('too-few-samples', lambda evidence: evidence[
                'trace'].__setitem__(
                    'stationary_samples', evidence['trace'][
                        'stationary_samples'][:2]),
             'at least three stationary samples'),
            ('duplicate-sample', lambda evidence: evidence['trace'][
                'stationary_samples'][1].__setitem__(
                    'sample_id', 'stationary-1'),
             'sample IDs must be unique'),
            ('duplicate-time', lambda evidence: evidence['trace'][
                'stationary_samples'][1].__setitem__(
                    'time_s', 1.0), 'strictly increasing'),
            ('short-dwell', lambda evidence: evidence['trace'].__setitem__(
                'stationary_dwell_s', 0.3), 'do not span'),
            ('early-ack', lambda evidence: evidence['trace'].__setitem__(
                'ack_at_s', 1.1), 'ACK must occur after'),
            ('early-result', lambda evidence: evidence['trace'].__setitem__(
                'result_at_s', 1.1), 'timeline is not safely ordered'),
        )
        for name, mutate, expected in mutations:
            with self.subTest(name=name):
                with tempfile.TemporaryDirectory() as root:
                    evidence = execution_safety_evidence()
                    mutate(evidence)
                    manifest, artifact_root = write_bound_release_fixture(
                        root, evidence=evidence)
                    report = evaluate_manifest(
                        manifest, artifact_root=artifact_root)
                    self.assertIn(
                        expected, '\n'.join(report['blocking_issues']))

    def test_validator_source_has_no_ros_vendor_or_motion_calls(self):
        source = MODULE.read_text(encoding='utf-8')
        tree = ast.parse(source, filename=str(MODULE))
        forbidden_imports = {'rclpy', 'serial', 'pymycobot', 'socket'}
        forbidden_calls = {
            'send_angles', 'send_coords', 'stop',
            'create_client', 'create_node',
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn(alias.name.split('.')[0], forbidden_imports)
            elif isinstance(node, ast.ImportFrom):
                self.assertNotIn(
                    (node.module or '').split('.')[0], forbidden_imports)
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute):
                    self.assertNotIn(node.func.attr, forbidden_calls)
                elif isinstance(node.func, ast.Name):
                    self.assertNotIn(node.func.id, forbidden_calls)
        for token in ('ros2 action', 'ros2 service'):
            self.assertNotIn(token, source.lower())

    def test_example_has_no_release_claim_or_runtime_endpoint(self):
        source = EXAMPLE.read_text(encoding='utf-8')
        payload = json.loads(source)
        self.assertNotIn('release_ready', payload)
        for token in ('/dev/', 'pymycobot', 'serial', 'action', 'service'):
            self.assertNotIn(token, source.lower())


if __name__ == '__main__':
    unittest.main()

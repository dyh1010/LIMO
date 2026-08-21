"""Offline contract tests for the formal four-scene field intake."""

import copy
import hashlib
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).parents[1]
SCHEMA_PATH = ROOT / 'fixtures/perception_field_intake.schema.json'
TEMPLATE_PATH = ROOT / 'fixtures/perception_field_intake_template.json'
TOPIC_MANIFEST_PATH = ROOT / 'fixtures/rgbd_expected_topics.json'
SETUP_PATH = ROOT / 'setup.py'
SCENES = ('background', 'bin_only', 'bottle_in_bin', 'bottle_outside')
TOPICS = (
    '/camera/color/image_raw',
    '/camera/depth/image_raw',
    '/camera/color/camera_info',
    '/camera/depth/camera_info',
    '/tf',
    '/tf_static',
)
ARTIFACT_KEYS = {
    'raw_capture', 'raw_inspection', 'typed_frames', 'collector_manifest',
    'typed_raw_binding', 'rgbd_artifact', 'ground_truth', 'tf_artifact',
    'xyz_ground_truth', 'depth_measurement_reference', 'depth_quality',
    'latency_evidence', 'scene_evidence_binding',
}
PROVENANCE_KEYS = {
    'capture_binding_id', 'capture_id', 'scene', 'task_id',
    'capture_window', 'release_id', 'source_set_sha256', 'model_sha256',
    'raw_capture_sha256', 'raw_inspection_sha256',
    'expected_topic_manifest',
}
AUTHORIZATION_KEYS = {
    'authorization_id', 'authorized_by', 'authorized_at_unix_sec',
    'expires_at_unix_sec', 'scope', 'allow', 'deny', 'preconditions',
}
PRECONDITION_KEYS = {
    'physical_estop_available', 'ros1_control_graph_confirmed_inactive',
    'ros2_control_graph_confirmed_inactive',
    'actuator_uart_owner_confirmed_absent',
}
RELEASE_KEYS = {
    'release_id', 'source_manifest', 'source_set_sha256', 'models',
}
GLOBAL_ARTIFACT_KEYS = {
    'runtime_preflight', 'ros_build_validation',
    'ros1_field_install_validation', 'hardware_readiness',
    'extrinsics_measurement_reference', 'authorization_record',
}
SCENE_KEYS = {
    'scene', 'expected_presence', 'expected_bottle_relation', 'capture_id',
    'task_id', 'min_unique_typed_frames', 'target_unique_typed_frames',
    'exclusive_new_files', 'arrangement', 'capture_window', 'artifacts',
    'capture_provenance', 'evidence_requirements',
}
ARRANGEMENT_KEYS = {
    'independently_arranged', 'operator', 'reviewer',
    'started_unix_sec', 'ended_unix_sec',
}
WINDOW_KEYS = {'started_unix_sec', 'ended_unix_sec'}
MODEL_KEYS = {'plastic_bottle', 'trash_bin'}
MANIFEST_BINDING_KEYS = {
    'manifest_id', 'schema_version', 'size_bytes', 'sha256',
}
AUTH_ALLOW = (
    'start_preapproved_rgbd_camera_driver',
    'subscribe_rgb_depth_camera_info_tf',
    'record_exact_frozen_six_topic_bag',
    'run_dual_model_inference',
    'publish_perception_only_outputs',
    'subscribe_typed_perception_frame',
    'write_exclusive_new_evidence_files',
    'run_offline_index_binding_and_readiness',
)
AUTH_DENY = (
    'publish_or_subscribe_actuation_commands',
    'send_navigation_goals',
    'start_base_navigation_teleop_bridge_watchdog',
    'start_arm_gripper_moveit_or_executor',
    'open_actuator_uart_or_serial',
    'rosbag_play',
    'record_extra_or_alias_topics',
    'frame_id_override_or_placeholder_tf',
    'overwrite_existing_evidence',
    'use_sim_time',
    'connect_perception_to_motion_consumers',
)
EXPECTED_MANIFEST_BINDING = {
    'manifest_id': 'limo-dabai-rgbd-six-topics-v1',
    'schema_version': 1,
    'size_bytes': 1969,
    'sha256': (
        '0e56197a7ca2bb01675d7894c79ff89fbcc2e45c5fad1c969ce97471c07dc8f4'),
}


def _load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def _template():
    return _load(TEMPLATE_PATH)


def _artifact(name):
    return {
        'path': 'evidence/{}.json'.format(name),
        'size_bytes': len(name) + 1,
        'sha256': hashlib.sha256(name.encode('utf-8')).hexdigest(),
    }


def _completed_intake():
    candidate = _template()
    candidate['intake_id'] = 'field-intake-001'
    candidate['created_at_unix_sec'] = 2200.0
    authorization = candidate['authorization']
    authorization.update({
        'authorization_id': 'readonly-camera-001',
        'authorized_by': 'field-safety-owner',
        'authorized_at_unix_sec': 1000.0,
        'expires_at_unix_sec': 2000.0,
    })
    authorization['preconditions'] = {
        key: True for key in PRECONDITION_KEYS}
    release = candidate['release_binding']
    release.update({
        'release_id': 'perception-v2-field-001',
        'source_manifest': _artifact('source-manifest'),
        'source_set_sha256': hashlib.sha256(
            b'complete-source-set').hexdigest(),
        'models': {
            'plastic_bottle': _artifact('plastic-bottle-model'),
            'trash_bin': _artifact('trash-bin-model'),
        },
    })
    candidate['global_artifacts'] = {
        key: _artifact('global-' + key) for key in GLOBAL_ARTIFACT_KEYS}
    planned = []
    for index, scene in enumerate(SCENES):
        declaration = candidate['scenes'][scene]
        capture_id = '{}-capture-001'.format(scene)
        task_id = '{}-readonly-001'.format(scene)
        started = 1100.0 + index * 100.0
        ended = started + 60.0
        declaration['capture_id'] = capture_id
        declaration['task_id'] = task_id
        declaration['arrangement'].update({
            'operator': 'operator-{}'.format(index),
            'reviewer': 'reviewer-{}'.format(index),
            'started_unix_sec': started,
            'ended_unix_sec': ended,
        })
        declaration['capture_window'].update({
            'started_unix_sec': started,
            'ended_unix_sec': ended,
        })
        declaration['artifacts'] = {
            key: _artifact('{}-{}'.format(scene, key))
            for key in ARTIFACT_KEYS}
        planned.extend(
            item['path'] for item in declaration['artifacts'].values())
        provenance = declaration['capture_provenance']
        provenance.update({
            'capture_binding_id': hashlib.sha256(
                (scene + '-binding').encode('utf-8')).hexdigest(),
            'capture_id': capture_id,
            'task_id': task_id,
            'capture_window': {
                'started_unix_sec': started,
                'ended_unix_sec': ended,
            },
            'release_id': release['release_id'],
            'source_set_sha256': release['source_set_sha256'],
            'model_sha256': {
                key: release['models'][key]['sha256'] for key in MODEL_KEYS},
            'raw_capture_sha256': declaration['artifacts'][
                'raw_capture']['sha256'],
            'raw_inspection_sha256': declaration['artifacts'][
                'raw_inspection']['sha256'],
            'expected_topic_manifest': dict(EXPECTED_MANIFEST_BINDING),
        })
    candidate['capture_policy']['planned_exclusive_output_paths'] = planned
    return candidate


def _assert_rejected(mutator):
    candidate = copy.deepcopy(_template())
    mutator(candidate)
    with unittest.TestCase().assertRaises(ValueError):
        _validate_intake(candidate)


def _assert_completed_rejected(mutator):
    candidate = _completed_intake()
    mutator(candidate)
    with unittest.TestCase().assertRaises(ValueError):
        _validate_intake(candidate)


def _exact(value, expected, name):
    if value != expected:
        raise ValueError('{} must equal frozen policy'.format(name))


def _mapping_keys(value, expected, name):
    if not isinstance(value, dict) or set(value) != set(expected):
        raise ValueError('{} fields are invalid'.format(name))


def _non_empty_string(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('{} must be non-empty'.format(name))


def _timestamp(value, name):
    if (not isinstance(value, (int, float)) or isinstance(value, bool)
            or value < 0):
        raise ValueError('{} must be a non-negative timestamp'.format(name))


def _sha256(value, name):
    if (not isinstance(value, str) or len(value) != 64
            or any(character not in '0123456789abcdef' for character in value)):
        raise ValueError('{} must be lowercase SHA-256'.format(name))


def _artifact_identity(value, name):
    _mapping_keys(value, {'path', 'size_bytes', 'sha256'}, name)
    _non_empty_string(value['path'], name + ' path')
    if (not isinstance(value['size_bytes'], int)
            or isinstance(value['size_bytes'], bool)
            or value['size_bytes'] <= 0):
        raise ValueError('{} size must be positive'.format(name))
    _sha256(value['sha256'], name + ' sha256')


def _window(value, name):
    _mapping_keys(value, WINDOW_KEYS, name)
    _timestamp(value['started_unix_sec'], name + ' start')
    _timestamp(value['ended_unix_sec'], name + ' end')
    if value['ended_unix_sec'] <= value['started_unix_sec']:
        raise ValueError('{} must have increasing time'.format(name))


def _validate_intake(candidate):
    """Small standard-library fail-closed validator for intake authoring."""
    required_root = {
        'schema_version', 'intake_scope', 'read_only', 'authorizes_motion',
        'publishes_control_messages', 'delivery_ready', 'intake_id',
        'created_at_unix_sec', 'authorization', 'release_binding',
        'frozen_topic_manifest', 'capture_policy', 'global_artifacts',
        'scenes',
    }
    _exact(set(candidate), required_root, 'root fields')
    _exact(candidate['schema_version'], 1, 'schema_version')
    _exact(candidate['intake_scope'],
           'limo_v2_formal_four_scene_rgbd_field_intake', 'intake_scope')
    _exact(candidate['read_only'], True, 'read_only')
    _exact(candidate['authorizes_motion'], False, 'authorizes_motion')
    _exact(candidate['publishes_control_messages'], False,
           'publishes_control_messages')
    _exact(candidate['delivery_ready'], False, 'delivery_ready')
    _exact(tuple(candidate['scenes']), SCENES, 'scenes')

    authorization = candidate['authorization']
    _mapping_keys(authorization, AUTHORIZATION_KEYS, 'authorization')
    _exact(authorization['scope'],
           'camera_read_capture_and_offline_evaluation_only',
           'authorization scope')
    _exact(tuple(authorization['allow']), AUTH_ALLOW, 'authorization allow')
    _exact(tuple(authorization['deny']), AUTH_DENY, 'authorization deny')
    _mapping_keys(
        authorization['preconditions'], PRECONDITION_KEYS,
        'authorization preconditions')

    release = candidate['release_binding']
    _mapping_keys(release, RELEASE_KEYS, 'release binding')
    _mapping_keys(release['models'], MODEL_KEYS, 'release models')
    global_artifacts = candidate['global_artifacts']
    _mapping_keys(
        global_artifacts, GLOBAL_ARTIFACT_KEYS, 'global artifacts')

    root_authoring_values = (
        candidate['intake_id'], candidate['created_at_unix_sec'],
        authorization['authorization_id'], authorization['authorized_by'],
        authorization['authorized_at_unix_sec'],
        authorization['expires_at_unix_sec'], release['release_id'],
        release['source_manifest'], release['source_set_sha256'],
        release['models']['plastic_bottle'], release['models']['trash_bin'],
    )
    scene_values = []
    for scene in SCENES:
        declaration = candidate['scenes'][scene]
        _mapping_keys(declaration, SCENE_KEYS, scene + ' declaration')
        _mapping_keys(
            declaration['arrangement'], ARRANGEMENT_KEYS,
            scene + ' arrangement')
        _mapping_keys(
            declaration['capture_window'], WINDOW_KEYS,
            scene + ' capture window')
        _mapping_keys(
            declaration['artifacts'], ARTIFACT_KEYS,
            scene + ' artifacts')
        _mapping_keys(
            declaration['capture_provenance'], PROVENANCE_KEYS,
            scene + ' provenance')
        scene_values.extend((
            declaration['capture_id'], declaration['task_id'],
            declaration['arrangement']['operator'],
            declaration['arrangement']['reviewer'],
            declaration['arrangement']['started_unix_sec'],
            declaration['arrangement']['ended_unix_sec'],
            declaration['capture_window']['started_unix_sec'],
            declaration['capture_window']['ended_unix_sec'],
        ))
        scene_values.extend(declaration['artifacts'].values())
        provenance = declaration['capture_provenance']
        scene_values.extend((
            provenance['capture_binding_id'], provenance['capture_id'],
            provenance['task_id'],
            provenance['capture_window']['started_unix_sec'],
            provenance['capture_window']['ended_unix_sec'],
            provenance['release_id'], provenance['source_set_sha256'],
            provenance['model_sha256']['plastic_bottle'],
            provenance['model_sha256']['trash_bin'],
            provenance['raw_capture_sha256'],
            provenance['raw_inspection_sha256'],
            provenance['expected_topic_manifest'],
        ))
    authoring_empty = (
        all(value is None for value in root_authoring_values)
        and all(value is None for value in scene_values)
        and all(value is None for value in authorization[
            'preconditions'].values())
        and all(value is None for value in global_artifacts.values())
        and candidate['capture_policy']['planned_exclusive_output_paths'] == [])

    manifest = candidate['frozen_topic_manifest']
    _mapping_keys(manifest, {
        'manifest_id', 'schema_version', 'path', 'size_bytes', 'sha256',
        'topics'}, 'frozen topic manifest')
    _exact(manifest['manifest_id'], 'limo-dabai-rgbd-six-topics-v1',
           'manifest id')
    _exact(manifest['schema_version'], 1, 'manifest schema version')
    _exact(manifest['path'], 'fixtures/rgbd_expected_topics.json',
           'manifest path')
    _exact(manifest['size_bytes'], 1969, 'manifest size')
    _exact(manifest['sha256'],
           '0e56197a7ca2bb01675d7894c79ff89fbcc2e45c5fad1c969ce97471c07dc8f4',
           'manifest sha256')
    _exact(tuple(manifest['topics']), TOPICS, 'frozen topics')
    policy = candidate['capture_policy']
    _mapping_keys(policy, {
        'scenes_exact', 'min_unique_typed_frames_per_scene',
        'target_unique_typed_frames_per_scene', 'duration_sec',
        'raw_storage_identifier', 'exclusive_new_files',
        'raw_topics_exact', 'planned_exclusive_output_paths',
        'max_sync_span_sec', 'max_dynamic_tf_age_sec',
        'max_typed_raw_unpaired_rate'}, 'capture policy')
    _exact(tuple(policy['scenes_exact']), SCENES, 'policy scenes')
    _exact(tuple(policy['raw_topics_exact']), TOPICS, 'raw topics')
    _exact(policy['min_unique_typed_frames_per_scene'], 30, 'policy min')
    _exact(policy['target_unique_typed_frames_per_scene'], 120,
           'policy target')
    planned = policy['planned_exclusive_output_paths']
    if len(planned) not in (0, 52) or len(planned) != len(set(planned)):
        raise ValueError('planned paths must be empty or 52 unique paths')
    if not authoring_empty and len(planned) != 52:
        raise ValueError('completed intake must plan exactly 52 output paths')

    for scene in SCENES:
        declaration = candidate['scenes'][scene]
        _exact(declaration['scene'], scene, 'scene')
        _exact(declaration['capture_provenance']['scene'], scene,
               'provenance scene')
        _exact(declaration['min_unique_typed_frames'], 30, 'scene min')
        _exact(declaration['target_unique_typed_frames'], 120,
               'scene target')
        _exact(declaration['exclusive_new_files'], True,
               scene + ' exclusive files')

    if authoring_empty:
        return candidate

    _non_empty_string(candidate['intake_id'], 'intake_id')
    _timestamp(candidate['created_at_unix_sec'], 'created_at_unix_sec')
    _non_empty_string(
        authorization['authorization_id'], 'authorization_id')
    _non_empty_string(authorization['authorized_by'], 'authorized_by')
    _timestamp(
        authorization['authorized_at_unix_sec'], 'authorization start')
    _timestamp(authorization['expires_at_unix_sec'], 'authorization end')
    if (authorization['expires_at_unix_sec']
            <= authorization['authorized_at_unix_sec']):
        raise ValueError('authorization time must be increasing')
    if any(value is not True for value in authorization[
            'preconditions'].values()):
        raise ValueError('all authorization safety preconditions must be true')
    _non_empty_string(release['release_id'], 'release_id')
    _artifact_identity(release['source_manifest'], 'source manifest')
    _sha256(release['source_set_sha256'], 'source set sha256')
    for label in MODEL_KEYS:
        _artifact_identity(release['models'][label], label + ' model')
    for name in GLOBAL_ARTIFACT_KEYS:
        _artifact_identity(global_artifacts[name], 'global ' + name)

    capture_ids = set()
    task_ids = set()
    for scene in SCENES:
        declaration = candidate['scenes'][scene]
        _non_empty_string(declaration['capture_id'], scene + ' capture_id')
        _non_empty_string(declaration['task_id'], scene + ' task_id')
        if declaration['capture_id'] in capture_ids:
            raise ValueError('capture_id must be unique across scenes')
        if declaration['task_id'] in task_ids:
            raise ValueError('task_id must be unique across scenes')
        capture_ids.add(declaration['capture_id'])
        task_ids.add(declaration['task_id'])
        arrangement = declaration['arrangement']
        _exact(arrangement['independently_arranged'], True,
               scene + ' independently arranged')
        _non_empty_string(arrangement['operator'], scene + ' operator')
        _non_empty_string(arrangement['reviewer'], scene + ' reviewer')
        _window({
            'started_unix_sec': arrangement['started_unix_sec'],
            'ended_unix_sec': arrangement['ended_unix_sec'],
        }, scene + ' arrangement window')
        _window(declaration['capture_window'], scene + ' capture window')
        for name, value in declaration['artifacts'].items():
            _artifact_identity(value, '{} {}'.format(scene, name))
        provenance = declaration['capture_provenance']
        _mapping_keys(provenance['model_sha256'], MODEL_KEYS,
                      scene + ' provenance models')
        _non_empty_string(
            provenance['capture_binding_id'], scene + ' capture binding')
        _exact(provenance['capture_id'], declaration['capture_id'],
               scene + ' provenance capture_id')
        _exact(provenance['task_id'], declaration['task_id'],
               scene + ' provenance task_id')
        _exact(provenance['capture_window'], declaration['capture_window'],
               scene + ' provenance capture window')
        _exact(provenance['release_id'], release['release_id'],
               scene + ' provenance release_id')
        _exact(provenance['source_set_sha256'], release['source_set_sha256'],
               scene + ' provenance source set')
        for label in MODEL_KEYS:
            _exact(provenance['model_sha256'][label],
                   release['models'][label]['sha256'],
                   scene + ' provenance ' + label)
        _exact(provenance['raw_capture_sha256'],
               declaration['artifacts']['raw_capture']['sha256'],
               scene + ' raw capture binding')
        _exact(provenance['raw_inspection_sha256'],
               declaration['artifacts']['raw_inspection']['sha256'],
               scene + ' raw inspection binding')
        _mapping_keys(
            provenance['expected_topic_manifest'], MANIFEST_BINDING_KEYS,
            scene + ' manifest binding')
        _exact(provenance['expected_topic_manifest'],
               EXPECTED_MANIFEST_BINDING, scene + ' manifest binding')
    artifact_paths = [
        value['path'] for scene in SCENES
        for value in candidate['scenes'][scene]['artifacts'].values()]
    if planned != artifact_paths or len(set(artifact_paths)) != 52:
        raise ValueError('planned paths must exactly bind all scene artifacts')
    return candidate


class FieldIntakeContractTests(unittest.TestCase):

    def test_json_schema_and_empty_template_are_valid(self):
        schema = _load(SCHEMA_PATH)
        template = _template()
        self.assertEqual(
            schema['$schema'], 'http://json-schema.org/draft-07/schema#')
        self.assertEqual(schema['type'], 'object')
        self.assertIs(schema['additionalProperties'], False)
        self.assertEqual(len(schema['oneOf']), 2)
        self.assertEqual(
            schema['oneOf'][0]['$ref'], '#/definitions/emptyAuthoringState')
        self.assertEqual(
            schema['oneOf'][1]['$ref'], '#/definitions/completedFieldState')
        _validate_intake(template)
        self.assertNotIn('evidence_scope', template)
        self.assertIs(template['read_only'], True)
        self.assertIs(template['authorizes_motion'], False)
        self.assertIs(template['publishes_control_messages'], False)
        self.assertIs(template['delivery_ready'], False)
        completed = _completed_intake()
        self.assertIs(_validate_intake(completed), completed)

    def test_exact_scenes_frame_policy_and_scene_semantics(self):
        template = _template()
        self.assertEqual(tuple(template['scenes']), SCENES)
        policy = template['capture_policy']
        self.assertEqual(tuple(policy['scenes_exact']), SCENES)
        self.assertEqual(policy['min_unique_typed_frames_per_scene'], 30)
        self.assertEqual(policy['target_unique_typed_frames_per_scene'], 120)
        expected = {
            'background': ({'plastic_bottle': False, 'trash_bin': False},
                           'absent'),
            'bin_only': ({'plastic_bottle': False, 'trash_bin': True},
                         'absent'),
            'bottle_in_bin': ({'plastic_bottle': True, 'trash_bin': True},
                              'inside_trash_bin_non_actionable'),
            'bottle_outside': ({'plastic_bottle': True, 'trash_bin': True},
                               'outside_trash_bin_actionable'),
        }
        for scene in SCENES:
            declaration = template['scenes'][scene]
            self.assertEqual(declaration['scene'], scene)
            self.assertEqual(declaration['capture_provenance']['scene'], scene)
            self.assertEqual(
                (declaration['expected_presence'],
                 declaration['expected_bottle_relation']), expected[scene])

    def test_frozen_six_topic_manifest_identity_matches_bytes(self):
        template = _template()
        manifest = _load(TOPIC_MANIFEST_PATH)
        raw = TOPIC_MANIFEST_PATH.read_bytes()
        binding = template['frozen_topic_manifest']
        self.assertEqual(manifest['manifest_id'], binding['manifest_id'])
        self.assertEqual(tuple(item['name'] for item in manifest['topics']),
                         TOPICS)
        self.assertEqual(tuple(binding['topics']), TOPICS)
        self.assertEqual(binding['size_bytes'], len(raw))
        self.assertEqual(binding['size_bytes'], 1969)
        self.assertEqual(binding['sha256'], hashlib.sha256(raw).hexdigest())

    def test_artifact_provenance_and_unique_output_contract_is_complete(self):
        template = _template()
        planned = template['capture_policy'][
            'planned_exclusive_output_paths']
        self.assertTrue(
            planned == [] or (len(planned) == 52
                              and len(set(planned)) == 52))
        for scene in SCENES:
            declaration = template['scenes'][scene]
            self.assertEqual(set(declaration['artifacts']), ARTIFACT_KEYS)
            self.assertEqual(
                set(declaration['capture_provenance']), PROVENANCE_KEYS)
            self.assertIs(declaration['exclusive_new_files'], True)
        completed = _completed_intake()
        self.assertEqual(len(completed['capture_policy'][
            'planned_exclusive_output_paths']), 52)
        _assert_completed_rejected(lambda item: item['scenes']['background'][
            'artifacts'].__setitem__('ground_truth', None))
        _assert_completed_rejected(lambda item: item['global_artifacts'][
            'runtime_preflight'].__setitem__('sha256', 'not-a-sha256'))
        _assert_completed_rejected(lambda item: item['scenes']['bin_only'][
            'artifacts']['ground_truth'].__setitem__(
                'path', item['scenes']['background']['artifacts'][
                    'ground_truth']['path']))

    def test_setup_installs_both_intake_artifacts(self):
        setup = SETUP_PATH.read_text(encoding='utf-8')
        self.assertIn(
            "'fixtures/perception_field_intake.schema.json'", setup)
        self.assertIn(
            "'fixtures/perception_field_intake_template.json'", setup)

    def test_rejects_missing_or_extra_scene(self):
        _assert_rejected(lambda item: item['scenes'].pop('background'))
        _assert_rejected(lambda item: item['scenes'].__setitem__(
            'alias_background', copy.deepcopy(item['scenes']['background'])))

    def test_rejects_low_or_inconsistent_frame_policy(self):
        _assert_rejected(lambda item: item['capture_policy'].__setitem__(
            'min_unique_typed_frames_per_scene', 29))
        _assert_rejected(lambda item: item['capture_policy'].__setitem__(
            'target_unique_typed_frames_per_scene', 29))
        _assert_rejected(lambda item: item['scenes']['background'].__setitem__(
            'min_unique_typed_frames', 29))
        _assert_rejected(lambda item: item['scenes']['background'].__setitem__(
            'target_unique_typed_frames', 29))

    def test_rejects_duplicate_or_partial_planned_paths(self):
        _assert_rejected(lambda item: item['capture_policy'].__setitem__(
            'planned_exclusive_output_paths', ['same.json'] * 52))
        _assert_rejected(lambda item: item['capture_policy'].__setitem__(
            'planned_exclusive_output_paths', [
                'path-{}.json'.format(index) for index in range(51)]))
        _assert_completed_rejected(lambda item: item['scenes']['bin_only']
                                   .__setitem__('capture_id', item['scenes'][
                                       'background']['capture_id']))
        _assert_completed_rejected(lambda item: item['scenes']['bin_only']
                                   .__setitem__('task_id', item['scenes'][
                                       'background']['task_id']))
        _assert_completed_rejected(lambda item: item['capture_policy'][
            'planned_exclusive_output_paths'].__setitem__(0, 'wrong.json'))

    def test_rejects_topic_alias_scene_alias_and_provenance_mismatch(self):
        _assert_rejected(lambda item: item['frozen_topic_manifest']['topics']
                         .append('/cleanup/perception/frames'))
        _assert_rejected(lambda item: item['capture_policy'][
            'raw_topics_exact'].__setitem__(0, '/camera/color/image'))
        _assert_rejected(lambda item: item['scenes']['background'][
            'capture_provenance'].__setitem__('scene', 'bin_only'))
        _assert_rejected(lambda item: item['frozen_topic_manifest']
                         .__setitem__('manifest_id', 'alias-v1'))
        _assert_rejected(lambda item: item['frozen_topic_manifest']
                         .__setitem__('sha256', '0' * 64))
        _assert_completed_rejected(lambda item: item['scenes']['background'][
            'capture_provenance'].__setitem__('release_id', 'other-release'))

    def test_rejects_motion_delivery_claim_and_readiness_scope(self):
        _assert_rejected(
            lambda item: item.__setitem__('authorizes_motion', True))
        _assert_rejected(lambda item: item.__setitem__(
            'publishes_control_messages', True))
        _assert_rejected(
            lambda item: item.__setitem__('delivery_ready', True))
        _assert_rejected(lambda item: item.__setitem__(
            'intake_scope', 'formal_four_scene_rgbd_acceptance'))
        _assert_rejected(lambda item: item.__setitem__(
            'evidence_scope', 'formal_four_scene_rgbd_acceptance'))
        _assert_completed_rejected(lambda item: item['authorization'][
            'preconditions'].__setitem__('physical_estop_available', None))
        _assert_completed_rejected(lambda item: item['authorization'][
            'preconditions'].__setitem__(
                'ros2_control_graph_confirmed_inactive', False))
        _assert_completed_rejected(lambda item: item['authorization']
                                   .__setitem__(
                                       'expires_at_unix_sec', 999.0))
        _assert_completed_rejected(lambda item: item['scenes']['background'][
            'capture_window'].__setitem__('ended_unix_sec', 100.0))
        _assert_completed_rejected(lambda item: item['global_artifacts']
                                   .__setitem__('hardware_readiness', None))


if __name__ == '__main__':
    unittest.main()

from pathlib import Path
import copy
import json
import math
import sys
import tempfile
import unittest
from types import MappingProxyType


PACKAGE_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / 'src'))

from limo_v1_navigation.apriltag_docking_contract import (  # noqa: E402
    CALIBRATION_SCHEMA_VERSION,
    SIDES,
    object_for_tag,
)
from limo_v1_navigation.tag_docking_adapter import (  # noqa: E402
    AdapterError,
    BoundTagPose,
    CALIBRATION_IDENTITY_SCHEMA,
    CALIBRATION_SHA256_BASIS,
    SOURCE_BUNDLE_SCHEMA,
    adapt_observation_to_map_pose,
    calibration_identity_from_calibration,
    canonical_calibration_payload,
    canonical_observation_sha256,
)
from limo_v1_navigation.tag_docking_policy import (  # noqa: E402
    DockingPolicyError,
    PREAPPROACH,
    SIDE_LABELS,
    compute_base_goal,
    load_config,
    validate_config,
)


class TagDockingPolicyAdapterTest(unittest.TestCase):

    def _calibration(self):
        return json.loads((PACKAGE_ROOT / 'fixtures' /
                           'apriltag_tag_docking_calibration_ready.json').read_text())

    def _valid_config(self):
        value = json.loads((PACKAGE_ROOT / 'config' /
                            'v1_apriltag_docking.template.json').read_text())
        value['template_only'] = False
        value['measurement_status'] = 'MEASURED_VERIFIED'
        for index, tag in enumerate(value['field_tags']):
            tag['measured'] = True
            tag['pose_map']['position_xyz'] = [float(index), 0.0, 0.3]
            tag['pose_map']['orientation_xyzw'] = [0.0, 0.0, 0.0, 1.0]
        value['geofence'].update({
            'measured': True,
            'polygon_map': [
                {'x': -5.0, 'y': -5.0}, {'x': 5.0, 'y': -5.0},
                {'x': 5.0, 'y': 5.0}, {'x': -5.0, 'y': 5.0},
            ],
            'boundary_margin_m': 0.2,
            'base_footprint_radius_m': 0.3,
        })
        for record in value['objects']:
            record['dimensions_m'] = {
                'length': 0.4, 'width': 0.3, 'height': 0.5}
            record['mount_verified'] = True
        value['calibration']['canonical_payload'] = (
            canonical_calibration_payload(self._calibration()))
        return value

    def _identity(self):
        return calibration_identity_from_calibration(self._calibration())

    def _observation(self):
        return json.loads((PACKAGE_ROOT / 'fixtures' /
                           'apriltag_static_observations_valid.json').read_text())[
                               'observations'][0]

    def _bundle(self, observation=None):
        observation = copy.deepcopy(observation or self._observation())
        digest = canonical_observation_sha256(observation)
        timestamp = observation['timestamp_ns']
        return {
            'schema_version': SOURCE_BUNDLE_SCHEMA,
            'observation_sha256': digest,
            'observation': observation,
            'tf_geometry': {
                'observation_sha256': digest,
                'timestamp_ns': timestamp,
                'map_to_base_link': {
                    'parent_frame': 'map', 'child_frame': 'base_link',
                    'timestamp_ns': timestamp,
                    'translation_m': {'x': 1.0, 'y': 2.0, 'z': -1.0},
                    'orientation_xyzw': {
                        'x': 0.0, 'y': 0.0, 'z': 0.0, 'w': 1.0},
                },
                'base_link_to_camera': {
                    'parent_frame': 'base_link',
                    'child_frame': 'camera_color_optical_frame',
                    'timestamp_ns': timestamp,
                    'translation_m': {'x': 0.1, 'y': 0.0, 'z': 0.3},
                    'orientation_xyzw': {
                        'x': 0.0, 'y': 0.0, 'z': 0.0, 'w': 1.0},
                    'calibration_sha256': self._identity()['sha256'],
                },
            },
            'calibration_payload': canonical_calibration_payload(
                self._calibration()),
            'calibration_identity': self._identity(),
        }

    def _adapt(self, bundle=None, host_now_ns=1234567990):
        return adapt_observation_to_map_pose(
            bundle or self._bundle(), host_now_ns=host_now_ns,
            max_age_ns=250000000,
            expected_calibration_identity=self._identity())

    def test_visual_and_planning_contract_share_one_exact_side_mapping(self):
        self.assertIs(SIDE_LABELS, SIDES)
        config = validate_config(self._valid_config())
        self.assertEqual(set(config['tag_map']), set(range(12)))
        for tag_id in range(12):
            visual = object_for_tag(tag_id)
            planning = config['tag_map'][tag_id]
            self.assertEqual(planning, {
                'object_id': visual['object_index'],
                'side_index': tag_id % 4,
                'side_label': visual['side'],
            })

    def test_swapped_duplicate_missing_and_permuted_mapping_abort(self):
        cases = []
        swapped_labels = self._valid_config()
        swapped_labels['objects'][0]['tags'][0]['side_label'] = 'right'
        swapped_labels['objects'][0]['tags'][1]['side_label'] = 'front'
        cases.append(('swapped_labels', swapped_labels))
        swapped_ids = self._valid_config()
        swapped_ids['objects'][0]['tags'][0]['id'] = 1
        swapped_ids['objects'][0]['tags'][1]['id'] = 0
        cases.append(('swapped_ids', swapped_ids))
        duplicate = self._valid_config()
        duplicate['objects'][0]['tags'][1]['id'] = 0
        cases.append(('duplicate_id', duplicate))
        missing = self._valid_config()
        missing['objects'][0]['tags'].pop()
        cases.append(('missing_tag', missing))
        side_permutation = self._valid_config()
        side_permutation['objects'][1]['tags'].reverse()
        cases.append(('record_permutation', side_permutation))
        object_permutation = self._valid_config()
        object_permutation['objects'].reverse()
        cases.append(('object_permutation', object_permutation))
        for name, value in cases:
            with self.subTest(name=name):
                with self.assertRaisesRegex(
                        DockingPolicyError, 'INVALID_OBJECT_MAP'):
                    validate_config(value)

    def test_object_tag_and_side_ids_require_exact_int_not_bool_or_float(self):
        paths = (
            ('field_tag_id', ('field_tags', 0, 'id')),
            ('object_id', ('objects', 0, 'object_id')),
            ('tag_id', ('objects', 0, 'tags', 0, 'id')),
            ('side_index', ('objects', 0, 'tags', 0, 'side_index')),
        )
        for name, path in paths:
            for replacement in (False, 0.0):
                value = self._valid_config()
                target = value
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = replacement
                with self.subTest(name=name, replacement=replacement):
                    with self.assertRaises(DockingPolicyError):
                        validate_config(value)

    def test_strict_loader_rejects_duplicate_nonfinite_and_trailing_json(self):
        valid = self._valid_config()
        raw = json.dumps(valid, sort_keys=True, separators=(',', ':'))
        invalid = {
            'duplicate': '{"schema":"duplicate",' + raw[1:],
            'nan': raw.replace(
                '"boundary_margin_m":0.2', '"boundary_margin_m":NaN', 1),
            'infinity': raw.replace(
                '"boundary_margin_m":0.2',
                '"boundary_margin_m":Infinity', 1),
            'trailing': raw + '\n{}',
        }
        bool_id = copy.deepcopy(valid)
        bool_id['objects'][0]['tags'][0]['id'] = False
        invalid['bool_id'] = json.dumps(bool_id, separators=(',', ':'))
        with tempfile.TemporaryDirectory(prefix='tag_docking_strict_json_') as temp:
            temp = Path(temp)
            valid_path = temp / 'valid.json'
            valid_path.write_text(raw, encoding='utf-8')
            self.assertEqual(len(load_config(valid_path)['tag_map']), 12)
            for name, content in invalid.items():
                path = temp / (name + '.json')
                path.write_text(content, encoding='utf-8')
                with self.subTest(name=name):
                    with self.assertRaisesRegex(
                            DockingPolicyError,
                            ('INVALID_OBJECT_MAP' if name == 'bool_id'
                             else 'CONFIG_READ_FAILED')):
                        load_config(path)

    def test_adapter_mechanically_composes_deterministic_map_pose(self):
        bound = self._adapt()
        self.assertTrue(bound.is_source_bound())
        self.assertEqual(bound.target_family, 'tag52h13')
        self.assertEqual(bound.target_id, 5)
        self.assertEqual(bound.object_id, 1)
        self.assertEqual(bound.side_index, 1)
        self.assertEqual(bound.side_label, 'right')
        self.assertEqual(
            bound.calibration_sha256, self._identity()['sha256'])
        expected = [1.2, 1.98, -0.3]
        for actual, wanted in zip(bound.pose_map['position_xyz'], expected):
            self.assertAlmostEqual(actual, wanted, places=12)
        self.assertEqual(bound.pose_map['frame_id'], 'map')
        self.assertEqual(
            bound.pose_map['orientation_xyzw'], (0.0, 0.0, 0.0, 1.0))

    def test_policy_rejects_raw_pose_and_consumes_only_sealed_adapter_output(self):
        config_value = self._valid_config()
        config_value['safety']['max_base_goal_z_m'] = 2.0
        config = validate_config(config_value)
        with self.assertRaisesRegex(DockingPolicyError, 'TAG_SOURCE_UNBOUND'):
            compute_base_goal(
                config, {'frame_id': 'map'}, 0.9, PREAPPROACH)
        with self.assertRaisesRegex(
                AdapterError, 'direct_construction_forbidden'):
            BoundTagPose({}, 1, 1, 1.0, '0' * 64, '0' * 64, {})

        observation = self._observation()
        observation['camera_frame_pose']['translation_m'] = {
            'x': 0.0, 'y': 0.0, 'z': 0.7}
        observation['camera_frame_pose']['orientation_xyzw'] = {
            'x': 0.0, 'y': 1.0, 'z': 0.0, 'w': 0.0}
        bound = self._adapt(self._bundle(observation))
        goal = compute_base_goal(config, bound, 0.9, PREAPPROACH)
        self.assertEqual(goal.target_id, 5)
        self.assertAlmostEqual(goal.base_x, 1.0, places=12)
        self.assertAlmostEqual(goal.base_y, 2.0, places=12)

        identity_mismatch = self._valid_config()
        identity_mismatch['calibration']['canonical_payload']['calibration'][
            'base_link_to_camera_extrinsics']['translation_m']['x'] = 0.2
        with self.assertRaisesRegex(DockingPolicyError, 'TAG_SOURCE_UNBOUND'):
            compute_base_goal(
                validate_config(identity_mismatch), bound, 0.9, PREAPPROACH)

    def test_bound_pose_is_deeply_immutable_and_digest_covers_every_field(self):
        bound = self._adapt()
        original_digest = bound.bound_digest_sha256
        with self.assertRaises(TypeError):
            bound.pose_map['frame_id'] = 'odom'
        with self.assertRaises(TypeError):
            bound.pose_map['position_xyz'][0] = 99.0
        for field in (
                'target_family', 'target_id', 'object_id', 'side_index',
                'side_label', 'timestamp_ns', 'age_ns', 'confidence',
                'calibration_sha256', 'source_sha256', 'pose_map'):
            with self.subTest(public_field=field):
                with self.assertRaises(AdapterError):
                    setattr(bound, field, None)
        self.assertEqual(bound.bound_digest_sha256, original_digest)
        self.assertTrue(bound.is_source_bound())

        config = validate_config(self._valid_config())
        internal_mutations = (
            ('_target_family', 'tag36h11'), ('_target_id', 6),
            ('_object_id', 2), ('_side_index', 2), ('_side_label', 'back'),
            ('_timestamp_ns', bound.timestamp_ns + 1),
            ('_age_ns', bound.age_ns + 1), ('_confidence', 0.1),
            ('_calibration_sha256', '0' * 64),
            ('_calibration_translation', (9.0, 0.0, 0.3)),
            ('_calibration_orientation', (0.0, 1.0, 0.0, 0.0)),
            ('_source_sha256', '1' * 64),
            ('_pose_map', MappingProxyType({
                'frame_id': 'map', 'position_xyz': (99.0, 0.0, 0.0),
                'orientation_xyzw': (0.0, 0.0, 0.0, 1.0)})),
        )
        for field, replacement in internal_mutations:
            candidate = self._adapt()
            object.__setattr__(candidate, field, replacement)
            with self.subTest(internal_field=field):
                self.assertFalse(candidate.is_source_bound())
                with self.assertRaisesRegex(
                        DockingPolicyError, 'TAG_SOURCE_UNBOUND'):
                    compute_base_goal(config, candidate, 0.9, PREAPPROACH)

    def test_source_alias_and_snapshot_toctou_cannot_change_policy_input(self):
        bundle = self._bundle()
        bound = self._adapt(bundle)
        snapshot = bound.verified_snapshot()
        bundle['observation']['target']['id'] = 9
        bundle['observation']['camera_frame_pose']['translation_m']['x'] = 99.0
        bundle['tf_geometry']['map_to_base_link']['translation_m']['x'] = 99.0
        self.assertEqual(bound.target_id, 5)
        self.assertEqual(bound.pose_map['position_xyz'], snapshot.pose_map['position_xyz'])
        self.assertEqual(
            bound.bound_digest_sha256, snapshot.bound_digest_sha256)

        config_value = self._valid_config()
        config_value['safety']['max_base_goal_z_m'] = 2.0
        normalized = validate_config(config_value)
        original_translation = normalized['calibration_binding']['translation']
        config_value['calibration']['canonical_payload']['calibration'][
            'base_link_to_camera_extrinsics']['translation_m']['x'] = 9.0
        self.assertEqual(
            normalized['calibration_binding']['translation'],
            original_translation)
        with self.assertRaises(TypeError):
            normalized['calibration_binding']['translation'] = (9.0, 0.0, 0.0)

    def test_adapter_rejects_external_pose_camera_as_map_and_wrong_direction(self):
        external_pose = self._bundle()
        external_pose['pose_map'] = {
            'frame_id': 'map', 'position_xyz': [0, 0, 0],
            'orientation_xyzw': [0, 0, 0, 1]}
        camera_as_map = self._bundle()
        camera_as_map['observation']['camera_frame_pose']['frame_id'] = 'map'
        camera_as_map['observation_sha256'] = canonical_observation_sha256(
            camera_as_map['observation'])
        camera_as_map['tf_geometry']['observation_sha256'] = (
            camera_as_map['observation_sha256'])
        wrong_map_direction = self._bundle()
        wrong_map_direction['tf_geometry']['map_to_base_link'].update({
            'parent_frame': 'base_link', 'child_frame': 'map'})
        wrong_camera_direction = self._bundle()
        wrong_camera_direction['tf_geometry']['base_link_to_camera'].update({
            'parent_frame': 'camera_color_optical_frame',
            'child_frame': 'base_link'})
        for name, bundle in (
                ('external_pose_map', external_pose),
                ('camera_as_map', camera_as_map),
                ('wrong_map_direction', wrong_map_direction),
                ('wrong_camera_direction', wrong_camera_direction)):
            with self.subTest(name=name):
                with self.assertRaises(AdapterError):
                    self._adapt(bundle)

    def test_adapter_rejects_stale_unsynchronised_and_source_swapped_inputs(self):
        stale = self._bundle()
        time_mismatch = self._bundle()
        time_mismatch['tf_geometry']['map_to_base_link']['timestamp_ns'] += 1
        source_swap = self._bundle()
        source_swap['tf_geometry']['observation_sha256'] = '1' * 64
        target_swap = self._bundle()
        target_swap['observation']['target']['id'] = 6
        target_swap['observation_sha256'] = canonical_observation_sha256(
            target_swap['observation'])
        target_swap['tf_geometry']['observation_sha256'] = (
            target_swap['observation_sha256'])
        cases = (
            ('stale', stale, 1484567890),
            ('time_mismatch', time_mismatch, 1234567990),
            ('source_swap', source_swap, 1234567990),
            ('target_swap', target_swap, 1234567990),
        )
        for name, bundle, now in cases:
            with self.subTest(name=name):
                with self.assertRaises(AdapterError):
                    self._adapt(bundle, host_now_ns=now)

    def test_adapter_rejects_calibration_identity_mismatch_everywhere(self):
        supplied_mismatch = self._bundle()
        supplied_mismatch['calibration_identity']['sha256'] = '2' * 64
        tf_mismatch = self._bundle()
        tf_mismatch['tf_geometry']['base_link_to_camera'][
            'calibration_sha256'] = '3' * 64
        expected_mismatch = self._identity()
        expected_mismatch['sha256'] = '4' * 64
        with self.assertRaisesRegex(AdapterError, 'calibration_identity_mismatch'):
            self._adapt(supplied_mismatch)
        with self.assertRaisesRegex(AdapterError, 'calibration_identity_mismatch'):
            self._adapt(tf_mismatch)
        with self.assertRaisesRegex(AdapterError, 'calibration_identity_mismatch'):
            adapt_observation_to_map_pose(
                self._bundle(), host_now_ns=1234567990,
                max_age_ns=250000000,
                expected_calibration_identity=expected_mismatch)


if __name__ == '__main__':
    unittest.main()

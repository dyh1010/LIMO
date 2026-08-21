from pathlib import Path
from contextlib import redirect_stdout
import copy
import io
import json
import sys
import tempfile
import unittest


PACKAGE_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / 'src'))
sys.path.insert(0, str(PACKAGE_ROOT / 'scripts'))

from limo_v1_navigation.apriltag_docking_contract import (  # noqa: E402
    ContractError,
    OBJECT_FAMILY,
    abort_observation,
    target_descriptor,
    validate_calibration,
    validate_inventory,
    validate_observation,
)
import validate_apriltag_docking_static as static_validator  # noqa: E402


class AprilTagDockingContractTest(unittest.TestCase):

    def setUp(self):
        inventory = json.loads((PACKAGE_ROOT / 'config' /
                                'apriltag_tag_docking_inventory.json').read_text())
        self.entries = (inventory['fixed_field_tags'] +
                        inventory['movable_object_tags'])

    def _observation(self, **changes):
        value = {
            'schema_version': 'limo_apriltag_docking_observation/v1',
            'target': target_descriptor(OBJECT_FAMILY, 5),
            'timestamp_ns': 1234567890,
            'visible': True,
            'camera_frame_pose': {
                'frame_id': 'camera_color_optical_frame',
                'translation_m': {'x': 0.1, 'y': -0.02, 'z': 0.4},
                'orientation_xyzw': {'x': 0.0, 'y': 0.0, 'z': 0.0, 'w': 1.0},
            },
            'quality': {'confidence': 0.9, 'reprojection_error_px': 0.4},
            'tf_inputs': {
                'map_to_base_link': {
                    'available': True, 'parent_frame': 'map',
                    'child_frame': 'base_link', 'timestamp_ns': 1234567890,
                },
                'base_link_to_camera': {
                    'available': True, 'parent_frame': 'base_link',
                    'child_frame': 'camera_color_optical_frame',
                    'timestamp_ns': 1234567890,
                },
            },
            'decision': 'ACCEPT',
            'failure_reason': None,
        }
        value.update(changes)
        return value

    def _calibration(self):
        return json.loads((PACKAGE_ROOT / 'fixtures' /
                           'apriltag_tag_docking_calibration_ready.json').read_text())

    @staticmethod
    def _field_paths(value, prefix=()):
        """Yield every required JSON object field, including objects in arrays."""
        paths = []
        if isinstance(value, dict):
            for key, child in value.items():
                path = prefix + (key,)
                paths.append(path)
                paths.extend(AprilTagDockingContractTest._field_paths(
                    child, path))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                paths.extend(AprilTagDockingContractTest._field_paths(
                    child, prefix + (index,)))
        return paths

    @staticmethod
    def _scalar_paths(value, prefix=()):
        """Yield scalar leaves, including distortion coefficients in arrays."""
        if isinstance(value, dict):
            paths = []
            for key, child in value.items():
                paths.extend(AprilTagDockingContractTest._scalar_paths(
                    child, prefix + (key,)))
            return paths
        if isinstance(value, list):
            paths = []
            for index, child in enumerate(value):
                paths.extend(AprilTagDockingContractTest._scalar_paths(
                    child, prefix + (index,)))
            return paths
        return [prefix]

    @staticmethod
    def _parent_at_path(value, path):
        target = value
        for key in path[:-1]:
            target = target[key]
        return target, path[-1]

    def test_exact_inventory_has_four_fixed_and_twelve_object_faces(self):
        self.assertEqual(validate_inventory(self.entries), {
            'fixed_tag_count': 4, 'object_tag_count': 12,
            'object_count': 3, 'object_sides_per_object': 4,
        })

    def test_wrong_family_duplicate_and_missing_face_fail_closed(self):
        bad_family = list(self.entries)
        bad_family[0] = {'family': 'tag52h13', 'id': 0}
        duplicate = list(self.entries) + [dict(self.entries[-1])]
        missing = self.entries[:-1]
        for entries in (bad_family, duplicate, missing):
            with self.subTest(entries=entries[-1]):
                with self.assertRaises(ContractError):
                    validate_inventory(entries)
        with self.assertRaisesRegex(ContractError, 'unknown_object_tag_id'):
            target_descriptor(OBJECT_FAMILY, False)

    def test_observation_accepts_camera_pose_and_tf_inputs_not_map_pose(self):
        result = validate_observation(
            self._observation(), host_now_ns=1234567990)
        self.assertEqual(result['decision'], 'ACCEPT')
        self.assertFalse(result['map_pose_provided'])
        self.assertEqual(result['freshness_owner'], 'host_now_ns')

    def test_low_quality_missing_tf_hidden_or_fabricated_map_pose_abort(self):
        cases = (
            self._observation(quality={'confidence': 0.69,
                                       'reprojection_error_px': 0.4}),
            self._observation(visible=False),
            self._observation(tf_inputs={}),
            self._observation(map_pose={'frame_id': 'map'}),
        )
        for observation in cases:
            with self.subTest(observation=observation):
                with self.assertRaises(ContractError):
                    validate_observation(observation, host_now_ns=1234567990)

    def test_observation_freshness_is_owned_by_host_now_and_fails_closed(self):
        observation = self._observation()
        cases = (
            (1234567889, 250000000, 'observation_from_future'),
            (1484567890, 250000000, 'observation_stale'),
            (1234567890, 0, 'max_observation_age_invalid'),
        )
        for host_now_ns, max_age_ns, reason in cases:
            with self.subTest(reason=reason):
                with self.assertRaisesRegex(ContractError, reason):
                    validate_observation(
                        observation, host_now_ns=host_now_ns,
                        max_age_ns=max_age_ns)

        old_synchronised = self._observation(timestamp_ns=1000000000)
        for tf_value in old_synchronised['tf_inputs'].values():
            tf_value['timestamp_ns'] = 1000000000
        with self.assertRaisesRegex(ContractError, 'observation_stale'):
            validate_observation(
                old_synchronised, host_now_ns=1250000000,
                max_age_ns=250000000)

    def test_calibration_requires_all_schema_geometry_and_installation_fields(self):
        self.assertEqual(validate_calibration(self._calibration())['decision'], 'ACCEPT')
        reference = self._calibration()
        field_paths = self._field_paths(reference)
        self.assertGreater(len(field_paths), 80)
        for path in field_paths:
            calibration = copy.deepcopy(self._calibration())
            target, key = self._parent_at_path(calibration, path)
            target.pop(key)
            with self.subTest(mutation='delete', path=path):
                with self.assertRaises(ContractError):
                    validate_calibration(calibration)

        mutation_paths = set(field_paths + self._scalar_paths(reference))
        for replacement in (None, False):
            for path in sorted(mutation_paths, key=repr):
                calibration = copy.deepcopy(reference)
                target, key = self._parent_at_path(calibration, path)
                target[key] = replacement
                with self.subTest(mutation=repr(replacement), path=path):
                    with self.assertRaises(ContractError):
                        validate_calibration(calibration)

    def test_calibration_types_ranges_frames_quaternion_and_measurements_abort(self):
        cases = (
            (('schema_version',), 'wrong/schema'),
            (('status',), 'UNFILLED_ABORT'),
            (('recorded_timestamp_ns',), 0),
            (('camera_intrinsics', 'camera_frame'), 'camera_link'),
            (('camera_intrinsics', 'image_width_px'), 640.0),
            (('camera_intrinsics', 'image_height_px'), 8),
            (('camera_intrinsics', 'fx'), 0.0),
            (('camera_intrinsics', 'cx'), 640.0),
            (('camera_intrinsics', 'distortion_model'), 'unknown'),
            (('camera_intrinsics', 'distortion_coefficients'), [0.0] * 3),
            (('camera_intrinsics', 'calibration_timestamp_ns'), 1234567001),
            (('base_link_to_camera_extrinsics', 'parent_frame'), 'odom'),
            (('base_link_to_camera_extrinsics', 'child_frame'), 'camera_link'),
            (('base_link_to_camera_extrinsics', 'translation_m', 'x'), 2.01),
            (('base_link_to_camera_extrinsics', 'orientation_xyzw', 'w'), 0.5),
            (('base_link_to_camera_extrinsics', 'calibration_timestamp_ns'), 1234567001),
            (('tag_installation_checklist', 'field_tag_size_m'), 0.17),
            (('tag_installation_checklist', 'object_tag_size_m'), 0.17),
            (('tag_installation_checklist', 'installation_verified_timestamp_ns'), 1234567001),
            (('tag_installation_checklist', 'fixed_field_tag_measurements', 0, 'id'), False),
            (('tag_installation_checklist', 'fixed_field_tag_measurements', 0, 'frame_id'), 'odom'),
            (('tag_installation_checklist', 'fixed_field_tag_measurements', 0,
              'position_m', 'x'), 100.01),
            (('tag_installation_checklist', 'fixed_field_tag_measurements', 0,
              'position_m', 'yaw'), 3.142),
            (('tag_installation_checklist', 'object_dimensions_m', 0,
              'object_index'), False),
            (('tag_installation_checklist', 'object_dimensions_m', 0,
              'length'), 5.01),
            (('tag_installation_checklist', 'object_tag_center_height_m'), 0.51),
            (('tag_installation_checklist', 'tag_flatness_checked'), False),
        )
        for path, replacement in cases:
            calibration = copy.deepcopy(self._calibration())
            target, key = self._parent_at_path(calibration, path)
            target[key] = replacement
            with self.subTest(path=path, replacement=replacement):
                with self.assertRaises(ContractError):
                    validate_calibration(calibration)

    def test_static_consumer_rejects_incomplete_calibration_and_stale_bundle(self):
        inventory_path = PACKAGE_ROOT / 'config' / 'apriltag_tag_docking_inventory.json'
        calibration_path = PACKAGE_ROOT / 'fixtures' / 'apriltag_tag_docking_calibration_ready.json'
        observations_path = PACKAGE_ROOT / 'fixtures' / 'apriltag_static_observations_valid.json'
        with tempfile.TemporaryDirectory(prefix='apriltag_static_contract_') as temp:
            temp = Path(temp)
            incomplete = self._calibration()
            incomplete['camera_intrinsics'].pop('distortion_model')
            incomplete_path = temp / 'incomplete_calibration.json'
            incomplete_path.write_text(json.dumps(incomplete), encoding='utf-8')
            output = io.StringIO()
            with redirect_stdout(output):
                return_code = static_validator.main([
                    '--inventory', str(inventory_path),
                    '--observations', str(observations_path),
                    '--calibration', str(incomplete_path),
                    '--host-now-ns', '1234567990',
                    '--max-observation-age-ns', '250000000',
                ])
            result = json.loads(output.getvalue())
            self.assertEqual(return_code, 3)
            self.assertEqual(result['decision'], 'ABORT')
            self.assertFalse(result['motion_authorized'])

            stale = json.loads(observations_path.read_text())
            observation = stale['observations'][0]
            observation['timestamp_ns'] = 1000000000
            for tf_value in observation['tf_inputs'].values():
                tf_value['timestamp_ns'] = 1000000000
            stale_path = temp / 'stale_observation_and_tf.json'
            stale_path.write_text(json.dumps(stale), encoding='utf-8')
            output = io.StringIO()
            with redirect_stdout(output):
                return_code = static_validator.main([
                    '--inventory', str(inventory_path),
                    '--observations', str(stale_path),
                    '--calibration', str(calibration_path),
                    '--host-now-ns', '1250000000',
                    '--max-observation-age-ns', '250000000',
                ])
            result = json.loads(output.getvalue())
            self.assertEqual(return_code, 3)
            self.assertEqual(result['decision'], 'ABORT')
            self.assertEqual(
                result['aborted_observation_reasons'], ['observation_stale'])
            self.assertFalse(result['motion_authorized'])

    def test_abort_payload_never_extrapolates_success(self):
        result = abort_observation(OBJECT_FAMILY, 9, 123, 'tag_not_visible')
        self.assertEqual(result['decision'], 'ABORT')
        self.assertIsNone(result['camera_frame_pose'])
        self.assertIsNone(result['tf_inputs'])
        self.assertEqual(result['target']['object_index'], 2)
        self.assertEqual(result['target']['side'], 'right')


if __name__ == '__main__':
    unittest.main()

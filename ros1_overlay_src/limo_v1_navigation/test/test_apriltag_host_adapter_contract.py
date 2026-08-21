from pathlib import Path
import copy
import json
import sys
import unittest


PACKAGE_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / 'src'))

from limo_v1_navigation.apriltag_host_adapter_contract import (  # noqa: E402
    AdapterContractError,
    calibration_identity,
    derive_bound_tag_pose,
    validate_mapping_authority,
)
from limo_v1_navigation.tag_docking_policy import (  # noqa: E402
    DockingPolicyError,
    FINAL_DOCKING,
    compute_base_goal,
)
from limo_v1_navigation.tag_docking_adapter import AdapterError  # noqa: E402


class AprilTagHostAdapterContractTest(unittest.TestCase):

    def _json(self, relative):
        return json.loads((PACKAGE_ROOT / relative).read_text(encoding='utf-8'))

    def _record(self):
        calibration = self._json('fixtures/apriltag_tag_docking_calibration_ready.json')
        observation = self._json('fixtures/apriltag_static_observations_valid.json')['observations'][0]
        return {
            'schema_version': 'limo_apriltag_host_observation_record/v1',
            'record_id': 'host-observation-001',
            'expected_target': {'family': 'tag52h13', 'id': 5},
            'observation': observation,
            'tf_snapshot': {
                'record_id': 'host-observation-001',
                'observation_sha256': '',
                'timestamp_ns': observation['timestamp_ns'],
                'map_to_base_link': {
                    'parent_frame': 'map', 'child_frame': 'base_link',
                    'timestamp_ns': observation['timestamp_ns'],
                    'translation_m': {'x': 1.0, 'y': 2.0, 'z': 0.0},
                    'orientation_xyzw': {'x': 0.0, 'y': 0.0, 'z': 0.0, 'w': 1.0},
                },
                'base_link_to_camera': {
                    'parent_frame': 'base_link', 'child_frame': 'camera_color_optical_frame',
                    'timestamp_ns': observation['timestamp_ns'],
                    'translation_m': {'x': 0.1, 'y': 0.0, 'z': 0.3},
                    'orientation_xyzw': {'x': 0.0, 'y': 0.0, 'z': 0.0, 'w': 1.0},
                    'calibration_sha256': '',
                },
            },
            'calibration': calibration,
            'calibration_identity': calibration_identity(calibration),
        }

    def _authority(self):
        return self._json('config/apriltag_tag_docking_inventory.json')

    def _v1_template(self):
        return self._json('config/v1_apriltag_docking.template.json')

    def test_fixture_binds_all_twelve_ids_to_one_shared_vocabulary(self):
        expected = self._json('fixtures/apriltag_cross_contract_mapping_fixture.json')['expected']
        mapping = validate_mapping_authority(self._authority(), self._v1_template())
        self.assertEqual(mapping, {int(key): value for key, value in expected.items()})

    def _bound_record(self):
        record = self._record()
        from limo_v1_navigation.tag_docking_adapter import canonical_observation_sha256
        digest = canonical_observation_sha256(record['observation'])
        record['tf_snapshot']['observation_sha256'] = digest
        record['tf_snapshot']['base_link_to_camera']['calibration_sha256'] = (
            record['calibration_identity']['sha256'])
        return record

    def test_host_adapter_derives_sealed_pose_from_camera_pose_and_same_record_tf(self):
        result = derive_bound_tag_pose(
            self._bound_record(), self._authority(), self._v1_template(), 1234567990)
        self.assertTrue(result.is_source_bound())
        self.assertEqual(result.target_family, 'tag52h13')
        self.assertEqual(result.target_id, 5)
        self.assertEqual(result.side_label, 'right')
        self.assertEqual(result.pose_map['frame_id'], 'map')
        self.assertAlmostEqual(result.pose_map['position_xyz'][0], 1.2)
        self.assertAlmostEqual(result.pose_map['position_xyz'][1], 1.98)
        self.assertAlmostEqual(result.pose_map['position_xyz'][2], 0.7)

    def test_bound_pose_and_its_projection_are_immutable(self):
        result = derive_bound_tag_pose(
            self._bound_record(), self._authority(), self._v1_template(), 1234567990)
        with self.assertRaises(AdapterError):
            result.target_id = 6
        projection = result.pose_map
        with self.assertRaises(TypeError):
            projection['position_xyz'][0] = 999.0
        self.assertAlmostEqual(result.pose_map['position_xyz'][0], 1.2)

    def test_policy_rejects_caller_supplied_map_pose(self):
        forged_map_pose = {
            'frame_id': 'map', 'position_xyz': [1.2, 1.98, 0.7],
            'orientation_xyzw': [0.0, 0.0, 0.0, 1.0],
        }
        with self.assertRaises(DockingPolicyError) as error:
            compute_base_goal({}, forged_map_pose, 0.40, FINAL_DOCKING)
        self.assertEqual(error.exception.code, 'TAG_SOURCE_UNBOUND')

    def test_source_swap_time_tf_frame_direction_target_and_calibration_mismatch_abort(self):
        cases = []
        record = self._bound_record(); record['tf_snapshot']['record_id'] = 'other'; cases.append(record)
        record = self._bound_record(); record['tf_snapshot']['timestamp_ns'] -= 1; cases.append(record)
        record = self._bound_record(); record['tf_snapshot']['base_link_to_camera']['child_frame'] = 'map'; cases.append(record)
        record = self._bound_record(); record['expected_target']['id'] = 6; cases.append(record)
        record = self._bound_record(); record['expected_target']['id'] = True; cases.append(record)
        record = self._bound_record(); record['observation']['target']['family'] = 'tag36h11'; cases.append(record)
        record = self._bound_record(); record['calibration_identity']['sha256'] = '0' * 64; cases.append(record)
        # A correct calibration SHA label cannot authorize divergent TF geometry.
        record = self._bound_record(); record['tf_snapshot']['base_link_to_camera']['translation_m']['x'] += 0.01; cases.append(record)
        record = self._bound_record(); record['tf_snapshot']['base_link_to_camera']['orientation_xyzw'] = {'x': 0.1, 'y': 0.0, 'z': 0.0, 'w': 0.99498743710662}; cases.append(record)
        # Calibration drift must change the canonical identity; recomputing it
        # still cannot approve the stale pre-drift TF geometry.
        record = self._bound_record(); record['calibration']['base_link_to_camera_extrinsics']['translation_m']['x'] += 0.01; record['calibration_identity'] = calibration_identity(record['calibration']); record['tf_snapshot']['base_link_to_camera']['calibration_sha256'] = record['calibration_identity']['sha256']; cases.append(record)
        record = self._bound_record(); record['observation']['camera_frame_pose']['frame_id'] = 'map'; cases.append(record)
        record = self._bound_record(); record['tf_snapshot']['observation_sha256'] = '0' * 64; cases.append(record)
        for record in cases:
            with self.subTest(record=record['record_id']):
                with self.assertRaises(AdapterContractError):
                    derive_bound_tag_pose(record, self._authority(), self._v1_template(), 1234567990)

    def test_v1_side_or_object_mapping_swap_is_rejected(self):
        v1 = copy.deepcopy(self._v1_template())
        v1['objects'][1]['tags'][1]['side_label'] = 'front'
        with self.assertRaises(AdapterContractError):
            validate_mapping_authority(self._authority(), v1)
        v1 = copy.deepcopy(self._v1_template())
        v1['objects'][1]['object_id'] = 0
        with self.assertRaises(AdapterContractError):
            validate_mapping_authority(self._authority(), v1)
        v1 = copy.deepcopy(self._v1_template())
        v1['objects'][0]['tags'].reverse()
        with self.assertRaises(AdapterContractError):
            validate_mapping_authority(self._authority(), v1)
        v1 = copy.deepcopy(self._v1_template())
        v1['objects'][0]['tags'][0]['id'] = False
        with self.assertRaises(AdapterContractError):
            validate_mapping_authority(self._authority(), v1)


if __name__ == '__main__':
    unittest.main()

from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest


PACKAGE_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / 'src'))

from limo_v1_navigation.config_policy import (  # noqa: E402
    load_profile,
    validate_amcl_transform_tolerance,
    validate_map_file,
    validate_profile,
    validate_runtime_request,
)


PROFILE_PATH = PACKAGE_ROOT / 'config' / 'v1_navigation_profile.yaml'


class ConfigPolicyTest(unittest.TestCase):

    def setUp(self):
        self.profile = load_profile(PROFILE_PATH)

    def test_reference_profile_passes(self):
        validate_profile(self.profile)
        self.assertEqual(self.profile['owners']['odom_tf'], '/limo_base_node')
        self.assertLess(self.profile['motion']['max_linear_x_mps'], 0.6)
        self.assertEqual(
            self.profile['tf_timing']['source_future_tolerance_s'], 0.10)
        self.assertEqual(
            self.profile['tf_timing']['amcl_transform_tolerance_s'], 0.05)
        self.assertEqual(validate_amcl_transform_tolerance(
            self.profile, PACKAGE_ROOT / 'config' / 'amcl.yaml'), 0.05)

    def test_unsafe_profile_mutations_are_blocked(self):
        mutations = (
            lambda p: p.pop('owners'),
            lambda p: p['owners'].__setitem__('odom_tf', ''),
            lambda p: p['owners'].__setitem__('odom_tf', '/robot_pose_ekf'),
            lambda p: p['owners'].__setitem__('forbidden_odom_tf', []),
            lambda p: p['topics'].__setitem__('driver_cmd', '/cmd_vel'),
            lambda p: p['frames'].__setitem__('base', 'base_footprint'),
            lambda p: p['scan'].__setitem__('expected_hz', 10.0),
            lambda p: p['freshness'].__setitem__('scan_timeout_s', 0.51),
            lambda p: p['freshness'].__setitem__('command_timeout_s', 0.26),
            lambda p: p.pop('tf_timing'),
            lambda p: p['tf_timing'].__setitem__(
                'source_future_tolerance_s', 0.11),
            lambda p: p['tf_timing'].__setitem__(
                'amcl_transform_tolerance_s', 0.10),
            lambda p: p['motion'].__setitem__('allow_nonzero_default', True),
            lambda p: p['motion'].__setitem__('driver_timeout_verified', True),
            lambda p: p['motion'].__setitem__('max_linear_x_mps', 0.6),
            lambda p: p['motion'].__setitem__('max_linear_accel_mps2', 0.6),
            lambda p: p['map_policy'].__setitem__('rejected_map_ids', []),
            lambda p: p.__setitem__('extra', True),
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                candidate = deepcopy(self.profile)
                mutation(candidate)
                with self.assertRaises(ValueError):
                    validate_profile(candidate)

    def test_amcl_transform_tolerance_missing_or_mismatch_blocks(self):
        invalid_sources = (
            '',
            'transform_tolerance: 0.04\n',
            'transform_tolerance: 0.10\n',
            'transform_tolerance: 0.11\n',
            'transform_tolerance: NaN\n',
            'transform_tolerance: 0.05\ntransform_tolerance: 0.05\n',
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'amcl.yaml'
            for source in invalid_sources:
                with self.subTest(source=source):
                    path.write_text(source, encoding='utf-8')
                    with self.assertRaises(ValueError):
                        validate_amcl_transform_tolerance(self.profile, path)

    def _write_map(self, directory, map_id='v1_frozen_room'):
        root = Path(directory)
        image = root / '{}.pgm'.format(map_id)
        image.write_text('P2\n1 1\n255\n0\n', encoding='ascii')
        yaml_path = root / '{}.yaml'.format(map_id)
        yaml_path.write_text(
            'image: {}.pgm\n'
            'resolution: 0.05\n'
            'origin: [1.0, -2.0, 0.5]\n'
            'negate: 0\n'
            'occupied_thresh: 0.65\n'
            'free_thresh: 0.196\n'.format(map_id),
            encoding='utf-8')
        return yaml_path

    def test_frozen_map_and_runtime_request_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            map_path = self._write_map(directory)
            artifact = validate_map_file(
                self.profile, map_path, 'v1_frozen_room')
            self.assertEqual(artifact.map_id, 'v1_frozen_room')
            validate_runtime_request(
                self.profile, 'localization', map_path,
                'v1_frozen_room')
            validate_runtime_request(
                self.profile, 'navigation', map_path,
                'v1_frozen_room', allow_nonzero=True,
                driver_timeout_verified=True)
            validate_runtime_request(
                self.profile, 'navigation', map_path,
                'v1_frozen_room', mode='integrated',
                cmd_vel_output_topic='/cleanup/base/cmd_vel_request')
            validate_runtime_request(
                self.profile, 'navigation_precore', map_path,
                'v1_frozen_room', mode='integrated',
                cmd_vel_output_topic='/cleanup/base/cmd_vel_request')

    def test_map_and_runtime_negative_cases(self):
        with tempfile.TemporaryDirectory() as directory:
            map_path = self._write_map(directory)
            with self.assertRaises(ValueError):
                validate_map_file(self.profile, Path(map_path.name))
            with self.assertRaises(ValueError):
                validate_map_file(self.profile, map_path, 'wrong_map')
            with self.assertRaises(ValueError):
                validate_runtime_request(
                    self.profile, 'navigation', map_path,
                    'v1_frozen_room', allow_nonzero=True,
                    driver_timeout_verified=False)
            with self.assertRaises(ValueError):
                validate_runtime_request(
                    self.profile, 'scan', map_path,
                    'v1_frozen_room')
            with self.assertRaises(ValueError):
                validate_runtime_request(
                    self.profile, 'navigation', map_path,
                    'v1_frozen_room', mode='integrated',
                    cmd_vel_output_topic='/v1/nav_cmd_vel')
            with self.assertRaises(ValueError):
                validate_runtime_request(
                    self.profile, 'scan', mode='integrated')
            with self.assertRaises(ValueError):
                validate_runtime_request(
                    self.profile, 'navigation_precore', map_path,
                    'v1_frozen_room', mode='integrated',
                    cmd_vel_output_topic='/cleanup/base/cmd_vel_request',
                    allow_nonzero=True, driver_timeout_verified=True)
            rejected = self._write_map(directory, 'map1017')
            with self.assertRaises(ValueError):
                validate_map_file(self.profile, rejected)
            missing_image = self._write_map(directory, 'missing_image')
            missing_image.with_suffix('.pgm').unlink()
            with self.assertRaises(ValueError):
                validate_map_file(self.profile, missing_image)

    def test_profile_is_json_compatible_yaml(self):
        source = PROFILE_PATH.read_text(encoding='utf-8')
        self.assertEqual(json.loads(source), self.profile)


if __name__ == '__main__':
    unittest.main()

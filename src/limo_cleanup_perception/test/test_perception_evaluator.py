"""Tests for quantitative four-scene and frozen-matrix evaluation."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from limo_cleanup_perception import perception_evaluator
from limo_cleanup_perception.perception_evaluator import (
    EvaluationThresholds,
    evaluate_frozen_matrix,
    evaluate_scene,
    evaluate_suite,
    recorded_artifact_binding,
    verify_recorded_artifacts,
)


def target(label, valid=True, actionable=False, status='observed'):
    """Build one serialized typed target."""
    target.counter += 1
    return {
        'observation_id': 'obs-{}'.format(target.counter),
        'object_class': label,
        'confidence': 0.9,
        'valid': valid,
        'actionable': actionable,
        'status': status,
        'error_code': '' if valid else 'insufficient_depth_pixels',
        'position': {'x': 0.1, 'y': 0.2, 'z': 1.0},
        'size': {'x': 0.1, 'y': 0.2, 'z': 0.3},
        'bbox': [10.0, 20.0, 100.0, 200.0],
        'depth_m': 1.0,
        'depth_valid_pixels': 75 if valid else 0,
        'depth_total_pixels': 100,
        'depth_valid_ratio': 0.75 if valid else 0.0,
        'source': label + '_model',
        'position_semantics': (
            'aligned_depth_roi_median_at_clipped_bbox_center'),
    }


target.counter = 0


def frame(
        targets, valid=True, latency=0.1, sync=0.02,
        end_to_end_latency=0.2):
    """Build one serialized typed perception frame."""
    frame.counter += 1
    return {
        'schema_version': 1,
        'read_only': True,
        'frame_id': 'camera_color_optical_frame',
        'task_id': 'evaluator-readonly',
        'sequence': frame.counter,
        'stamp': {'sec': 10, 'nanosec': frame.counter},
        'valid': valid,
        'status': (
            'targets_ready' if valid and targets else
            'no_targets' if valid else 'rgbd_contract_rejected'),
        'error_code': '' if valid else 'timestamp_span_exceeded',
        'sync_span_sec': sync,
        'processing_latency_sec': latency,
        'transport_latency_sec': end_to_end_latency,
        'targets': targets,
    }


frame.counter = 0


class PerceptionEvaluatorTest(unittest.TestCase):
    """Verify minimum samples, class metrics, depth, and safety semantics."""

    def setUp(self):
        self.thresholds = EvaluationThresholds(min_frames=3)

    def test_complete_synthetic_four_scene_suite_passes(self):
        scenes = {
            'background': [frame([]) for _ in range(30)],
            'bin_only': [
                frame([target('trash_bin')]) for _ in range(30)],
            'bottle_in_bin': [
                frame([
                    target('trash_bin'),
                    target('plastic_bottle', status='already_in_bin'),
                ]) for _ in range(30)],
            'bottle_outside': [
                frame([
                    target('trash_bin'),
                    target('plastic_bottle', actionable=True, status='active'),
                ]) for _ in range(30)],
        }
        report = evaluate_suite(scenes, EvaluationThresholds())
        self.assertTrue(report['passed'])
        outside = report['scene_reports']['bottle_outside']
        self.assertEqual(1.0, outside['outside_bottle_actionable_recall'])
        self.assertEqual(
            1.0,
            outside['class_metrics']['trash_bin']['image_recall'])

    def test_one_sample_cannot_pass_default_minimum(self):
        report = evaluate_scene(
            'background', [frame([])], EvaluationThresholds())
        self.assertFalse(report['passed'])
        self.assertIn('insufficient_frame_count', report['failures'])

    def test_depth_latency_and_in_bin_leak_fail_explicitly(self):
        bad = frame([
            target('trash_bin', valid=False),
            target(
                'plastic_bottle', valid=False, actionable=True,
                status='already_in_bin'),
        ], latency=0.8)
        report = evaluate_scene(
            'bottle_in_bin', [bad, bad, bad], self.thresholds)
        self.assertFalse(report['passed'])
        self.assertIn(
            'plastic_bottle_depth_valid_rate_below_threshold',
            report['failures'])
        self.assertIn(
            'in_bin_actionable_leak_rate_exceeded', report['failures'])
        self.assertIn(
            'processing_latency_p95_exceeded', report['failures'])

    def test_outside_bottle_wrong_suppression_fails_even_with_high_recall(self):
        good = frame([
            target('trash_bin'),
            target('plastic_bottle', actionable=True, status='active'),
        ])
        suppressed = frame([
            target('trash_bin'),
            target(
                'plastic_bottle', actionable=False,
                status='already_in_bin'),
        ])
        report = evaluate_scene(
            'bottle_outside', [good] * 29 + [suppressed],
            EvaluationThresholds(min_frames=30))
        self.assertAlmostEqual(
            29 / 30, report['outside_bottle_actionable_recall'])
        self.assertEqual(
            1, report['outside_bottle_wrong_suppressed_frames'])
        self.assertFalse(report['passed'])
        self.assertIn(
            'outside_bottle_wrong_suppression_rate_exceeded',
            report['failures'])

    def test_rgbd_rejection_sync_and_latency_each_fail_their_gate(self):
        cases = {
            'rejection': (
                [frame([], valid=False)] + [frame([]) for _ in range(2)],
                'rgbd_rejection_rate_exceeded'),
            'sync': (
                [frame([], sync=0.20) for _ in range(3)],
                'sync_p95_exceeded'),
            'latency': (
                [frame([], latency=0.60) for _ in range(3)],
                'processing_latency_p95_exceeded'),
            'end_to_end_latency': (
                [frame([], end_to_end_latency=0.80) for _ in range(3)],
                'end_to_end_latency_p95_exceeded'),
        }
        for name, (frames, failure) in cases.items():
            with self.subTest(case=name):
                report = evaluate_scene(
                    'background', frames, self.thresholds)
                self.assertFalse(report['passed'])
                self.assertIn(failure, report['failures'])

    def test_all_invalid_target_projections_reject_the_frame(self):
        invalid = frame([target('trash_bin', valid=False)])
        invalid['status'] = 'targets_invalid'
        invalid['error_code'] = 'all_target_projections_invalid'
        report = evaluate_scene(
            'bin_only', [invalid, invalid, invalid], self.thresholds)
        self.assertFalse(report['passed'])
        self.assertEqual(1.0, report['rgbd_rejection_rate'])

    def test_missing_latency_sample_is_fail_closed(self):
        frames = [frame([]) for _ in range(3)]
        frames[1].pop('transport_latency_sec')
        report = evaluate_scene(
            'background', frames, self.thresholds)
        self.assertFalse(report['passed'])
        self.assertIn(
            'end_to_end_latency_samples_incomplete', report['failures'])

    def test_invalid_schema_and_unknown_class_fail_closed(self):
        malformed = frame([])
        malformed['targets'] = 'not-a-list'
        report = evaluate_scene(
            'background', [malformed, frame([]), frame([])],
            self.thresholds)
        self.assertFalse(report['passed'])
        self.assertIn('frame_schema_invalid', report['failures'])
        self.assertIn('targets_not_list', report['schema_failures'])

        unknown = target('plastic_bottle')
        unknown['object_class'] = 'banana'
        report = evaluate_scene(
            'background', [frame([unknown]), frame([]), frame([])],
            self.thresholds)
        self.assertFalse(report['passed'])
        self.assertIn('unsupported_object_class', report['schema_failures'])

    def test_string_boolean_and_invalid_quality_fail_closed(self):
        malformed_target = target('plastic_bottle')
        malformed_target['valid'] = 'false'
        malformed_target['actionable'] = 'false'
        malformed_target['confidence'] = 1.5
        malformed_target['depth_valid_ratio'] = -1.0
        report = evaluate_scene(
            'bottle_outside', [
                frame([target('trash_bin'), malformed_target]),
                frame([target('trash_bin')]),
                frame([target('trash_bin')]),
            ], self.thresholds)
        self.assertFalse(report['passed'])
        self.assertIn('frame_schema_invalid', report['failures'])
        self.assertIn('invalid_valid_flag', report['schema_failures'])
        self.assertIn('invalid_actionable_flag', report['schema_failures'])
        self.assertIn('invalid_confidence', report['schema_failures'])
        self.assertIn('invalid_depth_valid_ratio', report['schema_failures'])

    def test_complete_geometry_and_depth_arithmetic_fail_closed(self):
        malformed = target('trash_bin')
        malformed['bbox'] = [10.0, 20.0, 10.0, 200.0]
        malformed['size']['x'] = 0.0
        malformed['depth_valid_pixels'] = 76
        malformed['source'] = ''
        malformed['position_semantics'] = ''
        report = evaluate_scene(
            'bin_only', [frame([malformed])] + [
                frame([target('trash_bin')]) for _ in range(2)],
            self.thresholds)
        self.assertFalse(report['passed'])
        for reason in (
                'invalid_bbox', 'invalid_size', 'depth_ratio_count_mismatch',
                'missing_source', 'missing_position_semantics'):
            self.assertIn(reason, report['schema_failures'])

    def test_class_false_positive_and_false_negative_are_quantified(self):
        background = evaluate_scene(
            'background', [
                frame([target('plastic_bottle')]), frame([]), frame([]),
            ], self.thresholds)
        bottle_metrics = background['class_metrics']['plastic_bottle']
        self.assertEqual((1, 2), (
            bottle_metrics['fp'], bottle_metrics['tn']))
        self.assertIn(
            'plastic_bottle_false_positive_rate_exceeded',
            background['failures'])

        outside = evaluate_scene(
            'bottle_outside', [
                frame([target('trash_bin')]),
                frame([target('trash_bin')]),
                frame([
                    target('trash_bin'),
                    target('plastic_bottle', actionable=True),
                ]),
            ], self.thresholds)
        bottle_metrics = outside['class_metrics']['plastic_bottle']
        self.assertEqual((1, 2), (
            bottle_metrics['tp'], bottle_metrics['fn']))
        self.assertIn(
            'plastic_bottle_recall_below_threshold', outside['failures'])

    def test_suite_cannot_pass_with_a_missing_scene(self):
        scenes = {
            'background': [frame([]) for _ in range(3)],
            'bin_only': [
                frame([target('trash_bin')]) for _ in range(3)],
            'bottle_in_bin': [
                frame([
                    target('trash_bin'),
                    target('plastic_bottle', status='already_in_bin'),
                ]) for _ in range(3)],
        }
        report = evaluate_suite(scenes, self.thresholds)
        self.assertFalse(report['passed'])
        self.assertIn('missing_scene:bottle_outside', report['failures'])

    def test_cli_cannot_lower_production_minimum_below_thirty(self):
        with patch('sys.argv', [
                'perception_evaluator', 'scene',
                '--scene', 'background',
                '--frames', 'unused.jsonl',
                '--report', 'unused-report.json',
                '--min-frames', '1']):
            with self.assertRaisesRegex(
                    SystemExit, 'min-frames cannot be lower than 30'):
                perception_evaluator.main()

    def test_python_api_cannot_lower_production_minimum_below_thirty(self):
        scenes = {
            'background': [frame([])],
            'bin_only': [frame([target('trash_bin')])],
            'bottle_in_bin': [frame([
                target('trash_bin'),
                target('plastic_bottle', status='already_in_bin'),
            ])],
            'bottle_outside': [frame([
                target('trash_bin'),
                target('plastic_bottle', actionable=True, status='active'),
            ])],
        }
        report = evaluate_suite(
            scenes, EvaluationThresholds(min_frames=1),
            enforce_production_minimum=True)
        self.assertFalse(report['passed'])
        self.assertIn(
            'min_frames_below_production_minimum', report['failures'])

    def test_non_object_frame_is_structurally_rejected(self):
        report = evaluate_scene(
            'background', [1] * 30, EvaluationThresholds())
        self.assertFalse(report['passed'])
        self.assertIn('frame_schema_invalid', report['failures'])
        self.assertIn('frame_not_object', report['schema_failures'])

    def test_replayed_sequence_stamp_and_observation_cannot_inflate_samples(self):
        repeated = frame([target('trash_bin')])
        report = evaluate_scene(
            'bin_only', [repeated, repeated, repeated], self.thresholds)
        self.assertFalse(report['passed'])
        self.assertIn('sequence_not_unique', report['failures'])
        self.assertIn('stamp_not_strictly_increasing', report['failures'])
        self.assertIn('duplicate_observation_id', report['failures'])

    def test_frozen_matrix_counts_and_representatives(self):
        def record(name, bottle=False, trash_bin=False, active=0, in_bin=0):
            return {
                'name': name,
                'target_bottle': {'label': 'plastic_bottle'} if bottle else None,
                'target_bin': {'label': 'trash_bin'} if trash_bin else None,
                'bottles_active': active,
                'bottles_already_in_bin': in_bin,
                'manual_label': {'selected_target_correct': True},
            }

        positives = [record('p{}'.format(index), bottle=True)
                     for index in range(49)]
        positives.extend(record('m{}'.format(index)) for index in range(5))
        backgrounds = [record('IMG_9048.JPG')]
        backgrounds.extend(record('b{}'.format(index)) for index in range(23))
        mixes = [
            record('IMG_8976.JPG', trash_bin=True),
            record('IMG_9030.JPG', trash_bin=True, in_bin=1),
            record('IMG_9017.JPG', bottle=True, trash_bin=True, active=1),
        ]
        for item, status in zip(
                mixes, ('frozen_manual_representative',) * 3):
            item['manual_label']['status'] = status
        for index in range(67):
            item = record('x{}'.format(index))
            item['manual_label'] = {
                'status': 'not_exhaustively_labeled',
                'selected_target_correct': None,
            }
            mixes.append(item)
        payload = {
            'run': {
                'records': {
                    'bottle_val': positives,
                    'invalid_background': backgrounds,
                    'mix': mixes,
                },
                'summaries': {'mix': {'images': 70}},
            },
        }
        report = evaluate_frozen_matrix(payload)
        metrics = report['bottle_background_confusion']
        self.assertEqual((49, 0, 5, 24), (
            metrics['tp'], metrics['fp'], metrics['fn'], metrics['tn']))
        self.assertAlmostEqual(49 / 54, metrics['image_recall'])
        self.assertTrue(report['regression_passed'])
        self.assertFalse(report['delivery_ready'])
        accounting = report['sample_accounting']
        self.assertEqual((148, 78, 70, 67, 3), (
            accounting['total_images'],
            accounting['confusion_matrix_scored_images'],
            accounting['excluded_from_confusion_matrix_images'],
            accounting['unknown_or_not_exhaustively_labeled_images'],
            accounting['manually_labeled_representative_images']))
        self.assertTrue(accounting['strictly_closed'])
        self.assertEqual(
            78,
            accounting['confusion_matrix_denominator'][
                'tp_plus_fn_plus_fp_plus_tn'])
        self.assertEqual(
            'actionable_plastic_bottle_present',
            accounting['datasets']['bottle_val']['ground_truth_label'])
        self.assertEqual(
            67, accounting['datasets']['mix']['unknown'])
        self.assertEqual(0, accounting['datasets']['mix']['skipped'])

    def test_frozen_matrix_accounting_and_boolean_labels_fail_closed(self):
        def record(name, label):
            return {
                'name': name,
                'target_bottle': {'label': 'plastic_bottle'},
                'target_bin': None,
                'bottles_active': 1,
                'bottles_already_in_bin': 0,
                'manual_label': {'selected_target_correct': label},
            }

        malformed = {
            'run': {'records': {
                'bottle_val': [record('p0', 'false')],
                'invalid_background': [],
                'mix': [],
            }},
        }
        report = evaluate_frozen_matrix(malformed)
        self.assertFalse(report['regression_passed'])
        self.assertIn(
            'sample_accounting_not_strictly_closed',
            report['regression_failures'])
        self.assertIn(
            'invalid_selected_target_correct_label',
            report['regression_failures'])
        self.assertEqual(
            0, report['bottle_background_confusion']['tp'])

    def test_recorded_artifacts_bind_and_verify_input_model_and_code(self):
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            model = root / 'model.pt'
            source = root / 'source.py'
            image = root / 'image.png'
            model.write_bytes(b'model')
            source.write_bytes(b'source')
            image.write_bytes(b'image')

            import hashlib

            def entry(path):
                return {
                    'path': str(path),
                    'size': path.stat().st_size,
                    'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                }

            payload = {
                'schema_version': 3,
                'models': {'bottle': entry(model)},
                'source': {'files': [entry(source)]},
                'datasets': {
                    'bottle_val': {
                        'images': 1,
                        'manifest_sha256': 'manifest',
                        'files': [dict(entry(image), name=image.name)],
                    },
                },
            }
            binding = recorded_artifact_binding(payload)
            verification = verify_recorded_artifacts(binding)
            self.assertEqual('manifest', (
                binding['datasets'][0]['manifest_sha256']))
            self.assertTrue(verification['all_recorded_files_match'])


if __name__ == '__main__':
    unittest.main()

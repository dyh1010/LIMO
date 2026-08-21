"""Tests for the read-only orchestration fixture and target selector."""

import json
import unittest
from pathlib import Path

from limo_cleanup_perception.orchestration_contract import (
    select_typed_target,
)


FIXTURE_PATH = (
    Path(__file__).parents[1]
    / 'fixtures/orchestration_typed_frames.json'
)


class OrchestrationContractTest(unittest.TestCase):
    """Verify bottle, bin, invalid, stale, and duplicate semantics."""

    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads(FIXTURE_PATH.read_text(encoding='utf-8'))

    def test_all_fixture_cases_match_expected_selection(self):
        self.assertEqual(7, len(self.fixture['cases']))
        for case in self.fixture['cases']:
            with self.subTest(case=case['name']):
                result = select_typed_target(
                    case['frame'], case['requested_class'],
                    case['consumer_now_sec'],
                    self.fixture['consumer_contract']['max_frame_age_sec'],
                    case['last_sequence'], case['seen_observation_ids'])
                expected = case['expected']
                self.assertEqual(expected['accepted'], result.accepted)
                self.assertEqual(expected['reason'], result.reason)
                observation_id = (
                    result.target.get('observation_id')
                    if result.target is not None else None)
                self.assertEqual(expected['observation_id'], observation_id)

    def test_fixture_is_read_only_and_has_required_case_classes(self):
        self.assertTrue(self.fixture['read_only'])
        self.assertFalse(
            self.fixture['consumer_contract']['authorizes_motion'])
        names = {case['name'] for case in self.fixture['cases']}
        self.assertTrue({
            'valid_bottle', 'valid_bin', 'invalid_frame',
            'invalid_target_depth', 'stale_frame',
            'duplicate_observation', 'duplicate_sequence',
        }.issubset(names))

    def test_bottle_requires_actionable_but_bin_is_observation_only(self):
        cases = {case['name']: case for case in self.fixture['cases']}
        bottle = cases['valid_bottle']['frame']['targets'][1]
        trash_bin = cases['valid_bin']['frame']['targets'][0]
        self.assertTrue(bottle['actionable'])
        self.assertFalse(trash_bin['actionable'])

    def test_invalid_higher_confidence_bottle_cannot_hide_valid_candidate(self):
        case = next(
            item for item in self.fixture['cases']
            if item['name'] == 'valid_bottle')
        targets = case['frame']['targets']
        self.assertGreater(targets[0]['confidence'], targets[1]['confidence'])
        self.assertFalse(targets[0]['valid'])
        result = select_typed_target(
            case['frame'], case['requested_class'],
            case['consumer_now_sec'],
            self.fixture['consumer_contract']['max_frame_age_sec'],
            case['last_sequence'], case['seen_observation_ids'])
        self.assertEqual('fixture-bottle-001', result.target['observation_id'])

    def test_inconsistent_frame_bin_and_same_frame_duplicate_fail_closed(self):
        cases = {case['name']: case for case in self.fixture['cases']}

        inconsistent = dict(cases['valid_bottle']['frame'])
        inconsistent['status'] = 'rgbd_contract_rejected'
        inconsistent['error_code'] = 'timestamp_span_exceeded'
        self.assertEqual(
            'frame_status_invalid',
            select_typed_target(
                inconsistent, 'plastic_bottle', 100.5, 1.0).reason)

        bin_frame = dict(cases['valid_bin']['frame'])
        bin_target = dict(bin_frame['targets'][0])
        bin_target.update(actionable=True, status='active')
        bin_frame['targets'] = [bin_target]
        self.assertEqual(
            'no_valid_target',
            select_typed_target(bin_frame, 'trash_bin', 101.4, 1.0).reason)

        duplicate_frame = dict(cases['valid_bottle']['frame'])
        duplicate_frame['targets'] = [
            dict(cases['valid_bottle']['frame']['targets'][1]),
            dict(cases['valid_bottle']['frame']['targets'][1]),
        ]
        self.assertEqual(
            'duplicate_observation',
            select_typed_target(
                duplicate_frame, 'plastic_bottle', 100.5, 1.0).reason)


if __name__ == '__main__':
    unittest.main()

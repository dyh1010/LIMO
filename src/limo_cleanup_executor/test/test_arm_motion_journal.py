import json
import math
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from limo_cleanup_executor.arm_motion_journal import (
    DurableMotionJournal,
    record_post_send_sample_and_classify,
    record_stop_outcome,
)


BEFORE = [-41.74, 6.76, 61.69, -29.09, -140.62, 89.12]
MODULE = (
    Path(__file__).resolve().parents[1]
    / 'limo_cleanup_executor' / 'arm_motion_journal.py'
)


def sample(error=0, angles=None, moving=1, connected=1):
    return {
        'connected': connected,
        'angles_deg': list(BEFORE) if angles is None else angles,
        'moving': moving,
        'error': error,
    }


class ArmMotionJournalTest(unittest.TestCase):
    def open_journal(self, directory):
        path = Path(directory) / 'motion.jsonl'
        return path, DurableMotionJournal(
            str(path), 'pose_00_to_01', 'J6_SINGLE_NO_RETRY')

    def records(self, path):
        return [json.loads(line) for line in path.read_text().splitlines()]

    def test_nonzero_error_sample_is_persisted_before_fault_decision(self):
        with tempfile.TemporaryDirectory() as directory:
            path, journal = self.open_journal(directory)
            raw = sample(error=6)
            decision = record_post_send_sample_and_classify(
                journal, raw, BEFORE, 6, 94.12)
            journal.close()
            self.assertEqual('FAULT_ERROR', decision)
            self.assertEqual(raw, self.records(path)[1]['payload']['sample'])

    def test_none_angles_sample_is_persisted_before_fault_decision(self):
        with tempfile.TemporaryDirectory() as directory:
            path, journal = self.open_journal(directory)
            raw = sample(angles=None)
            raw['angles_deg'] = None
            decision = record_post_send_sample_and_classify(
                journal, raw, BEFORE, 6, 94.12)
            journal.close()
            self.assertEqual('FAULT_ANGLES_INVALID', decision)
            self.assertIsNone(self.records(path)[1]['payload']['sample']['angles_deg'])

    def test_other_joint_change_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            unused_path, journal = self.open_journal(directory)
            angles = list(BEFORE)
            angles[2] += 0.71
            decision = record_post_send_sample_and_classify(
                journal, sample(angles=angles), BEFORE, 6, 94.12)
            journal.close()
            self.assertEqual('FAULT_OTHER_JOINT_CHANGED', decision)

    def test_target_requires_stationary_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            unused_path, journal = self.open_journal(directory)
            angles = list(BEFORE)
            angles[5] = 94.12
            moving = record_post_send_sample_and_classify(
                journal, sample(angles=angles, moving=1), BEFORE, 6, 94.12)
            stationary = record_post_send_sample_and_classify(
                journal, sample(angles=angles, moving=0), BEFORE, 6, 94.12)
            journal.close()
            self.assertEqual('TARGET_MOVING', moving)
            self.assertEqual('TARGET_STATIONARY', stationary)

    def test_journal_is_exclusive_and_sequence_is_monotonic(self):
        with tempfile.TemporaryDirectory() as directory:
            path, journal = self.open_journal(directory)
            with self.assertRaises(FileExistsError):
                DurableMotionJournal(
                    str(path), 'forged_second_session', 'FORGED')
            record_stop_outcome(journal, True, None, 'TransportTimeout')
            journal.close()
            records = self.records(path)
            self.assertEqual([0, 1], [item['sequence'] for item in records])
            stop = records[1]['payload']
            self.assertFalse(stop['physical_stop_proven'])
            self.assertEqual('TransportTimeout', stop['exception_name'])

    def test_nonfinite_sample_cannot_corrupt_journal(self):
        with tempfile.TemporaryDirectory() as directory:
            path, journal = self.open_journal(directory)
            raw = sample()
            raw['angles_deg'][0] = math.nan
            with self.assertRaises(ValueError):
                record_post_send_sample_and_classify(
                    journal, raw, BEFORE, 6, 94.12)
            journal.close()
            self.assertEqual(1, len(self.records(path)))

    def run_crash_child(self, journal_path, mode):
        code = textwrap.dedent('''
            import importlib.util
            import os
            import sys
            import time

            module_path, journal_path, mode = sys.argv[1:]
            spec = importlib.util.spec_from_file_location(
                'isolated_arm_motion_journal', module_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            journal = module.DurableMotionJournal(
                journal_path, 'crash_motion', 'PURE_FAKE_NO_HARDWARE')
            raw = {
                'connected': 1,
                'angles_deg': [-41.74, 6.76, 61.69, -29.09, -140.62, 89.12],
                'moving': 0,
                'error': 6,
            }
            decision = module.record_post_send_sample_and_classify(
                journal, raw, raw['angles_deg'], 6, 94.12)
            if decision != 'FAULT_ERROR':
                os._exit(92)
            if mode == 'hard_exit':
                os._exit(91)
            time.sleep(30.0)
        ''')
        command = [
            sys.executable, '-I', '-B', '-c', code,
            str(MODULE), str(journal_path), mode,
        ]
        if mode == 'hard_exit':
            return subprocess.run(
                command, check=False, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, timeout=5.0)
        with self.assertRaises(subprocess.TimeoutExpired):
            subprocess.run(
                command, check=False, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, timeout=0.5)
        return None

    def assert_crash_sample_preserved(self, path):
        records = self.records(path)
        self.assertEqual(2, len(records))
        self.assertEqual('journal_opened', records[0]['event'])
        self.assertEqual('post_send_sample', records[1]['event'])
        sample_record = records[1]['payload']['sample']
        self.assertEqual(6, sample_record['error'])
        self.assertEqual(0, sample_record['moving'])

    def test_hard_process_exit_preserves_fsynced_fault_sample(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'hard_exit.jsonl'
            completed = self.run_crash_child(path, 'hard_exit')
            self.assertEqual(91, completed.returncode, completed.stderr)
            self.assert_crash_sample_preserved(path)

    def test_timeout_kill_preserves_fsynced_fault_sample(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'timeout.jsonl'
            self.run_crash_child(path, 'timeout')
            self.assert_crash_sample_preserved(path)


if __name__ == '__main__':
    unittest.main()

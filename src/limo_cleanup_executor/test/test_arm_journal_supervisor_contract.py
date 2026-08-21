import unittest

from limo_cleanup_executor.arm_journal_supervisor_contract import (
    ACK_SCHEMA,
    BoundedJournalAckGate,
    DURABLE,
    PHYSICAL_ISOLATION_REQUIRED,
    WAITING,
)


SAMPLE = '1' * 64
WORKER = '2' * 64
RECORD = '3' * 64


class ManualClock:
    def __init__(self):
        self.now = 10.0

    def __call__(self):
        return self.now


def acknowledgement(**changes):
    value = {
        'schema': ACK_SCHEMA,
        'motion_id': 'pose_00_to_01',
        'epoch': 1,
        'sample_sha256': SAMPLE,
        'worker_release_sha256': WORKER,
        'record_sha256': RECORD,
        'journal_sequence': 1,
        'durable_fsync': True,
    }
    value.update(changes)
    return value


class ArmJournalSupervisorContractTest(unittest.TestCase):
    def gate(self):
        clock = ManualClock()
        return clock, BoundedJournalAckGate(
            'pose_00_to_01', WORKER, 0.25, clock=clock)

    def test_exact_durable_ack_is_the_only_classification_commit_point(self):
        unused_clock, gate = self.gate()
        ticket = gate.reserve(SAMPLE)
        self.assertEqual(WAITING, gate.state)
        self.assertFalse(gate.classification_permitted)
        self.assertEqual(1, ticket['epoch'])
        self.assertTrue(gate.accept(acknowledgement()))
        self.assertEqual(DURABLE, gate.state)
        self.assertTrue(gate.classification_permitted)
        self.assertFalse(gate.physical_stop_required)

    def test_missing_ack_deadline_requires_physical_isolation(self):
        clock, gate = self.gate()
        gate.reserve(SAMPLE)
        clock.now = 10.25
        self.assertEqual(PHYSICAL_ISOLATION_REQUIRED, gate.expire())
        self.assertTrue(gate.physical_stop_required)
        self.assertFalse(gate.classification_permitted)

    def test_late_ack_cannot_clear_latch(self):
        clock, gate = self.gate()
        gate.reserve(SAMPLE)
        clock.now = 10.26
        self.assertFalse(gate.accept(acknowledgement()))
        clock.now = 10.10
        self.assertFalse(gate.accept(acknowledgement()))
        self.assertTrue(gate.physical_stop_required)

    def test_wrong_epoch_sample_worker_or_record_is_rejected(self):
        mutations = (
            {'epoch': 2},
            {'sample_sha256': '4' * 64},
            {'worker_release_sha256': '5' * 64},
            {'record_sha256': 'not-a-hash'},
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                unused_clock, gate = self.gate()
                gate.reserve(SAMPLE)
                self.assertFalse(gate.accept(acknowledgement(**mutation)))
                self.assertTrue(gate.physical_stop_required)

    def test_synthetic_or_shape_changed_ack_is_rejected(self):
        candidates = [
            None,
            acknowledgement(durable_fsync=False),
            acknowledgement(journal_sequence=True),
            dict(acknowledgement(), attacker_claim='pass'),
        ]
        for candidate in candidates:
            with self.subTest(candidate=candidate):
                unused_clock, gate = self.gate()
                gate.reserve(SAMPLE)
                self.assertFalse(gate.accept(candidate))
                self.assertTrue(gate.physical_stop_required)

    def test_close_and_duplicate_accept_cannot_rearm(self):
        unused_clock, gate = self.gate()
        gate.reserve(SAMPLE)
        gate.close()
        self.assertFalse(gate.accept(acknowledgement()))
        self.assertEqual(PHYSICAL_ISOLATION_REQUIRED, gate.state)

    def test_contract_has_no_thread_or_io_implementation(self):
        import ast
        from pathlib import Path

        path = (Path(__file__).resolve().parents[1]
                / 'limo_cleanup_executor'
                / 'arm_journal_supervisor_contract.py')
        tree = ast.parse(path.read_text(encoding='utf-8'))
        imports = {
            alias.name.split('.')[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        self.assertFalse(imports & {
            'threading', 'subprocess', 'multiprocessing', 'socket', 'rclpy',
            'rospy', 'pymycobot', 'serial',
        })
        calls = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        self.assertFalse(calls & {'open', 'write', 'fsync', 'send', 'connect'})


if __name__ == '__main__':
    unittest.main()

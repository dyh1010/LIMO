import unittest

from limo_cleanup_perception.perception_core import (
    Detection2D,
    DisposalPhase,
    DisposalStateMachine,
    bin_opening_region,
    classify_bottles,
    select_target_bottle,
)


def detection(label, confidence, x1, y1, x2, y2):
    return Detection2D(label, confidence, x1, y1, x2, y2)


class PerceptionCoreTest(unittest.TestCase):

    def test_bottle_in_upper_bin_region_is_ignored(self):
        trash_bin = detection('trash_bin', 0.95, 100, 100, 300, 500)
        bottle = detection('plastic_bottle', 0.90, 160, 140, 230, 280)
        result = classify_bottles([bottle], [trash_bin])
        self.assertEqual((), result.active)
        self.assertEqual((bottle,), result.already_in_bin)

    def test_bottle_below_opening_region_remains_actionable(self):
        trash_bin = detection('trash_bin', 0.95, 100, 100, 300, 500)
        bottle = detection('plastic_bottle', 0.90, 160, 360, 230, 470)
        result = classify_bottles([bottle], [trash_bin])
        self.assertEqual((bottle,), result.active)
        self.assertEqual((), result.already_in_bin)

    def test_partial_overlap_without_center_inside_is_not_ignored(self):
        trash_bin = detection('trash_bin', 0.95, 100, 100, 300, 500)
        bottle = detection('plastic_bottle', 0.90, 40, 140, 130, 260)
        result = classify_bottles([bottle], [trash_bin])
        self.assertEqual((bottle,), result.active)

    def test_opening_region_uses_only_upper_part_of_bin(self):
        trash_bin = detection('trash_bin', 0.95, 100, 200, 300, 600)
        opening = bin_opening_region(trash_bin)
        self.assertAlmostEqual(100.0, opening.x1)
        self.assertAlmostEqual(300.0, opening.x2)
        self.assertAlmostEqual(200.0, opening.y1)
        self.assertAlmostEqual(448.0, opening.y2)

    def test_target_selection_prefers_larger_nearby_detection(self):
        small = detection('plastic_bottle', 0.99, 0, 0, 20, 20)
        large = detection('plastic_bottle', 0.80, 0, 0, 80, 100)
        self.assertEqual(large, select_target_bottle([small, large]))

    def test_state_machine_enforces_task_order(self):
        bottle = detection('plastic_bottle', 0.9, 0, 0, 20, 50)
        trash_bin = detection('trash_bin', 0.9, 100, 100, 200, 300)
        machine = DisposalStateMachine()
        self.assertEqual(
            DisposalPhase.BOTTLE_TARGET_READY,
            machine.observe([bottle], [trash_bin]),
        )
        self.assertEqual(
            DisposalPhase.CARRYING_BOTTLE,
            machine.confirm_bottle_acquired(),
        )
        self.assertEqual(
            DisposalPhase.SEARCHING_BIN,
            machine.begin_bin_search(),
        )
        self.assertEqual(
            DisposalPhase.BIN_TARGET_READY,
            machine.observe([], [trash_bin]),
        )
        self.assertEqual(
            DisposalPhase.READY_TO_DROP,
            machine.confirm_bin_aligned(),
        )
        self.assertEqual(
            DisposalPhase.VERIFYING_DROP,
            machine.confirm_drop_commanded(),
        )
        self.assertEqual(
            DisposalPhase.SUCCEEDED,
            machine.finish_verification(True),
        )

    def test_invalid_state_transition_raises(self):
        machine = DisposalStateMachine()
        with self.assertRaises(RuntimeError):
            machine.confirm_bottle_acquired()


if __name__ == '__main__':
    unittest.main()

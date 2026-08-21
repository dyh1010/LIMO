import unittest

from limo_cleanup_perception.perception_core import (
    Detection2D,
    DisposalPhase,
    DisposalStateMachine,
    bin_opening_region,
    classify_bottles,
    classify_bottles_with_depth,
    select_target_bin,
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

    def test_target_selection_uses_area_only_after_confidence_tie(self):
        small = detection('plastic_bottle', 0.80, 0, 0, 20, 20)
        large = detection('plastic_bottle', 0.80, 0, 0, 80, 100)
        self.assertEqual(large, select_target_bottle([small, large]))

    def test_img8949_giant_lower_confidence_box_cannot_win(self):
        correct = detection(
            'plastic_bottle', 0.5666795372962952,
            1459.5919189453125, 2256.30810546875,
            2255.181884765625, 2503.82373046875)
        small_background = detection(
            'plastic_bottle', 0.3937782347202301,
            13.325400352478027, 0.0,
            664.7854614257812, 276.6977844238281)
        giant_background = detection(
            'plastic_bottle', 0.37835693359375,
            2073.270263671875, 739.812744140625,
            4284.0, 4439.08837890625)

        self.assertGreater(giant_background.area, correct.area * 41.0)
        self.assertEqual(
            correct,
            select_target_bottle([
                correct, small_background, giant_background]),
        )

    def test_six_multi_active_images_choose_highest_confidence(self):
        candidates_by_image = {
            'IMG_8913.JPG': (
                detection('plastic_bottle', 0.8167792558670044,
                          1031.6845703125, 1341.5595703125,
                          2810.751953125, 3203.13134765625),
                detection('plastic_bottle', 0.4837484359741211,
                          2559.04833984375, 2763.21533203125,
                          2994.989501953125, 3173.48095703125),
            ),
            'IMG_8935.JPG': (
                detection('plastic_bottle', 0.5689412355422974,
                          1972.669677734375, 1415.5130615234375,
                          2573.326416015625, 1706.21875),
                detection('plastic_bottle', 0.47642621397972107,
                          1162.8116455078125, 1210.9521484375,
                          1549.2667236328125, 1618.1568603515625),
            ),
            'IMG_8936.JPG': (
                detection('plastic_bottle', 0.7542120218276978,
                          2425.568603515625, 859.065185546875,
                          2796.437744140625, 1210.280029296875),
                detection('plastic_bottle', 0.35291996598243713,
                          3051.49853515625, 1045.85498046875,
                          3478.865234375, 1320.78173828125),
            ),
            'IMG_8938.JPG': (
                detection('plastic_bottle', 0.5197660326957703,
                          2093.38916015625, 972.8680419921875,
                          2390.733154296875, 1277.8447265625),
                detection('plastic_bottle', 0.4859572649002075,
                          2657.96923828125, 1095.4903564453125,
                          2956.373779296875, 1328.0826416015625),
            ),
            'IMG_8949.JPG': (
                detection('plastic_bottle', 0.5666795372962952,
                          1459.5919189453125, 2256.30810546875,
                          2255.181884765625, 2503.82373046875),
                detection('plastic_bottle', 0.3937782347202301,
                          13.325400352478027, 0.0,
                          664.7854614257812, 276.6977844238281),
                detection('plastic_bottle', 0.37835693359375,
                          2073.270263671875, 739.812744140625,
                          4284.0, 4439.08837890625),
            ),
            'IMG_8951.JPG': (
                detection('plastic_bottle', 0.8559468984603882,
                          1863.062255859375, 3060.973388671875,
                          3131.902587890625, 3583.00732421875),
                detection('plastic_bottle', 0.37809988856315613,
                          2899.326904296875, 3491.74951171875,
                          3124.006591796875, 3720.333740234375),
            ),
        }

        for image_name, candidates in candidates_by_image.items():
            with self.subTest(image=image_name):
                expected = max(
                    candidates, key=lambda item: item.confidence)
                self.assertEqual(
                    expected, select_target_bottle(candidates))

    def test_target_selection_rejects_malformed_candidates(self):
        wrong_class = detection('trash_bin', 0.99, 0, 0, 100, 100)
        non_finite = detection(
            'plastic_bottle', float('nan'), 0, 0, 100, 100)
        zero_area = detection('plastic_bottle', 0.95, 10, 10, 10, 40)

        self.assertIsNone(select_target_bottle([
            wrong_class, non_finite, zero_area]))

    def test_bin_selection_is_confidence_first_and_fail_closed(self):
        correct = detection('trash_bin', 0.90, 100, 100, 300, 500)
        giant_false = detection('trash_bin', 0.40, 0, 0, 4000, 5000)
        wrong_class = detection('plastic_bottle', 0.99, 0, 0, 100, 100)
        self.assertEqual(
            correct, select_target_bin([giant_false, correct, wrong_class]))
        self.assertIsNone(select_target_bin([
            wrong_class,
            detection('trash_bin', float('nan'), 0, 0, 100, 100),
            detection('trash_bin', 0.8, 10, 10, 10, 30),
        ]))

    def test_img9030_exact_geometry_remains_in_bin(self):
        bottle = detection(
            'plastic_bottle', 0.645284,
            1332.585, 2938.871, 2656.408, 3408.170)
        trash_bin = detection(
            'trash_bin', 0.887762,
            1078.663, 1808.500, 3276.134, 4183.120)

        result = classify_bottles([bottle], [trash_bin])

        self.assertEqual((), result.active)
        self.assertEqual((bottle,), result.already_in_bin)

    def test_depth_disagreement_prevents_bin_front_false_suppression(self):
        bottle = detection('plastic_bottle', 0.9, 150, 120, 230, 250)
        trash_bin = detection('trash_bin', 0.9, 100, 100, 300, 500)
        result = classify_bottles_with_depth(
            [bottle], [trash_bin], {bottle: 0.7}, {trash_bin: 1.2})
        self.assertEqual((bottle,), result.active)
        self.assertEqual((), result.already_in_bin)

        result = classify_bottles_with_depth(
            [bottle], [trash_bin], {bottle: 1.1}, {trash_bin: 1.2})
        self.assertEqual((), result.active)
        self.assertEqual((bottle,), result.already_in_bin)

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

"""Pure 2D perception decisions shared by offline and ROS detectors."""

import math
from dataclasses import dataclass
from enum import Enum
from typing import Iterable, List, Optional, Sequence, Tuple


@dataclass(frozen=True)
class Detection2D:
    """One axis-aligned image detection."""

    label: str
    confidence: float
    x1: float
    y1: float
    x2: float
    y2: float
    source: str = ''

    @property
    def width(self) -> float:
        return max(0.0, self.x2 - self.x1)

    @property
    def height(self) -> float:
        return max(0.0, self.y2 - self.y1)

    @property
    def area(self) -> float:
        return self.width * self.height

    @property
    def center(self) -> Tuple[float, float]:
        return ((self.x1 + self.x2) / 2.0, (self.y1 + self.y2) / 2.0)


@dataclass(frozen=True)
class BottleClassification:
    """Bottle split after applying the bin-interior exclusion rule."""

    active: Tuple[Detection2D, ...]
    already_in_bin: Tuple[Detection2D, ...]


class DisposalPhase(str, Enum):
    """High-level task phases that do not command hardware directly."""

    SEARCHING_BOTTLE = 'searching_bottle'
    BOTTLE_TARGET_READY = 'bottle_target_ready'
    CARRYING_BOTTLE = 'carrying_bottle'
    SEARCHING_BIN = 'searching_bin'
    BIN_TARGET_READY = 'bin_target_ready'
    READY_TO_DROP = 'ready_to_drop'
    VERIFYING_DROP = 'verifying_drop'
    SUCCEEDED = 'succeeded'
    FAILED = 'failed'


class DisposalStateMachine:
    """Guard the intended perception/execution order without driving motors."""

    def __init__(self) -> None:
        self.phase = DisposalPhase.SEARCHING_BOTTLE

    def observe(
            self, active_bottles: Sequence[Detection2D],
            bins: Sequence[Detection2D]) -> DisposalPhase:
        if self.phase == DisposalPhase.SEARCHING_BOTTLE and active_bottles:
            self.phase = DisposalPhase.BOTTLE_TARGET_READY
        elif self.phase == DisposalPhase.SEARCHING_BIN and bins:
            self.phase = DisposalPhase.BIN_TARGET_READY
        return self.phase

    def confirm_bottle_acquired(self) -> DisposalPhase:
        self._require(DisposalPhase.BOTTLE_TARGET_READY)
        self.phase = DisposalPhase.CARRYING_BOTTLE
        return self.phase

    def begin_bin_search(self) -> DisposalPhase:
        self._require(DisposalPhase.CARRYING_BOTTLE)
        self.phase = DisposalPhase.SEARCHING_BIN
        return self.phase

    def confirm_bin_aligned(self) -> DisposalPhase:
        self._require(DisposalPhase.BIN_TARGET_READY)
        self.phase = DisposalPhase.READY_TO_DROP
        return self.phase

    def confirm_drop_commanded(self) -> DisposalPhase:
        self._require(DisposalPhase.READY_TO_DROP)
        self.phase = DisposalPhase.VERIFYING_DROP
        return self.phase

    def finish_verification(self, success: bool) -> DisposalPhase:
        self._require(DisposalPhase.VERIFYING_DROP)
        self.phase = (
            DisposalPhase.SUCCEEDED if success else DisposalPhase.FAILED)
        return self.phase

    def reset(self) -> DisposalPhase:
        self.phase = DisposalPhase.SEARCHING_BOTTLE
        return self.phase

    def _require(self, expected: DisposalPhase) -> None:
        if self.phase != expected:
            raise RuntimeError(
                f'invalid transition from {self.phase.value}; '
                f'expected {expected.value}')


def intersection_area(first: Detection2D, second: Detection2D) -> float:
    """Return intersection area of two boxes."""
    width = max(0.0, min(first.x2, second.x2) - max(first.x1, second.x1))
    height = max(0.0, min(first.y2, second.y2) - max(first.y1, second.y1))
    return width * height


def bin_opening_region(
        bin_detection: Detection2D, horizontal_margin_ratio: float = 0.0,
        opening_height_ratio: float = 0.62) -> Detection2D:
    """Approximate the open upper region of an upright trash bin box."""
    margin = bin_detection.width * horizontal_margin_ratio
    return Detection2D(
        label='trash_bin_opening',
        confidence=bin_detection.confidence,
        x1=bin_detection.x1 + margin,
        y1=bin_detection.y1,
        x2=bin_detection.x2 - margin,
        y2=bin_detection.y1 + bin_detection.height * opening_height_ratio,
        source=bin_detection.source,
    )


def bottle_is_in_bin(
        bottle: Detection2D, bins: Iterable[Detection2D],
        overlap_threshold: float = 0.30,
        horizontal_margin_ratio: float = 0.0,
        opening_height_ratio: float = 0.62,
        bottle_depth_m: float = None,
        bin_depth_m: float = None,
        max_depth_difference_m: float = 0.20,
        require_depth: bool = False) -> bool:
    """Classify a visible bottle as disposed using a conservative ROI."""
    if bottle.area <= 0.0:
        return False
    center_x, center_y = bottle.center
    for bin_detection in bins:
        opening = bin_opening_region(
            bin_detection, horizontal_margin_ratio, opening_height_ratio)
        center_inside = (
            opening.x1 <= center_x <= opening.x2
            and opening.y1 <= center_y <= opening.y2)
        overlap = intersection_area(bottle, opening) / bottle.area
        depth_consistent = (
            (not require_depth
             and bottle_depth_m is None and bin_depth_m is None)
            or (isinstance(bottle_depth_m, (int, float))
                and isinstance(bin_depth_m, (int, float))
                and math.isfinite(bottle_depth_m)
                and math.isfinite(bin_depth_m)
                and abs(bottle_depth_m - bin_depth_m)
                <= max_depth_difference_m))
        if center_inside and overlap >= overlap_threshold and depth_consistent:
            return True
    return False


def classify_bottles(
        bottles: Iterable[Detection2D], bins: Iterable[Detection2D],
        overlap_threshold: float = 0.30,
        horizontal_margin_ratio: float = 0.0,
        opening_height_ratio: float = 0.62) -> BottleClassification:
    """Split bottle detections into actionable and already-disposed groups."""
    bin_list = tuple(bins)
    active: List[Detection2D] = []
    already_in_bin: List[Detection2D] = []
    for bottle in bottles:
        if bottle_is_in_bin(
                bottle, bin_list, overlap_threshold,
                horizontal_margin_ratio, opening_height_ratio):
            already_in_bin.append(bottle)
        else:
            active.append(bottle)
    return BottleClassification(tuple(active), tuple(already_in_bin))


def classify_bottles_with_depth(
        bottles: Iterable[Detection2D], bins: Iterable[Detection2D],
        bottle_depths, bin_depths,
        overlap_threshold: float = 0.30,
        horizontal_margin_ratio: float = 0.0,
        opening_height_ratio: float = 0.62,
        max_depth_difference_m: float = 0.20) -> BottleClassification:
    """Require both 2D opening overlap and compatible metric depth."""
    bin_list = tuple(bins)
    active: List[Detection2D] = []
    already_in_bin: List[Detection2D] = []
    for bottle in bottles:
        contained = False
        for bin_detection in bin_list:
            if bottle_is_in_bin(
                    bottle, (bin_detection,), overlap_threshold,
                    horizontal_margin_ratio, opening_height_ratio,
                    bottle_depths.get(bottle), bin_depths.get(bin_detection),
                    max_depth_difference_m, True):
                contained = True
                break
        (already_in_bin if contained else active).append(bottle)
    return BottleClassification(tuple(active), tuple(already_in_bin))


def select_target_bottle(
        bottles: Sequence[Detection2D]) -> Optional[Detection2D]:
    """Select a valid bottle by confidence with deterministic tie-breaks."""
    # Invalid or non-bottle candidates are ignored fail-closed. Area is only a
    # tie-breaker, so a huge low-confidence box cannot outrank a stronger box.
    valid = [
        item for item in bottles
        if (
            item.label == 'plastic_bottle'
            and math.isfinite(item.confidence)
            and 0.0 <= item.confidence <= 1.0
            and all(math.isfinite(value) for value in (
                item.x1, item.y1, item.x2, item.y2))
            and item.width > 0.0
            and item.height > 0.0
        )
    ]
    if not valid:
        return None
    return max(
        valid,
        key=lambda item: (item.confidence, item.area, item.y2, -item.x1),
    )


def select_target_bin(
        bins: Sequence[Detection2D]) -> Optional[Detection2D]:
    """Select a valid bin by confidence with deterministic tie-breaks."""
    valid = [
        item for item in bins
        if (
            item.label == 'trash_bin'
            and math.isfinite(item.confidence)
            and 0.0 <= item.confidence <= 1.0
            and all(math.isfinite(value) for value in (
                item.x1, item.y1, item.x2, item.y2))
            and item.width > 0.0
            and item.height > 0.0
        )
    ]
    if not valid:
        return None
    return max(
        valid,
        key=lambda item: (item.confidence, item.area, item.y2, -item.x1),
    )

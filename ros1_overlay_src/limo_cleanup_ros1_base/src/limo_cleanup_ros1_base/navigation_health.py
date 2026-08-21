"""Pure freshness gates for ROS1 scan and navigation TF evidence."""

import math
from collections import deque


MAX_TF_FUTURE_TOLERANCE = 0.1
EXPECTED_AMCL_TRANSFORM_TOLERANCE = 0.05
EXPECTED_SCAN_MIN_HZ = 4.8
EXPECTED_SCAN_MAX_HZ = 7.2
EXPECTED_SCAN_RANGE_MIN = 0.02
EXPECTED_SCAN_RANGE_MAX = 16.0
EXPECTED_SCAN_ANGLE_MIN = math.radians(-100.0)
EXPECTED_SCAN_ANGLE_MAX = math.radians(100.0)
EXPECTED_SCAN_ANGLE_TOLERANCE = 0.05
EXPECTED_SCAN_MIN_BEAMS = 360
EXPECTED_SCAN_MIN_FINITE_RATIO = 0.05
EXPECTED_SCAN_WINDOW_SAMPLES = 10


def transform_tolerance_contract_ready(
        configured_amcl_tolerance: float,
        expected_amcl_tolerance: float,
        bridge_future_tolerance: float,
        equality_tolerance: float = 1e-9) -> bool:
    """Require configured AMCL timing to match the project 0.05 s value."""
    values = (
        configured_amcl_tolerance,
        expected_amcl_tolerance,
        bridge_future_tolerance,
        equality_tolerance,
    )
    if any(isinstance(value, bool) for value in values):
        return False
    if not all(math.isfinite(value) for value in values):
        return False
    if (
            configured_amcl_tolerance < 0.0
            or expected_amcl_tolerance < 0.0
            or bridge_future_tolerance < 0.0
            or bridge_future_tolerance > MAX_TF_FUTURE_TOLERANCE
            or expected_amcl_tolerance > bridge_future_tolerance
            or equality_tolerance < 0.0):
        return False
    if (
            abs(
                expected_amcl_tolerance
                - EXPECTED_AMCL_TRANSFORM_TOLERANCE)
            > equality_tolerance):
        return False
    return (
        abs(configured_amcl_tolerance - expected_amcl_tolerance)
        <= equality_tolerance
    )


def timestamp_is_fresh(
        source_stamp: float,
        now: float,
        timeout: float,
        future_tolerance: float = 0.1) -> bool:
    """Require a finite nonzero source stamp newer than the timeout."""
    values = (source_stamp, now, timeout, future_tolerance)
    if not all(math.isfinite(value) for value in values):
        return False
    if source_stamp <= 0.0 or now <= 0.0 or timeout <= 0.0:
        return False
    if (
            future_tolerance < 0.0
            or future_tolerance > MAX_TF_FUTURE_TOLERANCE):
        return False
    age = now - source_stamp
    return -future_tolerance <= age < timeout


def received_sample_is_fresh(
        received_at: float,
        source_stamp: float,
        monotonic_now: float,
        ros_now: float,
        timeout: float,
        future_tolerance: float = 0.1) -> bool:
    """Require both recent receipt and a recent ROS source timestamp."""
    values = (received_at, monotonic_now, timeout)
    if not all(math.isfinite(value) for value in values):
        return False
    if received_at < 0.0 or monotonic_now < received_at or timeout <= 0.0:
        return False
    return (
        monotonic_now - received_at < timeout
        and timestamp_is_fresh(
            source_stamp,
            ros_now,
            timeout,
            future_tolerance,
        )
    )


def navigation_health_ready(
        server_ready: bool,
        scan_fresh: bool,
        tf_ready: bool) -> bool:
    """Combine every navigation prerequisite with AND semantics."""
    return bool(server_ready and scan_fresh and tf_ready)


def _scan_sample_ready(
        ranges, range_min, range_max, angle_min, angle_max,
        angle_increment,
        expected_angle_min=EXPECTED_SCAN_ANGLE_MIN,
        expected_angle_max=EXPECTED_SCAN_ANGLE_MAX,
        minimum_beams=EXPECTED_SCAN_MIN_BEAMS) -> bool:
    """Validate one complete scan before it can enter a health window."""
    values = (
        range_min, range_max, angle_min, angle_max, angle_increment,
        expected_angle_min, expected_angle_max)
    if not all(isinstance(value, (int, float)) and not isinstance(value, bool)
               and math.isfinite(value) for value in values):
        return False
    if (
            abs(range_min - EXPECTED_SCAN_RANGE_MIN) > 1e-6
            or abs(range_max - EXPECTED_SCAN_RANGE_MAX) > 1e-6
            or abs(angle_min - expected_angle_min)
            > EXPECTED_SCAN_ANGLE_TOLERANCE
            or abs(angle_max - expected_angle_max)
            > EXPECTED_SCAN_ANGLE_TOLERANCE
            or angle_increment <= 0.0):
        return False
    values_list = list(ranges)
    if (
            isinstance(minimum_beams, bool)
            or not isinstance(minimum_beams, int)
            or minimum_beams < 2
            or len(values_list) < minimum_beams):
        return False
    expected_span = angle_increment * (len(values_list) - 1)
    if abs((angle_max - angle_min) - expected_span) > max(
            1e-4, angle_increment * 2.0):
        return False
    finite_count = 0
    for value in values_list:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return False
        numeric = float(value)
        if math.isnan(numeric) or numeric == -math.inf:
            return False
        if math.isfinite(numeric):
            if numeric < range_min or numeric > range_max:
                return False
            finite_count += 1
        elif numeric != math.inf:
            return False
    if finite_count / len(values_list) < EXPECTED_SCAN_MIN_FINITE_RATIO:
        return False
    return True


def scan_contract_ready(
        ranges, range_min, range_max, angle_min, angle_max,
        angle_increment, receipt_times,
        minimum_hz=EXPECTED_SCAN_MIN_HZ,
        maximum_hz=EXPECTED_SCAN_MAX_HZ,
        expected_angle_min=EXPECTED_SCAN_ANGLE_MIN,
        expected_angle_max=EXPECTED_SCAN_ANGLE_MAX,
        minimum_beams=EXPECTED_SCAN_MIN_BEAMS) -> bool:
    """Require one full YDLidar scan plus a continuous ten-scan window."""
    if (
            not _scan_sample_ready(
                ranges, range_min, range_max, angle_min, angle_max,
                angle_increment, expected_angle_min, expected_angle_max,
                minimum_beams)
            or minimum_hz != EXPECTED_SCAN_MIN_HZ
            or maximum_hz != EXPECTED_SCAN_MAX_HZ):
        return False
    times = list(receipt_times)
    if (
            len(times) < EXPECTED_SCAN_WINDOW_SAMPLES
            or not all(math.isfinite(value) for value in times)):
        return False
    minimum_interval = 1.0 / maximum_hz
    maximum_interval = 1.0 / minimum_hz
    interval_epsilon = 1e-9
    return all(
        minimum_interval - interval_epsilon
        <= later - earlier
        <= maximum_interval + interval_epsilon
        for earlier, later in zip(times, times[1:]))


class ScanWindow:
    """Build a strict ten-sample YDLidar health capability."""

    def __init__(
            self, sample_count=EXPECTED_SCAN_WINDOW_SAMPLES,
            expected_angle_min=EXPECTED_SCAN_ANGLE_MIN,
            expected_angle_max=EXPECTED_SCAN_ANGLE_MAX,
            minimum_beams=EXPECTED_SCAN_MIN_BEAMS):
        if sample_count < EXPECTED_SCAN_WINDOW_SAMPLES:
            raise ValueError('scan window requires at least ten samples')
        self.sample_count = sample_count
        self.expected_angle_min = expected_angle_min
        self.expected_angle_max = expected_angle_max
        self.minimum_beams = minimum_beams
        self.receipts = deque(maxlen=sample_count)
        self.source_stamps = deque(maxlen=sample_count)
        self.highest_source_stamp = None
        self.last_metadata = None

    def clear(self):
        self.receipts.clear()
        self.source_stamps.clear()
        self.last_metadata = None

    def add(
            self, *, frame_id, expected_frame, ranges, range_min, range_max,
            angle_min, angle_max, angle_increment, source_stamp, receipt_time,
            ros_now, timeout, future_tolerance=MAX_TF_FUTURE_TOLERANCE):
        numeric = (
            source_stamp, receipt_time, ros_now, timeout, future_tolerance,
            range_min, range_max, angle_min, angle_max, angle_increment)
        if (
                frame_id != expected_frame
                or not all(math.isfinite(value) for value in numeric)
                or receipt_time < 0.0
                or not timestamp_is_fresh(
                    source_stamp, ros_now, timeout, future_tolerance)):
            self.clear()
            return False
        # Validate every individual sample before it can contribute to the
        # continuous window.  A bad sample atomically discards all history.
        if not _scan_sample_ready(
                ranges, range_min, range_max, angle_min, angle_max,
                angle_increment, self.expected_angle_min,
                self.expected_angle_max, self.minimum_beams):
            self.clear()
            return False
        if (
                self.highest_source_stamp is not None
                and source_stamp <= self.highest_source_stamp):
            self.clear()
            return False
        self.highest_source_stamp = source_stamp
        metadata = (
            float(range_min), float(range_max), float(angle_min),
            float(angle_max), float(angle_increment), len(ranges))
        if self.last_metadata is not None and metadata != self.last_metadata:
            self.clear()
        self.last_metadata = metadata
        if self.receipts:
            interval = receipt_time - self.receipts[-1]
            if not (
                    1.0 / EXPECTED_SCAN_MAX_HZ - 1e-9
                    <= interval
                    <= 1.0 / EXPECTED_SCAN_MIN_HZ + 1e-9):
                self.clear()
                self.last_metadata = metadata
        self.receipts.append(receipt_time)
        self.source_stamps.append(source_stamp)
        if not scan_contract_ready(
                ranges, range_min, range_max, angle_min, angle_max,
                angle_increment, self.receipts,
                expected_angle_min=self.expected_angle_min,
                expected_angle_max=self.expected_angle_max,
                minimum_beams=self.minimum_beams):
            if len(self.receipts) >= self.sample_count:
                self.clear()
            return False
        return len(self.receipts) >= self.sample_count

    def ready(
            self, monotonic_now, ros_now, timeout,
            future_tolerance=MAX_TF_FUTURE_TOLERANCE):
        return (
            len(self.receipts) >= self.sample_count
            and received_sample_is_fresh(
                self.receipts[-1], self.source_stamps[-1], monotonic_now,
                ros_now, timeout, future_tolerance)
        )


class TransformChainWindow:
    """Track every required TF edge independently with monotonic stamps."""

    REQUIRED_SEGMENTS = ('map_to_odom', 'odom_to_base', 'base_to_laser')

    def __init__(self):
        self.stamps = {}
        self.receipts = {}

    def invalidate(self):
        self.stamps.clear()
        self.receipts.clear()

    def update(
            self, segment, source_stamp, receipt_time, ros_now,
            translation, rotation, timeout, future_tolerance):
        if segment not in self.REQUIRED_SEGMENTS:
            self.invalidate()
            return False
        if not transform_values_ready(translation, rotation):
            self.invalidate()
            return False
        previous = self.stamps.get(segment)
        if previous is not None and source_stamp < previous:
            self.invalidate()
            return False
        if previous is not None and source_stamp == previous:
            return received_sample_is_fresh(
                self.receipts[segment], source_stamp, receipt_time, ros_now,
                timeout, future_tolerance)
        if not received_sample_is_fresh(
                receipt_time, source_stamp, receipt_time, ros_now,
                timeout, future_tolerance):
            self.invalidate()
            return False
        self.stamps[segment] = source_stamp
        self.receipts[segment] = receipt_time
        return True

    def ready(
            self, monotonic_now, ros_now, timeout,
            future_tolerance=MAX_TF_FUTURE_TOLERANCE):
        if set(self.stamps) != set(self.REQUIRED_SEGMENTS):
            return False
        return all(received_sample_is_fresh(
            self.receipts[segment], self.stamps[segment], monotonic_now,
            ros_now, timeout, future_tolerance)
            for segment in self.REQUIRED_SEGMENTS)


def transform_values_ready(translation, rotation, tolerance=1e-6) -> bool:
    """Require finite translation and a normalized finite quaternion."""
    values = tuple(translation) + tuple(rotation)
    if len(translation) != 3 or len(rotation) != 4:
        return False
    if not all(math.isfinite(float(value)) for value in values):
        return False
    norm = math.sqrt(sum(float(value) ** 2 for value in rotation))
    return abs(norm - 1.0) <= tolerance

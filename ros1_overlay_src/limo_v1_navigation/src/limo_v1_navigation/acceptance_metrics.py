"""Pure metrics for separating localization and controller endpoint error."""

from dataclasses import dataclass
import math
import statistics

from limo_v1_navigation.localization_policy import angular_distance


@dataclass(frozen=True)
class PlanarPose:
    x: float
    y: float
    yaw: float


def _validated_pose(pose, name):
    if not isinstance(pose, PlanarPose):
        raise ValueError('{} must be PlanarPose'.format(name))
    values = (pose.x, pose.y, pose.yaw)
    if any(isinstance(value, bool) or not isinstance(value, (int, float))
           or not math.isfinite(float(value)) for value in values):
        raise ValueError('{} values must be finite numeric'.format(name))
    return pose


def pose_error(reference, measured):
    reference = _validated_pose(reference, 'reference')
    measured = _validated_pose(measured, 'measured')
    return {
        'position_m': math.hypot(
            measured.x - reference.x, measured.y - reference.y),
        'yaw_rad': angular_distance(measured.yaw, reference.yaw),
    }


def split_endpoint_errors(goal, amcl_final, ground_truth_final):
    """Return the three non-interchangeable V1 endpoint error components."""
    goal = _validated_pose(goal, 'goal')
    amcl_final = _validated_pose(amcl_final, 'amcl_final')
    ground_truth_final = _validated_pose(
        ground_truth_final, 'ground_truth_final')
    return {
        'amcl_estimation_error': pose_error(
            ground_truth_final, amcl_final),
        'controller_estimated_frame_error': pose_error(
            goal, amcl_final),
        'physical_total_endpoint_error': pose_error(
            goal, ground_truth_final),
    }


def repeatability(samples):
    """Summarize fixed-pose AMCL spread without claiming absolute accuracy."""
    samples = list(samples)
    if len(samples) < 2:
        raise ValueError('at least two pose samples are required')
    for index, sample in enumerate(samples):
        _validated_pose(sample, 'samples[{}]'.format(index))
    xs = [sample.x for sample in samples]
    ys = [sample.y for sample in samples]
    sin_mean = statistics.fmean(math.sin(sample.yaw) for sample in samples)
    cos_mean = statistics.fmean(math.cos(sample.yaw) for sample in samples)
    resultant = math.hypot(sin_mean, cos_mean)
    circular_std = (
        math.sqrt(max(0.0, -2.0 * math.log(resultant)))
        if 0.0 < resultant <= 1.0 else math.inf)
    return {
        'samples': len(samples),
        'mean_x_m': statistics.fmean(xs),
        'mean_y_m': statistics.fmean(ys),
        'stddev_x_m': statistics.stdev(xs),
        'stddev_y_m': statistics.stdev(ys),
        'circular_std_yaw_rad': circular_std,
        'span_position_m': math.hypot(max(xs) - min(xs), max(ys) - min(ys)),
    }


def threshold_result(value, maximum):
    """Return an explicit pass/fail record without hiding the raw metric."""
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(float(value))):
        raise ValueError('threshold value must be finite numeric')
    if (isinstance(maximum, bool) or not isinstance(maximum, (int, float))
            or not math.isfinite(float(maximum)) or maximum <= 0.0):
        raise ValueError('threshold maximum must be finite and positive')
    return {
        'value': float(value),
        'maximum': float(maximum),
        'passed': float(value) <= float(maximum),
    }

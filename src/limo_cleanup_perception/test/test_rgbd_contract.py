"""Unit tests for the fail-closed aligned RGB-D runtime contract."""

from pathlib import Path

from limo_cleanup_perception.rgbd_contract import (
    StreamMetadata,
    nearest_by_stamp,
    validate_rgbd_contract,
)


def metadata(name, stamp=10.0, frame='camera_color_optical_frame',
             width=640, height=480):
    """Build compact stream metadata for contract tests."""
    encoding = '16UC1' if name == 'depth' else ''
    return StreamMetadata(name, stamp, frame, width, height, encoding)


def test_aligned_four_stream_bundle_passes():
    """All streams may differ slightly in time within the configured span."""
    result = validate_rgbd_contract(
        metadata('rgb', 10.000),
        metadata('depth', 10.036),
        metadata('rgb_info', 10.010),
        metadata('depth_info', 10.020),
        0.15,
    )
    assert result.accepted
    assert result.reasons == ()
    assert abs(result.timestamp_span_sec - 0.036) < 1e-12


def test_timestamp_span_is_fail_closed():
    """A stale CameraInfo message must reject the whole bundle."""
    result = validate_rgbd_contract(
        metadata('rgb', 10.0),
        metadata('depth', 10.02),
        metadata('rgb_info', 9.70),
        metadata('depth_info', 10.01),
        0.15,
    )
    assert not result.accepted
    assert 'timestamp_span_exceeded' in result.reasons


def test_invalid_stamp_reports_json_safe_null_span():
    """Invalid timestamps must reject without emitting Infinity into JSON."""
    result = validate_rgbd_contract(
        metadata('rgb', float('nan')),
        metadata('depth'), metadata('rgb_info'), metadata('depth_info'),
        0.15,
    )
    assert not result.accepted
    assert result.reasons[0] == 'invalid_stamp:rgb'
    assert result.timestamp_span_sec is None


def test_zero_stamp_is_uninitialized_and_rejected():
    """ROS zero time is not a usable sensor timestamp."""
    result = validate_rgbd_contract(
        metadata('rgb', 0.0), metadata('depth', 0.0),
        metadata('rgb_info', 0.0), metadata('depth_info', 0.0), 0.15)
    assert not result.accepted
    assert result.reasons == (
        'invalid_stamp:rgb,depth,rgb_info,depth_info',)
    assert result.timestamp_span_sec is None


def test_frame_mismatch_and_empty_frame_are_rejected():
    """Aligned depth and both CameraInfo streams must use the RGB frame."""
    mismatch = validate_rgbd_contract(
        metadata('rgb'),
        metadata('depth', frame='camera_depth_optical_frame'),
        metadata('rgb_info'),
        metadata('depth_info'),
        0.15,
    )
    assert mismatch.reasons == ('frame_mismatch',)

    empty = validate_rgbd_contract(
        metadata('rgb'), metadata('depth'),
        metadata('rgb_info', frame=''), metadata('depth_info'), 0.15)
    assert empty.reasons == ('empty_frame:rgb_info',)


def test_resolution_mismatch_and_invalid_grid_are_rejected():
    """All four streams must describe the same positive RGB pixel grid."""
    mismatch = validate_rgbd_contract(
        metadata('rgb'), metadata('depth', width=320),
        metadata('rgb_info'), metadata('depth_info'), 0.15)
    assert mismatch.reasons == ('resolution_mismatch',)

    invalid = validate_rgbd_contract(
        metadata('rgb'), metadata('depth'),
        metadata('rgb_info'), metadata('depth_info', height=0), 0.15)
    assert invalid.reasons == ('invalid_resolution:depth_info',)


def test_depth_encoding_is_part_of_the_four_stream_contract():
    depth = metadata('depth')
    depth = StreamMetadata(
        depth.name, depth.stamp_sec, depth.frame_id,
        depth.width, depth.height, '8UC1')
    result = validate_rgbd_contract(
        metadata('rgb'), depth, metadata('rgb_info'),
        metadata('depth_info'), 0.15)
    assert result.reasons == ('invalid_depth_encoding',)


def test_nearest_by_stamp_uses_stream_metadata():
    """The nearest buffered candidate should be selected deterministically."""
    candidates = [
        (metadata('depth', 9.8), 'stale'),
        (metadata('depth', 10.03), 'nearest'),
        (metadata('depth', 10.2), 'future'),
    ]
    assert nearest_by_stamp(10.0, candidates)[1] == 'nearest'
    assert nearest_by_stamp(10.0, []) is None


def test_detector_requires_four_stream_contract_before_processing():
    """The ROS detector must retain the four-stream fail-closed integration."""
    source = (
        Path(__file__).parents[1]
        / 'limo_cleanup_perception/dual_model_detector.py'
    ).read_text(encoding='utf-8')
    assert "('depth_camera_info_topic', '/camera/depth/camera_info')" in source
    assert 'self.depth_camera_info_callback' in source
    assert 'validate_rgbd_contract(' in source
    assert "'rgbd_contract_rejected'" in source
    assert "'waiting_for_rgb_depth_camera_info_bundle'" in source


if __name__ == '__main__':
    import inspect

    tests = [
        value for name, value in sorted(globals().items())
        if name.startswith('test_') and inspect.isfunction(value)]
    for test in tests:
        test()
    print('{} rgbd-contract checks passed'.format(len(tests)))

"""Static safety contract for the typed-frame evidence collector."""

from pathlib import Path


SOURCE = (
    Path(__file__).parents[1]
    / 'limo_cleanup_perception/perception_frame_collector.py'
).read_text(encoding='utf-8')


def test_collector_subscribes_to_typed_frame_and_never_publishes():
    """The collector is a subscriber and filesystem writer only."""
    assert "PerceptionFrame, '/cleanup/perception/frames'" in SOURCE
    assert 'create_subscription(' in SOURCE
    assert 'create_publisher(' not in SOURCE
    assert '.publish(' not in SOURCE
    assert 'Twist' not in SOURCE
    assert 'NavigateToPose' not in SOURCE


def test_collector_is_bounded_and_writes_a_hashed_manifest():
    """Field collection must stop and produce a machine-readable manifest."""
    assert "parser.add_argument('--max-frames'" in SOURCE
    assert "parser.add_argument('--duration-sec'" in SOURCE
    assert "'sha256': sha256_file(parsed.output)" in SOURCE
    assert "'authorizes_motion': False" in SOURCE
    assert "'publishes_ros_messages': False" in SOURCE
    assert "output_path.open('x'" in SOURCE
    assert "parsed.manifest.open('x'" in SOURCE
    assert "if parsed.max_frames < 30:" in SOURCE
    assert 'max-frames cannot be lower than 30' in SOURCE
    assert 'node.unique_frames >= parsed.max_frames' in SOURCE
    assert 'node.duplicate_sequences == 0' in SOURCE
    assert 'node.serialization_errors == 0' in SOURCE


if __name__ == '__main__':
    test_collector_subscribes_to_typed_frame_and_never_publishes()
    test_collector_is_bounded_and_writes_a_hashed_manifest()
    print('2 source-contract checks passed')

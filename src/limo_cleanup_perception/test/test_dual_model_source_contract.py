"""Static ROS source checks for the dual-class read-only frame contract."""

from pathlib import Path


SOURCE = (
    Path(__file__).parents[1]
    / 'limo_cleanup_perception/dual_model_detector.py'
).read_text(encoding='utf-8')


def test_detector_publishes_typed_read_only_frames():
    """The detector must publish the new target frame without control APIs."""
    assert "PerceptionFrame, '/cleanup/perception/frames'" in SOURCE
    assert 'self.publish_perception_frame(' in SOURCE
    assert "message.position_semantics = (" in SOURCE
    assert 'Twist' not in SOURCE
    assert '/cmd_vel' not in SOURCE
    assert 'NavigateToPose' not in SOURCE


def test_legacy_topic_remains_actionable_bottle_only():
    """Trash-bin observations must not enter the executor-facing raw topic."""
    assert "ObjectDetection, '/cleanup/detection/raw'" in SOURCE
    publish_method = SOURCE.split(
        'def publish_detection(', 1)[1].split('def publish_status(', 1)[0]
    assert "message.object_class = 'plastic_bottle'" in publish_method
    assert "message.object_class = 'trash_bin'" not in publish_method
    assert "header, target_bottle, 'active'" in SOURCE
    assert 'legacy_actionable' not in SOURCE


def test_model_and_frame_identity_fail_closed():
    """Swapped weights and fake frame overrides are rejected at startup."""
    assert "self.bottle_model.names, 'plastic_bottle'" in SOURCE
    assert "self.bin_model.names, 'trash_bin'" in SOURCE
    assert 'frame_id_override cannot relabel untransformed coordinates' in SOURCE
    assert 'EXPECTED_MODEL_SHA256' in SOURCE
    assert 'model SHA-256 mismatch' in SOURCE


def test_bottle_and_bin_share_projection_quality_contract():
    """Both target classes must call the same pure projection helper."""
    assert SOURCE.count('project_detection(') >= 2
    assert 'classify_bottles_with_depth(' in SOURCE
    assert "actionable=True, status='active'" in SOURCE
    assert "actionable=False, status='observed'" in SOURCE
    assert 'depth_valid_ratio=projection.valid_ratio' in SOURCE
    assert "frame_status = 'targets_invalid'" in SOURCE
    assert "frame_error_code = 'all_target_projections_invalid'" in SOURCE
    assert "message.valid = status in ('targets_ready', 'no_targets')" in SOURCE


def test_bottle_or_bin_read_only_task_can_activate_typed_perception():
    assert "message.object_class in ('plastic_bottle', 'trash_bin')" in SOURCE


if __name__ == '__main__':
    import inspect

    tests = [
        value for name, value in sorted(globals().items())
        if name.startswith('test_') and inspect.isfunction(value)]
    for test in tests:
        test()
    print('{} dual-model source-contract checks passed'.format(len(tests)))

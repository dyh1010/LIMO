"""Static contract for the no-ROS runtime/model preflight."""

from pathlib import Path


SOURCE = (
    Path(__file__).parents[3] / 'scripts/perception_release_preflight.py'
).read_text(encoding='utf-8')


def test_runtime_preflight_loads_both_exact_single_class_models():
    runtime_branch = SOURCE.split('if args.require_runtime:', 1)[1]
    assert 'from ultralytics import YOLO' in runtime_branch
    assert "checks, 'models_load_and_labels_match'" in runtime_branch
    assert "0: 'plastic_bottle'" in runtime_branch
    assert "0: 'trash_bin'" in runtime_branch


def test_runtime_preflight_has_no_ros_or_motion_api():
    for token in (
            'rclpy', 'rospy', 'create_publisher(', '.publish(',
            'ActionClient', 'NavigateToPose', 'Twist', '/cmd_vel'):
        assert token not in SOURCE


def test_runtime_preflight_binds_release_source_manifest_and_models():
    for token in (
            "parser.add_argument('--release-id', required=True)",
            "parser.add_argument('--source-manifest'",
            "'source_manifest_artifact_sha256':",
            "'source_set_sha256': source_set_sha256",
            "'model_sha256': {",
            "'plastic_bottle': model_results.get(",
            "'trash_bin': model_results.get("):
        assert token in SOURCE

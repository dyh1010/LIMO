"""Static safety contract for the source-manifest generator."""

from pathlib import Path


SOURCE = (Path(__file__).parents[3]
          / 'scripts/generate_perception_source_manifest.py').read_text(
              encoding='utf-8')


def test_manifest_generator_is_filesystem_only_and_exclusive():
    for token in (
            'rclpy', 'rospy', 'create_publisher(', '.publish(',
            'subprocess', 'socket.', 'requests.', 'Twist(',
            'NavigateToPose('):
        assert token not in SOURCE
    assert "args.output.open('x'" in SOURCE
    assert "'authorizes_motion': False" in SOURCE
    assert "'publishes_ros_messages': False" in SOURCE
    assert "('interfaces', 'src/limo_cleanup_interfaces')" in SOURCE
    assert "('perception', 'src/limo_cleanup_perception')" in SOURCE
    assert "package_root.rglob('*')" in SOURCE
    assert "'source_set_sha256'" in SOURCE


def test_manifest_scope_includes_current_offline_typed_raw_binder():
    """The complete package manifest cannot predate the offline binder."""
    import importlib.util

    root = Path(__file__).parents[3]
    script = root / 'scripts/generate_perception_source_manifest.py'
    spec = importlib.util.spec_from_file_location(
        'perception_source_manifest_scope_test', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    files = module.discover_files(root)
    assert 'perception:limo_cleanup_perception/typed_raw_binding.py' in files
    assert 'perception:limo_cleanup_perception/evidence_binding.py' in files

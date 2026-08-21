"""Static safety and installation contract for the readiness command."""

import ast
import json
from pathlib import Path


ROOT = Path(__file__).parents[1]
SOURCE_PATH = ROOT / 'limo_cleanup_perception/perception_readiness.py'
SOURCE = SOURCE_PATH.read_text(encoding='utf-8')
SETUP = (ROOT / 'setup.py').read_text(encoding='utf-8')


def _call_terminal_name(node):
    """Return the statically visible terminal name for a call target."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _called_names(tree):
    return {
        _call_terminal_name(node.func)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    }


def test_readiness_is_pure_offline_and_has_no_motion_api():
    """The aggregator only reads evidence and writes one JSON report."""
    tree = ast.parse(SOURCE)
    imports = {
        alias.name for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    forbidden_imports = {
        'rclpy', 'rospy', 'launch', 'launch_ros', 'serial', 'socket',
        'nav2_msgs', 'control_msgs', 'trajectory_msgs', 'moveit_msgs',
    }
    assert not any(
        name == forbidden or name.startswith(forbidden + '.')
        for name in imports for forbidden in forbidden_imports)
    forbidden_calls = {
        'create_publisher', 'publish', 'create_subscription', 'create_client',
        'create_service', 'ActionClient', 'ActionServer', 'send_goal',
        'call_async', 'spin', 'Twist', 'NavigateToPose', 'JointTrajectory',
        'GripperCommand', 'ExecuteArmMotion', 'ExecuteGripperMotion',
    }
    assert not (_called_names(tree) & forbidden_calls)


def test_report_is_fail_closed_read_only_and_exclusive():
    """Delivery readiness is exactly the absence of validation failures."""
    assert "'read_only': True" in SOURCE
    assert "'authorizes_motion': False" in SOURCE
    assert "'publishes_ros_messages': False" in SOURCE
    assert "'delivery_ready': not failures" in SOURCE
    assert 'ROS2_AMENT_MIGRATION_OFFLINE_INSTALL_GATE' in SOURCE
    assert "'required_for_field_delivery': False" in SOURCE
    assert "'substitutes_for_ros1_field': False" in SOURCE
    assert "'non_delivery_failures': non_delivery_failures" in SOURCE
    assert "'offline_migration_passed': not non_delivery_failures" in SOURCE
    assert 'ROS1_NOETIC_FIELD_INSTALL' in SOURCE
    assert 'ROS1_NOETIC_PERCEPTION_RUNTIME_NOT_IMPLEMENTED' in SOURCE
    assert "payload.get('ros1_field_install_validation')" in SOURCE
    assert "with args.report.open('x'" in SOURCE
    assert "return 0 if report['delivery_ready'] else 1" in SOURCE


def test_setup_installs_python38_readiness_entry_and_fixtures():
    """Foxy-era Python can install and invoke the new offline command."""
    assert "python_requires='>=3.8'" in SETUP
    assert "'perception_readiness = '" in SETUP
    assert "'rgbd_bag_indexer = '" in SETUP
    assert "'typed_raw_binding = '" in SETUP
    assert 'perception_readiness:main' in SETUP
    assert 'perception_readiness_negative_cases.json' in SETUP
    assert 'perception_readiness_missing_bundle.json' in SETUP
    assert 'perception_readiness_bundle_template.json' in SETUP
    assert 'rgbd_expected_topics.json' in SETUP
    assert 'evidence_binding.py' in SOURCE
    assert 'canonical_file_manifest' in SOURCE
    assert 'typed_raw_payload_binding_mismatch' in SOURCE
    assert 'ground_truth_raw_rgb_binding_mismatch' in SOURCE
    assert 'known_depth_sample_binding_mismatch' in SOURCE
    assert 'scene_evidence_binding_mismatch' in SOURCE
    template = (ROOT / 'fixtures/perception_readiness_bundle_template.json').read_text(
        encoding='utf-8')
    assert '"path": "evidence_binding.py"' in template
    assert '"evidence_binding"' in template
    assert '"capture_provenance"' in template
    assert '"ros1_field_install_validation"' in template
    binder = (ROOT / 'limo_cleanup_perception/typed_raw_binding.py').read_text(
        encoding='utf-8')
    assert "parsed.output.open('x'" in binder
    assert 'create_publisher(' not in binder
    assert '.publish(' not in binder


def test_package_declares_python_runtime_dependencies():
    package_xml = (ROOT / 'package.xml').read_text(encoding='utf-8')
    for dependency in ('python3-numpy', 'python3-opencv'):
        assert '<exec_depend>{}</exec_depend>'.format(dependency) in package_xml
    # Torch, Ultralytics and exact YOLO model names are deliberately verified
    # by the fail-closed runtime preflight because Foxy package repositories do
    # not provide a portable rosdep key for the pinned Python wheels.
    assert 'runtime_preflight_not_passed' in SOURCE


def test_installed_layout_without_workspace_source_fails_closed():
    """Source scope discovery may never silently approve an empty install tree."""
    assert "if workspace is None:" in SOURCE
    assert "return ()" in SOURCE


def test_perception_package_publishers_remain_on_exact_read_only_allowlist():
    """New readiness work may not grow the ROS output or control surface."""
    expected = {
        'detection_gate.py': 2,
        'dual_model_detector.py': 3,
        'mock_perception.py': 1,
    }
    sources = ROOT / 'limo_cleanup_perception'
    actual = {}
    for path in sources.glob('*.py'):
        tree = ast.parse(path.read_text(encoding='utf-8'))
        count = sum(
            1 for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and _call_terminal_name(node.func) == 'create_publisher')
        if count:
            actual[path.name] = count
    assert actual == expected
    for path in sources.glob('*.py'):
        text = path.read_text(encoding='utf-8')
        tree = ast.parse(text)
        calls = _called_names(tree)
        assert not (calls & {
            'create_client', 'create_service', 'ActionClient', 'ActionServer',
            'NavigateToPose', 'send_goal', 'call_async', 'Twist',
            'JointTrajectory', 'GripperCommand', 'ExecuteArmMotion',
            'ExecuteGripperMotion',
        })
        if path.name == 'rgbd_bag_indexer.py':
            assert 'Twist' in text
            assert 'NavigateToPose' in text


def test_bundle_template_uses_the_frozen_six_topic_manifest_identity():
    """All scene bindings use the installed policy identity, never an alias."""
    manifest = json.loads((
        ROOT / 'fixtures/rgbd_expected_topics.json').read_text(
            encoding='utf-8'))
    template_path = ROOT / 'fixtures/perception_readiness_bundle_template.json'
    template_text = template_path.read_text(encoding='utf-8')
    template = json.loads(template_text)
    manifest_id = manifest['manifest_id']
    assert manifest_id == 'limo-dabai-rgbd-six-topics-v1'
    legacy_id = '-'.join(
        ('limo', 'v2', 'rgbd', 'six', 'topic', 'manifest', 'v1'))
    assert legacy_id not in template_text
    bound_ids = []
    for scene in ('background', 'bin_only', 'bottle_in_bin',
                  'bottle_outside'):
        declaration = template['scenes'][scene]
        bound_ids.append(declaration['evidence_binding'][
            'expected_topic_manifest']['manifest_id'])
        bound_ids.append(declaration['latency']['capture_provenance'][
            'expected_topic_manifest']['manifest_id'])
    assert len(bound_ids) == 8
    assert bound_ids == [manifest_id] * 8


if __name__ == '__main__':
    import inspect

    tests = [
        value for name, value in sorted(globals().items())
        if name.startswith('test_') and inspect.isfunction(value)]
    for test in tests:
        test()
    print('{} source-contract checks passed'.format(len(tests)))

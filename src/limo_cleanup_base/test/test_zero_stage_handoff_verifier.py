import ast
from pathlib import Path


WORKSPACE_ROOT = Path(__file__).parents[3]
PACKAGE_ROOT = Path(__file__).parents[1]
SCRIPT = (
    PACKAGE_ROOT / 'limo_cleanup_base' / 'zero_stage_handoff_verifier.py')


def test_handoff_verifier_is_read_only_and_exact_owner_only():
    source = SCRIPT.read_text(encoding='utf-8')
    ast.parse(source)
    assert "SAFE_TOPIC = '/cleanup/base/safe_cmd_vel'" in source
    assert "EXPECTED_CONTROLLER = '/cleanup_tracked_base_zero_output'" in source
    assert "EXPECTED_BRIDGE = '/dynamic_bridge'" in source
    assert "EXPECTED_ZERO_MONITOR = '/verify_ros1_bridge_ros2_zero_output'" in source
    assert 'create_subscription' not in source
    assert 'create_publisher' not in source
    assert 'ROS2_ZERO_STAGE_HANDOFF_PASS' in source
    assert 'validate_endpoint_metadata(' in source
    setup_source = (PACKAGE_ROOT / 'setup.py').read_text(encoding='utf-8')
    assert 'zero_stage_handoff_verifier = ' in setup_source
    assert (
        'limo_cleanup_base.zero_stage_handoff_verifier:main'
        in setup_source)

    runner_source = (
        WORKSPACE_ROOT / 'ros1_overlay_src' / 'limo_cleanup_ros1_base' /
        'scripts' / 'run_v2_bridged_navigation.py').read_text(
            encoding='utf-8')
    assert "'ros2', 'run', 'limo_cleanup_base'" in runner_source
    assert "'zero_stage_handoff_verifier'" in runner_source
    assert '_workspace_script' not in runner_source

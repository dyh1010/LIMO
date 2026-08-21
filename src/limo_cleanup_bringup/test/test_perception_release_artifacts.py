"""Static tests for controlled, fail-closed perception release tooling."""

import importlib.util
from pathlib import Path
import subprocess


ROOT = Path(__file__).parents[3]
SCRIPTS = ROOT / 'scripts'


def load_policy():
    """Load the standalone policy module without installing it."""
    path = SCRIPTS / 'perception_release_policy.py'
    spec = importlib.util.spec_from_file_location('release_policy', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_operator_docs():
    """Load the host-owned operator-document gate without installing it."""
    path = ROOT / 'audit_tools' / 'ros1_camera_only_operator_docs.py'
    spec = importlib.util.spec_from_file_location('operator_docs', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_legacy_camera_template_is_not_current_patch_scope():
    """The old ROS2 worksheet is provenance, not a current patch role."""
    policy = load_policy()
    relative = 'docs/REAL_CAMERA_READONLY_ACCEPTANCE_TEMPLATE.md'
    assert relative in policy.HISTORICAL_NONAUTHORITATIVE_DOCUMENTS
    assert relative not in policy.SAFE_PATCH_PATHS
    patch = 'diff --git a/{0} b/{0}\n'.format(relative)
    assert 'unexpected patch path: ' + relative in (
        policy.validate_patch_scope(patch))


def test_patch_scope_rejects_actuation_file():
    """An unrelated base launch file must fail the whitelist."""
    policy = load_policy()
    patch = (
        'diff --git a/src/limo_cleanup_bringup/launch/'
        'tracked_base_zero_output.launch.py '
        'b/src/limo_cleanup_bringup/launch/'
        'tracked_base_zero_output.launch.py\n')
    failures = policy.validate_patch_scope(patch)
    assert any('unexpected patch path' in item for item in failures)


def test_readonly_policy_rejects_commands_and_camera_start():
    """Publishing, actuation topics, and camera ownership are forbidden."""
    policy = load_policy()
    failures = policy.validate_readonly_text(
        'ros2 topic pub /cmd_vel X; start_camera:=true')
    assert any('ros2 topic pub' in item for item in failures)
    assert any('actuation topic outside' in item for item in failures)
    assert any('start_camera:=true' in item for item in failures)


def test_readonly_policy_allows_topic_info_for_actuation_audit():
    """Allow read-only inspection of command-topic endpoints."""
    policy = load_policy()
    assert policy.validate_readonly_text(
        'ros2 topic info -v /cmd_vel') == []


def test_current_runbook_is_static_readonly():
    """The repository-owned current runbook must pass the host scanner."""
    docs = load_operator_docs()
    runbook_path = ROOT.joinpath(*Path(docs.AUTHORITY_RUNBOOK).parts)
    text = runbook_path.read_text(encoding='utf-8')
    assert docs.AUTHORITY_RUNBOOK in docs.OPERATIONAL_DOCUMENTS
    assert docs.scan_document_text(docs.AUTHORITY_RUNBOOK, text) == []


def test_rollback_defaults_to_dry_run_and_requires_authorization():
    """Rollback must validate only unless explicitly and exactly authorized."""
    source = (SCRIPTS / 'rollback_perception_release.sh').read_text(
        encoding='utf-8')
    assert "execute=0" in source
    assert 'AUTHORIZE_PERCEPTION_ROLLBACK_20260812' in source
    assert 'ROLLBACK_DRY_RUN_PASS' in source
    assert 'rsync' not in source
    assert 'rm -rf "$workspace"' not in source
    assert '.perception_before_rollback_' in source
    assert 'mv "$target_perception"' in source


def test_static_preflight_help_does_not_touch_ros_graph():
    """Argument parsing must work without ROS, hardware, or graph access."""
    result = subprocess.run(
        ['python3', str(SCRIPTS / 'perception_release_preflight.py'),
         '--help'],
        check=False, capture_output=True, text=True)
    assert result.returncode == 0
    assert '--require-runtime' in result.stdout


def test_real_camera_template_is_demoted_to_ros1_noetic_operations():
    """The retained ROS2 worksheet cannot serve as a current field sheet."""
    docs = load_operator_docs()
    source = (
        ROOT / 'docs/REAL_CAMERA_READONLY_ACCEPTANCE_TEMPLATE.md'
    ).read_text(encoding='utf-8')
    assert source.startswith(docs.LEGACY_CAMERA_TEMPLATE_HEADER[0] + '\n')
    assert 'ROS1/Noetic is the current field authority' in source
    assert 'docs/PERCEPTION_V2_CURRENT_OPERATIONS_INDEX.md' in source
    assert 'NON_AUTHORITATIVE / DO NOT RUN' in source
    assert docs.scan_document_text(docs.LEGACY_CAMERA_TEMPLATE, source) == []
    for value in (
            '/camera/color/image_raw',
            '/camera/depth/image_raw',
            '/camera/color/camera_info',
            '/camera/depth/camera_info',
            'rgbd_contract_rejected',
            'no_actuation_publishers'):
        assert value in source
    for line in source.splitlines():
        stripped = line.strip()
        if any(token in stripped for token in (
                'python3 scripts/generate_perception_source_manifest.py',
                'python3 scripts/perception_release_preflight.py',
                'ros2 run limo_cleanup_perception',
                'ros2 launch limo_cleanup_bringup')):
            assert stripped.startswith(docs.HISTORICAL_PREFIX)

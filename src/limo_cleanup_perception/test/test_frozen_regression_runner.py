"""Offline contracts for the one-command frozen V2 regression harness."""

import importlib.util
import json
import shutil
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from unittest.mock import patch


ROOT = Path(__file__).parents[3]
SCRIPT = ROOT / 'scripts/run_perception_v2_frozen_regression.py'
SPEC = importlib.util.spec_from_file_location(
    'perception_v2_frozen_regression_test_target', SCRIPT)
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)


def _isolated_pytest_marker_result(
        argv, cwd, environment, payload_update=None, marker_count=1,
        exit_code=0):
    assert '--single-file' in argv
    assert argv[1:3] == ['-I', '-B']
    assert 'PYTHONPATH' not in environment
    assert all(
        key.upper() in RUNNER.PYTEST_STYLE_ENVIRONMENT_ALLOWLIST | {
            'PYTHONDONTWRITEBYTECODE', 'PYTHONHASHSEED',
            'PYTHONIOENCODING'}
        for key in environment)
    target = Path(argv[argv.index('--target') + 1]).resolve(strict=True)
    workspace = Path(argv[argv.index('--workspace') + 1]).resolve(strict=True)
    assert workspace == Path(cwd).resolve(strict=True)
    expected_ids = [
        argv[index + 1] for index, value in enumerate(argv[:-1])
        if value == '--expected-id']
    identity = RUNNER._pytest_target_identity(target, workspace)
    payload = {
        'schema_version': RUNNER.PYTEST_FILE_RESULT_SCHEMA_VERSION,
        'runner_kind': RUNNER.PYTEST_FILE_RESULT_RUNNER_KIND,
        'path': identity['path'],
        'size_bytes': identity['size_bytes'],
        'sha256': identity['sha256'],
        'expected_ids': expected_ids,
        'executed_ids': expected_ids,
        'collected': len(expected_ids),
        'passed': len(expected_ids),
        'failed': 0,
        'skipped': 0,
        'exit': exit_code,
        'result': 'PASS' if exit_code == 0 else 'FAIL',
    }
    if payload_update is not None:
        payload_update(payload)
    marker = RUNNER.PYTEST_FILE_RESULT_PREFIX + json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    stdout = '\n'.join(marker for _unused in range(marker_count))
    return {
        'argv': list(argv), 'cwd': str(workspace),
        'exit_code': exit_code, 'timed_out': False,
        'duration_sec': 1.0, 'stdout': stdout + ('\n' if stdout else ''),
        'stderr': '',
    }


def _isolated_unittest_marker_result(
        argv, cwd, environment, payload_update=None, marker_count=1,
        exit_code=0, skipped_ids=()):
    """Build one strict marker for either the Windows or WSL fake child."""
    assert '--workspace' in argv
    assert '--target' in argv
    assert '-I' in argv and '-B' in argv
    assert 'PYTHONPATH' not in environment
    expected_ids = [
        argv[index + 1] for index, value in enumerate(argv[:-1])
        if value == '--expected-id']
    assert expected_ids
    target_relative = expected_ids[0].split('::', 1)[0]
    assert all(
        case_id.split('::', 1)[0] == target_relative
        for case_id in expected_ids)
    target = (ROOT / target_relative).resolve(strict=True)
    identity = RUNNER._pytest_target_identity(target, ROOT)
    discovered_ids = list(RUNNER.static_unittest_case_ids(target, ROOT))
    is_wsl = '--distribution' in argv
    if is_wsl:
        assert argv[argv.index('--distribution') + 1] == RUNNER.WSL_DISTRIBUTION
        assert argv[argv.index('--exec') + 1:argv.index('--exec') + 3] == [
            '/usr/bin/env', '-i']
        executable_entry = argv[argv.index('-I') - 1]
        expected_executable = RUNNER._expected_wsl_executable_identity(
            executable_entry)
        expected_workspace = RUNNER._windows_path_to_wsl(ROOT)
    else:
        assert argv[1:3] == ['-I', '-B']
        expected_executable = RUNNER._expected_host_executable_identity()
        expected_workspace = str(ROOT.resolve(strict=True))
    skipped_ids = list(skipped_ids)
    passed_ids = [
        case_id for case_id in expected_ids if case_id not in skipped_ids]
    resolved_target = (
        str(PurePosixPath(expected_workspace).joinpath(target_relative))
        if is_wsl else str(target))
    target_file_identity = {
        'path': resolved_target,
        'size_bytes': identity['size_bytes'],
        'sha256': identity['sha256'],
        'regular_file': True,
        'is_symlink': False,
    }
    executable = json.loads(json.dumps(expected_executable))
    payload = {
        'schema_version': RUNNER.UNITTEST_FILE_RESULT_SCHEMA_VERSION,
        'runner_kind': RUNNER.UNITTEST_FILE_RESULT_RUNNER_KIND,
        'selection_mode': 'selected_ids',
        'workspace': expected_workspace,
        'import_roots': list(RUNNER.UNITTEST_STYLE_IMPORT_ROOTS),
        'path': identity['path'],
        'resolved_path': resolved_target,
        'size_bytes': identity['size_bytes'],
        'sha256': identity['sha256'],
        'target_identity_before': dict(target_file_identity),
        'target_identity_after': dict(target_file_identity),
        'requested_ids': list(expected_ids),
        'expected_ids': list(expected_ids),
        'executed_ids': list(expected_ids),
        'passed_ids': passed_ids,
        'failed_ids': [],
        'skipped_ids': skipped_ids,
        'discovered_ids': discovered_ids,
        'discovered': len(discovered_ids),
        'collected': len(expected_ids),
        'passed': len(passed_ids),
        'failed': 0,
        'skipped': len(skipped_ids),
        'exit': exit_code,
        'result': 'PASS_WITH_SKIPS' if skipped_ids else 'PASS',
        'failures': [],
        'executable': executable,
        'python': dict(executable),
        'environment': {
            'values': {}, 'watched_keys': [], 'contaminated_keys': [],
            'clean': True, 'cwd': expected_workspace,
            'sys_path_before_import_roots': [], 'meta_path_types': [],
        },
        'environment_unchanged_during_execution': True,
        'environment_restored': True,
        'stdout_marker_count': 1,
    }
    if payload_update is not None:
        payload_update(payload)
    marker = RUNNER.UNITTEST_FILE_RESULT_PREFIX + json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    stdout = '\n'.join(marker for _unused in range(marker_count))
    return {
        'argv': list(argv), 'cwd': str(Path(cwd).resolve()),
        'exit_code': exit_code, 'timed_out': False,
        'duration_sec': 1.0, 'stdout': stdout + ('\n' if stdout else ''),
        'stderr': '',
    }


def test_frozen_inventory_closes_baseline_and_post_fix_inventories():
    result = RUNNER.validate_frozen_inventory(ROOT)
    assert result['failures'] == []
    assert result['actual_static_test_count'] == 141
    assert result['expected_test_count'] == 141
    assert result['ast_passed_files'] == 59
    assert result['expected_ast_files'] == 59
    assert result['post_freeze_ast_passed_files'] == 4
    assert result['actual_ros1_static_test_count'] == 29
    assert result['expected_ros1_test_count'] == 29
    assert result['ros1_ast_passed_files'] == 5
    assert result['expected_ros1_ast_files'] == 5
    assert result['expected_grand_test_count'] == 197
    assert sum(RUNNER.POST_FREEZE_TEST_COUNTS.values()) == 27
    assert RUNNER.EXPECTED_GRAND_TEST_COUNT == 141 + 27 + 29
    assert result['supplemental_test_count'] == 10
    assert result['post_fix_test_count'] == 63
    assert result['expected_post_fix_test_count'] == 63
    assert result['post_fix_perception_ast_passed_files'] == 6
    assert result['post_fix_ros1_ast_passed_files'] == 19
    assert result['current_generation_test_count'] == 144
    assert result['expected_current_generation_test_count'] == 144
    assert RUNNER.EXPECTED_CURRENT_GENERATION_PHYSICAL_TEST_COUNT == 147
    wsl_manifest = result[
        'current_generation_wsl_unittest_target_manifest']
    assert wsl_manifest['validated_pass'] is True
    assert wsl_manifest['failures'] == []
    assert wsl_manifest['expected_target_count'] == 5
    assert wsl_manifest['actual_target_count'] == 5
    assert wsl_manifest['posix_companion_physical_count'] == 3
    assert (
        RUNNER.EXPECTED_CURRENT_GENERATION_PHYSICAL_TEST_COUNT
        == RUNNER.EXPECTED_CURRENT_GENERATION_TEST_COUNT
        + wsl_manifest['posix_companion_physical_count']
        == 144 + 1 + 2)
    assert result['current_generation_perception_ast_passed_files'] == 9
    assert result['current_generation_ros1_ast_passed_files'] == 4
    assert result['total_ros1_ast_files'] == 28
    assert result['total_ros1_ast_passed_files'] == 28
    assert result['supplemental_included_in_grand_total'] is False
    assert result['post_fix_included_in_grand_total'] is False
    assert result['current_generation_included_in_grand_total'] is False
    assert result['current_generation_included_in_post_fix_total'] is False
    assert (sum(count for _, _, count
                in RUNNER.POST_FIX_PYTEST_STYLE_FILES)
            + sum(len(names) for _, _, names
                  in RUNNER.POST_FIX_SELECTED_PYTEST_STYLE_TARGETS)
            + sum(count for _, _, count
                  in RUNNER.POST_FIX_UNITTEST_TARGETS)) == 63
    assert (sum(count for _, _, count
                in RUNNER.CURRENT_GENERATION_PYTEST_STYLE_FILES)
            + sum(len(names) for _, _, names
                  in RUNNER.CURRENT_GENERATION_SELECTED_PYTEST_STYLE_TARGETS)
            + sum(count for _, _, count
                  in RUNNER.CURRENT_GENERATION_UNITTEST_TARGETS)
            + sum(len(names) for _, _, names
                  in RUNNER.CURRENT_GENERATION_SELECTED_UNITTEST_TARGETS)
            + sum(count for _, _, count
                  in RUNNER.CURRENT_GENERATION_ROS1_UNITTEST_TARGETS)
            + RUNNER.EXACT_CLI_TEST_COUNT
            + RUNNER.ROS1_ISOLATED_PROBE_TEST_COUNT
            + RUNNER.ROS1_ISOLATED_PROBE_TEST_COUNT) == 144
    assert sum(count for _, count in RUNNER.UNITTEST_TARGETS) == 108
    assert (sum(count for _, count in RUNNER.PYTEST_STYLE_FILES)
            + sum(len(names) for _, names in RUNNER.PYTEST_STYLE_TARGETS)) == 33

    present_post_freeze = {
        name: ROOT / 'src/limo_cleanup_perception/test' / name
        for name in RUNNER.POST_FREEZE_TEST_FILES}
    plan, plan_failures = RUNNER._build_pytest_execution_plan(
        ROOT, present_post_freeze)
    assert plan_failures == []
    plan_paths = [entry['relative_path'] for entry in plan]
    assert len(plan_paths) == len(set(plan_paths))
    for entry in plan:
        assert tuple(entry['expected_ids']) == RUNNER.static_pytest_case_ids(
            entry['path'], ROOT)
    readiness_entries = [
        entry for entry in plan
        if entry['relative_path'].endswith(
            '/test_perception_readiness_source_contract.py')]
    runtime_entries = [
        entry for entry in plan
        if entry['relative_path'].endswith(
            '/test_ros1_runtime_source_contract.py')]
    assert len(readiness_entries) == 1
    assert len(runtime_entries) == 1
    assert {item['scope'] for item in readiness_entries[0]['allocations']} == {
        'frozen_selected', 'current_generation'}
    assert {item['scope'] for item in runtime_entries[0]['allocations']} == {
        'post_fix', 'current_generation'}
    runtime_ids = set(runtime_entries[0]['expected_ids'])
    runtime_post_fix_ids = {
        case_id
        for allocation in runtime_entries[0]['allocations']
        if allocation['scope'] == 'post_fix'
        for case_id in allocation['expected_ids']}
    runtime_current_ids = {
        case_id
        for allocation in runtime_entries[0]['allocations']
        if allocation['scope'] == 'current_generation'
        for case_id in allocation['expected_ids']}
    assert len(runtime_ids) == 8
    assert len(runtime_post_fix_ids) == 7
    assert len(runtime_current_ids) == 1
    assert runtime_post_fix_ids.isdisjoint(runtime_current_ids)
    assert runtime_post_fix_ids | runtime_current_ids == runtime_ids

    snapshot_paths = {
        item['path'] for item in RUNNER.snapshot_inputs(ROOT)['entries']}
    overlay_root = ROOT / 'ros1_overlay_src/limo_cleanup_ros1_perception'
    overlay_paths = {
        path.relative_to(ROOT).as_posix()
        for path in overlay_root.rglob('*')
        if (path.is_file()
            and not set(path.parts).intersection(
                RUNNER.EXCLUDED_SNAPSHOT_PARTS)
            and path.suffix.lower() not in RUNNER.EXCLUDED_SNAPSHOT_SUFFIXES)
    }
    assert overlay_paths.issubset(snapshot_paths)
    assert set(RUNNER.POST_FIX_PERCEPTION_AST_FILES).issubset(snapshot_paths)
    assert set(RUNNER.POST_FIX_ROS1_AST_FILES).issubset(snapshot_paths)
    assert set(RUNNER.CURRENT_GENERATION_PERCEPTION_AST_FILES).issubset(
        snapshot_paths)
    assert set(RUNNER.CURRENT_GENERATION_ROS1_AST_FILES).issubset(
        snapshot_paths)
    assert 'docs/PERCEPTION_V2_ROS1_NOETIC_FIELD_RUNBOOK.md' in snapshot_paths
    field_json = {
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / 'evidence/perception_v2_field_20260814').rglob(
            '*.json')}
    assert field_json
    assert field_json.issubset(snapshot_paths)
    json_paths = {
        item['path'] for item in RUNNER.validate_json_files(ROOT)['entries']}
    assert field_json.issubset(json_paths)
    assert (
        'ros1_overlay_src/limo_cleanup_ros1_perception/config/'
        'dabai_ros1_raw_rgbd_six_topics_v1.json' in json_paths)
    xml_paths = {
        item['path'] for item in RUNNER.validate_xml_files(ROOT)['entries']}
    assert (
        'ros1_overlay_src/limo_cleanup_ros1_perception/package.xml'
        in xml_paths)
    security = RUNNER.validate_security(ROOT)
    assert security['failures'] == []
    assert security['ros1_offline_tools_checked'] == 1


def test_source_snapshot_detects_added_removed_and_modified_inputs():
    with TemporaryDirectory() as directory:
        root = Path(directory)
        source = root / 'src/limo_cleanup_perception'
        source.mkdir(parents=True)
        first = source / 'first.py'
        first.write_text('value = 1\n', encoding='utf-8')
        before = RUNNER.snapshot_inputs(root)
        first.write_text('value = 2\n', encoding='utf-8')
        second = source / 'second.py'
        second.write_text('value = 3\n', encoding='utf-8')
        after = RUNNER.snapshot_inputs(root)
        drift = RUNNER.compare_snapshots(before, after)
        assert not drift['unchanged']
        assert 'src/limo_cleanup_perception/first.py' in drift['modified']
        assert 'src/limo_cleanup_perception/second.py' in drift['added']
        second.unlink()
        first.unlink()
        removed = RUNNER.snapshot_inputs(root)
        drift = RUNNER.compare_snapshots(after, removed)
        assert 'src/limo_cleanup_perception/first.py' in drift['removed']
        assert 'src/limo_cleanup_perception/second.py' in drift['removed']


def test_full_regression_fails_if_source_changes_during_test_execution():
    with TemporaryDirectory() as directory:
        root = Path(directory) / 'workspace'
        shutil.copytree(ROOT, root, ignore=shutil.ignore_patterns(
            '.git', 'build', 'install', 'log', '__pycache__', '*.pyc'))
        target = (
            root / 'src/limo_cleanup_perception/limo_cleanup_perception'
            / 'task_actions.py')
        calls = []

        def fake_command(argv, cwd, environment):
            calls.append(list(argv))
            if len(calls) == 1:
                target.write_text(
                    target.read_text(encoding='utf-8') + '\n# drift\n',
                    encoding='utf-8')
            if '--single-file' in argv:
                return _isolated_pytest_marker_result(
                    argv, cwd, environment)
            if any('test_ros1_model_binding_contract.py' in item
                   for item in argv):
                output = (
                    'OFFLINE_PYTEST_STYLE collected=18 passed=18 failed=0\n')
            elif any('test_ros1_runtime_source_contract.py' in item
                     for item in argv):
                if any(
                        'test_formal_rosbag1_source_admission_rejects_drift'
                        in item for item in argv):
                    output = (
                        'SELECTED_PYTEST_STYLE collected=1 passed=1 '
                        'failed=0\n')
                else:
                    output = (
                        'SELECTED_PYTEST_STYLE collected=7 passed=7 '
                        'failed=0\n')
            elif any('test_ros1_semantic_readiness.py' in item
                     for item in argv):
                output = (
                    'OFFLINE_PYTEST_STYLE collected=23 passed=23 failed=0\n')
            elif any('test_ros1_formal_rosbag1_admission.py' in item
                     for item in argv):
                output = (
                    'OFFLINE_PYTEST_STYLE collected=16 passed=16 failed=0\n')
            elif any('test_ros1_source_integrity_trust_root' in item
                     for item in argv):
                output = 'Ran 15 tests in 1.0s\n\nOK\n'
            elif any('test_ros1_field_install_gate' in item
                     for item in argv):
                output = 'Ran 10 tests in 1.0s\n\nOK\n'
            elif any('test_perception_field_intake' in item for item in argv):
                output = 'Ran 10 tests in 1.0s\n\nOK\n'
            elif any('test_rosbag1_rgbd_indexer.py' in item for item in argv):
                output = 'Ran 27 tests in 1.0s\n\nOK\n'
            elif any('test_diagnostic_evidence_lineage' in item
                     for item in argv):
                output = 'Ran 9 tests in 1.0s\n\nOK\n'
            elif 'unittest' in argv:
                output = 'Ran 108 tests in 1.0s\n\nOK\n'
            elif '--internal-selected-pytest-style' in argv:
                output = (
                    'SELECTED_PYTEST_STYLE collected=6 passed=6 failed=0\n')
            elif (argv and Path(argv[0]).name.lower() in ('git', 'git.exe')):
                assert not any(
                    key.upper().startswith('GIT_') for key in environment)
                if 'rev-parse' in argv:
                    output = str(root.resolve()) + '\n'
                else:
                    output = ''
            elif any('test_frozen_regression_runner.py' in item
                     for item in argv):
                output = (
                    'OFFLINE_PYTEST_STYLE collected=17 passed=17 failed=0\n')
            else:
                output = (
                    'OFFLINE_PYTEST_STYLE collected=27 passed=27 failed=0\n')
            return {
                'argv': list(argv), 'cwd': str(Path(cwd).resolve()),
                'exit_code': 0, 'timed_out': False,
                'duration_sec': 1.0, 'stdout': output, 'stderr': '',
            }

        report = RUNNER.run_regression(
            root, root / 'install', command_runner=fake_command)
        assert report['regression_passed'] is False
        assert 'source_changed_during_regression' in report['failures']
        assert (
            'src/limo_cleanup_perception/limo_cleanup_perception/'
            'task_actions.py' in report['source_drift']['modified'])
        git_calls = [
            argv for argv in calls
            if argv and Path(argv[0]).name.lower() in ('git', 'git.exe')]
        assert len(git_calls) == 2
        assert all(Path(argv[0]).is_absolute() for argv in git_calls)
        expected_prefix = [
            git_calls[0][0], '-c', 'safe.directory=', '-c',
            'safe.directory={}'.format(root.resolve()),
            '-C', str(root.resolve())]
        assert git_calls[0] == expected_prefix + [
            'rev-parse', '--show-toplevel']
        assert git_calls[1] == expected_prefix + ['diff', '--check']
        assert report['diff_check']['resolved_executable']['path'] == (
            git_calls[0][0])
        assert report['diff_check']['repository_probe_command']['cwd'] == (
            str(root.resolve()))
        assert report['diff_check']['repository_toplevel'] == str(root.resolve())
        assert report['diff_check'][
            'repository_toplevel_matches_workspace'] is True
        assert report['diff_check']['command']['cwd'] == str(root.resolve())
        assert report['diff_check']['safe_environment_git_keys'] == []
        assert all(
            'value' not in item
            for item in report['diff_check'][
                'inherited_git_environment']['entries'])
        pytest_calls = [argv for argv in calls if '--single-file' in argv]
        pytest_targets = [
            str(Path(argv[argv.index('--target') + 1]).resolve())
            for argv in pytest_calls]
        assert pytest_calls
        assert len(pytest_targets) == len(set(pytest_targets))
        assert all(argv[1:3] == ['-I', '-B'] for argv in pytest_calls)
        assert report['test_matrix'][
            'pytest_style_file_inventory']['ordered_paths'] == [
                item['path'] for item in report['test_matrix'][
                    'pytest_style_file_records']]


def test_installed_copy_check_rejects_missing_and_stale_artifacts():
    with TemporaryDirectory() as directory:
        root = Path(directory)
        source = root / 'source.py'
        installed = root / 'installed.py'
        source.write_bytes(b'current')
        record = []
        failures = []
        RUNNER._check_copy(
            source, installed, 'missing', record, failures)
        assert failures == ['installed_artifact_missing:missing']
        installed.write_bytes(b'stale')
        failures = []
        RUNNER._check_copy(
            source, installed, 'stale', record, failures)
        assert failures == ['installed_artifact_stale:stale']
        installed.write_bytes(b'current')
        failures = []
        RUNNER._check_copy(
            source, installed, 'current', record, failures)
        assert failures == []
        assert record[-1]['matches'] is True


def test_report_path_is_exclusive_and_offline_pass_never_grants_delivery():
    with TemporaryDirectory() as directory:
        path = Path(directory) / 'report.json'
        report = RUNNER._base_report(ROOT, ROOT / 'install')
        report['regression_passed'] = True
        with path.open('x', encoding='utf-8') as stream:
            RUNNER._write_reserved_report(stream, report)
        original = path.read_bytes()
        try:
            path.open('x', encoding='utf-8')
        except FileExistsError:
            pass
        else:
            raise AssertionError('existing report was opened for overwrite')
        assert path.read_bytes() == original
        payload = json.loads(path.read_text(encoding='utf-8'))
        assert payload['read_only'] is True
        assert payload['authorizes_motion'] is False
        assert payload['publishes_ros_messages'] is False
        assert payload['ros_graph_started'] is False
        assert payload['camera_opened'] is False
        assert payload['delivery_ready'] is False

    def authority_payload():
        return {
            'schema_version': RUNNER.EVIDENCE_AUTHORITY_SCHEMA_VERSION,
            'index_id': RUNNER.EVIDENCE_AUTHORITY_INDEX_ID,
            'index_kind': RUNNER.EVIDENCE_AUTHORITY_INDEX_KIND,
            'evidence_lineage': RUNNER.EVIDENCE_AUTHORITY_LINEAGE,
            'immutable': True,
            'current_evidence_id': RUNNER.EVIDENCE_AUTHORITY_CURRENT_ID,
            'selection_policy': {
                'exactly_one_current': True,
                'accept_only_index_selected_current': True,
                'filename_mtime_selection_forbidden': True,
                'current_required_status': (
                    RUNNER.EVIDENCE_AUTHORITY_CURRENT_STATUS),
                'current_required_scope': (
                    RUNNER.EVIDENCE_AUTHORITY_CURRENT_SCOPE),
                'authorizes_field_delivery': False,
            },
            'entries': [
                dict(item)
                for item in RUNNER.EXPECTED_EVIDENCE_AUTHORITY_ENTRIES
            ],
        }

    def cloned(value):
        return json.loads(json.dumps(value))

    def assert_rejected(value, *expected_failures):
        result = RUNNER.validate_evidence_authority_index(ROOT, value)
        assert result['validated_pass'] is False
        assert result['current_evidence'] is None
        assert result['current_identity'] is None
        for expected in expected_failures:
            assert expected in result['failures']
        return result

    authority = authority_payload()
    selected = RUNNER.validate_evidence_authority_index(ROOT, authority)
    assert selected['validated_pass'] is True
    assert selected['failures'] == []
    assert {
        item['evidence_id']: item['status']
        for item in authority['entries']
    } == {
        'ros1_canonical_source_binding_v6': 'STALE_FAILED_REGRESSION',
        'ros1_canonical_source_binding_v6_final': (
            'NON_CURRENT_SUPERSEDED_INTERMEDIATE'),
        'ros1_canonical_source_binding_v7': (
            'CURRENT_BLOCKED_OFFLINE_BASELINE'),
    }
    assert [
        item['evidence_id'] for item in authority['entries']
        if item['is_current'] is True
    ] == ['ros1_canonical_source_binding_v7']
    assert selected['current_evidence']['evidence_id'] == (
        'ros1_canonical_source_binding_v7')
    assert selected['current_evidence']['status'] == (
        'CURRENT_BLOCKED_OFFLINE_BASELINE')
    assert selected['current_evidence']['scope'] == (
        'offline_regression_only_not_field_3d_tf_build_or_runtime')
    assert selected['current_evidence']['delivery_ready'] is False
    assert selected['current_evidence']['authorizes_field_delivery'] is False
    assert selected['current_identity']['path'].endswith(
        'frozen_offline_regression_20260814_'
        'ros1_canonical_source_binding_v7.json')
    assert selected['authorizes_field_delivery'] is False
    assert selected['delivery_ready'] is False

    resolved = RUNNER.load_and_resolve_evidence_authority_index(ROOT)
    assert resolved['validated_pass'] is True
    assert resolved['failures'] == []
    assert resolved['current_evidence']['evidence_id'] == (
        RUNNER.EVIDENCE_AUTHORITY_CURRENT_ID)
    assert resolved['current_identity']['size_bytes'] == 190747
    assert resolved['current_identity']['sha256'] == (
        'dac31ed678ff7c3a8f4494c5b865f89a41715ee5555e80ef12a8ba4b895f6789')
    assert resolved['index_relative_path'] == (
        RUNNER.EVIDENCE_AUTHORITY_INDEX_RELATIVE)
    assert resolved['accept_only_index_selected_current'] is True
    assert resolved['filename_mtime_selection_forbidden'] is True

    with TemporaryDirectory() as directory:
        exclusive_path = Path(directory) / 'authority.json'
        identity = RUNNER.write_evidence_authority_index_exclusive(
            exclusive_path, authority)
        original = exclusive_path.read_bytes()
        assert identity['size_bytes'] == len(original)
        assert identity['sha256'] == RUNNER.sha256_file(exclusive_path)
        try:
            RUNNER.write_evidence_authority_index_exclusive(
                exclusive_path, authority)
        except FileExistsError:
            pass
        else:
            raise AssertionError('authority index overwrite was permitted')
        assert exclusive_path.read_bytes() == original

    with patch.object(
            RUNNER, '_authority_path_linklike_parts',
            side_effect=lambda _workspace, path: (
                ['mock-index-link'] if str(path).endswith(
                    'perception_v2_evidence_authority_index_20260814_v1.json')
                else [])):
        linked_index = RUNNER.load_and_resolve_evidence_authority_index(ROOT)
    assert linked_index['validated_pass'] is False
    assert linked_index['current_evidence'] is None
    assert 'evidence_authority_index_link_forbidden' in (
        linked_index['failures'])

    for missing in (
            'lifecycle', 'status', 'is_current', 'current_baseline'):
        mutated = cloned(authority)
        del mutated['entries'][0][missing]
        assert_rejected(
            mutated, 'evidence_authority_status_or_lifecycle_missing')

    no_current = cloned(authority)
    no_current['entries'][2]['is_current'] = False
    no_current['entries'][2]['current_baseline'] = False
    assert_rejected(
        no_current,
        'evidence_authority_current_count_invalid',
        'evidence_authority_current_baseline_count_invalid',
        'evidence_authority_current_id_mismatch')

    two_current = cloned(authority)
    two_current['entries'][0]['is_current'] = True
    two_current['entries'][0]['current_baseline'] = True
    assert_rejected(
        two_current,
        'evidence_authority_current_count_invalid',
        'evidence_authority_current_baseline_count_invalid',
        'evidence_authority_current_id_mismatch')

    split_current = cloned(authority)
    split_current['entries'][0]['current_baseline'] = True
    split_current['entries'][2]['current_baseline'] = False
    assert_rejected(
        split_current, 'evidence_authority_current_marker_mismatch')

    wrong_size = cloned(authority)
    wrong_size['entries'][2]['size_bytes'] += 1
    assert_rejected(
        wrong_size,
        'evidence_authority_entry_binding_mismatch:'
        'ros1_canonical_source_binding_v7:size_bytes',
        'evidence_authority_artifact_size_mismatch:'
        'ros1_canonical_source_binding_v7')

    wrong_hash = cloned(authority)
    wrong_hash['entries'][2]['sha256'] = '0' * 64
    assert_rejected(
        wrong_hash,
        'evidence_authority_entry_binding_mismatch:'
        'ros1_canonical_source_binding_v7:sha256',
        'evidence_authority_artifact_sha256_mismatch:'
        'ros1_canonical_source_binding_v7')

    duplicate_id = cloned(authority)
    duplicate_id['entries'][0]['evidence_id'] = (
        duplicate_id['entries'][1]['evidence_id'])
    assert_rejected(
        duplicate_id,
        'evidence_authority_duplicate_evidence_id',
        'evidence_authority_entry_set_mismatch')

    duplicate_path = cloned(authority)
    duplicate_path['entries'][0]['path'] = duplicate_path['entries'][1]['path']
    assert_rejected(
        duplicate_path,
        'evidence_authority_duplicate_path',
        'evidence_authority_entry_binding_mismatch:'
        'ros1_canonical_source_binding_v6:path')

    extra_entry = cloned(authority)
    extra_entry['entries'].append(dict(extra_entry['entries'][0]))
    extra_entry['entries'][-1]['evidence_id'] = 'foreign_offline_evidence'
    assert_rejected(
        extra_entry,
        'evidence_authority_entry_count_mismatch',
        'evidence_authority_entry_set_mismatch')

    wrong_current_id = cloned(authority)
    wrong_current_id['current_evidence_id'] = (
        'ros1_canonical_source_binding_v6_final')
    assert_rejected(
        wrong_current_id,
        'evidence_authority_top_level_mismatch:current_evidence_id',
        'evidence_authority_current_id_mismatch')

    for truthy in (1, 'true'):
        truthy_top = cloned(authority)
        truthy_top['immutable'] = truthy
        assert_rejected(
            truthy_top, 'evidence_authority_top_level_mismatch:immutable')
        truthy_marker = cloned(authority)
        truthy_marker['entries'][2]['is_current'] = truthy
        assert_rejected(
            truthy_marker,
            'evidence_authority_entry_binding_mismatch:'
            'ros1_canonical_source_binding_v7:is_current',
            'evidence_authority_current_count_invalid')

    for escaping_path in (
            '../frozen_offline_regression_20260814_'
            'ros1_canonical_source_binding_v7.json',
            str((ROOT / 'evidence/perception_v2_offline_20260813/'
                 'frozen_offline_regression_20260814_'
                 'ros1_canonical_source_binding_v7.json').resolve())):
        escaped = cloned(authority)
        escaped['entries'][2]['path'] = escaping_path
        assert_rejected(
            escaped,
            'evidence_authority_artifact_path_escape:'
            'ros1_canonical_source_binding_v7')

    with patch.object(
            RUNNER, '_authority_path_linklike_parts',
            side_effect=lambda _workspace, path: (
                ['mock-link'] if str(path).endswith(
                    'ros1_canonical_source_binding_v7.json') else [])):
        assert_rejected(
            authority,
            'evidence_authority_artifact_link_forbidden:'
            'ros1_canonical_source_binding_v7')

    with patch.object(
            RUNNER, 'EVIDENCE_AUTHORITY_INDEX_EXPECTED_SIZE_BYTES',
            RUNNER.EVIDENCE_AUTHORITY_INDEX_EXPECTED_SIZE_BYTES + 1):
        stale_index_size = (
            RUNNER.load_and_resolve_evidence_authority_index(ROOT))
    assert stale_index_size['validated_pass'] is False
    assert stale_index_size['current_evidence'] is None
    assert 'evidence_authority_index_size_mismatch' in (
        stale_index_size['failures'])

    with patch.object(
            RUNNER, 'EVIDENCE_AUTHORITY_INDEX_EXPECTED_SHA256', '0' * 64):
        stale_index_hash = (
            RUNNER.load_and_resolve_evidence_authority_index(ROOT))
    assert stale_index_hash['validated_pass'] is False
    assert stale_index_hash['current_evidence'] is None
    assert 'evidence_authority_index_sha256_mismatch' in (
        stale_index_hash['failures'])

    evidence_relative = Path(
        'evidence/perception_v2_offline_20260813')
    with TemporaryDirectory() as directory:
        root = Path(directory)
        evidence_root = root / evidence_relative
        evidence_root.mkdir(parents=True)
        for entry in RUNNER.EXPECTED_EVIDENCE_AUTHORITY_ENTRIES:
            source = ROOT / entry['path']
            target = root / entry['path']
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

        current_path = root / authority['entries'][2]['path']
        current_payload = json.loads(current_path.read_text(encoding='utf-8'))
        current_payload['delivery_ready'] = True
        current_payload['regression_passed'] = True
        current_payload['delivery_gate_summary']['delivery_ready'] = True
        current_payload['delivery_gate_summary'][
            'formal_field_evidence_gate']['validated_pass'] = True
        current_path.write_text(
            json.dumps(current_payload, ensure_ascii=False, sort_keys=True),
            encoding='utf-8')
        semantically_false = RUNNER.validate_evidence_authority_index(
            root, authority)
        assert semantically_false['validated_pass'] is False
        assert semantically_false['current_evidence'] is None
        assert (
            'evidence_authority_artifact_delivery_claim:'
            'ros1_canonical_source_binding_v7'
            in semantically_false['failures'])
        assert (
            'evidence_authority_artifact_regression_state_invalid:'
            'ros1_canonical_source_binding_v7'
            in semantically_false['failures'])
        assert (
            'evidence_authority_current_scope_not_blocked:'
            'ros1_canonical_source_binding_v7'
            in semantically_false['failures'])
        assert (
            'evidence_authority_artifact_sha256_mismatch:'
            'ros1_canonical_source_binding_v7'
            in semantically_false['failures'])

        strict_index = root / RUNNER.EVIDENCE_AUTHORITY_INDEX_RELATIVE
        duplicate_key_json = json.dumps(
            authority, ensure_ascii=False, sort_keys=True)
        duplicate_key_json = duplicate_key_json.replace(
            '{', '{"schema_version":"duplicate",', 1)
        strict_index.write_text(duplicate_key_json, encoding='utf-8')
        with patch.object(
                RUNNER, 'EVIDENCE_AUTHORITY_INDEX_EXPECTED_SIZE_BYTES',
                strict_index.stat().st_size), patch.object(
                    RUNNER, 'EVIDENCE_AUTHORITY_INDEX_EXPECTED_SHA256',
                    RUNNER.sha256_file(strict_index)):
            duplicate_key = RUNNER.load_and_resolve_evidence_authority_index(
                root)
        assert duplicate_key['validated_pass'] is False
        assert duplicate_key['current_evidence'] is None
        assert 'evidence_authority_index_invalid_json' in (
            duplicate_key['failures'])

        non_finite_json = json.dumps(
            authority, ensure_ascii=False, sort_keys=True).replace(
                '"immutable": true', '"immutable": NaN', 1)
        strict_index.write_text(non_finite_json, encoding='utf-8')
        with patch.object(
                RUNNER, 'EVIDENCE_AUTHORITY_INDEX_EXPECTED_SIZE_BYTES',
                strict_index.stat().st_size), patch.object(
                    RUNNER, 'EVIDENCE_AUTHORITY_INDEX_EXPECTED_SHA256',
                    RUNNER.sha256_file(strict_index)):
            non_finite = RUNNER.load_and_resolve_evidence_authority_index(root)
        assert non_finite['validated_pass'] is False
        assert non_finite['current_evidence'] is None
        assert 'evidence_authority_index_invalid_json' in (
            non_finite['failures'])


def test_command_result_gate_rejects_wrong_test_denominator():
    calls = []

    def fake_command(argv, cwd, environment):
        calls.append(list(argv))
        if '--single-file' in argv:
            target = Path(argv[argv.index('--target') + 1])
            update = None
            if target.name == 'test_ros1_model_binding_contract.py':
                def update(payload):
                    payload['executed_ids'] = payload['executed_ids'][:-1]
                    payload['collected'] -= 1
                    payload['passed'] -= 1
            return _isolated_pytest_marker_result(
                argv, cwd, environment, payload_update=update)
        if any(
                str(item).replace('\\', '/').endswith(
                    '/' + Path(RUNNER.UNITTEST_STYLE_HELPER_RELATIVE).name)
                for item in argv):
            expected_ids = [
                argv[index + 1] for index, value in enumerate(argv[:-1])
                if value == '--expected-id']
            skipped_ids = ()
            if '--distribution' not in argv:
                if expected_ids and expected_ids[0].startswith(
                        RUNNER.EXACT_CLI_TEST_RELATIVE + '::'):
                    skipped_ids = (RUNNER.EXACT_CLI_POSIX_CASE_ID,)
                elif expected_ids and expected_ids[0].startswith(
                        RUNNER.HOST_READINESS_TEST_RELATIVE + '::'):
                    skipped_ids = RUNNER.HOST_READINESS_POSIX_CASE_IDS
            return _isolated_unittest_marker_result(
                argv, cwd, environment, skipped_ids=skipped_ids)
        if any('test_ros1_model_binding_contract.py' in item for item in argv):
            output = (
                'OFFLINE_PYTEST_STYLE collected=17 passed=17 failed=0\n')
        elif any('test_ros1_runtime_source_contract.py' in item
                 for item in argv):
            if any(
                    'test_formal_rosbag1_source_admission_rejects_drift'
                    in item for item in argv):
                output = (
                    'SELECTED_PYTEST_STYLE collected=1 passed=1 failed=0\n')
            else:
                output = (
                    'SELECTED_PYTEST_STYLE collected=7 passed=7 failed=0\n')
        elif any('test_ros1_semantic_readiness.py' in item for item in argv):
            output = (
                'OFFLINE_PYTEST_STYLE collected=17 passed=17 failed=0\n')
        elif any('test_ros1_formal_rosbag1_admission.py' in item
                 for item in argv):
            output = (
                'OFFLINE_PYTEST_STYLE collected=15 passed=15 failed=0\n')
        elif any('test_ros1_source_integrity_trust_root' in item
                 for item in argv):
            output = 'Ran 15 tests in 1.0s\n\nOK\n'
        elif any('test_ros1_field_install_gate' in item for item in argv):
            selected = sum(
                'Ros1FieldInstallGateTest.test_' in item for item in argv)
            output = 'Ran {} tests in 1.0s\n\nOK\n'.format(selected)
        elif any('test_ros1_runtime_behavior' in item for item in argv):
            output = 'Ran 10 tests in 1.0s\n\nOK\n'
        elif any('test_ros1_runtime_implementation_admission' in item
                 for item in argv):
            output = 'Ran 20 tests in 1.0s\n\nOK\n'
        elif any('test_ros1_adapter_pure_fake.py' in item for item in argv):
            output = 'Ran 2 tests in 1.0s\n\nOK\n'
        elif any('test_runtime_install_contract.py' in item for item in argv):
            output = 'Ran 6 tests in 1.0s\n\nOK\n'
        elif any('test_perception_readiness_source_contract.py' in item
                 for item in argv):
            output = (
                'SELECTED_PYTEST_STYLE collected=1 passed=1 failed=0\n')
        elif any('test_perception_field_intake' in item for item in argv):
            output = 'Ran 10 tests in 1.0s\n\nOK\n'
        elif any('test_rosbag1_rgbd_indexer.py' in item for item in argv):
            output = 'Ran 25 tests in 1.0s\n\nOK\n'
        elif any('test_diagnostic_evidence_lineage' in item for item in argv):
            output = 'Ran 9 tests in 1.0s\n\nOK\n'
        elif 'unittest' in argv:
            output = 'Ran 107 tests in 1.0s\n\nOK\n'
        elif '--internal-selected-pytest-style' in argv:
            output = (
                'SELECTED_PYTEST_STYLE collected=6 passed=6 failed=0\n')
        elif any('test_frozen_regression_runner.py' in item for item in argv):
            output = (
                'OFFLINE_PYTEST_STYLE collected=17 passed=17 failed=0\n')
        else:
            output = (
                'OFFLINE_PYTEST_STYLE collected=27 passed=27 failed=0\n')
        return {
            'argv': list(argv), 'cwd': str(Path(cwd).resolve()),
            'exit_code': 0, 'timed_out': False,
            'duration_sec': 1.0, 'stdout': output, 'stderr': '',
        }

    fake_launcher = SCRIPT.resolve(strict=True)
    with patch.object(
            RUNNER, '_resolve_wsl_launcher', return_value=(
                fake_launcher, RUNNER._identity(fake_launcher))):
        result = RUNNER.run_test_commands(ROOT, command_runner=fake_command)
    assert 'frozen_unittest_failed_or_count_mismatch' in result['failures']
    assert 'frozen_executed_test_total_mismatch' in result['failures']
    assert 'ros1_unittest_failed_or_count_mismatch' in result['failures']
    assert 'ros_independent_grand_total_mismatch' in result['failures']
    assert ('post_fix_suite_failed_or_count_mismatch:'
            'ros1_model_binding_contract') in result['failures']
    assert 'post_fix_executed_total_mismatch' in result['failures']
    assert result['grand_total_passed'] == 0
    assert result['post_fix_passed'] == 45
    assert result['post_fix_failed'] == 18
    assert result['current_generation_passed'] == 144
    assert result['current_generation_failed'] == 0
    assert result['current_generation_physical_collected'] == 147
    assert result['current_generation_physical_passed'] == 144
    assert result['current_generation_physical_failed'] == 0
    assert result['current_generation_physical_skipped'] == 3
    assert len(calls) >= 7
    assert all(
        Path(item).name.lower() not in ('ros2', 'ros2.exe')
        for argv in calls for item in argv)

    test_root = ROOT / 'src/limo_cleanup_perception/test'
    first_path = test_root / 'test_task_actions.py'
    second_path = test_root / 'test_rgbd_contract.py'
    first_ids = RUNNER.static_pytest_case_ids(first_path, ROOT)
    second_ids = RUNNER.static_pytest_case_ids(second_path, ROOT)
    isolated_environment = RUNNER._pytest_style_environment({})

    def marker_argv(path, case_ids):
        argv = [
            RUNNER.sys.executable, '-I', '-B',
            str(ROOT / RUNNER.PYTEST_STYLE_HELPER_RELATIVE),
            '--single-file', '--workspace', str(ROOT),
            '--target', str(path),
        ]
        for import_root in RUNNER.PYTEST_STYLE_IMPORT_ROOTS:
            argv.extend(('--import-root', import_root))
        for case_id in case_ids:
            argv.extend(('--expected-id', case_id))
        return argv

    first_argv = marker_argv(first_path, first_ids)
    first_identity = RUNNER._pytest_target_identity(first_path, ROOT)
    good_first = RUNNER.validate_pytest_file_result(
        ROOT, first_path, first_ids,
        _isolated_pytest_marker_result(
            first_argv, ROOT, isolated_environment),
        pre_identity=first_identity)
    assert good_first['validated_pass'] is True

    missing_marker_command = dict(
        _isolated_pytest_marker_result(
            first_argv, ROOT, isolated_environment))
    missing_marker_command['stdout'] = ''
    missing_marker = RUNNER.validate_pytest_file_result(
        ROOT, first_path, first_ids, missing_marker_command,
        pre_identity=first_identity)
    assert 'pytest_file_result_marker_missing' in missing_marker['failures']

    duplicate_marker = RUNNER.validate_pytest_file_result(
        ROOT, first_path, first_ids,
        _isolated_pytest_marker_result(
            first_argv, ROOT, isolated_environment, marker_count=2),
        pre_identity=first_identity)
    assert 'pytest_file_result_marker_count_mismatch' in (
        duplicate_marker['failures'])

    def replace_path_and_hash(payload):
        payload['path'] = 'src/replaced/test_task_actions.py'
        payload['sha256'] = '0' * 64

    replaced_identity = RUNNER.validate_pytest_file_result(
        ROOT, first_path, first_ids,
        _isolated_pytest_marker_result(
            first_argv, ROOT, isolated_environment,
            payload_update=replace_path_and_hash),
        pre_identity=first_identity)
    assert 'pytest_file_result_path_mismatch' in replaced_identity['failures']
    assert 'pytest_file_result_hash_mismatch' in replaced_identity['failures']

    def no_import_or_execution(payload):
        payload['executed_ids'] = []
        payload['collected'] = 0
        payload['passed'] = 0
        payload['result'] = 'FAIL'

    not_executed = RUNNER.validate_pytest_file_result(
        ROOT, first_path, first_ids,
        _isolated_pytest_marker_result(
            first_argv, ROOT, isolated_environment,
            payload_update=no_import_or_execution),
        pre_identity=first_identity)
    assert 'pytest_file_result_executed_ids_mismatch' in (
        not_executed['failures'])
    assert 'pytest_file_result_zero_denominator' in not_executed['failures']

    empty_ids = ()
    zero_case = RUNNER.validate_pytest_file_result(
        ROOT, first_path, empty_ids,
        _isolated_pytest_marker_result(
            marker_argv(first_path, empty_ids), ROOT, isolated_environment),
        pre_identity=first_identity)
    assert 'pytest_file_expected_ids_invalid' in zero_case['failures']
    assert 'pytest_file_result_zero_denominator' in zero_case['failures']

    def omit_first_repeat_second(payload):
        payload['executed_ids'] = [first_ids[1]] * len(first_ids)

    equal_total_substitution = RUNNER.validate_pytest_file_result(
        ROOT, first_path, first_ids,
        _isolated_pytest_marker_result(
            first_argv, ROOT, isolated_environment,
            payload_update=omit_first_repeat_second),
        pre_identity=first_identity)
    assert equal_total_substitution['collected'] == len(first_ids)
    assert 'pytest_file_result_executed_ids_mismatch' in (
        equal_total_substitution['failures'])

    second_identity = RUNNER._pytest_target_identity(second_path, ROOT)
    good_second = RUNNER.validate_pytest_file_result(
        ROOT, second_path, second_ids,
        _isolated_pytest_marker_result(
            marker_argv(second_path, second_ids), ROOT,
            isolated_environment),
        pre_identity=second_identity)
    substituted_inventory = RUNNER.validate_pytest_file_record_inventory(
        [good_second, good_second],
        [good_first['path'], good_second['path']])
    assert 'pytest_file_record_order_or_path_mismatch' in (
        substituted_inventory)
    assert 'pytest_file_record_duplicate_path' in substituted_inventory
    assert 'pytest_file_record_duplicate_hash' in substituted_inventory

    # The successor runner's unittest evidence is strict per file and per
    # interpreter.  Exercise the marker gate directly so a fake command cannot
    # preserve totals while omitting IDs or substituting source/executable
    # identities.
    unittest_environment = RUNNER._pytest_style_environment({})
    unittest_helper_identity = RUNNER._pytest_target_identity(
        ROOT / RUNNER.UNITTEST_STYLE_HELPER_RELATIVE, ROOT)
    exact_path = ROOT / RUNNER.EXACT_CLI_TEST_RELATIVE
    exact_ids = RUNNER.static_unittest_case_ids(exact_path, ROOT)
    expected_wsl_targets = list(
        RUNNER._expected_current_generation_wsl_unittest_targets())
    manifest_pass = (
        RUNNER.validate_current_generation_wsl_unittest_target_manifest())
    assert manifest_pass['validated_pass'] is True
    assert manifest_pass['failures'] == []

    extra_wsl_targets = tuple(expected_wsl_targets + [(
        'unallocated_wsl_record', RUNNER.EXACT_CLI_TEST_RELATIVE,
        '/usr/bin/python3', (RUNNER.EXACT_CLI_POSIX_CASE_ID,))])
    extra_manifest = (
        RUNNER.validate_current_generation_wsl_unittest_target_manifest(
            extra_wsl_targets))
    assert extra_manifest['validated_pass'] is False
    assert 'wsl_unittest_target_manifest_mismatch' in extra_manifest['failures']
    assert 'wsl_unittest_unallocated_record' in extra_manifest['failures']

    reordered_wsl_targets = list(expected_wsl_targets)
    reordered_wsl_targets[0], reordered_wsl_targets[1] = (
        reordered_wsl_targets[1], reordered_wsl_targets[0])
    reordered_manifest = (
        RUNNER.validate_current_generation_wsl_unittest_target_manifest(
            tuple(reordered_wsl_targets)))
    assert reordered_manifest['failures'] == [
        'wsl_unittest_target_manifest_mismatch']

    wrong_id_wsl_targets = list(expected_wsl_targets)
    wrong_id_wsl_targets[0] = (
        'wrong_record_id', *wrong_id_wsl_targets[0][1:])
    wrong_id_manifest = (
        RUNNER.validate_current_generation_wsl_unittest_target_manifest(
            tuple(wrong_id_wsl_targets)))
    assert 'wsl_unittest_target_manifest_mismatch' in (
        wrong_id_manifest['failures'])
    assert 'wsl_unittest_unallocated_record' in wrong_id_manifest['failures']

    duplicate_wsl_targets = list(expected_wsl_targets)
    duplicate_wsl_targets[1] = duplicate_wsl_targets[0]
    duplicate_manifest = (
        RUNNER.validate_current_generation_wsl_unittest_target_manifest(
            tuple(duplicate_wsl_targets)))
    assert duplicate_manifest['failures'] == [
        'wsl_unittest_target_manifest_mismatch']

    def unittest_argv(path, case_ids):
        argv = [
            RUNNER.sys.executable, '-I', '-B',
            str(ROOT / RUNNER.UNITTEST_STYLE_HELPER_RELATIVE),
            '--workspace', str(ROOT), '--target', str(path),
        ]
        for import_root in RUNNER.UNITTEST_STYLE_IMPORT_ROOTS:
            argv.extend(('--import-root', import_root))
        for case_id in case_ids:
            argv.extend(('--expected-id', case_id))
        return argv

    exact_argv = unittest_argv(exact_path, exact_ids)
    exact_identity = RUNNER._pytest_target_identity(exact_path, ROOT)
    exact_windows = RUNNER.validate_unittest_file_result(
        ROOT, exact_path, exact_ids,
        _isolated_unittest_marker_result(
            exact_argv, ROOT, unittest_environment,
            skipped_ids=(RUNNER.EXACT_CLI_POSIX_CASE_ID,)),
        pre_identity=exact_identity,
        expected_executable=RUNNER._expected_host_executable_identity(),
        expected_workspace=str(ROOT.resolve(strict=True)),
        allowed_skipped_ids=(RUNNER.EXACT_CLI_POSIX_CASE_ID,),
        record_id='windows:' + RUNNER.EXACT_CLI_TEST_RELATIVE,
        platform='windows')
    exact_windows['helper_identity'] = unittest_helper_identity
    assert exact_windows['validated_pass'] is True

    missing_unittest_marker_result = _isolated_unittest_marker_result(
        exact_argv, ROOT, unittest_environment,
        skipped_ids=(RUNNER.EXACT_CLI_POSIX_CASE_ID,))
    missing_unittest_marker_result['stdout'] = ''
    missing_unittest_marker = RUNNER.validate_unittest_file_result(
        ROOT, exact_path, exact_ids, missing_unittest_marker_result,
        pre_identity=exact_identity,
        allowed_skipped_ids=(RUNNER.EXACT_CLI_POSIX_CASE_ID,))
    assert 'unittest_file_result_marker_count_or_stream_mismatch' in (
        missing_unittest_marker['failures'])

    duplicate_unittest_marker = RUNNER.validate_unittest_file_result(
        ROOT, exact_path, exact_ids,
        _isolated_unittest_marker_result(
            exact_argv, ROOT, unittest_environment, marker_count=2,
            skipped_ids=(RUNNER.EXACT_CLI_POSIX_CASE_ID,)),
        pre_identity=exact_identity,
        allowed_skipped_ids=(RUNNER.EXACT_CLI_POSIX_CASE_ID,))
    assert 'unittest_file_result_marker_count_or_stream_mismatch' in (
        duplicate_unittest_marker['failures'])

    def omit_unittest_id(payload):
        payload['executed_ids'] = payload['executed_ids'][:-1]
        payload['collected'] -= 1

    omitted_unittest_id = RUNNER.validate_unittest_file_result(
        ROOT, exact_path, exact_ids,
        _isolated_unittest_marker_result(
            exact_argv, ROOT, unittest_environment,
            payload_update=omit_unittest_id,
            skipped_ids=(RUNNER.EXACT_CLI_POSIX_CASE_ID,)),
        pre_identity=exact_identity,
        allowed_skipped_ids=(RUNNER.EXACT_CLI_POSIX_CASE_ID,))
    assert 'unittest_file_result_executed_ids_mismatch' in (
        omitted_unittest_id['failures'])
    assert 'unittest_file_result_count_invariant_failed' in (
        omitted_unittest_id['failures'])

    def duplicate_unittest_id(payload):
        payload['executed_ids'] = [payload['executed_ids'][0]] * len(
            payload['executed_ids'])

    duplicated_unittest_id = RUNNER.validate_unittest_file_result(
        ROOT, exact_path, exact_ids,
        _isolated_unittest_marker_result(
            exact_argv, ROOT, unittest_environment,
            payload_update=duplicate_unittest_id,
            skipped_ids=(RUNNER.EXACT_CLI_POSIX_CASE_ID,)),
        pre_identity=exact_identity,
        allowed_skipped_ids=(RUNNER.EXACT_CLI_POSIX_CASE_ID,))
    assert 'unittest_file_result_executed_ids_mismatch' in (
        duplicated_unittest_id['failures'])

    def zero_unittest_denominator(payload):
        payload['executed_ids'] = []
        payload['passed_ids'] = []
        payload['skipped_ids'] = []
        payload['collected'] = 0
        payload['passed'] = 0
        payload['skipped'] = 0
        payload['result'] = 'PASS'

    zero_unittest = RUNNER.validate_unittest_file_result(
        ROOT, exact_path, exact_ids,
        _isolated_unittest_marker_result(
            exact_argv, ROOT, unittest_environment,
            payload_update=zero_unittest_denominator,
            skipped_ids=(RUNNER.EXACT_CLI_POSIX_CASE_ID,)),
        pre_identity=exact_identity,
        allowed_skipped_ids=(RUNNER.EXACT_CLI_POSIX_CASE_ID,))
    assert 'unittest_file_result_zero_denominator' in zero_unittest['failures']
    assert 'unittest_file_result_count_invariant_failed' in (
        zero_unittest['failures'])

    def drift_unittest_path_and_hash(payload):
        payload['path'] = 'src/replaced/test_exact_cli.py'
        payload['sha256'] = '0' * 64

    drifted_unittest_identity = RUNNER.validate_unittest_file_result(
        ROOT, exact_path, exact_ids,
        _isolated_unittest_marker_result(
            exact_argv, ROOT, unittest_environment,
            payload_update=drift_unittest_path_and_hash,
            skipped_ids=(RUNNER.EXACT_CLI_POSIX_CASE_ID,)),
        pre_identity=exact_identity,
        allowed_skipped_ids=(RUNNER.EXACT_CLI_POSIX_CASE_ID,))
    assert 'unittest_file_result_path_mismatch' in (
        drifted_unittest_identity['failures'])
    assert 'unittest_file_result_hash_mismatch' in (
        drifted_unittest_identity['failures'])

    def synchronize_fake_resolved_paths(payload):
        fake_path = str(ROOT / 'synchronized-but-foreign.py')
        payload['resolved_path'] = fake_path
        payload['target_identity_before']['path'] = fake_path
        payload['target_identity_after']['path'] = fake_path

    synchronized_fake_paths = RUNNER.validate_unittest_file_result(
        ROOT, exact_path, exact_ids,
        _isolated_unittest_marker_result(
            exact_argv, ROOT, unittest_environment,
            payload_update=synchronize_fake_resolved_paths,
            skipped_ids=(RUNNER.EXACT_CLI_POSIX_CASE_ID,)),
        pre_identity=exact_identity,
        allowed_skipped_ids=(RUNNER.EXACT_CLI_POSIX_CASE_ID,))
    assert 'unittest_file_result_target_identity_mismatch' in (
        synchronized_fake_paths['failures'])

    def pollute_unittest_environment(payload):
        payload['environment']['clean'] = False
        payload['environment']['contaminated_keys'] = ['PYTHONPATH']

    polluted_unittest_environment = RUNNER.validate_unittest_file_result(
        ROOT, exact_path, exact_ids,
        _isolated_unittest_marker_result(
            exact_argv, ROOT, unittest_environment,
            payload_update=pollute_unittest_environment,
            skipped_ids=(RUNNER.EXACT_CLI_POSIX_CASE_ID,)),
        pre_identity=exact_identity,
        allowed_skipped_ids=(RUNNER.EXACT_CLI_POSIX_CASE_ID,))
    assert 'unittest_file_result_environment_invalid' in (
        polluted_unittest_environment['failures'])

    def drift_unittest_executable(payload):
        payload['executable']['resolved_target']['sha256'] = '0' * 64

    drifted_unittest_executable = RUNNER.validate_unittest_file_result(
        ROOT, exact_path, exact_ids,
        _isolated_unittest_marker_result(
            exact_argv, ROOT, unittest_environment,
            payload_update=drift_unittest_executable,
            skipped_ids=(RUNNER.EXACT_CLI_POSIX_CASE_ID,)),
        pre_identity=exact_identity,
        allowed_skipped_ids=(RUNNER.EXACT_CLI_POSIX_CASE_ID,))
    assert 'unittest_file_result_executable_identity_mismatch' in (
        drifted_unittest_executable['failures'])

    def drift_unittest_entry_lstat(payload):
        payload['executable']['entry_lstat_size_bytes'] += 1
        payload['python'] = json.loads(json.dumps(payload['executable']))

    wrong_entry_lstat = RUNNER.validate_unittest_file_result(
        ROOT, exact_path, exact_ids,
        _isolated_unittest_marker_result(
            exact_argv, ROOT, unittest_environment,
            payload_update=drift_unittest_entry_lstat,
            skipped_ids=(RUNNER.EXACT_CLI_POSIX_CASE_ID,)),
        pre_identity=exact_identity,
        allowed_skipped_ids=(RUNNER.EXACT_CLI_POSIX_CASE_ID,))
    assert 'unittest_file_result_executable_identity_mismatch' in (
        wrong_entry_lstat['failures'])

    def drift_unittest_link_chain(payload):
        payload['executable']['entry_link_chain'] = [{
            'path': 'wrong', 'link_target': 'wrong', 'next_path': 'wrong'}]
        payload['python'] = json.loads(json.dumps(payload['executable']))

    wrong_link_chain = RUNNER.validate_unittest_file_result(
        ROOT, exact_path, exact_ids,
        _isolated_unittest_marker_result(
            exact_argv, ROOT, unittest_environment,
            payload_update=drift_unittest_link_chain,
            skipped_ids=(RUNNER.EXACT_CLI_POSIX_CASE_ID,)),
        pre_identity=exact_identity,
        allowed_skipped_ids=(RUNNER.EXACT_CLI_POSIX_CASE_ID,))
    assert 'unittest_file_result_executable_chain_invalid' in (
        wrong_link_chain['failures'])
    assert 'unittest_file_result_executable_identity_mismatch' in (
        wrong_link_chain['failures'])

    def drift_unittest_version(payload):
        payload['executable']['version'] = [0, 0, 0]
        payload['python'] = json.loads(json.dumps(payload['executable']))

    wrong_unittest_version = RUNNER.validate_unittest_file_result(
        ROOT, exact_path, exact_ids,
        _isolated_unittest_marker_result(
            exact_argv, ROOT, unittest_environment,
            payload_update=drift_unittest_version,
            skipped_ids=(RUNNER.EXACT_CLI_POSIX_CASE_ID,)),
        pre_identity=exact_identity,
        allowed_skipped_ids=(RUNNER.EXACT_CLI_POSIX_CASE_ID,))
    assert 'unittest_file_result_executable_identity_mismatch' in (
        wrong_unittest_version['failures'])

    exact_posix_argv = RUNNER._wsl_unittest_argv(
        ROOT, exact_path, (RUNNER.EXACT_CLI_POSIX_CASE_ID,),
        '/usr/bin/python3', SCRIPT)
    exact_posix = RUNNER.validate_unittest_file_result(
        ROOT, exact_path, (RUNNER.EXACT_CLI_POSIX_CASE_ID,),
        _isolated_unittest_marker_result(
            exact_posix_argv, ROOT, unittest_environment),
        pre_identity=exact_identity,
        expected_executable=RUNNER._expected_wsl_executable_identity(
            '/usr/bin/python3'),
        expected_workspace=RUNNER._windows_path_to_wsl(ROOT),
        record_id='ros1_noetic_field_readiness_exact_cli_posix_companion',
        platform='posix_wsl')
    exact_posix['helper_identity'] = unittest_helper_identity
    exact_posix['wsl_distribution'] = RUNNER.WSL_DISTRIBUTION
    exact_posix['requested_executable_entry'] = '/usr/bin/python3'
    assert exact_posix['validated_pass'] is True
    assert RUNNER._exact_platform_composite(
        exact_windows, exact_posix, exact_ids)['validated_pass'] is True

    def mutate_record_provenance(record, field):
        mutated = json.loads(json.dumps(record))
        if field == 'record_id':
            mutated['record_id'] = 'wrong_record_id'
        elif field == 'platform':
            mutated['platform'] = 'wrong_platform'
        elif field == 'path':
            mutated['path'] = 'wrong/test.py'
        elif field == 'requested_executable_entry':
            mutated['requested_executable_entry'] = '/usr/bin/python3.99'
        elif field == 'wsl_distribution':
            mutated['wsl_distribution'] = 'WrongDistribution'
        elif field == 'executable':
            mutated['executable']['version'] = [0, 0, 0]
        elif field == 'helper_path':
            mutated['helper_identity']['path'] = 'wrong/helper.py'
        else:
            raise AssertionError('unknown provenance field: ' + field)
        return mutated

    for field in ('record_id', 'platform', 'path', 'executable',
                  'helper_path'):
        wrong_exact_windows = mutate_record_provenance(
            exact_windows, field)
        assert 'exact_composite_windows_provenance_mismatch' in (
            RUNNER._exact_platform_composite(
                wrong_exact_windows, exact_posix, exact_ids)['failures'])
    for field in (
            'record_id', 'platform', 'path', 'requested_executable_entry',
            'wsl_distribution', 'executable', 'helper_path'):
        wrong_exact_posix_provenance = mutate_record_provenance(
            exact_posix, field)
        assert 'exact_composite_posix_provenance_mismatch' in (
            RUNNER._exact_platform_composite(
                exact_windows, wrong_exact_posix_provenance,
                exact_ids)['failures'])

    assert 'exact_composite_posix_record_missing' in (
        RUNNER._exact_platform_composite(
            exact_windows, None, exact_ids)['failures'])
    wrong_exact_posix = dict(exact_posix)
    wrong_exact_posix['expected_ids'] = [RUNNER.HOST_READINESS_POSIX_CASE_IDS[0]]
    wrong_exact_posix['passed_ids'] = [RUNNER.HOST_READINESS_POSIX_CASE_IDS[0]]
    assert 'exact_composite_posix_companion_not_passed' in (
        RUNNER._exact_platform_composite(
            exact_windows, wrong_exact_posix, exact_ids)['failures'])
    skipped_exact_posix = dict(exact_posix)
    skipped_exact_posix.update({
        'passed_ids': [],
        'skipped_ids': [RUNNER.EXACT_CLI_POSIX_CASE_ID],
        'passed': 0,
        'skipped': 1,
    })
    assert 'exact_composite_posix_companion_not_passed' in (
        RUNNER._exact_platform_composite(
            exact_windows, skipped_exact_posix, exact_ids)['failures'])
    extra_skip_exact_windows = dict(exact_windows)
    extra_skip_exact_windows['skipped_ids'] = [
        RUNNER.EXACT_CLI_POSIX_CASE_ID, 'unexpected::skip']
    assert 'exact_composite_windows_skip_invalid' in (
        RUNNER._exact_platform_composite(
            extra_skip_exact_windows, exact_posix, exact_ids)['failures'])

    host_path = ROOT / RUNNER.HOST_READINESS_TEST_RELATIVE
    host_ids = RUNNER.static_unittest_case_ids(host_path, ROOT)
    host_identity = RUNNER._pytest_target_identity(host_path, ROOT)
    host_argv = unittest_argv(host_path, host_ids)
    host_windows = RUNNER.validate_unittest_file_result(
        ROOT, host_path, host_ids,
        _isolated_unittest_marker_result(
            host_argv, ROOT, unittest_environment,
            skipped_ids=RUNNER.HOST_READINESS_POSIX_CASE_IDS),
        pre_identity=host_identity,
        allowed_skipped_ids=RUNNER.HOST_READINESS_POSIX_CASE_IDS,
        record_id='windows:' + RUNNER.HOST_READINESS_TEST_RELATIVE,
        platform='windows')
    host_windows['helper_identity'] = unittest_helper_identity
    assert host_windows['validated_pass'] is True
    host_suite_by_case = {
        selected_ids[0]: suite_id
        for suite_id, relative, executable_entry, selected_ids
        in RUNNER.CURRENT_GENERATION_WSL_UNITTEST_TARGETS
        if (relative == RUNNER.HOST_READINESS_TEST_RELATIVE
            and executable_entry == '/usr/bin/python3')}
    assert set(host_suite_by_case) == set(RUNNER.HOST_READINESS_POSIX_CASE_IDS)
    host_posix = {}
    for case_id in RUNNER.HOST_READINESS_POSIX_CASE_IDS:
        posix_argv = RUNNER._wsl_unittest_argv(
            ROOT, host_path, (case_id,), '/usr/bin/python3', SCRIPT)
        record = RUNNER.validate_unittest_file_result(
            ROOT, host_path, (case_id,),
            _isolated_unittest_marker_result(
                posix_argv, ROOT, unittest_environment),
            pre_identity=host_identity,
            expected_executable=RUNNER._expected_wsl_executable_identity(
                '/usr/bin/python3'),
            expected_workspace=RUNNER._windows_path_to_wsl(ROOT),
            record_id=host_suite_by_case[case_id], platform='posix_wsl')
        record['helper_identity'] = unittest_helper_identity
        record['wsl_distribution'] = RUNNER.WSL_DISTRIBUTION
        record['requested_executable_entry'] = '/usr/bin/python3'
        assert record['validated_pass'] is True
        host_posix[case_id] = record
    assert RUNNER._host_readiness_platform_composite(
        host_windows, host_posix, host_ids)['validated_pass'] is True

    for field in ('record_id', 'platform', 'path', 'executable',
                  'helper_path'):
        wrong_host_windows = mutate_record_provenance(host_windows, field)
        assert 'host_composite_windows_provenance_mismatch' in (
            RUNNER._host_readiness_platform_composite(
                wrong_host_windows, host_posix, host_ids)['failures'])
    first_host_case = RUNNER.HOST_READINESS_POSIX_CASE_IDS[0]
    expected_host_posix_code = (
        'host_composite_posix_provenance_mismatch:' + first_host_case)
    for field in (
            'record_id', 'platform', 'path', 'requested_executable_entry',
            'wsl_distribution', 'executable', 'helper_path'):
        wrong_host_posix_provenance = dict(host_posix)
        wrong_host_posix_provenance[first_host_case] = (
            mutate_record_provenance(host_posix[first_host_case], field))
        assert expected_host_posix_code in (
            RUNNER._host_readiness_platform_composite(
                host_windows, wrong_host_posix_provenance,
                host_ids)['failures'])

    missing_host_posix = dict(host_posix)
    missing_host_posix.pop(RUNNER.HOST_READINESS_POSIX_CASE_IDS[1])
    missing_host = RUNNER._host_readiness_platform_composite(
        host_windows, missing_host_posix, host_ids)
    assert 'host_composite_posix_record_set_mismatch' in missing_host['failures']
    assert any(
        failure.startswith('host_composite_posix_record_missing:')
        for failure in missing_host['failures'])

    wrong_host_posix = dict(host_posix)
    wrong_case = RUNNER.HOST_READINESS_POSIX_CASE_IDS[1]
    wrong_record = dict(wrong_host_posix[wrong_case])
    wrong_record['expected_ids'] = ['wrong::case']
    wrong_record['passed_ids'] = ['wrong::case']
    wrong_host_posix[wrong_case] = wrong_record
    assert any(
        failure.startswith('host_composite_posix_companion_not_passed:')
        for failure in RUNNER._host_readiness_platform_composite(
            host_windows, wrong_host_posix, host_ids)['failures'])

    duplicate_host_posix = dict(host_posix)
    duplicate_record = dict(duplicate_host_posix[wrong_case])
    duplicate_record['record_id'] = host_posix[
        RUNNER.HOST_READINESS_POSIX_CASE_IDS[0]]['record_id']
    duplicate_host_posix[wrong_case] = duplicate_record
    assert 'host_composite_duplicate_posix_companion' in (
        RUNNER._host_readiness_platform_composite(
            host_windows, duplicate_host_posix, host_ids)['failures'])

    failed_host_posix = dict(host_posix)
    failed_record = dict(failed_host_posix[wrong_case])
    failed_record.update({
        'passed_ids': [], 'failed_ids': [wrong_case],
        'passed': 0, 'failed': 1,
    })
    failed_host_posix[wrong_case] = failed_record
    assert any(
        failure.startswith('host_composite_posix_companion_not_passed:')
        for failure in RUNNER._host_readiness_platform_composite(
            host_windows, failed_host_posix, host_ids)['failures'])

    skipped_host_posix = dict(host_posix)
    skipped_record = dict(skipped_host_posix[wrong_case])
    skipped_record.update({
        'passed_ids': [], 'skipped_ids': [wrong_case],
        'passed': 0, 'skipped': 1,
    })
    skipped_host_posix[wrong_case] = skipped_record
    assert any(
        failure.startswith('host_composite_posix_companion_not_passed:')
        for failure in RUNNER._host_readiness_platform_composite(
            host_windows, skipped_host_posix, host_ids)['failures'])

    extra_skip_host_windows = dict(host_windows)
    extra_skip_host_windows['skipped_ids'] = [
        *RUNNER.HOST_READINESS_POSIX_CASE_IDS, 'unexpected::skip']
    assert 'host_composite_windows_skip_invalid' in (
        RUNNER._host_readiness_platform_composite(
            extra_skip_host_windows, host_posix, host_ids)['failures'])

    # Execute three real helper subprocesses.  File A deliberately pollutes
    # sys.modules and registers a fixture.  File B proves the module cache is
    # fresh; file C proves A's fixture registry did not cross the process
    # boundary and therefore fails closed as an unsupported fixture.
    with TemporaryDirectory() as directory:
        isolated_root = Path(directory).resolve()
        isolated_test_root = (
            isolated_root / 'src/limo_cleanup_perception/test')
        isolated_test_root.mkdir(parents=True)
        (isolated_root / 'src/limo_cleanup_interfaces').mkdir(parents=True)
        isolated_audit_root = isolated_root / 'audit_tools'
        isolated_audit_root.mkdir()
        shutil.copy2(
            ROOT / RUNNER.PYTEST_STYLE_HELPER_RELATIVE,
            isolated_audit_root / 'run_pytest_style_tests.py')
        leak_path = isolated_test_root / 'test_a_leak.py'
        clean_path = isolated_test_root / 'test_b_clean.py'
        fixture_path = isolated_test_root / 'test_c_fixture.py'
        leak_path.write_text(
            "import sys\nimport types\nimport pytest\n\n"
            "@pytest.fixture\n"
            "def leaked_fixture():\n    return 'from-a'\n\n"
            "def test_install_leak():\n"
            "    sys.modules['leak_probe'] = types.ModuleType('leak_probe')\n",
            encoding='utf-8')
        clean_path.write_text(
            "import sys\n\n"
            "def test_process_has_no_leak():\n"
            "    assert 'leak_probe' not in sys.modules\n",
            encoding='utf-8')
        fixture_path.write_text(
            "def test_fixture_is_not_shared(leaked_fixture):\n"
            "    assert leaked_fixture == 'from-a'\n",
            encoding='utf-8')
        isolated_plan = []
        for path in (leak_path, clean_path, fixture_path):
            relative = path.relative_to(isolated_root).as_posix()
            case_ids = RUNNER.static_pytest_case_ids(path, isolated_root)
            isolated_plan.append({
                'path': path,
                'relative_path': relative,
                'expected_ids': list(case_ids),
                'allocations': [{
                    'scope': 'isolation_probe',
                    'suite_id': path.stem,
                    'expected_ids': list(case_ids),
                }],
            })
        isolation_records, isolation_failures = (
            RUNNER._execute_pytest_file_plan(
                isolated_root, isolated_plan, RUNNER._command_result,
                inherited_environment={}))
        assert isolation_records[0]['validated_pass'] is True
        assert isolation_records[1]['validated_pass'] is True
        assert isolation_records[2]['validated_pass'] is False
        assert 'pytest_file_result_not_all_passed' in (
            isolation_records[2]['failures'])
        assert 'pytest_file_subprocess_failed' in (
            isolation_records[2]['failures'])
        assert isolation_failures == [
            'pytest_file_record_contains_invalid_result']
        assert all(
            record['command']['argv'][1:3] == ['-I', '-B']
            for record in isolation_records)


def test_runner_has_no_ros_camera_wsl_or_motion_execution_surface():
    source = SCRIPT.read_text(encoding='utf-8')
    for token in (
            'ros2 run', 'ros2 bag', 'roscore', 'roslaunch', 'rosrun',
            'bash', 'ssh',
            'start_dabai_camera',
            '\nimport rclpy', '\nfrom rclpy',
            'NavigateToPose(', 'Twist('):
        assert token not in source
    assert "shutil.which('wsl.exe', path=source.get('PATH'))" in source
    assert (
        "str(wsl_launcher), '--distribution', WSL_DISTRIBUTION, '--exec'"
        in source)
    assert "'/usr/bin/env', '-i', 'HOME=/tmp'" in source
    assert RUNNER.WSL_DISTRIBUTION == 'Ubuntu'
    assert RUNNER.WSL_PYTHON_ENTRIES == (
        '/usr/bin/python3', '/usr/bin/python3.14')
    assert "'create_publisher('" in source
    assert "'.publish('" in source
    assert "shutil.which('git', path=environment.get('PATH'))" in source
    assert "'-c', 'safe.directory='," in source
    assert "'-c', 'safe.directory={}'.format(workspace)" in source
    assert "command_prefix + ['rev-parse', '--show-toplevel']" in source
    assert "command_prefix + ['diff', '--check']" in source
    assert "[sys.executable, '-B', '-m', 'unittest', '-v']" in source
    assert 'test_rosbag1_rgbd_indexer.py' in source
    assert 'EXPECTED_GRAND_TEST_COUNT = 197' in source
    assert 'EXPECTED_CURRENT_GENERATION_TEST_COUNT = 144' in source
    assert 'EXPECTED_CURRENT_GENERATION_PHYSICAL_TEST_COUNT = 147' in source
    with patch.object(RUNNER.shutil, 'which', return_value=None):
        result = RUNNER.run_diff_check(
            ROOT,
            command_runner=lambda *_args: (_ for _ in ()).throw(
                AssertionError('command must not run without git')))
    assert result['resolved_executable'] is None
    assert result['failures'] == ['git_executable_not_found']
    assert result['command']['argv'] == []

    config_pollution = {
        'GIT_CONFIG_COUNT': '2',
        'GIT_CONFIG_KEY_0': 'mock-key',
        'GIT_CONFIG_VALUE_0': 'mock-value',
        'GIT_CONFIG_PARAMETERS': 'mock-parameters',
    }
    long_stdout = 'stdout-head-' + ('x' * 9000) + '-stdout-tail'
    long_stderr = (
        'fatal: not a git repository; use --no-index\n'
        'usage: git diff --no-index [options] path path\n'
        'stderr-head-' + ('y' * 9000) + '-stderr-tail')
    observed_environments = []

    def exit_129(argv, cwd, environment):
        observed_environments.append(dict(environment))
        if 'rev-parse' in argv:
            return {
                'argv': list(argv), 'cwd': str(Path(cwd).resolve()),
                'exit_code': 0, 'timed_out': False, 'duration_sec': 1.0,
                'stdout': str(Path(cwd).resolve()) + '\n', 'stderr': '',
            }
        return {
            'argv': list(argv), 'cwd': str(Path(cwd).resolve()),
            'exit_code': 129, 'timed_out': False, 'duration_sec': 1.0,
            'stdout': long_stdout, 'stderr': long_stderr,
        }

    with patch.dict(RUNNER.os.environ, config_pollution, clear=True), \
            patch.object(
                RUNNER.shutil, 'which', return_value=RUNNER.sys.executable):
        polluted = RUNNER.run_diff_check(ROOT, command_runner=exit_129)
    assert polluted['failures'] == ['git_diff_check_failed']
    assert polluted['safe_environment_git_keys'] == []
    assert set(polluted['removed_git_environment_keys']) == set(
        config_pollution)
    assert len(observed_environments) == 2
    assert all(not any(
        key.upper().startswith('GIT_') for key in environment)
        for environment in observed_environments)
    metadata = polluted['inherited_git_environment']['entries']
    assert all('value' not in item for item in metadata)
    assert all(
        item['value_sha256'] and item['value_length_bytes'] > 0
        for item in metadata if item['present'])
    command = polluted['command']
    assert command['cwd'] == str(ROOT.resolve())
    assert command['exit_code'] == 129
    assert command['stdout_length_bytes'] == len(long_stdout.encode('utf-8'))
    assert command['stderr_length_bytes'] == len(long_stderr.encode('utf-8'))
    assert command['stdout_head'].startswith('stdout-head-')
    assert command['stdout_tail'].endswith('-stdout-tail')
    assert command['stderr_head'].startswith('fatal: not a git repository')
    assert 'usage: git diff --no-index' in command['stderr_head']
    assert 'stderr-head-' in command['stderr_head']
    assert command['stderr_tail'].endswith('-stderr-tail')
    assert len(command['stdout_head']) <= RUNNER.COMMAND_OUTPUT_EDGE_CHARS
    assert len(command['stdout_tail']) <= RUNNER.COMMAND_OUTPUT_EDGE_CHARS
    assert len(command['stderr_head']) <= RUNNER.COMMAND_OUTPUT_EDGE_CHARS
    assert len(command['stderr_tail']) <= RUNNER.COMMAND_OUTPUT_EDGE_CHARS
    assert 'stdout' not in command and 'stderr' not in command
    assert polluted['repository_probe_command']['exit_code'] == 0
    assert polluted['repository_toplevel'] == str(ROOT.resolve())
    assert polluted['repository_toplevel_matches_workspace'] is True
    assert polluted['diff_failure_classification'] == (
        'no_index_usage_exit_129')
    for recorded in (
            polluted['repository_probe_command'], polluted['command']):
        argv = recorded['argv']
        assert argv[1:5] == [
            '-c', 'safe.directory=', '-c',
            'safe.directory={}'.format(ROOT.resolve())]
        assert '*' not in argv
        assert '--global' not in argv
        assert 'config' not in argv
    serialized = json.dumps(polluted, sort_keys=True)
    for secret in ('mock-key', 'mock-value', 'mock-parameters'):
        assert secret not in serialized

    def successful_diff(argv, cwd, environment):
        assert not any(
            key.upper().startswith('GIT_') for key in environment)
        stdout = (
            str(Path(cwd).resolve()) + '\n' if 'rev-parse' in argv else '')
        return {
            'argv': list(argv), 'cwd': str(Path(cwd).resolve()),
            'exit_code': 0, 'timed_out': False, 'duration_sec': 1.0,
            'stdout': stdout, 'stderr': '',
        }

    with patch.dict(RUNNER.os.environ, config_pollution, clear=True), \
            patch.object(
                RUNNER.shutil, 'which', return_value=RUNNER.sys.executable):
        cleaned = RUNNER.run_diff_check(ROOT, command_runner=successful_diff)
    assert cleaned['failures'] == []
    assert cleaned['safe_environment_git_keys'] == []
    assert cleaned['repository_toplevel_matches_workspace'] is True

    calls = []

    def dubious_repository(argv, cwd, environment):
        calls.append(list(argv))
        return {
            'argv': list(argv), 'cwd': str(Path(cwd).resolve()),
            'exit_code': 128, 'timed_out': False, 'duration_sec': 1.0,
            'stdout': '',
            'stderr': 'fatal: detected dubious ownership in repository',
        }

    with patch.dict(RUNNER.os.environ, {}, clear=True), patch.object(
            RUNNER.shutil, 'which', return_value=RUNNER.sys.executable):
        dubious = RUNNER.run_diff_check(
            ROOT, command_runner=dubious_repository)
    assert dubious['failures'] == ['git_repository_probe_failed']
    assert dubious['repository_probe_failure_classification'] == (
        'dubious_ownership')
    assert len(calls) == 1
    assert calls[0][-2:] == ['rev-parse', '--show-toplevel']
    assert dubious['repository_probe_command']['exit_code'] == 128
    assert 'dubious ownership' in (
        dubious['repository_probe_command']['stderr_head'])
    assert dubious['command']['exit_code'] is None
    assert 'diff was not run' in dubious['command']['stderr_head']

    def wrong_toplevel(argv, cwd, environment):
        return {
            'argv': list(argv), 'cwd': str(Path(cwd).resolve()),
            'exit_code': 0, 'timed_out': False, 'duration_sec': 1.0,
            'stdout': str(Path(cwd).resolve().parent) + '\n', 'stderr': '',
        }

    with patch.dict(RUNNER.os.environ, {}, clear=True), patch.object(
            RUNNER.shutil, 'which', return_value=RUNNER.sys.executable):
        mismatched = RUNNER.run_diff_check(
            ROOT, command_runner=wrong_toplevel)
    assert mismatched['failures'] == ['git_repository_toplevel_mismatch']
    assert mismatched['repository_toplevel_matches_workspace'] is False

    redirect_sentinel = 'must-never-appear-in-report'
    for redirect_key in sorted(RUNNER.GIT_REPOSITORY_REDIRECTION_KEYS):
        with patch.dict(
                RUNNER.os.environ,
                {redirect_key: redirect_sentinel}, clear=True), \
                patch.object(
                    RUNNER.shutil, 'which',
                    side_effect=AssertionError('git must not resolve')):
            rejected = RUNNER.run_diff_check(
                ROOT,
                command_runner=lambda *_args: (_ for _ in ()).throw(
                    AssertionError('redirected command must not run')))
        assert rejected['failures'] == [
            'git_repository_redirection_environment_present']
        assert rejected['repository_redirection_keys_present'] == [
            redirect_key]
        assert redirect_sentinel not in json.dumps(rejected, sort_keys=True)

    collision_environment = {
        'GIT_DIR': redirect_sentinel,
        'git_dir': redirect_sentinel + '-second',
    }
    audit = RUNNER._git_environment_audit(collision_environment)
    present_names = {
        item['name'] for item in audit['entries'] if item['present']}
    assert present_names == set(collision_environment)
    assert audit['case_collisions'] == [{
        'normalized_name': 'GIT_DIR',
        'key_names': ['GIT_DIR', 'git_dir'],
    }]


if __name__ == '__main__':
    import inspect

    tests = [
        value for name, value in sorted(globals().items())
        if name.startswith('test_') and inspect.isfunction(value)]
    for test in tests:
        test()
    print('{} frozen runner tests passed'.format(len(tests)))

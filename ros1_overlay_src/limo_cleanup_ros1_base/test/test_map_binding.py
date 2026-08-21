import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

import pytest


PACKAGE_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / 'src'))

from limo_cleanup_ros1_base.map_binding import (  # noqa: E402
    EXPECTED_RELEASE_SHA256,
    RELEASE_RELATIVE_PATHS,
    TOKEN_PREFIX,
    build_runtime_preflight_lease,
    canonical_bytes,
    load_runtime_preflight_lease,
    validate_map_binding,
    validate_release_files,
    validate_runtime_preflight_lease,
)
from limo_cleanup_ros1_base.runtime_snapshot import (  # noqa: E402
    CONFIG_SHA256,
    INTERFACE_SHA256,
)


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(tmp_path, map_id='v1_frozen_room'):
    root = tmp_path / 'frozen_maps'
    root.mkdir(mode=0o700, parents=True)
    image = root / '{}.pgm'.format(map_id)
    image.write_bytes(b'P2\n1 1\n255\n0\n')
    yaml_path = root / '{}.yaml'.format(map_id)
    yaml_path.write_text(
        'image: {}.pgm\n'
        'resolution: 0.05\n'
        'origin: [1.0, -2.0, 0.5]\n'
        'negate: 0\n'
        'occupied_thresh: 0.65\n'
        'free_thresh: 0.196\n'.format(map_id),
        encoding='utf-8')
    yaml_path.chmod(0o600)
    image.chmod(0o600)
    root.chmod(0o500)
    unsigned = {
        'schema': 'limo_v1_map_binding/v1',
        'active_map_id': map_id,
        'map_frame': 'map',
        'map_yaml': {
            'realpath': str(yaml_path.resolve()),
            'size': yaml_path.stat().st_size,
            'sha256': _sha(yaml_path),
        },
        'map_image': {
            'realpath': str(image.resolve()),
            'size': image.stat().st_size,
            'sha256': _sha(image),
        },
        'metadata': {
            'image': '{}.pgm'.format(map_id),
            'resolution': 0.05,
            'origin': [1.0, -2.0, 0.5],
            'negate': 0,
            'occupied_thresh': 0.65,
            'free_thresh': 0.196,
        },
        'mode': 'integrated',
        'cmd_vel_output_topic': '/cleanup/base/cmd_vel_request',
        'release_sha256': dict(EXPECTED_RELEASE_SHA256),
    }
    return root, yaml_path, image, unsigned


def _write_binding(tmp_path, unsigned):
    tmp_path.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(canonical_bytes(unsigned)).hexdigest()
    manifest = {**unsigned, 'binding_sha256': digest}
    path = tmp_path / 'binding.json'
    path.write_text(
        json.dumps(manifest, sort_keys=True, separators=(',', ':')),
        encoding='utf-8')
    path.chmod(0o600)
    return path, digest, TOKEN_PREFIX + digest


def test_binding_and_short_lived_runtime_lease_pass(tmp_path):
    root, yaml_path, _image, unsigned = _fixture(tmp_path)
    path, digest, token = _write_binding(tmp_path, unsigned)
    binding = validate_map_binding(path, digest, token, root)
    assert binding.active_map_id == 'v1_frozen_room'
    assert binding.map_file == str(yaml_path.resolve())
    lease = build_runtime_preflight_lease(binding, 'a' * 64, 10.0, 30.0)
    lease_path = tmp_path / 'runtime_lease.json'
    lease_path.write_bytes(canonical_bytes(lease))
    lease_path.chmod(0o600)
    assert load_runtime_preflight_lease(lease_path) == lease
    assert validate_runtime_preflight_lease(
        lease, binding, lease['lease_sha256'], lease['runtime_token'], 39.999)
    with pytest.raises(ValueError):
        validate_runtime_preflight_lease(
            lease, binding, lease['lease_sha256'], lease['runtime_token'], 40.0)
    tampered = dict(lease)
    tampered['active_map_id'] = 'other_map'
    with pytest.raises(ValueError):
        validate_runtime_preflight_lease(
            tampered, binding, lease['lease_sha256'], lease['runtime_token'], 20.0)
    lease_path.chmod(0o640)
    with pytest.raises(ValueError):
        load_runtime_preflight_lease(lease_path)


@pytest.mark.parametrize('map_id', [
    'map02', 'map1017', 'NOT_AVAILABLE_MAP_NOT_FROZEN', 'UPPERCASE'])
def test_rejected_or_malformed_map_ids_block(tmp_path, map_id):
    root, _yaml, _image, unsigned = _fixture(tmp_path, map_id)
    path, digest, token = _write_binding(tmp_path, unsigned)
    with pytest.raises(ValueError):
        validate_map_binding(path, digest, token, root)


def test_hash_permission_release_and_token_drift_block(tmp_path):
    root, _yaml, image, unsigned = _fixture(tmp_path)
    path, digest, token = _write_binding(tmp_path, unsigned)
    image.write_bytes(image.read_bytes() + b'0')
    with pytest.raises(ValueError):
        validate_map_binding(path, digest, token, root)

    root, yaml_path, _image, unsigned = _fixture(tmp_path / 'permissions')
    path, digest, token = _write_binding(tmp_path / 'permissions', unsigned)
    yaml_path.chmod(0o620)
    with pytest.raises(ValueError):
        validate_map_binding(path, digest, token, root)

    root, _yaml, _image, unsigned = _fixture(tmp_path / 'release')
    unsigned['release_sha256']['amcl.yaml'] = '0' * 64
    path, digest, token = _write_binding(tmp_path / 'release', unsigned)
    with pytest.raises(ValueError):
        validate_map_binding(path, digest, token, root)

    root, _yaml, _image, unsigned = _fixture(tmp_path / 'token')
    path, digest, _token = _write_binding(tmp_path / 'token', unsigned)
    with pytest.raises(ValueError):
        validate_map_binding(path, digest, TOKEN_PREFIX + '0' * 64, root)


def test_symlink_and_toctou_changes_block(tmp_path):
    root, _yaml, image, unsigned = _fixture(tmp_path / 'symlink')
    root.chmod(0o700)
    real_image = root / 'real.pgm'
    image.rename(real_image)
    image.symlink_to(real_image.name)
    root.chmod(0o500)
    unsigned['map_image'] = {
        'realpath': str(image),
        'size': real_image.stat().st_size,
        'sha256': _sha(real_image),
    }
    path, digest, token = _write_binding(tmp_path / 'symlink', unsigned)
    with pytest.raises(ValueError):
        validate_map_binding(path, digest, token, root)

    root, yaml_path, _image, unsigned = _fixture(tmp_path / 'toctou')
    path, digest, token = _write_binding(tmp_path / 'toctou', unsigned)

    def mutate(_real_path):
        with yaml_path.open('ab') as stream:
            stream.write(b'# drift\n')
            stream.flush()
            os.fsync(stream.fileno())

    with pytest.raises(RuntimeError):
        validate_map_binding(
            path, digest, token, root, after_yaml_read_hook=mutate)

    root, _yaml, image, unsigned = _fixture(tmp_path / 'image_toctou')
    path, digest, token = _write_binding(tmp_path / 'image_toctou', unsigned)
    image_payload = image.read_bytes()

    def replace_image(_real_path):
        root.chmod(0o700)
        image.rename(image.with_name('v1_frozen_room.old.pgm'))
        image.write_bytes(image_payload)
        image.chmod(0o600)
        root.chmod(0o500)

    with pytest.raises(RuntimeError):
        validate_map_binding(
            path, digest, token, root,
            after_image_read_hook=replace_image)


def test_metadata_image_path_root_escape_and_noncanonical_manifest_block(tmp_path):
    root, yaml_path, _image, unsigned = _fixture(tmp_path / 'metadata')
    unsigned['metadata']['resolution'] = 0.10
    path, digest, token = _write_binding(tmp_path / 'metadata', unsigned)
    with pytest.raises(ValueError):
        validate_map_binding(path, digest, token, root)

    root, yaml_path, _image, unsigned = _fixture(tmp_path / 'image_ref')
    yaml_path.write_text(
        yaml_path.read_text(encoding='utf-8').replace(
            'image: v1_frozen_room.pgm', 'image: ../v1_frozen_room.pgm'),
        encoding='utf-8')
    unsigned['map_yaml']['size'] = yaml_path.stat().st_size
    unsigned['map_yaml']['sha256'] = _sha(yaml_path)
    unsigned['metadata']['image'] = '../v1_frozen_room.pgm'
    path, digest, token = _write_binding(tmp_path / 'image_ref', unsigned)
    with pytest.raises(ValueError):
        validate_map_binding(path, digest, token, root)

    root, _yaml, _image, unsigned = _fixture(tmp_path / 'escape')
    outside = tmp_path / 'outside.pgm'
    outside.write_bytes(b'P2\n1 1\n255\n0\n')
    outside.chmod(0o600)
    unsigned['map_image'] = {
        'realpath': str(outside.resolve()),
        'size': outside.stat().st_size,
        'sha256': _sha(outside),
    }
    path, digest, token = _write_binding(tmp_path / 'escape', unsigned)
    with pytest.raises(ValueError):
        validate_map_binding(path, digest, token, root)

    root, _yaml, _image, unsigned = _fixture(tmp_path / 'canonical')
    path, digest, token = _write_binding(tmp_path / 'canonical', unsigned)
    path.write_text(path.read_text(encoding='utf-8') + '\n', encoding='utf-8')
    with pytest.raises(ValueError):
        validate_map_binding(path, digest, token, root)


def test_release_files_match_the_frozen_hash_set():
    v1_root = PACKAGE_ROOT.parent / 'limo_v1_navigation'
    paths = {
        name: v1_root / relative
        for name, relative in RELEASE_RELATIVE_PATHS.items()
    }
    assert {name: _sha(path) for name, path in paths.items()} == (
        EXPECTED_RELEASE_SHA256)
    assert validate_release_files(v1_root) == EXPECTED_RELEASE_SHA256


def test_release_and_runtime_snapshot_pins_are_one_consistent_contract():
    assert set(EXPECTED_RELEASE_SHA256) == set(RELEASE_RELATIVE_PATHS)
    assert len(EXPECTED_RELEASE_SHA256) == 14
    assert INTERFACE_SHA256 == EXPECTED_RELEASE_SHA256[
        'v1_navigation_interface.json']
    assert CONFIG_SHA256 == {
        name: EXPECTED_RELEASE_SHA256[name]
        for name in (
            'amcl.yaml', 'costmap_common.yaml', 'global_costmap.yaml',
            'local_costmap.yaml', 'move_base.yaml', 'planner.yaml')
    }
    superseded_audit = json.loads((
        PACKAGE_ROOT / 'docs' /
        'V1_TOPOLOGY_POLICY_RELEASE_AUDIT_2026-08-14.json'
    ).read_text(encoding='utf-8'))
    assert superseded_audit['audit_status'] == (
        'BLOCKED_PENDING_TF_EDGE_POLICY_AND_FULL_REGRESSION')
    assert superseded_audit['disposition'] == 'do_not_update_pin'
    assert superseded_audit['lifecycle'] == (
        'STALE_SUPERSEDED_FOR_APPROVAL_PURPOSES')
    assert superseded_audit['may_be_promoted_in_place'] is False
    assert superseded_audit['future_approval_requires_new_audit_file'] is True
    assert superseded_audit['future_approval_requires_new_evidence_id'] is True
    drift_blocker = json.loads((
        PACKAGE_ROOT / 'docs' /
        'V1_TF_EDGE_RELEASE_DRIFT_BLOCKER_2026-08-14.json'
    ).read_text(encoding='utf-8'))
    assert drift_blocker['status'] == (
        'BLOCKED_PIN_UPDATE_PROHIBITED_PENDING_ALL_GREEN')
    assert drift_blocker['disposition'] == 'do_not_update_pin'
    assert drift_blocker['release_pin_updated'] is False
    assert drift_blocker['approval_audit_created'] is False
    assert drift_blocker['release_set'] == {
        'total_files': 14,
        'matching_files': 11,
        'mismatching_files': 3,
    }
    assert {
        item['path'] for item in drift_blocker['files']} == {
        'src/limo_v1_navigation/topology_policy.py',
        'scripts/v1_runtime_preflight.py',
        'launch/v1_runtime_preflight.launch',
    }
    assert all(
        item['recommended_disposition'] ==
        'KEEP_BLOCKED_DO_NOT_UPDATE_PIN'
        for item in drift_blocker['files'])
    v1_root = PACKAGE_ROOT.parent / 'limo_v1_navigation'
    for item in drift_blocker['files']:
        assert item['current_sha256'] == _sha(v1_root / item['path'])
    vendor = drift_blocker['independent_vendor_blocker']
    assert vendor['trusted_blocker_status'] == 'BLOCKED_ON_VENDOR_INCLUDE'
    assert vendor['trusted_blocker_sha256'] == _sha(
        v1_root / 'docs' / 'V1_ROS1_VENDOR_INCLUDE_BLOCKER.json')
    assert vendor['source_manifest_verified'] is False
    assert vendor['rules_manifest_verified'] is False
    assert vendor['publisher_executable_bytes_verified'] is False
    regression = drift_blocker['offline_evidence'][
        'exclusive_regression_report']
    assert regression['status'] == 'COMPLETED_BEFORE_EVIDENCE_LINK_REFRESH'
    assert regression['path'].endswith(
        'v1_frozen_release_readiness_20260814_164200_'
        'vendor_provenance_blocked.json')
    assert len(regression['sha256']) == 64
    assert regression['software_release_pass'] is False
    assert regression['delivery_ready'] is False


def test_machine_readable_release_drift_report_matches_the_accepted_release():
    report_path = (
        PACKAGE_ROOT / 'docs' / 'V1_INTEGRATED_RELEASE_DRIFT_2026-08-13.json')
    report = json.loads(report_path.read_text(encoding='utf-8'))
    assert report['schema'] == 'limo_v1_integrated_release_drift/v1'
    assert report['disposition'] == 'accept_new_release'
    assert report['audit']['source_of_truth'] == [
        'current workspace',
        'Codex main task session 019ffae1-790d-7412-93f2-3d118ed02efa',
        'Codex topology subtask session '
        '019ffae2-2233-76f3-a444-4824daa762f3',
    ]
    assert report['audit']['current_test_evidence'] == {
        'bridge_package_pytest': '122 passed',
        'bridge_cross_package': '9/9 groups PASS',
        'linux_secure_validator': 'VALIDATE_RELEASE_FILES_PASS:14',
        'v1_offline': '113/113 PASS',
    }
    entries = {entry['path']: entry for entry in report['files']}
    assert set(entries) == set(RELEASE_RELATIVE_PATHS.values())
    assert len(entries) == 14
    accepted = set()
    for name, relative in RELEASE_RELATIVE_PATHS.items():
        entry = entries[relative]
        assert entry['current_sha256'] == EXPECTED_RELEASE_SHA256[name]
        assert entry['git_status'] == '??'
        assert entry['semantic_diff']
        assert entry['risk']
        assert entry['verification']
        assert entry['mtime_local']
        assert entry['provenance']
        if entry['expected_sha256_before_audit'] != entry['current_sha256']:
            accepted.add(name)
            assert entry['recommended_disposition'] == 'accept_new_release'
        else:
            assert entry['recommended_disposition'] == 'keep_existing_pin'
    assert accepted == {
        'v1_navigation_core.launch', 'v1_navigation.launch', 'amcl.yaml',
        'topology_policy.py', 'v1_navigation_interface.json'}
    assert report['post_audit_pin_state'] == {
        'release_match_count': 14,
        'release_mismatch_count': 0,
        'runtime_snapshot_amcl_matches_release': True,
        'runtime_snapshot_interface_matches_release': True,
    }


def test_installed_release_file_drift_blocks(tmp_path):
    source = PACKAGE_ROOT.parent / 'limo_v1_navigation'
    copied = tmp_path / 'limo_v1_navigation'
    shutil.copytree(source, copied)
    target = copied / 'config' / 'amcl.yaml'
    target.write_text(
        target.read_text(encoding='utf-8') + '\n# drift\n',
        encoding='utf-8')
    with pytest.raises(ValueError):
        validate_release_files(copied)


def test_manifest_lease_and_release_final_or_ancestor_symlinks_block(tmp_path):
    root, _yaml, _image, unsigned = _fixture(tmp_path / 'manifest')
    binding, digest, token = _write_binding(tmp_path / 'manifest', unsigned)
    binding_real = binding.with_name('binding.real.json')
    binding.rename(binding_real)
    binding.symlink_to(binding_real.name)
    with pytest.raises(ValueError):
        validate_map_binding(binding, digest, token, root)

    binding.unlink()
    binding_real.rename(binding)
    alias = tmp_path / 'manifest_alias'
    alias.symlink_to(binding.parent, target_is_directory=True)
    with pytest.raises(ValueError):
        validate_map_binding(alias / binding.name, digest, token, root)

    validated = validate_map_binding(binding, digest, token, root)
    lease = build_runtime_preflight_lease(validated, 'b' * 64, 1.0, 10.0)
    lease_path = tmp_path / 'lease.json'
    lease_path.write_bytes(canonical_bytes(lease))
    lease_path.chmod(0o600)
    lease_real = tmp_path / 'lease.real.json'
    lease_path.rename(lease_real)
    lease_path.symlink_to(lease_real.name)
    with pytest.raises(ValueError):
        load_runtime_preflight_lease(lease_path)

    lease_path.unlink()
    lease_real.rename(lease_path)
    lease_dir_alias = tmp_path / 'lease_alias'
    lease_dir_alias.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError):
        load_runtime_preflight_lease(lease_dir_alias / lease_path.name)

    source = PACKAGE_ROOT.parent / 'limo_v1_navigation'
    copied = tmp_path / 'release_real'
    shutil.copytree(source, copied)
    core = copied / 'launch' / 'v1_navigation_core.launch'
    core_real = core.with_name('v1_navigation_core.real.launch')
    core.rename(core_real)
    core.symlink_to(core_real.name)
    with pytest.raises(ValueError):
        validate_release_files(copied)

    core.unlink()
    core_real.rename(core)
    release_alias = tmp_path / 'release_alias'
    release_alias.symlink_to(copied, target_is_directory=True)
    with pytest.raises(ValueError):
        validate_release_files(release_alias)


def test_manifest_lease_and_release_path_replacement_toctou_blocks(tmp_path):
    root, _yaml, _image, unsigned = _fixture(tmp_path / 'binding_replace')
    binding, digest, token = _write_binding(
        tmp_path / 'binding_replace', unsigned)
    binding_payload = binding.read_bytes()

    def replace_binding(_real_path):
        binding.rename(binding.with_name('binding.old.json'))
        binding.write_bytes(binding_payload)
        binding.chmod(0o600)

    with pytest.raises(RuntimeError):
        validate_map_binding(
            binding,
            digest,
            token,
            root,
            during_binding_read_hook=replace_binding,
        )

    root, _yaml, _image, unsigned = _fixture(tmp_path / 'lease_replace')
    binding, digest, token = _write_binding(
        tmp_path / 'lease_replace', unsigned)
    validated = validate_map_binding(binding, digest, token, root)
    lease = build_runtime_preflight_lease(validated, 'c' * 64, 1.0, 10.0)
    lease_path = tmp_path / 'lease_replace.json'
    lease_payload = canonical_bytes(lease)
    lease_path.write_bytes(lease_payload)
    lease_path.chmod(0o600)

    def replace_lease(_real_path):
        lease_path.rename(tmp_path / 'lease_replace.old.json')
        lease_path.write_bytes(lease_payload)
        lease_path.chmod(0o600)

    with pytest.raises(RuntimeError):
        load_runtime_preflight_lease(
            lease_path, during_read_hook=replace_lease)

    source = PACKAGE_ROOT.parent / 'limo_v1_navigation'
    copied = tmp_path / 'release_replace'
    shutil.copytree(source, copied)
    target = copied / 'launch' / 'v1_navigation_core.launch'
    target_payload = target.read_bytes()

    def replace_release(name, _real_path):
        if name != 'v1_navigation_core.launch':
            return
        target.rename(target.with_name('v1_navigation_core.old.launch'))
        target.write_bytes(target_payload)
        target.chmod(0o644)

    with pytest.raises(RuntimeError):
        validate_release_files(copied, during_read_hook=replace_release)


def test_manifest_ancestor_replaced_by_symlink_during_read_blocks(tmp_path):
    base = tmp_path / 'ancestor_live'
    root, _yaml, _image, unsigned = _fixture(base)
    binding, digest, token = _write_binding(base, unsigned)
    moved = tmp_path / 'ancestor_moved'

    def replace_ancestor(_real_path):
        base.rename(moved)
        base.symlink_to(moved, target_is_directory=True)

    with pytest.raises((RuntimeError, ValueError)):
        validate_map_binding(
            binding,
            digest,
            token,
            root,
            after_binding_read_hook=replace_ancestor,
        )


@pytest.mark.parametrize('release_name', sorted(RELEASE_RELATIVE_PATHS))
def test_each_frozen_release_final_symlink_blocks(tmp_path, release_name):
    source = PACKAGE_ROOT.parent / 'limo_v1_navigation'
    copied = tmp_path / release_name.replace('.', '_')
    shutil.copytree(source, copied)
    target = copied / RELEASE_RELATIVE_PATHS[release_name]
    real_target = target.with_name(target.name + '.real')
    target.rename(real_target)
    target.symlink_to(real_target.name)
    with pytest.raises(ValueError):
        validate_release_files(copied)


@pytest.mark.parametrize('release_name', sorted(RELEASE_RELATIVE_PATHS))
def test_each_frozen_release_read_in_replacement_blocks(
        tmp_path, release_name):
    source = PACKAGE_ROOT.parent / 'limo_v1_navigation'
    copied = tmp_path / ('replace_' + release_name.replace('.', '_'))
    shutil.copytree(source, copied)
    target = copied / RELEASE_RELATIVE_PATHS[release_name]
    payload = target.read_bytes()

    def replace_during_read(name, _real_path):
        if name != release_name:
            return
        target.rename(target.with_name(target.name + '.old'))
        target.write_bytes(payload)

    with pytest.raises(RuntimeError):
        validate_release_files(
            copied, during_read_hook=replace_during_read)

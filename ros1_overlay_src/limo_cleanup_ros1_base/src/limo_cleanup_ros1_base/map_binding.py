"""Fail-closed V1 frozen-map artifact binding validation."""

import hashlib
import json
import math
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path


SCHEMA = 'limo_v1_map_binding/v1'
TOKEN_PREFIX = 'V1_MAP_BINDING_PASS_V1:'
RUNTIME_TOKEN_PREFIX = 'V1_RUNTIME_PREFLIGHT_PASS_V1:'
ACTIVE_MAP_PATTERN = re.compile(r'^[a-z0-9][a-z0-9_-]{2,63}$')
REJECTED_MAP_IDS = frozenset({
    'map02', 'map1017', 'NOT_AVAILABLE_MAP_NOT_FROZEN'})
INTEGRATED_TOPIC = '/cleanup/base/cmd_vel_request'
EXPECTED_RELEASE_SHA256 = {
    'v1_navigation_core.launch': (
        '8477e7aaa6b772a035aa06f5a5d08fb4cdae16ac590329f613ab67d66de1a445'),
    'v1_navigation.launch': (
        '74cf5d1ae42cdbf95d32e4093452f6873d734140e227beaf783df9d09d17a8ca'),
    'amcl.yaml': (
        '8648ba3f354335cceb356a10b3b9d9f905bf6c5d43a6e4425fb6ce5827369e33'),
    'v1_navigation_profile.yaml': (
        '75141531b0318e96a160d0dc7935c89877d6c43671d0f8aa5a6a63c4724aa240'),
    'topology_policy.py': (
        'c0a860407702d2ccac9f401e38dd8486b79aaf2062296c419b8ade79de921e5a'),
    'v1_navigation_interface.json': (
        '57fb103069e702809dc8366ca2c07600a3c9f1bc530a92c2a9954972b18743cc'),
    'costmap_common.yaml': (
        '4c38280248e658b677f6c1a3c0631a825a4ac3e6ffc0916e32cbf10f55e14193'),
    'global_costmap.yaml': (
        '7520f19ac21b7a36d0a3abf58ca39c78f005d5fcd824d0d9b5a21612eb26f576'),
    'local_costmap.yaml': (
        'cfbebf667375cc8109abbf9d12d5a66cfc07356e77013a4cbb346c4ae2819891'),
    'move_base.yaml': (
        'e4c9e7e38982ae9ddc2f8c26f386fddb01e6b7b9d6b4639e2f8ef9baeab6c950'),
    'planner.yaml': (
        '87b6d44cb250b0325bd71d7a67a1dca4fc7291ccdbee5db7182a11921cea0027'),
    'v1_runtime_preflight.launch': (
        'd99bc0eb6cc76a51c7fb122b84508373a49ecabb234f5231aebc23f6641f5ba7'),
    'v1_runtime_preflight.py': (
        '163d92b1c968886fc2a9ff450a98308edbfe3f81518c7ddf9e29d7c22d2c66cd'),
    'config_policy.py': (
        'd484a4a8953d0a1bda41b08dc2da2c42a21626212c223ded531b5e52332fd413'),
}
RELEASE_RELATIVE_PATHS = {
    'v1_navigation_core.launch': 'launch/v1_navigation_core.launch',
    'v1_navigation.launch': 'launch/v1_navigation.launch',
    'amcl.yaml': 'config/amcl.yaml',
    'v1_navigation_profile.yaml': 'config/v1_navigation_profile.yaml',
    'topology_policy.py': 'src/limo_v1_navigation/topology_policy.py',
    'v1_navigation_interface.json': 'config/v1_navigation_interface.json',
    'costmap_common.yaml': 'config/costmap_common.yaml',
    'global_costmap.yaml': 'config/global_costmap.yaml',
    'local_costmap.yaml': 'config/local_costmap.yaml',
    'move_base.yaml': 'config/move_base.yaml',
    'planner.yaml': 'config/planner.yaml',
    'v1_runtime_preflight.launch': 'launch/v1_runtime_preflight.launch',
    'v1_runtime_preflight.py': 'scripts/v1_runtime_preflight.py',
    'config_policy.py': 'src/limo_v1_navigation/config_policy.py',
}


@dataclass(frozen=True)
class ValidatedMapBinding:
    """Validated immutable inputs for the integrated V1 core."""

    binding_sha256: str
    token: str
    active_map_id: str
    map_file: str
    map_image: str
    map_yaml_size: int = 0
    map_yaml_sha256: str = ''
    map_image_size: int = 0
    map_image_sha256: str = ''


def build_runtime_preflight_lease(binding, run_nonce, now, lifetime=30.0):
    """Bind one short-lived runtime preflight result to one map binding."""
    if not isinstance(run_nonce, str) or not re.fullmatch(
            r'[0-9a-f]{32,128}', run_nonce):
        raise ValueError('run nonce must be lowercase random hex')
    if not math.isfinite(now) or not math.isfinite(lifetime):
        raise ValueError('runtime lease timing must be finite')
    if now < 0.0 or not 0.0 < lifetime <= 60.0:
        raise ValueError('runtime lease lifetime must be in (0, 60] seconds')
    unsigned = {
        'schema': 'limo_v1_runtime_preflight/v1',
        'binding_sha256': binding.binding_sha256,
        'active_map_id': binding.active_map_id,
        'map_file': binding.map_file,
        'mode': 'integrated',
        'cmd_vel_output_topic': INTEGRATED_TOPIC,
        'run_nonce': run_nonce,
        'issued_monotonic': now,
        'expires_monotonic': now + lifetime,
        'preflight_status': 'V1_SCAN_ODOM_TF_PREFLIGHT_PASS',
    }
    digest = hashlib.sha256(canonical_bytes(unsigned)).hexdigest()
    return {
        **unsigned,
        'lease_sha256': digest,
        'runtime_token': RUNTIME_TOKEN_PREFIX + digest,
    }


def validate_runtime_preflight_lease(
        lease, binding, expected_lease_sha256, runtime_token, now):
    """Validate freshness and every binding field before spawning the core."""
    if not isinstance(lease, dict):
        raise ValueError('runtime preflight lease must be an object')
    expected_keys = {
        'schema', 'binding_sha256', 'active_map_id', 'map_file', 'mode',
        'cmd_vel_output_topic', 'run_nonce', 'issued_monotonic',
        'expires_monotonic', 'preflight_status', 'lease_sha256',
        'runtime_token'}
    if set(lease) != expected_keys:
        raise ValueError('runtime preflight lease fields do not match v1')
    _require_sha256(expected_lease_sha256, 'expected_lease_sha256')
    unsigned = dict(lease)
    del unsigned['lease_sha256']
    del unsigned['runtime_token']
    digest = hashlib.sha256(canonical_bytes(unsigned)).hexdigest()
    if (
            digest != lease['lease_sha256']
            or digest != expected_lease_sha256
            or runtime_token != RUNTIME_TOKEN_PREFIX + digest
            or lease['runtime_token'] != runtime_token):
        raise ValueError('runtime preflight lease hash/token mismatch')
    expected_values = {
        'schema': 'limo_v1_runtime_preflight/v1',
        'binding_sha256': binding.binding_sha256,
        'active_map_id': binding.active_map_id,
        'map_file': binding.map_file,
        'mode': 'integrated',
        'cmd_vel_output_topic': INTEGRATED_TOPIC,
        'preflight_status': 'V1_SCAN_ODOM_TF_PREFLIGHT_PASS',
    }
    for key, value in expected_values.items():
        if lease[key] != value:
            raise ValueError('runtime preflight lease {} mismatch'.format(key))
    issued = lease['issued_monotonic']
    expires = lease['expires_monotonic']
    if not all(isinstance(value, (int, float)) and not isinstance(value, bool)
               and math.isfinite(value) for value in (issued, expires, now)):
        raise ValueError('runtime preflight lease timing is invalid')
    if now < issued or now >= expires or expires - issued > 60.0:
        raise ValueError('runtime preflight lease is stale or future-dated')
    return True


def load_runtime_preflight_lease(
        path, after_read_hook=None, during_read_hook=None):
    """Read one owner-only canonical runtime lease without following links."""
    _real, _size, _digest, payload = _secure_read_file(
        path,
        'runtime lease',
        forbidden_mode=stat.S_IRWXG | stat.S_IRWXO,
        require_current_owner=True,
        after_read_hook=after_read_hook,
        during_read_hook=during_read_hook,
    )
    try:
        lease = json.loads(payload.decode('utf-8'))
    except (UnicodeDecodeError, ValueError) as error:
        raise ValueError('runtime lease must be UTF-8 JSON') from error
    if payload != canonical_bytes(lease):
        raise ValueError('runtime lease bytes are not canonical JSON')
    return lease


def canonical_bytes(value) -> bytes:
    """Return the one accepted canonical JSON representation."""
    return json.dumps(
        value, sort_keys=True, separators=(',', ':'),
        ensure_ascii=False).encode('utf-8')


def _stat_identity(file_stat):
    return (
        file_stat.st_dev,
        file_stat.st_ino,
        stat.S_IFMT(file_stat.st_mode),
        file_stat.st_size,
        getattr(
            file_stat, 'st_mtime_ns', int(file_stat.st_mtime * 1e9)),
        getattr(
            file_stat, 'st_ctime_ns', int(file_stat.st_ctime * 1e9)),
    )


def _validated_absolute_path(path, name):
    candidate = Path(path)
    if not candidate.is_absolute():
        raise ValueError('{} path must be absolute'.format(name))
    if '..' in candidate.parts:
        raise ValueError('{} path must not contain parent traversal'.format(name))
    if (
            os.name != 'posix'
            or not hasattr(os, 'O_NOFOLLOW')
            or not hasattr(os, 'O_DIRECTORY')
            or os.open not in os.supports_dir_fd):
        raise RuntimeError(
            'secure openat/O_NOFOLLOW support is required for {}'.format(name))
    return candidate


def _directory_identity(directory_stat):
    return (
        directory_stat.st_dev,
        directory_stat.st_ino,
        stat.S_IFMT(directory_stat.st_mode),
    )


def _close_descriptors(descriptors):
    for descriptor in reversed(descriptors):
        try:
            os.close(descriptor)
        except OSError:
            pass


def _open_directory_chain(path, name):
    candidate = _validated_absolute_path(path, name)
    flags = (
        os.O_RDONLY
        | os.O_DIRECTORY
        | os.O_NOFOLLOW
        | getattr(os, 'O_CLOEXEC', 0)
    )
    descriptors = []
    try:
        descriptors.append(os.open(candidate.anchor, flags))
        parts = candidate.parts[1:] if candidate.anchor else candidate.parts
        for part in parts:
            descriptor = os.open(
                part,
                flags,
                dir_fd=descriptors[-1],
            )
            component_stat = os.fstat(descriptor)
            if not stat.S_ISDIR(component_stat.st_mode):
                raise ValueError(
                    '{} component is not a directory: {}'.format(name, part))
            descriptors.append(descriptor)
        return descriptors
    except OSError as error:
        _close_descriptors(descriptors)
        raise ValueError(
            '{} contains a missing or symlinked ancestor'.format(name)
        ) from error
    except Exception:
        _close_descriptors(descriptors)
        raise


def _reopen_directory_chain(path, identities, name):
    descriptors = _open_directory_chain(path, name)
    try:
        current = [
            _directory_identity(os.fstat(descriptor))
            for descriptor in descriptors
        ]
        if current != identities:
            raise RuntimeError(
                '{} ancestor identity changed during verification'.format(name))
    finally:
        _close_descriptors(descriptors)


def _secure_read_file(
        path, name, forbidden_mode=stat.S_IWGRP | stat.S_IWOTH,
        require_current_owner=False, after_read_hook=None,
        during_read_hook=None):
    """Read one stable regular file through a non-following descriptor."""
    candidate = _validated_absolute_path(path, name)
    parent_descriptors = _open_directory_chain(candidate.parent, name)
    parent_identities = [
        _directory_identity(os.fstat(descriptor))
        for descriptor in parent_descriptors
    ]
    flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, 'O_CLOEXEC', 0)
    if hasattr(os, 'O_BINARY'):
        flags |= os.O_BINARY
    try:
        descriptor = os.open(
            candidate.name,
            flags,
            dir_fd=parent_descriptors[-1],
        )
    except OSError as error:
        _close_descriptors(parent_descriptors)
        raise ValueError(
            '{} final component is unavailable or a symlink'.format(name)
        ) from error
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size <= 0:
            raise ValueError('{} must be a non-empty regular file'.format(name))
        if before.st_mode & forbidden_mode:
            raise ValueError('{} has unsafe permissions'.format(name))
        if (
                require_current_owner
                and hasattr(os, 'geteuid')
                and before.st_uid != os.geteuid()):
            raise ValueError('{} must be owned by the current user'.format(name))
        chunks = []
        real_path = os.path.realpath(str(candidate))
        during_hook_called = False
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
            if during_read_hook is not None and not during_hook_called:
                during_hook_called = True
                during_read_hook(real_path)
        payload = b''.join(chunks)
        if after_read_hook is not None:
            after_read_hook(real_path)
        after = os.fstat(descriptor)
        try:
            pinned_path_after = os.stat(
                candidate.name,
                dir_fd=parent_descriptors[-1],
                follow_symlinks=False,
            )
            path_after = os.stat(str(candidate), follow_symlinks=False)
        except OSError as error:
            raise RuntimeError(
                '{} path changed while it was verified'.format(name)) from error
        _reopen_directory_chain(
            candidate.parent,
            parent_identities,
            name,
        )
        if (
                _stat_identity(before) != _stat_identity(after)
                or _stat_identity(before) != _stat_identity(pinned_path_after)
                or _stat_identity(before) != _stat_identity(path_after)
                or len(payload) != before.st_size):
            raise RuntimeError(
                '{} changed while it was being verified'.format(name))
        return (
            real_path,
            before.st_size,
            hashlib.sha256(payload).hexdigest(),
            payload,
        )
    finally:
        os.close(descriptor)
        _close_descriptors(parent_descriptors)


def _secure_directory(path, name):
    candidate = _validated_absolute_path(path, name)
    descriptors = _open_directory_chain(candidate, name)
    identities = [
        _directory_identity(os.fstat(descriptor))
        for descriptor in descriptors
    ]
    try:
        directory_stat = os.fstat(descriptors[-1])
        path_stat = os.stat(str(candidate), follow_symlinks=False)
        if _directory_identity(directory_stat) != _directory_identity(path_stat):
            raise RuntimeError('{} directory identity changed'.format(name))
        _reopen_directory_chain(candidate, identities, name)
        return directory_stat, os.path.realpath(str(candidate))
    finally:
        _close_descriptors(descriptors)


def validate_release_files(
        v1_package_root, after_read_hook=None, during_read_hook=None):
    """Require the installed reusable V1 release files to match all hashes."""
    root = Path(v1_package_root)
    root_stat, _root_real = _secure_directory(root, 'v1_package_root')
    if not stat.S_ISDIR(root_stat.st_mode):
        raise ValueError('v1_package_root must be an absolute real directory')
    actual = {}
    for name, relative in RELEASE_RELATIVE_PATHS.items():
        path = root / relative
        hook = None
        during_hook = None
        if after_read_hook is not None:
            hook = lambda real_path, release_name=name: after_read_hook(
                release_name, real_path)
        if during_read_hook is not None:
            during_hook = lambda real_path, release_name=name: during_read_hook(
                release_name, real_path)
        _real_path, _size, digest, _payload = _secure_read_file(
            path,
            'V1 release file {}'.format(name),
            forbidden_mode=0,
            after_read_hook=hook,
            during_read_hook=during_hook,
        )
        actual[name] = digest
    if actual != EXPECTED_RELEASE_SHA256:
        raise ValueError('installed V1 release files do not match frozen SHA set')
    return actual


def load_release_payloads(v1_package_root):
    """Securely read and hash every frozen V1 launch/config interface file."""
    root = Path(v1_package_root)
    _secure_directory(root, 'v1_package_root')
    payloads = {}
    actual = {}
    for name, relative in RELEASE_RELATIVE_PATHS.items():
        _real, _size, digest, payload = _secure_read_file(
            root / relative,
            'V1 release file {}'.format(name),
            forbidden_mode=0,
        )
        payloads[name] = payload
        actual[name] = digest
    if actual != EXPECTED_RELEASE_SHA256:
        raise ValueError('installed V1 release payloads do not match SHA set')
    return payloads


def load_bound_map_payloads(binding, map_root):
    """Re-open the bound YAML/PGM securely for immutable snapshot creation."""
    root = _real_root(map_root)
    yaml_real, yaml_size, yaml_sha, yaml_payload = _read_immutable_file(
        binding.map_file, root)
    image_real, image_size, image_sha, image_payload = _read_immutable_file(
        binding.map_image, root)
    if (
            yaml_real != binding.map_file
            or image_real != binding.map_image
            or yaml_size != binding.map_yaml_size
            or yaml_sha != binding.map_yaml_sha256
            or image_size != binding.map_image_size
            or image_sha != binding.map_image_sha256):
        raise ValueError('bound map bytes drifted before snapshot creation')
    return yaml_payload, image_payload


def _require_sha256(value, name):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{64}', value):
        raise ValueError('{} must be lowercase SHA-256 hex'.format(name))


def _real_root(map_root):
    root = Path(map_root)
    root_stat, root_real = _secure_directory(root, 'map_root')
    if not stat.S_ISDIR(root_stat.st_mode):
        raise ValueError('map_root must be a real directory, not a symlink')
    if root_stat.st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH):
        raise ValueError('frozen map_root must be read-only during navigation')
    return root_real


def _read_immutable_file(
        path, map_root, after_read_hook=None, during_read_hook=None):
    candidate = Path(path)
    _validated_absolute_path(candidate, 'bound map artifact')
    real_path = os.path.realpath(str(candidate))
    if os.path.commonpath((map_root, real_path)) != map_root:
        raise ValueError('bound map file escapes the frozen map root')
    return _secure_read_file(
        candidate,
        'bound map artifact',
        after_read_hook=after_read_hook,
        during_read_hook=during_read_hook,
    )


def _parse_map_yaml(payload):
    try:
        lines = payload.decode('utf-8').splitlines()
    except UnicodeDecodeError as error:
        raise ValueError('map YAML must be UTF-8') from error
    pattern = re.compile(r'^\s*([A-Za-z_]+)\s*:\s*(.*?)\s*$')
    values = {}
    required = {
        'image', 'resolution', 'origin', 'negate',
        'occupied_thresh', 'free_thresh'}
    for raw_line in lines:
        match = pattern.match(raw_line)
        if not match or match.group(1) not in required:
            continue
        key = match.group(1)
        if key in values:
            raise ValueError('map YAML metadata field is duplicated: {}'.format(key))
        values[key] = match.group(2).strip().strip('"\'')
    if set(values) != required:
        raise ValueError('map YAML metadata fields are incomplete')
    try:
        resolution = float(values['resolution'])
        negate = int(values['negate'])
        occupied = float(values['occupied_thresh'])
        free = float(values['free_thresh'])
        origin_text = values['origin']
        if not (origin_text.startswith('[') and origin_text.endswith(']')):
            raise ValueError('origin must be an array')
        origin = [float(part.strip()) for part in origin_text[1:-1].split(',')]
    except (TypeError, ValueError) as error:
        raise ValueError('map YAML metadata must be numeric') from error
    numeric = [resolution, occupied, free, *origin]
    if not all(math.isfinite(value) for value in numeric):
        raise ValueError('map YAML metadata must be finite')
    if resolution <= 0.0 or len(origin) != 3:
        raise ValueError('map resolution/origin is invalid')
    if negate not in (0, 1) or not 0.0 <= free < occupied <= 1.0:
        raise ValueError('map thresholds/negate are invalid')
    return {
        'image': values['image'],
        'resolution': resolution,
        'origin': origin,
        'negate': negate,
        'occupied_thresh': occupied,
        'free_thresh': free,
    }


def validate_map_binding(
        binding_file, expected_binding_sha256, external_token, map_root,
        after_binding_read_hook=None, after_yaml_read_hook=None,
        after_image_read_hook=None, during_binding_read_hook=None,
        during_yaml_read_hook=None, during_image_read_hook=None):
    """Validate one binding manifest and both artifacts without following links."""
    _require_sha256(expected_binding_sha256, 'expected_binding_sha256')
    _binding_real, _binding_size, _binding_digest, binding_payload = (
        _secure_read_file(
            binding_file,
            'binding_file',
            after_read_hook=after_binding_read_hook,
            during_read_hook=during_binding_read_hook,
        ))
    try:
        manifest = json.loads(binding_payload.decode('utf-8'))
    except (UnicodeDecodeError, ValueError) as error:
        raise ValueError('binding manifest must be UTF-8 JSON') from error
    expected_top_level = {
        'schema', 'binding_sha256', 'active_map_id', 'map_frame',
        'map_yaml', 'map_image', 'metadata', 'mode',
        'cmd_vel_output_topic', 'release_sha256'}
    if not isinstance(manifest, dict) or set(manifest) != expected_top_level:
        raise ValueError('binding manifest fields do not match v1 schema')
    if binding_payload != canonical_bytes(manifest):
        raise ValueError('binding manifest bytes are not canonical JSON')
    if manifest['schema'] != SCHEMA or manifest['map_frame'] != 'map':
        raise ValueError('binding schema/map frame is unsupported')
    active_map_id = manifest['active_map_id']
    if (
            not isinstance(active_map_id, str)
            or not ACTIVE_MAP_PATTERN.fullmatch(active_map_id)
            or active_map_id in REJECTED_MAP_IDS):
        raise ValueError('active_map_id is missing, malformed, or rejected')
    if (
            manifest['mode'] != 'integrated'
            or manifest['cmd_vel_output_topic'] != INTEGRATED_TOPIC):
        raise ValueError('binding must select the integrated private request topic')
    if manifest['release_sha256'] != EXPECTED_RELEASE_SHA256:
        raise ValueError('frozen V1 release SHA set does not match')
    declared_digest = manifest['binding_sha256']
    _require_sha256(declared_digest, 'binding_sha256')
    unsigned = dict(manifest)
    del unsigned['binding_sha256']
    calculated_digest = hashlib.sha256(canonical_bytes(unsigned)).hexdigest()
    if declared_digest != calculated_digest or declared_digest != expected_binding_sha256:
        raise ValueError('binding SHA does not match canonical manifest bytes')
    if external_token != TOKEN_PREFIX + calculated_digest:
        raise ValueError('external map binding token does not match the manifest')

    root = _real_root(map_root)
    for key in ('map_yaml', 'map_image'):
        value = manifest[key]
        if not isinstance(value, dict) or set(value) != {
                'realpath', 'size', 'sha256'}:
            raise ValueError('{} descriptor is malformed'.format(key))
        if not isinstance(value['size'], int) or isinstance(value['size'], bool):
            raise ValueError('{} size must be an integer'.format(key))
        _require_sha256(value['sha256'], '{} sha256'.format(key))
    yaml_real, yaml_size, yaml_sha, yaml_payload = _read_immutable_file(
        manifest['map_yaml']['realpath'], root, after_yaml_read_hook,
        during_yaml_read_hook)
    image_real, image_size, image_sha, _ = _read_immutable_file(
        manifest['map_image']['realpath'], root, after_image_read_hook,
        during_image_read_hook)
    if Path(yaml_real).suffix != '.yaml' or Path(yaml_real).stem != active_map_id:
        raise ValueError('YAML basename must exactly match active_map_id')
    expected_image_name = '{}.pgm'.format(active_map_id)
    if Path(image_real).name != expected_image_name:
        raise ValueError('PGM basename must exactly match active_map_id')
    if Path(yaml_real).parent != Path(image_real).parent:
        raise ValueError('YAML and PGM must share one frozen directory')
    parsed_metadata = _parse_map_yaml(yaml_payload)
    if parsed_metadata['image'] != expected_image_name:
        raise ValueError('YAML image must be the same-directory PGM basename')
    if manifest['metadata'] != parsed_metadata:
        raise ValueError('canonical map metadata does not match YAML bytes')
    actual_descriptors = {
        'map_yaml': {'realpath': yaml_real, 'size': yaml_size, 'sha256': yaml_sha},
        'map_image': {'realpath': image_real, 'size': image_size, 'sha256': image_sha},
    }
    for key, actual in actual_descriptors.items():
        if manifest[key] != actual:
            raise ValueError('{} path/size/SHA does not match'.format(key))
    return ValidatedMapBinding(
        binding_sha256=calculated_digest,
        token=external_token,
        active_map_id=active_map_id,
        map_file=yaml_real,
        map_image=image_real,
        map_yaml_size=yaml_size,
        map_yaml_sha256=yaml_sha,
        map_image_size=image_size,
        map_image_sha256=image_sha,
    )

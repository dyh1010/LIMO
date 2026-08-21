"""Linux sealed runtime artifacts for the private integrated V1 core."""

import fcntl
import hashlib
import json
import os
import re
from dataclasses import dataclass

from limo_cleanup_ros1_base.map_binding import load_bound_map_payloads


INTERFACE_SHA256 = (
    '57fb103069e702809dc8366ca2c07600a3c9f1bc530a92c2a9954972b18743cc')
CONFIG_SHA256 = {
    'amcl.yaml': (
        '8648ba3f354335cceb356a10b3b9d9f905bf6c5d43a6e4425fb6ce5827369e33'),
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
}
LOAD_ORDER = (
    ('amcl.yaml', '/amcl'),
    ('costmap_common.yaml', '/move_base/global_costmap'),
    ('costmap_common.yaml', '/move_base/local_costmap'),
    ('local_costmap.yaml', '/move_base'),
    ('global_costmap.yaml', '/move_base'),
    ('move_base.yaml', '/move_base'),
    ('planner.yaml', '/move_base'),
)
SEAL_MASK = (
    fcntl.F_SEAL_WRITE
    | fcntl.F_SEAL_GROW
    | fcntl.F_SEAL_SHRINK
    | fcntl.F_SEAL_SEAL
)


def validate_interface_payload(payload):
    """Require the exact V1 v2 integrated/private snapshot interface."""
    if hashlib.sha256(payload).hexdigest() != INTERFACE_SHA256:
        raise ValueError('V1 navigation interface SHA mismatch')
    try:
        interface = json.loads(payload.decode('utf-8'))
    except (UnicodeDecodeError, ValueError) as error:
        raise ValueError('V1 navigation interface is not UTF-8 JSON') from error
    if interface.get('schema') != 'limo_v1_navigation_interface/v2':
        raise ValueError('unsupported V1 navigation interface schema')
    integrated = interface.get('integrated_navigation')
    if integrated != {
            'core_owner': 'bridge_runner_private_launch',
            'installed_launch_entry': False,
            'move_base_output_topic': '/cleanup/base/cmd_vel_request',
            'precore_stage': 'navigation_precore',
            'snapshot_required': True}:
        raise ValueError('V1 integrated navigation interface is not exact')
    public = interface.get('public_navigation', {})
    if (
            public.get('mode') != 'native'
            or public.get('move_base_output_topic') != '/v1/nav_cmd_vel'
            or 'cmd_vel_output_topic' in public.get('core_args', ())):
        raise ValueError('installed V1 navigation is not native-only')
    if interface.get('snapshot_config_sha256') != CONFIG_SHA256:
        raise ValueError('V1 snapshot config SHA mapping is not exact')
    load_order = tuple(
        (item.get('file'), item.get('namespace'))
        for item in interface.get('snapshot_rosparam_load_order', ()))
    if load_order != LOAD_ORDER:
        raise ValueError('V1 rosparam load order/namespace contract drifted')
    return interface


def _sealed_memfd(name, payload):
    if os.name != 'posix' or not hasattr(os, 'memfd_create'):
        raise RuntimeError('Linux memfd_create is required for navigation')
    flags = os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING
    descriptor = os.memfd_create(name, flags)
    try:
        offset = 0
        while offset < len(payload):
            offset += os.write(descriptor, payload[offset:])
        os.fsync(descriptor)
        fcntl.fcntl(descriptor, fcntl.F_ADD_SEALS, SEAL_MASK)
        if fcntl.fcntl(descriptor, fcntl.F_GET_SEALS) != SEAL_MASK:
            raise RuntimeError('memfd seal set is incomplete')
        os.lseek(descriptor, 0, os.SEEK_SET)
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def _fd_path(descriptor):
    return '/proc/{}/fd/{}'.format(os.getpid(), descriptor)


def _rewrite_map_yaml(yaml_payload, image_path):
    try:
        text = yaml_payload.decode('utf-8')
    except UnicodeDecodeError as error:
        raise ValueError('bound map YAML is not UTF-8') from error
    pattern = re.compile(r'(?m)^(\s*image\s*:\s*).*$')
    matches = pattern.findall(text)
    if len(matches) != 1:
        raise ValueError('bound map YAML must contain exactly one image field')
    rewritten = pattern.sub(
        lambda match: '{}{}'.format(match.group(1), image_path), text)
    return rewritten.encode('utf-8')


def _read_fd(descriptor):
    file_stat = os.fstat(descriptor)
    payload = bytearray()
    offset = 0
    while offset < file_stat.st_size:
        chunk = os.pread(descriptor, min(65536, file_stat.st_size - offset), offset)
        if not chunk:
            break
        payload.extend(chunk)
        offset += len(chunk)
    if len(payload) != file_stat.st_size:
        raise RuntimeError('sealed runtime FD became unreadable')
    return bytes(payload)


@dataclass
class ImmutableNavigationSnapshot:
    """Runner-held sealed map/config FDs consumed through /proc paths."""

    descriptors: dict
    paths: dict
    sha256: dict

    def validate(self):
        for name, descriptor in self.descriptors.items():
            if fcntl.fcntl(descriptor, fcntl.F_GET_SEALS) != SEAL_MASK:
                raise RuntimeError('{} runtime FD lost required seals'.format(name))
            payload = _read_fd(descriptor)
            if hashlib.sha256(payload).hexdigest() != self.sha256[name]:
                raise RuntimeError('{} runtime FD content drifted'.format(name))
            if self.paths[name] != _fd_path(descriptor):
                raise RuntimeError('{} runtime FD path drifted'.format(name))
        return True

    def close(self):
        descriptors = list(self.descriptors.values())
        self.descriptors.clear()
        for descriptor in descriptors:
            try:
                os.close(descriptor)
            except OSError:
                pass


def create_navigation_snapshot(binding, map_root, release_payloads):
    """Seal the bound map and six V1 config files before core spawn."""
    validate_interface_payload(release_payloads['v1_navigation_interface.json'])
    for name, expected_sha in CONFIG_SHA256.items():
        payload = release_payloads.get(name)
        if payload is None or hashlib.sha256(payload).hexdigest() != expected_sha:
            raise ValueError('{} snapshot source SHA mismatch'.format(name))
    yaml_payload, image_payload = load_bound_map_payloads(binding, map_root)
    descriptors = {}
    paths = {}
    digests = {}
    try:
        image_fd = _sealed_memfd(
            '{}.pgm'.format(binding.active_map_id), image_payload)
        descriptors['map_image'] = image_fd
        paths['map_image'] = _fd_path(image_fd)
        digests['map_image'] = hashlib.sha256(image_payload).hexdigest()
        sealed_yaml = _rewrite_map_yaml(yaml_payload, paths['map_image'])
        yaml_fd = _sealed_memfd(
            '{}.yaml'.format(binding.active_map_id), sealed_yaml)
        descriptors['map_yaml'] = yaml_fd
        paths['map_yaml'] = _fd_path(yaml_fd)
        digests['map_yaml'] = hashlib.sha256(sealed_yaml).hexdigest()
        for name in CONFIG_SHA256:
            descriptor = _sealed_memfd(name, release_payloads[name])
            descriptors[name] = descriptor
            paths[name] = _fd_path(descriptor)
            digests[name] = CONFIG_SHA256[name]
        snapshot = ImmutableNavigationSnapshot(descriptors, paths, digests)
        snapshot.validate()
        return snapshot
    except Exception:
        ImmutableNavigationSnapshot(descriptors, paths, digests).close()
        raise

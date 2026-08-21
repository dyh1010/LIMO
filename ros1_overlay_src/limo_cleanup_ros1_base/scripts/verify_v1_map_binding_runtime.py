#!/usr/bin/env python3
"""Continuously guard a validated V1 map binding during bridged navigation."""

import os
import fcntl
import hashlib
import json
import stat
import time

import rospy

from limo_cleanup_ros1_base.map_binding import (
    load_runtime_preflight_lease,
    validate_map_binding,
    validate_release_files,
    validate_runtime_preflight_lease,
)
from limo_cleanup_ros1_base.runtime_snapshot import SEAL_MASK
from limo_cleanup_ros1_base.strict_json import loads_strict


def _validated_inputs():
    validate_release_files(rospy.get_param('~v1_release_root'))
    binding = validate_map_binding(
        rospy.get_param('~binding_file'),
        rospy.get_param('~binding_sha256'),
        rospy.get_param('~binding_token'),
        rospy.get_param('~map_root'),
    )
    lease = load_runtime_preflight_lease(
        rospy.get_param('~runtime_lease_file'))
    validate_runtime_preflight_lease(
        lease,
        binding,
        rospy.get_param('~runtime_lease_sha256'),
        rospy.get_param('~runtime_token'),
        time.monotonic(),
    )
    if binding.map_file != rospy.get_param('~expected_source_map_file'):
        raise RuntimeError('validated source map_file does not match binding')
    if binding.active_map_id != rospy.get_param('~expected_active_map_id'):
        raise RuntimeError('validated active_map_id does not match core input')
    return binding, _validated_snapshot()


def _read_descriptor(descriptor):
    file_stat = os.fstat(descriptor)
    payload = bytearray()
    offset = 0
    while offset < file_stat.st_size:
        chunk = os.pread(
            descriptor, min(65536, file_stat.st_size - offset), offset)
        if not chunk:
            break
        payload.extend(chunk)
        offset += len(chunk)
    if len(payload) != file_stat.st_size:
        raise RuntimeError('sealed snapshot descriptor became unreadable')
    return bytes(payload)


def _parse_snapshot_manifest(raw_manifest):
    """Accept ROS string or dictionary parameters without type confusion."""
    if isinstance(raw_manifest, str):
        try:
            manifest = loads_strict(raw_manifest, 'snapshot manifest')
        except ValueError as error:
            raise RuntimeError('snapshot manifest is invalid JSON') from error
    elif isinstance(raw_manifest, dict):
        manifest = dict(raw_manifest)
    else:
        raise RuntimeError('snapshot manifest must be a dict or JSON string')
    if not isinstance(manifest, dict):
        raise RuntimeError('snapshot manifest JSON root must be an object')
    return manifest


def _validated_snapshot():
    runner_pid = rospy.get_param('~snapshot_runner_pid')
    if isinstance(runner_pid, bool) or not isinstance(runner_pid, int):
        raise RuntimeError('snapshot runner PID is invalid')
    manifest = _parse_snapshot_manifest(
        rospy.get_param('~snapshot_manifest'))
    expected_names = {
        'map_yaml', 'map_image', 'amcl.yaml', 'costmap_common.yaml',
        'global_costmap.yaml', 'local_costmap.yaml', 'move_base.yaml',
        'planner.yaml'}
    if set(manifest) != expected_names:
        raise RuntimeError('snapshot manifest file set is not exact')
    prefix = '/proc/{}/fd/'.format(runner_pid)
    for name, item in manifest.items():
        if not isinstance(item, dict) or set(item) != {'path', 'sha256'}:
            raise RuntimeError('snapshot descriptor {} is malformed'.format(name))
        path = item['path']
        if (
                not isinstance(path, str)
                or not path.startswith(prefix)
                or not path[len(prefix):].isdigit()):
            raise RuntimeError('snapshot path is not runner-owned /proc FD')
        descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_CLOEXEC', 0))
        try:
            if fcntl.fcntl(descriptor, fcntl.F_GET_SEALS) != SEAL_MASK:
                raise RuntimeError('{} snapshot FD is not fully sealed'.format(name))
            digest = hashlib.sha256(_read_descriptor(descriptor)).hexdigest()
            if digest != item['sha256']:
                raise RuntimeError('{} snapshot FD SHA mismatch'.format(name))
        finally:
            os.close(descriptor)
    return manifest


def _write_private_record(ready_fd, label, binding, sequence):
    payload = '{}:{}:{}\n'.format(
        label, binding.binding_sha256, sequence).encode('ascii')
    offset = 0
    while offset < len(payload):
        offset += os.write(ready_fd, payload[offset:])


def _private_ready_fd(binding):
    ready_fd = rospy.get_param('~ready_fd', None)
    if isinstance(ready_fd, bool) or not isinstance(ready_fd, int):
        raise RuntimeError('private ready FD is required')
    if ready_fd < 3:
        raise RuntimeError('private ready FD is invalid')
    descriptor_stat = os.fstat(ready_fd)
    if not stat.S_ISFIFO(descriptor_stat.st_mode):
        raise RuntimeError('private ready FD must be a pipe')
    _write_private_record(
        ready_fd, 'V1_MAP_BINDING_MONITOR_READY', binding, 0)
    return ready_fd


def main():
    rospy.init_node('verify_v1_map_binding_runtime')
    try:
        binding, snapshot = _validated_inputs()
        ready_fd = _private_ready_fd(binding)
        rospy.loginfo(
            'V1_MAP_BINDING_RUNTIME_PASS: %s %s',
            binding.active_map_id, binding.binding_sha256)
        rate = rospy.Rate(1.0)
        sequence = 1
        while not rospy.is_shutdown():
            validate_release_files(rospy.get_param('~v1_release_root'))
            current = validate_map_binding(
                rospy.get_param('~binding_file'),
                rospy.get_param('~binding_sha256'),
                rospy.get_param('~binding_token'),
                rospy.get_param('~map_root'),
            )
            if current != binding:
                raise RuntimeError('map binding changed after startup')
            if _validated_snapshot() != snapshot:
                raise RuntimeError('sealed navigation snapshot changed')
            _write_private_record(
                ready_fd, 'V1_MAP_BINDING_MONITOR_HEARTBEAT',
                binding, sequence)
            sequence += 1
            rate.sleep()
        os.close(ready_fd)
        return 0
    except Exception as error:
        rospy.logfatal('V1_MAP_BINDING_RUNTIME_BLOCKED: %s', error)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

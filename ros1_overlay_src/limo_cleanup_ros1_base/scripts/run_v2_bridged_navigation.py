#!/usr/bin/env python3
"""Sole production entry for sealed, staged V2 bridged navigation."""

import argparse
import ctypes
import fcntl
import json
import os
from pathlib import Path
import secrets
import select
import shutil
import signal
import stat
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET

from limo_cleanup_ros1_base.map_binding import (
    build_runtime_preflight_lease,
    canonical_bytes,
    load_release_payloads,
    load_runtime_preflight_lease,
    validate_map_binding,
    validate_release_files,
    validate_runtime_preflight_lease,
)
from limo_cleanup_ros1_base.runtime_snapshot import (
    CONFIG_SHA256,
    LOAD_ORDER,
    create_navigation_snapshot,
    validate_interface_payload,
)


MAP_READY = 'V1_MAP_BINDING_MONITOR_READY'
MAP_HEARTBEAT = 'V1_MAP_BINDING_MONITOR_HEARTBEAT'
POST_CORE_READY = 'ROS1_NAV_TOPOLOGY_POST_CORE_READY'
FULL_TOPOLOGY_READY = 'ROS1_NAV_TOPOLOGY_FULL_READY'
TOPOLOGY_HEARTBEAT = 'ROS1_NAV_TOPOLOGY_HEARTBEAT'
PRIVATE_LIFETIME_SECONDS = 60.0
HEARTBEAT_TIMEOUT = 2.5
RUN_ID_ENV = 'LIMO_V2_BRIDGED_RUN_ID'
RUNNER_LOCK_PATH = '/tmp/limo_v2_bridged_navigation.runner.lock'
_SHUTDOWN_SIGNAL = None


class ShutdownRequested(RuntimeError):
    """Request fail-closed teardown from a process signal."""


class SingleRunnerLock:
    """Hold one host-wide navigation runner capability until cleanup ends."""

    def __init__(self, path=RUNNER_LOCK_PATH):
        self.path = path
        self.descriptor = None

    def __enter__(self):
        if os.name != 'posix' or not hasattr(os, 'O_NOFOLLOW'):
            raise RuntimeError('single-runner lock requires POSIX O_NOFOLLOW')
        flags = os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW
        descriptor = os.open(self.path, flags, 0o600)
        try:
            file_stat = os.fstat(descriptor)
            if (
                    not stat.S_ISREG(file_stat.st_mode)
                    or file_stat.st_uid != os.getuid()
                    or stat.S_IMODE(file_stat.st_mode) != 0o600):
                raise RuntimeError(
                    'single-runner lock must be owner-only regular file')
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise RuntimeError(
                    'another V2 bridged navigation runner owns the lock') \
                    from error
            os.ftruncate(descriptor, 0)
            os.write(descriptor, '{}\n'.format(os.getpid()).encode('ascii'))
            os.fsync(descriptor)
            self.descriptor = descriptor
            return self
        except Exception:
            os.close(descriptor)
            raise

    def __exit__(self, _error_type, _error, _traceback):
        if self.descriptor is not None:
            try:
                fcntl.flock(self.descriptor, fcntl.LOCK_UN)
            finally:
                os.close(self.descriptor)
                self.descriptor = None


def _preflight(binding):
    """PRE_CORE: external scan/odom/TF only; core/adapter must be absent."""
    command = [
        'roslaunch', 'limo_v1_navigation', 'v1_runtime_preflight.launch',
        'stage:=navigation_precore',
        'mode:=integrated',
        'cmd_vel_output_topic:=/cleanup/base/cmd_vel_request',
        'map_file:={}'.format(binding.map_file),
        'active_map_id:={}'.format(binding.active_map_id),
    ]
    completed = subprocess.run(
        command, capture_output=True, text=True, timeout=60, check=False)
    output = '{}\n{}'.format(completed.stdout, completed.stderr)
    if (
            completed.returncode != 0
            or 'V1_SCAN_ODOM_TF_PREFLIGHT_PASS' not in output):
        raise RuntimeError(
            'V1 navigation_precore preflight did not pass: {}'.format(output))
    topology = subprocess.run([
        'rosrun', 'limo_cleanup_ros1_base',
        'verify_ros1_base_bridge_topology.py',
        '_driver_expected:=true',
        '_navigation_phase:=pre_core',
        '_continuous:=false',
        '_monitor_role:=production',
        '__name:=/verify_ros1_base_bridge_topology',
    ], capture_output=True, text=True, timeout=15, check=False)
    topology_output = '{}\n{}'.format(topology.stdout, topology.stderr)
    if (
            topology.returncode != 0
            or 'ROS1_BASE_BRIDGE_TOPOLOGY_PASS' not in topology_output):
        raise RuntimeError(
            'PRE_CORE zero/topology proof did not pass: {}'.format(
                topology_output))
    ros2_zero = subprocess.run([
        'ros2', 'run', 'limo_cleanup_base',
        'zero_stage_handoff_verifier',
    ], capture_output=True, text=True, timeout=15, check=False)
    ros2_output = '{}\n{}'.format(ros2_zero.stdout, ros2_zero.stderr)
    if (
            ros2_zero.returncode != 0
            or 'ROS2_ZERO_STAGE_HANDOFF_PASS' not in ros2_output):
        raise RuntimeError(
            'PRE_CORE unique ROS2 controller/zero proof did not pass: '
            '{}'.format(ros2_output))


def _find_v1_release_root():
    return subprocess.check_output(
        ['rospack', 'find', 'limo_v1_navigation'],
        text=True,
        timeout=10,
    ).strip()


def _write_exclusive(path, payload, mode=0o600):
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if not hasattr(os, 'O_NOFOLLOW'):
        raise RuntimeError('O_NOFOLLOW is required for private runtime files')
    descriptor = os.open(str(path), flags | os.O_NOFOLLOW, mode)
    try:
        os.fchmod(descriptor, mode)
        offset = 0
        while offset < len(payload):
            offset += os.write(descriptor, payload[offset:])
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _create_private_run_dir():
    path = Path(tempfile.mkdtemp(prefix='limo_v2_bridged_navigation.'))
    path.chmod(0o700)
    return path


def _add_param(node, name, value):
    ET.SubElement(node, 'param', {'name': name, 'value': str(value)})


def _build_private_core_launch(binding, snapshot):
    """Generate the only integrated map_server+AMCL+move_base core."""
    root = ET.Element('launch')
    ET.SubElement(root, 'param', {
        'name': '/v1/active_map_id', 'value': binding.active_map_id})
    ET.SubElement(root, 'param', {
        'name': '/v1/navigation_mode', 'value': 'integrated'})
    ET.SubElement(root, 'param', {
        'name': '/v1/navigation_cmd_output',
        'value': '/cleanup/base/cmd_vel_request'})

    map_server = ET.SubElement(root, 'node', {
        'pkg': 'map_server', 'type': 'map_server', 'name': 'map_server',
        'args': snapshot.paths['map_yaml'], 'output': 'screen',
        'required': 'true'})
    _add_param(map_server, 'frame_id', 'map')

    amcl = ET.SubElement(root, 'node', {
        'pkg': 'amcl', 'type': 'amcl', 'name': 'amcl',
        'output': 'screen', 'required': 'true'})
    ET.SubElement(amcl, 'rosparam', {
        'file': snapshot.paths['amcl.yaml'], 'command': 'load'})

    move_base = ET.SubElement(root, 'node', {
        'pkg': 'move_base', 'type': 'move_base', 'name': 'move_base',
        'output': 'screen', 'required': 'true'})
    for config_name, namespace in LOAD_ORDER[1:]:
        attributes = {
            'file': snapshot.paths[config_name], 'command': 'load'}
        if namespace != '/move_base':
            attributes['ns'] = namespace.rsplit('/', 1)[-1]
        ET.SubElement(move_base, 'rosparam', attributes)
    _add_param(move_base, 'base_global_planner',
               'global_planner/GlobalPlanner')
    _add_param(move_base, 'base_local_planner',
               'base_local_planner/TrajectoryPlannerROS')
    ET.SubElement(move_base, 'remap', {
        'from': '/cmd_vel', 'to': '/cleanup/base/cmd_vel_request'})
    return ET.tostring(root, encoding='utf-8', xml_declaration=True)


def _build_private_adapter_launch(
        binding, binding_file, map_root, v1_release_root, lease_path, lease):
    root = ET.Element('launch')
    adapter = ET.SubElement(root, 'include', {
        'file': '$(find limo_cleanup_ros1_base)/launch/'
                'navigation_bridge_adapter.launch'})
    for name, value in (
            ('enable_navigation_bridge', 'true'),
            ('binding_file', binding_file),
            ('binding_sha256', binding.binding_sha256),
            ('binding_token', binding.token),
            ('map_root', map_root),
            ('v1_release_root', v1_release_root),
            ('runtime_lease_file', lease_path),
            ('runtime_lease_sha256', lease['lease_sha256']),
            ('runtime_token', lease['runtime_token'])):
        ET.SubElement(adapter, 'arg', {'name': name, 'value': str(value)})
    return ET.tostring(root, encoding='utf-8', xml_declaration=True)


def _snapshot_manifest(snapshot):
    return json.dumps({
        name: {'path': snapshot.paths[name], 'sha256': snapshot.sha256[name]}
        for name in sorted(snapshot.paths)
    }, sort_keys=True, separators=(',', ':'))


def _map_monitor_command(
        binding, binding_file, map_root, v1_release_root, lease_path, lease,
        snapshot, ready_fd):
    return [
        'rosrun', 'limo_cleanup_ros1_base',
        'verify_v1_map_binding_runtime.py',
        '_binding_file:={}'.format(binding_file),
        '_binding_sha256:={}'.format(binding.binding_sha256),
        '_binding_token:={}'.format(binding.token),
        '_map_root:={}'.format(map_root),
        '_v1_release_root:={}'.format(v1_release_root),
        '_runtime_lease_file:={}'.format(lease_path),
        '_runtime_lease_sha256:={}'.format(lease['lease_sha256']),
        '_runtime_token:={}'.format(lease['runtime_token']),
        '_expected_source_map_file:={}'.format(binding.map_file),
        '_expected_active_map_id:={}'.format(binding.active_map_id),
        '_snapshot_manifest:={}'.format(_snapshot_manifest(snapshot)),
        '_snapshot_runner_pid:={}'.format(os.getpid()),
        '_ready_fd:={}'.format(ready_fd),
    ]


def _topology_monitor_command(ready_fd, digest):
    return [
        'rosrun', 'limo_cleanup_ros1_base',
        'verify_ros1_base_bridge_topology.py',
        '_driver_expected:=true',
        '_navigation_phase:=post_core',
        '_bootstrap_then_full:=true',
        '_continuous:=true',
        '_monitor_role:=production',
        '__name:=/verify_ros1_base_bridge_topology',
        '_ready_fd:={}'.format(ready_fd),
        '_ready_digest:={}'.format(digest),
        '_full_topology_timeout:=10.0',
    ]


def _set_parent_death_signal():
    if os.name != 'posix':
        return
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), 'PR_SET_PDEATHSIG failed')


def _spawn_process(command, run_id, pass_fds=()):
    environment = os.environ.copy()
    environment[RUN_ID_ENV] = run_id
    return subprocess.Popen(
        command,
        pass_fds=tuple(pass_fds),
        start_new_session=True,
        preexec_fn=_set_parent_death_signal if os.name == 'posix' else None,
        env=environment,
    )


class PrivatePipe:
    """Validate digest-bound monotonic READY/heartbeat records."""

    def __init__(self, descriptor, digest):
        self.descriptor = descriptor
        self.digest = digest
        self.buffer = b''
        self.sequence = -1
        self.last_received = time.monotonic()

    def _drain(self, timeout):
        readable, _, _ = select.select([self.descriptor], [], [], timeout)
        if not readable:
            return []
        chunk = os.read(self.descriptor, 4096)
        if not chunk:
            raise RuntimeError('private monitor heartbeat pipe closed')
        self.buffer += chunk
        lines = []
        while b'\n' in self.buffer:
            raw, self.buffer = self.buffer.split(b'\n', 1)
            try:
                label, digest, sequence_text = raw.decode('ascii').split(':')
                sequence = int(sequence_text)
            except (UnicodeDecodeError, ValueError) as error:
                raise RuntimeError('private monitor record is malformed') from error
            if digest != self.digest or sequence <= self.sequence:
                raise RuntimeError('private monitor digest/sequence is invalid')
            self.sequence = sequence
            self.last_received = time.monotonic()
            lines.append(label)
        return lines

    def wait_for(
            self, process, label, timeout=10.0,
            allowed_intermediate=(), allowed_following=()):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(
                    'monitor exited before private {} handshake'.format(label))
            labels = self._drain(min(0.1, deadline - time.monotonic()))
            target_count = labels.count(label)
            if target_count > 1:
                raise RuntimeError(
                    'private monitor emitted duplicate {} handshake'.format(
                        label))
            # Validate the entire drained batch before accepting READY.  This
            # prevents a trailing unknown/wrong record already removed from
            # the FD from being discarded by an early return.
            if target_count == 1:
                target_index = labels.index(label)
                leading = labels[:target_index]
                trailing = labels[target_index + 1:]
                unexpected_leading = [
                    received_label for received_label in leading
                    if received_label not in set(allowed_intermediate)]
                unexpected_trailing = [
                    received_label for received_label in trailing
                    if received_label not in set(allowed_following)]
                if unexpected_leading or unexpected_trailing:
                    raise RuntimeError(
                        'unexpected private monitor labels before={} after={} '
                        'while waiting for {}'.format(
                            unexpected_leading, unexpected_trailing, label))
                return
            unexpected = [
                received_label for received_label in labels
                if received_label not in set(allowed_intermediate)]
            if unexpected:
                raise RuntimeError(
                    'unexpected private monitor labels {} while waiting '
                    'for {}'.format(unexpected, label))
        raise RuntimeError('private {} handshake timed out'.format(label))

    def require_fresh(self, expected_heartbeat):
        labels = self._drain(0.0)
        unexpected = [
            label for label in labels
            if label not in {expected_heartbeat}]
        if unexpected:
            raise RuntimeError(
                'unexpected monitor heartbeat labels: {}'.format(unexpected))
        if time.monotonic() - self.last_received >= HEARTBEAT_TIMEOUT:
            raise RuntimeError('{} heartbeat became stale'.format(
                expected_heartbeat))


def _run_marker_pids(run_id):
    if os.name != 'posix' or not Path('/proc').is_dir():
        return []
    marker = '{}={}'.format(RUN_ID_ENV, run_id).encode('ascii')
    matches = []
    for entry in Path('/proc').iterdir():
        if not entry.name.isdigit() or int(entry.name) == os.getpid():
            continue
        try:
            fields = (entry / 'environ').read_bytes().split(b'\0')
        except (OSError, PermissionError):
            continue
        if marker in fields:
            matches.append(int(entry.name))
    return matches


def _stop_process_group(process, run_id=None):
    failures = []
    if process is not None and process.poll() is None:
        group_id = None
        try:
            group_id = os.getpgid(process.pid)
            os.killpg(group_id, signal.SIGTERM)
            process.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            try:
                if group_id is not None:
                    os.killpg(group_id, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=5.0)
            except subprocess.TimeoutExpired as error:
                failures.append(
                    'direct child did not reap after SIGKILL: {}'.format(
                        error))
        except ProcessLookupError:
            try:
                process.wait(timeout=1.0)
            except subprocess.TimeoutExpired as error:
                failures.append(
                    'direct child did not reap after group disappeared: '
                    '{}'.format(error))
        except OSError as error:
            failures.append('process-group cleanup failed: {}'.format(error))
    if run_id:
        for signal_value in (signal.SIGTERM, signal.SIGKILL):
            survivors = _run_marker_pids(run_id)
            if not survivors:
                break
            for pid in survivors:
                try:
                    os.kill(pid, signal_value)
                except ProcessLookupError:
                    pass
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline and _run_marker_pids(run_id):
                time.sleep(0.05)
        survivors = _run_marker_pids(run_id)
        if survivors:
            failures.append(
                'managed descendant processes survived cleanup: {}'.format(
                    survivors))
    _reap_children()
    if failures:
        raise RuntimeError('; '.join(failures))


def _enable_child_subreaper():
    if os.name != 'posix':
        raise RuntimeError('process containment requires POSIX')
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(36, 1, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), 'PR_SET_CHILD_SUBREAPER failed')


def _reap_children():
    if os.name != 'posix':
        return
    while True:
        try:
            pid, _status = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            return
        if pid <= 0:
            return


def _install_signal_handlers():
    def request_shutdown(signum, _frame):
        global _SHUTDOWN_SIGNAL
        if _SHUTDOWN_SIGNAL is not None:
            return
        _SHUTDOWN_SIGNAL = signum
        # A repeated TERM/INT must not interrupt the cleanup triggered below.
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        raise ShutdownRequested('runner received signal {}'.format(signum))

    signal.signal(signal.SIGTERM, request_shutdown)
    signal.signal(signal.SIGINT, request_shutdown)


def _validate_boundary(
        binding_args, expected_binding, v1_release_root, expected_release,
        expected_payloads, lease_path, lease, snapshot):
    current_binding = validate_map_binding(*binding_args)
    current_release = validate_release_files(v1_release_root)
    current_payloads = load_release_payloads(v1_release_root)
    if (
            current_binding != expected_binding
            or current_release != expected_release
            or current_payloads != expected_payloads):
        raise RuntimeError('binding or V1 release drifted at spawn boundary')
    loaded_lease = load_runtime_preflight_lease(lease_path)
    validate_runtime_preflight_lease(
        loaded_lease, expected_binding, lease['lease_sha256'],
        lease['runtime_token'], time.monotonic())
    snapshot.validate()


def _supervise(monitors, processes, pipes, sleep=time.sleep):
    while True:
        for label, monitor in monitors.items():
            if monitor.poll() is not None:
                raise RuntimeError('{} monitor faulted'.format(label))
        for label, process in processes.items():
            status = process.poll()
            if status is not None:
                raise RuntimeError(
                    '{} process exited unexpectedly: {}'.format(label, status))
        pipes['map'].require_fresh(MAP_HEARTBEAT)
        pipes['topology'].require_fresh(TOPOLOGY_HEARTBEAT)
        sleep(0.05)


def _execute(arguments):
    binding_args = (
        arguments.binding_file,
        arguments.binding_sha256,
        arguments.binding_token,
        arguments.map_root,
    )
    initial_binding = validate_map_binding(*binding_args)
    v1_release_root = _find_v1_release_root()
    initial_release = validate_release_files(v1_release_root)
    initial_payloads = load_release_payloads(v1_release_root)
    validate_interface_payload(
        initial_payloads['v1_navigation_interface.json'])
    _preflight(initial_binding)

    final_binding = validate_map_binding(*binding_args)
    final_release = validate_release_files(v1_release_root)
    final_payloads = load_release_payloads(v1_release_root)
    if (
            final_binding != initial_binding
            or final_release != initial_release
            or final_payloads != initial_payloads):
        raise RuntimeError('binding or V1 release drifted during PRE_CORE')

    private_dir = _create_private_run_dir()
    snapshot = None
    map_monitor = topology_monitor = None
    core = adapter = ros2_navigation = None
    map_read_fd = map_write_fd = None
    topology_read_fd = topology_write_fd = None
    run_id = secrets.token_hex(32)
    try:
        snapshot = create_navigation_snapshot(
            final_binding, arguments.map_root, final_payloads)
        lease = build_runtime_preflight_lease(
            final_binding, secrets.token_hex(32), time.monotonic(),
            PRIVATE_LIFETIME_SECONDS)
        lease_path = private_dir / 'runtime_lease.json'
        _write_exclusive(lease_path, canonical_bytes(lease))
        _validate_boundary(
            binding_args, final_binding, v1_release_root, final_release,
            final_payloads, lease_path, lease, snapshot)

        map_read_fd, map_write_fd = os.pipe()
        map_monitor = _spawn_process(
            _map_monitor_command(
                final_binding,
                str(Path(arguments.binding_file).resolve()),
                str(Path(arguments.map_root).resolve()),
                v1_release_root,
                str(lease_path),
                lease,
                snapshot,
                map_write_fd),
            run_id,
            pass_fds=(map_write_fd,))
        os.close(map_write_fd)
        map_write_fd = None
        map_pipe = PrivatePipe(map_read_fd, final_binding.binding_sha256)
        map_pipe.wait_for(
            map_monitor, MAP_READY,
            allowed_following=(MAP_HEARTBEAT,))

        _validate_boundary(
            binding_args, final_binding, v1_release_root, final_release,
            final_payloads, lease_path, lease, snapshot)
        core_path = private_dir / 'sealed_integrated_core.launch'
        _write_exclusive(
            core_path, _build_private_core_launch(final_binding, snapshot))
        core = _spawn_process(['roslaunch', str(core_path)], run_id)

        topology_read_fd, topology_write_fd = os.pipe()
        _validate_boundary(
            binding_args, final_binding, v1_release_root, final_release,
            final_payloads, lease_path, lease, snapshot)
        topology_monitor = _spawn_process(
            _topology_monitor_command(
                topology_write_fd, final_binding.binding_sha256),
            run_id,
            pass_fds=(topology_write_fd,))
        os.close(topology_write_fd)
        topology_write_fd = None
        topology_pipe = PrivatePipe(
            topology_read_fd, final_binding.binding_sha256)
        topology_pipe.wait_for(
            topology_monitor, POST_CORE_READY, timeout=15.0)

        _validate_boundary(
            binding_args, final_binding, v1_release_root, final_release,
            final_payloads, lease_path, lease, snapshot)
        adapter_path = private_dir / 'validated_adapter.launch'
        _write_exclusive(adapter_path, _build_private_adapter_launch(
            final_binding,
            str(Path(arguments.binding_file).resolve()),
            str(Path(arguments.map_root).resolve()),
            v1_release_root,
            str(lease_path),
            lease))
        adapter = _spawn_process(['roslaunch', str(adapter_path)], run_id)
        _validate_boundary(
            binding_args, final_binding, v1_release_root, final_release,
            final_payloads, lease_path, lease, snapshot)
        ros2_navigation = _spawn_process([
            'ros2', 'launch', 'limo_cleanup_base',
            'navigation_intent_bridge.launch.py',
            'enable_navigation_intent_bridge:=true',
            'waypoint_file:={}'.format(arguments.waypoint_file),
            'active_v1_map_id:={}'.format(final_binding.active_map_id),
            'epoch_state_file:={}'.format(arguments.epoch_state_file),
            'voice_expected:={}'.format(
                'true' if arguments.voice_expected else 'false'),
        ], run_id)
        topology_pipe.wait_for(
            topology_monitor, FULL_TOPOLOGY_READY, timeout=15.0,
            allowed_intermediate=(TOPOLOGY_HEARTBEAT,),
            allowed_following=(TOPOLOGY_HEARTBEAT,))
        _validate_boundary(
            binding_args, final_binding, v1_release_root, final_release,
            final_payloads, lease_path, lease, snapshot)
        return _supervise(
            {'map': map_monitor, 'topology': topology_monitor},
            {'core': core, 'adapter': adapter, 'ros2_navigation': ros2_navigation},
            {'map': map_pipe, 'topology': topology_pipe})
    finally:
        for descriptor in (
                map_write_fd, map_read_fd,
                topology_write_fd, topology_read_fd):
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
        # Stop every possible goal producer before the core.  The external
        # watchdog/zero safety chain is deliberately not owned or removed here.
        cleanup_failures = []
        for process in (ros2_navigation, adapter, core,
                        topology_monitor, map_monitor):
            try:
                _stop_process_group(process)
            except Exception as error:
                cleanup_failures.append(str(error))
        try:
            _stop_process_group(None, run_id)
        except Exception as error:
            cleanup_failures.append(str(error))
        if snapshot is not None:
            try:
                snapshot.close()
            except Exception as error:
                cleanup_failures.append(str(error))
        shutil.rmtree(str(private_dir), ignore_errors=True)
        if cleanup_failures:
            raise RuntimeError(
                'navigation cleanup incomplete: {}'.format(
                    '; '.join(cleanup_failures)))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--binding-file', required=True)
    parser.add_argument('--binding-sha256', required=True)
    parser.add_argument('--binding-token', required=True)
    parser.add_argument('--map-root', required=True)
    parser.add_argument('--waypoint-file', required=True)
    parser.add_argument('--epoch-state-file', required=True)
    parser.add_argument('--voice-expected', action='store_true', default=False)
    arguments = parser.parse_args()
    try:
        _enable_child_subreaper()
        _install_signal_handlers()
        with SingleRunnerLock():
            return _execute(arguments)
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        print('V2_BRIDGED_NAVIGATION_BLOCKED: {}'.format(error))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

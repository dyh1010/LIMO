import importlib.util
import multiprocessing
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace
import xml.etree.ElementTree as ET

import pytest


PACKAGE_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / 'src'))
RUNNER_PATH = PACKAGE_ROOT / 'scripts' / 'run_v2_bridged_navigation.py'
SPEC = importlib.util.spec_from_file_location('v2_runner', RUNNER_PATH)
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)

from limo_cleanup_ros1_base.map_binding import ValidatedMapBinding  # noqa: E402
from limo_cleanup_ros1_base.runtime_snapshot import (  # noqa: E402
    CONFIG_SHA256,
    create_navigation_snapshot,
)


class FakeProcess:
    def __init__(self, label='process', status=None, pid=43210):
        self.label = label
        self.status = status
        self.pid = pid

    def poll(self):
        return self.status

    def wait(self, timeout=None):
        return self.status


class FakeSnapshot:
    def __init__(self, events):
        self.events = events
        names = {'map_yaml', 'map_image', *CONFIG_SHA256}
        self.paths = {name: '/proc/1/fd/{}'.format(index + 10)
                      for index, name in enumerate(sorted(names))}
        self.sha256 = {name: str(index).zfill(64)
                       for index, name in enumerate(sorted(names))}

    def validate(self):
        self.events.append('snapshot_validate')
        return True

    def close(self):
        self.events.append('snapshot_close')


def _binding(tmp_path):
    return ValidatedMapBinding(
        binding_sha256='1' * 64,
        token='V1_MAP_BINDING_PASS_V1:' + '1' * 64,
        active_map_id='frozen_test_map',
        map_file=str(tmp_path / 'frozen_test_map.yaml'),
        map_image=str(tmp_path / 'frozen_test_map.pgm'),
        map_yaml_size=100,
        map_yaml_sha256='2' * 64,
        map_image_size=200,
        map_image_sha256='3' * 64,
    )


def _arguments(tmp_path):
    return SimpleNamespace(
        binding_file=str(tmp_path / 'binding.json'),
        binding_sha256='1' * 64,
        binding_token='V1_MAP_BINDING_PASS_V1:' + '1' * 64,
        map_root=str(tmp_path),
        waypoint_file=str(tmp_path / 'waypoints.yaml'),
        epoch_state_file=str(tmp_path / 'epoch'),
        voice_expected=False,
    )


def _hold_runner_lock(path, ready, release):
    with RUNNER.SingleRunnerLock(path):
        ready.set()
        release.wait(timeout=5.0)


def _try_runner_lock(path, result):
    try:
        with RUNNER.SingleRunnerLock(path):
            result.put('acquired')
    except RuntimeError:
        result.put('blocked')


def _patch_execute(monkeypatch, tmp_path, events, failure=None):
    binding = _binding(tmp_path)
    payloads = {'v1_navigation_interface.json': b'interface'}
    payloads.update({name: name.encode('ascii') for name in CONFIG_SHA256})
    monkeypatch.setattr(RUNNER, 'validate_map_binding', lambda *_: binding)
    monkeypatch.setattr(RUNNER, '_find_v1_release_root', lambda: '/v1')
    monkeypatch.setattr(RUNNER, 'validate_release_files', lambda *_: {'ok': '1'})
    monkeypatch.setattr(RUNNER, 'load_release_payloads', lambda *_: payloads)
    monkeypatch.setattr(RUNNER, 'validate_interface_payload', lambda *_: {})

    def preflight(_binding_value):
        events.append('pre_core')
        if failure == 'pre_core':
            raise RuntimeError('PRE_CORE failed')

    monkeypatch.setattr(RUNNER, '_preflight', preflight)
    private_dir = tmp_path / 'private'

    def private():
        private_dir.mkdir()
        events.append('private_dir')
        return private_dir

    monkeypatch.setattr(RUNNER, '_create_private_run_dir', private)
    monkeypatch.setattr(
        RUNNER, 'create_navigation_snapshot',
        lambda *_: events.append('snapshot_create') or FakeSnapshot(events))

    boundary_count = {'value': 0}

    def boundary(*_args):
        boundary_count['value'] += 1
        events.append('boundary{}'.format(boundary_count['value']))
        if failure == 'boundary{}'.format(boundary_count['value']):
            raise RuntimeError('boundary failed')

    monkeypatch.setattr(RUNNER, '_validate_boundary', boundary)
    spawn_counts = {'core': 0, 'adapter': 0, 'ros2': 0}

    def spawn(command, _run_id, pass_fds=()):
        text = ' '.join(command)
        if 'verify_v1_map_binding_runtime.py' in text:
            label = 'map_monitor'
        elif 'verify_ros1_base_bridge_topology.py' in text:
            label = 'topology_monitor'
        elif 'sealed_integrated_core.launch' in text:
            label = 'core'
            spawn_counts['core'] += 1
        elif 'validated_adapter.launch' in text:
            label = 'adapter'
            spawn_counts['adapter'] += 1
        elif command[:2] == ['ros2', 'launch']:
            label = 'ros2'
            spawn_counts['ros2'] += 1
        else:
            raise AssertionError(command)
        events.append('spawn_' + label)
        return FakeProcess(label=label, pid=44000 + len(events))

    monkeypatch.setattr(RUNNER, '_spawn_process', spawn)

    class FakePipe:
        def __init__(self, _descriptor, _digest):
            pass

        def wait_for(
                self, _process, label, timeout=10.0,
                allowed_intermediate=(), allowed_following=()):
            events.append('wait_' + label)
            if failure == label:
                raise RuntimeError('{} failed'.format(label))

        def require_fresh(self, _label):
            pass

    monkeypatch.setattr(RUNNER, 'PrivatePipe', FakePipe)
    monkeypatch.setattr(
        RUNNER, '_supervise',
        lambda *_args: events.append('supervise') or 0)
    stopped = []
    monkeypatch.setattr(
        RUNNER, '_stop_process_group',
        lambda process, run_id=None: stopped.append(
            None if process is None else process.label))
    return spawn_counts, stopped


def test_staged_runner_orders_precore_core_postcore_adapter_and_full_ready(
        monkeypatch, tmp_path):
    events = []
    counts, _stopped = _patch_execute(monkeypatch, tmp_path, events)
    assert RUNNER._execute(_arguments(tmp_path)) == 0
    assert counts == {'core': 1, 'adapter': 1, 'ros2': 1}
    assert events.index('pre_core') < events.index('snapshot_create')
    assert events.index('boundary1') < events.index('spawn_map_monitor')
    assert events.index('wait_' + RUNNER.MAP_READY) < events.index('spawn_core')
    assert events.index('boundary3') < events.index('spawn_topology_monitor')
    assert events.index('spawn_core') < events.index('spawn_topology_monitor')
    assert events.index('wait_' + RUNNER.POST_CORE_READY) < events.index(
        'spawn_adapter')
    assert events.index('spawn_adapter') < events.index(
        'wait_' + RUNNER.FULL_TOPOLOGY_READY)
    assert events.index('boundary5') < events.index('spawn_ros2')
    assert events.index('wait_' + RUNNER.FULL_TOPOLOGY_READY) < events.index(
        'supervise')


@pytest.mark.parametrize('failure', [
    'pre_core', 'boundary1', RUNNER.MAP_READY,
])
def test_every_pre_core_ready_failure_spawns_zero_core(
        monkeypatch, tmp_path, failure):
    events = []
    counts, _stopped = _patch_execute(
        monkeypatch, tmp_path, events, failure=failure)
    with pytest.raises(RuntimeError):
        RUNNER._execute(_arguments(tmp_path))
    assert counts['core'] == 0
    assert counts['adapter'] == 0


def test_post_core_failure_never_spawns_adapter_and_cleans_core(
        monkeypatch, tmp_path):
    events = []
    counts, stopped = _patch_execute(
        monkeypatch, tmp_path, events, failure=RUNNER.POST_CORE_READY)
    with pytest.raises(RuntimeError):
        RUNNER._execute(_arguments(tmp_path))
    assert counts == {'core': 1, 'adapter': 0, 'ros2': 0}
    assert 'core' in stopped


def test_preflight_passes_mandatory_map_identity(monkeypatch, tmp_path):
    commands = []

    def run(command, **_kwargs):
        commands.append(command)
        if command[0] == 'roslaunch':
            token = 'V1_SCAN_ODOM_TF_PREFLIGHT_PASS'
        elif command[0] == 'rosrun':
            token = 'ROS1_BASE_BRIDGE_TOPOLOGY_PASS'
        else:
            token = 'ROS2_ZERO_STAGE_HANDOFF_PASS'
        return SimpleNamespace(returncode=0, stdout=token, stderr='')

    monkeypatch.setattr(RUNNER.subprocess, 'run', run)
    binding = _binding(tmp_path)
    RUNNER._preflight(binding)
    assert 'map_file:={}'.format(binding.map_file) in commands[0]
    assert 'active_map_id:={}'.format(binding.active_map_id) in commands[0]
    assert commands[2] == [
        'ros2', 'run', 'limo_cleanup_base',
        'zero_stage_handoff_verifier',
    ]
    assert '_monitor_role:=production' in commands[1]
    assert '__name:=/verify_ros1_base_bridge_topology' in commands[1]

    topology_command = RUNNER._topology_monitor_command(17, '1' * 64)
    assert topology_command.count('verify_ros1_base_bridge_topology.py') == 1
    assert '_monitor_role:=production' in topology_command
    assert '__name:=/verify_ros1_base_bridge_topology' in topology_command

    ros2_package = PACKAGE_ROOT.parents[1] / 'src' / 'limo_cleanup_base'
    package_verifier = (
        ros2_package / 'limo_cleanup_base' /
        'zero_stage_handoff_verifier.py')
    setup_source = (ros2_package / 'setup.py').read_text(encoding='utf-8')
    cmake = (PACKAGE_ROOT / 'CMakeLists.txt').read_text(encoding='utf-8')
    runner_source = RUNNER_PATH.read_text(encoding='utf-8')
    rollback = (
        PACKAGE_ROOT / 'docs' /
        'V1_INTEGRATED_VERIFIER_INSTALL_ROLLBACK.md').read_text(
            encoding='utf-8')
    assert package_verifier.is_file()
    assert 'zero_stage_handoff_verifier = ' in setup_source
    assert (
        'limo_cleanup_base.zero_stage_handoff_verifier:main'
        in setup_source)
    assert 'zero_stage_handoff_verifier' not in cmake
    assert '_workspace_script' not in runner_source
    assert "Path(__file__).resolve().parents[3] / 'scripts'" not in runner_source
    assert 'Keep integrated navigation BLOCKED' in rollback
    assert 'Do not kill\n   an unknown process' in rollback

    def missing_install(command, **_kwargs):
        commands.append(command)
        if command[0] == 'roslaunch':
            token = 'V1_SCAN_ODOM_TF_PREFLIGHT_PASS'
            return SimpleNamespace(returncode=0, stdout=token, stderr='')
        if command[:3] == [
                'rosrun', 'limo_cleanup_ros1_base',
                'verify_ros1_base_bridge_topology.py']:
            token = 'ROS1_BASE_BRIDGE_TOPOLOGY_PASS'
            return SimpleNamespace(returncode=0, stdout=token, stderr='')
        assert command == [
            'ros2', 'run', 'limo_cleanup_base',
            'zero_stage_handoff_verifier',
        ]
        return SimpleNamespace(
            returncode=1, stdout='',
            stderr='Package not found')

    monkeypatch.setattr(RUNNER.subprocess, 'run', missing_install)
    with pytest.raises(RuntimeError, match='unique ROS2 controller'):
        RUNNER._preflight(binding)

    def execution_failed(command, **_kwargs):
        if command[0] == 'roslaunch':
            token = 'V1_SCAN_ODOM_TF_PREFLIGHT_PASS'
        elif command[0] == 'rosrun':
            token = 'ROS1_BASE_BRIDGE_TOPOLOGY_PASS'
        else:
            assert command == [
                'ros2', 'run', 'limo_cleanup_base',
                'zero_stage_handoff_verifier',
            ]
            return SimpleNamespace(
                returncode=0, stdout='ROS2_ZERO_STAGE_HANDOFF_BLOCKED',
                stderr='')
        return SimpleNamespace(returncode=0, stdout=token, stderr='')

    monkeypatch.setattr(RUNNER.subprocess, 'run', execution_failed)
    with pytest.raises(RuntimeError, match='unique ROS2 controller'):
        RUNNER._preflight(binding)


def test_private_pipe_rejects_unknown_ready_label():
    read_fd, write_fd = os.pipe()
    try:
        os.write(write_fd, (
            'UNKNOWN_READY:{}:0\n{}:{}:1\n'.format(
                '1' * 64, RUNNER.MAP_READY, '1' * 64)).encode('ascii'))
        pipe = RUNNER.PrivatePipe(read_fd, '1' * 64)
        with pytest.raises(RuntimeError, match='unexpected private monitor'):
            pipe.wait_for(FakeProcess(), RUNNER.MAP_READY, timeout=0.2)
    finally:
        os.close(read_fd)
        os.close(write_fd)


@pytest.mark.parametrize('trailing_label', [
    'UNKNOWN_READY', RUNNER.POST_CORE_READY,
])
def test_private_pipe_rejects_expected_then_unknown_or_wrong_ready(
        trailing_label):
    read_fd, write_fd = os.pipe()
    try:
        os.write(write_fd, (
            '{}:{}:0\n{}:{}:1\n'.format(
                RUNNER.MAP_READY, '1' * 64,
                trailing_label, '1' * 64)).encode('ascii'))
        pipe = RUNNER.PrivatePipe(read_fd, '1' * 64)
        with pytest.raises(RuntimeError, match='unexpected private monitor'):
            pipe.wait_for(FakeProcess(), RUNNER.MAP_READY, timeout=0.2)
    finally:
        os.close(read_fd)
        os.close(write_fd)


def test_private_pipe_rejects_duplicate_expected_ready_in_same_batch():
    read_fd, write_fd = os.pipe()
    try:
        os.write(write_fd, (
            '{}:{}:0\n{}:{}:1\n'.format(
                RUNNER.MAP_READY, '1' * 64,
                RUNNER.MAP_READY, '1' * 64)).encode('ascii'))
        pipe = RUNNER.PrivatePipe(read_fd, '1' * 64)
        with pytest.raises(RuntimeError, match='duplicate'):
            pipe.wait_for(FakeProcess(), RUNNER.MAP_READY, timeout=0.2)
    finally:
        os.close(read_fd)
        os.close(write_fd)


def test_private_pipe_accepts_allowed_heartbeat_then_full_ready_same_batch():
    read_fd, write_fd = os.pipe()
    try:
        os.write(write_fd, (
            '{}:{}:0\n{}:{}:1\n'.format(
                RUNNER.TOPOLOGY_HEARTBEAT, '1' * 64,
                RUNNER.FULL_TOPOLOGY_READY, '1' * 64)).encode('ascii'))
        pipe = RUNNER.PrivatePipe(read_fd, '1' * 64)
        pipe.wait_for(
            FakeProcess(), RUNNER.FULL_TOPOLOGY_READY, timeout=0.2,
            allowed_intermediate=(RUNNER.TOPOLOGY_HEARTBEAT,))
    finally:
        os.close(read_fd)
        os.close(write_fd)


@pytest.mark.parametrize('ready,heartbeat', [
    (RUNNER.MAP_READY, RUNNER.MAP_HEARTBEAT),
    (RUNNER.FULL_TOPOLOGY_READY, RUNNER.TOPOLOGY_HEARTBEAT),
])
def test_private_pipe_accepts_same_stage_heartbeat_after_ready_from_two_writes(
        monkeypatch, ready, heartbeat):
    read_fd, write_fd = os.pipe()
    try:
        os.write(write_fd, '{}:{}:0\n'.format(
            ready, '1' * 64).encode('ascii'))
        os.write(write_fd, '{}:{}:1\n'.format(
            heartbeat, '1' * 64).encode('ascii'))
        original_read = os.read
        read_calls = []

        def counted_read(descriptor, size):
            read_calls.append((descriptor, size))
            return original_read(descriptor, size)

        monkeypatch.setattr(RUNNER.os, 'read', counted_read)
        pipe = RUNNER.PrivatePipe(read_fd, '1' * 64)
        pipe.wait_for(
            FakeProcess(), ready, timeout=0.2,
            allowed_following=(heartbeat,))
        assert read_calls == [(read_fd, 4096)]
        assert pipe.sequence == 1
        assert pipe.buffer == b''
    finally:
        os.close(read_fd)
        os.close(write_fd)


@pytest.mark.parametrize('ready,allowed_heartbeat,wrong_heartbeat', [
    (RUNNER.MAP_READY, RUNNER.MAP_HEARTBEAT,
     RUNNER.TOPOLOGY_HEARTBEAT),
    (RUNNER.FULL_TOPOLOGY_READY, RUNNER.TOPOLOGY_HEARTBEAT,
     RUNNER.MAP_HEARTBEAT),
])
def test_private_pipe_rejects_wrong_stage_heartbeat_after_ready_from_two_writes(
        monkeypatch, ready, allowed_heartbeat, wrong_heartbeat):
    read_fd, write_fd = os.pipe()
    try:
        os.write(write_fd, '{}:{}:0\n'.format(
            ready, '1' * 64).encode('ascii'))
        os.write(write_fd, '{}:{}:1\n'.format(
            wrong_heartbeat, '1' * 64).encode('ascii'))
        original_read = os.read
        read_calls = []

        def counted_read(descriptor, size):
            read_calls.append((descriptor, size))
            return original_read(descriptor, size)

        monkeypatch.setattr(RUNNER.os, 'read', counted_read)
        pipe = RUNNER.PrivatePipe(read_fd, '1' * 64)
        with pytest.raises(RuntimeError, match='unexpected private monitor'):
            pipe.wait_for(
                FakeProcess(), ready, timeout=0.2,
                allowed_following=(allowed_heartbeat,))
        assert read_calls == [(read_fd, 4096)]
        assert pipe.sequence == 1
        assert pipe.buffer == b''
    finally:
        os.close(read_fd)
        os.close(write_fd)


@pytest.mark.skipif(os.name != 'posix', reason='flock requires POSIX')
def test_single_runner_lock_blocks_second_owner_before_work(tmp_path):
    path = str(tmp_path / 'runner.lock')
    with RUNNER.SingleRunnerLock(path):
        with pytest.raises(RuntimeError, match='another V2'):
            with RUNNER.SingleRunnerLock(path):
                raise AssertionError('second owner entered critical section')


@pytest.mark.skipif(os.name != 'posix', reason='flock requires POSIX')
def test_single_runner_lock_blocks_a_second_process(tmp_path):
    context = multiprocessing.get_context('fork')
    ready = context.Event()
    release = context.Event()
    result = context.Queue()
    path = str(tmp_path / 'cross_process.lock')
    owner = context.Process(
        target=_hold_runner_lock, args=(path, ready, release))
    owner.start()
    assert ready.wait(timeout=2.0)
    contender = context.Process(target=_try_runner_lock, args=(path, result))
    contender.start()
    contender.join(timeout=2.0)
    assert contender.exitcode == 0
    assert result.get(timeout=1.0) == 'blocked'
    release.set()
    owner.join(timeout=2.0)
    assert owner.exitcode == 0


def test_second_wait_timeout_is_reported_after_descendant_sweep(monkeypatch):
    class DoubleTimeoutProcess(FakeProcess):
        def poll(self):
            return None

        def wait(self, timeout=None):
            raise subprocess.TimeoutExpired('fixture', timeout)

    signals = []
    sweeps = []
    monkeypatch.setattr(RUNNER.os, 'getpgid', lambda _pid: 99)
    monkeypatch.setattr(
        RUNNER.os, 'killpg', lambda _group, value: signals.append(value))
    monkeypatch.setattr(
        RUNNER, '_run_marker_pids',
        lambda _run_id: sweeps.append('sweep') or [])
    monkeypatch.setattr(RUNNER, '_reap_children', lambda: sweeps.append('reap'))
    with pytest.raises(RuntimeError, match='did not reap after SIGKILL'):
        RUNNER._stop_process_group(DoubleTimeoutProcess(), 'run')
    assert signals == [RUNNER.signal.SIGTERM, RUNNER.signal.SIGKILL]
    assert 'sweep' in sweeps and 'reap' in sweeps


def test_private_integrated_core_has_no_installed_include_and_exact_nodes(tmp_path):
    snapshot = FakeSnapshot([])
    root = ET.fromstring(RUNNER._build_private_core_launch(
        _binding(tmp_path), snapshot))
    assert root.findall('.//include') == []
    for node_name in ('map_server', 'amcl', 'move_base'):
        assert len(root.findall(".//node[@name='{}']".format(node_name))) == 1
    assert root.findall(".//node[@name='v1_cmd_guard']") == []
    move_base = root.find(".//node[@name='move_base']")
    loads = [(item.attrib['file'], item.attrib.get('ns', '/move_base'))
             for item in move_base.findall('rosparam')]
    expected = []
    for name, namespace in RUNNER.LOAD_ORDER[1:]:
        expected.append((
            snapshot.paths[name],
            namespace.rsplit('/', 1)[-1]
            if namespace != '/move_base' else '/move_base'))
    assert loads == expected
    remap = move_base.find('remap')
    assert remap.attrib == {
        'from': '/cmd_vel', 'to': '/cleanup/base/cmd_vel_request'}


def test_installed_v1_launches_are_native_only_and_have_no_cleanup_request():
    launch_root = PACKAGE_ROOT.parent / 'limo_v1_navigation' / 'launch'
    combined = '\n'.join(
        path.read_text(encoding='utf-8')
        for path in sorted(launch_root.glob('*.launch')))
    assert '/cleanup/base/cmd_vel_request' not in combined
    wrapper_root = ET.parse(launch_root / 'v1_navigation.launch').getroot()
    assert wrapper_root.find("./arg[@name='mode']") is None
    core = (launch_root / 'v1_navigation_core.launch').read_text(
        encoding='utf-8')
    assert 'cmd_vel_output_topic' not in core
    assert 'to="/v1/nav_cmd_vel"' in core
    assert '$(find limo_v1_navigation)/launch/' not in RUNNER_PATH.read_text(
        encoding='utf-8')


@pytest.mark.skipif(os.name != 'posix', reason='sealed memfd requires Linux')
def test_sealed_snapshot_is_unchanged_by_source_tamper_and_fd_close_blocks(
        monkeypatch):
    v1_root = PACKAGE_ROOT.parent / 'limo_v1_navigation'
    release_payloads = {
        'v1_navigation_interface.json': (
            v1_root / 'config' / 'v1_navigation_interface.json').read_bytes(),
    }
    for name in CONFIG_SHA256:
        release_payloads[name] = (v1_root / 'config' / name).read_bytes()
    source_yaml = bytearray(
        b'image: frozen_test_map.pgm\nresolution: 0.05\norigin: [0,0,0]\n'
        b'negate: 0\noccupied_thresh: 0.65\nfree_thresh: 0.196\n')
    source_image = bytearray(b'P5\n1 1\n255\n\x00')
    monkeypatch.setattr(
        'limo_cleanup_ros1_base.runtime_snapshot.load_bound_map_payloads',
        lambda *_: (bytes(source_yaml), bytes(source_image)))
    binding = ValidatedMapBinding(
        '1' * 64, 'V1_MAP_BINDING_PASS_V1:' + '1' * 64,
        'frozen_test_map', '/map/frozen_test_map.yaml',
        '/map/frozen_test_map.pgm')
    snapshot = create_navigation_snapshot(binding, '/map', release_payloads)
    try:
        before = Path(snapshot.paths['map_image']).read_bytes()
        source_image[-1] = 255
        assert Path(snapshot.paths['map_image']).read_bytes() == before
        descriptor = snapshot.descriptors['map_image']
        os.close(descriptor)
        with pytest.raises(OSError):
            snapshot.validate()
        snapshot.descriptors.pop('map_image')
    finally:
        snapshot.close()


@pytest.mark.skipif(os.name != 'posix', reason='process containment requires /proc')
def test_run_marker_cleanup_kills_a_setsess_escape_child():
    run_id = 'escape' + secrets_token()
    code = (
        'import subprocess,sys,time; '
        'subprocess.Popen([sys.executable,"-c","import time;time.sleep(60)"],'
        'start_new_session=True); time.sleep(60)')
    process = RUNNER._spawn_process([sys.executable, '-c', code], run_id)
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        if len(RUNNER._run_marker_pids(run_id)) >= 2:
            break
        time.sleep(0.05)
    RUNNER._stop_process_group(process, run_id)
    assert RUNNER._run_marker_pids(run_id) == []


def secrets_token():
    return '{}{}'.format(os.getpid(), int(time.time() * 1e6))

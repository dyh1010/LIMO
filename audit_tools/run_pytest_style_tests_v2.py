"""Two-process isolated runner for one pytest-style source file.

The supervisor owns the exact workspace-PYC broker.  The zero-capability test
child alone installs the loader/audit guard and executes the small local pytest
surface implemented below.  Only the supervisor emits the public v2 marker.
"""

import argparse
import ast
import hashlib
import importlib.machinery
import importlib.util
import inspect
import io
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
import traceback
import types
from contextlib import ContextDecorator, redirect_stderr, redirect_stdout
from pathlib import Path


SINGLE_FILE_MARKER = 'OFFLINE_PYTEST_FILE_RESULT '
CHILD_MARKER = 'OFFLINE_PYTEST_TEST_CHILD_RESULT '
SCHEMA_VERSION = 'offline_pytest_file_result/v2'
CHILD_SCHEMA_VERSION = 'offline_pytest_test_child_result/v2'
RUNNER_KIND = 'offline_pytest_style_single_file_supervisor_v2'
CHILD_RUNNER_KIND = 'offline_pytest_style_single_file_test_child_v2'
WORKSPACE_BYTECODE_POLICY = 'SOURCE_ONLY_REJECT_WORKSPACE_PYC_V2'
WORKSPACE_PYC_INODE_POLICY = 'WORKSPACE_PYC_BROKER_AND_CHILD_REJECT_V2'
PYC_BROKER_RESULT_SCHEMA = 'workspace_pyc_identity_broker_result/v1'
PYC_BROKER_TRANSCRIPT_SCHEMA = 'workspace_pyc_identity_broker_transcript/v1'
PYC_VERIFIER_RESULT_SCHEMA = 'workspace_pyc_identity_verifier_result/v1'
PRODUCTION_WRAPPER_OBSERVATION_SCHEMA = (
    'ros1_formal_authority_production_wrapper_observation/v1')
BROKER_RELATIVE_PATH = 'audit_tools/workspace_pyc_identity_broker_v1.py'
VERIFIER_RELATIVE_PATH = 'audit_tools/workspace_pyc_identity_verifier_v1.py'
WRAPPER_RELATIVE_PATH = 'audit_tools/formal_admission_evidence_authority_v7.py'
BROKER_READY_MARKER = 'OFFLINE_WORKSPACE_PYC_BROKER_READY '
BROKER_CHECKPOINT_MARKER = 'OFFLINE_WORKSPACE_PYC_BROKER_CHECKPOINT '
BROKER_FINAL_MARKER = 'OFFLINE_WORKSPACE_PYC_BROKER_FINAL '
BROKER_ERROR_MARKER = 'OFFLINE_WORKSPACE_PYC_BROKER_ERROR '
WRAPPER_MARKER = 'OFFLINE_FORMAL_AUTHORITY_RESOLUTION_RESULT '
PYC_INVENTORY_COUNT = 18
PYC_INVENTORY_SHA256 = (
    '5dc8444d9821c591b272ee89e6fdc03ad1cdd79bee105f5017621f3e6daa8292')
COMMAND_TIMEOUT_SECONDS = 1800
EXECUTION_COMPONENT_BOOTSTRAP_SCHEMA = (
    'host_owned_execution_component_bootstrap/v1')
EXECUTION_COMPONENT_BOOTSTRAP_ERROR_MARKER = (
    'OFFLINE_EXECUTION_COMPONENT_BOOTSTRAP_ERROR ')
_EXECUTION_COMPONENT_BOOTSTRAP = r'''import hashlib,json,os,stat,sys,types
from pathlib import Path
SCHEMA='host_owned_execution_component_bootstrap/v1'
ERROR='OFFLINE_EXECUTION_COMPONENT_BOOTSTRAP_ERROR '
def fail(code,kind='UNKNOWN'):
    payload={'schema_version':SCHEMA,'code':code,'component_kind':kind}
    sys.stderr.buffer.write((ERROR+json.dumps(payload,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode('utf-8'));sys.stderr.buffer.flush();raise SystemExit(86)
def linklike(path,info):
    attributes=int(getattr(info,'st_file_attributes',0) or 0)
    return bool(stat.S_ISLNK(info.st_mode) or attributes&getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',0x400) or getattr(os.path,'isjunction',lambda unused:False)(path))
def same(info):
    return (info.st_dev,info.st_ino,info.st_mode,info.st_size,getattr(info,'st_mtime_ns',None),getattr(info,'st_ctime_ns',None),getattr(info,'st_nlink',1),getattr(info,'st_uid',None),getattr(info,'st_gid',None),getattr(info,'st_file_attributes',None))
def cross(info):
    mode=stat.S_IFMT(info.st_mode) if os.name=='nt' else info.st_mode
    common=(info.st_dev,info.st_ino,mode,info.st_size,getattr(info,'st_mtime_ns',None))
    if os.name=='nt': return common+(getattr(info,'st_nlink',1),getattr(info,'st_uid',None),getattr(info,'st_gid',None),getattr(info,'st_file_attributes',None))
    return common+(getattr(info,'st_ctime_ns',None),getattr(info,'st_nlink',1),getattr(info,'st_uid',None),getattr(info,'st_gid',None),getattr(info,'st_file_attributes',None))
def main():
    if len(sys.argv)<9: fail('execution_component_arguments_invalid')
    workspace=Path(sys.argv[1]).resolve(strict=True);relative=sys.argv[2]
    try: expected_size=int(sys.argv[3])
    except (TypeError,ValueError): fail('execution_component_expected_identity_invalid')
    expected_sha=sys.argv[4];kind=sys.argv[5];schema=sys.argv[6];bootstrap_sha=sys.argv[7]
    if schema!=SCHEMA or len(bootstrap_sha)!=64 or any(c not in '0123456789abcdef' for c in bootstrap_sha): fail('execution_component_bootstrap_contract_invalid',kind)
    parts=relative.split('/')
    if not parts or any(part in ('','.','..') or '\\' in part for part in parts): fail('execution_component_path_invalid',kind)
    path=workspace
    try:
        for part in parts:
            path=path/part;info=os.lstat(str(path))
            if linklike(path,info): fail('execution_component_path_linklike',kind)
        before=os.lstat(str(path))
    except OSError: fail('execution_component_path_unreadable',kind)
    if linklike(path,before) or not stat.S_ISREG(before.st_mode) or getattr(before,'st_nlink',1)!=1: fail('execution_component_not_exclusive_regular',kind)
    flags=os.O_RDONLY|getattr(os,'O_BINARY',0)|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_CLOEXEC',0)
    try: fd=os.open(str(path),flags)
    except OSError: fail('execution_component_open_failed',kind)
    try:
        os.set_inheritable(fd,False);opened_before=os.fstat(fd)
        if os.get_inheritable(fd) or not stat.S_ISREG(opened_before.st_mode) or getattr(opened_before,'st_nlink',1)!=1 or cross(before)!=cross(opened_before): fail('execution_component_changed_before_open',kind)
        chunks=[]
        while True:
            chunk=os.read(fd,1048576)
            if not chunk: break
            chunks.append(chunk)
        raw=b''.join(chunks);opened_after=os.fstat(fd)
        if same(opened_before)!=same(opened_after): fail('execution_component_fd_changed_during_read',kind)
    finally: os.close(fd)
    try: after=os.lstat(str(path))
    except OSError: fail('execution_component_path_unreadable_after_read',kind)
    if linklike(path,after) or not stat.S_ISREG(after.st_mode) or getattr(after,'st_nlink',1)!=1: fail('execution_component_type_changed_during_read',kind)
    if same(before)!=same(after): fail('execution_component_path_changed_during_read',kind)
    if cross(opened_after)!=cross(after): fail('execution_component_path_fd_mismatch',kind)
    actual_sha=hashlib.sha256(raw).hexdigest()
    if len(raw)!=opened_before.st_size or len(raw)!=opened_after.st_size or len(raw)!=after.st_size: fail('execution_component_size_changed_during_read',kind)
    if len(raw)!=expected_size or actual_sha!=expected_sha: fail('execution_component_expected_identity_mismatch',kind)
    binding={'schema_version':SCHEMA,'component_kind':kind,'path':relative,'size_bytes':len(raw),'sha256':actual_sha,'bootstrap_sha256':bootstrap_sha}
    module=types.ModuleType('__main__');module.__file__=str(path);module.__package__=None;module.__spec__=None;module.__loader__=None;module.__dict__['__execution_component_binding__']=binding
    sys.modules['__main__']=module;sys.argv=[str(path),*sys.argv[8:]]
    exec(compile(raw,str(path),'exec',dont_inherit=True,optimize=0),module.__dict__)
main()
'''
_EXECUTION_COMPONENT_BOOTSTRAP_SHA256 = hashlib.sha256(
    _EXECUTION_COMPONENT_BOOTSTRAP.encode('utf-8')).hexdigest()
_WORKSPACE_AUDIT_GUARD_USED = False


_BROKER_SOURCE_BOOTSTRAP = r'''import hashlib,json,os,sys
MARKER='OFFLINE_WORKSPACE_PYC_BROKER_ERROR '
SCHEMA='workspace_pyc_identity_broker_source_bootstrap/v1'
RELATIVE='audit_tools/workspace_pyc_identity_broker_v1.py'
def canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')
def fail(code):
    payload={'failure_code':code}
    sys.stdout.buffer.write(MARKER.encode('ascii')+canonical(payload)+b'\n')
    sys.stdout.buffer.flush()
    raise SystemExit(2)
def pairs(items):
    value={}
    for key,item in items:
        if key in value: fail('pyc_broker_source_bootstrap_json_duplicate_key')
        value[key]=item
    return value
def reject_constant(unused):
    fail('pyc_broker_source_bootstrap_json_nonfinite')
line=sys.stdin.buffer.readline()
if not line.endswith(b'\n'): fail('pyc_broker_source_bootstrap_truncated')
try:
    envelope=json.loads(line[:-1].decode('utf-8'),object_pairs_hook=pairs,parse_constant=reject_constant)
except SystemExit:
    raise
except BaseException:
    fail('pyc_broker_source_bootstrap_json_invalid')
if canonical(envelope)+b'\n'!=line: fail('pyc_broker_source_bootstrap_json_noncanonical')
if not isinstance(envelope,dict) or set(envelope)!={'schema_version','source_path','source_identity','source_utf8'}: fail('pyc_broker_source_bootstrap_schema_invalid')
if envelope.get('schema_version')!=SCHEMA: fail('pyc_broker_source_bootstrap_schema_invalid')
source_path=envelope.get('source_path')
identity=envelope.get('source_identity')
source_utf8=envelope.get('source_utf8')
expected_path=os.path.abspath(os.path.join(os.getcwd(),*RELATIVE.split('/')))
if not isinstance(source_path,str) or os.path.abspath(source_path)!=expected_path: fail('pyc_broker_source_bootstrap_path_mismatch')
if not isinstance(source_utf8,str): fail('pyc_broker_source_bootstrap_source_invalid')
try:
    raw=source_utf8.encode('utf-8')
except UnicodeError:
    fail('pyc_broker_source_bootstrap_source_invalid')
expected_identity={'path':RELATIVE,'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
if identity!=expected_identity: fail('pyc_broker_source_bootstrap_identity_mismatch')
namespace={'__name__':'__main__','__file__':source_path,'__package__':None,'__spec__':None}
exec(compile(raw,source_path,'exec',dont_inherit=True,optimize=0),namespace)
'''


class RaisesContext(ContextDecorator):
    def __init__(self, expected, match=None):
        self.expected = expected
        self.match = match

    def __enter__(self):
        return self

    def __exit__(self, exception_type, exception, unused_traceback):
        if exception_type is None:
            raise AssertionError(
                'expected {} to be raised'.format(self.expected.__name__))
        if not issubclass(exception_type, self.expected):
            return False
        if self.match is not None and re.search(self.match, str(exception)) is None:
            raise AssertionError(
                'exception {!r} does not match {!r}'.format(
                    str(exception), self.match))
        return True


class Approx:
    def __init__(self, expected, rel=1e-6, abs_tol=1e-12):
        self.expected = float(expected)
        self.rel = float(rel)
        self.abs_tol = float(abs_tol)

    def __eq__(self, observed):
        observed_value = float(observed)
        tolerance = max(
            self.abs_tol,
            self.rel * max(abs(observed_value), abs(self.expected)),
        )
        return abs(observed_value - self.expected) <= tolerance

    def __repr__(self):
        return 'approx({!r})'.format(self.expected)


class Mark:
    @staticmethod
    def parametrize(names, values):
        resolved_names = tuple(
            name.strip() for name in names.split(',') if name.strip())

        def decorate(function):
            function.__offline_parametrize__ = (
                resolved_names,
                tuple(values),
            )
            return function

        return decorate


class SkipTest(Exception):
    pass


class Message:
    def __init__(self):
        self.data = ''


class Node:
    pass


class QoSProfile:
    def __init__(self, depth=10):
        self.depth = depth
        self.reliability = None
        self.durability = None


class ReliabilityPolicy:
    RELIABLE = 'reliable'


class DurabilityPolicy:
    TRANSIENT_LOCAL = 'transient_local'


class MonkeyPatch:
    def __init__(self):
        self._items = []

    def setitem(self, mapping, key, value):
        present = key in mapping
        previous = mapping.get(key)
        mapping[key] = value
        self._items.append((mapping, key, present, previous))

    def undo(self):
        for mapping, key, present, previous in reversed(self._items):
            if present:
                mapping[key] = previous
            else:
                mapping.pop(key, None)


def install_pytest_stub():
    module = types.ModuleType('pytest')
    module.raises = lambda expected, match=None: RaisesContext(expected, match)
    module.approx = lambda expected, rel=1e-6, abs=1e-12: Approx(
        expected, rel=rel, abs_tol=abs)
    module.mark = Mark()
    module.fixture = lambda function: setattr(
        function, '__offline_fixture__', True) or function
    module.skip = lambda reason='': (_ for _ in ()).throw(SkipTest(reason))
    sys.modules['pytest'] = module


def install_ros_import_stubs():
    """Install import-only ROS shims; no graph or transport is created."""
    rclpy = types.ModuleType('rclpy')
    rclpy.ok = lambda: False
    rclpy.init = lambda args=None: None
    rclpy.shutdown = lambda: None
    rclpy.spin = lambda node: None
    rclpy.spin_once = lambda node, timeout_sec=0.0: None
    rclpy_node = types.ModuleType('rclpy.node')
    rclpy_node.Node = Node
    rclpy_qos = types.ModuleType('rclpy.qos')
    rclpy_qos.QoSProfile = QoSProfile
    rclpy_qos.ReliabilityPolicy = ReliabilityPolicy
    rclpy_qos.DurabilityPolicy = DurabilityPolicy
    sys.modules['rclpy'] = rclpy
    sys.modules['rclpy.node'] = rclpy_node
    sys.modules['rclpy.qos'] = rclpy_qos

    std_msgs = types.ModuleType('std_msgs')
    std_msgs_msg = types.ModuleType('std_msgs.msg')
    std_msgs_msg.String = Message
    sys.modules['std_msgs'] = std_msgs
    sys.modules['std_msgs.msg'] = std_msgs_msg

    interfaces = types.ModuleType('limo_cleanup_interfaces')
    interfaces_msg = types.ModuleType('limo_cleanup_interfaces.msg')
    interfaces_msg.CleanupStatus = type('CleanupStatus', (), {})
    interfaces_msg.CleanupTask = type('CleanupTask', (), {})
    sys.modules['limo_cleanup_interfaces'] = interfaces
    sys.modules['limo_cleanup_interfaces.msg'] = interfaces_msg


def restore_module(name, previous):
    """Restore one import slot after an isolation fixture."""
    if previous is None:
        sys.modules.pop(name, None)
    else:
        sys.modules[name] = previous


def load_module(path, sequence, raw=None):
    name = 'offline_pytest_module_{}'.format(sequence)
    payload = _read_regular_bytes(path, 'target') if raw is None else raw
    module = types.ModuleType(name)
    module.__file__ = str(path)
    module.__package__ = ''
    module.__spec__ = importlib.machinery.ModuleSpec(
        name, loader=None, origin=str(path))
    code = compile(payload, str(path), 'exec', dont_inherit=True, optimize=0)
    exec(code, module.__dict__)
    if (Path(module.__file__).resolve(strict=True) != path
            or Path(module.__spec__.origin).resolve(strict=True) != path):
        raise RuntimeError('loaded_test_module_origin_mismatch')
    return module


def invoke(function, arguments):
    signature = inspect.signature(function)
    signature.bind(**arguments)
    function(**arguments)


def add_supported_fixtures(function, arguments):
    """Materialize only the small fixture set used by voice tests."""
    cleanups = []
    for name in inspect.signature(function).parameters:
        if name in arguments:
            continue
        if name == 'tmp_path':
            temporary_path = Path(tempfile.mkdtemp(prefix='voice_stub_'))
            arguments[name] = temporary_path
            cleanups.append(
                lambda path=temporary_path: shutil.rmtree(path))
        elif name == 'monkeypatch':
            monkeypatch = MonkeyPatch()
            arguments[name] = monkeypatch
            cleanups.append(monkeypatch.undo)
        elif name == 'isolated_no_ros_imports':
            names = (
                'rclpy', 'rclpy.node', 'rclpy.qos',
                'std_msgs', 'std_msgs.msg',
                'limo_cleanup_interfaces', 'limo_cleanup_interfaces.msg',
            )
            previous = {name: sys.modules.get(name) for name in names}
            for module_name in names:
                sys.modules.pop(module_name, None)
            arguments[name] = True
            cleanups.append(
                lambda values=previous: [
                    restore_module(module_name, value)
                    for module_name, value in values.items()
                ])
        elif name in OFFLINE_FIXTURES:
            arguments[name] = OFFLINE_FIXTURES[name]()
        else:
            raise TypeError('unsupported fixture: {}'.format(name))
    return cleanups


OFFLINE_FIXTURES = {}


def _is_relative_to(path, root):
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _meta_path_snapshot():
    return sys.meta_path, tuple(sys.meta_path)


def _meta_path_matches(snapshot):
    expected_object, expected_entries = snapshot
    return (
        sys.meta_path is expected_object
        and len(sys.meta_path) == len(expected_entries)
        and all(
            actual is expected
            for actual, expected in zip(sys.meta_path, expected_entries)
        )
    )


def _is_linklike(path, metadata):
    attributes = int(getattr(metadata, 'st_file_attributes', 0) or 0)
    is_junction = getattr(os.path, 'isjunction', lambda unused: False)
    return bool(
        stat.S_ISLNK(metadata.st_mode)
        or attributes & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)
        or is_junction(path)
    )


def _same_side_projection(metadata):
    return (
        metadata.st_dev, metadata.st_ino, metadata.st_mode,
        metadata.st_size, getattr(metadata, 'st_mtime_ns', None),
        getattr(metadata, 'st_ctime_ns', None),
        getattr(metadata, 'st_nlink', 1), getattr(metadata, 'st_uid', None),
        getattr(metadata, 'st_gid', None),
        getattr(metadata, 'st_file_attributes', None),
    )


def _cross_source_projection(metadata):
    if os.name == 'nt':
        return (
            metadata.st_dev, metadata.st_ino, stat.S_IFMT(metadata.st_mode),
            metadata.st_size, getattr(metadata, 'st_mtime_ns', None),
            getattr(metadata, 'st_nlink', 1),
            getattr(metadata, 'st_uid', None),
            getattr(metadata, 'st_gid', None),
            getattr(metadata, 'st_file_attributes', None),
        )
    return (
        metadata.st_dev, metadata.st_ino, metadata.st_mode,
        metadata.st_size, getattr(metadata, 'st_mtime_ns', None),
        getattr(metadata, 'st_ctime_ns', None),
        getattr(metadata, 'st_nlink', 1), getattr(metadata, 'st_uid', None),
        getattr(metadata, 'st_gid', None),
        getattr(metadata, 'st_file_attributes', None),
    )


def _read_regular_binding(path, label):
    path = Path(path)
    before = path.lstat()
    if _is_linklike(path, before):
        raise ValueError('{}_is_link'.format(label))
    if (not stat.S_ISREG(before.st_mode)
            or getattr(before, 'st_nlink', 1) != 1):
        raise ValueError('{}_is_not_regular_file'.format(label))
    flags = os.O_RDONLY
    flags |= getattr(os, 'O_BINARY', 0)
    flags |= getattr(os, 'O_NOFOLLOW', 0)
    flags |= getattr(os, 'O_CLOEXEC', 0)
    descriptor = os.open(os.fspath(path), flags)
    try:
        os.set_inheritable(descriptor, False)
        opened_before = os.fstat(descriptor)
        if (not stat.S_ISREG(opened_before.st_mode)
                or getattr(opened_before, 'st_nlink', 1) != 1):
            raise ValueError('{}_opened_object_is_not_regular'.format(label))
        if _cross_source_projection(opened_before) != (
                _cross_source_projection(before)):
            raise ValueError('{}_changed_before_open'.format(label))
        chunks = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        raw = b''.join(chunks)
        opened_after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    after = path.lstat()
    if (_is_linklike(path, after) or not stat.S_ISREG(after.st_mode)
            or getattr(after, 'st_nlink', 1) != 1):
        raise ValueError('{}_changed_file_type_while_reading'.format(label))
    if _same_side_projection(after) != _same_side_projection(before):
        raise ValueError('{}_replaced_while_reading'.format(label))
    if _same_side_projection(opened_after) != _same_side_projection(
            opened_before):
        raise ValueError('{}_opened_object_changed_while_reading'.format(label))
    if _cross_source_projection(opened_after) != _cross_source_projection(
            after):
        raise ValueError('{}_path_fd_changed_while_reading'.format(label))
    if len(raw) != opened_after.st_size:
        raise ValueError('{}_size_changed_while_reading'.format(label))
    identity = {
        'size_bytes': len(raw),
        'sha256': hashlib.sha256(raw).hexdigest(),
    }
    if (
        len(raw) != identity['size_bytes']
        or hashlib.sha256(raw).hexdigest() != identity['sha256']
    ):
        raise ValueError('{}_bound_identity_mismatch'.format(label))
    return {'raw': raw, 'identity': identity}


def _read_regular_bytes(path, label):
    return _read_regular_binding(path, label)['raw']


def _regular_file_identity(path, label='target'):
    return dict(_read_regular_binding(path, label)['identity'])


def _workspace_file(workspace, relative, label):
    path = Path(workspace)
    for part in Path(relative).parts:
        path = path / part
        metadata = path.lstat()
        if _is_linklike(path, metadata):
            raise ValueError(label + '_path_component_linklike')
    path = path.resolve(strict=True)
    if not _is_relative_to(path, workspace):
        raise ValueError(label + '_outside_workspace')
    return path


def _relative_binding(workspace, relative, label):
    path = _workspace_file(workspace, relative, label)
    binding = _read_regular_binding(path, label)
    identity = {
        'path': path.relative_to(workspace).as_posix(),
        'size_bytes': binding['identity']['size_bytes'],
        'sha256': binding['identity']['sha256'],
    }
    return {'path': path, 'raw': binding['raw'], 'identity': identity}


def _relative_identity(workspace, relative, label):
    return _relative_binding(workspace, relative, label)['identity']


def _binding_identity_matches_raw(binding, label):
    if not isinstance(binding, dict) or set(binding) != {
            'path', 'raw', 'identity'}:
        raise ValueError(label + '_bound_record_invalid')
    raw = binding['raw']
    identity = binding['identity']
    bound_path = binding['path']
    if (
        not isinstance(raw, bytes)
        or not isinstance(bound_path, Path)
        or not bound_path.is_absolute()
        or not isinstance(identity, dict)
        or set(identity) != {'path', 'size_bytes', 'sha256'}
        or not isinstance(identity.get('path'), str)
        or not identity['path']
        or len(raw) != identity.get('size_bytes')
        or hashlib.sha256(raw).hexdigest() != identity.get('sha256')
    ):
        raise ValueError(label + '_bound_identity_mismatch')
    return identity


def _execution_component_argv(
        workspace, relative, binding, component_kind, component_argv):
    identity = _binding_identity_matches_raw(
        binding, component_kind + '_execution_component')
    expected_path = _workspace_file(
        workspace, relative, component_kind + '_execution_component_path')
    if identity['path'] != relative:
        raise ValueError(
            component_kind + '_execution_component_relative_identity_path_mismatch')
    if binding['path'] != expected_path:
        raise ValueError(
            component_kind + '_execution_component_bound_path_mismatch')
    return [
        sys.executable, '-I', '-S', '-B', '-c',
        _EXECUTION_COMPONENT_BOOTSTRAP, str(workspace), relative,
        str(identity['size_bytes']), identity['sha256'], component_kind,
        EXECUTION_COMPONENT_BOOTSTRAP_SCHEMA,
        _EXECUTION_COMPONENT_BOOTSTRAP_SHA256,
        *component_argv,
    ]


def _current_runner_execution_binding(workspace):
    value = globals().get('__execution_component_binding__')
    expected_path = Path(__file__).resolve(strict=True)
    expected_relative = expected_path.relative_to(workspace).as_posix()
    if (
        not isinstance(value, dict)
        or set(value) != {
            'schema_version', 'component_kind', 'path', 'size_bytes',
            'sha256', 'bootstrap_sha256'}
        or value.get('schema_version')
        != EXECUTION_COMPONENT_BOOTSTRAP_SCHEMA
        or value.get('component_kind') != 'runner'
        or value.get('path') != expected_relative
        or value.get('bootstrap_sha256')
        != _EXECUTION_COMPONENT_BOOTSTRAP_SHA256
        or type(value.get('size_bytes')) is not int
        or value['size_bytes'] <= 0
        or not isinstance(value.get('sha256'), str)
        or len(value['sha256']) != 64
    ):
        raise ValueError('runner_execution_component_binding_invalid')
    live = _relative_binding(
        workspace, expected_relative, 'runner_execution_component')
    if live['identity'] != {
        'path': value['path'], 'size_bytes': value['size_bytes'],
        'sha256': value['sha256'],
    }:
        raise ValueError('runner_execution_component_live_drift')
    return dict(value)


class WorkspaceLoaderGuard:
    """Reject workspace bytecode reads and attest source bytes read by loaders."""

    _MISSING_ATTRIBUTE = object()
    _LOADER_NAMES = ('SourceFileLoader', 'SourcelessFileLoader')

    def __init__(self, workspace):
        self.workspace = Path(workspace).resolve(strict=True)
        self._states = []
        self._wrappers = {}
        self._blocked = set()
        self._source_reads = {}
        self._installed = False
        self._tampered = False
        self._restored = False
        self._audit_hook_active = False
        self._audit_probe_token = object()
        self._bytecode_inventory_before = None
        self._bytecode_inode_paths = {}
        self._bytecode_inventory_stable = False
        self._meta_path_snapshot = None
        self._meta_path_tampered = False
        self._meta_path_restored = False

    @staticmethod
    def _is_bytecode_relative(relative):
        return (
            relative.suffix.casefold() == '.pyc'
            or any(part.casefold() == '__pycache__'
                   for part in relative.parts)
        )

    @staticmethod
    def _is_linklike(path, metadata):
        attributes = int(getattr(metadata, 'st_file_attributes', 0) or 0)
        is_junction = getattr(os.path, 'isjunction', lambda unused: False)
        return bool(
            stat.S_ISLNK(metadata.st_mode)
            or attributes & 0x400
            or is_junction(path)
        )

    def _collect_bytecode_inventory(self):
        inventory = []
        for current_root, directory_names, file_names in os.walk(
                self.workspace, topdown=True, followlinks=False):
            directory_names.sort()
            file_names.sort()
            retained_directories = []
            for name in directory_names:
                candidate = Path(current_root) / name
                metadata = candidate.lstat()
                if self._is_linklike(candidate, metadata):
                    relative = candidate.relative_to(self.workspace)
                    if self._is_bytecode_relative(relative):
                        raise ValueError(
                            'workspace_bytecode_directory_linklike:{}'.format(
                                relative.as_posix()))
                    continue
                retained_directories.append(name)
            directory_names[:] = retained_directories
            for name in file_names:
                candidate = Path(current_root) / name
                relative = candidate.relative_to(self.workspace)
                if not self._is_bytecode_relative(relative):
                    continue
                metadata = candidate.lstat()
                if self._is_linklike(candidate, metadata):
                    raise ValueError(
                        'workspace_bytecode_file_linklike:{}'.format(
                            relative.as_posix()))
                if not stat.S_ISREG(metadata.st_mode):
                    raise ValueError(
                        'workspace_bytecode_not_regular:{}'.format(
                            relative.as_posix()))
                if metadata.st_nlink != 1:
                    raise ValueError(
                        'workspace_bytecode_hardlink_rejected:{}'.format(
                            relative.as_posix()))
                inventory.append({
                    'path': relative.as_posix(),
                    'device': int(metadata.st_dev),
                    'inode': int(metadata.st_ino),
                    'size_bytes': int(metadata.st_size),
                    'mtime_ns': int(metadata.st_mtime_ns),
                    'nlink': int(metadata.st_nlink),
                    'file_type': int(stat.S_IFMT(metadata.st_mode)),
                })
        inventory.sort(key=lambda item: item['path'])
        identities = [(item['device'], item['inode']) for item in inventory]
        if len(identities) != len(set(identities)):
            raise ValueError('workspace_bytecode_inode_duplicate')
        return inventory

    def _install_bytecode_inventory(self):
        inventory = self._collect_bytecode_inventory()
        self._bytecode_inventory_before = inventory
        self._bytecode_inode_paths = {
            (item['device'], item['inode']): item['path']
            for item in inventory
        }

    def _workspace_relative(self, raw_path):
        try:
            decoded = os.fsdecode(raw_path)
        except (TypeError, ValueError):
            return None
        candidate = Path(decoded)
        if not candidate.is_absolute():
            candidate = self.workspace / candidate
        candidate = Path(os.path.abspath(os.fspath(candidate)))
        candidates = [candidate]
        try:
            resolved = candidate.resolve(strict=False)
        except (OSError, RuntimeError):
            resolved = None
        if resolved is not None and resolved not in candidates:
            candidates.append(resolved)
        for item in candidates:
            if _is_relative_to(item, self.workspace):
                return item.relative_to(self.workspace).as_posix()
        return None

    def _guard_is_installed(self):
        installed = bool(self._installed and self._states)
        if (
            self._meta_path_snapshot is None
            or not _meta_path_matches(self._meta_path_snapshot)
        ):
            installed = False
            self._meta_path_tampered = True
        for loader_name, loader_class, _raw_attribute, _original in self._states:
            if getattr(importlib.machinery, loader_name, None) is not loader_class:
                installed = False
            if loader_class.__dict__.get(
                    'get_data', self._MISSING_ATTRIBUTE
            ) is not self._wrappers.get(loader_class):
                installed = False
        if not installed and self._installed:
            self._tampered = True
        return installed

    def _guarded_get_data(self, original, loader, raw_path):
        if not self._guard_is_installed():
            raise ValueError('workspace_loader_guard_replaced_during_execution')
        relative = self._workspace_relative(raw_path)
        if relative is not None:
            path = Path(relative)
            if (
                    path.suffix.casefold() == '.pyc'
                    or any(part.casefold() == '__pycache__'
                           for part in path.parts)):
                self._blocked.add(relative)
                raise FileNotFoundError(
                    'workspace_bytecode_read_blocked:{}'.format(relative))
        raw = original(loader, raw_path)
        if relative is not None and Path(relative).suffix.lower() == '.py':
            identity = {
                'path': relative,
                'size_bytes': len(raw),
                'sha256': hashlib.sha256(raw).hexdigest(),
            }
            previous = self._source_reads.get(relative)
            if previous is not None and previous != identity:
                raise ValueError(
                    'workspace_source_changed_during_execution:{}'.format(
                        relative))
            self._source_reads[relative] = identity
        return raw

    def _audit_hook(self, event, arguments):
        if event == 'limo.workspace_loader_guard_probe':
            if arguments and arguments[0] is self._audit_probe_token:
                self._audit_hook_active = True
            return
        if (
            self._installed and self._meta_path_snapshot is not None
            and not _meta_path_matches(self._meta_path_snapshot)
        ):
            self._meta_path_tampered = True
            self._tampered = True
            raise RuntimeError('sys_meta_path_changed_during_execution')
        if event != 'open' or not arguments:
            return
        relative = self._workspace_relative(arguments[0])
        if relative is not None and self._is_bytecode_relative(Path(relative)):
            self._blocked.add(relative)
            raise PermissionError(
                'workspace_bytecode_open_blocked:{}'.format(relative))
        try:
            raw_candidate = Path(os.fsdecode(arguments[0]))
            if not raw_candidate.is_absolute():
                raw_candidate = self.workspace / raw_candidate
            raw_candidate = Path(os.path.abspath(os.fspath(raw_candidate)))
            metadata = raw_candidate.stat()
        except (OSError, RuntimeError, TypeError, ValueError):
            return
        inode_path = self._bytecode_inode_paths.get(
            (int(metadata.st_dev), int(metadata.st_ino)))
        if inode_path is not None:
            self._blocked.add(inode_path)
            raise PermissionError(
                'workspace_bytecode_inode_alias_blocked:{}'.format(
                    inode_path))

    def _install_audit_hook(self):
        global _WORKSPACE_AUDIT_GUARD_USED
        if _WORKSPACE_AUDIT_GUARD_USED:
            raise RuntimeError('workspace_pyc_audit_hook_process_reuse_forbidden')
        sys.addaudithook(self._audit_hook)
        sys.audit('limo.workspace_loader_guard_probe', self._audit_probe_token)
        if not self._audit_hook_active:
            raise RuntimeError('workspace_pyc_audit_hook_install_failed')
        _WORKSPACE_AUDIT_GUARD_USED = True

    def install(self):
        if self._installed:
            raise RuntimeError('workspace_loader_guard_already_installed')
        try:
            self._meta_path_snapshot = _meta_path_snapshot()
            self._install_bytecode_inventory()
            for loader_name in self._LOADER_NAMES:
                loader_class = getattr(importlib.machinery, loader_name)
                raw_attribute = loader_class.__dict__.get(
                    'get_data', self._MISSING_ATTRIBUTE)
                original = getattr(loader_class, 'get_data')
                self._states.append(
                    (loader_name, loader_class, raw_attribute, original))

                def guarded_get_data(loader, raw_path, _original=original):
                    return self._guarded_get_data(
                        _original, loader, raw_path)

                self._wrappers[loader_class] = guarded_get_data
            for loader_class, wrapper in self._wrappers.items():
                setattr(loader_class, 'get_data', wrapper)
            self._installed = True
            self._install_audit_hook()
            if not self._guard_is_installed():
                raise RuntimeError('workspace_loader_guard_install_failed')
        except BaseException:
            self.restore()
            raise

    def restore(self):
        if not self._states:
            self._restored = False
            return
        if self._bytecode_inventory_before is not None:
            try:
                self._bytecode_inventory_stable = (
                    self._collect_bytecode_inventory()
                    == self._bytecode_inventory_before)
            except BaseException:
                self._bytecode_inventory_stable = False
        self._guard_is_installed()
        restore_failed = False
        for loader_name, loader_class, raw_attribute, _original in reversed(
                self._states):
            try:
                setattr(importlib.machinery, loader_name, loader_class)
                if raw_attribute is self._MISSING_ATTRIBUTE:
                    if 'get_data' in loader_class.__dict__:
                        delattr(loader_class, 'get_data')
                else:
                    setattr(loader_class, 'get_data', raw_attribute)
            except BaseException:
                restore_failed = True
        restored = not restore_failed
        for loader_name, loader_class, raw_attribute, original in self._states:
            try:
                if getattr(importlib.machinery, loader_name) is not loader_class:
                    restored = False
                if loader_class.__dict__.get(
                        'get_data', self._MISSING_ATTRIBUTE
                ) is not raw_attribute:
                    restored = False
                if getattr(loader_class, 'get_data') is not original:
                    restored = False
            except BaseException:
                restored = False
        if self._meta_path_snapshot is not None:
            expected_object, expected_entries = self._meta_path_snapshot
            try:
                if sys.meta_path is not expected_object:
                    sys.meta_path = expected_object
                expected_object[:] = expected_entries
            except BaseException:
                restore_failed = True
            self._meta_path_restored = _meta_path_matches(
                self._meta_path_snapshot)
        else:
            self._meta_path_restored = False
        restored = restored and not restore_failed and self._meta_path_restored
        self._restored = restored
        self._installed = False

    @property
    def tampered(self):
        return self._tampered

    @property
    def restored(self):
        return self._restored

    @property
    def meta_path_tampered(self):
        return self._meta_path_tampered

    def marker_fields(self):
        return {
            'workspace_bytecode_policy': WORKSPACE_BYTECODE_POLICY,
            'workspace_pyc_bytes_read': 0,
            'workspace_pyc_attempts_blocked': sorted(self._blocked),
            'workspace_source_reads': [
                self._source_reads[path] for path in sorted(self._source_reads)
            ],
            'workspace_loader_guard_restored': self._restored,
            'workspace_pyc_audit_hook_active': self._audit_hook_active,
            'workspace_pyc_inode_policy': WORKSPACE_PYC_INODE_POLICY,
            'workspace_pyc_inventory_count': len(
                self._bytecode_inventory_before or ()),
            'workspace_pyc_inventory_stable': self._bytecode_inventory_stable,
            'sys_meta_path_guard_active': self._meta_path_snapshot is not None,
            'sys_meta_path_changed_during_execution': self._meta_path_tampered,
            'sys_meta_path_restored': self._meta_path_restored,
        }

    def record_source_bytes(self, path, raw):
        relative = Path(path).resolve(strict=True).relative_to(
            self.workspace).as_posix()
        identity = {
            'path': relative,
            'size_bytes': len(raw),
            'sha256': hashlib.sha256(raw).hexdigest(),
        }
        previous = self._source_reads.get(relative)
        if previous is not None and previous != identity:
            raise ValueError(
                'workspace_source_changed_during_execution:{}'.format(
                    relative))
        self._source_reads[relative] = identity


class _NativeStreamCapture:
    """Capture Python and native writes through file descriptors 1 and 2."""
    def __enter__(self):
        sys.stdout.flush()
        sys.stderr.flush()
        self._stdout_object = sys.stdout
        self._stderr_object = sys.stderr
        self._stdout_fd = os.dup(1)
        self._stderr_fd = os.dup(2)
        self._stdout_file = tempfile.TemporaryFile(mode='w+b')
        self._stderr_file = tempfile.TemporaryFile(mode='w+b')
        os.dup2(self._stdout_file.fileno(), 1)
        os.dup2(self._stderr_file.fileno(), 2)
        return self

    def __exit__(self, exception_type, exception, unused_traceback):
        try:
            try:
                sys.stdout.flush()
                sys.stderr.flush()
            finally:
                os.dup2(self._stdout_fd, 1)
                os.dup2(self._stderr_fd, 2)
        finally:
            os.close(self._stdout_fd)
            os.close(self._stderr_fd)
        self.stdout_object_unchanged = sys.stdout is self._stdout_object
        self.stderr_object_unchanged = sys.stderr is self._stderr_object
        sys.stdout = self._stdout_object
        sys.stderr = self._stderr_object
        self._stdout_file.seek(0)
        self._stderr_file.seek(0)
        self.stdout = self._stdout_file.read().decode(
            'utf-8', 'backslashreplace')
        self.stderr = self._stderr_file.read().decode(
            'utf-8', 'backslashreplace')
        self._stdout_file.close()
        self._stderr_file.close()
        return False


def _resolve_protocol_directory(raw_path, workspace, label):
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = workspace / candidate
    if candidate.is_symlink():
        raise ValueError('{}_is_link'.format(label))
    candidate = candidate.resolve(strict=True)
    if not _is_relative_to(candidate, workspace):
        raise ValueError('{}_outside_workspace'.format(label))
    if candidate.is_symlink() or not candidate.is_dir():
        raise ValueError('{}_not_regular_directory'.format(label))
    return candidate


def _collect_cases(module, target_relative):
    """Collect stable case IDs and their call data from one loaded module."""
    cases = []
    seen = set()
    OFFLINE_FIXTURES.update({
        name: function
        for name, function in vars(module).items()
        if callable(function)
        and getattr(function, '__offline_fixture__', False)
    })
    for name, function in sorted(vars(module).items()):
        if not name.startswith('test_') or not callable(function):
            continue
        parametrized = getattr(function, '__offline_parametrize__', None)
        parameter_names = () if parametrized is None else parametrized[0]
        parameter_cases = ((),) if parametrized is None else parametrized[1]
        for case_index, case in enumerate(parameter_cases):
            case_values = case if isinstance(case, tuple) else (case,)
            arguments = dict(zip(parameter_names, case_values))
            case_id = '{}::{}'.format(target_relative, name)
            if parametrized is not None:
                case_id += '[{}]'.format(case_index)
            if case_id in seen:
                raise ValueError('duplicate_collected_test_id:{}'.format(case_id))
            seen.add(case_id)
            cases.append((case_id, function, arguments))
    return cases


def _run_selected_cases(cases, expected_ids, stubbed_modules):
    by_id = {case[0]: case for case in cases}
    unknown = [case_id for case_id in expected_ids if case_id not in by_id]
    if unknown:
        raise ValueError(
            'expected_test_id_not_collected:{}'.format(','.join(unknown)))

    executed_ids = []
    passed = 0
    failed = 0
    skipped = 0
    diagnostics = []
    for case_id in expected_ids:
        _unused_id, function, initial_arguments = by_id[case_id]
        arguments = dict(initial_arguments)
        cleanups = []
        outcome = None
        executed_ids.append(case_id)
        try:
            cleanups = add_supported_fixtures(function, arguments)
            invoke(function, arguments)
        except SkipTest as error:
            outcome = 'skipped'
            diagnostics.append('SKIP {} {}'.format(case_id, error))
        except BaseException:
            outcome = 'failed'
            diagnostics.append(
                'FAIL {}\n{}'.format(case_id, traceback.format_exc()))
        else:
            outcome = 'passed'
        finally:
            cleanup_failed = False
            for cleanup in reversed(cleanups):
                try:
                    cleanup()
                except BaseException:
                    cleanup_failed = True
                    diagnostics.append(
                        'CLEANUP_FAIL {}\n{}'.format(
                            case_id, traceback.format_exc()))
            if cleanup_failed:
                outcome = 'failed'
            for module_name in (
                    'rclpy', 'rclpy.node', 'rclpy.qos',
                    'std_msgs', 'std_msgs.msg',
                    'limo_cleanup_interfaces',
                    'limo_cleanup_interfaces.msg'):
                sys.modules[module_name] = stubbed_modules[module_name]
        if outcome == 'passed':
            passed += 1
        elif outcome == 'skipped':
            skipped += 1
        else:
            failed += 1
    return {
        'executed_ids': executed_ids,
        'passed': passed,
        'failed': failed,
        'skipped': skipped,
        'diagnostics': diagnostics,
    }


def _single_file_report(args):
    """Run exactly one allowlisted test file and return its strict marker."""
    expected_ids = list(args.expected_id or ())
    report = {
        'schema_version': CHILD_SCHEMA_VERSION,
        'runner_kind': CHILD_RUNNER_KIND,
        'mode': 'test-child-v2',
        'record_id': args.record_id,
        'suite_id': args.suite_id,
        'path': '',
        'resolved_path': '',
        'size_bytes': 0,
        'sha256': '',
        'target_identity_before': None,
        'target_identity_after': None,
        'expected_ids': expected_ids,
        'executed_ids': [],
        'collected': 0,
        'passed': 0,
        'failed': 0,
        'skipped': 0,
        'exit': 1,
        'result': 'FAIL',
        'failures': [],
        'workspace_bytecode_policy': WORKSPACE_BYTECODE_POLICY,
        'workspace_pyc_bytes_read': 0,
        'workspace_pyc_attempts_blocked': [],
        'workspace_source_reads': [],
        'workspace_loader_guard_restored': False,
        'workspace_pyc_audit_hook_active': False,
        'workspace_pyc_inode_policy': WORKSPACE_PYC_INODE_POLICY,
        'workspace_pyc_inventory_count': 0,
        'workspace_pyc_inventory_stable': False,
        'sys_meta_path_guard_active': False,
        'sys_meta_path_changed_during_execution': False,
        'sys_meta_path_restored': False,
        'child_capability_surface': {
            'broker_argv_fields': [],
            'broker_channels': [],
            'broker_environment_fields': [],
            'broker_fds': [],
            'broker_modules_in_sys_modules': [],
            'broker_secrets': [],
            'broker_tokens': [],
        },
        'runner_execution_binding': None,
    }
    diagnostics = []
    workspace_loader_guard = None
    baseline_sys_path = list(sys.path)
    baseline_meta_path = _meta_path_snapshot()
    meta_path_unchanged_before_restore = False
    try:
        if not isinstance(args.workspace, str) or not args.workspace:
            raise ValueError('single_file_requires_exactly_one_workspace')
        if not isinstance(args.target, str) or not args.target:
            raise ValueError('single_file_requires_exactly_one_target')
        if not args.import_root:
            raise ValueError('single_file_requires_import_root_allowlist')
        if not expected_ids:
            raise ValueError('single_file_zero_expected_test_ids')
        if len(expected_ids) != len(set(expected_ids)):
            raise ValueError('single_file_duplicate_expected_test_id')
        if not sys.flags.isolated:
            raise ValueError('single_file_requires_python_isolated_mode')
        if not sys.flags.no_site:
            raise ValueError('single_file_requires_python_no_site_mode')
        if not sys.dont_write_bytecode:
            raise ValueError('single_file_requires_python_no_bytecode_mode')

        workspace_input = Path(args.workspace)
        if workspace_input.is_symlink():
            raise ValueError('workspace_is_link')
        workspace = workspace_input.resolve(strict=True)
        if workspace.is_symlink() or not workspace.is_dir():
            raise ValueError('workspace_not_regular_directory')
        if Path.cwd().resolve(strict=True) != workspace:
            raise ValueError('single_file_cwd_must_equal_workspace')
        report['runner_execution_binding'] = (
            _current_runner_execution_binding(workspace))

        raw_target = Path(args.target)
        if not raw_target.is_absolute():
            raw_target = workspace / raw_target
        if raw_target.is_symlink():
            raise ValueError('target_is_link')
        target = raw_target.resolve(strict=True)
        if not _is_relative_to(target, workspace):
            raise ValueError('target_outside_workspace')
        target_relative = target.relative_to(workspace).as_posix()
        report['path'] = target_relative
        report['resolved_path'] = str(target)
        target_raw = _read_regular_bytes(target, 'target')
        before_identity = {
            'path': target_relative,
            'size_bytes': len(target_raw),
            'sha256': hashlib.sha256(target_raw).hexdigest(),
        }
        report['target_identity_before'] = before_identity
        report.update(before_identity)

        prefix = target_relative + '::'
        if any(not isinstance(item, str) or not item.startswith(prefix)
               for item in expected_ids):
            raise ValueError('expected_test_id_path_mismatch')

        import_roots = []
        for raw_root in args.import_root:
            root = _resolve_protocol_directory(
                raw_root, workspace, 'import_root')
            if root in import_roots:
                raise ValueError('duplicate_import_root')
            import_roots.append(root)
        for root in reversed(import_roots):
            sys.path.insert(0, str(root))

        workspace_loader_guard = WorkspaceLoaderGuard(workspace)
        workspace_loader_guard.install()
        try:
            OFFLINE_FIXTURES.clear()
            install_pytest_stub()
            install_ros_import_stubs()
            stubbed_modules = dict(sys.modules)
            workspace_loader_guard.record_source_bytes(target, target_raw)
            with _NativeStreamCapture() as capture:
                module = load_module(target, 1, target_raw)
                cases = _collect_cases(module, target_relative)
                selected = _run_selected_cases(
                    cases, expected_ids, stubbed_modules)
        finally:
            meta_path_unchanged_before_restore = _meta_path_matches(
                baseline_meta_path)
            workspace_loader_guard.restore()
        if (
            not meta_path_unchanged_before_restore
            or workspace_loader_guard.meta_path_tampered
        ):
            raise ValueError('sys_meta_path_changed_during_execution')
        if workspace_loader_guard.tampered:
            raise ValueError('workspace_loader_guard_replaced')
        if not workspace_loader_guard.restored:
            raise ValueError('workspace_loader_guard_not_restored')
        if not workspace_loader_guard._bytecode_inventory_stable:
            raise ValueError('workspace_pyc_inventory_changed_during_execution')
        report['executed_ids'] = selected['executed_ids']
        report['collected'] = len(selected['executed_ids'])
        report['passed'] = selected['passed']
        report['failed'] = selected['failed']
        report['skipped'] = selected['skipped']
        diagnostics.extend(selected['diagnostics'])
        if capture.stdout:
            diagnostics.append('CAPTURED_STDOUT\n' + capture.stdout)
        if capture.stderr:
            diagnostics.append('CAPTURED_STDERR\n' + capture.stderr)
        if not capture.stdout_object_unchanged:
            raise ValueError('test_replaced_sys_stdout')
        if not capture.stderr_object_unchanged:
            raise ValueError('test_replaced_sys_stderr')

        target_after_raw = _read_regular_bytes(target, 'target')
        after_identity = {
            'path': target_relative,
            'size_bytes': len(target_after_raw),
            'sha256': hashlib.sha256(target_after_raw).hexdigest(),
        }
        report['target_identity_after'] = after_identity
        if after_identity != before_identity:
            raise ValueError('target_identity_changed_during_execution')
        if target_after_raw != target_raw:
            raise ValueError('target_bytes_changed_during_execution')
        if report['executed_ids'] != expected_ids:
            raise ValueError('executed_test_id_order_mismatch')
        if report['collected'] == 0:
            raise ValueError('single_file_zero_collected_tests')
        if report['collected'] != (
                report['passed'] + report['failed'] + report['skipped']):
            raise ValueError('single_file_test_count_not_conserved')
        if report['failed']:
            raise ValueError('single_file_test_failure')
        report['exit'] = 0
        report['result'] = 'PASS'
    except BaseException as error:
        message = str(error)
        report['failures'].append(
            message if message else type(error).__name__)
        diagnostics.append(traceback.format_exc())
    finally:
        if workspace_loader_guard is not None:
            report.update(workspace_loader_guard.marker_fields())
        try:
            expected_meta_object, expected_meta_entries = baseline_meta_path
            if sys.meta_path is not expected_meta_object:
                sys.meta_path = expected_meta_object
            expected_meta_object[:] = expected_meta_entries
            sys.path[:] = baseline_sys_path
            meta_path_restored = _meta_path_matches(baseline_meta_path)
        except BaseException:
            meta_path_restored = False
        report['sys_meta_path_restored'] = meta_path_restored
        if not meta_path_restored:
            report['exit'] = 1
            report['result'] = 'FAIL'
            report['failures'].append('sys_meta_path_restore_failed')
            diagnostics.append('sys_meta_path_restore_failed')
        report['failures'] = sorted(set(report['failures']))

    if diagnostics:
        sys.stderr.write('\n'.join(diagnostics))
        if not diagnostics[-1].endswith('\n'):
            sys.stderr.write('\n')
    return report


class _ArgvFailure(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def _canonical_json(value):
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, sort_keys=True,
        separators=(',', ':')).encode('utf-8')


def _canonical_sha256(value):
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _stream_identity(raw):
    return {
        'size_bytes': len(raw),
        'sha256': hashlib.sha256(raw).hexdigest(),
    }


def _strict_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('strict_json_duplicate_key')
        result[key] = value
    return result


def _strict_json(raw):
    if isinstance(raw, bytes):
        raw = raw.decode('utf-8')
    return json.loads(
        raw, object_pairs_hook=_strict_pairs,
        parse_constant=lambda value: (_ for _ in ()).throw(
            ValueError('strict_json_nonfinite:' + value)))


def _strict_raw_options(argv):
    raw = list(sys.argv[1:] if argv is None else argv)
    scalar_names = ('mode', 'workspace', 'record-id', 'suite-id', 'target')
    repeat_names = ('import-root', 'expected-id')
    scalars = {name: None for name in scalar_names}
    repeats = {name: [] for name in repeat_names}
    single_file_count = 0
    index = 0
    while index < len(raw):
        token = raw[index]
        if token == '--single-file':
            single_file_count += 1
            index += 1
            continue
        if not isinstance(token, str) or not token.startswith('--'):
            raise _ArgvFailure('runner_argv_positional_forbidden')
        name = token[2:]
        if name not in scalars and name not in repeats:
            raise _ArgvFailure('runner_argv_unknown_option')
        if index + 1 >= len(raw) or raw[index + 1].startswith('--'):
            raise _ArgvFailure('runner_argv_option_value_missing')
        value = raw[index + 1]
        if name in scalars:
            if scalars[name] is not None:
                raise _ArgvFailure('runner_argv_duplicate_scalar')
            scalars[name] = value
        else:
            repeats[name].append(value)
        index += 2
    if single_file_count != 1:
        raise _ArgvFailure('runner_argv_single_file_count_invalid')
    if any(scalars[name] is None for name in scalar_names):
        raise _ArgvFailure('runner_argv_missing_scalar')
    if scalars['mode'] not in ('supervisor-v2', 'test-child-v2'):
        raise _ArgvFailure('runner_argv_mode_invalid')
    if not repeats['import-root']:
        raise _ArgvFailure('runner_argv_missing_import_root')
    if not repeats['expected-id']:
        raise _ArgvFailure('runner_argv_missing_expected_id')
    return types.SimpleNamespace(
        mode=scalars['mode'], workspace=scalars['workspace'],
        record_id=scalars['record-id'], suite_id=scalars['suite-id'],
        target=scalars['target'], import_root=repeats['import-root'],
        expected_id=repeats['expected-id'], single_file=True, raw_argv=raw,
    )


def _resolve_workspace_exact(raw_workspace):
    candidate = Path(raw_workspace)
    before = candidate.lstat()
    if _is_linklike(candidate, before):
        raise ValueError('workspace_is_linklike')
    workspace = candidate.resolve(strict=True)
    metadata = workspace.lstat()
    if _is_linklike(workspace, metadata) or not stat.S_ISDIR(metadata.st_mode):
        raise ValueError('workspace_not_regular_directory')
    if Path.cwd().resolve(strict=True) != workspace:
        raise ValueError('single_file_cwd_must_equal_workspace')
    return workspace


def _subprocess_environment():
    if os.name == 'nt':
        allowed = {'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'TEMP', 'TMP'}
        return {
            key: value for key, value in os.environ.items()
            if key.upper() in allowed
        }
    return {
        'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8',
        'PATH': '/usr/bin:/bin', 'PYTHONDONTWRITEBYTECODE': '1',
        'PYTHONNOUSERSITE': '1',
    }


def _popen_kwargs():
    result = {'close_fds': True}
    if os.name != 'nt':
        result['pass_fds'] = ()
    return result


def _extract_inventory(verifier_raw):
    parsed = ast.parse(verifier_raw, filename=VERIFIER_RELATIVE_PATH)
    values = []
    for node in parsed.body:
        target = None
        value = None
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target, value = node.target.id, node.value
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 and (
                isinstance(node.targets[0], ast.Name)):
            target, value = node.targets[0].id, node.value
        if target == 'PYC_INVENTORY' and value is not None:
            values.append(ast.literal_eval(value))
    if len(values) != 1:
        raise ValueError('pyc_verifier_inventory_literal_count_invalid')
    inventory = [dict(item) for item in values[0]]
    if (
        len(inventory) != PYC_INVENTORY_COUNT
        or any(not isinstance(item, dict) or set(item) != {
            'path', 'size_bytes', 'sha256'} for item in inventory)
        or [item['path'] for item in inventory]
        != sorted(set(item['path'] for item in inventory))
        or _canonical_sha256(inventory) != PYC_INVENTORY_SHA256
    ):
        raise ValueError('pyc_verifier_inventory_literal_invalid')
    return inventory


def _load_source_only_verifier(workspace, expected_binding):
    expected_identity = _binding_identity_matches_raw(
        expected_binding, 'pyc_verifier_expected')
    binding = _relative_binding(
        workspace, VERIFIER_RELATIVE_PATH, 'pyc_verifier')
    identity = _binding_identity_matches_raw(binding, 'pyc_verifier_load')
    raw = binding['raw']
    path = binding['path']
    if raw != expected_binding['raw'] or identity != expected_identity:
        raise ValueError('pyc_verifier_bound_record_drift_before_load')
    name = '_workspace_pyc_identity_verifier_exact_' + identity['sha256']
    module = types.ModuleType(name)
    module.__file__ = str(path)
    module.__package__ = 'audit_tools'
    module.__spec__ = importlib.machinery.ModuleSpec(
        name, loader=None, origin=str(path))
    exec(compile(raw, str(path), 'exec', dont_inherit=True, optimize=0),
         module.__dict__)
    if (module.__file__ != str(path)
            or getattr(module.__spec__, 'origin', None) != str(path)):
        raise ValueError('pyc_verifier_origin_mismatch')
    if module.inventory() != _extract_inventory(raw):
        raise ValueError('pyc_verifier_inventory_runtime_mismatch')
    if module.inventory_sha256() != PYC_INVENTORY_SHA256:
        raise ValueError('pyc_verifier_inventory_digest_mismatch')
    after = _relative_binding(
        workspace, VERIFIER_RELATIVE_PATH, 'pyc_verifier')
    if (
        _binding_identity_matches_raw(after, 'pyc_verifier_after_load')
        != identity
        or after['raw'] != raw
    ):
        raise ValueError('pyc_verifier_bound_record_drift_after_load')
    return module, binding


def _parse_marker(raw, prefix, label):
    lines = raw.splitlines()
    prefix_bytes = prefix.encode('ascii')
    if len(lines) != 1 or not lines[0].startswith(prefix_bytes):
        raise ValueError(label + '_marker_count_invalid')
    payload_raw = lines[0][len(prefix_bytes):]
    payload = _strict_json(payload_raw)
    if _canonical_json(payload) != payload_raw:
        raise ValueError(label + '_marker_not_canonical')
    return payload


def _broker_event(process, expected_marker, label):
    raw = process.stdout.readline()
    if raw == b'':
        raise ValueError(label + '_missing')
    if raw.startswith(BROKER_ERROR_MARKER.encode('ascii')):
        payload = _strict_json(raw[len(BROKER_ERROR_MARKER):])
        raise ValueError(str(payload.get('failure_code', 'pyc_broker_error')))
    return _parse_marker(raw, expected_marker, label)


def _broker_command(process, record_id, nonce, command, index, phase):
    payload = {
        'schema_version': 'workspace_pyc_identity_broker_command/v1',
        'record_id': record_id, 'nonce': nonce, 'command': command,
        'index': index, 'phase': phase,
    }
    process.stdin.write(_canonical_json(payload) + b'\n')
    process.stdin.flush()


_WRAPPER_OBSERVER_BOOTSTRAP = r'''import hashlib,json,os,stat,sys,types
from pathlib import Path
def linklike(path,info):
    attributes=int(getattr(info,'st_file_attributes',0) or 0)
    return bool(stat.S_ISLNK(info.st_mode) or attributes&getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',0x400) or getattr(os.path,'isjunction',lambda unused:False)(path))
def same(info):
    return (info.st_dev,info.st_ino,info.st_mode,info.st_size,getattr(info,'st_mtime_ns',None),getattr(info,'st_ctime_ns',None),getattr(info,'st_nlink',1),getattr(info,'st_uid',None),getattr(info,'st_gid',None),getattr(info,'st_file_attributes',None))
def cross(info):
    mode=stat.S_IFMT(info.st_mode) if os.name=='nt' else info.st_mode
    common=(info.st_dev,info.st_ino,mode,info.st_size,getattr(info,'st_mtime_ns',None))
    if os.name=='nt': return common+(getattr(info,'st_nlink',1),getattr(info,'st_uid',None),getattr(info,'st_gid',None),getattr(info,'st_file_attributes',None))
    return common+(getattr(info,'st_ctime_ns',None),getattr(info,'st_nlink',1),getattr(info,'st_uid',None),getattr(info,'st_gid',None),getattr(info,'st_file_attributes',None))
workspace=Path(sys.argv[1]).resolve(strict=True)
relative=sys.argv[2]
path=workspace
for part in relative.split('/'):
    path=path/part
    info=os.lstat(str(path))
    if linklike(path,info): raise SystemExit(81)
before=os.lstat(str(path))
if linklike(path,before) or not stat.S_ISREG(before.st_mode) or getattr(before,'st_nlink',1)!=1: raise SystemExit(82)
fd=os.open(str(path),os.O_RDONLY|getattr(os,'O_BINARY',0)|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_CLOEXEC',0))
try:
    os.set_inheritable(fd,False)
    opened_before=os.fstat(fd)
    if os.get_inheritable(fd) or not stat.S_ISREG(opened_before.st_mode) or getattr(opened_before,'st_nlink',1)!=1 or cross(before)!=cross(opened_before): raise SystemExit(83)
    chunks=[]
    while True:
        chunk=os.read(fd,1048576)
        if not chunk: break
        chunks.append(chunk)
    raw=b''.join(chunks)
    opened_after=os.fstat(fd)
    if same(opened_before)!=same(opened_after): raise SystemExit(83)
finally:
    os.close(fd)
after=os.lstat(str(path))
if linklike(path,after) or not stat.S_ISREG(after.st_mode) or getattr(after,'st_nlink',1)!=1: raise SystemExit(82)
if same(before)!=same(after) or cross(opened_after)!=cross(after): raise SystemExit(84)
if any(info.st_size!=len(raw) for info in (before,opened_before,opened_after,after)): raise SystemExit(86)
identity={'path':relative,'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
name='_formal_authority_v7_wrapper_observer_'+identity['sha256']
module=types.ModuleType(name)
module.__file__=str(path)
module.__package__='audit_tools'
module.__spec__=types.SimpleNamespace(origin=str(path))
exec(compile(raw,str(path),'exec',dont_inherit=True,optimize=0),module.__dict__)
if module.__file__!=str(path) or getattr(module.__spec__,'origin',None)!=str(path): raise SystemExit(85)
result=module.load_and_resolve_current_authority(workspace)
surface={'broker_argv_fields':[],'broker_channels':[],'broker_environment_fields':[],'broker_fds':[],'broker_modules_in_sys_modules':[],'broker_secrets':[],'broker_tokens':[]}
payload={'schema_version':'formal_admission_evidence_authority_resolution/v7','wrapper_identity':identity,'capability_surface':surface,'result':result}
sys.stdout.buffer.write(('OFFLINE_FORMAL_AUTHORITY_RESOLUTION_RESULT '+json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode('utf-8'));sys.stdout.buffer.flush()
'''


def _observe_production_wrapper(workspace, record_id, environment):
    parent_before = _relative_identity(
        workspace, WRAPPER_RELATIVE_PATH, 'production_wrapper')
    argv = [sys.executable, '-I', '-S', '-B', '-c',
            _WRAPPER_OBSERVER_BOOTSTRAP, str(workspace), WRAPPER_RELATIVE_PATH]
    completed = subprocess.run(
        argv, cwd=str(workspace), env=environment, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        timeout=COMMAND_TIMEOUT_SECONDS, check=False, **_popen_kwargs())
    parent_after = _relative_identity(
        workspace, WRAPPER_RELATIVE_PATH, 'production_wrapper')
    payload = _parse_marker(
        completed.stdout, WRAPPER_MARKER, 'production_wrapper')
    empty_surface = {
        'broker_argv_fields': [], 'broker_channels': [],
        'broker_environment_fields': [], 'broker_fds': [],
        'broker_modules_in_sys_modules': [], 'broker_secrets': [],
        'broker_tokens': [],
    }
    if (completed.returncode != 0 or completed.stderr != b''
            or parent_before != parent_after
            or payload.get('wrapper_identity') != parent_before
            or payload.get('capability_surface') != empty_surface
            or not isinstance(payload.get('result'), dict)):
        raise ValueError('production_wrapper_observation_invalid')
    return {
        'schema_version': PRODUCTION_WRAPPER_OBSERVATION_SCHEMA,
        'record_id': record_id, 'path': WRAPPER_RELATIVE_PATH,
        'parent_before': parent_before, 'parent_after': parent_after,
        'argv': argv, 'argv_sha256': _canonical_sha256(argv),
        'environment': dict(environment),
        'environment_sha256': _canonical_sha256(environment),
        'exit_code': completed.returncode, 'marker_count': 1,
        'marker_prefix': WRAPPER_MARKER, 'payload': payload,
        'payload_sha256': _canonical_sha256(payload),
        'stdout': _stream_identity(completed.stdout),
        'stderr': _stream_identity(completed.stderr),
    }


def _child_argv(args, workspace, runner_binding):
    live = _relative_binding(
        workspace, runner_binding['path'], 'runner_test_child_expected')
    if live['identity'] != {
        'path': runner_binding['path'],
        'size_bytes': runner_binding['size_bytes'],
        'sha256': runner_binding['sha256'],
    }:
        raise ValueError('runner_test_child_expected_identity_drift')
    argv = _execution_component_argv(
        workspace, runner_binding['path'], live, 'runner', [
        '--single-file', '--mode', 'test-child-v2',
        '--workspace', args.workspace, '--record-id', args.record_id,
        '--suite-id', args.suite_id, '--target', args.target,
    ])
    for value in args.import_root:
        argv.extend(('--import-root', value))
    for value in args.expected_id:
        argv.extend(('--expected-id', value))
    return argv


def _run_test_child(args, workspace, environment, runner_binding):
    argv = _child_argv(args, workspace, runner_binding)
    completed = subprocess.run(
        argv, cwd=str(workspace), env=environment, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        timeout=COMMAND_TIMEOUT_SECONDS, check=False, **_popen_kwargs())
    payload = _parse_marker(completed.stdout, CHILD_MARKER, 'test_child')
    if payload.get('runner_execution_binding') != runner_binding:
        raise ValueError('runner_test_child_returned_binding_mismatch')
    if (payload.get('schema_version') != CHILD_SCHEMA_VERSION
            or payload.get('record_id') != args.record_id
            or payload.get('suite_id') != args.suite_id
            or completed.returncode != payload.get('exit')):
        raise ValueError('test_child_contract_invalid')
    return argv, completed, payload


def _supervisor_report(args):
    workspace = _resolve_workspace_exact(args.workspace)
    environment = _subprocess_environment()
    runner_binding = _current_runner_execution_binding(workspace)
    broker_binding = _relative_binding(
        workspace, BROKER_RELATIVE_PATH, 'pyc_broker')
    broker_identity = _binding_identity_matches_raw(
        broker_binding, 'pyc_broker_expected')
    broker_execution_binding = {
        'schema_version': EXECUTION_COMPONENT_BOOTSTRAP_SCHEMA,
        'component_kind': 'broker',
        'path': broker_identity['path'],
        'size_bytes': broker_identity['size_bytes'],
        'sha256': broker_identity['sha256'],
        'bootstrap_sha256': _EXECUTION_COMPONENT_BOOTSTRAP_SHA256,
    }
    verifier_binding = _relative_binding(
        workspace, VERIFIER_RELATIVE_PATH, 'pyc_verifier')
    verifier_identity = _binding_identity_matches_raw(
        verifier_binding, 'pyc_verifier_expected')
    inventory = _extract_inventory(verifier_binding['raw'])
    nonce = secrets.token_hex(32)
    broker_argv = _execution_component_argv(
        workspace, BROKER_RELATIVE_PATH, broker_binding, 'broker', [
        '--mode', 'hold-open-v1', '--workspace', str(workspace),
        '--record-id', args.record_id,
    ])
    broker = None
    try:
        broker = subprocess.Popen(
            broker_argv, cwd=str(workspace), env=environment,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, **_popen_kwargs())
        initial = {
            'schema_version': 'workspace_pyc_identity_broker_init/v1',
            'record_id': args.record_id, 'nonce': nonce,
            'inventory': inventory, 'inventory_sha256': PYC_INVENTORY_SHA256,
        }
        broker.stdin.write(_canonical_json(initial) + b'\n')
        broker.stdin.flush()
        ready = _broker_event(broker, BROKER_READY_MARKER, 'pyc_broker_ready')
        verifier, verifier_execution_binding = _load_source_only_verifier(
            workspace, verifier_binding)
        wrapper_observation = _observe_production_wrapper(
            workspace, args.record_id, environment)
        _broker_command(broker, args.record_id, nonce, 'checkpoint', 1,
                        'AFTER_PRODUCTION_WRAPPER')
        checkpoints = [_broker_event(
            broker, BROKER_CHECKPOINT_MARKER,
            'pyc_broker_after_production_wrapper')]
        child_argv, child_completed, child_payload = _run_test_child(
            args, workspace, environment, runner_binding)
        _broker_command(broker, args.record_id, nonce, 'checkpoint', 2,
                        'AFTER_TEST_CHILD')
        checkpoints.append(_broker_event(
            broker, BROKER_CHECKPOINT_MARKER, 'pyc_broker_after_test_child'))
        _broker_command(broker, args.record_id, nonce, 'finalize', 3, 'FINAL')
        broker.stdin.close()
        final = _broker_event(broker, BROKER_FINAL_MARKER, 'pyc_broker_final')
        broker_exit = broker.wait(timeout=COMMAND_TIMEOUT_SECONDS)
        broker_stderr = broker.stderr.read()
        broker_stdout_tail = broker.stdout.read()
        if (broker_exit != 0 or broker_stderr != b''
                or broker_stdout_tail != b''):
            raise ValueError('pyc_broker_exit_or_stderr_invalid')
        verifier_result = verifier.verify_transcript(
            record_id=args.record_id, nonce=nonce, ready=ready,
            checkpoints=checkpoints, final=final,
            child_capability_surface=child_payload.get(
                'child_capability_surface'),
            broker_execution_binding=broker_execution_binding)
        if verifier_result.get('validated_pass') is not True:
            raise ValueError('pyc_verifier_transcript_invalid')
        broker_after = _relative_binding(
            workspace, BROKER_RELATIVE_PATH,
            'pyc_broker_after_transcript')
        if (
            broker_after['identity'] != broker_identity
            or broker_after['raw'] != broker_binding['raw']
        ):
            raise ValueError('pyc_broker_bound_record_drift_after_transcript')
        verifier_after = _relative_binding(
            workspace, VERIFIER_RELATIVE_PATH,
            'pyc_verifier_after_transcript')
        if (
            verifier_after['identity'] != verifier_identity
            or verifier_after['raw'] != verifier_execution_binding['raw']
        ):
            raise ValueError(
                'pyc_verifier_bound_record_drift_after_transcript')
        transcript = {
            'schema_version': PYC_BROKER_TRANSCRIPT_SCHEMA,
            'record_id': args.record_id,
            'broker_artifact_identity': broker_identity,
            'broker_execution_binding': broker_execution_binding,
            'verifier_artifact_identity': (
                verifier_execution_binding['identity']),
            'argv': broker_argv, 'argv_sha256': _canonical_sha256(broker_argv),
            'environment': dict(environment),
            'environment_sha256': _canonical_sha256(environment),
            'ready': ready, 'checkpoints': checkpoints, 'final': final,
            'stderr': _stream_identity(broker_stderr),
            'exit_code': broker_exit,
        }
        report = dict(child_payload)
        report.update({
            'schema_version': SCHEMA_VERSION, 'runner_kind': RUNNER_KIND,
            'mode': 'supervisor-v2',
            'child_schema_version': CHILD_SCHEMA_VERSION,
            'child_marker_prefix': CHILD_MARKER,
            'child_argv': child_argv,
            'child_argv_sha256': _canonical_sha256(child_argv),
            'child_stdout': _stream_identity(child_completed.stdout),
            'child_stderr': _stream_identity(child_completed.stderr),
            'runner_execution_binding': runner_binding,
            'child_runner_execution_binding': child_payload.get(
                'runner_execution_binding'),
            'pyc_broker_transcript': transcript,
            'pyc_verifier_result': verifier_result,
            'production_wrapper_observation': wrapper_observation,
            'supervisor_validated_pass': child_payload.get('exit') == 0,
        })
        if child_completed.stderr:
            sys.stderr.buffer.write(child_completed.stderr)
            sys.stderr.buffer.flush()
        return report
    finally:
        nonce = None
        if broker is not None and broker.poll() is None:
            try:
                broker.kill()
            except OSError:
                pass
            try:
                broker.wait(timeout=5)
            except BaseException:
                pass


def _child_capability_preflight():
    forbidden_environment = sorted(
        key for key in os.environ
        if 'PYC_BROKER' in key.upper() or 'BROKER_NONCE' in key.upper())
    forbidden_argv = [
        value for value in sys.argv
        if 'broker-nonce' in value.casefold()
        or 'broker-token' in value.casefold()
        or 'broker-fd' in value.casefold()
    ]
    forbidden_modules = sorted(
        name for name in sys.modules
        if name.endswith('workspace_pyc_identity_broker_v1')
        or name.endswith('workspace_pyc_identity_verifier_v1'))
    if forbidden_environment or forbidden_argv or forbidden_modules:
        raise ValueError('pyc_test_child_capability_surface_nonempty')


def _preload_guard_safe_stdlib(raw_workspace):
    if (
            not sys.flags.isolated
            or not sys.flags.no_site
            or not sys.dont_write_bytecode):
        raise ValueError('test_child_stdlib_preload_process_contract_invalid')
    if dict(os.environ) != _subprocess_environment():
        raise ValueError('test_child_stdlib_preload_environment_invalid')
    workspace = _resolve_workspace_exact(raw_workspace)
    _current_runner_execution_binding(workspace)
    for raw_entry in sys.path:
        try:
            entry = Path(raw_entry).resolve(strict=True)
        except (OSError, TypeError, ValueError):
            continue
        if _is_relative_to(entry, workspace):
            raise ValueError('test_child_stdlib_preload_workspace_path_invalid')

    path_object = sys.path
    path_entries = tuple(sys.path)
    meta_path_snapshot = _meta_path_snapshot()
    import dataclasses as trusted_dataclasses
    import typing as trusted_typing
    if (
            sys.path is not path_object
            or tuple(sys.path) != path_entries
            or not _meta_path_matches(meta_path_snapshot)):
        raise ValueError('test_child_stdlib_preload_import_state_changed')

    stdlib_root = Path(os.__file__).resolve(strict=True).parent
    for name, module in (
            ('dataclasses', trusted_dataclasses), ('typing', trusted_typing)):
        spec = getattr(module, '__spec__', None)
        origin = getattr(spec, 'origin', None)
        module_file = getattr(module, '__file__', None)
        if (
                sys.modules.get(name) is not module
                or type(module) is not types.ModuleType
                or not isinstance(origin, str)
                or not isinstance(module_file, str)):
            raise ValueError('test_child_stdlib_preload_identity_invalid:' + name)
        origin_path = Path(origin)
        module_path = Path(module_file)
        try:
            origin_metadata = origin_path.lstat()
            module_metadata = module_path.lstat()
            resolved_origin = origin_path.resolve(strict=True)
            resolved_module = module_path.resolve(strict=True)
        except OSError as error:
            raise ValueError(
                'test_child_stdlib_preload_identity_invalid:' + name
            ) from error
        if (
                _is_linklike(origin_path, origin_metadata)
                or _is_linklike(module_path, module_metadata)
                or not stat.S_ISREG(origin_metadata.st_mode)
                or not stat.S_ISREG(module_metadata.st_mode)
                or resolved_origin != resolved_module
                or not _is_relative_to(resolved_origin, stdlib_root)
                or _is_relative_to(resolved_origin, workspace)):
            raise ValueError('test_child_stdlib_preload_identity_invalid:' + name)


def _failure_report(options, error):
    return {
        'schema_version': SCHEMA_VERSION, 'runner_kind': RUNNER_KIND,
        'mode': getattr(options, 'mode', None),
        'record_id': getattr(options, 'record_id', ''),
        'suite_id': getattr(options, 'suite_id', ''),
        'exit': 2, 'result': 'FAIL',
        'failures': [getattr(error, 'code', str(error))],
        'pyc_broker_transcript': None, 'pyc_verifier_result': None,
        'production_wrapper_observation': None,
        'supervisor_validated_pass': False,
    }


def main(argv=None):
    options = None
    try:
        options = _strict_raw_options(argv)
        if options.mode == 'test-child-v2':
            _child_capability_preflight()
            _preload_guard_safe_stdlib(options.workspace)
            report = _single_file_report(options)
            print(CHILD_MARKER + _canonical_json(report).decode('utf-8'),
                  flush=True)
            return report['exit']
        report = _supervisor_report(options)
    except BaseException as error:
        report = _failure_report(options, error)
        traceback.print_exc(file=sys.stderr)
    print(SINGLE_FILE_MARKER + _canonical_json(report).decode('utf-8'),
          flush=True)
    return report['exit']


if __name__ == '__main__':
    raise SystemExit(main())

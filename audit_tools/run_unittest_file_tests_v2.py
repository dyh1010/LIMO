"""Two-process isolated runner for one stdlib ``unittest`` source file.

``supervisor-v2`` owns the host-attestation broker and is the only mode that
emits the public marker.  ``test-child-v2`` runs the untrusted test file with a
source-only loader/audit guard and emits an internal marker captured by the
supervisor.  Broker capabilities are never placed in child argv, environment,
inherited descriptors, modules, globals, or files.
"""

import argparse
import ast
import hashlib
import importlib.machinery
import importlib.util
import json
import os
import secrets
import stat
import subprocess
import sys
import tempfile
import traceback
import types
import unittest
from pathlib import Path


SINGLE_FILE_MARKER = 'OFFLINE_UNITTEST_FILE_RESULT '
CHILD_MARKER = 'OFFLINE_UNITTEST_TEST_CHILD_RESULT '
SCHEMA_VERSION = 'offline_unittest_file_result/v2'
CHILD_SCHEMA_VERSION = 'offline_unittest_test_child_result/v2'
RUNNER_KIND = 'stdlib_unittest_single_file_supervisor_v2'
CHILD_RUNNER_KIND = 'stdlib_unittest_single_file_test_child_v2'
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
_MISSING_ATTRIBUTE = object()
_WORKSPACE_AUDIT_GUARD_USED = False
_WATCHED_PYTHON_ENV = (
    'PYTHONHOME',
    'PYTHONINSPECT',
    'PYTHONPATH',
    'PYTHONSTARTUP',
    'PYTHONUSERBASE',
)
_RECORDED_PYTHON_ENV = _WATCHED_PYTHON_ENV + (
    'PYTHONDONTWRITEBYTECODE',
    'PYTHONNOUSERSITE',
    'PYTHONSAFEPATH',
)


def _is_relative_to(path, root):
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _stable_path(path):
    return os.path.normcase(os.path.abspath(os.fspath(path)))


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


def _read_file_binding(path, label):
    """Return raw bytes and their identity from one stable regular FD."""
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
        payload = b''.join(chunks)
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
    if len(payload) != opened_after.st_size:
        raise ValueError('{}_size_changed_while_reading'.format(label))
    identity = {
        'size_bytes': len(payload),
        'sha256': hashlib.sha256(payload).hexdigest(),
    }
    if (
        len(payload) != identity['size_bytes']
        or hashlib.sha256(payload).hexdigest() != identity['sha256']
    ):
        raise ValueError('{}_bound_identity_mismatch'.format(label))
    return {'raw': payload, 'identity': identity}


def _read_file_bytes(path, label):
    return _read_file_binding(path, label)['raw']


def _file_identity(path, label):
    binding = _read_file_binding(path, label)
    path = Path(path)
    return {
        'path': str(path),
        'size_bytes': binding['identity']['size_bytes'],
        'sha256': binding['identity']['sha256'],
        'regular_file': True,
        'is_symlink': False,
    }


def _relative_binding(workspace, relative, label):
    path = _lexical_workspace_path(relative, workspace, label)
    binding = _read_file_binding(path, label)
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
    expected_path = _lexical_workspace_path(
        relative, workspace, component_kind + '_execution_component_path')
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


def _resolve_workspace(raw_workspace):
    input_path = Path(raw_workspace)
    if input_path.is_symlink():
        raise ValueError('workspace_is_link')
    workspace = input_path.resolve(strict=True)
    metadata = workspace.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ValueError('workspace_is_not_regular_directory')
    if Path.cwd().resolve(strict=True) != workspace:
        raise ValueError('cwd_must_equal_workspace')
    return workspace


def _lexical_workspace_path(raw_path, workspace, label):
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = workspace / candidate
    candidate = Path(os.path.abspath(os.fspath(candidate)))
    if not _is_relative_to(candidate, workspace):
        raise ValueError('{}_outside_workspace'.format(label))
    current = workspace
    for component in candidate.relative_to(workspace).parts:
        current = current / component
        metadata = current.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            raise ValueError('{}_path_component_is_link'.format(label))
    resolved = candidate.resolve(strict=True)
    if resolved != candidate:
        raise ValueError('{}_resolved_path_mismatch'.format(label))
    return resolved


def _resolve_target(raw_target, workspace):
    target = _lexical_workspace_path(raw_target, workspace, 'target')
    relative = target.relative_to(workspace).as_posix()
    binding = _read_file_binding(target, 'target')
    binding = {
        'path': target, 'raw': binding['raw'],
        'identity': {
            'path': relative,
            'size_bytes': binding['identity']['size_bytes'],
            'sha256': binding['identity']['sha256'],
        },
    }
    return target, relative, binding


def _resolve_import_roots(raw_roots, workspace):
    roots = []
    seen = set()
    for sequence, raw_root in enumerate(raw_roots):
        root = _lexical_workspace_path(
            raw_root, workspace, 'import_root_{}'.format(sequence))
        metadata = root.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise ValueError('import_root_is_not_regular_directory')
        key = _stable_path(root)
        if key in seen:
            raise ValueError('duplicate_import_root')
        seen.add(key)
        roots.append(root)
    if not roots:
        raise ValueError('missing_import_root')
    return roots


def _executable_identity():
    """Bind the interpreter entry, every symlink hop and its real target."""
    if not sys.executable:
        raise ValueError('sys_executable_missing')
    entry = Path(os.path.abspath(sys.executable))
    current = entry
    seen = set()
    link_chain = []
    for _unused in range(64):
        key = _stable_path(current)
        if key in seen:
            raise ValueError('sys_executable_link_cycle')
        seen.add(key)
        metadata = current.lstat()
        if not stat.S_ISLNK(metadata.st_mode):
            break
        raw_destination = os.readlink(os.fspath(current))
        destination = Path(raw_destination)
        if not destination.is_absolute():
            destination = current.parent / destination
        destination = Path(os.path.abspath(os.fspath(destination)))
        link_chain.append({
            'path': str(current),
            'link_target': raw_destination,
            'next_path': str(destination),
        })
        current = destination
    else:
        raise ValueError('sys_executable_link_chain_too_long')

    resolved = entry.resolve(strict=True)
    if resolved != current.resolve(strict=True):
        raise ValueError('sys_executable_link_chain_resolution_mismatch')
    target = _file_identity(resolved, 'sys_executable_target')
    entry_metadata = entry.lstat()
    return {
        'entry_path': str(entry),
        'entry_is_symlink': stat.S_ISLNK(entry_metadata.st_mode),
        'entry_lstat_size_bytes': entry_metadata.st_size,
        'entry_link_chain': link_chain,
        'resolved_target': target,
    }


def _environment_snapshot():
    ros_keys = sorted(key for key in os.environ if key.startswith('ROS_'))
    keys = tuple(sorted(set(_RECORDED_PYTHON_ENV + tuple(ros_keys))))
    values = {key: os.environ.get(key) for key in keys}
    contaminated = sorted(
        key for key in _WATCHED_PYTHON_ENV
        if os.environ.get(key) not in (None, ''))
    contaminated.extend(
        key for key in ros_keys if os.environ.get(key) not in (None, ''))
    return {
        'values': values,
        'watched_keys': list(keys),
        'contaminated_keys': sorted(set(contaminated)),
        'clean': not contaminated,
    }


def _meta_path_snapshot():
    return tuple(id(item) for item in sys.meta_path)


class _WorkspaceLoaderGuard:
    """Reject workspace bytecode while binding source bytes read by loaders."""

    _LOADER_NAMES = ('SourceFileLoader', 'SourcelessFileLoader')

    def __init__(self, workspace, report):
        self.workspace = workspace
        self.report = report
        self.blocked_paths = set()
        self.source_reads = {}
        self.states = []
        self.wrappers = {}
        self.replaced = False
        self.restored = False
        self.audit_hook_active = False
        self._audit_probe_token = object()
        self.bytecode_inventory_before = None
        self.bytecode_inode_paths = {}
        self.bytecode_inventory_stable = False

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
        self.bytecode_inventory_before = inventory
        self.bytecode_inode_paths = {
            (item['device'], item['inode']): item['path']
            for item in inventory
        }

    def _workspace_path(self, raw_path):
        try:
            candidate = Path(os.fsdecode(raw_path))
        except (TypeError, ValueError):
            return None
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
                relative = item.relative_to(self.workspace)
                return item, relative, relative.as_posix()
        return None

    def _guard_is_installed(self):
        installed = True
        for loader_name, loader_class, _raw_attribute, _original in self.states:
            if getattr(importlib.machinery, loader_name, None) is not loader_class:
                installed = False
            wrapper = self.wrappers.get(loader_class)
            if loader_class.__dict__.get(
                    'get_data', _MISSING_ATTRIBUTE) is not wrapper:
                installed = False
        if not installed:
            self.replaced = True
        return installed

    def _read(self, original, loader, raw_path):
        if not self._guard_is_installed():
            raise ValueError('workspace_loader_guard_replaced_during_execution')
        workspace_path = self._workspace_path(raw_path)
        if workspace_path is not None:
            candidate, relative, relative_text = workspace_path
            is_bytecode = (
                candidate.suffix.casefold() == '.pyc'
                or any(part.casefold() == '__pycache__'
                       for part in relative.parts)
            )
            if is_bytecode:
                self.blocked_paths.add(relative_text)
                raise FileNotFoundError(
                    'workspace_bytecode_blocked:{}'.format(relative_text))

        payload = original(loader, raw_path)
        if (workspace_path is not None
                and workspace_path[0].suffix.casefold() == '.py'):
            relative_text = workspace_path[2]
            identity = {
                'path': relative_text,
                'size_bytes': len(payload),
                'sha256': hashlib.sha256(payload).hexdigest(),
            }
            previous = self.source_reads.get(relative_text)
            if previous is not None and previous != identity:
                raise ValueError(
                    'workspace_source_changed_during_execution:{}'.format(
                        relative_text))
            self.source_reads[relative_text] = identity
        return payload

    def record_source_bytes(self, path, raw):
        relative = Path(path).resolve(strict=True).relative_to(
            self.workspace).as_posix()
        identity = {
            'path': relative,
            'size_bytes': len(raw),
            'sha256': hashlib.sha256(raw).hexdigest(),
        }
        previous = self.source_reads.get(relative)
        if previous is not None and previous != identity:
            raise ValueError(
                'workspace_source_changed_during_execution:{}'.format(
                    relative))
        self.source_reads[relative] = identity

    def _audit_hook(self, event, arguments):
        if event == 'limo.workspace_loader_guard_probe':
            if arguments and arguments[0] is self._audit_probe_token:
                self.audit_hook_active = True
            return
        if event != 'open' or not arguments:
            return
        workspace_path = self._workspace_path(arguments[0])
        if workspace_path is not None:
            candidate, relative, relative_text = workspace_path
        else:
            candidate = None
            relative = None
            relative_text = None
        if relative is not None and self._is_bytecode_relative(relative):
            self.blocked_paths.add(relative_text)
            raise PermissionError(
                'workspace_bytecode_open_blocked:{}'.format(relative_text))
        try:
            raw_candidate = Path(os.fsdecode(arguments[0]))
            if not raw_candidate.is_absolute():
                raw_candidate = self.workspace / raw_candidate
            raw_candidate = Path(os.path.abspath(os.fspath(raw_candidate)))
            metadata = raw_candidate.stat()
        except (OSError, RuntimeError, TypeError, ValueError):
            return
        inode_path = self.bytecode_inode_paths.get(
            (int(metadata.st_dev), int(metadata.st_ino)))
        if inode_path is not None:
            self.blocked_paths.add(inode_path)
            raise PermissionError(
                'workspace_bytecode_inode_alias_blocked:{}'.format(
                    inode_path))

    def _install_audit_hook(self):
        global _WORKSPACE_AUDIT_GUARD_USED
        if _WORKSPACE_AUDIT_GUARD_USED:
            raise ValueError('workspace_pyc_audit_hook_process_reuse_forbidden')
        sys.addaudithook(self._audit_hook)
        sys.audit('limo.workspace_loader_guard_probe', self._audit_probe_token)
        if not self.audit_hook_active:
            raise ValueError('workspace_pyc_audit_hook_install_failed')
        _WORKSPACE_AUDIT_GUARD_USED = True

    def _publish(self):
        self.report['workspace_pyc_bytes_read'] = 0
        self.report['workspace_pyc_attempts_blocked'] = sorted(
            self.blocked_paths)
        self.report['workspace_source_reads'] = [
            self.source_reads[path] for path in sorted(self.source_reads)]
        self.report['workspace_loader_guard_restored'] = self.restored
        self.report['workspace_pyc_audit_hook_active'] = self.audit_hook_active
        self.report['workspace_pyc_inode_policy'] = WORKSPACE_PYC_INODE_POLICY
        self.report['workspace_pyc_inventory_count'] = len(
            self.bytecode_inventory_before or ())
        self.report['workspace_pyc_inventory_stable'] = (
            self.bytecode_inventory_stable)

    def _restore(self):
        if self.bytecode_inventory_before is not None:
            try:
                self.bytecode_inventory_stable = (
                    self._collect_bytecode_inventory()
                    == self.bytecode_inventory_before)
            except BaseException:
                self.bytecode_inventory_stable = False
        restore_failed = False
        for loader_name, loader_class, raw_attribute, _unused_original in reversed(
                self.states):
            try:
                setattr(importlib.machinery, loader_name, loader_class)
                if raw_attribute is _MISSING_ATTRIBUTE:
                    if 'get_data' in loader_class.__dict__:
                        delattr(loader_class, 'get_data')
                else:
                    setattr(loader_class, 'get_data', raw_attribute)
            except BaseException:
                restore_failed = True

        restored = not restore_failed
        for loader_name, loader_class, raw_attribute, original in self.states:
            try:
                if getattr(importlib.machinery, loader_name) is not loader_class:
                    restored = False
                current_raw = loader_class.__dict__.get(
                    'get_data', _MISSING_ATTRIBUTE)
                if current_raw is not raw_attribute:
                    restored = False
                if getattr(loader_class, 'get_data') is not original:
                    restored = False
            except BaseException:
                restored = False
        self.restored = restored

    def __enter__(self):
        try:
            self._install_bytecode_inventory()
            for loader_name in self._LOADER_NAMES:
                loader_class = getattr(importlib.machinery, loader_name)
                raw_attribute = loader_class.__dict__.get(
                    'get_data', _MISSING_ATTRIBUTE)
                original = getattr(loader_class, 'get_data')
                self.states.append(
                    (loader_name, loader_class, raw_attribute, original))

                def guarded_get_data(loader, raw_path, _original=original):
                    return self._read(_original, loader, raw_path)

                self.wrappers[loader_class] = guarded_get_data
            for loader_class, wrapper in self.wrappers.items():
                setattr(loader_class, 'get_data', wrapper)
            self._install_audit_hook()
            if not self._guard_is_installed():
                raise ValueError('workspace_loader_guard_install_mismatch')
        except BaseException:
            self._restore()
            self._publish()
            raise
        return self

    def __exit__(self, exception_type, exception, unused_traceback):
        self._guard_is_installed()
        self._restore()
        self._publish()
        if self.replaced:
            raise ValueError('workspace_loader_guard_replaced_during_execution')
        if not self.restored:
            raise ValueError('workspace_loader_guard_not_restored')
        if not self.bytecode_inventory_stable:
            raise ValueError('workspace_pyc_inventory_changed_during_execution')
        return False


def _flatten_suite(suite):
    tests = []
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            tests.extend(_flatten_suite(item))
        else:
            tests.append(item)
    return tests


def _normalized_test_id(test, target_relative):
    if not isinstance(test, unittest.TestCase):
        raise ValueError('collected_item_is_not_unittest_testcase')
    method = getattr(test, '_testMethodName', None)
    class_name = test.__class__.__qualname__
    if (not isinstance(method, str) or not method
            or not isinstance(class_name, str) or not class_name
            or '<locals>' in class_name):
        raise ValueError('collected_test_id_not_normalizable')
    return '{}::{}.{}'.format(target_relative, class_name, method)


def _discover_tests(module, target_relative):
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(module)
    if loader.errors:
        raise ValueError('unittest_loader_errors')
    ordered = []
    by_id = {}
    for test in _flatten_suite(suite):
        normalized = _normalized_test_id(test, target_relative)
        if normalized in by_id:
            raise ValueError('duplicate_collected_test_id:{}'.format(normalized))
        by_id[normalized] = test
        ordered.append(normalized)
    if not ordered:
        raise ValueError('zero_discovered_tests')
    return ordered, by_id


class _StrictResult(unittest.TestResult):
    def __init__(self, target_relative):
        super().__init__()
        self.target_relative = target_relative
        self.executed_ids = []
        self.outcomes = {}
        self.infrastructure_errors = []

    def _normalized(self, test):
        try:
            return _normalized_test_id(test, self.target_relative)
        except (AttributeError, TypeError, ValueError):
            return None

    def _record(self, test, outcome):
        normalized = self._normalized(test)
        if normalized is None:
            self.infrastructure_errors.append(
                'unmapped_result:{}'.format(test.id()))
            return
        previous = self.outcomes.get(normalized)
        if previous == 'failed':
            return
        self.outcomes[normalized] = outcome

    def startTest(self, test):
        normalized = self._normalized(test)
        if normalized is None:
            self.infrastructure_errors.append(
                'unmapped_started_test:{}'.format(test.id()))
        else:
            self.executed_ids.append(normalized)
        super().startTest(test)

    def stopTest(self, test):
        normalized = self._normalized(test)
        if normalized is not None and normalized not in self.outcomes:
            self.outcomes[normalized] = 'failed'
            self.infrastructure_errors.append(
                'test_stopped_without_outcome:{}'.format(normalized))
        super().stopTest(test)

    def addSuccess(self, test):
        super().addSuccess(test)
        self._record(test, 'passed')

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self._record(test, 'skipped')

    def addFailure(self, test, error):
        super().addFailure(test, error)
        self._record(test, 'failed')

    def addError(self, test, error):
        super().addError(test, error)
        self._record(test, 'failed')

    def addExpectedFailure(self, test, error):
        super().addExpectedFailure(test, error)
        self._record(test, 'failed')
        normalized = self._normalized(test) or test.id()
        self.infrastructure_errors.append(
            'expected_failure_forbidden:{}'.format(normalized))

    def addUnexpectedSuccess(self, test):
        super().addUnexpectedSuccess(test)
        self._record(test, 'failed')
        normalized = self._normalized(test) or test.id()
        self.infrastructure_errors.append(
            'unexpected_success:{}'.format(normalized))

    def addSubTest(self, test, subtest, error):
        super().addSubTest(test, subtest, error)
        if error is not None:
            self._record(test, 'failed')


class _ProcessStreamCapture:
    """Capture Python, child-process and native writes to stdout/stderr."""
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
        self.stdout = self._stdout_file.read().decode('utf-8', 'backslashreplace')
        self.stderr = self._stderr_file.read().decode('utf-8', 'backslashreplace')
        self._stdout_file.close()
        self._stderr_file.close()
        return False


def _load_exact_module(target, binding, loader_guard):
    identity = _binding_identity_matches_raw(binding, 'target_load')
    raw = binding['raw']
    module_name = '_offline_unittest_{}'.format(identity['sha256'][:24])
    if module_name in sys.modules:
        raise ValueError('exact_test_module_name_preloaded')
    module = types.ModuleType(module_name)
    module.__file__ = str(target)
    module.__package__ = ''
    module.__spec__ = importlib.machinery.ModuleSpec(
        module_name, loader=None, origin=str(target))
    sys.modules[module_name] = module
    try:
        loader_guard.record_source_bytes(target, raw)
        exec(compile(raw, str(target), 'exec', dont_inherit=True, optimize=0),
             module.__dict__)
    except BaseException:
        sys.modules.pop(module_name, None)
        raise
    module_file = Path(module.__file__).resolve(strict=True)
    if module_file != target:
        raise ValueError('loaded_test_module_path_mismatch')
    module_spec_origin = Path(module.__spec__.origin).resolve(strict=True)
    if module_spec_origin != target:
        raise ValueError('loaded_test_module_spec_origin_mismatch')
    return module_name, module


def _diagnose_result(result):
    lines = []
    for label, entries in (('FAIL', result.failures), ('ERROR', result.errors)):
        for test, detail in entries:
            lines.append('{} {}\n{}'.format(label, test.id(), detail))
    for test, detail in result.expectedFailures:
        lines.append('EXPECTED_FAILURE {}\n{}'.format(test.id(), detail))
    for test in result.unexpectedSuccesses:
        lines.append('UNEXPECTED_SUCCESS {}'.format(test.id()))
    lines.extend(result.infrastructure_errors)
    return lines


def _base_report(args):
    requested_ids = list(args.expected_id or ())
    return {
        'schema_version': CHILD_SCHEMA_VERSION,
        'runner_kind': CHILD_RUNNER_KIND,
        'mode': 'test-child-v2',
        'record_id': args.record_id,
        'suite_id': args.suite_id,
        'selection_mode': 'selected_ids' if requested_ids else 'whole_file',
        'workspace': '',
        'import_roots': [],
        'path': '',
        'resolved_path': '',
        'size_bytes': 0,
        'sha256': '',
        'target_identity_before': None,
        'target_identity_after': None,
        'requested_ids': requested_ids,
        'expected_ids': [],
        'executed_ids': [],
        'passed_ids': [],
        'failed_ids': [],
        'skipped_ids': [],
        'discovered_ids': [],
        'discovered': 0,
        'collected': 0,
        'passed': 0,
        'failed': 0,
        'skipped': 0,
        'exit': 1,
        'result': 'FAIL',
        'failures': [],
        'executable': None,
        'python': None,
        'environment': None,
        'environment_unchanged_during_execution': False,
        'environment_restored': False,
        'workspace_bytecode_policy': WORKSPACE_BYTECODE_POLICY,
        'workspace_pyc_bytes_read': 0,
        'workspace_pyc_attempts_blocked': [],
        'workspace_source_reads': [],
        'workspace_loader_guard_restored': False,
        'workspace_pyc_audit_hook_active': False,
        'workspace_pyc_inode_policy': WORKSPACE_PYC_INODE_POLICY,
        'workspace_pyc_inventory_count': 0,
        'workspace_pyc_inventory_stable': False,
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
        'stdout_marker_count': 1,
    }


def _single_file_report(args):
    report = _base_report(args)
    diagnostics = []
    baseline_path = list(sys.path)
    baseline_meta_path = list(sys.meta_path)
    baseline_meta_ids = _meta_path_snapshot()
    baseline_cwd = Path.cwd().resolve(strict=True)
    baseline_environment_object = os.environ
    baseline_environment_values = dict(os.environ)
    baseline_environment = _environment_snapshot()
    executable_before = None
    target = None
    target_before = None
    capture = None
    module_name = None
    try:
        if not sys.flags.isolated:
            raise ValueError('runner_requires_python_isolated_mode')
        if not sys.flags.no_site:
            raise ValueError('runner_requires_python_no_site_mode')
        if not sys.dont_write_bytecode:
            raise ValueError('runner_requires_python_no_bytecode_mode')
        if not baseline_environment['clean']:
            raise ValueError('runner_environment_contaminated')
        requested_ids = report['requested_ids']
        if len(requested_ids) != len(set(requested_ids)):
            raise ValueError('duplicate_expected_test_id')

        workspace = _resolve_workspace(args.workspace)
        report['runner_execution_binding'] = (
            _current_runner_execution_binding(workspace))
        target, target_relative, target_binding = _resolve_target(
            args.target, workspace)
        target_bound_identity = _binding_identity_matches_raw(
            target_binding, 'target_expected')
        target_before = {
            'path': str(target),
            'size_bytes': target_bound_identity['size_bytes'],
            'sha256': target_bound_identity['sha256'],
            'regular_file': True,
            'is_symlink': False,
        }
        roots = _resolve_import_roots(args.import_root, workspace)
        executable_before = _executable_identity()

        report['workspace'] = str(workspace)
        report['import_roots'] = [
            root.relative_to(workspace).as_posix() or '.' for root in roots]
        report['path'] = target_relative
        report['resolved_path'] = str(target)
        report['size_bytes'] = target_before['size_bytes']
        report['sha256'] = target_before['sha256']
        report['target_identity_before'] = target_before
        executable_report = {
            **executable_before,
            'isolated': bool(sys.flags.isolated),
            'no_bytecode': bool(sys.dont_write_bytecode),
            'version': [sys.version_info.major, sys.version_info.minor,
                        sys.version_info.micro],
        }
        report['executable'] = executable_report
        report['python'] = executable_report
        report['environment'] = {
            **baseline_environment,
            'cwd': str(baseline_cwd),
            'sys_path_before_import_roots': baseline_path,
            'meta_path_types': [
                '{}.{}'.format(type(item).__module__, type(item).__qualname__)
                for item in baseline_meta_path
            ],
        }

        for root in reversed(roots):
            sys.path.insert(0, str(root))
        expected_path = [str(root) for root in roots] + baseline_path
        if sys.path != expected_path:
            raise ValueError('import_root_application_mismatch')

        with _WorkspaceLoaderGuard(workspace, report) as loader_guard:
            with _ProcessStreamCapture() as capture:
                module_name, module = _load_exact_module(
                    target, target_binding, loader_guard)
                discovered_ids, by_id = _discover_tests(
                    module, target_relative)
                report['discovered_ids'] = discovered_ids
                report['discovered'] = len(discovered_ids)
                expected_ids = requested_ids or discovered_ids
                prefix = target_relative + '::'
                if any(not isinstance(item, str) or not item.startswith(prefix)
                       for item in expected_ids):
                    raise ValueError('expected_test_id_path_mismatch')
                unknown = [
                    item for item in expected_ids if item not in by_id]
                if unknown:
                    raise ValueError(
                        'expected_test_id_not_discovered:{}'.format(
                            ','.join(unknown)))
                report['expected_ids'] = list(expected_ids)
                report['collected'] = len(expected_ids)
                suite = unittest.TestSuite(
                    by_id[item] for item in expected_ids)
                result = _StrictResult(target_relative)
                suite.run(result)

        report['executed_ids'] = list(result.executed_ids)
        diagnostics.extend(_diagnose_result(result))
        outcomes = dict(result.outcomes)
        for expected_id in report['expected_ids']:
            outcomes.setdefault(expected_id, 'failed')
        report['passed_ids'] = [
            item for item in report['expected_ids']
            if outcomes[item] == 'passed']
        report['failed_ids'] = [
            item for item in report['expected_ids']
            if outcomes[item] == 'failed']
        report['skipped_ids'] = [
            item for item in report['expected_ids']
            if outcomes[item] == 'skipped']
        report['passed'] = len(report['passed_ids'])
        report['failed'] = len(report['failed_ids'])
        report['skipped'] = len(report['skipped_ids'])

        if capture.stdout:
            diagnostics.append('CAPTURED_STDOUT\n' + capture.stdout)
        if capture.stderr:
            diagnostics.append('CAPTURED_STDERR\n' + capture.stderr)
        if not capture.stdout_object_unchanged:
            raise ValueError('test_replaced_sys_stdout')
        if not capture.stderr_object_unchanged:
            raise ValueError('test_replaced_sys_stderr')
        if report['executed_ids'] != report['expected_ids']:
            raise ValueError('executed_test_id_order_mismatch')
        if len(report['executed_ids']) != len(set(report['executed_ids'])):
            raise ValueError('duplicate_executed_test_id')
        if report['collected'] == 0:
            raise ValueError('zero_collected_tests')
        if report['collected'] != (
                report['passed'] + report['failed'] + report['skipped']):
            raise ValueError('test_count_not_conserved')
        if result.infrastructure_errors:
            raise ValueError('unittest_infrastructure_error')
        if report['failed']:
            raise ValueError('unittest_test_failure')

        target_after_binding = _read_file_binding(target, 'target')
        target_after = {
            'path': str(target),
            'size_bytes': target_after_binding['identity']['size_bytes'],
            'sha256': target_after_binding['identity']['sha256'],
            'regular_file': True,
            'is_symlink': False,
        }
        report['target_identity_after'] = target_after
        expected_target_after = {
            'path': str(target),
            'size_bytes': target_before['size_bytes'],
            'sha256': target_before['sha256'],
            'regular_file': True,
            'is_symlink': False,
        }
        if (
            target_after != expected_target_after
            or target_after_binding['raw'] != target_binding['raw']
        ):
            raise ValueError('target_identity_changed_during_execution')
        if target.resolve(strict=True) != Path(
                report['resolved_path']).resolve(strict=True):
            raise ValueError('target_path_changed_during_execution')
        executable_after = _executable_identity()
        if executable_after != executable_before:
            raise ValueError('sys_executable_identity_changed_during_execution')
        if Path.cwd().resolve(strict=True) != baseline_cwd:
            raise ValueError('cwd_changed_during_execution')
        if sys.path != expected_path:
            raise ValueError('sys_path_changed_during_execution')
        if _meta_path_snapshot() != baseline_meta_ids:
            raise ValueError('sys_meta_path_changed_during_execution')
        if _environment_snapshot() != baseline_environment:
            raise ValueError('environment_changed_during_execution')
        if os.environ is not baseline_environment_object:
            raise ValueError('environment_object_replaced_during_execution')
        if dict(os.environ) != baseline_environment_values:
            raise ValueError('environment_values_changed_during_execution')
        report['environment_unchanged_during_execution'] = True

        report['exit'] = 0
        report['result'] = 'PASS_WITH_SKIPS' if report['skipped'] else 'PASS'
    except BaseException as error:
        report['failures'].append(
            '{}:{}'.format(type(error).__name__, str(error)))
        diagnostics.append(traceback.format_exc())
    finally:
        try:
            report['environment_unchanged_during_execution'] = (
                os.environ is baseline_environment_object
                and dict(os.environ) == baseline_environment_values
                and _environment_snapshot() == baseline_environment)
        except BaseException:
            report['environment_unchanged_during_execution'] = False
        if module_name is not None:
            sys.modules.pop(module_name, None)
        sys.path[:] = baseline_path
        sys.meta_path[:] = baseline_meta_path
        if os.environ is not baseline_environment_object:
            os.environ = baseline_environment_object
        os.environ.clear()
        os.environ.update(baseline_environment_values)
        try:
            os.chdir(str(baseline_cwd))
        except OSError:
            report['failures'].append('environment_restore_cwd_failed')
        current_environment = _environment_snapshot()
        report['environment_restored'] = (
            sys.path == baseline_path
            and _meta_path_snapshot() == baseline_meta_ids
            and Path.cwd().resolve(strict=True) == baseline_cwd
            and os.environ is baseline_environment_object
            and dict(os.environ) == baseline_environment_values
            and current_environment == baseline_environment)
        if not report['environment_restored']:
            report['failures'].append('environment_not_restored')
            report['exit'] = 1
            report['result'] = 'FAIL'
        if target is not None and report['target_identity_after'] is None:
            try:
                report['target_identity_after'] = _file_identity(target, 'target')
            except BaseException as error:
                report['failures'].append(
                    'target_post_identity_failed:{}'.format(type(error).__name__))
        report['failures'] = sorted(set(report['failures']))

    if diagnostics:
        sys.stderr.write('\n'.join(diagnostics))
        if not diagnostics[-1].endswith('\n'):
            sys.stderr.write('\n')
        sys.stderr.flush()
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
    index = 0
    while index < len(raw):
        token = raw[index]
        if token == '--single-file':
            raise _ArgvFailure('runner_argv_single_file_forbidden')
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
        expected_id=repeats['expected-id'], raw_argv=raw,
    )


def _subprocess_environment():
    if os.name == 'nt':
        allowed = {'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'TEMP', 'TMP'}
        return {
            key: value for key, value in os.environ.items()
            if key.upper() in allowed
        }
    return {
        'LANG': 'C.UTF-8',
        'LC_ALL': 'C.UTF-8',
        'PATH': '/usr/bin:/bin',
        'PYTHONDONTWRITEBYTECODE': '1',
        'PYTHONNOUSERSITE': '1',
    }


def _popen_kwargs():
    values = {'close_fds': True}
    if os.name != 'nt':
        values['pass_fds'] = ()
    return values


def _extract_inventory(verifier_raw):
    parsed = ast.parse(verifier_raw, filename=VERIFIER_RELATIVE_PATH)
    values = []
    for node in parsed.body:
        target = None
        value = None
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target = node.target.id
            value = node.value
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 and (
                isinstance(node.targets[0], ast.Name)):
            target = node.targets[0].id
            value = node.value
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
    code = compile(raw, str(path), 'exec', dont_inherit=True, optimize=0)
    exec(code, module.__dict__)
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
        'record_id': record_id,
        'nonce': nonce,
        'command': command,
        'index': index,
        'phase': phase,
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
    argv = [
        sys.executable, '-I', '-S', '-B', '-c',
        _WRAPPER_OBSERVER_BOOTSTRAP, str(workspace), WRAPPER_RELATIVE_PATH,
    ]
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
    if (
        completed.returncode != 0 or completed.stderr != b''
        or parent_before != parent_after
        or payload.get('wrapper_identity') != parent_before
        or payload.get('capability_surface') != empty_surface
        or not isinstance(payload.get('result'), dict)
    ):
        raise ValueError('production_wrapper_observation_invalid')
    return {
        'schema_version': PRODUCTION_WRAPPER_OBSERVATION_SCHEMA,
        'record_id': record_id,
        'path': WRAPPER_RELATIVE_PATH,
        'parent_before': parent_before,
        'parent_after': parent_after,
        'argv': argv,
        'argv_sha256': _canonical_sha256(argv),
        'environment': dict(environment),
        'environment_sha256': _canonical_sha256(environment),
        'exit_code': completed.returncode,
        'marker_count': 1,
        'marker_prefix': WRAPPER_MARKER,
        'payload': payload,
        'payload_sha256': _canonical_sha256(payload),
        'stdout': _stream_identity(completed.stdout),
        'stderr': _stream_identity(completed.stderr),
    }


def _child_argv(args, workspace, runner_binding):
    argv = _execution_component_argv(
        workspace, runner_binding['path'], {
            'path': Path(__file__).resolve(strict=True),
            'raw': _relative_binding(
                workspace, runner_binding['path'],
                'runner_test_child_expected')['raw'],
            'identity': {
                'path': runner_binding['path'],
                'size_bytes': runner_binding['size_bytes'],
                'sha256': runner_binding['sha256'],
            },
        }, 'runner', [
        '--mode', 'test-child-v2', '--workspace', args.workspace,
        '--record-id', args.record_id, '--suite-id', args.suite_id,
        '--target', args.target,
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
    if (
        payload.get('schema_version') != CHILD_SCHEMA_VERSION
        or payload.get('record_id') != args.record_id
        or payload.get('suite_id') != args.suite_id
        or completed.returncode != payload.get('exit')
    ):
        raise ValueError('test_child_contract_invalid')
    return argv, completed, payload


def _supervisor_report(args):
    workspace = _resolve_workspace(args.workspace)
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
    ready = None
    checkpoints = []
    final = None
    broker_stderr = b''
    broker_exit = None
    child_completed = None
    try:
        broker = subprocess.Popen(
            broker_argv, cwd=str(workspace), env=environment,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, **_popen_kwargs())
        initial = {
            'schema_version': 'workspace_pyc_identity_broker_init/v1',
            'record_id': args.record_id,
            'nonce': nonce,
            'inventory': inventory,
            'inventory_sha256': PYC_INVENTORY_SHA256,
        }
        broker.stdin.write(_canonical_json(initial) + b'\n')
        broker.stdin.flush()
        ready = _broker_event(broker, BROKER_READY_MARKER, 'pyc_broker_ready')
        verifier, verifier_execution_binding = _load_source_only_verifier(
            workspace, verifier_binding)
        wrapper_observation = _observe_production_wrapper(
            workspace, args.record_id, environment)
        _broker_command(
            broker, args.record_id, nonce, 'checkpoint', 1,
            'AFTER_PRODUCTION_WRAPPER')
        checkpoints.append(_broker_event(
            broker, BROKER_CHECKPOINT_MARKER,
            'pyc_broker_after_production_wrapper'))
        child_argv, child_completed, child_payload = _run_test_child(
            args, workspace, environment, runner_binding)
        _broker_command(
            broker, args.record_id, nonce, 'checkpoint', 2,
            'AFTER_TEST_CHILD')
        checkpoints.append(_broker_event(
            broker, BROKER_CHECKPOINT_MARKER,
            'pyc_broker_after_test_child'))
        _broker_command(broker, args.record_id, nonce, 'finalize', 3, 'FINAL')
        broker.stdin.close()
        final = _broker_event(broker, BROKER_FINAL_MARKER, 'pyc_broker_final')
        broker_exit = broker.wait(timeout=COMMAND_TIMEOUT_SECONDS)
        broker_stderr = broker.stderr.read()
        broker_stdout_tail = broker.stdout.read()
        if (
            broker_exit != 0 or broker_stderr != b''
            or broker_stdout_tail != b''
        ):
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
            'argv': broker_argv,
            'argv_sha256': _canonical_sha256(broker_argv),
            'environment': dict(environment),
            'environment_sha256': _canonical_sha256(environment),
            'ready': ready,
            'checkpoints': checkpoints,
            'final': final,
            'stderr': _stream_identity(broker_stderr),
            'exit_code': broker_exit,
        }
        report = dict(child_payload)
        report.update({
            'schema_version': SCHEMA_VERSION,
            'runner_kind': RUNNER_KIND,
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


def _failure_report(options, error):
    return {
        'schema_version': SCHEMA_VERSION,
        'runner_kind': RUNNER_KIND,
        'mode': getattr(options, 'mode', None),
        'record_id': getattr(options, 'record_id', ''),
        'suite_id': getattr(options, 'suite_id', ''),
        'exit': 2,
        'result': 'FAIL',
        'failures': [getattr(error, 'code', str(error))],
        'pyc_broker_transcript': None,
        'pyc_verifier_result': None,
        'production_wrapper_observation': None,
        'supervisor_validated_pass': False,
    }


def main(argv=None):
    options = None
    try:
        options = _strict_raw_options(argv)
        if options.mode == 'test-child-v2':
            _child_capability_preflight()
            report = _single_file_report(options)
            payload = _canonical_json(report).decode('utf-8')
            print(CHILD_MARKER + payload, flush=True)
            return report['exit']
        report = _supervisor_report(options)
    except BaseException as error:
        report = _failure_report(options, error)
        traceback.print_exc(file=sys.stderr)
    payload = _canonical_json(report).decode('utf-8')
    print(SINGLE_FILE_MARKER + payload, flush=True)
    return report['exit']


if __name__ == '__main__':
    raise SystemExit(main())

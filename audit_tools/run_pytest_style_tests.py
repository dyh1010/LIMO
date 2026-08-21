"""Minimal offline runner for this repository's pytest-style unit tests.

This is a local validation utility, not a production dependency.  It provides
only the small pytest surface used by the selected test modules.
"""

import argparse
import hashlib
import importlib
import importlib.machinery
import importlib.util
import inspect
import io
import json
import os
import re
import shutil
import stat
import sys
import tempfile
import traceback
import types
from contextlib import ContextDecorator, redirect_stderr, redirect_stdout
from pathlib import Path


SINGLE_FILE_MARKER = 'OFFLINE_PYTEST_FILE_RESULT '
WORKSPACE_BYTECODE_POLICY = 'SOURCE_ONLY_REJECT_WORKSPACE_PYC_V1'
WORKSPACE_PYC_INODE_POLICY = 'WORKSPACE_PYC_SINGLE_LINK_INODE_V1'
_WORKSPACE_AUDIT_GUARD_USED = False


class RaisesContext(ContextDecorator):
    def __init__(self, expected, match=None):
        self.expected = expected
        self.match = match
        self.value = None

    def __enter__(self):
        return self

    def __exit__(self, exception_type, exception, unused_traceback):
        if exception_type is None:
            raise AssertionError(
                'expected {} to be raised'.format(self.expected.__name__))
        if not issubclass(exception_type, self.expected):
            return False
        self.value = exception
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
    _NOT_SET = object()

    def __init__(self):
        self._items = []

    def setitem(self, mapping, key, value):
        present = key in mapping
        previous = mapping.get(key)
        mapping[key] = value
        self._items.append(('item', mapping, key, present, previous))

    def setattr(self, target, name, value=_NOT_SET):
        if value is self._NOT_SET:
            if not isinstance(target, str) or '.' not in target:
                raise TypeError(
                    'dotted setattr requires module.attribute target')
            replacement = name
            parts = target.split('.')
            imported = None
            imported_count = 0
            for count in range(len(parts) - 1, 0, -1):
                module_name = '.'.join(parts[:count])
                try:
                    imported = importlib.import_module(module_name)
                except ModuleNotFoundError as error:
                    if error.name != module_name:
                        raise
                    continue
                imported_count = count
                break
            if imported is None:
                raise ModuleNotFoundError(target)
            owner = imported
            for attribute in parts[imported_count:-1]:
                owner = getattr(owner, attribute)
            target = owner
            name = parts[-1]
            value = replacement
        present = hasattr(target, name)
        previous = getattr(target, name, None)
        setattr(target, name, value)
        self._items.append(('attr', target, name, present, previous))

    def undo(self):
        for kind, target, name, present, previous in reversed(self._items):
            if kind == 'item':
                if present:
                    target[name] = previous
                else:
                    target.pop(name, None)
            elif present:
                setattr(target, name, previous)
            else:
                delattr(target, name)


class CaptureSys:
    def __init__(self):
        self._stdout = io.StringIO()
        self._stderr = io.StringIO()
        self._stdout_context = redirect_stdout(self._stdout)
        self._stderr_context = redirect_stderr(self._stderr)
        self._stdout_context.__enter__()
        self._stderr_context.__enter__()

    def readouterr(self):
        captured = types.SimpleNamespace(
            out=self._stdout.getvalue(),
            err=self._stderr.getvalue(),
        )
        self._stdout.seek(0)
        self._stdout.truncate(0)
        self._stderr.seek(0)
        self._stderr.truncate(0)
        return captured

    def close(self):
        self._stderr_context.__exit__(None, None, None)
        self._stdout_context.__exit__(None, None, None)


def install_pytest_stub():
    module = types.ModuleType('pytest')
    module.raises = lambda expected, match=None: RaisesContext(expected, match)
    module.approx = lambda expected, rel=1e-6, abs=1e-12: Approx(
        expected, rel=rel, abs_tol=abs)
    module.mark = Mark()
    module.fixture = lambda function: setattr(
        function, '__offline_fixture__', True) or function
    module.skip = lambda reason='': (_ for _ in ()).throw(SkipTest(reason))
    module.fail = lambda reason='': (_ for _ in ()).throw(
        AssertionError(reason))
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


def load_module(path, sequence):
    name = 'offline_pytest_module_{}'.format(sequence)
    spec = importlib.util.spec_from_file_location(name, str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError('cannot load {}'.format(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
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
        elif name == 'capsys':
            capture = CaptureSys()
            arguments[name] = capture
            cleanups.append(capture.close)
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


def _regular_file_identity(path):
    """Return an identity read from one exact regular, non-link file."""
    if path.is_symlink():
        raise ValueError('target_is_link')
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError('target_is_not_regular_file')
    payload = path.read_bytes()
    if len(payload) != metadata.st_size:
        raise ValueError('target_size_changed_while_reading')
    return {
        'size_bytes': len(payload),
        'sha256': hashlib.sha256(payload).hexdigest(),
    }


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
        self._restored = restored
        self._installed = False

    @property
    def tampered(self):
        return self._tampered

    @property
    def restored(self):
        return self._restored

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
        }


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
    discovered_ids = [case[0] for case in cases]
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
    case_results = []
    for case_id in expected_ids:
        _unused_id, function, initial_arguments = by_id[case_id]
        arguments = dict(initial_arguments)
        cleanups = []
        outcome = None
        outcome_reason = None
        executed_ids.append(case_id)
        try:
            cleanups = add_supported_fixtures(function, arguments)
            invoke(function, arguments)
        except SkipTest as error:
            if len(error.args) != 1 or type(error.args[0]) is not str or (
                    not error.args[0]):
                outcome = 'failed'
                outcome_reason = 'INVALID_SKIP_REASON'
                diagnostics.append(
                    'FAIL {} invalid skip reason'.format(case_id))
            else:
                outcome = 'skipped'
                outcome_reason = error.args[0]
                diagnostics.append(
                    'SKIP {} {}'.format(case_id, outcome_reason))
        except BaseException as error:
            outcome = 'failed'
            outcome_reason = 'EXCEPTION:{}'.format(type(error).__name__)
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
                outcome_reason = 'FIXTURE_CLEANUP_FAILED'
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
        entry = {'test_id': case_id, 'outcome': outcome}
        if outcome != 'passed':
            entry['reason'] = outcome_reason or 'MISSING_OUTCOME_REASON'
        case_results.append(entry)
    return {
        'discovered_ids': discovered_ids,
        'executed_ids': executed_ids,
        'case_results': case_results,
        'passed': passed,
        'failed': failed,
        'skipped': skipped,
        'diagnostics': diagnostics,
    }


def _single_file_report(args):
    """Run exactly one allowlisted test file and return its strict marker."""
    expected_ids = list(args.expected_id or ())
    report = {
        'schema_version': 'offline_pytest_file_result/v2',
        'runner_kind': 'offline_pytest_style_single_file',
        'runner_output_contract': {
            'encoding': 'UTF-8',
            'json': 'SORTED_KEYS_COMPACT_ENSURE_ASCII_FALSE',
            'line_ending_hex': '0a',
        },
        'runner_identity_before': None,
        'runner_identity_after': None,
        'path': '',
        'size_bytes': 0,
        'sha256': '',
        'selection_mode': 'selected_ids',
        'expected_ids': expected_ids,
        'discovered_ids': [],
        'executed_ids': [],
        'discovered': 0,
        'case_results_schema': 'offline_case_results/v1',
        'case_results': [],
        'collected': 0,
        'passed': 0,
        'failed': 0,
        'skipped': 0,
        'exit': 1,
        'result': 'FAIL',
        'workspace_bytecode_policy': WORKSPACE_BYTECODE_POLICY,
        'workspace_pyc_bytes_read': 0,
        'workspace_pyc_attempts_blocked': [],
        'workspace_source_reads': [],
        'workspace_loader_guard_restored': False,
        'workspace_pyc_audit_hook_active': False,
        'workspace_pyc_inode_policy': WORKSPACE_PYC_INODE_POLICY,
        'workspace_pyc_inventory_count': 0,
        'workspace_pyc_inventory_stable': False,
    }
    diagnostics = []
    workspace_loader_guard = None
    try:
        if len(args.workspace or ()) != 1:
            raise ValueError('single_file_requires_exactly_one_workspace')
        if len(args.target or ()) != 1:
            raise ValueError('single_file_requires_exactly_one_target')
        if args.paths:
            raise ValueError('single_file_rejects_positional_or_multiple_targets')
        if not args.import_root:
            raise ValueError('single_file_requires_import_root_allowlist')
        if not expected_ids:
            raise ValueError('single_file_zero_expected_test_ids')
        if len(expected_ids) != len(set(expected_ids)):
            raise ValueError('single_file_duplicate_expected_test_id')
        if not sys.flags.isolated:
            raise ValueError('single_file_requires_python_isolated_mode')
        if not sys.dont_write_bytecode:
            raise ValueError('single_file_requires_python_no_bytecode_mode')

        workspace_input = Path(args.workspace[0])
        if workspace_input.is_symlink():
            raise ValueError('workspace_is_link')
        workspace = workspace_input.resolve(strict=True)
        if workspace.is_symlink() or not workspace.is_dir():
            raise ValueError('workspace_not_regular_directory')
        if Path.cwd().resolve(strict=True) != workspace:
            raise ValueError('single_file_cwd_must_equal_workspace')

        runner_path = Path(__file__).resolve(strict=True)
        if not _is_relative_to(runner_path, workspace):
            raise ValueError('runner_outside_workspace')
        runner_relative = runner_path.relative_to(workspace).as_posix()
        runner_before = _regular_file_identity(runner_path)
        report['runner_identity_before'] = {
            'path': runner_relative,
            **runner_before,
        }

        raw_target = Path(args.target[0])
        if not raw_target.is_absolute():
            raw_target = workspace / raw_target
        if raw_target.is_symlink():
            raise ValueError('target_is_link')
        target = raw_target.resolve(strict=True)
        if not _is_relative_to(target, workspace):
            raise ValueError('target_outside_workspace')
        target_relative = target.relative_to(workspace).as_posix()
        report['path'] = target_relative
        before_identity = _regular_file_identity(target)
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
            capture_stdout = io.StringIO()
            capture_stderr = io.StringIO()
            with redirect_stdout(capture_stdout), redirect_stderr(capture_stderr):
                module = load_module(target, 1)
                cases = _collect_cases(module, target_relative)
                selected = _run_selected_cases(
                    cases, expected_ids, stubbed_modules)
        finally:
            workspace_loader_guard.restore()
        if workspace_loader_guard.tampered:
            raise ValueError('workspace_loader_guard_replaced')
        if not workspace_loader_guard.restored:
            raise ValueError('workspace_loader_guard_not_restored')
        if not workspace_loader_guard._bytecode_inventory_stable:
            raise ValueError('workspace_pyc_inventory_changed_during_execution')
        report['discovered_ids'] = selected['discovered_ids']
        report['discovered'] = len(selected['discovered_ids'])
        report['executed_ids'] = selected['executed_ids']
        report['case_results'] = selected['case_results']
        report['collected'] = len(selected['executed_ids'])
        report['passed'] = selected['passed']
        report['failed'] = selected['failed']
        report['skipped'] = selected['skipped']
        diagnostics.extend(selected['diagnostics'])
        if capture_stdout.getvalue():
            diagnostics.append(
                'CAPTURED_STDOUT\n{}'.format(capture_stdout.getvalue()))
        if capture_stderr.getvalue():
            diagnostics.append(
                'CAPTURED_STDERR\n{}'.format(capture_stderr.getvalue()))

        after_identity = _regular_file_identity(target)
        if after_identity != before_identity:
            raise ValueError('target_identity_changed_during_execution')
        runner_after = _regular_file_identity(runner_path)
        report['runner_identity_after'] = {
            'path': runner_relative,
            **runner_after,
        }
        if runner_after != runner_before:
            raise ValueError('runner_identity_changed_during_execution')
        if report['executed_ids'] != expected_ids:
            raise ValueError('executed_test_id_order_mismatch')
        if [item['test_id'] for item in report['case_results']] != expected_ids:
            raise ValueError('case_result_order_mismatch')
        if report['collected'] == 0:
            raise ValueError('single_file_zero_collected_tests')
        if report['collected'] != (
                report['passed'] + report['failed'] + report['skipped']):
            raise ValueError('single_file_test_count_not_conserved')
        if report['failed']:
            raise ValueError('single_file_test_failure')
        report['exit'] = 0
        report['result'] = (
            'PASS_WITH_SKIPS' if report['skipped'] else 'PASS')
    except BaseException:
        diagnostics.append(traceback.format_exc())
    finally:
        if workspace_loader_guard is not None:
            report.update(workspace_loader_guard.marker_fields())

    if diagnostics:
        sys.stderr.write('\n'.join(diagnostics))
        if not diagnostics[-1].endswith('\n'):
            sys.stderr.write('\n')
    return report


def _legacy_main(paths):
    install_pytest_stub()
    install_ros_import_stubs()
    stubbed_modules = dict(sys.modules)
    passed = 0
    failed = 0
    collected = 0
    for sequence, raw_path in enumerate(paths, start=1):
        path = Path(raw_path).resolve()
        module = load_module(path, sequence)
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
            cases = ((),) if parametrized is None else parametrized[1]
            parameter_names = () if parametrized is None else parametrized[0]
            for case_index, case in enumerate(cases):
                collected += 1
                case_values = case if isinstance(case, tuple) else (case,)
                arguments = dict(zip(parameter_names, case_values))
                label = '{}::{}'.format(path.name, name)
                if parametrized is not None:
                    label += '[{}]'.format(case_index)
                cleanups = []
                try:
                    cleanups = add_supported_fixtures(function, arguments)
                    invoke(function, arguments)
                except SkipTest as error:
                    print('SKIP {} {}'.format(label, error))
                except Exception:
                    failed += 1
                    print('FAIL {}'.format(label))
                    traceback.print_exc()
                else:
                    passed += 1
                    print('PASS {}'.format(label))
                finally:
                    for cleanup in reversed(cleanups):
                        cleanup()
                    for module_name in (
                            'rclpy', 'rclpy.node', 'rclpy.qos',
                            'std_msgs', 'std_msgs.msg',
                            'limo_cleanup_interfaces',
                            'limo_cleanup_interfaces.msg'):
                        sys.modules[module_name] = stubbed_modules[module_name]
    print(
        'OFFLINE_PYTEST_STYLE collected={} passed={} failed={}'.format(
            collected, passed, failed))
    return 1 if failed else 0


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('paths', nargs='*')
    parser.add_argument('--single-file', action='store_true')
    parser.add_argument('--workspace', action='append')
    parser.add_argument('--target', action='append')
    parser.add_argument('--import-root', action='append')
    parser.add_argument('--expected-id', action='append')
    args = parser.parse_args(argv)
    if args.single_file:
        report = _single_file_report(args)
        payload = json.dumps(
            report, allow_nan=False, ensure_ascii=False, sort_keys=True,
            separators=(',', ':')).encode('utf-8')
        sys.stdout.buffer.write(
            SINGLE_FILE_MARKER.encode('ascii')
            + payload
            + b'\n')
        sys.stdout.buffer.flush()
        return report['exit']
    if any((args.workspace, args.target, args.import_root, args.expected_id)):
        parser.error('single-file options require --single-file')
    if not args.paths:
        parser.error('at least one path is required')
    return _legacy_main(args.paths)


if __name__ == '__main__':
    raise SystemExit(main())

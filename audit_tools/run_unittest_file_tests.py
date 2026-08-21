"""Strict isolated runner for one stdlib ``unittest`` source file.

The parent frozen-regression runner starts this script with ``python -I -B``.
Test/module output is captured and replayed only on stderr; stdout contains one
machine-readable marker.  This utility intentionally has no project or third
party imports.
"""

import argparse
import hashlib
import importlib.machinery
import importlib.util
import json
import os
import stat
import sys
import tempfile
import traceback
import unittest
from pathlib import Path


SINGLE_FILE_MARKER = 'OFFLINE_UNITTEST_FILE_RESULT '
SCHEMA_VERSION = 'offline_unittest_file_result/v2'
RUNNER_KIND = 'stdlib_unittest_single_file_isolated'
WORKSPACE_BYTECODE_POLICY = 'SOURCE_ONLY_REJECT_WORKSPACE_PYC_V1'
WORKSPACE_PYC_INODE_POLICY = 'WORKSPACE_PYC_SINGLE_LINK_INODE_V1'
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


def _file_identity(path, label):
    """Read one exact regular, non-link file and bind the opened object."""
    path = Path(path)
    before = path.lstat()
    if stat.S_ISLNK(before.st_mode):
        raise ValueError('{}_is_link'.format(label))
    if not stat.S_ISREG(before.st_mode):
        raise ValueError('{}_is_not_regular_file'.format(label))

    flags = os.O_RDONLY
    flags |= getattr(os, 'O_BINARY', 0)
    flags |= getattr(os, 'O_NOFOLLOW', 0)
    descriptor = os.open(os.fspath(path), flags)
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise ValueError('{}_opened_object_is_not_regular'.format(label))
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise ValueError('{}_changed_before_open'.format(label))
        chunks = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        payload = b''.join(chunks)
    finally:
        os.close(descriptor)

    after = path.lstat()
    if stat.S_ISLNK(after.st_mode) or not stat.S_ISREG(after.st_mode):
        raise ValueError('{}_changed_file_type_while_reading'.format(label))
    if (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino):
        raise ValueError('{}_replaced_while_reading'.format(label))
    if len(payload) != opened.st_size or opened.st_size != after.st_size:
        raise ValueError('{}_size_changed_while_reading'.format(label))
    return {
        'path': str(path),
        'size_bytes': len(payload),
        'sha256': hashlib.sha256(payload).hexdigest(),
        'regular_file': True,
        'is_symlink': False,
    }


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
    identity = _file_identity(target, 'target')
    relative = target.relative_to(workspace).as_posix()
    return target, relative, identity


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


class _ScopedSubprocessEnvironment:
    """Expose only fixed import roots/no-bytecode settings to child Python."""

    def __init__(self, import_roots):
        self._import_roots = list(import_roots)
        self._object = None
        self._before = None
        self._expected = None

    def __enter__(self):
        self._object = os.environ
        self._before = dict(os.environ)
        os.environ['PYTHONPATH'] = os.pathsep.join(
            str(root) for root in self._import_roots)
        os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
        os.environ['PYTHONNOUSERSITE'] = '1'
        self._expected = dict(os.environ)
        return self

    def __exit__(self, exc_type, exc_value, traceback_object):
        unchanged = (
            os.environ is self._object
            and dict(os.environ) == self._expected)
        if os.environ is not self._object:
            os.environ = self._object
        os.environ.clear()
        os.environ.update(self._before)
        if not unchanged and exc_type is None:
            raise ValueError('scoped_subprocess_environment_changed')
        return False


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
        self.outcome_reasons = {}
        self.infrastructure_errors = []

    def _normalized(self, test):
        try:
            return _normalized_test_id(test, self.target_relative)
        except (AttributeError, TypeError, ValueError):
            return None

    def _record(self, test, outcome, reason=None):
        normalized = self._normalized(test)
        if normalized is None:
            self.infrastructure_errors.append(
                'unmapped_result:{}'.format(test.id()))
            return
        previous = self.outcomes.get(normalized)
        if previous == 'failed':
            return
        self.outcomes[normalized] = outcome
        if reason is None:
            self.outcome_reasons.pop(normalized, None)
        else:
            self.outcome_reasons[normalized] = reason

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
        if type(reason) is not str or not reason:
            self.infrastructure_errors.append('invalid_skip_reason')
            self._record(test, 'failed', 'INVALID_SKIP_REASON')
            return
        self._record(test, 'skipped', reason)

    def addFailure(self, test, error):
        super().addFailure(test, error)
        self._record(
            test, 'failed',
            'FAILURE:{}'.format(getattr(error[0], '__name__', 'UNKNOWN')))

    def addError(self, test, error):
        super().addError(test, error)
        self._record(
            test, 'failed',
            'ERROR:{}'.format(getattr(error[0], '__name__', 'UNKNOWN')))

    def addExpectedFailure(self, test, error):
        super().addExpectedFailure(test, error)
        self._record(test, 'failed', 'EXPECTED_FAILURE_FORBIDDEN')
        normalized = self._normalized(test) or test.id()
        self.infrastructure_errors.append(
            'expected_failure_forbidden:{}'.format(normalized))

    def addUnexpectedSuccess(self, test):
        super().addUnexpectedSuccess(test)
        self._record(test, 'failed', 'UNEXPECTED_SUCCESS')
        normalized = self._normalized(test) or test.id()
        self.infrastructure_errors.append(
            'unexpected_success:{}'.format(normalized))

    def addSubTest(self, test, subtest, error):
        super().addSubTest(test, subtest, error)
        if error is not None:
            self._record(
                test, 'failed',
                'SUBTEST_FAILURE:{}'.format(
                    getattr(error[0], '__name__', 'UNKNOWN')))


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


def _load_exact_module(target, identity):
    module_name = '_offline_unittest_{}'.format(identity['sha256'][:24])
    if module_name in sys.modules:
        raise ValueError('exact_test_module_name_preloaded')
    spec = importlib.util.spec_from_file_location(module_name, str(target))
    if spec is None or spec.loader is None:
        raise ValueError('cannot_create_exact_test_module_spec')
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
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
        'schema_version': SCHEMA_VERSION,
        'runner_kind': RUNNER_KIND,
        'runner_output_contract': {
            'encoding': 'UTF-8',
            'json': 'SORTED_KEYS_COMPACT_ENSURE_ASCII_FALSE',
            'line_ending_hex': '0a',
        },
        'runner_identity_before': None,
        'runner_identity_after': None,
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
        'case_results_schema': 'offline_case_results/v1',
        'case_results': [],
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
        if not sys.dont_write_bytecode:
            raise ValueError('runner_requires_python_no_bytecode_mode')
        if not baseline_environment['clean']:
            raise ValueError('runner_environment_contaminated')
        requested_ids = report['requested_ids']
        if len(requested_ids) != len(set(requested_ids)):
            raise ValueError('duplicate_expected_test_id')

        workspace = _resolve_workspace(args.workspace)
        runner_path = _lexical_workspace_path(
            Path(__file__), workspace, 'runner')
        runner_relative = runner_path.relative_to(workspace).as_posix()
        runner_before = _file_identity(runner_path, 'runner')
        runner_before['path'] = runner_relative
        report['runner_identity_before'] = runner_before
        target, target_relative, target_before = _resolve_target(
            args.target, workspace)
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

        with _ScopedSubprocessEnvironment(roots):
            with _WorkspaceLoaderGuard(workspace, report):
                with _ProcessStreamCapture() as capture:
                    module_name, module = _load_exact_module(
                        target, target_before)
                    discovered_ids, by_id = _discover_tests(
                        module, target_relative)
                    report['discovered_ids'] = discovered_ids
                    report['discovered'] = len(discovered_ids)
                    expected_ids = requested_ids or discovered_ids
                    prefix = target_relative + '::'
                    if any(
                            not isinstance(item, str)
                            or not item.startswith(prefix)
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
        report['case_results'] = []
        for item in report['expected_ids']:
            entry = {
                'test_id': item,
                'outcome': outcomes[item],
            }
            if outcomes[item] != 'passed':
                entry['reason'] = result.outcome_reasons.get(
                    item, 'MISSING_OUTCOME_REASON')
            report['case_results'].append(entry)
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
        if [item['test_id'] for item in report['case_results']] != (
                report['expected_ids']):
            raise ValueError('case_result_order_mismatch')
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

        target_after = _file_identity(target, 'target')
        report['target_identity_after'] = target_after
        if target_after != target_before:
            raise ValueError('target_identity_changed_during_execution')
        runner_after = _file_identity(runner_path, 'runner')
        runner_after['path'] = runner_relative
        report['runner_identity_after'] = runner_after
        if runner_after != runner_before:
            raise ValueError('runner_identity_changed_during_execution')
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
        if report['runner_identity_before'] is not None and (
                report['runner_identity_after'] is None):
            try:
                runner_after = _file_identity(runner_path, 'runner')
                runner_after['path'] = runner_relative
                report['runner_identity_after'] = runner_after
            except BaseException as error:
                report['failures'].append(
                    'runner_post_identity_failed:{}'.format(
                        type(error).__name__))
        report['failures'] = sorted(set(report['failures']))

    if diagnostics:
        sys.stderr.write('\n'.join(diagnostics))
        if not diagnostics[-1].endswith('\n'):
            sys.stderr.write('\n')
        sys.stderr.flush()
    return report


def _parser():
    parser = argparse.ArgumentParser(
        description='Run one exact unittest file in an isolated process.')
    parser.add_argument('--workspace', required=True)
    parser.add_argument('--target', required=True)
    parser.add_argument('--import-root', action='append', required=True)
    parser.add_argument('--expected-id', action='append')
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
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


if __name__ == '__main__':
    raise SystemExit(main())

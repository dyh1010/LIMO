"""Fail-closed tests for the versioned v7 BLOCKED_OFFLINE authority."""

from __future__ import annotations

import ast
from contextlib import ExitStack
from copy import deepcopy
import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import py_compile
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest import mock

from audit_tools import formal_admission_evidence_authority_v7_core as CORE
from audit_tools import generate_ros1_atomic_cli_field_producer_pyc_identity_gate_blocked_offline_evidence_v2 as GENERATOR


ROOT = Path(__file__).resolve().parents[1]
PYC_BROKER_RELATIVE_PATH = "audit_tools/workspace_pyc_identity_broker_v1.py"
PYC_VERIFIER_RELATIVE_PATH = "audit_tools/workspace_pyc_identity_verifier_v1.py"
UNITTEST_V2_RELATIVE_PATH = "audit_tools/run_unittest_file_tests_v2.py"
PYTEST_V2_RELATIVE_PATH = "audit_tools/run_pytest_style_tests_v2.py"
AUTHORITY_TARGET_RELATIVE_PATH = (
    "audit_tools/test_formal_admission_evidence_authority_v7.py"
)
WINDOWS_AUTHORITY_RECORD_ID = "successor_authority_windows_bundled"
_WRAPPER_MODULE_NAME = "audit_tools.formal_admission_evidence_authority_v7"
_AUTHORITY_RECORD_CONTEXT_SCHEMA = (
    "successor_authority_test_child_record_binding/v1"
)
_BROKER_PROTOCOL_CACHE = None


def _compact_json(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _authority_record_binding_failure(code):
    raise RuntimeError(
        "authority_test_child_record_binding_invalid:" + code
    )


def _authority_test_child_record_context():
    runner = sys.modules.get("__main__")
    surface_names = (
        "__execution_component_binding__", "_strict_raw_options",
        "_resolve_workspace", "_current_runner_execution_binding",
    )
    if runner is None or not any(
            name in getattr(runner, "__dict__", {})
            for name in surface_names):
        return (
            _AUTHORITY_RECORD_CONTEXT_SCHEMA, False, None, False, None,
        )
    if any(
            name not in runner.__dict__
            for name in surface_names):
        _authority_record_binding_failure("runner_surface_incomplete")
    if not all(callable(runner.__dict__[name]) for name in surface_names[1:]):
        _authority_record_binding_failure("runner_surface_invalid")
    try:
        options = runner._strict_raw_options(None)
        workspace = runner._resolve_workspace(options.workspace)
        runner_binding = runner._current_runner_execution_binding(workspace)
    except Exception as error:
        raise RuntimeError(
            "authority_test_child_record_binding_invalid:runner_validation"
        ) from error

    if getattr(options, "mode", None) != "test-child-v2":
        _authority_record_binding_failure("mode")
    if getattr(options, "raw_argv", None) != list(sys.argv[1:]):
        _authority_record_binding_failure("raw_argv")
    if Path(workspace).resolve(strict=True) != ROOT.resolve(strict=True):
        _authority_record_binding_failure("workspace")
    expected_runner_path = (
        ROOT.joinpath(*UNITTEST_V2_RELATIVE_PATH.split("/"))
        .resolve(strict=True)
    )
    try:
        runner_path = Path(runner.__file__).resolve(strict=True)
    except (AttributeError, OSError, TypeError, ValueError) as error:
        raise RuntimeError(
            "authority_test_child_record_binding_invalid:runner_path"
        ) from error
    if runner_path != expected_runner_path:
        _authority_record_binding_failure("runner_path")
    raw_binding = runner.__execution_component_binding__
    if runner_binding != raw_binding:
        _authority_record_binding_failure("runner_binding_drift")
    if (
        not isinstance(runner_binding, dict)
        or set(runner_binding) != {
            "schema_version", "component_kind", "path", "size_bytes",
            "sha256", "bootstrap_sha256",
        }
        or runner_binding.get("schema_version")
        != CORE.EXECUTION_COMPONENT_BOOTSTRAP_SCHEMA
        or runner_binding.get("component_kind") != "runner"
        or runner_binding.get("path") != UNITTEST_V2_RELATIVE_PATH
        or runner_binding.get("bootstrap_sha256")
        != CORE.EXECUTION_COMPONENT_BOOTSTRAP_SHA256
        or type(runner_binding.get("size_bytes")) is not int
        or runner_binding["size_bytes"] <= 0
        or not isinstance(runner_binding.get("sha256"), str)
        or len(runner_binding["sha256"]) != 64
    ):
        _authority_record_binding_failure("runner_binding")

    record_id = getattr(options, "record_id", None)
    allowed_records = {
        WINDOWS_AUTHORITY_RECORD_ID,
        CORE.GENERATION_WRAPPER_READ_RECORD_ID,
    }
    if record_id not in allowed_records:
        _authority_record_binding_failure("record_id")
    if getattr(options, "suite_id", None) != (
            CORE.GENERATION_WRAPPER_READ_SUITE_ID):
        _authority_record_binding_failure("suite_id")
    if getattr(options, "target", None) != AUTHORITY_TARGET_RELATIVE_PATH:
        _authority_record_binding_failure("target")
    if getattr(options, "import_root", None) != ["."]:
        _authority_record_binding_failure("import_roots")
    expected_ids = getattr(options, "expected_id", None)
    if (
        not isinstance(expected_ids, list)
        or len(expected_ids) != CORE.AUTHORITY_EXPECTED_TEST_COUNT
        or len(set(expected_ids)) != len(expected_ids)
        or hashlib.sha256(_compact_json(expected_ids)).hexdigest()
        != CORE.AUTHORITY_EXPECTED_TEST_IDS_SHA256
    ):
        _authority_record_binding_failure("expected_ids")
    definitions = [
        dict(item) for item in CORE.EXECUTION_DEFINITIONS
        if item.get("record_id") == record_id
    ]
    if len(definitions) != 1:
        _authority_record_binding_failure("record_definition")
    expected_definition = {
        "record_id": record_id,
        "suite_id": CORE.GENERATION_WRAPPER_READ_SUITE_ID,
        "platform": (
            "POSIX_WSL"
            if record_id == CORE.GENERATION_WRAPPER_READ_RECORD_ID
            else "WINDOWS_HOST"
        ),
        "interpreter_role": (
            "system_python314_target"
            if record_id == CORE.GENERATION_WRAPPER_READ_RECORD_ID
            else "bundled_host_python"
        ),
        "selection": "ALL",
    }
    if definitions[0] != expected_definition:
        _authority_record_binding_failure("record_definition")
    wrapper_read_required = (
        record_id == CORE.GENERATION_WRAPPER_READ_RECORD_ID
    )
    return (
        _AUTHORITY_RECORD_CONTEXT_SCHEMA, True, record_id,
        wrapper_read_required, runner_binding["sha256"],
    )


_AUTHORITY_RECORD_CONTEXT = _authority_test_child_record_context()
if _AUTHORITY_RECORD_CONTEXT[1] and _WRAPPER_MODULE_NAME in sys.modules:
    _authority_record_binding_failure("wrapper_preloaded")
if _AUTHORITY_RECORD_CONTEXT[3]:
    WRAPPER = __import__(_WRAPPER_MODULE_NAME, fromlist=["*"])
    if (
        sys.modules.get(_WRAPPER_MODULE_NAME) is not WRAPPER
        or Path(WRAPPER.__file__).resolve(strict=True)
        != ROOT.joinpath(*CORE.GENERATION_WRAPPER_SOURCE_PATH.split("/"))
        .resolve(strict=True)
    ):
        _authority_record_binding_failure("wrapper_identity")
else:
    WRAPPER = None


def _source_text(relative):
    return (ROOT / relative).read_bytes().decode("utf-8")


def _top_level_assignment(tree, name):
    matches = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == name
                for target in node.targets):
            matches.append(node)
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == name
        ):
            matches.append(node)
    if len(matches) != 1:
        raise AssertionError(
            "top-level assignment count invalid:{}:{}".format(
                name, len(matches),
            )
        )
    node = matches[0]
    if isinstance(node, ast.Assign) and (
        len(node.targets) != 1
        or not isinstance(node.targets[0], ast.Name)
    ):
        raise AssertionError("top-level assignment target invalid:" + name)
    if node.value is None:
        raise AssertionError("top-level assignment value missing:" + name)
    return node


def _literal_assignment(relative, name):
    tree = ast.parse(_source_text(relative), filename=relative)
    return ast.literal_eval(_top_level_assignment(tree, name).value)


def _replace_top_level_literal_assignment(raw, relative, name, value):
    assignment = _top_level_assignment(
        ast.parse(raw.decode("utf-8"), filename=relative), name,
    )
    ast.literal_eval(assignment.value)
    value_node = assignment.value
    if value_node.end_lineno is None or value_node.end_col_offset is None:
        raise AssertionError("top-level assignment span missing:" + name)
    offsets = [0]
    for line in raw.splitlines(keepends=True):
        offsets.append(offsets[-1] + len(line))
    start = offsets[value_node.lineno - 1] + value_node.col_offset
    end = offsets[value_node.end_lineno - 1] + value_node.end_col_offset
    updated = raw[:start] + repr(value).encode("utf-8") + raw[end:]
    check = _top_level_assignment(
        ast.parse(updated.decode("utf-8"), filename=relative), name,
    )
    if ast.literal_eval(check.value) != value:
        raise AssertionError("top-level assignment replacement failed:" + name)
    return updated


def _isolated_local_environment():
    allowed = {
        "COMSPEC", "SYSTEMROOT", "TEMP", "TMP", "WINDIR", "PATH",
        "LANG", "LC_ALL",
    }
    return {
        key: value for key, value in os.environ.items()
        if key in allowed
    }


def _broker_inventory():
    return [dict(item) for item in _literal_assignment(
        PYC_VERIFIER_RELATIVE_PATH, "PYC_INVENTORY",
    )]


def _run_broker_protocol(inventory=None, trailing_commands=()):
    inventory = _broker_inventory() if inventory is None else inventory
    record_id = "successor_authority_protocol_test"
    nonce = "42" * 32
    lines = [{
        "schema_version": "workspace_pyc_identity_broker_init/v1",
        "record_id": record_id,
        "nonce": nonce,
        "inventory": inventory,
        "inventory_sha256": hashlib.sha256(_compact_json(inventory)).hexdigest(),
    }]
    for index, phase in enumerate((
        "AFTER_PRODUCTION_WRAPPER", "AFTER_TEST_CHILD",
    ), 1):
        lines.append({
            "schema_version": "workspace_pyc_identity_broker_command/v1",
            "record_id": record_id,
            "nonce": nonce,
            "command": "checkpoint",
            "index": index,
            "phase": phase,
        })
    lines.append({
        "schema_version": "workspace_pyc_identity_broker_command/v1",
        "record_id": record_id,
        "nonce": nonce,
        "command": "finalize",
        "index": 3,
        "phase": "FINAL",
    })
    lines.extend(trailing_commands)
    raw_input = b"".join(_compact_json(item) + b"\n" for item in lines)
    broker_identity = CORE.artifact_identity(
        ROOT, PYC_BROKER_RELATIVE_PATH,
    )
    broker_argv = [
        sys.executable, "-I", "-S", "-B", "-c",
        CORE.EXECUTION_COMPONENT_BOOTSTRAP, str(ROOT),
        PYC_BROKER_RELATIVE_PATH, str(broker_identity["size_bytes"]),
        broker_identity["sha256"], "broker",
        CORE.EXECUTION_COMPONENT_BOOTSTRAP_SCHEMA,
        CORE.EXECUTION_COMPONENT_BOOTSTRAP_SHA256,
        "--mode", "hold-open-v1", "--workspace", str(ROOT),
        "--record-id", record_id,
    ]
    completed = subprocess.run(
        broker_argv,
        cwd=str(ROOT), env=_isolated_local_environment(), input=raw_input,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60,
        check=False,
    )
    marker_prefixes = (
        "OFFLINE_WORKSPACE_PYC_BROKER_READY ",
        "OFFLINE_WORKSPACE_PYC_BROKER_CHECKPOINT ",
        "OFFLINE_WORKSPACE_PYC_BROKER_FINAL ",
        "OFFLINE_WORKSPACE_PYC_BROKER_ERROR ",
    )
    parsed = []
    for raw_line in completed.stdout.decode("utf-8").splitlines():
        matches = [prefix for prefix in marker_prefixes if raw_line.startswith(prefix)]
        if len(matches) != 1:
            raise AssertionError("unexpected broker output line: " + raw_line)
        prefix = matches[0]
        parsed.append((prefix, json.loads(raw_line[len(prefix):])))
    return {
        "record_id": record_id,
        "nonce": nonce,
        "inventory": inventory,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "events": parsed,
        "argv": broker_argv,
        "broker_identity": broker_identity,
    }


def _cached_broker_protocol():
    global _BROKER_PROTOCOL_CACHE
    if _BROKER_PROTOCOL_CACHE is None:
        _BROKER_PROTOCOL_CACHE = _run_broker_protocol()
    return deepcopy(_BROKER_PROTOCOL_CACHE)


def _verify_broker_protocol(protocol):
    by_prefix = {}
    for prefix, payload in protocol["events"]:
        by_prefix.setdefault(prefix, []).append(payload)
    request = {
        "record_id": protocol["record_id"],
        "nonce": protocol["nonce"],
        "ready": by_prefix["OFFLINE_WORKSPACE_PYC_BROKER_READY "][0],
        "checkpoints": by_prefix[
            "OFFLINE_WORKSPACE_PYC_BROKER_CHECKPOINT "
        ],
        "final": by_prefix["OFFLINE_WORKSPACE_PYC_BROKER_FINAL "][0],
        "child_capability_surface": {
            "broker_argv_fields": [],
            "broker_channels": [],
            "broker_environment_fields": [],
            "broker_fds": [],
            "broker_modules_in_sys_modules": [],
            "broker_secrets": [],
            "broker_tokens": [],
        },
        "broker_execution_binding": {
            "schema_version": CORE.EXECUTION_COMPONENT_BOOTSTRAP_SCHEMA,
            "component_kind": "broker",
            "path": protocol["broker_identity"]["path"],
            "size_bytes": protocol["broker_identity"]["size_bytes"],
            "sha256": protocol["broker_identity"]["sha256"],
            "bootstrap_sha256": CORE.EXECUTION_COMPONENT_BOOTSTRAP_SHA256,
        },
    }
    verifier_identity = CORE.artifact_identity(
        ROOT, PYC_VERIFIER_RELATIVE_PATH,
    )
    bootstrap = r'''import hashlib,json,os,stat,sys
from pathlib import Path
workspace=Path(sys.argv[1]).resolve(strict=True);relative=sys.argv[2]
expected_size=int(sys.argv[3]);expected_sha=sys.argv[4]
path=workspace
for part in relative.split('/'):
    path=path/part
    info=os.lstat(str(path))
    if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0)&getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',0x400): raise SystemExit(81)
before=os.lstat(str(path))
if not stat.S_ISREG(before.st_mode) or getattr(before,'st_nlink',1)!=1: raise SystemExit(82)
def same(info): return (info.st_dev,info.st_ino,info.st_mode,info.st_size,getattr(info,'st_mtime_ns',None),getattr(info,'st_ctime_ns',None),getattr(info,'st_nlink',1),getattr(info,'st_uid',None),getattr(info,'st_gid',None),getattr(info,'st_file_attributes',None))
def cross(info):
    common=(info.st_dev,info.st_ino,stat.S_IFMT(info.st_mode) if os.name=='nt' else info.st_mode,info.st_size,getattr(info,'st_mtime_ns',None))
    return common+((getattr(info,'st_nlink',1),getattr(info,'st_uid',None),getattr(info,'st_gid',None),getattr(info,'st_file_attributes',None)) if os.name=='nt' else (getattr(info,'st_ctime_ns',None),getattr(info,'st_nlink',1),getattr(info,'st_uid',None),getattr(info,'st_gid',None),getattr(info,'st_file_attributes',None)))
fd=os.open(str(path),os.O_RDONLY|getattr(os,'O_BINARY',0)|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_CLOEXEC',0))
try:
    os.set_inheritable(fd,False);opened_before=os.fstat(fd)
    if os.get_inheritable(fd) or cross(before)!=cross(opened_before): raise SystemExit(83)
    chunks=[]
    while True:
        chunk=os.read(fd,1048576)
        if not chunk: break
        chunks.append(chunk)
    raw=b''.join(chunks);opened_after=os.fstat(fd)
    if same(opened_before)!=same(opened_after): raise SystemExit(84)
finally: os.close(fd)
after=os.lstat(str(path))
digest=hashlib.sha256(raw).hexdigest()
if same(before)!=same(after) or cross(opened_after)!=cross(after) or len(raw)!=expected_size or digest!=expected_sha: raise SystemExit(85)
ns={'__name__':'_exact_pyc_verifier','__file__':str(path),'__package__':None}
exec(compile(raw,str(path),'exec',dont_inherit=True,optimize=0),ns)
request=json.loads(sys.stdin.buffer.read().decode('utf-8'))
result=ns['verify_transcript'](**request)
sys.stdout.buffer.write(ns['canonical_json'](result))
'''
    completed = subprocess.run(
        [
            sys.executable, "-I", "-S", "-B", "-c", bootstrap,
            str(ROOT), PYC_VERIFIER_RELATIVE_PATH,
            str(verifier_identity["size_bytes"]), verifier_identity["sha256"],
        ],
        cwd=str(ROOT), env=_isolated_local_environment(),
        input=_compact_json(request), stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, timeout=30, check=False,
    )
    if completed.returncode != 0 or completed.stderr:
        raise AssertionError((completed.returncode, completed.stderr))
    return json.loads(completed.stdout.decode("utf-8"))


def _run_broker_internal_case(case):
    bootstrap = r'''
import builtins
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import threading

source = Path(sys.argv[1]).resolve(strict=True)
raw = source.read_bytes()
ns = {"__name__": "_exact_pyc_broker_unit", "__file__": str(source),
      "__package__": None}
exec(compile(raw, str(source), "exec", dont_inherit=True, optimize=0), ns)
case = sys.argv[2]
result = {"case": case, "code": None, "value": None}

def capture(call):
    try:
        result["value"] = call()
    except ns["BrokerFailure"] as error:
        result["code"] = error.code

if case.startswith("execution_binding_"):
    workspace = source.parents[1]
    binding = {
        "schema_version": ns["EXECUTION_COMPONENT_BOOTSTRAP_SCHEMA"],
        "component_kind": "broker",
        "path": ns["BROKER_RELATIVE_PATH"],
        "size_bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bootstrap_sha256": ns["EXECUTION_COMPONENT_BOOTSTRAP_SHA256"],
    }
    if case == "execution_binding_missing":
        binding = None
    elif case == "execution_binding_kind":
        binding["component_kind"] = "runner"
    elif case == "execution_binding_path":
        binding["path"] = "audit_tools/not_the_broker.py"
    elif case == "execution_binding_sha":
        binding["sha256"] = "0" * 64
    elif case == "execution_binding_bootstrap":
        binding["bootstrap_sha256"] = "0" * 64
    else:
        raise AssertionError(case)
    if binding is None:
        ns.pop("__execution_component_binding__", None)
    else:
        ns["__execution_component_binding__"] = binding
    capture(lambda: ns["_validate_execution_binding"](workspace))
elif case in ("nested", "reuse", "cross_thread"):
    ns["_SESSION_STATE"] = "UNUSED"
    ns["_SESSION_THREAD_ID"] = None
    ns["_claim_session"]()
    if case == "nested":
        capture(ns["_claim_session"])
    elif case == "reuse":
        ns["_finish_session"]("FINALIZED")
        capture(ns["_claim_session"])
    else:
        values = []
        def worker():
            try:
                ns["_require_session_thread"]()
            except ns["BrokerFailure"] as error:
                values.append(error.code)
        thread = threading.Thread(target=worker)
        thread.start()
        thread.join()
        result["code"] = values[0] if values else None
elif case == "windows_reparse_projection":
    setattr(ns["stat"], "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    class Info:
        st_mode = stat.S_IFREG | 0o444
        st_file_attributes = 0x400
    result["value"] = ns["_is_linklike"](Info())
elif case == "windows_cross_source_ctime_contract":
    class Info:
        def __init__(self):
            self.st_dev = 1
            self.st_ino = 2
            self.st_mode = stat.S_IFREG | 0o444
            self.st_size = 3
            self.st_mtime = 4.0
            self.st_mtime_ns = 4_000_000_000
            self.st_ctime = 5.0
            self.st_ctime_ns = 5_000_000_000
            self.st_nlink = 1
            self.st_uid = 6
            self.st_gid = 7
            self.st_file_attributes = 8
    left = Info()
    right = Info()
    right.st_ctime_ns += 999
    original_name = ns["os"].name
    ns["os"].name = "nt"
    try:
        windows_cross_equal = (
            ns["_cross_source_projection"](left)
            == ns["_cross_source_projection"](right)
        )
        same_source_equal = ns["_stat_projection"](left) == ns["_stat_projection"](right)
        other_fields = (
            "st_dev", "st_ino", "st_size", "st_mtime_ns",
            "st_nlink", "st_uid", "st_gid", "st_file_attributes",
        )
        other_mismatches_rejected = []
        for field in other_fields:
            changed = Info()
            setattr(changed, field, getattr(changed, field) + 1)
            other_mismatches_rejected.append(
                ns["_cross_source_projection"](left)
                != ns["_cross_source_projection"](changed)
            )
        permission_only = Info()
        permission_only.st_mode ^= 0o111
        permission_only_normalized = (
            ns["_cross_source_projection"](left)
            == ns["_cross_source_projection"](permission_only)
        )
        file_type_changed = Info()
        file_type_changed.st_mode = stat.S_IFDIR | 0o444
        file_type_mismatch_rejected = (
            ns["_cross_source_projection"](left)
            != ns["_cross_source_projection"](file_type_changed)
        )
        ns["os"].name = "posix"
        posix_cross_equal = (
            ns["_cross_source_projection"](left)
            == ns["_cross_source_projection"](right)
        )
        posix_permission_mismatch_rejected = (
            ns["_cross_source_projection"](left)
            != ns["_cross_source_projection"](permission_only)
        )
    finally:
        ns["os"].name = original_name
    result["value"] = {
        "windows_cross_ctime_equal": windows_cross_equal,
        "same_source_ctime_equal": same_source_equal,
        "posix_cross_ctime_equal": posix_cross_equal,
        "other_mismatches_rejected": other_mismatches_rejected,
        "permission_only_mode_normalized": permission_only_normalized,
        "posix_permission_mismatch_rejected": (
            posix_permission_mismatch_rejected
        ),
        "file_type_mismatch_rejected": file_type_mismatch_rejected,
    }
else:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve(strict=True)
        target = root / "x.pyc"
        raw_value = b"alpha-pyc-fixture"
        target.write_bytes(raw_value)
        expected = {
            "path": "x.pyc", "size_bytes": len(raw_value),
            "sha256": hashlib.sha256(raw_value).hexdigest(),
        }
        if case == "hardlink":
            os.link(target, root / "alias.pyc")
        elif case == "replacement_before_open":
            original_open = ns["os"].open
            replaced = [False]
            def hooked_open(path, flags, mode=0o777, *, dir_fd=None):
                if (
                    dir_fd is None and not replaced[0]
                    and Path(path) == target
                ):
                    replaced[0] = True
                    target.unlink()
                    target.write_bytes(raw_value)
                return original_open(path, flags, mode, dir_fd=dir_fd)
            ns["os"].open = hooked_open
        elif case in ("replacement_during_hash", "rewrite_during_hash"):
            original_read = ns["_read_fd"]
            changed = [False]
            def hooked_read(descriptor):
                value = original_read(descriptor)
                if not changed[0]:
                    changed[0] = True
                    if case == "replacement_during_hash":
                        target.unlink()
                        target.write_bytes(raw_value)
                    else:
                        with builtins.open(target, "r+b", buffering=0) as stream:
                            stream.seek(0)
                            stream.write(b"ALPHA-pyc-fixture")
                        info = target.stat()
                        os.utime(target, ns=(info.st_atime_ns, info.st_mtime_ns + 1_000_000))
                return value
            ns["_read_fd"] = hooked_read
        entry_box = []
        def operation():
            entry = ns["_open_entry"](root, expected)
            entry_box.append(entry)
            if case == "closed_fd":
                os.close(entry["descriptor"])
                return ns["_checkpoint"]([entry])
            return entry["identity"]
        capture(operation)
        if case == "replacement_before_open":
            ns["os"].open = original_open
        for entry in entry_box:
            try:
                os.close(entry["descriptor"])
            except OSError:
                pass

sys.stdout.write(json.dumps(result, sort_keys=True, separators=(",", ":")))
'''
    completed = subprocess.run(
        [
            sys.executable, "-I", "-S", "-B", "-c", bootstrap,
            str(ROOT / PYC_BROKER_RELATIVE_PATH), case,
        ],
        cwd=str(ROOT), env=_isolated_local_environment(),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30,
        check=False,
    )
    if completed.returncode != 0 or completed.stderr:
        raise AssertionError((case, completed.returncode, completed.stderr))
    return json.loads(completed.stdout.decode("utf-8"))


def _run_runner_binding_internal_case(runner_relative, case):
    bootstrap = r'''
import builtins
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

source = Path(sys.argv[1]).resolve(strict=True)
verifier_source = Path(sys.argv[2]).resolve(strict=True)
raw = source.read_bytes()
ns = {"__name__": "_exact_runner_binding_unit", "__file__": str(source),
      "__package__": None}
exec(compile(raw, str(source), "exec", dont_inherit=True, optimize=0), ns)
case = sys.argv[3]
result = {"case": case, "code": None, "value": None}

def capture(call):
    try:
        result["value"] = call()
    except (ValueError, OSError) as error:
        result["code"] = str(error)

with tempfile.TemporaryDirectory() as directory:
    root = Path(directory).resolve(strict=True)
    target = root / "component.py"
    target.write_bytes(b"A" * 4096)
    read_binding = (
        ns.get("_read_file_binding") or ns.get("_read_regular_binding"))
    if case == "raw_identity_mismatch":
        binding = {
            "path": target,
            "raw": b"A",
            "identity": {
                "path": "component.py", "size_bytes": 1,
                "sha256": hashlib.sha256(b"B").hexdigest(),
            },
        }
        capture(lambda: ns["_binding_identity_matches_raw"](
            binding, "execution_component_aba"))
    elif case == "bound_path_mismatch":
        binding = ns["_relative_binding"](
            root, "component.py", "execution_component")
        binding["path"] = root / "different.py"
        capture(lambda: ns["_execution_component_argv"](
            root, "component.py", binding, "runner", ["--mode", "x"]))
    elif case == "replacement_before_open":
        original_open = ns["os"].open
        replaced = [False]
        def hooked_open(path, flags, mode=0o777, *, dir_fd=None):
            if dir_fd is None and not replaced[0] and Path(path) == target:
                replaced[0] = True
                target.unlink()
                target.write_bytes(b"A" * 4096)
            return original_open(path, flags, mode, dir_fd=dir_fd)
        ns["os"].open = hooked_open
        try:
            capture(lambda: read_binding(
                target, "execution_component_aba"))
        finally:
            ns["os"].open = original_open
    elif case == "rewrite_during_read":
        original_read = ns["os"].read
        changed = [False]
        def hooked_read(descriptor, count):
            value = original_read(descriptor, count)
            if value and not changed[0]:
                changed[0] = True
                with builtins.open(target, "r+b", buffering=0) as stream:
                    stream.seek(0)
                    stream.write(b"B" * len(value))
                info = target.stat()
                os.utime(target, ns=(
                    info.st_atime_ns, info.st_mtime_ns + 1_000_000))
            return value
        ns["os"].read = hooked_read
        try:
            capture(lambda: read_binding(
                target, "execution_component_rewrite"))
        finally:
            ns["os"].read = original_read
    elif case in ("verifier_positive", "verifier_aba"):
        relative = ns["VERIFIER_RELATIVE_PATH"]
        verifier_target = root.joinpath(*relative.split("/"))
        verifier_target.parent.mkdir(parents=True, exist_ok=True)
        verifier_target.write_bytes(verifier_source.read_bytes())
        expected = ns["_relative_binding"](
            root, relative, "pyc_verifier_expected")
        if case == "verifier_aba":
            forged = {
                "path": expected["path"], "raw": expected["raw"],
                "identity": dict(expected["identity"]),
            }
            forged["identity"]["sha256"] = "0" * 64
            original_relative = ns["_relative_binding"]
            ns["_relative_binding"] = lambda *unused: forged
            try:
                capture(lambda: ns["_load_source_only_verifier"](
                    root, expected))
            finally:
                ns["_relative_binding"] = original_relative
        else:
            def load_verifier():
                unused_module, loaded = ns["_load_source_only_verifier"](
                    root, expected)
                identity = ns["_binding_identity_matches_raw"](
                    loaded, "pyc_verifier_positive")
                return {
                    "size_bytes": len(loaded["raw"]),
                    "sha256": hashlib.sha256(loaded["raw"]).hexdigest(),
                    "identity": identity,
                }
            capture(load_verifier)
    else:
        raise AssertionError(case)

sys.stdout.write(json.dumps(result, sort_keys=True, separators=(",", ":")))
'''
    completed = subprocess.run(
        [
            sys.executable, "-I", "-S", "-B", "-c", bootstrap,
            str(ROOT.joinpath(*runner_relative.split("/"))),
            str(ROOT / PYC_VERIFIER_RELATIVE_PATH), case,
        ],
        cwd=str(ROOT), env=_isolated_local_environment(),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30,
        check=False,
    )
    if completed.returncode != 0 or completed.stderr:
        raise AssertionError((
            runner_relative, case, completed.returncode, completed.stderr,
        ))
    return json.loads(completed.stdout.decode("utf-8"))


def _json_bytes(value):
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _runner_projection_contract(
    relative, same_name="_same_side_projection",
    cross_name="_cross_source_projection",
):
    source = _source_text(relative)
    tree = ast.parse(source, filename=relative)
    functions = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name in (same_name, cross_name)
    ]
    if {node.name for node in functions} != {same_name, cross_name}:
        raise AssertionError("runner projection functions missing: " + relative)
    module = ast.fix_missing_locations(ast.Module(body=functions, type_ignores=[]))

    class Info:
        def __init__(self):
            self.st_dev = 1
            self.st_ino = 2
            self.st_mode = __import__("stat").S_IFREG | 0o444
            self.st_size = 3
            self.st_mtime_ns = 4_000_000_000
            self.st_ctime_ns = 5_000_000_000
            self.st_nlink = 1
            self.st_uid = 6
            self.st_gid = 7
            self.st_file_attributes = 8

    def evaluate(platform):
        namespace = {
            "os": SimpleNamespace(name=platform),
            "stat": __import__("stat"),
        }
        exec(compile(module, relative, "exec"), namespace)
        left = Info()
        ctime = Info()
        ctime.st_ctime_ns += 1
        permission = Info()
        permission.st_mode ^= 0o111
        file_type = Info()
        file_type.st_mode = __import__("stat").S_IFDIR | 0o444
        mismatches = {}
        for field in (
            "st_dev", "st_ino", "st_size", "st_mtime_ns", "st_nlink",
            "st_uid", "st_gid", "st_file_attributes",
        ):
            changed = Info()
            setattr(changed, field, getattr(changed, field) + 1)
            mismatches[field] = (
                namespace[cross_name](left)
                != namespace[cross_name](changed)
            )
        return {
            "cross_ctime_equal": (
                namespace[cross_name](left)
                == namespace[cross_name](ctime)
            ),
            "same_side_ctime_equal": (
                namespace[same_name](left)
                == namespace[same_name](ctime)
            ),
            "cross_permission_equal": (
                namespace[cross_name](left)
                == namespace[cross_name](permission)
            ),
            "file_type_mismatch_rejected": (
                namespace[cross_name](left)
                != namespace[cross_name](file_type)
            ),
            "other_mismatches_rejected": mismatches,
        }

    return {"windows": evaluate("nt"), "posix": evaluate("posix")}


def _write(root, relative, raw):
    path = root.joinpath(*relative.split("/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return {
        "root_role": "workspace",
        "path": relative,
        "size_bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def _write_json(root, relative, value):
    return _write(root, relative, _json_bytes(value))


def _stream(raw=b""):
    return {"size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def _sha(value):
    return hashlib.sha256(CORE._canonical_json(value)).hexdigest()


def _test_generator_execution_contract(root, mode):
    source = CORE.source_artifact_identity(
        root, "workspace", GENERATOR.GENERATOR_RELATIVE_PATH,
    )
    generator_identity = {
        key: source[key] for key in ("path", "size_bytes", "sha256")
    }
    executable_raw = Path(sys.executable).read_bytes()
    interpreter_identity = {
        "path": str(Path(sys.executable).resolve(strict=True)),
        "size_bytes": len(executable_raw),
        "sha256": hashlib.sha256(executable_raw).hexdigest(),
        "hardlink_count": getattr(Path(sys.executable).stat(), "st_nlink", 1),
    }
    environment = (
        GENERATOR._outer_windows_environment()
        if os.name == "nt" else dict(GENERATOR.INNER_ENVIRONMENT)
    )
    workspace_path = str(Path(root).resolve(strict=True))
    argv = CORE.expected_generator_execution_argv(
        workspace_path, generator_identity, interpreter_identity, mode,
    )
    return {
        "schema_version": GENERATOR.GENERATOR_EXECUTION_CONTRACT_SCHEMA,
        "mode": mode,
        "bootstrap_schema_version": CORE.EXECUTION_COMPONENT_BOOTSTRAP_SCHEMA,
        "bootstrap_sha256": CORE.EXECUTION_COMPONENT_BOOTSTRAP_SHA256,
        "generator_identity": deepcopy(generator_identity),
        "execution_binding": {
            "schema_version": CORE.EXECUTION_COMPONENT_BOOTSTRAP_SCHEMA,
            "component_kind": "generator",
            **deepcopy(generator_identity),
            "bootstrap_sha256": CORE.EXECUTION_COMPONENT_BOOTSTRAP_SHA256,
        },
        "source_identity_before": deepcopy(generator_identity),
        "source_identity_after": deepcopy(generator_identity),
        "interpreter_identity": interpreter_identity,
        "argv": argv,
        "argv_sha256": _sha(argv),
        "environment": environment,
        "environment_sha256": _sha(environment),
        "cwd": workspace_path,
        "expected_marker_prefix": (
            GENERATOR.PLAN_MARKER if mode == "--plan"
            else GENERATOR.GENERATED_MARKER
        ),
        "expected_result_schema": (
            GENERATOR.PLAN_SCHEMA_VERSION if mode == "--plan"
            else GENERATOR.GENERATION_RESULT_SCHEMA_VERSION
        ),
    }


def _test_generator_capability_fixture(root, mode):
    capability = object()
    contract = _test_generator_execution_contract(root, mode)
    expected_root = Path(root).resolve(strict=True)
    calls = []

    def consume(value, expected_mode, actual_root):
        if value is not capability:
            raise AssertionError("test generator capability identity mismatch")
        if expected_mode != mode:
            raise AssertionError("test generator capability mode mismatch")
        if Path(actual_root).resolve(strict=True) != expected_root:
            raise AssertionError("test generator capability root mismatch")
        if calls:
            raise AssertionError("test generator capability replayed")
        calls.append((value, expected_mode, expected_root))
        return deepcopy(contract)

    return capability, consume, calls


def _assert_generator_execution_component_contract(test_case):
    generator_identity = CORE.artifact_identity(
        ROOT, GENERATOR.GENERATOR_RELATIVE_PATH,
    )
    generator_environment = (
        GENERATOR._outer_windows_environment()
        if os.name == "nt" else dict(GENERATOR.INNER_ENVIRONMENT)
    )
    generator_argv = [
        sys.executable, "-I", "-S", "-B", "-c",
        CORE.EXECUTION_COMPONENT_BOOTSTRAP, str(ROOT),
        GENERATOR.GENERATOR_RELATIVE_PATH,
        str(generator_identity["size_bytes"]),
        generator_identity["sha256"], "generator",
        CORE.EXECUTION_COMPONENT_BOOTSTRAP_SCHEMA,
        CORE.EXECUTION_COMPONENT_BOOTSTRAP_SHA256, "--plan",
    ]

    def run_generator(argv, environment=generator_environment):
        return subprocess.run(
            argv, cwd=str(ROOT), env=environment,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, timeout=120, check=False,
        )

    positive_plan = run_generator(generator_argv)
    test_case.assertEqual(b"", positive_plan.stderr)
    plan_lines = positive_plan.stdout.splitlines()
    test_case.assertEqual(1, len(plan_lines), positive_plan.stdout)
    test_case.assertTrue(
        plan_lines[0].startswith(GENERATOR.PLAN_MARKER.encode("ascii")),
    )
    plan_payload = json.loads(plan_lines[0][len(GENERATOR.PLAN_MARKER):])
    ready_to_attempt_generation = plan_payload[
        "ready_to_attempt_generation"
    ]
    test_case.assertIs(type(ready_to_attempt_generation), bool)
    test_case.assertEqual(
        0 if ready_to_attempt_generation else 3,
        positive_plan.returncode,
        positive_plan.stderr,
    )
    execution_contract = plan_payload["generator_execution_contract"]
    test_case.assertEqual(
        generator_identity["sha256"],
        execution_contract["execution_binding"]["sha256"],
    )
    test_case.assertEqual(
        generator_identity["sha256"],
        execution_contract["generator_identity"]["sha256"],
    )
    test_case.assertEqual(
        execution_contract["source_identity_before"],
        execution_contract["source_identity_after"],
    )

    generate_argv = generator_argv[:-1] + ["--generate"]
    generate_binding = {
        "schema_version": CORE.EXECUTION_COMPONENT_BOOTSTRAP_SCHEMA,
        "component_kind": "generator",
        "path": GENERATOR.GENERATOR_RELATIVE_PATH,
        "size_bytes": generator_identity["size_bytes"],
        "sha256": generator_identity["sha256"],
        "bootstrap_sha256": CORE.EXECUTION_COMPONENT_BOOTSTRAP_SHA256,
    }
    safe_generate_calls = []

    def safe_generate(actual_root, actual_capability):
        consumed = GENERATOR._consume_generator_execution_capability(
            actual_capability, "--generate", actual_root,
        )
        safe_generate_calls.append((actual_capability, consumed))
        return {"generation_status": "FAILED_NO_ARTIFACTS"}

    generate_output = io.StringIO()
    with mock.patch.dict(
            GENERATOR.__dict__,
            {"__execution_component_binding__": generate_binding}), \
            mock.patch.object(
                GENERATOR, "_PENDING_GENERATOR_EXECUTION_CAPABILITY", None), \
            mock.patch.object(
                GENERATOR, "_PENDING_GENERATOR_EXECUTION_RECORD", None), \
            mock.patch.object(
                GENERATOR, "_CONSUMED_GENERATOR_EXECUTION_CAPABILITIES", []), \
            mock.patch.object(GENERATOR, "_workspace_root", return_value=ROOT), \
            mock.patch.object(GENERATOR, "_generate", side_effect=safe_generate), \
            mock.patch.object(sys, "orig_argv", generate_argv), \
            mock.patch.object(
                sys, "argv", [str(ROOT / GENERATOR.GENERATOR_RELATIVE_PATH),
                              "--generate"]), \
            mock.patch.dict(os.environ, generator_environment, clear=True), \
            mock.patch.object(sys, "stdout", generate_output):
        test_case.assertEqual(4, GENERATOR.main(["--generate"]))
    test_case.assertEqual(1, len(safe_generate_calls))
    test_case.assertIs(type(safe_generate_calls[0][0]), object)
    test_case.assertEqual(
        "--generate", safe_generate_calls[0][1]["mode"],
    )
    test_case.assertEqual(
        generator_identity["sha256"],
        safe_generate_calls[0][1]["generator_identity"]["sha256"],
    )
    generate_lines = generate_output.getvalue().splitlines()
    test_case.assertEqual(1, len(generate_lines), generate_output.getvalue())
    test_case.assertTrue(generate_lines[0].startswith(
        GENERATOR.GENERATED_MARKER))

    direct_generator = run_generator([
        sys.executable, "-I", "-S", "-B",
        str(ROOT / GENERATOR.GENERATOR_RELATIVE_PATH), "--plan",
    ])
    test_case.assertEqual(2, direct_generator.returncode)
    test_case.assertEqual(b"", direct_generator.stderr)
    test_case.assertIn(
        b"generator_execution_component_binding_invalid",
        direct_generator.stdout,
    )

    direct_prefix = [
        sys.executable, "-I", "-S", "-B",
        str(ROOT / GENERATOR.GENERATOR_RELATIVE_PATH),
    ]
    for case_name, trailing in (
        ("help", ["--help"]),
        ("missing", []),
        ("invalid", ["--definitely-invalid"]),
    ):
        with test_case.subTest(generator_direct_entry=case_name):
            rejected = run_generator(direct_prefix + trailing)
            test_case.assertEqual(2, rejected.returncode)
            test_case.assertEqual(b"", rejected.stderr)
            rejected_lines = rejected.stdout.splitlines()
            test_case.assertEqual(1, len(rejected_lines), rejected.stdout)
            test_case.assertTrue(rejected_lines[0].startswith(
                GENERATOR.GENERATED_MARKER.encode("ascii")))
            rejected_payload = json.loads(rejected_lines[0][
                len(GENERATOR.GENERATED_MARKER):
            ])
            test_case.assertEqual(
                GENERATOR.GENERATION_RESULT_SCHEMA_VERSION,
                rejected_payload["schema_version"],
            )
            test_case.assertEqual(
                "GenerationError:generator_execution_component_binding_invalid",
                rejected_payload["failure"],
            )
            test_case.assertFalse(rejected_payload["validated_pass"])
            test_case.assertFalse(rejected_payload["formal_consumer"])
            test_case.assertFalse(rejected_payload["delivery_ready"])
            combined = rejected.stdout.lower() + rejected.stderr.lower()
            test_case.assertNotIn(b"usage:", combined)

    forged_contract = {
        "source_identity_before": GENERATOR._generator_source_identity(ROOT),
        "forged_direct_call": True,
    }
    with mock.patch.object(GENERATOR, "_load_core") as load_core:
        with test_case.assertRaisesRegex(
                GENERATOR.GenerationError,
                "^generator_execution_capability_invalid$"):
            GENERATOR._plan(ROOT, forged_contract)
    load_core.assert_not_called()
    with mock.patch.object(
            GENERATOR, "_require_generation_context") as generation_context:
        with test_case.assertRaisesRegex(
                GENERATOR.GenerationError,
                "^generator_execution_capability_invalid$"):
            GENERATOR._generate(ROOT, object())
    generation_context.assert_not_called()

    contract = _test_generator_execution_contract(ROOT, "--plan")
    capability = object()
    record = (
        capability, str(ROOT.resolve(strict=True)), "--plan",
        GENERATOR._canonical_json(contract),
        hashlib.sha256(GENERATOR._canonical_json(contract)).hexdigest(),
        os.getpid(),
    )
    with mock.patch.object(
            GENERATOR, "_PENDING_GENERATOR_EXECUTION_CAPABILITY", capability), \
            mock.patch.object(
                GENERATOR, "_PENDING_GENERATOR_EXECUTION_RECORD", record), \
            mock.patch.object(
                GENERATOR, "_CONSUMED_GENERATOR_EXECUTION_CAPABILITIES", []):
        consumed_contract = GENERATOR._consume_generator_execution_capability(
            capability, "--plan", ROOT,
        )
        test_case.assertEqual(contract, consumed_contract)
        with test_case.assertRaisesRegex(
                GENERATOR.GenerationError,
                "^generator_execution_capability_replayed$"):
            GENERATOR._consume_generator_execution_capability(
                capability, "--plan", ROOT,
            )

    generate_contract = _test_generator_execution_contract(
        ROOT, "--generate",
    )
    generate_capability = object()
    generate_record = (
        generate_capability, str(ROOT.resolve(strict=True)), "--generate",
        GENERATOR._canonical_json(generate_contract),
        hashlib.sha256(
            GENERATOR._canonical_json(generate_contract)).hexdigest(),
        os.getpid(),
    )
    with mock.patch.object(
            GENERATOR, "_PENDING_GENERATOR_EXECUTION_CAPABILITY",
            generate_capability,
        ), mock.patch.object(
            GENERATOR, "_PENDING_GENERATOR_EXECUTION_RECORD",
            generate_record,
        ), mock.patch.object(
            GENERATOR, "_CONSUMED_GENERATOR_EXECUTION_CAPABILITIES", [],
        ):
        test_case.assertEqual(
            generate_contract,
            GENERATOR._consume_generator_execution_capability(
                generate_capability, "--generate", ROOT,
            ),
        )

    for (
        failure_code, record_root, record_mode, expected_mode, process_id,
        consume_root,
    ) in (
        (
            "generator_execution_capability_mode_mismatch",
            str(ROOT.resolve(strict=True)), "--plan", "--generate",
            os.getpid(), ROOT,
        ),
        (
            "generator_execution_capability_process_mismatch",
            str(ROOT.resolve(strict=True)), "--plan", "--plan",
            os.getpid() + 1, ROOT,
        ),
        (
            "generator_execution_capability_root_mismatch",
            str(ROOT.resolve(strict=True)) + "-other", "--plan", "--plan",
            os.getpid(), ROOT,
        ),
    ):
        capability = object()
        record = (
            capability, record_root, record_mode,
            GENERATOR._canonical_json(contract),
            hashlib.sha256(GENERATOR._canonical_json(contract)).hexdigest(),
            process_id,
        )
        with test_case.subTest(generator_capability_failure=failure_code), \
                mock.patch.object(
                    GENERATOR, "_PENDING_GENERATOR_EXECUTION_CAPABILITY",
                    capability,
                ), mock.patch.object(
                    GENERATOR, "_PENDING_GENERATOR_EXECUTION_RECORD", record,
                ), mock.patch.object(
                    GENERATOR,
                    "_CONSUMED_GENERATOR_EXECUTION_CAPABILITIES", [],
                ):
            with test_case.assertRaisesRegex(
                    GENERATOR.GenerationError, "^" + failure_code + "$"):
                GENERATOR._consume_generator_execution_capability(
                    capability, expected_mode, consume_root,
                )

    drift_capability = object()
    drift_contract = deepcopy(contract)
    drift_contract["argv_sha256"] = "0" * 64
    drift_raw = GENERATOR._canonical_json(drift_contract)
    original_raw = GENERATOR._canonical_json(contract)
    drift_record = (
        drift_capability, str(ROOT.resolve(strict=True)), "--plan",
        drift_raw, hashlib.sha256(original_raw).hexdigest(), os.getpid(),
    )
    with mock.patch.object(
            GENERATOR, "_PENDING_GENERATOR_EXECUTION_CAPABILITY",
            drift_capability), mock.patch.object(
                GENERATOR, "_PENDING_GENERATOR_EXECUTION_RECORD",
                drift_record), mock.patch.object(
                    GENERATOR,
                    "_CONSUMED_GENERATOR_EXECUTION_CAPABILITIES", []):
        with test_case.assertRaisesRegex(
                GENERATOR.GenerationError,
                "^generator_execution_capability_contract_invalid$"):
            GENERATOR._consume_generator_execution_capability(
                drift_capability, "--plan", ROOT,
            )

    concurrent_capability = object()
    concurrent_raw = GENERATOR._canonical_json(contract)
    concurrent_record = (
        concurrent_capability, str(ROOT.resolve(strict=True)), "--plan",
        concurrent_raw, hashlib.sha256(concurrent_raw).hexdigest(), os.getpid(),
    )
    concurrent_results = []
    start = threading.Barrier(3)

    def consume_concurrently():
        start.wait()
        try:
            GENERATOR._consume_generator_execution_capability(
                concurrent_capability, "--plan", ROOT,
            )
            concurrent_results.append("accepted")
        except GENERATOR.GenerationError as error:
            concurrent_results.append(str(error))

    with mock.patch.object(
            GENERATOR, "_PENDING_GENERATOR_EXECUTION_CAPABILITY",
            concurrent_capability), mock.patch.object(
                GENERATOR, "_PENDING_GENERATOR_EXECUTION_RECORD",
                concurrent_record), mock.patch.object(
                    GENERATOR,
                    "_CONSUMED_GENERATOR_EXECUTION_CAPABILITIES", []):
        workers = [threading.Thread(target=consume_concurrently) for _ in range(2)]
        for worker in workers:
            worker.start()
        start.wait()
        for worker in workers:
            worker.join(timeout=10)
            test_case.assertFalse(worker.is_alive())
    test_case.assertEqual(
        ["accepted", "generator_execution_capability_replayed"],
        sorted(concurrent_results),
    )

    for case_name, trailing in (
        ("help", ["--help"]),
        ("invalid", ["--definitely-invalid"]),
        ("extra", ["--plan", "--definitely-invalid"]),
    ):
        with test_case.subTest(generator_bootstrap_entry=case_name):
            rejected = run_generator(generator_argv[:-1] + trailing)
            test_case.assertEqual(2, rejected.returncode)
            test_case.assertEqual(b"", rejected.stderr)
            rejected_lines = rejected.stdout.splitlines()
            test_case.assertEqual(1, len(rejected_lines), rejected.stdout)
            test_case.assertTrue(rejected_lines[0].startswith(
                GENERATOR.GENERATED_MARKER.encode("ascii")))
            rejected_payload = json.loads(rejected_lines[0][
                len(GENERATOR.GENERATED_MARKER):
            ])
            test_case.assertEqual(
                "GenerationError:generator_entry_arguments_invalid",
                rejected_payload["failure"],
            )
            combined = rejected.stdout.lower() + rejected.stderr.lower()
            test_case.assertNotIn(b"usage:", combined)

    wrong_expected_sha = list(generator_argv)
    wrong_expected_sha[9] = "0" * 64
    mismatch = run_generator(wrong_expected_sha)
    test_case.assertEqual(86, mismatch.returncode)
    test_case.assertEqual(b"", mismatch.stdout)
    test_case.assertIn(
        b"execution_component_expected_identity_mismatch", mismatch.stderr,
    )

    wrong_bootstrap_sha = list(generator_argv)
    wrong_bootstrap_sha[12] = "0" * 64
    bootstrap_drift = run_generator(wrong_bootstrap_sha)
    test_case.assertEqual(2, bootstrap_drift.returncode)
    test_case.assertEqual(b"", bootstrap_drift.stderr)
    test_case.assertIn(
        b"generator_execution_component_binding_invalid",
        bootstrap_drift.stdout,
    )

    wrong_component_kind = list(generator_argv)
    wrong_component_kind[10] = "runner"
    kind_drift = run_generator(wrong_component_kind)
    test_case.assertEqual(2, kind_drift.returncode)
    test_case.assertEqual(b"", kind_drift.stderr)
    test_case.assertIn(
        b"generator_execution_component_binding_invalid", kind_drift.stdout,
    )

    polluted_environment = dict(generator_environment)
    polluted_environment["PYTHONPATH"] = "FORBIDDEN"
    environment_drift = run_generator(generator_argv, polluted_environment)
    test_case.assertEqual(2, environment_drift.returncode)
    test_case.assertEqual(b"", environment_drift.stderr)
    test_case.assertIn(
        b"generator_environment_not_allowlisted", environment_drift.stdout,
    )

    canonical_windows_environment = {
        "SYSTEMROOT": r"C:\Windows",
        "WINDIR": r"C:\Windows",
        "COMSPEC": r"C:\Windows\System32\cmd.exe",
        "TEMP": r"C:\Temp",
        "TMP": r"C:\Temp",
    }
    with mock.patch.object(
            GENERATOR.os, "environ",
            {**canonical_windows_environment, "IGNORED": "not forwarded"}):
        normalized_windows_environment = GENERATOR._outer_windows_environment()
    test_case.assertEqual(
        canonical_windows_environment, normalized_windows_environment,
    )
    test_case.assertEqual(
        _sha(canonical_windows_environment),
        _sha(normalized_windows_environment),
    )
    test_case.assertNotIn("SystemRoot", normalized_windows_environment)

    for case_name, environment in (
        (
            "missing_systemroot",
            {
                key: value
                for key, value in canonical_windows_environment.items()
                if key != "SYSTEMROOT"
            },
        ),
        (
            "mixed_case_systemroot",
            {
                **{
                    key: value
                    for key, value in canonical_windows_environment.items()
                    if key != "SYSTEMROOT"
                },
                "SystemRoot": canonical_windows_environment["SYSTEMROOT"],
            },
        ),
    ):
        with test_case.subTest(windows_environment=case_name), \
                mock.patch.object(GENERATOR.os, "environ", environment):
            with test_case.assertRaisesRegex(
                    GENERATOR.GenerationError,
                    "^windows_systemroot_missing$"):
                GENERATOR._outer_windows_environment()

    for sensitive_key in GENERATOR.SENSITIVE_ENVIRONMENT:
        polluted = dict(canonical_windows_environment)
        polluted[sensitive_key] = "FORBIDDEN"
        with test_case.subTest(windows_sensitive_key=sensitive_key), \
                mock.patch.object(GENERATOR.os, "environ", polluted):
            with test_case.assertRaisesRegex(
                    GENERATOR.GenerationError,
                    "^generator_sensitive_environment_present$"):
                GENERATOR._outer_windows_environment()

    output = io.StringIO()
    with mock.patch.object(
            GENERATOR, "_generator_execution_contract",
            side_effect=GENERATOR.GenerationError(
                "generator_contract_invocation_sentinel")), \
            mock.patch.object(GENERATOR, "_plan") as plan_mock, \
            mock.patch.object(sys, "stdout", output):
        test_case.assertEqual(2, GENERATOR.main(["--plan"]))
    plan_mock.assert_not_called()
    test_case.assertIn(
        "generator_contract_invocation_sentinel", output.getvalue(),
    )


class FormalAdmissionEvidenceAuthorityV7Test(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve(strict=True)
        self.doc_target = "audit_tools/test_ros1_machine_contract_doc_demotion.py"
        self.atomic_target = "audit_tools/test_ros1_camera_only_atomic_launcher.py"
        self.field_target = (
            "src/limo_cleanup_perception/test/"
            "test_ros1_noetic_field_readiness_exact_cli.py"
        )
        self.runner_target = CORE.UNITTEST_RUNNER
        self.test_id = CORE.DOC_DEMOTION_LINK_CASE_ID
        self.atomic_test_id = CORE.ATOMIC_SUPPORTING_TEST_ID
        self.field_test_id = CORE.FIELD_READINESS_SUPPORTING_TEST_ID
        _write(
            self.root, self.doc_target,
            (
                "import unittest\n\n"
                "class Ros1MachineContractDocDemotionTest(unittest.TestCase):\n"
                "    def test_document_symlink_is_rejected(self):\n"
                "        self.assertTrue(True)\n"
            ).encode("utf-8"),
        )
        _write(self.root, self.runner_target, b"# isolated runner fixture\n")
        _write(
            self.root, self.atomic_target,
            (
                "import unittest\n\n"
                "class Ros1CameraOnlyAtomicLauncherTest(unittest.TestCase):\n"
                "    def test_production_cli_is_blocked_until_runtime_admission_is_bound(self):\n"
                "        self.assertTrue(True)\n"
            ).encode("utf-8"),
        )
        _write(
            self.root, self.field_target,
            (
                "import unittest\n\n"
                "class Ros1NoeticFieldReadinessExactCliTest(unittest.TestCase):\n"
                "    def test_production_cli_blocks_on_unbound_producer_index_before_inputs(self):\n"
                "        self.assertTrue(True)\n"
            ).encode("utf-8"),
        )
        for relative in (
            "audit_tools/ros1_camera_runtime_import_probe.py",
            "audit_tools/ros1_camera_runtime_install_admission.py",
            "audit_tools/ros1_camera_only_atomic_launcher.py",
            (
                "src/limo_cleanup_perception/limo_cleanup_perception/"
                "__init__.py"
            ),
            (
                "src/limo_cleanup_perception/limo_cleanup_perception/"
                "ros1_semantic_evidence_producer.py"
            ),
            (
                "src/limo_cleanup_perception/limo_cleanup_perception/"
                "ros1_noetic_field_readiness.py"
            ),
        ):
            _write(self.root, relative, ("# " + relative + "\n").encode("utf-8"))
        wrapper_binding = _write(
            self.root, CORE.GENERATION_WRAPPER_SOURCE_PATH,
            b"PRODUCTION_INDEX_TRUST_ANCHOR = None\n",
        )
        self.wrapper_identity = {
            key: wrapper_binding[key]
            for key in ("path", "size_bytes", "sha256")
        }
        for relative in (
            PYC_BROKER_RELATIVE_PATH, PYC_VERIFIER_RELATIVE_PATH,
            CORE.GENERATOR_SOURCE_PATH,
        ):
            _write(self.root, relative, (ROOT / relative).read_bytes())
        _write(self.root, "overlay/a.py", b"VALUE = 1\n")

        self.predecessor_evidence_id = "fixture_predecessor_evidence"
        self.predecessor_generation_id = "fixture_predecessor_generation"
        self.predecessor_predecessor_evidence_id = (
            "fixture_predecessor_predecessor_evidence"
        )
        predecessor_report = {
            "evidence_id": self.predecessor_evidence_id,
            "generation_id": self.predecessor_generation_id,
            "regression_passed": False,
            "delivery_ready": False,
            "authorizes_field_delivery": False,
        }
        predecessor_canonical = {
            "generation_id": self.predecessor_generation_id,
            "delivery_ready": False,
            "authorizes_field_delivery": False,
        }
        predecessor_index = {
            "authority_id": CORE.AUTHORITY_FAMILY_ID,
            "index_instance_id": "fixture-predecessor-index",
            "generation_id": self.predecessor_generation_id,
            "current_evidence_id": self.predecessor_evidence_id,
            "accepted_by_formal_field_evidence_consumer": False,
            "authorizes_field_delivery": False,
            "entries": [{
                "evidence_id": self.predecessor_evidence_id,
                "predecessor_evidence_id": (
                    self.predecessor_predecessor_evidence_id
                ),
                "is_current": True,
            }],
        }
        self.predecessor_report_identity = _write_json(
            self.root, "frozen/predecessor_report.json", predecessor_report,
        )
        self.predecessor_canonical_identity = _write_json(
            self.root, "frozen/predecessor_canonical.json", predecessor_canonical,
        )
        self.predecessor_index_identity = _write_json(
            self.root, "frozen/predecessor_index.json", predecessor_index,
        )
        self.predecessor_index_identity.update({
            "authority_id": CORE.AUTHORITY_FAMILY_ID,
            "index_instance_id": "fixture-predecessor-index",
            "generation_id": self.predecessor_generation_id,
            "current_evidence_id": self.predecessor_evidence_id,
        })

        source_definitions = (
            ("doc_test", "workspace", self.doc_target),
            ("unittest_runner", "workspace", self.runner_target),
            ("workspace_pyc_broker", "workspace", PYC_BROKER_RELATIVE_PATH),
            (
                "workspace_pyc_verifier", "workspace",
                PYC_VERIFIER_RELATIVE_PATH,
            ),
            (
                "successor_evidence_generator", "workspace",
                CORE.GENERATOR_SOURCE_PATH,
            ),
            ("probe", "workspace", "audit_tools/ros1_camera_runtime_import_probe.py"),
            ("install", "workspace", "audit_tools/ros1_camera_runtime_install_admission.py"),
            ("atomic", "workspace", "audit_tools/ros1_camera_only_atomic_launcher.py"),
            ("atomic_test", "workspace", self.atomic_target),
            (
                "semantic_package_init", "workspace",
                "src/limo_cleanup_perception/limo_cleanup_perception/"
                "__init__.py",
            ),
            (
                "semantic_producer", "workspace",
                "src/limo_cleanup_perception/limo_cleanup_perception/"
                "ros1_semantic_evidence_producer.py",
            ),
            (
                "field_readiness", "workspace",
                "src/limo_cleanup_perception/limo_cleanup_perception/"
                "ros1_noetic_field_readiness.py",
            ),
            ("field_readiness_test", "workspace", self.field_target),
            ("predecessor_index", "workspace", "frozen/predecessor_index.json"),
            ("predecessor_report", "workspace", "frozen/predecessor_report.json"),
            ("predecessor_canonical", "workspace", "frozen/predecessor_canonical.json"),
        )
        suites = (
            {
                "suite_id": "machine_contract_doc_demotion",
                "root_role": "workspace",
                "target": self.doc_target,
                "runner": "unittest",
            },
            {
                "suite_id": "camera_only_atomic_launcher",
                "root_role": "workspace",
                "target": self.atomic_target,
                "runner": "unittest",
            },
            {
                "suite_id": "field_readiness_exact_cli",
                "root_role": "workspace",
                "target": self.field_target,
                "runner": "unittest",
            },
        )
        executions = (
            {
                "record_id": "doc_demotion_windows_bundled",
                "suite_id": "machine_contract_doc_demotion",
                "platform": "WINDOWS_HOST",
                "interpreter_role": "bundled_host_python",
                "selection": "ALL",
            },
            {
                "record_id": "doc_demotion_link_posix_companion",
                "suite_id": "machine_contract_doc_demotion",
                "platform": "POSIX_WSL",
                "interpreter_role": "system_python314_target",
                "selection": self.test_id,
            },
            {
                "record_id": "atomic_wsl_python3",
                "suite_id": "camera_only_atomic_launcher",
                "platform": "POSIX_WSL",
                "interpreter_role": "system_python3_entry",
                "selection": "ALL",
            },
            {
                "record_id": "atomic_wsl_python314",
                "suite_id": "camera_only_atomic_launcher",
                "platform": "POSIX_WSL",
                "interpreter_role": "system_python314_target",
                "selection": "ALL",
            },
            {
                "record_id": "field_readiness_exact_cli_wsl_python314",
                "suite_id": "field_readiness_exact_cli",
                "platform": "POSIX_WSL",
                "interpreter_role": "system_python314_target",
                "selection": "ALL",
            },
        )
        self.policy = CORE.AuthorityPolicy(
            index_relative_path="out/index.json",
            report_relative_path="out/report.json",
            canonical_relative_path="out/canonical.json",
            source_role_definitions=source_definitions,
            suite_definitions=suites,
            execution_definitions=executions,
            predecessor_index_identity=self.predecessor_index_identity,
            predecessor_report_identity=self.predecessor_report_identity,
            predecessor_canonical_identity=self.predecessor_canonical_identity,
            predecessor_current_entry_predecessor_evidence_id=(
                self.predecessor_predecessor_evidence_id
            ),
            frozen_source_identities={},
            live_overlay_root="overlay",
            required_live_overlay_paths=("a.py",),
            host_perception_package_root=None,
            host_perception_package_files=(),
            host_perception_cache_files=(),
            allowed_empty_source_paths=(),
        )
        (self.root / "out").mkdir()
        self.source_roles = CORE.collect_source_role_bindings(
            self.root, self.policy,
        )
        self.logical = CORE.expected_logical_suite_records(
            self.root, self.source_roles, self.policy,
        )
        self.physical = sorted([
            self._physical_record(
                "doc_demotion_windows_bundled", "WINDOWS_HOST",
                "bundled_host_python", "machine_contract_doc_demotion",
                self.doc_target, self.test_id, passed=False,
            ),
            self._physical_record(
                "doc_demotion_link_posix_companion", "POSIX_WSL",
                "system_python314_target", "machine_contract_doc_demotion",
                self.doc_target, self.test_id, passed=True,
            ),
            self._physical_record(
                "atomic_wsl_python3", "POSIX_WSL",
                "system_python3_entry", "camera_only_atomic_launcher",
                self.atomic_target, self.atomic_test_id, passed=True,
            ),
            self._physical_record(
                "atomic_wsl_python314", "POSIX_WSL",
                "system_python314_target", "camera_only_atomic_launcher",
                self.atomic_target, self.atomic_test_id, passed=True,
            ),
            self._physical_record(
                "field_readiness_exact_cli_wsl_python314", "POSIX_WSL",
                "system_python314_target", "field_readiness_exact_cli",
                self.field_target, self.field_test_id, passed=True,
            ),
        ], key=lambda item: item["record_id"])
        failures, by_id = CORE._validate_physical_records(
            self.root, self.physical, self.source_roles, self.policy,
        )
        self.assertEqual(failures, [])
        self.composites = CORE._expected_platform_composites(by_id)
        self.observations = self._production_observations()
        self.generator_execution_contract = (
            self._generator_execution_contract("--generate")
        )

        canonical = CORE.build_canonical_payload(
            self.root, self.source_roles, self.policy,
        )
        self.canonical_identity = CORE.write_json_exclusive(
            self.root / "out" / "canonical.json", canonical,
            self.policy.canonical_relative_path,
        )
        self.report = CORE.build_report_payload(
            self.root, self.canonical_identity, self.source_roles,
            self.logical, self.physical, self.composites, self.observations,
            self.generator_execution_contract, self.policy,
        )
        self.report_identity = CORE.write_json_exclusive(
            self.root / "out" / "report.json", self.report,
            self.policy.report_relative_path,
        )
        self.payload = CORE.build_index_payload(
            self.report_identity, self.canonical_identity,
            self.source_roles, self.policy,
        )

    def tearDown(self):
        self.temporary.cleanup()

    def _bound_generation_wrapper(self):
        schema, bound, record_id, wrapper_read_required, runner_sha256 = (
            _AUTHORITY_RECORD_CONTEXT
        )
        self.assertEqual(_AUTHORITY_RECORD_CONTEXT_SCHEMA, schema)
        self.assertTrue(bound, "trusted authority test-child binding required")
        self.assertIn(record_id, {
            WINDOWS_AUTHORITY_RECORD_ID,
            CORE.GENERATION_WRAPPER_READ_RECORD_ID,
        })
        self.assertEqual(
            wrapper_read_required,
            record_id == CORE.GENERATION_WRAPPER_READ_RECORD_ID,
        )
        self.assertIsInstance(runner_sha256, str)
        self.assertEqual(64, len(runner_sha256))
        if wrapper_read_required:
            self.assertIsNotNone(WRAPPER)
            self.assertIs(sys.modules.get(_WRAPPER_MODULE_NAME), WRAPPER)
            return WRAPPER
        self.assertEqual(WINDOWS_AUTHORITY_RECORD_ID, record_id)
        self.assertIsNone(WRAPPER)
        self.assertNotIn(_WRAPPER_MODULE_NAME, sys.modules)
        return None

    def _assert_authority_record_binding_fail_closed(self):
        runner = sys.modules.get("__main__")
        self.assertIsNotNone(runner)
        self.assertEqual(
            _AUTHORITY_RECORD_CONTEXT,
            _authority_test_child_record_context(),
        )
        options = runner._strict_raw_options(None)

        wrong_record = SimpleNamespace(**vars(options))
        wrong_record.record_id = "probe_wsl_python314"
        with mock.patch.object(
                runner, "_strict_raw_options", return_value=wrong_record):
            with self.assertRaisesRegex(
                    RuntimeError,
                    "authority_test_child_record_binding_invalid:record_id"):
                _authority_test_child_record_context()

        wrong_mode = SimpleNamespace(**vars(options))
        wrong_mode.mode = "supervisor-v2"
        with mock.patch.object(
                runner, "_strict_raw_options", return_value=wrong_mode):
            with self.assertRaisesRegex(
                    RuntimeError,
                    "authority_test_child_record_binding_invalid:mode"):
                _authority_test_child_record_context()

        wrong_target = SimpleNamespace(**vars(options))
        wrong_target.target = "audit_tools/not_the_authority_test.py"
        with mock.patch.object(
                runner, "_strict_raw_options", return_value=wrong_target):
            with self.assertRaisesRegex(
                    RuntimeError,
                    "authority_test_child_record_binding_invalid:target"):
                _authority_test_child_record_context()

        with mock.patch.object(
                runner, "_current_runner_execution_binding", None):
            with self.assertRaisesRegex(
                    RuntimeError,
                    "authority_test_child_record_binding_invalid:"
                    "runner_surface_invalid"):
                _authority_test_child_record_context()

        drifted_binding = dict(runner.__execution_component_binding__)
        drifted_binding["sha256"] = "0" * 64
        with mock.patch.object(
                runner, "__execution_component_binding__", drifted_binding):
            with self.assertRaisesRegex(
                    RuntimeError,
                    "authority_test_child_record_binding_invalid:"
                    "runner_validation"):
                _authority_test_child_record_context()

    def _source(self, relative):
        item = next(
            record for record in self.source_roles
            if record["root_role"] == "workspace" and record["path"] == relative
        )
        return {
            key: item[key]
            for key in ("root_role", "path", "size_bytes", "sha256")
        }

    def _interpreter_identity(self, role):
        if role == "bundled_host_python":
            entry_path = str(self.root / "bundled-python.exe")
            entry_is_symlink = False
            entry_link_chain = []
            target_path = entry_path
        elif role == "system_python3_entry":
            entry_path = "/usr/bin/python3"
            entry_is_symlink = True
            entry_link_chain = [{
                "path": "/usr/bin/python3",
                "target": "python3.14",
            }]
            target_path = "/usr/bin/python3.14"
        elif role == "system_python314_target":
            entry_path = "/usr/bin/python3.14"
            entry_is_symlink = False
            entry_link_chain = []
            target_path = entry_path
        else:
            raise AssertionError("unexpected interpreter role: " + role)
        return {
            "entry_path": entry_path,
            "entry_is_symlink": entry_is_symlink,
            "entry_lstat_size_bytes": (
                32 if role == "system_python3_entry"
                else (
                    CORE.PYTHON314_TARGET_IDENTITY["size_bytes"]
                    if role == "system_python314_target" else 4096
                )
            ),
            "entry_link_chain": entry_link_chain,
            "resolved_target": (
                deepcopy(CORE.PYTHON314_TARGET_IDENTITY)
                if role in (
                    "system_python3_entry", "system_python314_target")
                else {
                    "path": target_path,
                    "size_bytes": 4096,
                    "sha256": "1" * 64,
                    "regular_file": True,
                    "is_symlink": False,
                }
            ),
            "isolated": True,
            "no_bytecode": True,
            "version": (
                list(CORE.PYTHON314_VERSION)
                if role in (
                    "system_python3_entry", "system_python314_target")
                else [3, 14, 0]
            ),
        }

    @staticmethod
    def _orchestrator_identity():
        return {
            "path": r"C:\Windows\System32\wsl.exe",
            "size_bytes": 4096,
            "sha256": "2" * 64,
            "hardlink_count": 2,
        }

    def _generator_execution_contract(self, mode):
        generator_source = self._source(CORE.GENERATOR_SOURCE_PATH)
        generator_identity = {
            key: generator_source[key]
            for key in ("path", "size_bytes", "sha256")
        }
        windows_record = next(
            item for item in self.physical
            if item["platform"] == "WINDOWS_HOST"
        )
        target = windows_record["interpreter_identity"]["resolved_target"]
        interpreter_identity = {
            "path": target["path"],
            "size_bytes": target["size_bytes"],
            "sha256": target["sha256"],
            "hardlink_count": 1,
        }
        workspace_path = windows_record["marker_payload"]["workspace"]
        argv = CORE.expected_generator_execution_argv(
            workspace_path, generator_identity, interpreter_identity, mode,
        )
        return {
            "schema_version": CORE.GENERATOR_EXECUTION_CONTRACT_SCHEMA,
            "mode": mode,
            "bootstrap_schema_version": (
                CORE.EXECUTION_COMPONENT_BOOTSTRAP_SCHEMA
            ),
            "bootstrap_sha256": CORE.EXECUTION_COMPONENT_BOOTSTRAP_SHA256,
            "generator_identity": deepcopy(generator_identity),
            "execution_binding": {
                "schema_version": CORE.EXECUTION_COMPONENT_BOOTSTRAP_SCHEMA,
                "component_kind": "generator",
                **deepcopy(generator_identity),
                "bootstrap_sha256": (
                    CORE.EXECUTION_COMPONENT_BOOTSTRAP_SHA256
                ),
            },
            "source_identity_before": deepcopy(generator_identity),
            "source_identity_after": deepcopy(generator_identity),
            "interpreter_identity": interpreter_identity,
            "argv": argv,
            "argv_sha256": _sha(argv),
            "environment": deepcopy(windows_record["environment"]),
            "environment_sha256": _sha(windows_record["environment"]),
            "cwd": workspace_path,
            "expected_marker_prefix": (
                CORE.GENERATOR_RESULT_MARKER if mode == "--generate"
                else "OFFLINE_ROS1_PYC_IDENTITY_GATE_PLAN "
            ),
            "expected_result_schema": (
                CORE.GENERATOR_RESULT_SCHEMA if mode == "--generate"
                else "ros1_pyc_identity_gate_plan/v2"
            ),
        }

    def _physical_record(
        self, record_id, platform, interpreter_role, suite_id,
        test_target, test_id, passed,
    ):
        test_identity = self._source(test_target)
        runner_identity = self._source(self.runner_target)
        passed_ids = [test_id] if passed else []
        skipped_ids = [] if passed else [test_id]
        marker = {
            "workspace": str(self.root),
            "path": test_target,
            "size_bytes": test_identity["size_bytes"],
            "sha256": test_identity["sha256"],
            "expected_ids": [test_id],
            "executed_ids": [test_id],
            "collected": 1,
            "passed": len(passed_ids),
            "failed": 0,
            "skipped": len(skipped_ids),
            "workspace_bytecode_policy": CORE.WORKSPACE_BYTECODE_POLICY,
            "workspace_pyc_bytes_read": 0,
            "workspace_pyc_attempts_blocked": [],
            "workspace_source_reads": [{
                "path": test_identity["path"],
                "size_bytes": test_identity["size_bytes"],
                "sha256": test_identity["sha256"],
            }],
            "workspace_loader_guard_restored": True,
            "workspace_pyc_audit_hook_active": True,
            "workspace_pyc_inode_policy": CORE.WORKSPACE_PYC_INODE_POLICY,
            "workspace_pyc_inventory_count": 0,
            "workspace_pyc_inventory_stable": True,
        }
        interpreter_identity = self._interpreter_identity(interpreter_role)
        orchestrator_identity = (
            None if platform == "WINDOWS_HOST"
            else self._orchestrator_identity()
        )
        definition = next(
            item for item in self.policy.execution_definitions
            if item["record_id"] == record_id
        )
        suite = next(
            item for item in CORE.suite_inventory(self.root, self.policy)
            if item["suite_id"] == definition["suite_id"]
        )
        profile = CORE.runner_profile(suite["runner"])
        argv = CORE._expected_child_argv(
            self.root, definition, suite, [test_id],
            interpreter_identity, orchestrator_identity, runner_identity,
        )
        environment = (
            {"SYSTEMROOT": r"C:\Windows"}
            if platform == "WINDOWS_HOST"
            else dict(CORE.CHILD_ENVIRONMENT)
        )
        identities = [dict(item, regular_file=True, non_linklike=True,
                           nlink=1, fd_inheritable=False)
                      for item in CORE.workspace_pyc_inventory()]

        def broker_event(event, checkpoint_index, phase):
            digest_material = "{}:{}:{}".format(
                record_id, checkpoint_index, phase,
            ).encode("utf-8")
            return {
                "schema_version": CORE.PYC_BROKER_RESULT_SCHEMA,
                "event": event,
                "record_id": record_id,
                "checkpoint_index": checkpoint_index,
                "phase": phase,
                "inventory_sha256": CORE.workspace_pyc_inventory_sha256(),
                "nonce_sha256": hashlib.sha256(
                    b"fixture-nonce:" + record_id.encode("utf-8")
                ).hexdigest(),
                "identities": deepcopy(identities),
                "raw_bytes_exported": False,
                "file_descriptors_exported": False,
                "descriptor_count": 0 if event == "FINAL" else 18,
                "descriptors_closed": event == "FINAL",
                "nonce_invalidated": event == "FINAL",
                "broker_execution_binding": broker_execution_binding,
                "hmac_sha256": hashlib.sha256(digest_material).hexdigest(),
            }

        broker_source_identity = self._source(PYC_BROKER_RELATIVE_PATH)
        verifier_source_identity = self._source(PYC_VERIFIER_RELATIVE_PATH)
        broker_artifact_identity = {
            key: broker_source_identity[key]
            for key in ("path", "size_bytes", "sha256")
        }
        verifier_artifact_identity = {
            key: verifier_source_identity[key]
            for key in ("path", "size_bytes", "sha256")
        }
        broker_execution_binding = {
            "schema_version": CORE.EXECUTION_COMPONENT_BOOTSTRAP_SCHEMA,
            "component_kind": "broker",
            "path": broker_artifact_identity["path"],
            "size_bytes": broker_artifact_identity["size_bytes"],
            "sha256": broker_artifact_identity["sha256"],
            "bootstrap_sha256": CORE.EXECUTION_COMPONENT_BOOTSTRAP_SHA256,
        }
        broker_argv = CORE.expected_pyc_broker_argv(
            self.root, definition, interpreter_identity,
            broker_artifact_identity,
        )
        broker_transcript = {
            "schema_version": CORE.PYC_BROKER_TRANSCRIPT_SCHEMA,
            "record_id": record_id,
            "broker_artifact_identity": deepcopy(broker_artifact_identity),
            "broker_execution_binding": broker_execution_binding,
            "verifier_artifact_identity": deepcopy(verifier_artifact_identity),
            "argv": broker_argv,
            "argv_sha256": _sha(broker_argv),
            "environment": environment,
            "environment_sha256": _sha(environment),
            "ready": broker_event("READY", 0, "READY"),
            "checkpoints": [
                broker_event("CHECKPOINT", 1, "AFTER_PRODUCTION_WRAPPER"),
                broker_event("CHECKPOINT", 2, "AFTER_TEST_CHILD"),
            ],
            "final": broker_event("FINAL", 3, "FINAL"),
            "stderr": _stream(),
            "exit_code": 0,
        }
        verifier_result = {
            "schema_version": CORE.PYC_VERIFIER_RESULT_SCHEMA,
            "validated_pass": True,
            "record_id": record_id,
            "inventory_count": len(CORE.workspace_pyc_inventory()),
            "inventory_sha256": CORE.workspace_pyc_inventory_sha256(),
            "checkpoint_count": 2,
            "raw_bytes_exposed": False,
            "file_descriptors_exposed": False,
            "broker_execution_binding": broker_execution_binding,
            "failures": [],
        }
        wrapper_result = {
            "schema_version": CORE.SCHEMA_VERSION,
            "validated_pass": False,
            "semantic_validated_pass": False,
            "accepted_as_offline_release_selection_authority": False,
            "accepted_by_formal_field_evidence_consumer": False,
            "delivery_ready": False,
            "authorizes_field_delivery": False,
            "formal_four_scene_frame_denominator": 0,
            "ros1_noetic_runtime_verified": False,
            "ros1_noetic_build_install_verified": False,
            "ros1_noetic_field_install_pass": False,
            "current_evidence": None,
            "failures": [
                "formal_authority_v7_production_anchor_not_configured",
            ],
        }
        wrapper_payload = {
            "schema_version": CORE.PRODUCTION_WRAPPER_RESOLUTION_SCHEMA,
            "wrapper_identity": deepcopy(self.wrapper_identity),
            "capability_surface": deepcopy(
                CORE.PRODUCTION_WRAPPER_EMPTY_CAPABILITY_SURFACE
            ),
            "result": wrapper_result,
        }
        wrapper_argv = CORE.expected_production_wrapper_argv(
            self.root, definition, interpreter_identity,
        )
        wrapper_stdout = (
            CORE.PRODUCTION_WRAPPER_MARKER.encode("ascii")
            + CORE._canonical_json(wrapper_payload) + b"\n"
        )
        wrapper_observation = {
            "schema_version": CORE.PRODUCTION_WRAPPER_OBSERVATION_SCHEMA,
            "record_id": record_id,
            "path": CORE.GENERATION_WRAPPER_SOURCE_PATH,
            "parent_before": deepcopy(self.wrapper_identity),
            "parent_after": deepcopy(self.wrapper_identity),
            "argv": wrapper_argv,
            "argv_sha256": _sha(wrapper_argv),
            "environment": environment,
            "environment_sha256": _sha(environment),
            "exit_code": 0,
            "marker_count": 1,
            "marker_prefix": CORE.PRODUCTION_WRAPPER_MARKER,
            "payload": wrapper_payload,
            "payload_sha256": _sha(wrapper_payload),
            "stdout": _stream(wrapper_stdout),
            "stderr": _stream(),
        }
        marker.update({
            "schema_version": profile["result_schema"],
            "runner_kind": profile["runner_kind"],
            "record_id": record_id,
            "suite_id": suite_id,
            "workspace_pyc_inode_policy": CORE.WORKSPACE_PYC_INODE_POLICY,
            "workspace_pyc_inventory_count": len(
                CORE.workspace_pyc_inventory()
            ),
            "pyc_broker_transcript": broker_transcript,
            "pyc_verifier_result": verifier_result,
            "production_wrapper_observation": wrapper_observation,
            "runner_execution_binding": {
                "schema_version": CORE.EXECUTION_COMPONENT_BOOTSTRAP_SCHEMA,
                "component_kind": "runner",
                "path": runner_identity["path"],
                "size_bytes": runner_identity["size_bytes"],
                "sha256": runner_identity["sha256"],
                "bootstrap_sha256": CORE.EXECUTION_COMPONENT_BOOTSTRAP_SHA256,
            },
        })
        marker["child_runner_execution_binding"] = deepcopy(
            marker["runner_execution_binding"])
        marker["child_argv"] = CORE.expected_runner_test_child_argv(
            self.root, definition, suite, [test_id], interpreter_identity,
            runner_identity,
        )
        marker["child_argv_sha256"] = _sha(marker["child_argv"])
        marker["executable"] = interpreter_identity
        return {
            "record_id": record_id,
            "suite_id": suite_id,
            "platform": platform,
            "interpreter_role": interpreter_role,
            "runner_kind": profile["runner_kind"],
            "result_schema": profile["result_schema"],
            "test_artifact_identity": test_identity,
            "runner_artifact_identity": runner_identity,
            "interpreter_identity": interpreter_identity,
            "orchestrator_identity": orchestrator_identity,
            "expected_test_ids": [test_id],
            "executed_test_ids": [test_id],
            "passed_ids": passed_ids,
            "failed_ids": [],
            "skipped_ids": skipped_ids,
            "collected": 1,
            "passed": len(passed_ids),
            "failed": 0,
            "skipped": len(skipped_ids),
            "exit_code": 0,
            "marker_count": 1,
            "marker_prefix": CORE.UNITTEST_MARKER,
            "marker_payload": marker,
            "marker_payload_sha256": _sha(marker),
            "argv": argv,
            "argv_sha256": _sha(argv),
            "environment": environment,
            "environment_sha256": _sha(environment),
            "stdout": _stream(),
            "stderr": _stream(),
            "external_wrapper_observation": None,
            "pyc_broker_transcript": broker_transcript,
            "pyc_verifier_result": verifier_result,
            "production_wrapper_observation": wrapper_observation,
        }

    def _production_observations(self):
        result = []
        for definition in CORE.PRODUCTION_CLI_EXPECTATIONS:
            source = self._source(definition["source_path"])
            attempted = definition["execution_attempted"]
            if attempted:
                interpreter_identity = self._interpreter_identity(
                    "system_python314_target"
                )
                orchestrator_identity = self._orchestrator_identity()
                environment = dict(CORE.CHILD_ENVIRONMENT)
                argv = CORE._expected_production_cli_argv(
                    self.root, definition, orchestrator_identity["path"],
                    self.source_roles,
                    interpreter_identity,
                )
            else:
                interpreter_identity = None
                orchestrator_identity = None
                argv = ["NOT_EXECUTED_SAFETY_BOUNDARY"]
                environment = {}
            if attempted:
                payload = CORE.expected_unbound_production_payload(definition)
            else:
                payload = {
                    "execution_attempted": False,
                    "supporting_test_id": definition["supporting_test_id"],
                    "supporting_record_ids": list(
                        definition["supporting_record_ids"]),
                    "blocked_code": definition["blocked_code"],
                }
            runtime_dependencies = []
            if attempted:
                for relative in CORE.production_runtime_dependency_paths(
                        definition):
                    identity = self._source(relative)
                    signature = CORE.source_runtime_signature(
                        self.root, "workspace", relative)
                    runtime_dependencies.append({
                        "path": relative,
                        "identity_before": deepcopy(identity),
                        "identity_after": deepcopy(identity),
                        "signature_before": deepcopy(signature),
                        "signature_after": deepcopy(signature),
                    })
            stdout = CORE.expected_production_observation_stdout(
                definition, payload)
            stderr = CORE.expected_production_observation_stderr(definition)
            result.append({
                "observation_id": definition["observation_id"],
                "source_identity_before": source,
                "source_identity_after": source,
                "runtime_dependencies": runtime_dependencies,
                "interpreter_identity": interpreter_identity,
                "orchestrator_identity": orchestrator_identity,
                "argv": argv,
                "argv_sha256": _sha(argv),
                "environment": environment,
                "environment_sha256": _sha(environment),
                "exit_code": definition["exit_code"],
                "marker_count": definition["marker_count"],
                "blocked_code": definition["blocked_code"],
                "failure_codes": [definition["blocked_code"]],
                "stdout": _stream(stdout),
                "stderr": _stream(stderr),
                "payload": payload,
                "payload_sha256": _sha(payload),
                "expected_fail_closed": True,
                "not_in_logical_denominator": True,
                "not_in_physical_denominator": True,
                "formal_consumer": False,
                "delivery_ready": False,
                "self_reported_anchor_accepted": False,
                "execution_attempted": attempted,
                "supporting_test_id": definition["supporting_test_id"],
            })
        return sorted(result, key=lambda item: item["observation_id"])

    def _validate(self, payload=None):
        return CORE.validate_formal_admission_evidence_authority_v7(
            self.root, self.payload if payload is None else payload,
            self.policy,
        )

    def _replace_report(self, mutate):
        value = deepcopy(self.report)
        mutate(value)
        material = dict(value)
        material.pop("report_binding_sha256", None)
        value["report_binding_sha256"] = _sha(material)
        path = self.root / self.policy.report_relative_path
        path.write_bytes(_json_bytes(value))
        identity = {
            "path": self.policy.report_relative_path,
            "size_bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        self.payload = CORE.build_index_payload(
            identity, self.canonical_identity, self.source_roles, self.policy,
        )

    def test_valid_payload_is_offline_only(self):
        result = self._validate()
        self.assertTrue(result["semantic_validated_pass"], result["failures"])
        self.assertFalse(result["accepted_by_formal_field_evidence_consumer"])
        self.assertFalse(result["regression_passed"])
        self.assertFalse(result["ros1_noetic_runtime_verified"])
        self.assertFalse(result["ros1_noetic_build_install_verified"])
        self.assertFalse(result["delivery_ready"])

    def test_exact_anchor_resolver_accepts_only_offline_selection(self):
        identity = CORE.write_json_exclusive(
            self.root / self.policy.index_relative_path, self.payload,
            self.policy.index_relative_path,
        )
        result = CORE.load_and_resolve_formal_admission_evidence_authority_v7(
            self.root, identity, self.policy,
        )
        self.assertTrue(result["validated_pass"], result["failures"])
        self.assertTrue(result["accepted_as_offline_release_selection_authority"])
        self.assertTrue(
            result["semantic_evidence_producer_contract_implemented"]
        )
        self.assertTrue(
            result["semantic_evidence_producer_offline_algorithm_validated"]
        )
        self.assertFalse(
            result["semantic_evidence_producer_production_authority_bound"]
        )
        self.assertFalse(
            result["semantic_evidence_producer_formal_evidence_admitted"]
        )
        self.assertFalse(result["delivery_ready"])
        self.assertEqual(result["current_evidence"]["evidence_id"], CORE.CURRENT_EVIDENCE_ID)

    def test_wrong_anchor_path_size_and_hash_fail_closed(self):
        identity = CORE.write_json_exclusive(
            self.root / self.policy.index_relative_path, self.payload,
            self.policy.index_relative_path,
        )
        for key, value in (
            ("path", "out/other.json"),
            ("size_bytes", identity["size_bytes"] + 1),
            ("sha256", "0" * 64),
        ):
            anchor = dict(identity)
            anchor[key] = value
            result = CORE.load_and_resolve_formal_admission_evidence_authority_v7(
                self.root, anchor, self.policy,
            )
            self.assertFalse(result["validated_pass"], key)
            self.assertIsNone(result["current_evidence"], key)

    def test_missing_and_duplicate_current_are_rejected(self):
        for mutate in (
            lambda value: value["entries"][1].update(is_current=False),
            lambda value: value["entries"][0].update(is_current=True),
        ):
            payload = deepcopy(self.payload)
            mutate(payload)
            result = self._validate(payload)
            self.assertFalse(result["semantic_validated_pass"])
            self.assertIn("formal_authority_v7_current_count_invalid", result["failures"])

    def test_old_v6_entry_cannot_be_repromoted(self):
        payload = deepcopy(self.payload)
        payload["entries"][0]["is_current"] = True
        payload["entries"][1]["is_current"] = False
        payload["current_evidence_id"] = self.predecessor_evidence_id
        result = self._validate(payload)
        self.assertFalse(result["semantic_validated_pass"])
        self.assertTrue(any("current" in item for item in result["failures"]))

    def test_predecessor_identity_and_instance_are_exact(self):
        for key, value in (
            ("index_instance_id", "wrong"),
            ("size_bytes", self.predecessor_index_identity["size_bytes"] + 1),
            ("sha256", "0" * 64),
        ):
            payload = deepcopy(self.payload)
            payload["predecessor_authority_index"][key] = value
            result = self._validate(payload)
            self.assertFalse(result["semantic_validated_pass"], key)

    def test_predecessor_current_entry_lineage_is_exact(self):
        predecessor = {
            "authority_id": CORE.AUTHORITY_FAMILY_ID,
            "index_instance_id": self.predecessor_index_identity[
                "index_instance_id"
            ],
            "generation_id": self.predecessor_generation_id,
            "current_evidence_id": self.predecessor_evidence_id,
            "accepted_by_formal_field_evidence_consumer": False,
            "authorizes_field_delivery": False,
            "entries": [{
                "evidence_id": self.predecessor_evidence_id,
                "predecessor_evidence_id": "wrong-lineage",
                "is_current": True,
            }],
        }
        failures = CORE._validate_predecessor_payload(
            predecessor, self.policy,
        )
        self.assertIn(
            "formal_authority_v7_predecessor_current_lineage_mismatch",
            failures,
        )

    def test_source_role_root_path_size_and_hash_are_exact(self):
        for key, value in (
            ("root_role", "workspace_parent"),
            ("path", "audit_tools/other.py"),
            ("size_bytes", 999),
            ("sha256", "0" * 64),
        ):
            payload = deepcopy(self.payload)
            payload["source_roles"][0][key] = value
            payload["source_role_set_sha256"] = _sha(payload["source_roles"])
            result = self._validate(payload)
            self.assertFalse(result["semantic_validated_pass"], key)

    def test_missing_duplicate_source_roles_and_missing_canonical_child_are_rejected(self):
        payload = deepcopy(self.payload)
        payload["source_roles"].pop()
        payload["source_role_count"] = len(payload["source_roles"])
        payload["source_role_set_sha256"] = _sha(payload["source_roles"])
        result = self._validate(payload)
        self.assertFalse(result["validated_pass"])
        self.assertIsNone(result["current_evidence"])
        self.assertIn("formal_authority_v7_source_role_set_invalid", result["failures"])

        payload = deepcopy(self.payload)
        payload["source_roles"].append(deepcopy(payload["source_roles"][0]))
        payload["source_role_count"] = len(payload["source_roles"])
        payload["source_role_set_sha256"] = _sha(payload["source_roles"])
        result = self._validate(payload)
        self.assertFalse(result["validated_pass"])
        self.assertIsNone(result["current_evidence"])
        self.assertTrue(any(
            "source_role_duplicate" in failure
            for failure in result["failures"]
        ))

        payload = deepcopy(self.payload)
        payload["child_artifacts"] = []
        result = self._validate(payload)
        self.assertFalse(result["validated_pass"])
        self.assertIsNone(result["current_evidence"])
        self.assertIn(
            "formal_authority_v7_child_artifacts_invalid", result["failures"]
        )

    def test_unhashable_json_identity_fields_fail_closed_without_exception(self):
        payload = deepcopy(self.payload)
        payload["source_roles"][0]["path"] = []
        payload["source_role_set_sha256"] = _sha(payload["source_roles"])
        result = self._validate(payload)
        self.assertFalse(result["validated_pass"])
        self.assertIsNone(result["current_evidence"])
        self.assertTrue(any(
            "source_role_identity_type_invalid" in failure
            for failure in result["failures"]
        ))

        payload = deepcopy(self.payload)
        payload["entries"][1]["evidence_id"] = []
        result = self._validate(payload)
        self.assertFalse(result["validated_pass"])
        self.assertIsNone(result["current_evidence"])
        self.assertIn("formal_authority_v7_entry_invalid", result["failures"])

        self._replace_report(
            lambda value: value["test_matrix"][
                "physical_execution_records"
            ][0].update(record_id=[])
        )
        result = self._validate()
        self.assertFalse(result["validated_pass"])
        self.assertIsNone(result["current_evidence"])
        self.assertEqual(
            result["failures"],
            [
                "formal_authority_v7_artifact_semantic_recompute_failed:"
                + CORE.CURRENT_EVIDENCE_ID
            ],
        )

        self._replace_report(
            lambda value: value["production_cli_observations"][0].update(
                observation_id=[]
            )
        )
        result = self._validate()
        self.assertFalse(result["validated_pass"])
        self.assertIsNone(result["current_evidence"])
        self.assertTrue(any(
            "production_observation_id_invalid" in failure
            for failure in result["failures"]
        ))

    def test_source_artifact_drift_is_rejected(self):
        path = self.root / "audit_tools" / "ros1_camera_runtime_import_probe.py"
        original = path.read_bytes()
        path.write_bytes(original + b"# drift\n")
        result = self._validate()
        self.assertFalse(result["semantic_validated_pass"])
        self.assertTrue(any("source_role_identity_mismatch" in item for item in result["failures"]))
        path.write_bytes(original)

        definition = next(
            item for item in CORE.PRODUCTION_CLI_EXPECTATIONS
            if item["observation_id"] == "runtime_import_probe_unbound"
        )
        interpreter = self._interpreter_identity("system_python314_target")
        orchestrator = self._orchestrator_identity()
        wsl_path = Path(orchestrator["path"])
        payload = CORE.expected_unbound_production_payload(definition)
        completed = subprocess.CompletedProcess(
            [], definition["exit_code"],
            (
                definition["marker_prefix"].encode("ascii")
                + CORE._canonical_json(payload) + b"\n"
            ),
            b"",
        )
        outer = mock.patch.object(
            GENERATOR, "_outer_windows_environment",
            return_value={"SYSTEMROOT": r"C:\Windows"},
        )
        with outer:
            observation = GENERATOR._run_production_cli(
                CORE, self.root, self.source_roles, definition,
                interpreter, orchestrator, wsl_path,
                _command_runner=lambda *unused_args, **unused_kwargs: completed,
            )
        cached = self._source(definition["source_path"])
        self.assertEqual(cached, observation["source_identity_before"])
        self.assertEqual(cached, observation["source_identity_after"])

        malformed_streams = (
            (completed.stdout[:-1], completed.stderr,
             "production_cli_stdout_mismatch:runtime_import_probe_unbound"),
            (completed.stdout + b"\n", completed.stderr,
             "production_cli_stdout_mismatch:runtime_import_probe_unbound"),
            (completed.stdout, b"unexpected stderr\n",
             "production_cli_stderr_mismatch:runtime_import_probe_unbound"),
        )
        for stdout, stderr, expected_error in malformed_streams:
            malformed = subprocess.CompletedProcess(
                [], definition["exit_code"], stdout, stderr)
            with mock.patch.object(
                    GENERATOR, "_outer_windows_environment",
                    return_value={"SYSTEMROOT": r"C:\Windows"}):
                with self.assertRaises(GENERATOR.GenerationError) as raised:
                    GENERATOR._run_production_cli(
                        CORE, self.root, self.source_roles, definition,
                        interpreter, orchestrator, wsl_path,
                        _command_runner=lambda *unused_args, _value=malformed,
                        **unused_kwargs: _value,
                    )
            self.assertEqual(expected_error, str(raised.exception))

        for case, expected_error in (
            ("unknown", "production_payload_schema_invalid:"
             "runtime_import_probe_unbound"),
            ("elevated", "production_payload_semantic_mismatch:"
             "runtime_import_probe_unbound"),
        ):
            forged_payload = deepcopy(payload)
            if case == "unknown":
                forged_payload["unknown_elevation"] = True
            else:
                forged_payload["formal_consumer"] = True
            forged_stdout = (
                definition["marker_prefix"].encode("ascii")
                + CORE._canonical_json(forged_payload) + b"\n"
            )
            forged = subprocess.CompletedProcess(
                [], definition["exit_code"], forged_stdout, b"")
            with mock.patch.object(
                    GENERATOR, "_outer_windows_environment",
                    return_value={"SYSTEMROOT": r"C:\Windows"}):
                with self.assertRaises(GENERATOR.GenerationError) as raised:
                    GENERATOR._run_production_cli(
                        CORE, self.root, self.source_roles, definition,
                        interpreter, orchestrator, wsl_path,
                        _command_runner=lambda *unused_args, _value=forged,
                        **unused_kwargs: _value,
                    )
            self.assertEqual(expected_error, str(raised.exception))

        replacement = path.with_name("runtime-probe-replacement.py")
        replacement.write_bytes(b"X" * len(original))
        os.replace(replacement, path)
        calls = []
        with mock.patch.object(
                GENERATOR, "_outer_windows_environment",
                return_value={"SYSTEMROOT": r"C:\Windows"}):
            with self.assertRaisesRegex(
                    GENERATOR.GenerationError,
                    "production_cli_source_identity_mismatch_before:"
                    "runtime_import_probe_unbound"):
                GENERATOR._run_production_cli(
                    CORE, self.root, self.source_roles, definition,
                    interpreter, orchestrator, wsl_path,
                    _command_runner=lambda *args, **kwargs: calls.append(
                        (args, kwargs)),
                )
        self.assertEqual([], calls)
        path.write_bytes(original)

        def drift_then_restore(*unused_args, **unused_kwargs):
            path.write_bytes(original + b"# transient drift\n")
            path.write_bytes(original)
            metadata = path.stat()
            os.utime(
                path,
                ns=(metadata.st_atime_ns, metadata.st_mtime_ns + 1_000_000),
            )
            return completed

        with mock.patch.object(
                GENERATOR, "_outer_windows_environment",
                return_value={"SYSTEMROOT": r"C:\Windows"}):
            with self.assertRaises(GENERATOR.GenerationError) as raised:
                GENERATOR._run_production_cli(
                    CORE, self.root, self.source_roles, definition,
                    interpreter, orchestrator, wsl_path,
                    _command_runner=drift_then_restore,
                )
        self.assertEqual(
            "production_cli_source_runtime_drift:runtime_import_probe_unbound",
            str(raised.exception),
        )

        persistent_calls = []
        def drift_without_restore(*unused_args, **unused_kwargs):
            persistent_calls.append(True)
            path.write_bytes(original + b"# persistent drift\n")
            return completed

        try:
            with mock.patch.object(
                    GENERATOR, "_outer_windows_environment",
                    return_value={"SYSTEMROOT": r"C:\Windows"}):
                with self.assertRaises(GENERATOR.GenerationError) as raised:
                    GENERATOR._run_production_cli(
                        CORE, self.root, self.source_roles, definition,
                        interpreter, orchestrator, wsl_path,
                        _command_runner=drift_without_restore,
                    )
            self.assertEqual(
                "production_cli_source_identity_mismatch_after:"
                "runtime_import_probe_unbound",
                str(raised.exception),
            )
            self.assertEqual([True], persistent_calls)
        finally:
            path.write_bytes(original)

        semantic = next(
            item for item in CORE.PRODUCTION_CLI_EXPECTATIONS
            if item["observation_id"] == "semantic_producer_authority_unbound"
        )
        semantic_payload = CORE.expected_unbound_production_payload(semantic)
        semantic_success_completed = subprocess.CompletedProcess(
            [], semantic["exit_code"],
            CORE._canonical_json(semantic_payload) + b"\n",
            b"",
        )
        dependency_paths = (
            "src/limo_cleanup_perception/limo_cleanup_perception/__init__.py",
            "src/limo_cleanup_perception/limo_cleanup_perception/"
            "ros1_noetic_field_readiness.py",
        )
        for dependency_relative in dependency_paths:
            dependency_path = self.root.joinpath(
                *dependency_relative.split("/"))
            dependency_original = dependency_path.read_bytes()
            dependency_before_code = (
                "production_cli_runtime_dependency_identity_mismatch_before:"
                "semantic_producer_authority_unbound:"
                + dependency_relative
            )
            dependency_after_code = (
                "production_cli_runtime_dependency_identity_mismatch_after:"
                "semantic_producer_authority_unbound:"
                + dependency_relative
            )
            dependency_runtime_code = (
                "production_cli_runtime_dependency_runtime_drift:"
                "semantic_producer_authority_unbound:"
                + dependency_relative
            )

            calls = []
            dependency_path.write_bytes(
                dependency_original + b"# dependency before drift\n")
            try:
                with mock.patch.object(
                        GENERATOR, "_outer_windows_environment",
                        return_value={"SYSTEMROOT": r"C:\Windows"}):
                    with self.assertRaises(
                            GENERATOR.GenerationError) as raised:
                        GENERATOR._run_production_cli(
                            CORE, self.root, self.source_roles, semantic,
                            interpreter, orchestrator, wsl_path,
                            _command_runner=lambda *args, **kwargs:
                            calls.append((args, kwargs)),
                        )
                self.assertEqual(dependency_before_code, str(raised.exception))
                self.assertEqual([], calls)
            finally:
                dependency_path.write_bytes(dependency_original)

            persistent_calls = []
            def dependency_drift_without_restore(
                    *unused_args, **unused_kwargs):
                persistent_calls.append(True)
                dependency_path.write_bytes(
                    dependency_original + b"# dependency persistent drift\n")
                return semantic_success_completed

            try:
                with mock.patch.object(
                        GENERATOR, "_outer_windows_environment",
                        return_value={"SYSTEMROOT": r"C:\Windows"}):
                    with self.assertRaises(
                            GENERATOR.GenerationError) as raised:
                        GENERATOR._run_production_cli(
                            CORE, self.root, self.source_roles, semantic,
                            interpreter, orchestrator, wsl_path,
                            _command_runner=dependency_drift_without_restore,
                        )
                self.assertEqual(dependency_after_code, str(raised.exception))
                self.assertEqual([True], persistent_calls)
            finally:
                dependency_path.write_bytes(dependency_original)

            transient_calls = []
            def dependency_drift_then_restore(
                    *unused_args, **unused_kwargs):
                transient_calls.append(True)
                dependency_path.write_bytes(
                    dependency_original + b"# dependency transient drift\n")
                dependency_path.write_bytes(dependency_original)
                metadata = dependency_path.stat()
                os.utime(
                    dependency_path,
                    ns=(metadata.st_atime_ns, metadata.st_mtime_ns + 1_000_000),
                )
                return semantic_success_completed

            with mock.patch.object(
                    GENERATOR, "_outer_windows_environment",
                    return_value={"SYSTEMROOT": r"C:\Windows"}):
                with self.assertRaises(GENERATOR.GenerationError) as raised:
                    GENERATOR._run_production_cli(
                        CORE, self.root, self.source_roles, semantic,
                        interpreter, orchestrator, wsl_path,
                        _command_runner=dependency_drift_then_restore,
                    )
            self.assertEqual(dependency_runtime_code, str(raised.exception))
            self.assertEqual([True], transient_calls)

        semantic_completed = subprocess.CompletedProcess(
            [], semantic["exit_code"],
            CORE._canonical_json(semantic_payload) + b"\n",
            b"unexpected stderr\n",
        )
        with mock.patch.object(
                GENERATOR, "_outer_windows_environment",
                return_value={"SYSTEMROOT": r"C:\Windows"}):
            with self.assertRaisesRegex(
                    GENERATOR.GenerationError,
                    "production_cli_stderr_mismatch:"
                    "semantic_producer_authority_unbound"):
                GENERATOR._run_production_cli(
                    CORE, self.root, self.source_roles, semantic,
                    interpreter, orchestrator, wsl_path,
                    _command_runner=lambda *unused_args, **unused_kwargs:
                    semantic_completed,
                )

    def test_nonformal_diagnostic_source_is_forbidden(self):
        definitions = self.policy.source_role_definitions + (
            ("bad", "workspace", "evidence/NON_FORMAL_UNSELECTED_diagnostic.json"),
        )
        bad_policy = CORE.AuthorityPolicy(
            **{
                **self.policy.__dict__,
                "source_role_definitions": definitions,
            }
        )
        result = CORE.validate_formal_admission_evidence_authority_v7(
            self.root, self.payload, bad_policy,
        )
        self.assertIn(
            "formal_authority_v7_policy_nonformal_diagnostic_forbidden",
            result["failures"],
        )

    def test_logical_denominator_is_recomputed_from_ast(self):
        self.assertEqual(len(self.logical), 3)
        self.assertEqual(
            {item["suite_id"] for item in self.logical},
            {
                "machine_contract_doc_demotion",
                "camera_only_atomic_launcher",
                "field_readiness_exact_cli",
            },
        )
        self.assertTrue(all(item["collected"] == 1 for item in self.logical))
        self._replace_report(
            lambda value: value["test_matrix"].update(
                logical_expected_total=187,
            )
        )
        result = self._validate()
        self.assertIn(
            "formal_authority_v7_report_test_count_mismatch:logical_expected_total",
            result["failures"],
        )

    def test_physical_denominator_and_zero_denominator_forgery_are_rejected(self):
        self._replace_report(
            lambda value: value["test_matrix"].update(
                physical_expected_total=0,
                physical_collected=0,
                physical_effective_passed=0,
            )
        )
        result = self._validate()
        self.assertFalse(result["semantic_validated_pass"])
        self.assertTrue(any("physical_" in item for item in result["failures"]))

        for mode in ("missing", "wrong", "duplicate"):
            def tamper_distro(report, mode=mode):
                record = next(
                    item for item in report["test_matrix"][
                        "physical_execution_records"]
                    if item["record_id"] == "atomic_wsl_python314"
                )
                index = record["argv"].index("--distribution")
                if mode == "missing":
                    del record["argv"][index:index + 2]
                elif mode == "wrong":
                    record["argv"][index + 1] = "Debian"
                else:
                    record["argv"][index:index] = [
                        "--distribution", CORE.WSL_DISTRIBUTION,
                    ]
                record["argv_sha256"] = _sha(record["argv"])

            self._replace_report(tamper_distro)
            result = self._validate()
            self.assertIn(
                "formal_authority_v7_physical_argv_mismatch:"
                "atomic_wsl_python314",
                result["failures"],
            )

    def test_windows_skip_requires_same_id_posix_pass(self):
        def mutate(value):
            companion = next(
                item for item in value["test_matrix"]["physical_execution_records"]
                if item["record_id"] == "doc_demotion_link_posix_companion"
            )
            companion["passed_ids"] = []
            companion["skipped_ids"] = [self.test_id]
            companion["passed"] = 0
            companion["skipped"] = 1
            companion["marker_payload"]["passed"] = 0
            companion["marker_payload"]["skipped"] = 1
            companion["marker_payload_sha256"] = _sha(companion["marker_payload"])
        self._replace_report(mutate)
        result = self._validate()
        self.assertFalse(result["semantic_validated_pass"])
        self.assertTrue(any(
            "unapproved_physical_skip" in item or "platform_composite" in item
            for item in result["failures"]
        ))

    def test_duplicate_or_missing_marker_is_rejected(self):
        for count in (0, 2):
            def mutate(value, count=count):
                value["test_matrix"]["physical_execution_records"][0]["marker_count"] = count
            self._replace_report(mutate)
            result = self._validate()
            self.assertFalse(result["semantic_validated_pass"], count)
            self.tearDown()
            self.setUp()

    def test_production_observation_self_report_and_atomic_execution_are_rejected(self):
        for key, value in (
            ("self_reported_anchor_accepted", True),
            ("execution_attempted", True),
        ):
            def mutate(report, key=key, value=value):
                item = next(
                    record for record in report["production_cli_observations"]
                    if record["observation_id"] == "atomic_runtime_admission_unbound"
                )
                item[key] = value
            self._replace_report(mutate)
            result = self._validate()
            self.assertFalse(result["semantic_validated_pass"], key)
            self.tearDown()
            self.setUp()

        def tamper_static_record_id(report):
            item = next(
                record for record in report["production_cli_observations"]
                if record["observation_id"]
                == "field_readiness_production_cli_unbound"
            )
            item["payload"]["supporting_record_ids"] = [
                "atomic_wsl_python314",
            ]
            item["payload_sha256"] = _sha(item["payload"])

        self._replace_report(tamper_static_record_id)
        result = self._validate()
        self.assertIn(
            "formal_authority_v7_static_observation_payload_invalid:"
            "field_readiness_production_cli_unbound",
            result["failures"],
        )
        self.tearDown()
        self.setUp()

        def remove_supporting_pass(report):
            record = next(
                item for item in report["test_matrix"][
                    "physical_execution_records"
                ]
                if item["record_id"]
                == "field_readiness_exact_cli_wsl_python314"
            )
            record["passed_ids"] = []

        self._replace_report(remove_supporting_pass)
        result = self._validate()
        self.assertIn(
            "formal_authority_v7_static_observation_"
            "supporting_record_invalid:"
            "field_readiness_production_cli_unbound:"
            "field_readiness_exact_cli_wsl_python314",
            result["failures"],
        )

        dependency_path = (
            "src/limo_cleanup_perception/limo_cleanup_perception/"
            "ros1_noetic_field_readiness.py"
        )
        for case in ("missing", "extra", "duplicate"):
            self.tearDown()
            self.setUp()

            def tamper_dependencies(report, case=case):
                item = next(
                    record for record in report["production_cli_observations"]
                    if record["observation_id"]
                    == "semantic_producer_authority_unbound"
                )
                dependencies = item["runtime_dependencies"]
                if case == "missing":
                    dependencies[:] = [
                        entry for entry in dependencies
                        if entry["path"] != dependency_path
                    ]
                elif case == "extra":
                    extra = deepcopy(dependencies[0])
                    extra["path"] = "src/extra_runtime_dependency.py"
                    dependencies.append(extra)
                else:
                    duplicate = next(
                        deepcopy(entry) for entry in dependencies
                        if entry["path"] == dependency_path
                    )
                    dependencies.append(duplicate)

            self._replace_report(tamper_dependencies)
            result = self._validate()
            expected_code = {
                "missing": (
                    "formal_authority_v7_production_dependency_missing:"
                    "semantic_producer_authority_unbound:" + dependency_path
                ),
                "extra": (
                    "formal_authority_v7_production_dependency_extra:"
                    "semantic_producer_authority_unbound:"
                    "src/extra_runtime_dependency.py"
                ),
                "duplicate": (
                    "formal_authority_v7_production_dependency_duplicate:"
                    "semantic_producer_authority_unbound:" + dependency_path
                ),
            }[case]
            self.assertIn(expected_code, result["failures"])

        self.tearDown()
        self.setUp()
        def reorder_dependencies(report):
            item = next(
                record for record in report["production_cli_observations"]
                if record["observation_id"]
                == "semantic_producer_authority_unbound"
            )
            item["runtime_dependencies"].reverse()

        self._replace_report(reorder_dependencies)
        result = self._validate()
        self.assertIn(
            "formal_authority_v7_production_dependency_order_invalid:"
            "semantic_producer_authority_unbound",
            result["failures"],
        )

        self.tearDown()
        self.setUp()
        def forge_bound_dependency_material(report):
            item = next(
                record for record in report["production_cli_observations"]
                if record["observation_id"]
                == "semantic_producer_authority_unbound"
            )
            dependency = next(
                entry for entry in item["runtime_dependencies"]
                if entry["path"] == item["source_identity_before"]["path"]
            )
            forged_identity = deepcopy(dependency["identity_before"])
            forged_identity["size_bytes"] += 1
            forged_identity["sha256"] = "f" * 64
            dependency["identity_before"] = deepcopy(forged_identity)
            dependency["identity_after"] = deepcopy(forged_identity)
            forged_signature = deepcopy(dependency["signature_before"])
            forged_signature[-1]["size_bytes"] += 1
            dependency["signature_before"] = deepcopy(forged_signature)
            dependency["signature_after"] = deepcopy(forged_signature)
            item["source_identity_before"] = deepcopy(forged_identity)
            item["source_identity_after"] = deepcopy(forged_identity)

        self._replace_report(forge_bound_dependency_material)
        result = self._validate()
        self.assertIn(
            "formal_authority_v7_production_dependency_identity_mismatch:"
            "semantic_producer_authority_unbound:"
            "src/limo_cleanup_perception/limo_cleanup_perception/"
            "ros1_semantic_evidence_producer.py:before",
            result["failures"],
        )
        self.assertIn(
            "formal_authority_v7_production_dependency_signature_mismatch:"
            "semantic_producer_authority_unbound:"
            "src/limo_cleanup_perception/limo_cleanup_perception/"
            "ros1_semantic_evidence_producer.py:before",
            result["failures"],
        )

        self.tearDown()
        self.setUp()
        def add_static_dependencies(report):
            semantic = next(
                record for record in report["production_cli_observations"]
                if record["observation_id"]
                == "semantic_producer_authority_unbound"
            )
            static = next(
                record for record in report["production_cli_observations"]
                if record["observation_id"]
                == "atomic_runtime_admission_unbound"
            )
            static["runtime_dependencies"] = [
                deepcopy(semantic["runtime_dependencies"][0])]

        self._replace_report(add_static_dependencies)
        result = self._validate()
        self.assertIn(
            "formal_authority_v7_static_observation_runtime_"
            "dependencies_forbidden:atomic_runtime_admission_unbound",
            result["failures"],
        )

        self.tearDown()
        self.setUp()
        def split_top_level_source(report):
            item = next(
                record for record in report["production_cli_observations"]
                if record["observation_id"]
                == "semantic_producer_authority_unbound"
            )
            item["source_identity_before"] = deepcopy(
                item["runtime_dependencies"][1]["identity_before"])

        self._replace_report(split_top_level_source)
        result = self._validate()
        self.assertIn(
            "formal_authority_v7_production_source_dependency_split:"
            "semantic_producer_authority_unbound:before",
            result["failures"],
        )

    def test_wrong_production_blocked_code_is_rejected(self):
        executed = {
            item["observation_id"]: item
            for item in CORE.PRODUCTION_CLI_EXPECTATIONS
            if item["execution_attempted"]
        }
        self.assertEqual(
            {
                observation_id: len(
                    CORE.expected_unbound_production_payload(definition))
                for observation_id, definition in executed.items()
            },
            {
                "runtime_import_probe_unbound": 23,
                "runtime_install_authority_unbound": 46,
                "semantic_producer_authority_unbound": 13,
            },
        )

        def sync_payload_stream(record, definition):
            record["payload_sha256"] = _sha(record["payload"])
            prefix = definition["marker_prefix"]
            raw = CORE._canonical_json(record["payload"]) + b"\n"
            if prefix is not None:
                raw = prefix.encode("ascii") + raw
            record["stdout"] = _stream(raw)

        for observation_id, definition in executed.items():
            def add_upgrade_and_unknown(report, observation_id=observation_id,
                                        definition=definition):
                record = next(
                    item for item in report["production_cli_observations"]
                    if item["observation_id"] == observation_id)
                record["payload"].update({
                    "formal_acceptance": True,
                    "formal_consumer": True,
                    "field_evidence_admitted": True,
                    "authorizes_field_delivery": True,
                    "unknown_elevation": True,
                })
                sync_payload_stream(record, definition)

            self._replace_report(add_upgrade_and_unknown)
            result = self._validate()
            self.assertIn(
                "formal_authority_v7_production_payload_schema_invalid:"
                + observation_id,
                result["failures"],
            )
            self.assertIn(
                "formal_authority_v7_production_stdout_mismatch:"
                + observation_id,
                result["failures"],
            )

        upgrade_field = {
            "runtime_import_probe_unbound": "formal_consumer",
            "runtime_install_authority_unbound": "formal_acceptance",
            "semantic_producer_authority_unbound": "formal_acceptance",
        }
        for observation_id, field in upgrade_field.items():
            definition = executed[observation_id]

            def elevate_known_flag(report, observation_id=observation_id,
                                   definition=definition, field=field):
                record = next(
                    item for item in report["production_cli_observations"]
                    if item["observation_id"] == observation_id)
                record["payload"][field] = True
                sync_payload_stream(record, definition)

            self._replace_report(elevate_known_flag)
            result = self._validate()
            self.assertIn(
                "formal_authority_v7_production_payload_semantic_mismatch:"
                + observation_id,
                result["failures"],
            )

        def wrong_type(report):
            observation_id = "semantic_producer_authority_unbound"
            definition = executed[observation_id]
            record = next(
                item for item in report["production_cli_observations"]
                if item["observation_id"] == observation_id)
            record["payload"]["delivery_ready"] = 0
            sync_payload_stream(record, definition)

        self._replace_report(wrong_type)
        result = self._validate()
        self.assertIn(
            "formal_authority_v7_production_payload_schema_invalid:"
            "semantic_producer_authority_unbound",
            result["failures"],
        )

    def test_semantic_producer_unbound_observation_is_exact_and_nonformal(self):
        expected = next(
            item for item in CORE.PRODUCTION_CLI_EXPECTATIONS
            if item["observation_id"] == "semantic_producer_authority_unbound"
        )
        self.assertEqual(
            expected["blocked_code"],
            "semantic_producer_production_authority_not_anchored",
        )
        self.assertIn(
            "FORMAL_SEMANTIC_EVIDENCE_PRODUCER_PRODUCTION_AUTHORITY_NOT_BOUND",
            CORE.GATE_STATE["active_blockers"],
        )
        self.assertFalse(
            CORE.GATE_STATE[
                "semantic_evidence_producer_production_authority_bound"
            ]
        )
        self.assertFalse(
            CORE.GATE_STATE[
                "semantic_evidence_producer_formal_evidence_admitted"
            ]
        )
        semantic_record = next(
            item for item in self.observations
            if item["observation_id"]
            == "semantic_producer_authority_unbound"
        )
        wsl_root = CORE._execution_workspace_path(self.root)
        source_root = wsl_root.rstrip("/") + "/" + (
            CORE.PRODUCTION_PACKAGE_SOURCE_ROOT
        )
        target = wsl_root.rstrip("/") + "/" + expected["source_path"]
        bootstrap_index = semantic_record["argv"].index(
            CORE.PRODUCTION_PACKAGE_BOOTSTRAP
        )
        distribution_index = semantic_record["argv"].index("--distribution")
        self.assertEqual(
            CORE.WSL_DISTRIBUTION,
            semantic_record["argv"][distribution_index + 1],
        )
        self.assertEqual("-c", semantic_record["argv"][bootstrap_index - 1])
        self.assertEqual(source_root, semantic_record["argv"][bootstrap_index + 1])
        self.assertEqual(target, semantic_record["argv"][bootstrap_index + 2])
        expected_manifest = CORE.production_runtime_dependency_manifest(
            self.source_roles, expected)
        manifest_json = semantic_record["argv"][bootstrap_index + 3]
        self.assertEqual(
            expected_manifest, json.loads(manifest_json),
        )
        self.assertEqual(
            _sha(expected_manifest),
            semantic_record["argv"][bootstrap_index + 4],
        )
        expected_interpreter_manifest = {
            key: CORE.PYTHON314_TARGET_IDENTITY[key]
            for key in ("path", "size_bytes", "sha256")
        }
        interpreter_manifest_json = semantic_record["argv"][
            bootstrap_index + 5]
        self.assertEqual(
            expected_interpreter_manifest,
            json.loads(interpreter_manifest_json),
        )
        self.assertEqual(
            _sha(expected_interpreter_manifest),
            semantic_record["argv"][bootstrap_index + 6],
        )
        self.assertEqual(
            list(CORE.SEMANTIC_PRODUCTION_RUNTIME_DEPENDENCY_PATHS),
            [item["path"] for item in semantic_record["runtime_dependencies"]],
        )
        for item in semantic_record["runtime_dependencies"]:
            expected_identity = self._source(item["path"])
            expected_signature = CORE.source_runtime_signature(
                self.root, "workspace", item["path"])
            self.assertEqual(expected_identity, item["identity_before"])
            self.assertEqual(expected_identity, item["identity_after"])
            self.assertEqual(expected_signature, item["signature_before"])
            self.assertEqual(expected_signature, item["signature_after"])
        self.assertEqual(1, semantic_record["argv"].count(source_root))
        self.assertEqual(
            semantic_record["argv_sha256"], _sha(semantic_record["argv"]),
        )
        self.assertEqual(dict(CORE.EMPTY_STREAM_IDENTITY), semantic_record["stderr"])
        self.assertEqual(
            _stream(CORE.expected_production_observation_stdout(
                expected, semantic_record["payload"])),
            semantic_record["stdout"],
        )
        self.assertTrue(semantic_record["execution_attempted"])
        self.assertTrue(semantic_record["not_in_logical_denominator"])
        self.assertTrue(semantic_record["not_in_physical_denominator"])
        self.assertFalse(semantic_record["formal_consumer"])
        self.assertFalse(semantic_record["delivery_ready"])

        field_expected = next(
            item for item in CORE.PRODUCTION_CLI_EXPECTATIONS
            if item["observation_id"]
            == "field_readiness_production_cli_unbound"
        )
        self.assertFalse(field_expected["execution_attempted"])
        self.assertEqual(
            field_expected["blocked_code"],
            "semantic_producer_production_authority_not_anchored",
        )
        self.assertEqual(
            field_expected["supporting_test_id"],
            CORE.FIELD_READINESS_SUPPORTING_TEST_ID,
        )
        self.assertEqual(
            field_expected["supporting_record_ids"],
            ("field_readiness_exact_cli_wsl_python314",),
        )
        field_record = next(
            item for item in self.observations
            if item["observation_id"]
            == "field_readiness_production_cli_unbound"
        )
        self.assertEqual(["NOT_EXECUTED_SAFETY_BOUNDARY"], field_record["argv"])
        self.assertTrue(field_record["not_in_logical_denominator"])
        self.assertTrue(field_record["not_in_physical_denominator"])
        self.assertFalse(field_record["formal_consumer"])
        self.assertFalse(field_record["delivery_ready"])

        if os.name != "nt":
            actual_source_roles = [
                CORE.source_artifact_identity(ROOT, "workspace", relative)
                for relative in CORE.production_runtime_dependency_paths(
                    expected)
            ]
            actual_argv = CORE._expected_production_cli_argv(
                ROOT, expected, "wsl.exe", actual_source_roles,
                self._interpreter_identity("system_python314_target"),
            )
            child = actual_argv[actual_argv.index("--exec") + 1:]

            def run_child(argv):
                return subprocess.run(
                    argv, cwd=str(ROOT), env={}, stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    check=False, timeout=30.0,
                )

            completed = run_child(child)
            self.assertEqual(1, completed.returncode)
            self.assertEqual(b"", completed.stderr)
            child_payload = json.loads(completed.stdout.decode("utf-8"))
            self.assertEqual(
                CORE.expected_unbound_production_payload(expected),
                child_payload,
            )
            self.assertEqual(
                ["semantic_producer_production_authority_not_anchored"],
                child_payload["failures"],
            )
            self.assertFalse(child_payload["producer_material_validated"])
            self.assertFalse(child_payload["formal_acceptance"])
            self.assertTrue(child_payload["not_in_four_scene_denominator"])
            self.assertFalse(child_payload["delivery_ready"])

            python_index = child.index("/usr/bin/python3.14")
            actual_target = child[child.index(
                CORE.PRODUCTION_PACKAGE_BOOTSTRAP) + 2]
            bare = [
                *child[:python_index + 1], "-I", "-S", "-B",
                actual_target, *expected["argv_suffix"],
            ]
            bare_completed = run_child(bare)
            self.assertNotEqual(0, bare_completed.returncode)
            self.assertIn(b"ModuleNotFoundError", bare_completed.stderr)

            child_bootstrap_index = child.index(
                CORE.PRODUCTION_PACKAGE_BOOTSTRAP
            )
            root_index = child_bootstrap_index + 1
            target_index = child_bootstrap_index + 2
            wrong_root = list(child)
            wrong_root[root_index] = (
                "/tmp/forbidden/src/limo_cleanup_perception"
            )
            self.assertEqual(94, run_child(wrong_root).returncode)
            wrong_target = list(child)
            wrong_target[target_index] = (
                child[root_index]
                + "/limo_cleanup_perception/ros1_noetic_field_readiness.py"
            )
            self.assertEqual(94, run_child(wrong_target).returncode)

            ambient = list(child)
            ambient[child_bootstrap_index] = (
                "import sys;sys.path.append({!r});exec({!r})".format(
                    str(ROOT), CORE.PRODUCTION_PACKAGE_BOOTSTRAP,
                )
            )
            self.assertEqual(95, run_child(ambient).returncode)
            preloaded = list(child)
            preloaded[child_bootstrap_index] = (
                "import sys,types;"
                "_m=types.ModuleType('limo_cleanup_perception."
                "ros1_semantic_evidence_producer');"
                "_m.__file__='/tmp/fake.py';"
                "_m.__spec__=types.SimpleNamespace(origin='/tmp/fake.py');"
                "sys.modules[_m.__name__]=_m;exec({!r})".format(
                    CORE.PRODUCTION_PACKAGE_BOOTSTRAP,
                )
            )
            self.assertEqual(97, run_child(preloaded).returncode)

            manifest_index = child_bootstrap_index + 3
            manifest_sha_index = child_bootstrap_index + 4
            wrong_manifest_digest = list(child)
            wrong_manifest_digest[manifest_sha_index] = "0" * 64
            self.assertEqual(102, run_child(wrong_manifest_digest).returncode)

            wrong_manifest_bytes = list(child)
            manifest = json.loads(wrong_manifest_bytes[manifest_index])
            manifest[0]["size_bytes"] += 1
            wrong_manifest_bytes[manifest_index] = (
                CORE._canonical_json(manifest).decode("utf-8"))
            wrong_manifest_bytes[manifest_sha_index] = _sha(manifest)
            self.assertEqual(104, run_child(wrong_manifest_bytes).returncode)

            interpreter_manifest_index = child_bootstrap_index + 5
            interpreter_manifest_sha_index = child_bootstrap_index + 6
            wrong_interpreter_digest = list(child)
            wrong_interpreter_digest[interpreter_manifest_sha_index] = "0" * 64
            self.assertEqual(
                106, run_child(wrong_interpreter_digest).returncode)
            wrong_interpreter_path = list(child)
            interpreter_manifest = json.loads(
                wrong_interpreter_path[interpreter_manifest_index])
            interpreter_manifest["path"] = "/usr/bin/python3"
            wrong_interpreter_path[interpreter_manifest_index] = (
                CORE._canonical_json(interpreter_manifest).decode("utf-8"))
            wrong_interpreter_path[interpreter_manifest_sha_index] = _sha(
                interpreter_manifest)
            self.assertEqual(106, run_child(wrong_interpreter_path).returncode)
            wrong_interpreter_hash = list(child)
            interpreter_manifest = json.loads(
                wrong_interpreter_hash[interpreter_manifest_index])
            interpreter_manifest["sha256"] = "0" * 64
            wrong_interpreter_hash[interpreter_manifest_index] = (
                CORE._canonical_json(interpreter_manifest).decode("utf-8"))
            wrong_interpreter_hash[interpreter_manifest_sha_index] = _sha(
                interpreter_manifest)
            self.assertEqual(107, run_child(wrong_interpreter_hash).returncode)

            importlib_hook = list(child)
            importlib_hook[child_bootstrap_index] = (
                "import importlib;"
                "importlib.import_module=lambda *args,**kwargs:"
                "(_ for _ in ()).throw(SystemExit(88));"
                "exec({!r})".format(CORE.PRODUCTION_PACKAGE_BOOTSTRAP)
            )
            importlib_hook_completed = run_child(importlib_hook)
            self.assertEqual(1, importlib_hook_completed.returncode)
            self.assertEqual(b"", importlib_hook_completed.stderr)
            self.assertEqual(
                ["semantic_producer_production_authority_not_anchored"],
                json.loads(importlib_hook_completed.stdout.decode("utf-8"))[
                    "failures"],
            )

            wrong_package_origin = list(child)
            wrong_package_origin[child_bootstrap_index] = (
                CORE.PRODUCTION_PACKAGE_BOOTSTRAP.replace(
                    "_attest(_package,_package_init_path)\n",
                    "_package.__file__='/tmp/fake.py'\n"
                    "_attest(_package,_package_init_path)\n",
                )
            )
            self.assertEqual(99, run_child(wrong_package_origin).returncode)

            wrong_package_path = list(child)
            wrong_package_path[child_bootstrap_index] = (
                CORE.PRODUCTION_PACKAGE_BOOTSTRAP.replace(
                    "if list(getattr(_package,'__path__',())) != "
                    "[_package_directory]: raise SystemExit(101)\n",
                    "_package.__path__=['/tmp/fake-package']\n"
                    "if list(getattr(_package,'__path__',())) != "
                    "[_package_directory]: raise SystemExit(101)\n",
                )
            )
            self.assertEqual(101, run_child(wrong_package_path).returncode)

            for direct_id in (
                    "runtime_import_probe_unbound",
                    "runtime_install_authority_unbound"):
                direct_definition = next(
                    item for item in CORE.PRODUCTION_CLI_EXPECTATIONS
                    if item["observation_id"] == direct_id
                )
                direct_roles = [CORE.source_artifact_identity(
                    ROOT, "workspace", direct_definition["source_path"])]
                direct_argv = CORE._expected_production_cli_argv(
                    ROOT, direct_definition, "wsl.exe", direct_roles,
                    self._interpreter_identity("system_python314_target"),
                )
                direct_child = direct_argv[
                    direct_argv.index("--exec") + 1:]
                direct_bootstrap_index = direct_child.index(
                    CORE.PRODUCTION_SCRIPT_BOOTSTRAP)
                self.assertEqual(
                    "-c", direct_child[direct_bootstrap_index - 1])
                self.assertEqual(
                    direct_definition["source_path"],
                    json.loads(direct_child[direct_bootstrap_index + 3])[
                        0]["path"],
                )
                direct_completed = run_child(direct_child)
                self.assertEqual(
                    direct_definition["exit_code"],
                    direct_completed.returncode,
                )
                marker = direct_definition["marker_prefix"].encode("ascii")
                marker_lines = [
                    line for line in direct_completed.stdout.splitlines()
                    if line.startswith(marker)
                ]
                self.assertEqual(
                    1, len(marker_lines),
                    (direct_id, direct_completed.stdout,
                     direct_completed.stderr, direct_completed.returncode),
                )
                direct_payload = json.loads(
                    marker_lines[0][len(marker):].decode("utf-8"))
                self.assertEqual(
                    CORE.expected_unbound_production_payload(
                        direct_definition),
                    direct_payload,
                )
                self.assertEqual(
                    [direct_definition["blocked_code"]],
                    direct_payload["failures"],
                )
                direct_wrong_digest = list(direct_child)
                direct_wrong_digest[direct_bootstrap_index + 4] = "0" * 64
                self.assertEqual(
                    102, run_child(direct_wrong_digest).returncode)
                direct_wrong_bytes = list(direct_child)
                direct_manifest = json.loads(
                    direct_wrong_bytes[direct_bootstrap_index + 3])
                direct_manifest[0]["size_bytes"] += 1
                direct_wrong_bytes[direct_bootstrap_index + 3] = (
                    CORE._canonical_json(direct_manifest).decode("utf-8"))
                direct_wrong_bytes[direct_bootstrap_index + 4] = _sha(
                    direct_manifest)
                self.assertEqual(
                    104, run_child(direct_wrong_bytes).returncode)
                direct_wrong_interpreter_digest = list(direct_child)
                direct_wrong_interpreter_digest[
                    direct_bootstrap_index + 6] = "0" * 64
                self.assertEqual(
                    106,
                    run_child(direct_wrong_interpreter_digest).returncode,
                )
                direct_wrong_interpreter_hash = list(direct_child)
                direct_interpreter_manifest = json.loads(
                    direct_wrong_interpreter_hash[
                        direct_bootstrap_index + 5])
                direct_interpreter_manifest["sha256"] = "0" * 64
                direct_wrong_interpreter_hash[
                    direct_bootstrap_index + 5] = CORE._canonical_json(
                        direct_interpreter_manifest).decode("utf-8")
                direct_wrong_interpreter_hash[
                    direct_bootstrap_index + 6] = _sha(
                        direct_interpreter_manifest)
                self.assertEqual(
                    107, run_child(direct_wrong_interpreter_hash).returncode)

        def tamper_marker(report):
            record = next(
                item for item in report["production_cli_observations"]
                if item["observation_id"]
                == "semantic_producer_authority_unbound"
            )
            record["payload"]["marker"] = "WRONG"
            record["payload_sha256"] = _sha(record["payload"])

        self._replace_report(tamper_marker)
        result = self._validate()
        self.assertIn(
            "formal_authority_v7_production_payload_semantic_mismatch:"
            "semantic_producer_authority_unbound",
            result["failures"],
        )

        def tamper_argv(report):
            record = next(
                item for item in report["production_cli_observations"]
                if item["observation_id"]
                == "semantic_producer_authority_unbound"
            )
            record["argv"] = record["argv"][:-2]
            record["argv_sha256"] = _sha(record["argv"])

        self._replace_report(tamper_argv)
        result = self._validate()
        self.assertIn(
            "formal_authority_v7_production_argv_mismatch:"
            "semantic_producer_authority_unbound",
            result["failures"],
        )

        for mode in ("missing", "wrong", "duplicate"):
            def tamper_production_distro(report, mode=mode):
                record = next(
                    item for item in report["production_cli_observations"]
                    if item["observation_id"]
                    == "semantic_producer_authority_unbound"
                )
                index = record["argv"].index("--distribution")
                if mode == "missing":
                    del record["argv"][index:index + 2]
                elif mode == "wrong":
                    record["argv"][index + 1] = "Debian"
                else:
                    record["argv"][index:index] = [
                        "--distribution", CORE.WSL_DISTRIBUTION,
                    ]
                record["argv_sha256"] = _sha(record["argv"])

            self._replace_report(tamper_production_distro)
            result = self._validate()
            self.assertIn(
                "formal_authority_v7_production_argv_mismatch:"
                "semantic_producer_authority_unbound",
                result["failures"],
            )

        def tamper_bootstrap(report):
            record = next(
                item for item in report["production_cli_observations"]
                if item["observation_id"]
                == "semantic_producer_authority_unbound"
            )
            index = record["argv"].index(CORE.PRODUCTION_PACKAGE_BOOTSTRAP)
            record["argv"][index] += "# drift"
            record["argv_sha256"] = _sha(record["argv"])

        self._replace_report(tamper_bootstrap)
        result = self._validate()
        self.assertIn(
            "formal_authority_v7_production_argv_mismatch:"
            "semantic_producer_authority_unbound",
            result["failures"],
        )

        for offset, replacement in (
            (1, "/tmp/substitute/src/limo_cleanup_perception"),
            (2, "/tmp/substitute/producer.py"),
        ):
            def tamper_bound_path(report, offset=offset, replacement=replacement):
                record = next(
                    item for item in report["production_cli_observations"]
                    if item["observation_id"]
                    == "semantic_producer_authority_unbound"
                )
                index = record["argv"].index(
                    CORE.PRODUCTION_PACKAGE_BOOTSTRAP
                )
                record["argv"][index + offset] = replacement
                record["argv_sha256"] = _sha(record["argv"])

            self._replace_report(tamper_bound_path)
            result = self._validate()
            self.assertIn(
                "formal_authority_v7_production_argv_mismatch:"
                "semantic_producer_authority_unbound",
                result["failures"],
            )

        def tamper_stderr(report):
            record = next(
                item for item in report["production_cli_observations"]
                if item["observation_id"]
                == "semantic_producer_authority_unbound"
            )
            record["stderr"] = _stream(b"unexpected stderr\n")

        self._replace_report(tamper_stderr)
        result = self._validate()
        self.assertIn(
            "formal_authority_v7_production_stderr_mismatch:"
            "semantic_producer_authority_unbound",
            result["failures"],
        )

        def tamper_stdout(report):
            record = next(
                item for item in report["production_cli_observations"]
                if item["observation_id"]
                == "semantic_producer_authority_unbound"
            )
            record["stdout"] = _stream(b"forged canonical-looking stream\n")

        self._replace_report(tamper_stdout)
        result = self._validate()
        self.assertIn(
            "formal_authority_v7_production_stdout_mismatch:"
            "semantic_producer_authority_unbound",
            result["failures"],
        )

        def synchronously_forge_interpreter(report):
            forged = self._interpreter_identity("system_python314_target")
            forged["entry_lstat_size_bytes"] += 1
            forged["resolved_target"]["size_bytes"] += 1
            forged["resolved_target"]["sha256"] = "f" * 64
            for record in report["test_matrix"]["physical_execution_records"]:
                identity = record["interpreter_identity"]
                if record["interpreter_role"] in (
                        "system_python3_entry", "system_python314_target"):
                    replacement = deepcopy(forged)
                    if record["interpreter_role"] == "system_python3_entry":
                        replacement["entry_path"] = "/usr/bin/python3"
                        replacement["entry_is_symlink"] = True
                        replacement["entry_lstat_size_bytes"] = 32
                        replacement["entry_link_chain"] = [{
                            "path": "/usr/bin/python3", "target": "python3.14",
                        }]
                    record["interpreter_identity"] = replacement
                    record["marker_payload"]["executable"] = deepcopy(
                        replacement)
                    record["marker_payload_sha256"] = _sha(
                        record["marker_payload"])
            for record in report["production_cli_observations"]:
                if record["execution_attempted"] is not True:
                    continue
                record["interpreter_identity"] = deepcopy(forged)
                bootstrap = (
                    CORE.PRODUCTION_PACKAGE_BOOTSTRAP
                    if CORE.PRODUCTION_PACKAGE_BOOTSTRAP in record["argv"]
                    else CORE.PRODUCTION_SCRIPT_BOOTSTRAP
                )
                index = record["argv"].index(bootstrap)
                manifest = {
                    key: forged["resolved_target"][key]
                    for key in ("path", "size_bytes", "sha256")
                }
                record["argv"][index + 5] = CORE._canonical_json(
                    manifest).decode("utf-8")
                record["argv"][index + 6] = _sha(manifest)
                record["argv_sha256"] = _sha(record["argv"])

        self._replace_report(synchronously_forge_interpreter)
        result = self._validate()
        self.assertTrue(any(
            failure.endswith("_target_anchor_mismatch")
            for failure in result["failures"]
        ), result["failures"])

    def test_runtime_field_delivery_and_regression_promotions_are_rejected(self):
        for container, key in (
            ("top", "accepted_by_formal_field_evidence_consumer"),
            ("top", "authorizes_field_delivery"),
            ("gate", "ros1_noetic_runtime_verified"),
            ("gate", "ros1_noetic_build_install_verified"),
            ("gate", "ros1_noetic_field_install_pass"),
            ("gate", "formal_acceptance"),
            ("gate", "formal_tf_pass"),
            ("gate", "formal_3d_pass"),
            ("gate", "formal_latency_pass"),
            ("gate", "delivery_ready"),
            ("gate", "regression_passed"),
        ):
            payload = deepcopy(self.payload)
            target = payload if container == "top" else payload["gate_state"]
            target[key] = True
            result = self._validate(payload)
            self.assertFalse(result["semantic_validated_pass"], key)

        payload = deepcopy(self.payload)
        payload["gate_state"]["formal_denominator"] = 1
        result = self._validate(payload)
        self.assertFalse(result["semantic_validated_pass"])

    def test_canonical_report_and_index_share_exact_blocked_gate_state(self):
        canonical = CORE.build_canonical_payload(
            self.root, self.source_roles, self.policy,
        )
        self.assertEqual(canonical["gate_state"], dict(CORE.GATE_STATE))
        self.assertEqual(self.report["gate_state"], dict(CORE.GATE_STATE))
        self.assertEqual(self.payload["gate_state"], dict(CORE.GATE_STATE))
        for gate in (canonical["gate_state"], self.report["gate_state"], self.payload["gate_state"]):
            self.assertFalse(gate["formal_acceptance"])
            self.assertEqual(gate["formal_denominator"], 0)
            self.assertFalse(gate["ros1_noetic_runtime_verified"])
            self.assertFalse(gate["ros1_noetic_build_install_verified"])
            self.assertFalse(gate["formal_tf_pass"])
            self.assertFalse(gate["formal_3d_pass"])
            self.assertFalse(gate["formal_latency_pass"])
            self.assertFalse(gate["delivery_ready"])

    def test_filename_or_mtime_selection_is_rejected(self):
        payload = deepcopy(self.payload)
        payload["uses_filename_or_mtime_authority"] = True
        payload["filename_mtime_selection_forbidden"] = False
        result = self._validate(payload)
        self.assertFalse(result["semantic_validated_pass"])

    def test_generation_inventory_rejects_id_collision_not_filename_or_mtime(self):
        evidence = self.root / "evidence"
        evidence.mkdir()
        collision = evidence / "unrelated-name.json"
        collision.write_bytes(_json_bytes({
            "generation_id": CORE.GENERATION_ID,
        }))
        inventory, collisions = GENERATOR._evidence_identity_inventory(
            CORE, self.root,
        )
        self.assertEqual(len(inventory), 1)
        self.assertEqual(collisions, [{
            "path": "evidence/unrelated-name.json",
            "field": "generation_id",
            "value": CORE.GENERATION_ID,
        }])

        collision.unlink()
        noncollision = evidence / (CORE.GENERATION_ID + ".json")
        noncollision.write_bytes(_json_bytes({
            "generation_id": "historical-unrelated-generation",
        }))
        inventory, collisions = GENERATOR._evidence_identity_inventory(
            CORE, self.root,
        )
        self.assertEqual(len(inventory), 1)
        self.assertEqual(collisions, [])

        noncollision.unlink()
        nested = evidence / "nested-collision.json"
        nested.write_bytes(_json_bytes({
            "entries": [{"evidence_id": CORE.CURRENT_EVIDENCE_ID}],
        }))
        inventory, collisions = GENERATOR._evidence_identity_inventory(
            CORE, self.root,
        )
        self.assertEqual(len(inventory), 1)
        self.assertEqual(collisions, [{
            "path": "evidence/nested-collision.json",
            "field": "entries[0].evidence_id",
            "value": CORE.CURRENT_EVIDENCE_ID,
        }])

        nested.unlink()
        abandoned = evidence / "abandoned" / "partial.json"
        abandoned.parent.mkdir()
        abandoned.write_bytes(b"")
        abandoned_relative = abandoned.relative_to(self.root).as_posix()
        abandoned_identity = {
            "path": abandoned_relative,
            "size_bytes": 0,
            "sha256": hashlib.sha256(b"").hexdigest(),
        }
        registry_entry = {
            "schema_version": "registered_nonselectable_generation/v1",
            "registry_status": "REGISTERED_NONSELECTABLE_GENERATION",
            "generation_status": "ABANDONED_UNINDEXED",
            "generation_id": "historical-abandoned-generation",
            "index_instance_id": "historical-abandoned-index-instance",
            "artifacts": [{
                "role": "canonical",
                **abandoned_identity,
            }],
        }
        with mock.patch.object(
            GENERATOR, "REGISTERED_NONSELECTABLE_GENERATIONS",
            (registry_entry,),
        ):
            inventory, collisions = GENERATOR._evidence_identity_inventory(
                CORE, self.root,
            )
        registered = next(
            item for item in inventory if item["path"] == abandoned_relative
        )
        self.assertEqual(collisions, [])
        self.assertFalse(registered["strict_json_readable"])
        self.assertEqual(
            registered["registry_generation_status"],
            "ABANDONED_UNINDEXED",
        )
        self.assertEqual(registered["registry_artifact_role"], "canonical")

        parseable = evidence / "abandoned" / "report.json"
        parseable.write_bytes(_json_bytes({
            "generation_id": "historical-abandoned-generation",
        }))
        parseable_relative = parseable.relative_to(self.root).as_posix()
        parseable_raw = parseable.read_bytes()
        registry_entry["artifacts"].append({
            "role": "report",
            "path": parseable_relative,
            "size_bytes": len(parseable_raw),
            "sha256": hashlib.sha256(parseable_raw).hexdigest(),
        })
        with mock.patch.object(
            GENERATOR, "REGISTERED_NONSELECTABLE_GENERATIONS",
            (deepcopy(registry_entry),),
        ):
            inventory, collisions = GENERATOR._evidence_identity_inventory(
                CORE, self.root,
            )
        registered_parseable = next(
            item for item in inventory if item["path"] == parseable_relative
        )
        self.assertEqual(collisions, [])
        self.assertTrue(registered_parseable["strict_json_readable"])
        self.assertEqual(
            registered_parseable["registry_index_instance_id"],
            "historical-abandoned-index-instance",
        )

        invalid_registries = []
        wrong_identity = deepcopy(registry_entry)
        wrong_identity["artifacts"][0]["sha256"] = "f" * 64
        invalid_registries.append(wrong_identity)
        wrong_status = deepcopy(registry_entry)
        wrong_status["generation_status"] = "COMMITTED_UNSELECTED"
        invalid_registries.append(wrong_status)
        current_generation = deepcopy(registry_entry)
        current_generation["generation_id"] = CORE.GENERATION_ID
        invalid_registries.append(current_generation)
        predecessor_generation = deepcopy(registry_entry)
        predecessor_generation["generation_id"] = (
            CORE.PREDECESSOR_INDEX_IDENTITY["generation_id"]
        )
        invalid_registries.append(predecessor_generation)
        current_index = deepcopy(registry_entry)
        current_index["index_instance_id"] = CORE.INDEX_INSTANCE_ID
        invalid_registries.append(current_index)
        outside_evidence = deepcopy(registry_entry)
        outside_evidence["artifacts"][0]["path"] = "out/partial.json"
        invalid_registries.append(outside_evidence)
        source_role = deepcopy(registry_entry)
        source_role["artifacts"][0]["path"] = self.doc_target
        invalid_registries.append(source_role)
        duplicate_role = deepcopy(registry_entry)
        duplicate_role["artifacts"][1]["role"] = "canonical"
        invalid_registries.append(duplicate_role)
        for invalid in invalid_registries:
            with self.subTest(registry=invalid):
                with mock.patch.object(
                    GENERATOR, "REGISTERED_NONSELECTABLE_GENERATIONS",
                    (invalid,),
                ):
                    with self.assertRaises(GENERATOR.GenerationError):
                        GENERATOR._evidence_identity_inventory(CORE, self.root)
        self.assertEqual(GENERATOR.REGISTERED_NONSELECTABLE_GENERATIONS, ())

    def test_strict_json_rejects_duplicate_nan_and_trailing_content(self):
        for raw in (
            b'{"schema_version":1,"schema_version":2}',
            b'{"value":NaN}',
            b'{} trailing',
        ):
            with self.assertRaises((ValueError, json.JSONDecodeError)):
                CORE._strict_json_bytes(raw)
        _assert_generator_execution_component_contract(self)

    def test_exclusive_writer_refuses_overwrite(self):
        path = self.root / "out" / "exclusive.json"
        CORE.write_json_exclusive(path, {"value": 1}, "out/exclusive.json")
        with self.assertRaises(FileExistsError):
            CORE.write_json_exclusive(path, {"value": 2}, "out/exclusive.json")

        def invoke(
            case_name, *, writer_fault=None, exact_anchor=False,
            resolver_raises=False, post_index_keyerror=False,
            drift_output=None, state_after_commit=None,
            workspace_root=None, registry=(), use_real_inventory=False,
        ):
            case_root = (
                Path(workspace_root)
                if workspace_root is not None
                else self.root / "commit_cases" / case_name
            )
            case_root.mkdir(parents=True, exist_ok=True)
            core_identity = _write(
                case_root, GENERATOR.CORE_RELATIVE_PATH,
                b"# exact fake authority core\n",
            )
            _write(
                case_root, GENERATOR.GENERATOR_RELATIVE_PATH,
                b"# exact fake evidence generator\n",
            )
            source_identity = _write(
                case_root, "source.py", b"SOURCE = True\n",
            )
            output_prefix = "evidence/commit_cases/" + case_name
            case_root.joinpath(*output_prefix.split("/")).mkdir(
                parents=True, exist_ok=True,
            )
            fake = SimpleNamespace(
                GENERATION_ID="fixture-generation-" + case_name,
                INDEX_INSTANCE_ID="fixture-index-" + case_name,
                CURRENT_EVIDENCE_ID="fixture-evidence-" + case_name,
                CANONICAL_ARTIFACT_ID="fixture-canonical-artifact-" + case_name,
                CANONICAL_ID="fixture-canonical-" + case_name,
                REPORT_ID="fixture-report-" + case_name,
                CANONICAL_RELATIVE_PATH=output_prefix + "/canonical.json",
                REPORT_RELATIVE_PATH=output_prefix + "/report.json",
                INDEX_RELATIVE_PATH=output_prefix + "/index.json",
                PREDECESSOR_INDEX_IDENTITY={
                    "path": "evidence/predecessor/index.json",
                    "index_instance_id": "successful-predecessor-index",
                    "generation_id": "successful-predecessor-generation",
                },
                PREDECESSOR_REPORT_IDENTITY={
                    "path": "evidence/predecessor/report.json",
                },
                PREDECESSOR_CANONICAL_IDENTITY={
                    "path": "evidence/predecessor/canonical.json",
                },
                REQUIRED_SOURCE_ROLE_DEFINITIONS=(
                    ("source", "workspace", "source.py"),
                ),
                EXECUTION_DEFINITIONS=(),
                PRODUCTION_CLI_EXPECTATIONS=(),
                ATOMIC_SUPPORTING_TEST_ID="fixture.atomic.test",
            )
            source_roles = [{"role": "source", **source_identity}]
            host_binding = {"tree_sha256": "a" * 64}
            overlay_binding = {"tree_sha256": "b" * 64}
            fake.collect_source_role_bindings = lambda unused_root: deepcopy(
                source_roles
            )
            fake.collect_host_perception_package_tree = (
                lambda unused_root: deepcopy(host_binding)
            )
            fake.collect_live_overlay_binding = (
                lambda unused_root: deepcopy(overlay_binding)
            )
            fake.source_artifact_identity = CORE.source_artifact_identity
            fake._read_regular_identity = CORE._read_regular_identity
            fake.build_canonical_payload = lambda unused_root, unused_roles: {
                "generation_id": fake.GENERATION_ID,
                "live_overlay_binding": deepcopy(overlay_binding),
                "formal_consumer": False,
                "delivery_ready": False,
            }
            fake.build_report_payload = (
                lambda unused_root, unused_canonical, unused_roles,
                unused_logical, unused_physical, unused_composites,
                unused_observations, unused_generator_contract: {
                    "evidence_id": fake.CURRENT_EVIDENCE_ID,
                    "generation_id": fake.GENERATION_ID,
                    "formal_consumer": False,
                    "delivery_ready": False,
                }
            )

            def build_index(report_identity, canonical_identity, unused_roles):
                return {
                    "index_instance_id": fake.INDEX_INSTANCE_ID,
                    "generation_id": fake.GENERATION_ID,
                    "current_evidence_id": fake.CURRENT_EVIDENCE_ID,
                    "entries": [{
                        "evidence_id": fake.CURRENT_EVIDENCE_ID,
                        "is_current": True,
                        **dict(report_identity),
                    }],
                    "child_artifacts": [{
                        "artifact_id": fake.CANONICAL_ARTIFACT_ID,
                        "canonical_id": fake.CANONICAL_ID,
                        **dict(canonical_identity),
                    }],
                }
            fake.build_index_payload = build_index

            def validate_index(unused_root, unused_index):
                if drift_output is not None:
                    relative = (
                        fake.CANONICAL_RELATIVE_PATH
                        if drift_output == "canonical"
                        else fake.REPORT_RELATIVE_PATH
                    )
                    drift_path = case_root.joinpath(*relative.split("/"))
                    drift_path.write_bytes(drift_path.read_bytes() + b" ")
                return {"semantic_validated_pass": True, "failures": []}
            fake.validate_formal_admission_evidence_authority_v7 = validate_index

            def resolve(unused_root, unused_identity):
                if resolver_raises:
                    raise RuntimeError("resolver-fault")
                return {
                    "validated_pass": True,
                    "accepted_as_offline_release_selection_authority": True,
                    "failures": [],
                }
            fake.load_and_resolve_formal_admission_evidence_authority_v7 = resolve

            writer_calls = []
            role_by_path = {
                fake.CANONICAL_RELATIVE_PATH: "canonical",
                fake.REPORT_RELATIVE_PATH: "report",
                fake.INDEX_RELATIVE_PATH: "index",
            }

            def writer(output_path, payload, reported_path=None):
                role = role_by_path[reported_path]
                writer_calls.append(role)
                if writer_fault == role + "_before":
                    raise RuntimeError(role + "-before")
                if writer_fault == role + "_create_only":
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    with output_path.open("xb"):
                        pass
                    raise RuntimeError(role + "-create-only")
                if writer_fault == role + "_partial":
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    with output_path.open("xb") as stream:
                        stream.write(b"{")
                    raise RuntimeError(role + "-partial")
                if writer_fault == role + "_post_fsync":
                    raw = (
                        json.dumps(
                            payload, ensure_ascii=False, indent=2,
                            sort_keys=True, allow_nan=False,
                        ) + "\n"
                    ).encode("utf-8")
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    with output_path.open("xb") as stream:
                        stream.write(raw)
                        stream.flush()
                        os.fsync(stream.fileno())
                    raise RuntimeError(role + "-post-fsync-pre-reopen")
                if writer_fault == role + "_reopen":
                    original_read_bytes = Path.read_bytes
                    def fail_exact_reopen(read_path):
                        if read_path == output_path:
                            raise OSError(role + "-reopen")
                        return original_read_bytes(read_path)
                    with mock.patch.object(
                        Path, "read_bytes", new=fail_exact_reopen,
                    ):
                        return CORE.write_json_exclusive(
                            output_path, payload, reported_path,
                        )
                identity = CORE.write_json_exclusive(
                    output_path, payload, reported_path,
                )
                return identity
            fake.write_json_exclusive = writer

            def wrapper_status(unused_root, identity):
                index_path = case_root.joinpath(
                    *fake.INDEX_RELATIVE_PATH.split("/")
                )
                anchor = None
                if exact_anchor and index_path.exists():
                    anchor = CORE.source_artifact_identity(
                        case_root, "workspace", fake.INDEX_RELATIVE_PATH,
                    )
                    anchor = {
                        key: anchor[key]
                        for key in ("path", "size_bytes", "sha256")
                    }
                return {
                    "configured_core_anchor": dict(identity),
                    "matches_live_core": True,
                    "configured_production_index_anchor": anchor,
                }

            logical = [{}] if post_index_keyerror else [{"collected": 1}]
            original_generation_state = GENERATOR._current_generation_output_state
            state_mutated = {"done": False}
            def generation_state(
                core_arg, root_arg, identity_arg, *, selection_anchor_unset,
            ):
                index_path = root_arg.joinpath(
                    *core_arg.INDEX_RELATIVE_PATH.split("/")
                )
                if index_path.exists():
                    if state_after_commit == "raise":
                        raise RuntimeError("post-index-state-fault")
                    if (
                        state_after_commit == "truncate"
                        and not state_mutated["done"]
                    ):
                        state_mutated["done"] = True
                        index_path.write_bytes(b"{")
                return original_generation_state(
                    core_arg, root_arg, identity_arg,
                    selection_anchor_unset=selection_anchor_unset,
                )

            generation_capability, consume_generation, capability_calls = (
                _test_generator_capability_fixture(
                    case_root, "--generate",
                )
            )
            with ExitStack() as stack:
                stack.enter_context(mock.patch.object(
                    GENERATOR, "_consume_generator_execution_capability",
                    side_effect=consume_generation,
                ))
                stack.enter_context(mock.patch.object(
                    GENERATOR, "_require_generation_context",
                ))
                stack.enter_context(mock.patch.object(
                    GENERATOR, "_load_core",
                    return_value=(fake, core_identity),
                ))
                stack.enter_context(mock.patch.object(
                    GENERATOR, "_wrapper_core_anchor_status",
                    side_effect=wrapper_status,
                ))
                stack.enter_context(mock.patch.object(
                    GENERATOR, "REGISTERED_NONSELECTABLE_GENERATIONS",
                    tuple(registry),
                ))
                if not use_real_inventory:
                    stack.enter_context(mock.patch.object(
                        GENERATOR, "_evidence_identity_inventory",
                        return_value=([], []),
                    ))
                stack.enter_context(mock.patch.object(
                    GENERATOR, "_frozen_source_mismatches",
                    return_value=[],
                ))
                stack.enter_context(mock.patch.object(
                    GENERATOR, "_run_execution_matrix",
                    return_value=(
                        logical,
                        [{"collected": 1, "passed": 1, "skipped": 0}],
                        [], {}, {},
                    ),
                ))
                stack.enter_context(mock.patch.object(
                    GENERATOR, "_production_observations",
                    return_value=[],
                ))
                if state_after_commit is not None:
                    stack.enter_context(mock.patch.object(
                        GENERATOR, "_current_generation_output_state",
                        side_effect=generation_state,
                    ))
                result = GENERATOR._generate(
                    case_root, generation_capability,
                )
            self.assertEqual(1, len(capability_calls))
            return result, writer_calls, fake, case_root

        fault_expectations = (
            ("canonical-before", "canonical_before", "FAILED_NO_ARTIFACTS"),
            ("canonical-create-only", "canonical_create_only", "ABANDONED_UNINDEXED"),
            ("canonical-partial", "canonical_partial", "ABANDONED_UNINDEXED"),
            ("canonical-post-fsync", "canonical_post_fsync", "ABANDONED_UNINDEXED"),
            ("canonical-reopen", "canonical_reopen", "ABANDONED_UNINDEXED"),
            ("report-before", "report_before", "ABANDONED_UNINDEXED"),
            ("report-create-only", "report_create_only", "ABANDONED_UNINDEXED"),
            ("report-partial", "report_partial", "ABANDONED_UNINDEXED"),
            ("report-post-fsync", "report_post_fsync", "ABANDONED_UNINDEXED"),
            ("report-reopen", "report_reopen", "ABANDONED_UNINDEXED"),
            ("index-before", "index_before", "ABANDONED_UNINDEXED"),
            ("index-create-only", "index_create_only", "ABANDONED_UNINDEXED"),
            ("index-partial", "index_partial", "ABANDONED_UNINDEXED"),
            ("index-post-fsync", "index_post_fsync", "COMMITTED_UNSELECTED"),
            ("index-reopen", "index_reopen", "COMMITTED_UNSELECTED"),
        )
        fault_results = {}
        for case_name, fault, expected_status in fault_expectations:
            with self.subTest(fault=fault):
                result, calls, fake, case_root = invoke(
                    case_name, writer_fault=fault,
                )
                fault_results[case_name] = (result, fake, case_root)
                self.assertEqual(result["generation_status"], expected_status)
                self.assertFalse(result["selected"])
                self.assertFalse(result["delivery_ready"])
                expected_committed = expected_status == "COMMITTED_UNSELECTED"
                expected_abandoned = expected_status == "ABANDONED_UNINDEXED"
                self.assertIs(result["index_committed"], expected_committed)
                self.assertIs(
                    result["same_generation_retry_forbidden"],
                    expected_committed or expected_abandoned,
                )
                self.assertIs(
                    result["requires_new_generation_id"], expected_abandoned,
                )
                self.assertIs(result["selection_anchor_unset"], True)
                self.assertGreaterEqual(len(calls), 1)
        self.assertIn(
            "generation_index_o_excl_commit_not_completed",
            fault_results["index-partial"][0]["failures"],
        )
        self.assertTrue(
            fault_results["index-post-fsync"][0]["index_committed"]
        )
        self.assertEqual(
            fault_results["index-post-fsync"][0]["commit_basis"],
            "EXACT_INDEX_BYTES",
        )

        for case_name, unused_fault, expected_status in fault_expectations:
            original_result, original_fake, original_root = fault_results[
                case_name
            ]
            role_paths = {
                "canonical": original_fake.CANONICAL_RELATIVE_PATH,
                "report": original_fake.REPORT_RELATIVE_PATH,
                "index": original_fake.INDEX_RELATIVE_PATH,
            }
            original_bytes = {
                relative: original_root.joinpath(
                    *relative.split("/")
                ).read_bytes()
                for relative in role_paths.values()
                if original_root.joinpath(*relative.split("/")).is_file()
            }
            if expected_status == "FAILED_NO_ARTIFACTS":
                self.assertEqual(original_bytes, {})
            else:
                retry, retry_calls, unused, unused = invoke(case_name)
                self.assertEqual(retry_calls, [])
                self.assertEqual(retry["generation_status"], expected_status)
                self.assertEqual(original_bytes, {
                    relative: original_root.joinpath(
                        *relative.split("/")
                    ).read_bytes()
                    for relative in original_bytes
                })

            registry = ()
            if expected_status == "ABANDONED_UNINDEXED":
                artifacts = []
                for role, relative in role_paths.items():
                    if relative not in original_bytes:
                        continue
                    identity = CORE.source_artifact_identity(
                        original_root, "workspace", relative,
                    )
                    artifacts.append({
                        "role": role,
                        **{
                            key: identity[key]
                            for key in ("path", "size_bytes", "sha256")
                        },
                    })
                registry = ({
                    "schema_version": (
                        "registered_nonselectable_generation/v1"
                    ),
                    "registry_status": "REGISTERED_NONSELECTABLE_GENERATION",
                    "generation_status": "ABANDONED_UNINDEXED",
                    "generation_id": original_fake.GENERATION_ID,
                    "index_instance_id": original_fake.INDEX_INSTANCE_ID,
                    "artifacts": artifacts,
                },)
            next_result, next_calls, next_fake, unused = invoke(
                "next-" + case_name,
                workspace_root=original_root,
                registry=registry,
                use_real_inventory=True,
            )
            self.assertEqual(next_calls, ["canonical", "report", "index"])
            self.assertEqual(
                next_result["generation_status"], "COMMITTED_UNSELECTED"
            )
            self.assertTrue(original_root.joinpath(
                *next_fake.INDEX_RELATIVE_PATH.split("/")
            ).is_file())
            self.assertEqual(original_bytes, {
                relative: original_root.joinpath(
                    *relative.split("/")
                ).read_bytes()
                for relative in original_bytes
            })
            if expected_status == "FAILED_NO_ARTIFACTS":
                self.assertTrue(all(
                    not original_root.joinpath(*relative.split("/")).exists()
                    for relative in role_paths.values()
                ))

        committed, committed_calls, committed_fake, committed_root = invoke(
            "committed-unselected",
        )
        self.assertEqual(committed_calls, ["canonical", "report", "index"])
        self.assertEqual(committed["generation_status"], "COMMITTED_UNSELECTED")
        self.assertTrue(committed["index_committed"])
        self.assertTrue(committed["selection_anchor_unset"])
        self.assertTrue(committed["independent_resolution_pending"])
        self.assertFalse(
            committed["accepted_as_offline_release_selection_authority"]
        )
        committed_retry, committed_retry_calls, unused, unused = invoke(
            "committed-unselected",
        )
        self.assertEqual(committed_retry_calls, [])
        self.assertEqual(
            committed_retry["generation_status"], "COMMITTED_UNSELECTED"
        )

        selected, selected_calls, unused, unused = invoke(
            "selected", exact_anchor=True,
        )
        self.assertEqual(selected_calls, ["canonical", "report", "index"])
        self.assertEqual(selected["generation_status"], "SELECTED_BLOCKED_OFFLINE")
        self.assertTrue(
            selected["accepted_as_offline_release_selection_authority"]
        )
        self.assertFalse(selected["independent_resolution_pending"])
        self.assertFalse(selected["formal_consumer"])
        self.assertFalse(selected["delivery_ready"])

        resolver_result, unused, unused, unused = invoke(
            "resolver-exception", resolver_raises=True,
        )
        self.assertEqual(
            resolver_result["generation_status"], "COMMITTED_UNSELECTED"
        )
        self.assertIn(
            "generation_post_commit_candidate_resolver_exception",
            resolver_result["failures"],
        )
        post_commit_result, unused, unused, unused = invoke(
            "post-index-exception", post_index_keyerror=True,
        )
        self.assertEqual(
            post_commit_result["generation_status"], "COMMITTED_UNSELECTED"
        )
        self.assertIn(
            "generation_post_commit_candidate_validation_failed",
            post_commit_result["failures"],
        )
        for state_mode in ("truncate", "raise"):
            state_result, unused, unused, unused = invoke(
                "post-index-state-" + state_mode,
                state_after_commit=state_mode,
            )
            self.assertEqual(
                state_result["generation_status"], "COMMITTED_UNSELECTED"
            )
            self.assertTrue(state_result["index_committed"])
            self.assertTrue(state_result["selection_anchor_unset"])
            self.assertIn(
                "formal_authority_v7_production_anchor_not_configured",
                state_result["failures"],
            )
            self.assertIn(
                "generation_post_commit_candidate_validation_failed",
                state_result["failures"],
            )

        for output_role in ("canonical", "report"):
            drift_result, unused, drift_fake, drift_root = invoke(
                "pre-index-drift-" + output_role,
                drift_output=output_role,
            )
            self.assertEqual(
                drift_result["generation_status"], "ABANDONED_UNINDEXED"
            )
            self.assertIn(
                "generation_exception:GenerationError:"
                "generation_output_identity_drift_before_index_commit:"
                + output_role,
                drift_result["failures"],
            )
            self.assertFalse(drift_root.joinpath(
                *drift_fake.INDEX_RELATIVE_PATH.split("/")
            ).exists())

        committed_report = committed_root.joinpath(
            *committed_fake.REPORT_RELATIVE_PATH.split("/")
        )
        committed_report.unlink()
        missing_child, missing_calls, unused, unused = invoke(
            "committed-unselected",
        )
        self.assertEqual(missing_calls, [])
        self.assertEqual(
            missing_child["generation_status"], "COMMITTED_UNSELECTED"
        )
        self.assertIn(
            "generation_current_output_missing:report",
            missing_child["failures"],
        )

        abandoned_result, unused, abandoned_fake, abandoned_root = invoke(
            "plan-index-partial", writer_fault="index_partial",
        )
        self.assertEqual(
            abandoned_result["generation_status"], "ABANDONED_UNINDEXED"
        )

        abandoned_core_identity = CORE.source_artifact_identity(
            abandoned_root, "workspace", GENERATOR.CORE_RELATIVE_PATH,
        )
        abandoned_wrapper_status = {
            "configured_core_anchor": dict(abandoned_core_identity),
            "matches_live_core": True,
            "configured_production_index_anchor": None,
        }
        abandoned_plan_contract = _test_generator_execution_contract(
            abandoned_root, "--plan",
        )
        abandoned_direct_capability, consume_abandoned_direct, direct_calls = (
            _test_generator_capability_fixture(abandoned_root, "--plan")
        )
        abandoned_main_capability, consume_abandoned_main, main_calls = (
            _test_generator_capability_fixture(abandoned_root, "--plan")
        )

        def consume_abandoned(value, expected_mode, actual_root):
            if value is abandoned_direct_capability:
                return consume_abandoned_direct(
                    value, expected_mode, actual_root,
                )
            if value is abandoned_main_capability:
                return consume_abandoned_main(
                    value, expected_mode, actual_root,
                )
            raise AssertionError("unexpected test generator capability")

        with mock.patch.object(
            GENERATOR, "_load_core",
            return_value=(abandoned_fake, abandoned_core_identity),
        ), mock.patch.object(
            GENERATOR, "_wrapper_core_anchor_status",
            return_value=abandoned_wrapper_status,
        ), mock.patch.object(
            GENERATOR, "_evidence_identity_inventory",
            side_effect=AssertionError("inventory must be skipped"),
        ), mock.patch.object(
            GENERATOR, "_consume_generator_execution_capability",
            side_effect=consume_abandoned,
        ):
            abandoned_plan = GENERATOR._plan(
                abandoned_root, abandoned_direct_capability,
            )
            self.assertEqual(
                abandoned_plan["generation_status"], "ABANDONED_UNINDEXED"
            )
            self.assertFalse(abandoned_plan["ready_to_attempt_generation"])
            self.assertTrue(
                abandoned_plan[
                    "evidence_inventory_skipped_for_existing_generation"
                ]
            )
            output = io.StringIO()
            with mock.patch.object(
                GENERATOR, "_workspace_root", return_value=abandoned_root,
            ), mock.patch.object(
                GENERATOR, "_generator_execution_contract",
                return_value=abandoned_main_capability,
            ), mock.patch.object(sys, "stdout", output):
                self.assertEqual(GENERATOR.main(["--plan"]), 3)
            marker_payload = json.loads(
                output.getvalue().split(GENERATOR.PLAN_MARKER, 1)[1]
            )
            self.assertEqual(
                marker_payload["generation_status"], "ABANDONED_UNINDEXED"
            )
        self.assertEqual(1, len(direct_calls))
        self.assertEqual(1, len(main_calls))

        malformed_raws = {
            "duplicate": b'{"generation_id":"a","generation_id":"b"}',
            "nan": b'{"value":NaN}',
        }
        malformed_cases = {}
        for malformed_name, malformed_raw in malformed_raws.items():
            malformed_result, unused, malformed_fake, malformed_root = invoke(
                "malformed-" + malformed_name,
                writer_fault="index_partial",
            )
            malformed_index = malformed_root.joinpath(
                *malformed_fake.INDEX_RELATIVE_PATH.split("/")
            )
            malformed_index.write_bytes(malformed_raw)
            retry, calls, unused, unused = invoke(
                "malformed-" + malformed_name,
            )
            self.assertEqual(calls, [])
            self.assertEqual(retry["generation_status"], "ABANDONED_UNINDEXED")
            self.assertEqual(malformed_index.read_bytes(), malformed_raw)
            malformed_cases[malformed_name] = (
                malformed_fake, malformed_root, malformed_raw,
            )

        wrong_type_result, unused, wrong_type_fake, wrong_type_root = invoke(
            "malformed-child-type", writer_fault="index_partial",
        )
        wrong_type_report = CORE.source_artifact_identity(
            wrong_type_root, "workspace", wrong_type_fake.REPORT_RELATIVE_PATH,
        )
        wrong_type_index = wrong_type_root.joinpath(
            *wrong_type_fake.INDEX_RELATIVE_PATH.split("/")
        )
        wrong_type_index.write_bytes(_json_bytes({
            "index_instance_id": wrong_type_fake.INDEX_INSTANCE_ID,
            "generation_id": wrong_type_fake.GENERATION_ID,
            "current_evidence_id": wrong_type_fake.CURRENT_EVIDENCE_ID,
            "entries": [{
                "evidence_id": wrong_type_fake.CURRENT_EVIDENCE_ID,
                "is_current": True,
                **{
                    key: wrong_type_report[key]
                    for key in ("path", "size_bytes", "sha256")
                },
            }],
            "child_artifacts": [0],
        }))
        wrong_type_retry, wrong_type_calls, unused, unused = invoke(
            "malformed-child-type",
        )
        self.assertEqual(wrong_type_calls, [])
        self.assertEqual(
            wrong_type_retry["generation_status"], "ABANDONED_UNINDEXED"
        )

        # Exercise the registry's GenerationError path, not only an ordinary
        # JSONDecodeError, before a distinct generation is allowed to proceed.
        abandoned_fake, abandoned_root, unused_raw = malformed_cases[
            "duplicate"
        ]
        registered_artifacts = []
        for role, relative in (
            ("canonical", abandoned_fake.CANONICAL_RELATIVE_PATH),
            ("report", abandoned_fake.REPORT_RELATIVE_PATH),
            ("index", abandoned_fake.INDEX_RELATIVE_PATH),
        ):
            identity = CORE.source_artifact_identity(
                abandoned_root, "workspace", relative,
            )
            registered_artifacts.append({
                "role": role,
                **{
                    key: identity[key]
                    for key in ("path", "size_bytes", "sha256")
                },
            })
        registry = ({
            "schema_version": "registered_nonselectable_generation/v1",
            "registry_status": "REGISTERED_NONSELECTABLE_GENERATION",
            "generation_status": "ABANDONED_UNINDEXED",
            "generation_id": abandoned_fake.GENERATION_ID,
            "index_instance_id": abandoned_fake.INDEX_INSTANCE_ID,
            "artifacts": registered_artifacts,
        },)
        registered_bytes_before = {
            item["path"]: abandoned_root.joinpath(
                *item["path"].split("/")
            ).read_bytes()
            for item in registered_artifacts
        }
        next_result, next_calls, next_fake, unused = invoke(
            "next-generation",
            workspace_root=abandoned_root,
            registry=registry,
            use_real_inventory=True,
        )
        self.assertEqual(next_calls, ["canonical", "report", "index"])
        self.assertEqual(
            next_result["generation_status"], "COMMITTED_UNSELECTED"
        )
        self.assertTrue(abandoned_root.joinpath(
            *next_fake.INDEX_RELATIVE_PATH.split("/")
        ).is_file())
        self.assertEqual(registered_bytes_before, {
            item["path"]: abandoned_root.joinpath(
                *item["path"].split("/")
            ).read_bytes()
            for item in registered_artifacts
        })

        for status, expected_exit in (
            ("FAILED_NO_ARTIFACTS", 4),
            ("ABANDONED_UNINDEXED", 4),
            ("COMMITTED_UNSELECTED", 0),
            ("SELECTED_BLOCKED_OFFLINE", 0),
        ):
            status_capability = object()
            status_calls = []

            def status_generate(actual_root, actual_capability,
                                result_status=status):
                self.assertEqual(self.root, actual_root)
                self.assertIs(status_capability, actual_capability)
                status_calls.append(actual_capability)
                return {"generation_status": result_status}

            with mock.patch.object(GENERATOR, "_workspace_root", return_value=self.root), \
                    mock.patch.object(
                        GENERATOR, "_generator_execution_contract",
                        return_value=status_capability,
                    ), \
                    mock.patch.object(
                        GENERATOR, "_generate",
                        side_effect=status_generate,
                    ), mock.patch.object(sys, "stdout", io.StringIO()):
                self.assertEqual(GENERATOR.main(["--generate"]), expected_exit)
            self.assertEqual([status_capability], status_calls)
        fault_capability = object()

        def fault_generate(actual_root, actual_capability):
            self.assertEqual(self.root, actual_root)
            self.assertIs(fault_capability, actual_capability)
            raise RuntimeError("outer-fault")

        with mock.patch.object(GENERATOR, "_workspace_root", return_value=self.root), \
                mock.patch.object(
                    GENERATOR, "_generator_execution_contract",
                    return_value=fault_capability,
                ), \
                mock.patch.object(
                    GENERATOR, "_generate",
                    side_effect=fault_generate,
                ), mock.patch.object(sys, "stdout", io.StringIO()):
            self.assertEqual(GENERATOR.main(["--generate"]), 2)

    def test_workspace_parent_is_an_explicit_independent_root(self):
        parent_file = self.root.parent / (self.root.name + "_shared.md")
        try:
            parent_file.write_bytes(b"shared\n")
            identity = CORE.source_artifact_identity(
                self.root, "workspace_parent", parent_file.name,
            )
            self.assertEqual(identity["root_role"], "workspace_parent")
            with self.assertRaises(ValueError):
                CORE.source_artifact_identity(
                    self.root, "workspace", "../" + parent_file.name,
                )
        finally:
            parent_file.unlink(missing_ok=True)

    def test_production_policy_uses_root_roles_and_excludes_diagnostics(self):
        definitions = CORE.REQUIRED_SOURCE_ROLE_DEFINITIONS
        self.assertTrue(any(item[1] == "workspace_parent" for item in definitions))
        self.assertFalse(any(
            item[2].lower().startswith("evidence/")
            and "diagnostic" in item[2].lower()
            for item in definitions
        ))
        required_transitive_roles = (
            ("legacy_operational_scripts_test", "workspace", "audit_tools/test_ros1_legacy_operational_scripts.py"),
            ("runtime_behavior_nested_test", "workspace", "src/limo_cleanup_perception/test/test_ros1_runtime_behavior.py"),
            ("dabai_field_readiness_runbook", "workspace", "docs/PERCEPTION_V2_FIELD_READINESS_RUNBOOK.md"),
            ("dabai_sensor_package_readme", "workspace", "src/limo_cleanup_dabai_sensor/README.md"),
            ("perception_release_preflight", "workspace", "scripts/perception_release_preflight.py"),
            ("perception_release_rollback", "workspace", "scripts/rollback_perception_release.sh"),
            ("preflight_predecessor_authority_v4", "workspace", "evidence/perception_v2_offline_20260813/ros1_formal_admission_evidence_authority_index_20260815_v4.json"),
            ("preflight_frozen_canonical_v5", "workspace", "evidence/perception_v2_offline_20260813/ros1_noetic_canonical_source_admission_20260815_v5.json"),
            ("preflight_frozen_report_v4", "workspace", "evidence/perception_v2_offline_20260813/frozen_offline_regression_20260815_runner_platform_composite_v4.json"),
            ("semantic_evidence_producer_test", "workspace", "src/limo_cleanup_perception/test/test_ros1_semantic_evidence_producer.py"),
            ("field_readiness_test", "workspace", "src/limo_cleanup_perception/test/test_ros1_noetic_field_readiness.py"),
            ("field_readiness_exact_cli_test", "workspace", "src/limo_cleanup_perception/test/test_ros1_noetic_field_readiness_exact_cli.py"),
            ("perception_package_setup", "workspace", "src/limo_cleanup_perception/setup.py"),
        )
        for expected in required_transitive_roles:
            self.assertIn(expected, definitions)
        host_paths = {
            path for unused_role, root_role, path in definitions
            if (
                root_role == "workspace"
                and path.startswith(CORE.HOST_PERCEPTION_PACKAGE_ROOT + "/")
                and "/__pycache__/" not in path
            )
        }
        self.assertEqual(host_paths, {
            CORE.HOST_PERCEPTION_PACKAGE_ROOT + "/" + name
            for name in CORE.HOST_PERCEPTION_PACKAGE_FILES
        })
        host_cache_paths = {
            path for unused_role, root_role, path in definitions
            if (
                root_role == "workspace"
                and path.startswith(
                    CORE.HOST_PERCEPTION_PACKAGE_ROOT + "/__pycache__/"
                )
            )
        }
        self.assertEqual(host_cache_paths, {
            CORE.HOST_PERCEPTION_PACKAGE_ROOT + "/__pycache__/" + name
            for name in CORE.HOST_PERCEPTION_CACHE_FILES
        })

    def test_host_perception_package_exact_tree_rejects_extra_missing_and_drift(self):
        package_root = "fixture_host_perception_package"
        files = ("a.py", "b.py")
        cache_files = ("a.cpython-314.pyc",)
        definitions = self.policy.source_role_definitions + tuple(
            (
                "fixture_host_package_" + name.replace(".", "_"),
                "workspace", package_root + "/" + name,
            )
            for name in files
        ) + tuple(
            (
                "fixture_host_cache_" + name.replace(".", "_"),
                "workspace", package_root + "/__pycache__/" + name,
            )
            for name in cache_files
        )
        for name in files:
            _write(
                self.root, package_root + "/" + name,
                (name + "\n").encode("utf-8"),
            )
        _write(
            self.root, package_root + "/__pycache__/" + cache_files[0],
            b"fixture pyc bytes\n",
        )
        policy = CORE.AuthorityPolicy(**{
            **self.policy.__dict__,
            "source_role_definitions": definitions,
            "host_perception_package_root": package_root,
            "host_perception_package_files": files,
            "host_perception_cache_files": cache_files,
        })
        roles = CORE.collect_source_role_bindings(self.root, policy)
        binding = CORE.collect_host_perception_package_tree(
            self.root, policy,
        )
        self.assertEqual(binding["file_count"], 3)
        planned_binding, plan_error = GENERATOR._host_tree_plan_state(
            CORE, self.root, policy,
        )
        self.assertEqual(plan_error, None)
        self.assertEqual(planned_binding, binding)

        original_scandir = CORE.os.scandir
        between_scan_extra = self.root / package_root / "between_scan.py"
        calls = {"count": 0}
        def add_source_between_scans(path):
            calls["count"] += 1
            if calls["count"] == 3:
                between_scan_extra.write_bytes(b"between scans\n")
            return original_scandir(path)
        CORE.os.scandir = add_source_between_scans
        try:
            with self.assertRaises(ValueError):
                CORE.collect_host_perception_package_tree(self.root, policy)
        finally:
            CORE.os.scandir = original_scandir
            between_scan_extra.unlink(missing_ok=True)

        between_cache_extra = (
            self.root / package_root / "__pycache__" /
            "between_scan.cpython-314.pyc"
        )
        calls = {"count": 0}
        def add_cache_between_scans(path):
            calls["count"] += 1
            if calls["count"] == 4:
                between_cache_extra.write_bytes(b"between cache scans\n")
            return original_scandir(path)
        CORE.os.scandir = add_cache_between_scans
        try:
            with self.assertRaises(ValueError):
                CORE.collect_host_perception_package_tree(self.root, policy)
        finally:
            CORE.os.scandir = original_scandir
            between_cache_extra.unlink(missing_ok=True)

        original_identity = CORE.source_artifact_identity
        source_path = self.root / package_root / "a.py"
        calls = {"count": 0}
        def mutate_source_before_final_read(workspace, root_role, relative):
            calls["count"] += 1
            if calls["count"] == 4:
                source_path.write_bytes(b"in-place source drift\n")
            return original_identity(workspace, root_role, relative)
        CORE.source_artifact_identity = mutate_source_before_final_read
        try:
            with self.assertRaises(ValueError):
                CORE.collect_host_perception_package_tree(self.root, policy)
        finally:
            CORE.source_artifact_identity = original_identity
            source_path.write_bytes(b"a.py\n")

        cache_path = (
            self.root / package_root / "__pycache__" / cache_files[0]
        )
        calls = {"count": 0}
        def mutate_cache_before_final_read(workspace, root_role, relative):
            calls["count"] += 1
            if calls["count"] == 6:
                cache_path.write_bytes(b"in-place cache drift\n")
            return original_identity(workspace, root_role, relative)
        CORE.source_artifact_identity = mutate_cache_before_final_read
        try:
            with self.assertRaises(ValueError):
                CORE.collect_host_perception_package_tree(self.root, policy)
        finally:
            CORE.source_artifact_identity = original_identity
            cache_path.write_bytes(b"fixture pyc bytes\n")

        extra = self.root / package_root / "extra.py"
        extra.write_bytes(b"EXTRA = True\n")
        failures, unused = CORE._validate_source_roles(
            self.root, roles, policy,
        )
        self.assertIn(
            "formal_authority_v7_host_package_tree_invalid", failures,
        )
        extra.unlink()

        extra_cache = (
            self.root / package_root / "__pycache__" / "extra.cpython-314.pyc"
        )
        extra_cache.write_bytes(b"extra pyc\n")
        planned_binding, plan_error = GENERATOR._host_tree_plan_state(
            CORE, self.root, policy,
        )
        self.assertIsNone(planned_binding)
        self.assertIn("exact file set mismatch", plan_error)
        failures, unused = CORE._validate_source_roles(
            self.root, roles, policy,
        )
        self.assertIn(
            "formal_authority_v7_host_package_tree_invalid", failures,
        )
        extra_cache.unlink()

        missing_cache = (
            self.root / package_root / "__pycache__" / cache_files[0]
        )
        missing_cache.unlink()
        failures, unused = CORE._validate_source_roles(
            self.root, roles, policy,
        )
        self.assertIn(
            "formal_authority_v7_host_package_tree_invalid", failures,
        )
        missing_cache.write_bytes(b"fixture pyc bytes\n")

        cache_subdirectory = self.root / package_root / "__pycache__" / "nested"
        cache_subdirectory.mkdir()
        failures, unused = CORE._validate_source_roles(
            self.root, roles, policy,
        )
        self.assertIn(
            "formal_authority_v7_host_package_tree_invalid", failures,
        )
        cache_subdirectory.rmdir()

        link = self.root / package_root / "__pycache__" / "linked.pyc"
        try:
            link.symlink_to(missing_cache)
        except OSError:
            link = None
        if link is not None:
            failures, unused = CORE._validate_source_roles(
                self.root, roles, policy,
            )
            self.assertIn(
                "formal_authority_v7_host_package_tree_invalid", failures,
            )
            link.unlink()

        missing = self.root / package_root / "b.py"
        missing.unlink()
        failures, unused = CORE._validate_source_roles(
            self.root, roles, policy,
        )
        self.assertIn(
            "formal_authority_v7_host_package_tree_invalid", failures,
        )
        missing.write_bytes(b"b.py\n")

        roles = CORE.collect_source_role_bindings(self.root, policy)
        (self.root / package_root / "a.py").write_bytes(b"DRIFT = True\n")
        failures, unused = CORE._validate_source_roles(
            self.root, roles, policy,
        )
        self.assertTrue(any(
            "source_role_identity_mismatch" in failure
            for failure in failures
        ))

        (self.root / package_root / "a.py").write_bytes(b"a.py\n")
        roles = CORE.collect_source_role_bindings(self.root, policy)
        missing_cache.write_bytes(b"drifted pyc\n")
        failures, unused = CORE._validate_source_roles(
            self.root, roles, policy,
        )
        self.assertTrue(any(
            "source_role_identity_mismatch" in failure
            for failure in failures
        ))

    def test_only_exact_host_package_init_may_be_empty(self):
        init_path = (
            CORE.HOST_PERCEPTION_PACKAGE_ROOT + "/__init__.py"
        )
        init_identity = CORE.source_artifact_identity(
            ROOT, "workspace", init_path,
        )
        self.assertEqual(init_identity["size_bytes"], 0)
        self.assertEqual(
            CORE._identity_failures(
                init_identity, "fixture", with_root=True, allow_empty=True,
            ),
            [],
        )
        self.assertIn(
            "fixture_size_invalid",
            CORE._identity_failures(
                init_identity, "fixture", with_root=True, allow_empty=False,
            ),
        )
        self.assertEqual(
            CORE.ALLOWED_EMPTY_SOURCE_PATHS,
            (("workspace", init_path),),
        )
        # The isolated child deliberately cannot read workspace bytecode.
        # The generation parent owns the live host-tree identity read and
        # recomputes it before and after the execution matrix and again before
        # the index commit point.  Keep this child assertion structural so no
        # ordinary pyc path exception is introduced into the source-only guard.
        policy = CORE.PRODUCTION_POLICY
        self.assertEqual(
            policy.host_perception_package_root,
            CORE.HOST_PERCEPTION_PACKAGE_ROOT,
        )
        self.assertEqual(
            policy.host_perception_package_files,
            CORE.HOST_PERCEPTION_PACKAGE_FILES,
        )
        self.assertEqual(
            policy.host_perception_cache_files,
            CORE.HOST_PERCEPTION_CACHE_FILES,
        )
        source_role_paths = {
            (root_role, path)
            for unused_role, root_role, path
            in policy.source_role_definitions
        }
        self.assertIn(("workspace", init_path), source_role_paths)
        self.assertEqual(
            {
                path for root_role, path in source_role_paths
                if (
                    root_role == "workspace"
                    and path.startswith(
                        CORE.HOST_PERCEPTION_PACKAGE_ROOT + "/__pycache__/"
                    )
                )
            },
            {
                CORE.HOST_PERCEPTION_PACKAGE_ROOT + "/__pycache__/" + name
                for name in CORE.HOST_PERCEPTION_CACHE_FILES
            },
        )

        empty_path = "empty_unrelated_role.txt"
        _write(self.root, empty_path, b"")
        policy = CORE.AuthorityPolicy(**{
            **self.policy.__dict__,
            "source_role_definitions": self.policy.source_role_definitions + (
                ("empty_unrelated_role", "workspace", empty_path),
            ),
        })
        roles = CORE.collect_source_role_bindings(self.root, policy)
        failures, unused = CORE._validate_source_roles(
            self.root, roles, policy,
        )
        self.assertIn(
            "formal_authority_v7_source_role_size_invalid", failures,
        )

    def test_production_suite_inventory_is_mechanical_and_contains_new_suites(self):
        inventory = CORE.suite_inventory(ROOT)
        by_id = {item["suite_id"]: item for item in inventory}
        for suite_id in (
            "camera_runtime_import_probe", "camera_runtime_install_admission",
            "camera_only_atomic_launcher", "machine_contract_doc_demotion",
            "camera_only_operator_docs", "runtime_source_contract",
            "dabai_runtime_contract", "legacy_operational_scripts",
            "perception_release_artifacts", "field_readiness",
            "field_readiness_exact_cli", "semantic_evidence_producer",
            "successor_authority_validator",
        ):
            self.assertIn(suite_id, by_id)
            self.assertGreater(by_id[suite_id]["logical_count"], 0)
        self.assertIn(
            CORE.ATOMIC_SUPPORTING_TEST_ID,
            by_id["camera_only_atomic_launcher"]["expected_test_ids"],
        )
        semantic_records = [
            item for item in CORE.EXECUTION_DEFINITIONS
            if item["suite_id"] == "semantic_evidence_producer"
        ]
        self.assertEqual(
            {item["interpreter_role"] for item in semantic_records},
            {"system_python3_entry", "system_python314_target"},
        )
        self.assertEqual(len(CORE.REQUIRED_SOURCE_ROLE_DEFINITIONS), 103)
        self.assertIn(
            CORE.GENERATION_WRAPPER_SOURCE_PATH,
            CORE.EXTERNAL_TRUST_ROOT_EXCLUSIONS,
        )
        self.assertNotIn(
            CORE.GENERATION_WRAPPER_SOURCE_PATH,
            {path for unused, unused_root, path
             in CORE.REQUIRED_SOURCE_ROLE_DEFINITIONS},
        )

        generator_tree = ast.parse(
            _source_text(GENERATOR.GENERATOR_RELATIVE_PATH),
            filename=GENERATOR.GENERATOR_RELATIVE_PATH,
        )
        matrix_functions = [
            node for node in generator_tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "_run_execution_matrix"
        ]
        self.assertEqual(1, len(matrix_functions))
        verifier_calls = [
            node for node in ast.walk(matrix_functions[0])
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "core"
            and node.func.attr == "validate_pyc_verifier_result"
        ]
        self.assertEqual(1, len(verifier_calls))
        verifier_call = verifier_calls[0]
        self.assertEqual([], verifier_call.keywords)
        self.assertEqual(3, len(verifier_call.args))
        self.assertIsInstance(verifier_call.args[0], ast.Name)
        self.assertEqual("verifier_result", verifier_call.args[0].id)
        self.assertIsInstance(verifier_call.args[1], ast.Subscript)
        self.assertIsInstance(verifier_call.args[1].value, ast.Name)
        self.assertEqual("definition", verifier_call.args[1].value.id)
        self.assertIsInstance(verifier_call.args[1].slice, ast.Constant)
        self.assertEqual("record_id", verifier_call.args[1].slice.value)
        self.assertIsInstance(verifier_call.args[2], ast.Name)
        self.assertEqual(
            "broker_artifact_identity", verifier_call.args[2].id,
        )
        broker_assignments = [
            node for node in ast.walk(matrix_functions[0])
            if isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "broker_identity"
        ]
        self.assertEqual(1, len(broker_assignments))
        broker_assignment = broker_assignments[0]
        self.assertLess(broker_assignment.lineno, verifier_call.lineno)
        self.assertIsInstance(broker_assignment.value, ast.Call)
        self.assertIsInstance(broker_assignment.value.func, ast.Name)
        self.assertEqual(
            "_source_identity", broker_assignment.value.func.id,
        )
        self.assertEqual(3, len(broker_assignment.value.args))
        self.assertIsInstance(broker_assignment.value.args[0], ast.Name)
        self.assertEqual("sources", broker_assignment.value.args[0].id)
        self.assertIsInstance(broker_assignment.value.args[1], ast.Constant)
        self.assertEqual("workspace", broker_assignment.value.args[1].value)
        self.assertIsInstance(broker_assignment.value.args[2], ast.Attribute)
        self.assertIsInstance(
            broker_assignment.value.args[2].value, ast.Name,
        )
        self.assertEqual(
            "core", broker_assignment.value.args[2].value.id,
        )
        self.assertEqual(
            "PYC_BROKER_RELATIVE_PATH",
            broker_assignment.value.args[2].attr,
        )
        artifact_identity_functions = [
            node for node in generator_tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "_artifact_identity"
        ]
        self.assertEqual(1, len(artifact_identity_functions))
        artifact_returns = [
            node for node in artifact_identity_functions[0].body
            if isinstance(node, ast.Return)
        ]
        self.assertEqual(1, len(artifact_returns))
        self.assertIsInstance(artifact_returns[0].value, ast.DictComp)
        artifact_projection = GENERATOR._artifact_identity({
            "root_role": "workspace",
            "path": PYC_BROKER_RELATIVE_PATH,
            "size_bytes": 17,
            "sha256": "1" * 64,
        })
        self.assertEqual(
            {"path", "size_bytes", "sha256"},
            set(artifact_projection),
        )
        self.assertNotIn("root_role", artifact_projection)
        with self.assertRaises(KeyError):
            GENERATOR._artifact_identity({
                "root_role": "workspace",
                "path": PYC_BROKER_RELATIVE_PATH,
                "size_bytes": 17,
            })
        broker_transcript_calls = [
            node for node in ast.walk(matrix_functions[0])
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "core"
            and node.func.attr == "validate_pyc_broker_transcript"
        ]
        self.assertEqual(1, len(broker_transcript_calls))
        broker_transcript_call = broker_transcript_calls[0]
        self.assertEqual([], broker_transcript_call.keywords)
        self.assertEqual(4, len(broker_transcript_call.args))
        self.assertEqual(
            ["broker_artifact_identity", "verifier_artifact_identity"],
            [
                argument.id
                for argument in broker_transcript_call.args[2:]
                if isinstance(argument, ast.Name)
            ],
        )
        artifact_assignments = {
            node.targets[0].id: node
            for node in ast.walk(matrix_functions[0])
            if isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id in {
                "broker_artifact_identity", "verifier_artifact_identity",
            }
        }
        self.assertEqual(
            {"broker_artifact_identity", "verifier_artifact_identity"},
            set(artifact_assignments),
        )
        for target, source in (
            ("broker_artifact_identity", "broker_identity"),
            ("verifier_artifact_identity", "verifier_identity"),
        ):
            value = artifact_assignments[target].value
            self.assertIsInstance(value, ast.Call)
            self.assertIsInstance(value.func, ast.Name)
            self.assertEqual("_artifact_identity", value.func.id)
            self.assertEqual([], value.keywords)
            self.assertEqual(1, len(value.args))
            self.assertIsInstance(value.args[0], ast.Name)
            self.assertEqual(source, value.args[0].id)

        core_tree = ast.parse(
            _source_text(GENERATOR.CORE_RELATIVE_PATH),
            filename=GENERATOR.CORE_RELATIVE_PATH,
        )
        physical_validators = [
            node for node in core_tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "_validate_physical_records"
        ]
        self.assertEqual(1, len(physical_validators))
        physical_validator = physical_validators[0]
        core_artifact_assignments = {
            node.targets[0].id: node.value
            for node in ast.walk(physical_validator)
            if isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id in {
                "broker_artifact_identity", "verifier_artifact_identity",
            }
            and isinstance(node.value, ast.DictComp)
        }
        self.assertEqual(
            {"broker_artifact_identity", "verifier_artifact_identity"},
            set(core_artifact_assignments),
        )
        for target, source in (
            ("broker_artifact_identity", "broker_identity"),
            ("verifier_artifact_identity", "verifier_identity"),
        ):
            projection = core_artifact_assignments[target]
            self.assertEqual(1, len(projection.generators))
            iterator = projection.generators[0].iter
            self.assertIsInstance(iterator, ast.Tuple)
            self.assertEqual(
                ["path", "size_bytes", "sha256"],
                [item.value for item in iterator.elts],
            )
            self.assertIsInstance(projection.value, ast.Subscript)
            self.assertIsInstance(projection.value.value, ast.Name)
            self.assertEqual(source, projection.value.value.id)

        consumer_calls = {}
        for node in ast.walk(physical_validator):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in {
                    "_pyc_broker_transcript_failures",
                    "_pyc_verifier_result_failures",
                    "expected_pyc_broker_argv",
                }
            ):
                consumer_calls.setdefault(node.func.id, []).append(node)
        self.assertEqual(
            {
                "_pyc_broker_transcript_failures",
                "_pyc_verifier_result_failures",
                "expected_pyc_broker_argv",
            },
            set(consumer_calls),
        )
        self.assertTrue(all(len(calls) == 1 for calls in consumer_calls.values()))
        transcript_consumer = consumer_calls[
            "_pyc_broker_transcript_failures"
        ][0]
        self.assertEqual(
            ["broker_artifact_identity", "verifier_artifact_identity"],
            [argument.id for argument in transcript_consumer.args[2:]],
        )
        verifier_consumer = consumer_calls["_pyc_verifier_result_failures"][0]
        self.assertIsInstance(verifier_consumer.args[2], ast.Name)
        self.assertEqual(
            "broker_artifact_identity", verifier_consumer.args[2].id,
        )
        broker_argv_consumer = consumer_calls["expected_pyc_broker_argv"][0]
        self.assertIsInstance(broker_argv_consumer.args[3], ast.Name)
        self.assertEqual(
            "broker_artifact_identity", broker_argv_consumer.args[3].id,
        )

        production_record_ids = [
            item["record_id"] for item in CORE.EXECUTION_DEFINITIONS
        ]
        self.assertEqual(21, len(production_record_ids))
        self.assertEqual(21, len(set(production_record_ids)))
        self.assertEqual(42, sum(2 for unused in production_record_ids))

        broker_source = self._source(PYC_BROKER_RELATIVE_PATH)
        source_role_identity = CORE._identity_from_source(
            {("workspace", PYC_BROKER_RELATIVE_PATH): broker_source},
            "workspace", PYC_BROKER_RELATIVE_PATH,
        )
        self.assertEqual(
            {"root_role", "path", "size_bytes", "sha256"},
            set(source_role_identity),
        )
        sample_record = self.physical[0]
        sample_record_id = sample_record["record_id"]
        sample_transcript = sample_record["pyc_broker_transcript"]
        sample_broker_artifact = sample_transcript[
            "broker_artifact_identity"
        ]
        sample_verifier_artifact = sample_transcript[
            "verifier_artifact_identity"
        ]
        self.assertEqual(
            {"path", "size_bytes", "sha256"},
            set(sample_broker_artifact),
        )
        self.assertEqual(
            {"path", "size_bytes", "sha256"},
            set(sample_verifier_artifact),
        )
        self.assertEqual([], CORE.validate_pyc_broker_transcript(
            sample_transcript, sample_record_id,
            sample_broker_artifact, sample_verifier_artifact,
        ))
        self.assertEqual([], CORE.validate_pyc_verifier_result(
            sample_record["pyc_verifier_result"], sample_record_id,
            sample_broker_artifact,
        ))
        four_key_transcript = deepcopy(sample_transcript)
        four_key_transcript["broker_artifact_identity"] = {
            "root_role": "workspace", **sample_broker_artifact,
        }
        self.assertIn(
            "formal_authority_v7_pyc_broker:{}:transcript_mismatch:"
            "broker_artifact_identity".format(sample_record_id),
            CORE.validate_pyc_broker_transcript(
                four_key_transcript, sample_record_id,
                sample_broker_artifact, sample_verifier_artifact,
            ),
        )
        four_key_verifier = deepcopy(sample_record["pyc_verifier_result"])
        four_key_verifier["broker_execution_binding"] = {
            "root_role": "workspace",
            **four_key_verifier["broker_execution_binding"],
        }
        self.assertIn(
            "formal_authority_v7_pyc_verifier:{}:mismatch:"
            "broker_execution_binding".format(sample_record_id),
            CORE.validate_pyc_verifier_result(
                four_key_verifier, sample_record_id,
                sample_broker_artifact,
            ),
        )

        definitions = {
            item["record_id"]: item for item in CORE.EXECUTION_DEFINITIONS
        }
        wrapper_identity = CORE.artifact_identity(
            ROOT, CORE.GENERATION_WRAPPER_SOURCE_PATH,
        )
        target_observation = {
            "path": CORE.GENERATION_WRAPPER_SOURCE_PATH,
            "parent_before": deepcopy(wrapper_identity),
            "child_read": deepcopy(wrapper_identity),
            "parent_after": deepcopy(wrapper_identity),
        }
        target_marker = {
            "workspace_source_reads": [deepcopy(wrapper_identity)],
        }
        self.assertEqual([], CORE._external_wrapper_observation_failures(
            CORE.GENERATION_WRAPPER_READ_RECORD_ID, target_marker,
            target_observation, definitions,
        ))
        other_record_id = "probe_wsl_python314"
        other_observation = {
            "path": CORE.GENERATION_WRAPPER_SOURCE_PATH,
            "parent_before": deepcopy(wrapper_identity),
            "child_read": None,
            "parent_after": deepcopy(wrapper_identity),
        }
        self.assertEqual([], CORE._external_wrapper_observation_failures(
            other_record_id, {"workspace_source_reads": []},
            other_observation, definitions,
        ))

        wrong_identity = deepcopy(wrapper_identity)
        wrong_identity["sha256"] = "f" * 64
        core_scope_cases = []
        missing = deepcopy(target_marker)
        missing["workspace_source_reads"] = []
        core_scope_cases.append((
            CORE.GENERATION_WRAPPER_READ_RECORD_ID, missing,
            deepcopy(target_observation), "marker_read_scope_invalid",
        ))
        wrong = deepcopy(target_marker)
        wrong["workspace_source_reads"] = [deepcopy(wrong_identity)]
        core_scope_cases.append((
            CORE.GENERATION_WRAPPER_READ_RECORD_ID, wrong,
            deepcopy(target_observation), "marker_read_scope_invalid",
        ))
        duplicate = deepcopy(target_marker)
        duplicate["workspace_source_reads"].append(
            deepcopy(wrapper_identity))
        core_scope_cases.append((
            CORE.GENERATION_WRAPPER_READ_RECORD_ID, duplicate,
            deepcopy(target_observation), "marker_read_scope_invalid",
        ))
        wrong_record_observation = deepcopy(other_observation)
        wrong_record_observation["child_read"] = deepcopy(wrapper_identity)
        core_scope_cases.append((
            other_record_id, deepcopy(target_marker),
            wrong_record_observation, "child_read_scope_invalid",
        ))
        parent_drift = deepcopy(target_observation)
        parent_drift["parent_after"] = deepcopy(wrong_identity)
        core_scope_cases.append((
            CORE.GENERATION_WRAPPER_READ_RECORD_ID,
            deepcopy(target_marker), parent_drift, "parent_identity_drift",
        ))
        for record_id, marker, observation, expected_code in core_scope_cases:
            failures = CORE._external_wrapper_observation_failures(
                record_id, marker, observation, definitions,
            )
            self.assertTrue(any(
                expected_code in failure for failure in failures
            ), (record_id, expected_code, failures))

        wrong_definitions = deepcopy(definitions)
        wrong_definitions[CORE.GENERATION_WRAPPER_READ_RECORD_ID] = {
            **wrong_definitions[CORE.GENERATION_WRAPPER_READ_RECORD_ID],
            "suite_id": "wrong_suite",
        }
        self.assertTrue(any(
            "record_definition_invalid" in failure
            for failure in CORE._external_wrapper_observation_failures(
                CORE.GENERATION_WRAPPER_READ_RECORD_ID, target_marker,
                target_observation, wrong_definitions,
            )
        ))

        observation_by_id = {
            record_id: {
                "external_wrapper_observation": deepcopy(
                    target_observation
                    if record_id == CORE.GENERATION_WRAPPER_READ_RECORD_ID
                    else other_observation
                ),
            }
            for record_id in definitions
        }
        self.assertEqual([], CORE._external_wrapper_observation_set_failures(
            observation_by_id, definitions,
        ))
        split = deepcopy(observation_by_id)
        split[other_record_id]["external_wrapper_observation"][
            "parent_after"
        ] = deepcopy(wrong_identity)
        self.assertIn(
            "formal_authority_v7_external_wrapper_parent_identity_split",
            CORE._external_wrapper_observation_set_failures(
                split, definitions,
            ),
        )
        missing_observation = deepcopy(observation_by_id)
        missing_observation[other_record_id][
            "external_wrapper_observation"
        ] = None
        self.assertIn(
            "formal_authority_v7_external_wrapper_observation_set_invalid",
            CORE._external_wrapper_observation_set_failures(
                missing_observation, definitions,
            ),
        )

        stable_signature = [{"component": "wrapper", "mtime_ns": 1}]
        target_definition = definitions[
            CORE.GENERATION_WRAPPER_READ_RECORD_ID
        ]
        generated = GENERATOR._external_wrapper_observation(
            CORE, target_definition, target_marker,
            wrapper_identity, stable_signature,
            wrapper_identity, stable_signature,
        )
        self.assertEqual(generated, target_observation)
        generated_other = GENERATOR._external_wrapper_observation(
            CORE, definitions[other_record_id],
            {"workspace_source_reads": []},
            wrapper_identity, stable_signature,
            wrapper_identity, stable_signature,
        )
        self.assertEqual(generated_other, other_observation)
        for marker in (missing, wrong, duplicate):
            with self.assertRaisesRegex(
                    GENERATOR.GenerationError,
                    "child_external_wrapper_read_scope_invalid"):
                GENERATOR._external_wrapper_observation(
                    CORE, target_definition, marker,
                    wrapper_identity, stable_signature,
                    wrapper_identity, stable_signature,
                )
        with self.assertRaisesRegex(
                GENERATOR.GenerationError,
                "child_external_wrapper_read_scope_invalid"):
            GENERATOR._external_wrapper_observation(
                CORE, definitions[other_record_id], target_marker,
                wrapper_identity, stable_signature,
                wrapper_identity, stable_signature,
            )
        with self.assertRaisesRegex(
                GENERATOR.GenerationError,
                "child_external_wrapper_parent_identity_drift"):
            GENERATOR._external_wrapper_observation(
                CORE, target_definition, target_marker,
                wrapper_identity, stable_signature,
                wrong_identity, stable_signature,
            )
        with self.assertRaisesRegex(
                GENERATOR.GenerationError,
                "child_external_wrapper_runtime_drift"):
            GENERATOR._external_wrapper_observation(
                CORE, target_definition, target_marker,
                wrapper_identity, stable_signature,
                wrapper_identity,
                [{"component": "wrapper", "mtime_ns": 2}],
            )

    def test_workspace_timestamp_pyc_is_blocked_and_loader_report_is_exact(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            core_raw = (ROOT / GENERATOR.CORE_RELATIVE_PATH).read_bytes()
            core_binding = _write(
                workspace, GENERATOR.CORE_RELATIVE_PATH, core_raw,
            )
            core_anchor = {
                key: core_binding[key]
                for key in ("path", "size_bytes", "sha256")
            }
            wrapper_raw = (
                ROOT / CORE.GENERATION_WRAPPER_SOURCE_PATH
            ).read_bytes()
            wrapper_raw = _replace_top_level_literal_assignment(
                wrapper_raw, CORE.GENERATION_WRAPPER_SOURCE_PATH,
                "CORE_SOURCE_TRUST_ANCHOR", core_anchor,
            )
            _write(
                workspace, CORE.GENERATION_WRAPPER_SOURCE_PATH, wrapper_raw,
            )
            package = workspace / "poison_package"
            package.mkdir()
            package_source = package / "__init__.py"
            malicious = b"VALUE = 'PYC'\n"
            benign = b"VALUE = 'SRC'\n"
            self.assertEqual(len(malicious), len(benign))
            stamp = 1_700_000_000
            package_source.write_bytes(malicious)
            os.utime(package_source, (stamp, stamp))
            pyc_path = Path(py_compile.compile(
                str(package_source), doraise=True,
                invalidation_mode=py_compile.PycInvalidationMode.TIMESTAMP,
            ))
            package_source.write_bytes(benign)
            os.utime(package_source, (stamp, stamp))
            relative_pyc = pyc_path.relative_to(workspace).as_posix()
            (workspace / "direct.pyc").write_bytes(b"DIRECT_PYC_BYTES")
            fixture_inventory = []
            for fixture_path in sorted((
                workspace / "direct.pyc", pyc_path,
            )):
                fixture_raw = fixture_path.read_bytes()
                fixture_inventory.append({
                    "path": fixture_path.relative_to(workspace).as_posix(),
                    "size_bytes": len(fixture_raw),
                    "sha256": hashlib.sha256(fixture_raw).hexdigest(),
                })
            fixture_inventory_sha256 = hashlib.sha256(
                _compact_json(fixture_inventory)
            ).hexdigest()
            broker_raw = (ROOT / PYC_BROKER_RELATIVE_PATH).read_bytes()
            broker_raw = _replace_top_level_literal_assignment(
                broker_raw, PYC_BROKER_RELATIVE_PATH,
                "EXPECTED_INVENTORY_COUNT", len(fixture_inventory),
            )
            broker_raw = _replace_top_level_literal_assignment(
                broker_raw, PYC_BROKER_RELATIVE_PATH,
                "EXPECTED_INVENTORY_SHA256", fixture_inventory_sha256,
            )
            _write(workspace, PYC_BROKER_RELATIVE_PATH, broker_raw)
            verifier_raw = (
                ROOT / PYC_VERIFIER_RELATIVE_PATH
            ).read_bytes()
            verifier_raw = _replace_top_level_literal_assignment(
                verifier_raw, PYC_VERIFIER_RELATIVE_PATH,
                "PYC_INVENTORY", tuple(fixture_inventory),
            )
            _write(workspace, PYC_VERIFIER_RELATIVE_PATH, verifier_raw)

            child_environment = (
                GENERATOR._outer_windows_environment()
                if os.name == "nt" else dict(CORE.CHILD_ENVIRONMENT)
            )
            control = subprocess.run(
                [
                    sys.executable, "-I", "-S", "-B", "-c",
                    "import sys;sys.path.insert(0,{!r});"
                    "import poison_package;print(poison_package.VALUE)".format(
                        str(workspace)
                    ),
                ],
                cwd=str(workspace), env=child_environment,
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, check=False, timeout=30,
                close_fds=True,
            )
            self.assertEqual(0, control.returncode, control.stderr)
            self.assertEqual([b"PYC"], control.stdout.splitlines())

            runner_cases = (
                (
                    CORE.UNITTEST_RUNNER, False, "sample_unittest.py",
                     "sample_unittest.py::LoaderCase.test_source_only",
                     b"from pathlib import Path\nimport unittest\nimport poison_package\n"
                     b"class LoaderCase(unittest.TestCase):\n"
                     b"    def test_source_only(self):\n"
                     b"        with self.assertRaises(PermissionError):\n"
                     b"            Path('direct.pyc').read_bytes()\n"
                     b"        self.assertEqual('SRC', poison_package.VALUE)\n",
                    CORE.UNITTEST_MARKER,
                ),
                (
                    CORE.PYTEST_RUNNER, True, "sample_pytest.py",
                    "sample_pytest.py::test_source_only",
                     b"from pathlib import Path\nimport poison_package\n"
                     b"def test_source_only():\n"
                     b"    try:\n"
                     b"        Path('direct.pyc').read_bytes()\n"
                     b"    except PermissionError:\n"
                     b"        pass\n"
                     b"    else:\n"
                     b"        raise AssertionError('workspace pyc read was not blocked')\n"
                     b"    assert poison_package.VALUE == 'SRC'\n",
                    CORE.PYTEST_MARKER,
                ),
            )
            for runner_relative, pytest_style, target_name, test_id, raw, marker_prefix in runner_cases:
                runner_raw = ROOT.joinpath(
                    *runner_relative.split("/")
                ).read_bytes()
                runner_raw = _replace_top_level_literal_assignment(
                    runner_raw, runner_relative, "PYC_INVENTORY_COUNT",
                    len(fixture_inventory),
                )
                runner_raw = _replace_top_level_literal_assignment(
                    runner_raw, runner_relative, "PYC_INVENTORY_SHA256",
                    fixture_inventory_sha256,
                )
                runner_binding = _write(
                    workspace, runner_relative, runner_raw,
                )
                (workspace / target_name).write_bytes(raw)
                argv = [
                    sys.executable, "-I", "-S", "-B", "-c",
                    CORE.EXECUTION_COMPONENT_BOOTSTRAP, str(workspace),
                    runner_relative, str(runner_binding["size_bytes"]),
                    runner_binding["sha256"], "runner",
                    CORE.EXECUTION_COMPONENT_BOOTSTRAP_SCHEMA,
                    CORE.EXECUTION_COMPONENT_BOOTSTRAP_SHA256,
                ]
                if pytest_style:
                    argv.append("--single-file")
                argv.extend((
                    "--mode", "supervisor-v2",
                    "--workspace", str(workspace),
                    "--record-id", "timestamp_pyc_" + Path(target_name).stem,
                    "--suite-id", "workspace_timestamp_pyc_contract",
                    "--target", target_name,
                    "--import-root", ".",
                    "--expected-id", test_id,
                ))
                completed = subprocess.run(
                    argv, cwd=str(workspace), env=child_environment,
                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, check=False, timeout=30,
                    close_fds=True,
                )
                self.assertEqual(0, completed.returncode, completed.stderr)
                lines = completed.stdout.splitlines()
                self.assertEqual(1, len(lines), completed.stdout)
                self.assertTrue(lines[0].startswith(marker_prefix.encode("ascii")))
                marker = json.loads(lines[0][len(marker_prefix):])
                profile = CORE.runner_profile(
                    "pytest_style" if pytest_style else "unittest"
                )
                self.assertEqual(profile["runner_kind"], marker["runner_kind"])
                self.assertEqual(
                    profile["result_schema"], marker["schema_version"],
                )
                self.assertEqual(CORE.WORKSPACE_BYTECODE_POLICY,
                                 marker["workspace_bytecode_policy"])
                self.assertEqual(0, marker["workspace_pyc_bytes_read"])
                self.assertTrue(marker["workspace_loader_guard_restored"])
                self.assertTrue(marker["workspace_pyc_audit_hook_active"])
                self.assertEqual(
                    CORE.WORKSPACE_PYC_INODE_POLICY,
                    marker["workspace_pyc_inode_policy"],
                )
                self.assertGreaterEqual(marker["workspace_pyc_inventory_count"], 2)
                self.assertTrue(marker["workspace_pyc_inventory_stable"])
                transcript = marker["pyc_broker_transcript"]
                self.assertEqual(
                    CORE.PYC_BROKER_TRANSCRIPT_SCHEMA,
                    transcript["schema_version"],
                )
                for event in (
                    [transcript["ready"]]
                    + transcript["checkpoints"]
                    + [transcript["final"]]
                ):
                    self.assertEqual(
                        CORE.PYC_BROKER_RESULT_SCHEMA,
                        event["schema_version"],
                    )
                verifier_result = marker["pyc_verifier_result"]
                self.assertEqual(
                    CORE.PYC_VERIFIER_RESULT_SCHEMA,
                    verifier_result["schema_version"],
                )
                observation = marker["production_wrapper_observation"]
                self.assertEqual(
                    CORE.PRODUCTION_WRAPPER_OBSERVATION_SCHEMA,
                    observation["schema_version"],
                )
                self.assertTrue(verifier_result["validated_pass"])
                self.assertEqual([], verifier_result["failures"])
                self.assertEqual(
                    len(fixture_inventory),
                    verifier_result["inventory_count"],
                )
                self.assertEqual(
                    fixture_inventory_sha256,
                    verifier_result["inventory_sha256"],
                )
                self.assertEqual(
                    [], CORE.validate_production_wrapper_observation(
                        observation, observation["record_id"],
                    ),
                )
                self.assertIn(relative_pyc,
                              marker["workspace_pyc_attempts_blocked"])
                self.assertIn("direct.pyc",
                              marker["workspace_pyc_attempts_blocked"])
                reads = {
                    item["path"]: item
                    for item in marker["workspace_source_reads"]
                }
                self.assertEqual(
                    hashlib.sha256(benign).hexdigest(),
                    reads["poison_package/__init__.py"]["sha256"],
                )

        def uppercase_blocked_path(report):
            record = report["test_matrix"]["physical_execution_records"][0]
            record["marker_payload"]["workspace_pyc_attempts_blocked"] = [
                "__PYCACHE__/UPPER.PYC",
            ]
            record["marker_payload_sha256"] = _sha(record["marker_payload"])

        self._replace_report(uppercase_blocked_path)
        uppercase_result = self._validate()
        self.assertTrue(
            uppercase_result["semantic_validated_pass"],
            uppercase_result["failures"],
        )
        self.tearDown()
        self.setUp()

        mutation_cases = (
            ("missing_policy", "policy_invalid"),
            ("pyc_bytes", "pyc_bytes_read_nonzero"),
            ("guard", "guard_not_restored"),
            ("audit_hook", "pyc_audit_hook_not_active"),
            ("inode_policy", "pyc_inode_policy_invalid"),
            ("inventory_count", "pyc_inventory_count_invalid"),
            ("inventory_stable", "pyc_inventory_not_stable"),
            ("unbound", "source_read_unbound"),
            ("blocked_path", "blocked_path_invalid"),
            ("blocked_duplicate", "blocked_paths_order_or_duplicate_invalid"),
            ("source_schema", "source_read_schema_invalid"),
            ("source_duplicate", "source_read_order_or_duplicate_invalid"),
            ("target_missing", "target_source_read_missing"),
            ("identity_mismatch", "source_read_identity_mismatch"),
        )
        for case, expected_code in mutation_cases:
            def mutate(report, case=case):
                record = report["test_matrix"]["physical_execution_records"][0]
                marker = record["marker_payload"]
                if case == "missing_policy":
                    marker.pop("workspace_bytecode_policy")
                elif case == "pyc_bytes":
                    marker["workspace_pyc_bytes_read"] = 1
                elif case == "guard":
                    marker["workspace_loader_guard_restored"] = False
                elif case == "audit_hook":
                    marker["workspace_pyc_audit_hook_active"] = False
                elif case == "inode_policy":
                    marker["workspace_pyc_inode_policy"] = "UNTRUSTED"
                elif case == "inventory_count":
                    marker["workspace_pyc_inventory_count"] = -1
                elif case == "inventory_stable":
                    marker["workspace_pyc_inventory_stable"] = False
                elif case == "unbound":
                    marker["workspace_source_reads"].append({
                        "path": "unbound.py", "size_bytes": 1,
                        "sha256": "f" * 64,
                    })
                    marker["workspace_source_reads"].sort(
                        key=lambda item: item["path"])
                elif case == "blocked_path":
                    marker["workspace_pyc_attempts_blocked"] = ["not_bytecode.py"]
                elif case == "blocked_duplicate":
                    marker["workspace_pyc_attempts_blocked"] = [
                        "__pycache__/x.pyc", "__pycache__/x.pyc",
                    ]
                elif case == "source_schema":
                    marker["workspace_source_reads"][0]["extra"] = True
                elif case == "source_duplicate":
                    marker["workspace_source_reads"].append(
                        deepcopy(marker["workspace_source_reads"][0]))
                elif case == "target_missing":
                    marker["workspace_source_reads"] = []
                else:
                    marker["workspace_source_reads"][0]["sha256"] = "f" * 64
                record["marker_payload_sha256"] = _sha(marker)
            self._replace_report(mutate)
            result = self._validate()
            self.assertTrue(any(
                expected_code in failure for failure in result["failures"]
            ), (case, result["failures"]))
            self.tearDown()
            self.setUp()

        from audit_tools import run_pytest_style_tests_v2 as pytest_runner
        from audit_tools import run_unittest_file_tests_v2 as unittest_runner

        hardlink_target = self.root / "hardlink-target.pyc"
        hardlink_target.write_bytes(b"HARDLINK_PYC")
        with tempfile.TemporaryDirectory(dir=self.root.parent) as outside_directory:
            outside_hardlink = Path(outside_directory) / "outside-hardlink"
            try:
                os.link(hardlink_target, outside_hardlink)
            except OSError:
                outside_hardlink = None
            if outside_hardlink is not None:
                guard_factories = (
                    lambda: unittest_runner._WorkspaceLoaderGuard(
                        self.root, {}),
                    lambda: pytest_runner.WorkspaceLoaderGuard(self.root),
                )
                for guard_factory in guard_factories:
                    candidate_guard = guard_factory()
                    with self.assertRaisesRegex(
                            ValueError, "workspace_bytecode_hardlink_rejected"):
                        if hasattr(candidate_guard, "__enter__"):
                            with candidate_guard:
                                pass
                        else:
                            candidate_guard.install()
                outside_hardlink.unlink()
        hardlink_target.unlink()

        loop_a = self.root / "loop-a.pyc"
        loop_b = self.root / "loop-b.pyc"
        loop_created = False
        try:
            loop_a.symlink_to(loop_b)
            loop_b.symlink_to(loop_a)
            loop_created = True
        except OSError:
            for path in (loop_a, loop_b):
                try:
                    path.unlink()
                except OSError:
                    pass
        if loop_created:
            with self.assertRaisesRegex(
                    ValueError, "workspace_bytecode_file_linklike"):
                with unittest_runner._WorkspaceLoaderGuard(self.root, {}):
                    pass
            loop_a.unlink()
            loop_b.unlink()

        original_loader = unittest_runner.importlib.machinery.SourceFileLoader

        class ReplacementSourceFileLoader:
            pass

        alias_target = self.root / "alias-target.pyc"
        alias_target.write_bytes(b"ALIAS_TARGET_PYC")
        outside_alias_directory = tempfile.TemporaryDirectory(
            dir=self.root.parent)
        outside_alias = Path(outside_alias_directory.name) / "alias-without-pyc-suffix"
        try:
            outside_alias.symlink_to(alias_target)
        except OSError:
            outside_alias = None
        guard_report = {}
        guard = unittest_runner._WorkspaceLoaderGuard(self.root, guard_report)
        with self.assertRaisesRegex(
                ValueError, "workspace_loader_guard_replaced_during_execution"):
            with guard:
                with self.assertRaises(PermissionError):
                    alias_target.read_bytes()
                if outside_alias is not None:
                    with self.assertRaises(PermissionError):
                        outside_alias.read_bytes()
                unittest_runner.importlib.machinery.SourceFileLoader = (
                    ReplacementSourceFileLoader)
        outside_alias_directory.cleanup()
        self.assertIs(
            original_loader,
            unittest_runner.importlib.machinery.SourceFileLoader,
        )
        self.assertTrue(guard_report["workspace_loader_guard_restored"])
        self.assertTrue(guard_report["workspace_pyc_audit_hook_active"])
        self.assertTrue(guard_report["workspace_pyc_inventory_stable"])
        self.assertIn(
            "alias-target.pyc",
            guard_report["workspace_pyc_attempts_blocked"],
        )

        pytest_guard = pytest_runner.WorkspaceLoaderGuard(self.root)
        original_pytest_loader = (
            pytest_runner.importlib.machinery.SourceFileLoader)
        pytest_guard.install()
        try:
            pytest_runner.importlib.machinery.SourceFileLoader = (
                ReplacementSourceFileLoader)
            self.assertFalse(pytest_guard._guard_is_installed())
        finally:
            pytest_guard.restore()
        self.assertIs(
            original_pytest_loader,
            pytest_runner.importlib.machinery.SourceFileLoader,
        )
        self.assertTrue(pytest_guard.tampered)
        self.assertTrue(pytest_guard.restored)

    def test_legacy_suite_has_two_physical_interpreters_but_one_logical_suite(self):
        records = [
            item for item in CORE.EXECUTION_DEFINITIONS
            if item["suite_id"] == "legacy_operational_scripts"
        ]
        self.assertEqual(
            {item["interpreter_role"] for item in records},
            {"system_python3_entry", "system_python314_target"},
        )
        self.assertEqual(
            sum(item["suite_id"] == "legacy_operational_scripts" for item in CORE.SUITE_DEFINITIONS),
            1,
        )

    def test_runtime_source_uses_bundled_host_python_with_real_numpy_behavior_child(self):
        records = [
            item for item in CORE.EXECUTION_DEFINITIONS
            if item["suite_id"] == "runtime_source_contract"
        ]
        self.assertEqual(records, [{
            "record_id": "runtime_source_windows_bundled",
            "suite_id": "runtime_source_contract",
            "platform": "WINDOWS_HOST",
            "interpreter_role": "bundled_host_python",
            "selection": "ALL",
        }])

        watched_modules = (
            "json", "hashlib", "stat", "dataclasses", "pathlib", "typing",
        )
        readiness_relative = (
            "src/limo_cleanup_perception/limo_cleanup_perception/"
            "perception_readiness.py"
        )
        readiness_source = _source_text(readiness_relative)
        readiness_tree = ast.parse(
            readiness_source, filename=readiness_relative,
        )
        self.assertEqual(
            watched_modules,
            ast.literal_eval(_top_level_assignment(
                readiness_tree, "_WATCHED_STDLIB_MODULES",
            ).value),
        )
        decision_functions = [
            node for node in readiness_tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "_bootstrap_stdlib_can_skip_finder"
        ]
        self.assertEqual(1, len(decision_functions))
        decision_module = ast.Module(
            body=[deepcopy(decision_functions[0])], type_ignores=[],
        )
        ast.fix_missing_locations(decision_module)
        decision_namespace = {
            "_STDLIB_ATTESTOR_IDENTITY_VALID": True,
            "_STDLIB_ATTESTOR_SHA256": "a" * 64,
            "_WATCHED_STDLIB_MODULES": watched_modules,
        }
        exec(compile(
            decision_module, readiness_relative, "exec", dont_inherit=True,
        ), decision_namespace)
        can_skip_finder = decision_namespace[
            "_bootstrap_stdlib_can_skip_finder"
        ]
        trusted = tuple({
            "module": name,
            "present": True,
            "provenance_valid": True,
            "attestor_source_sha256": "a" * 64,
        } for name in watched_modules)
        meta_path_object = sys.meta_path
        meta_path_entries = tuple(sys.meta_path)
        self.assertTrue(can_skip_finder(trusted, ()))
        self.assertIs(meta_path_object, sys.meta_path)
        self.assertEqual(meta_path_entries, tuple(sys.meta_path))
        for index, name in enumerate(watched_modules):
            with self.subTest(missing_preloaded_stdlib=name):
                missing = deepcopy(trusted)
                missing[index]["present"] = False
                self.assertFalse(can_skip_finder(tuple(missing), ()))
                self.assertFalse(can_skip_finder(
                    trusted[:index] + trusted[index + 1:], (),
                ))
        malformed_provenance = (
            trusted + (deepcopy(trusted[-1]),),
            tuple(reversed(trusted)),
            tuple(
                dict(item, provenance_valid=False)
                if index == 0 else dict(item)
                for index, item in enumerate(trusted)
            ),
            tuple(
                dict(item, attestor_source_sha256="b" * 64)
                if index == 0 else dict(item)
                for index, item in enumerate(trusted)
            ),
            None,
        )
        for index, provenance in enumerate(malformed_provenance):
            with self.subTest(malformed_provenance=index):
                self.assertFalse(can_skip_finder(provenance, ()))
        self.assertFalse(can_skip_finder(
            trusted,
            ("ros1_field_model_loader_ambient_stdlib_identity_mismatch:typing",),
        ))
        decision_namespace["_STDLIB_ATTESTOR_IDENTITY_VALID"] = False
        self.assertFalse(can_skip_finder(trusted, ()))

        self.assertIn(
            "_use_watched_import_finder = not "
            "_BOOTSTRAP_STDLIB_SKIP_FINDER",
            readiness_source,
        )
        self.assertIn(
            "if _use_watched_import_finder:\n"
            "        _watched_import_token = "
            "_begin_canonical_watched_imports()",
            readiness_source,
        )
        self.assertIn(
            "_use_watched_import_finder\n"
            "            and not _end_canonical_watched_imports",
            readiness_source,
        )
        self.assertEqual(
            1, readiness_source.count("_begin_canonical_watched_imports()"),
        )
        self.assertEqual(
            1,
            readiness_source.count(
                "_end_canonical_watched_imports(_watched_import_token)"
            ),
        )

        pytest_source = _source_text(PYTEST_V2_RELATIVE_PATH)
        pytest_tree = ast.parse(
            pytest_source, filename=PYTEST_V2_RELATIVE_PATH,
        )
        preload_functions = [
            node for node in pytest_tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "_preload_guard_safe_stdlib"
        ]
        self.assertEqual(1, len(preload_functions))
        preload_imports = [
            alias.name
            for node in ast.walk(preload_functions[0])
            if isinstance(node, ast.Import)
            for alias in node.names
        ]
        self.assertEqual(["dataclasses", "typing"], preload_imports)
        preload_source = ast.get_source_segment(
            pytest_source, preload_functions[0],
        )
        self.assertIsNotNone(preload_source)
        for token in (
            "sys.flags.isolated", "sys.flags.no_site",
            "sys.dont_write_bytecode", "_subprocess_environment()",
            "_resolve_workspace_exact", "_current_runner_execution_binding",
            "sys.path is not path_object", "_meta_path_matches",
            "not _is_relative_to(resolved_origin, stdlib_root)",
            "_is_relative_to(resolved_origin, workspace)",
        ):
            self.assertIn(token, preload_source)
        self.assertNotIn("limo_cleanup_perception", preload_source)
        self.assertNotIn("SourceFileLoader", preload_source)

        main_function = next(
            node for node in pytest_tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "main"
        )
        main_source = ast.get_source_segment(pytest_source, main_function)
        self.assertIsNotNone(main_source)
        capability_index = main_source.index(
            "_child_capability_preflight()"
        )
        preload_index = main_source.index(
            "_preload_guard_safe_stdlib(options.workspace)"
        )
        report_index = main_source.index("_single_file_report(options)")
        self.assertLess(capability_index, preload_index)
        self.assertLess(preload_index, report_index)
        self.assertEqual(
            1,
            pytest_source.count(
                "_preload_guard_safe_stdlib(options.workspace)"
            ),
        )

        audit_hook = next(
            node for node in ast.walk(pytest_tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_audit_hook"
        )
        audit_source = ast.get_source_segment(pytest_source, audit_hook)
        self.assertIsNotNone(audit_source)
        self.assertIn("not _meta_path_matches", audit_source)
        self.assertIn(
            "raise RuntimeError('sys_meta_path_changed_during_execution')",
            audit_source,
        )
        for forbidden in (
            "dataclasses", "typing", "CanonicalWatchedFinder",
            "allowlist", "allowed_finder",
        ):
            self.assertNotIn(forbidden, audit_source)

    def test_wrapper_production_anchor_is_self_consistent_before_and_after_freeze(self):
        self._assert_authority_record_binding_fail_closed()
        wrapper = self._bound_generation_wrapper()
        if wrapper is None:
            return
        configured_anchor = wrapper.PRODUCTION_INDEX_TRUST_ANCHOR
        try:
            wrapper.PRODUCTION_INDEX_TRUST_ANCHOR = None
            result = wrapper.load_and_resolve_current_authority(ROOT)
            self.assertFalse(result["validated_pass"])
            self.assertFalse(result["production_anchor_configured"])
            self.assertIn(
                "formal_authority_v7_production_anchor_not_configured",
                result["failures"],
            )
        finally:
            wrapper.PRODUCTION_INDEX_TRUST_ANCHOR = configured_anchor

        if configured_anchor is None:
            return
        self.assertEqual(
            set(configured_anchor), {"path", "size_bytes", "sha256"},
        )
        self.assertEqual(configured_anchor["path"], CORE.INDEX_RELATIVE_PATH)
        index_path = ROOT.joinpath(*configured_anchor["path"].split("/"))
        raw = index_path.read_bytes()
        self.assertEqual(configured_anchor["size_bytes"], len(raw))
        self.assertEqual(
            configured_anchor["sha256"], hashlib.sha256(raw).hexdigest(),
        )
        result = wrapper.load_and_resolve_current_authority(ROOT)
        self.assertTrue(result["validated_pass"])
        self.assertTrue(
            result["accepted_as_offline_release_selection_authority"]
        )
        self.assertFalse(result["accepted_by_formal_field_evidence_consumer"])
        self.assertFalse(result["delivery_ready"])
        self.assertFalse(result["authorizes_field_delivery"])
        self.assertIsNotNone(result["current_evidence"])

    def test_wrapper_configured_anchor_uses_exact_core_resolver_offline_only(self):
        wrapper = self._bound_generation_wrapper()
        if wrapper is None:
            return
        wrapper_fixture = self.root.joinpath(
            *CORE.GENERATION_WRAPPER_SOURCE_PATH.split("/")
        )
        wrapper_fixture.write_bytes(b"PRODUCTION_INDEX_TRUST_ANCHOR = None\n")
        before_anchor_bytes = self._validate()
        self.assertTrue(
            before_anchor_bytes["semantic_validated_pass"],
            before_anchor_bytes["failures"],
        )
        wrapper_fixture.write_bytes(
            b"PRODUCTION_INDEX_TRUST_ANCHOR = {'sha256': 'frozen'}\n"
        )
        after_anchor_bytes = self._validate()
        self.assertTrue(
            after_anchor_bytes["semantic_validated_pass"],
            after_anchor_bytes["failures"],
        )
        self.assertNotIn(
            CORE.GENERATION_WRAPPER_SOURCE_PATH,
            {item["path"] for item in self.source_roles},
        )
        index_identity = CORE.write_json_exclusive(
            self.root / self.policy.index_relative_path, self.payload,
            self.policy.index_relative_path,
        )
        original_loader = wrapper._load_exact_core
        original_anchor = wrapper.PRODUCTION_INDEX_TRUST_ANCHOR
        original_policy = CORE.PRODUCTION_POLICY
        try:
            CORE.PRODUCTION_POLICY = self.policy
            wrapper.PRODUCTION_INDEX_TRUST_ANCHOR = dict(index_identity)
            wrapper._load_exact_core = lambda workspace: (
                CORE,
                {
                    "path": wrapper.CORE_SOURCE_RELATIVE_PATH,
                    "size_bytes": 1,
                    "sha256": "a" * 64,
                },
                [],
            )
            result = wrapper.load_and_resolve_current_authority(self.root)
        finally:
            wrapper._load_exact_core = original_loader
            wrapper.PRODUCTION_INDEX_TRUST_ANCHOR = original_anchor
            CORE.PRODUCTION_POLICY = original_policy
        self.assertTrue(result["production_anchor_configured"])
        self.assertTrue(result["validated_pass"], result["failures"])
        self.assertTrue(
            result["accepted_as_offline_release_selection_authority"]
        )
        self.assertFalse(result["accepted_by_formal_field_evidence_consumer"])
        self.assertFalse(result["delivery_ready"])
        self.assertFalse(result["authorizes_field_delivery"])
        self.assertIsNotNone(result["current_evidence"])

    def test_wrapper_core_source_anchor_is_exact_and_fails_closed_on_drift(self):
        wrapper = self._bound_generation_wrapper()
        if wrapper is None:
            return
        core_path = ROOT / wrapper.CORE_SOURCE_RELATIVE_PATH
        raw = core_path.read_bytes()
        expected = {
            "path": wrapper.CORE_SOURCE_RELATIVE_PATH,
            "size_bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
        self.assertEqual(wrapper.CORE_SOURCE_TRUST_ANCHOR, expected)
        status = GENERATOR._wrapper_core_anchor_status(ROOT, expected)
        self.assertTrue(status["matches_live_core"])
        self.assertEqual(status["configured_core_anchor"], expected)
        core, identity, failures = wrapper._load_exact_core(ROOT)
        self.assertIsNotNone(core)
        self.assertEqual(identity, expected)
        self.assertEqual(failures, [])

        original_anchor = wrapper.CORE_SOURCE_TRUST_ANCHOR
        try:
            cases = (
                (None, "formal_authority_v7_core_source_anchor_not_configured"),
                ({
                    "path": "audit_tools/formal_admission_evidence_authority_v5_core.py",
                    "size_bytes": expected["size_bytes"],
                    "sha256": expected["sha256"],
                }, "formal_authority_v7_core_source_anchor_path_mismatch"),
                ({
                    "path": expected["path"],
                    "size_bytes": expected["size_bytes"],
                    "sha256": "0" * 64,
                }, "formal_authority_v7_core_source_sha256_mismatch"),
                ({
                    "path": expected["path"],
                    "size_bytes": expected["size_bytes"] - 1,
                    "sha256": expected["sha256"],
                }, "formal_authority_v7_core_source_size_bytes_mismatch"),
            )
            for anchor, code in cases:
                with self.subTest(code=code):
                    wrapper.CORE_SOURCE_TRUST_ANCHOR = anchor
                    rejected, observed, rejected_failures = (
                        wrapper._load_exact_core(ROOT))
                    self.assertIsNone(rejected)
                    if anchor is None or code.endswith("path_mismatch"):
                        self.assertEqual(observed, {})
                    else:
                        self.assertEqual(observed, expected)
                    self.assertEqual(rejected_failures, [code])

            with tempfile.TemporaryDirectory() as directory:
                copy_root = Path(directory)
                copy_path = copy_root / wrapper.CORE_SOURCE_RELATIVE_PATH
                copy_path.parent.mkdir(parents=True)
                copy_path.write_bytes(raw + b"\n# source drift\n")
                wrapper.CORE_SOURCE_TRUST_ANCHOR = expected
                rejected, observed, rejected_failures = (
                    wrapper._load_exact_core(copy_root))
                self.assertIsNone(rejected)
                self.assertEqual(observed["path"], expected["path"])
                self.assertIn(
                    "formal_authority_v7_core_source_size_bytes_mismatch",
                    rejected_failures,
                )
                self.assertIn(
                    "formal_authority_v7_core_source_sha256_mismatch",
                    rejected_failures,
                )
        finally:
            wrapper.CORE_SOURCE_TRUST_ANCHOR = original_anchor

    def test_old_resolver_cannot_select_the_new_generation_path(self):
        old_wrapper_module = (
            "audit_tools.formal_admission_evidence_authority_v5"
        )
        old_wrapper_path = (
            "audit_tools/formal_admission_evidence_authority_v5.py"
        )
        self.assertNotIn(old_wrapper_module, sys.modules)
        self.assertNotIn(
            old_wrapper_path,
            {
                path
                for unused_role, unused_root_role, path
                in CORE.REQUIRED_SOURCE_ROLE_DEFINITIONS
            },
        )
        candidate = {
            "path": CORE.INDEX_RELATIVE_PATH,
            "size_bytes": 1,
            "sha256": "0" * 64,
        }
        predecessor_anchor = {
            key: CORE.PREDECESSOR_INDEX_IDENTITY[key]
            for key in ("path", "size_bytes", "sha256")
        }
        self.assertNotEqual(candidate, predecessor_anchor)
        self.assertNotEqual(
            candidate["path"], predecessor_anchor["path"],
        )
        self.assertNotEqual(
            CORE.GENERATION_ID,
            CORE.PREDECESSOR_INDEX_IDENTITY["generation_id"],
        )

    def test_old_current_authority_is_stale_against_live_source(self):
        predecessor_path = (
            ROOT / CORE.PREDECESSOR_CANONICAL_IDENTITY["path"]
        )
        predecessor_raw = predecessor_path.read_bytes()
        self.assertEqual(
            len(predecessor_raw),
            CORE.PREDECESSOR_CANONICAL_IDENTITY["size_bytes"],
        )
        self.assertEqual(
            hashlib.sha256(predecessor_raw).hexdigest(),
            CORE.PREDECESSOR_CANONICAL_IDENTITY["sha256"],
        )
        predecessor = CORE._strict_json_bytes(predecessor_raw)
        self.assertEqual(101, predecessor["source_role_count"])
        readiness_path = (
            "src/limo_cleanup_perception/limo_cleanup_perception/"
            "perception_readiness.py"
        )
        predecessor_readiness = next(
            item for item in predecessor["source_roles"]
            if item["root_role"] == "workspace"
            and item["path"] == readiness_path
        )
        live_readiness = CORE.source_artifact_identity(
            ROOT, "workspace", readiness_path,
        )
        self.assertEqual(
            {
                key: predecessor_readiness[key]
                for key in ("root_role", "path")
            },
            {
                key: live_readiness[key]
                for key in ("root_role", "path")
            },
        )
        self.assertNotEqual(
            {
                key: predecessor_readiness[key]
                for key in ("size_bytes", "sha256")
            },
            {
                key: live_readiness[key]
                for key in ("size_bytes", "sha256")
            },
        )

    def test_system_orchestrator_hardlink_is_descriptor_bound_not_symlink_accepted(self):
        target = self.root / "system-orchestrator.exe"
        alias = self.root / "system-orchestrator-hardlink.exe"
        target.write_bytes(b"system executable fixture\n")
        alias.hardlink_to(target)
        identity = GENERATOR._absolute_regular_identity(alias)
        self.assertEqual(identity["path"], str(alias))
        self.assertGreaterEqual(identity["hardlink_count"], 2)
        self.assertEqual(
            identity["sha256"], hashlib.sha256(alias.read_bytes()).hexdigest(),
        )
        link = self.root / "system-orchestrator-symlink.exe"
        try:
            link.symlink_to(target)
        except OSError:
            return
        with self.assertRaises(GENERATOR.GenerationError):
            GENERATOR._absolute_regular_identity(link)

    @staticmethod
    def _runner_source_pair():
        return (
            _source_text(UNITTEST_V2_RELATIVE_PATH),
            _source_text(PYTEST_V2_RELATIVE_PATH),
        )

    def _assert_runner_tokens(self, *tokens):
        for source in self._runner_source_pair():
            for token in tokens:
                self.assertIn(token, source)

    @staticmethod
    def _broker_events_by_prefix(protocol):
        result = {}
        for prefix, payload in protocol["events"]:
            result.setdefault(prefix, []).append(payload)
        return result

    def test_broker_identity_only_same_fd_hash_accepts_exact_eighteen_frozen_pyc(self):
        from audit_tools import run_pytest_style_tests_v2 as pytest_runner_v2

        pytest_v2_source = _source_text(PYTEST_V2_RELATIVE_PATH)
        self.assertNotIn("def _legacy_main", pytest_v2_source)
        self.assertNotIn("OFFLINE_PYTEST_STYLE", pytest_v2_source)
        self.assertFalse(hasattr(pytest_runner_v2, "_legacy_main"))
        legacy_stdout = io.StringIO()
        legacy_stderr = io.StringIO()
        with mock.patch.object(sys, "stdout", legacy_stdout), \
                mock.patch.object(sys, "stderr", legacy_stderr):
            self.assertEqual(2, pytest_runner_v2.main([]))
        legacy_lines = legacy_stdout.getvalue().splitlines()
        self.assertEqual(1, len(legacy_lines), legacy_stdout.getvalue())
        self.assertTrue(legacy_lines[0].startswith(
            pytest_runner_v2.SINGLE_FILE_MARKER))
        legacy_payload = json.loads(legacy_lines[0][
            len(pytest_runner_v2.SINGLE_FILE_MARKER):
        ])
        self.assertEqual(pytest_runner_v2.SCHEMA_VERSION,
                         legacy_payload["schema_version"])
        self.assertEqual(2, legacy_payload["exit"])
        self.assertEqual("FAIL", legacy_payload["result"])
        self.assertEqual(
            ["runner_argv_single_file_count_invalid"],
            legacy_payload["failures"],
        )
        self.assertNotIn("collected", legacy_payload)
        self.assertNotIn("OFFLINE_PYTEST_STYLE", legacy_stdout.getvalue())

        positional_stdout = io.StringIO()
        positional_stderr = io.StringIO()
        with mock.patch.object(sys, "stdout", positional_stdout), \
                mock.patch.object(sys, "stderr", positional_stderr):
            self.assertEqual(2, pytest_runner_v2.main([
                str(ROOT / "legacy_pytest_path.py"),
            ]))
        positional_lines = positional_stdout.getvalue().splitlines()
        self.assertEqual(
            1, len(positional_lines), positional_stdout.getvalue(),
        )
        self.assertTrue(positional_lines[0].startswith(
            pytest_runner_v2.SINGLE_FILE_MARKER))
        positional_payload = json.loads(positional_lines[0][
            len(pytest_runner_v2.SINGLE_FILE_MARKER):
        ])
        self.assertEqual(2, positional_payload["exit"])
        self.assertEqual("FAIL", positional_payload["result"])
        self.assertEqual(
            ["runner_argv_positional_forbidden"],
            positional_payload["failures"],
        )
        self.assertNotIn("collected", positional_payload)
        self.assertNotIn(
            "OFFLINE_PYTEST_STYLE", positional_stdout.getvalue(),
        )

        protocol = _cached_broker_protocol()
        self.assertEqual(protocol["returncode"], 0)
        self.assertEqual(protocol["stderr"], b"")
        events = self._broker_events_by_prefix(protocol)
        self.assertEqual(len(events["OFFLINE_WORKSPACE_PYC_BROKER_READY "]), 1)
        self.assertEqual(
            len(events["OFFLINE_WORKSPACE_PYC_BROKER_CHECKPOINT "]), 2,
        )
        self.assertEqual(len(events["OFFLINE_WORKSPACE_PYC_BROKER_FINAL "]), 1)
        ready = events["OFFLINE_WORKSPACE_PYC_BROKER_READY "][0]
        final = events["OFFLINE_WORKSPACE_PYC_BROKER_FINAL "][0]
        self.assertEqual(ready["descriptor_count"], 18)
        self.assertFalse(ready["descriptors_closed"])
        self.assertEqual(len(ready["identities"]), 18)
        for actual, expected in zip(
            ready["identities"], protocol["inventory"],
        ):
            self.assertEqual(
                {key: actual[key] for key in (
                    "path", "size_bytes", "sha256",
                )},
                expected,
            )
            self.assertEqual(set(actual), {
                "path", "size_bytes", "sha256", "regular_file",
                "non_linklike", "nlink", "fd_inheritable",
            })
            self.assertTrue(actual["regular_file"])
            self.assertTrue(actual["non_linklike"])
            self.assertEqual(actual["nlink"], 1)
            self.assertFalse(actual["fd_inheritable"])
        self.assertEqual(final["descriptor_count"], 0)
        self.assertTrue(final["descriptors_closed"])
        self.assertTrue(final["nonce_invalidated"])
        verified = _verify_broker_protocol(protocol)
        self.assertTrue(verified["validated_pass"], verified["failures"])
        self.assertEqual(verified["inventory_count"], 18)
        projection = _run_broker_internal_case(
            "windows_cross_source_ctime_contract",
        )["value"]
        self.assertTrue(projection["windows_cross_ctime_equal"])
        self.assertFalse(projection["same_source_ctime_equal"])
        self.assertFalse(projection["posix_cross_ctime_equal"])
        self.assertTrue(all(projection["other_mismatches_rejected"]))
        self.assertTrue(projection["permission_only_mode_normalized"])
        self.assertTrue(projection["posix_permission_mismatch_rejected"])
        self.assertTrue(projection["file_type_mismatch_rejected"])
        for relative in (UNITTEST_V2_RELATIVE_PATH, PYTEST_V2_RELATIVE_PATH):
            with self.subTest(runner_projection=relative):
                runner_projection = _runner_projection_contract(relative)
                windows = runner_projection["windows"]
                self.assertTrue(windows["cross_ctime_equal"])
                self.assertFalse(windows["same_side_ctime_equal"])
                self.assertTrue(windows["cross_permission_equal"])
                self.assertTrue(windows["file_type_mismatch_rejected"])
                self.assertTrue(all(
                    windows["other_mismatches_rejected"].values()
                ))
                posix = runner_projection["posix"]
                self.assertFalse(posix["cross_ctime_equal"])
                self.assertFalse(posix["same_side_ctime_equal"])
                self.assertFalse(posix["cross_permission_equal"])
                self.assertTrue(posix["file_type_mismatch_rejected"])
                self.assertTrue(all(
                    posix["other_mismatches_rejected"].values()
                ))
        observer_bootstraps = (
            _literal_assignment(
                GENERATOR.CORE_RELATIVE_PATH,
                "PRODUCTION_WRAPPER_BOOTSTRAP",
            ),
            _literal_assignment(
                UNITTEST_V2_RELATIVE_PATH, "_WRAPPER_OBSERVER_BOOTSTRAP",
            ),
            _literal_assignment(
                PYTEST_V2_RELATIVE_PATH, "_WRAPPER_OBSERVER_BOOTSTRAP",
            ),
        )
        self.assertEqual(observer_bootstraps[0], observer_bootstraps[1])
        self.assertEqual(observer_bootstraps[0], observer_bootstraps[2])
        self.assertIn("same(before)!=same(after)", observer_bootstraps[0])
        self.assertIn("cross(before)!=cross(opened_before)", observer_bootstraps[0])
        self.assertIn("cross(opened_after)!=cross(after)", observer_bootstraps[0])
        self.assertIn("sys.stdout.buffer.write", observer_bootstraps[0])
        for relative in (
            CORE.GENERATION_WRAPPER_SOURCE_PATH,
            GENERATOR.CORE_RELATIVE_PATH,
            (
                "audit_tools/"
                "generate_ros1_atomic_cli_field_producer_pyc_identity_gate_"
                "blocked_offline_evidence_v2.py"
            ),
        ):
            with self.subTest(host_projection=relative):
                host_projection = _runner_projection_contract(
                    relative,
                    same_name="_same_side_stat_projection",
                    cross_name="_cross_source_stat_projection",
                )
                windows = host_projection["windows"]
                self.assertTrue(windows["cross_ctime_equal"])
                self.assertFalse(windows["same_side_ctime_equal"])
                self.assertTrue(windows["cross_permission_equal"])
                self.assertTrue(windows["file_type_mismatch_rejected"])
                self.assertTrue(all(
                    windows["other_mismatches_rejected"].values()
                ))
                posix = host_projection["posix"]
                self.assertFalse(posix["cross_ctime_equal"])
                self.assertFalse(posix["same_side_ctime_equal"])
                self.assertFalse(posix["cross_permission_equal"])
                self.assertTrue(posix["file_type_mismatch_rejected"])
                self.assertTrue(all(
                    posix["other_mismatches_rejected"].values()
                ))

    def test_audit_hook_replacement_or_removal_is_rejected(self):
        self._assert_runner_tokens(
            "sys.addaudithook", "workspace_pyc_audit_hook_active",
            "workspace_pyc_audit_hook_install_failed",
        )
        for source in self._runner_source_pair():
            self.assertGreaterEqual(source.count("_audit_hook"), 4)
            self.assertIn("workspace_loader_guard_restored", source)

    def test_broker_never_exposes_raw_bytes_fd_token_or_secret(self):
        protocol = _cached_broker_protocol()
        self.assertNotIn(protocol["nonce"].encode("ascii"), protocol["stdout"])
        for unused_prefix, event in protocol["events"]:
            self.assertFalse(event.get("raw_bytes_exported"))
            self.assertFalse(event.get("file_descriptors_exported"))
            self.assertNotIn("nonce", event)
            self.assertNotIn("fd", event)
            self.assertNotIn("token", event)
            self.assertNotIn("secret", event)
            self.assertNotIn("raw_bytes", event)

    def test_broker_preopens_exact_inventory_before_any_workspace_import(self):
        broker = _source_text(PYC_BROKER_RELATIVE_PATH)
        self.assertNotIn("import audit_tools", broker)
        self.assertIn("EXPECTED_INVENTORY_COUNT = 18", broker)
        self.assertLess(
            broker.index("entries.append(_open_entry"),
            broker.index("_emit(READY_MARKER"),
        )
        for source in self._runner_source_pair():
            supervisor = source[source.index("def _supervisor_report"):]
            self.assertLess(
                supervisor.index("BROKER_READY_MARKER"),
                supervisor.index("_observe_production_wrapper"),
            )
            self.assertLess(
                supervisor.index("_observe_production_wrapper"),
                supervisor.index("_run_test_child"),
            )

    def test_broker_process_python_argv_environment_and_cwd_are_exact(self):
        broker = _source_text(PYC_BROKER_RELATIVE_PATH)
        self.assertIn("len(raw) != 6", broker)
        self.assertIn('["--mode", "hold-open-v1"]', broker)
        self.assertIn("Path.cwd().resolve(strict=True) != resolved", broker)
        self.assertLess(
            broker.index("_validate_process_contract()"),
            broker.index("_parse_argv(argv)"),
        )
        self.assertLess(
            broker.index("_validate_process_contract()"),
            broker.index("_validate_execution_binding(workspace)"),
        )

        positive = _run_broker_protocol()
        self.assertEqual(positive["returncode"], 0)
        self.assertEqual(positive["stderr"], b"")
        self.assertEqual(
            positive["argv"][1:6],
            ["-I", "-S", "-B", "-c", CORE.EXECUTION_COMPONENT_BOOTSTRAP],
        )
        self.assertNotIn(
            str(ROOT / PYC_BROKER_RELATIVE_PATH), positive["argv"][1:5],
        )

        broker_identity = positive["broker_identity"]
        record_id = "successor_authority_broker_contract_test"
        bootstrap_argv = [
            sys.executable, "-I", "-S", "-B", "-c",
            CORE.EXECUTION_COMPONENT_BOOTSTRAP, str(ROOT),
            PYC_BROKER_RELATIVE_PATH, str(broker_identity["size_bytes"]),
            broker_identity["sha256"], "broker",
            CORE.EXECUTION_COMPONENT_BOOTSTRAP_SCHEMA,
            CORE.EXECUTION_COMPONENT_BOOTSTRAP_SHA256,
            "--mode", "hold-open-v1", "--workspace", str(ROOT),
            "--record-id", record_id,
        ]

        def run_case(argv, *, environment=None, cwd=ROOT):
            return subprocess.run(
                argv, cwd=str(cwd),
                env=(
                    _isolated_local_environment()
                    if environment is None else environment
                ),
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, timeout=30, check=False,
            )

        def broker_failure_code(completed):
            prefix = b"OFFLINE_WORKSPACE_PYC_BROKER_ERROR "
            lines = completed.stdout.splitlines()
            self.assertEqual(1, len(lines), completed.stdout)
            self.assertTrue(lines[0].startswith(prefix), completed.stdout)
            return json.loads(lines[0][len(prefix):])["failure_code"]

        direct_live_path = [
            sys.executable, "-I", "-S", "-B",
            str(ROOT / PYC_BROKER_RELATIVE_PATH),
            "--mode", "hold-open-v1", "--workspace", str(ROOT),
            "--record-id", record_id,
        ]
        direct = run_case(direct_live_path)
        self.assertEqual(2, direct.returncode)
        self.assertEqual(b"", direct.stderr)
        self.assertEqual(
            "pyc_broker_execution_binding_missing",
            broker_failure_code(direct),
        )

        wrong_argv = run_case(bootstrap_argv[:-2])
        self.assertEqual(2, wrong_argv.returncode)
        self.assertEqual(b"", wrong_argv.stderr)
        self.assertEqual(
            "pyc_broker_record_scope_invalid",
            broker_failure_code(wrong_argv),
        )
        wrong_cwd = run_case(bootstrap_argv, cwd=ROOT.parent)
        self.assertEqual(2, wrong_cwd.returncode)
        self.assertEqual(b"", wrong_cwd.stderr)
        self.assertEqual(
            "pyc_broker_cwd_invalid", broker_failure_code(wrong_cwd),
        )

        forbidden_keys = _literal_assignment(
            PYC_BROKER_RELATIVE_PATH, "_FORBIDDEN_ENVIRONMENT_KEYS",
        )
        self.assertEqual(forbidden_keys, (
            "PYTHONHOME", "PYTHONINSPECT", "PYTHONPATH", "PYTHONSTARTUP",
            "PYTHONUSERBASE", "LD_PRELOAD", "LD_LIBRARY_PATH",
            "ROS_PACKAGE_PATH", "ROS_MASTER_URI", "WSLENV",
            "LIMO_PYC_BROKER_FD", "LIMO_PYC_BROKER_TOKEN",
            "LIMO_PYC_BROKER_NONCE",
        ))
        for key in forbidden_keys:
            with self.subTest(forbidden_environment=key):
                environment = _isolated_local_environment()
                environment[key] = (
                    "/definitely/not/a/preload/library.so"
                    if key == "LD_PRELOAD" else "FORBIDDEN"
                )
                polluted = run_case(
                    bootstrap_argv, environment=environment,
                )
                self.assertEqual(2, polluted.returncode)
                self.assertEqual(
                    "pyc_broker_process_contract_invalid",
                    broker_failure_code(polluted),
                )

        binding_cases = {
            "execution_binding_missing": (
                "pyc_broker_execution_binding_missing"),
            "execution_binding_kind": (
                "pyc_broker_execution_binding_kind_invalid"),
            "execution_binding_path": (
                "pyc_broker_execution_binding_path_invalid"),
            "execution_binding_sha": (
                "pyc_broker_execution_binding_identity_mismatch"),
            "execution_binding_bootstrap": (
                "pyc_broker_execution_binding_bootstrap_invalid"),
        }
        for case, expected_code in binding_cases.items():
            with self.subTest(binding_case=case):
                self.assertEqual(
                    expected_code, _run_broker_internal_case(case)["code"],
                )

    def test_broker_result_requires_parent_recompute_and_exact_marker_schema(self):
        protocol = _cached_broker_protocol()
        verified = _verify_broker_protocol(protocol)
        self.assertTrue(verified["validated_pass"])
        expected_binding = {
            "schema_version": CORE.EXECUTION_COMPONENT_BOOTSTRAP_SCHEMA,
            "component_kind": "broker",
            "path": protocol["broker_identity"]["path"],
            "size_bytes": protocol["broker_identity"]["size_bytes"],
            "sha256": protocol["broker_identity"]["sha256"],
            "bootstrap_sha256": CORE.EXECUTION_COMPONENT_BOOTSTRAP_SHA256,
        }
        for unused_prefix, payload in protocol["events"]:
            self.assertEqual(
                expected_binding, payload["broker_execution_binding"],
            )
        self.assertEqual(
            expected_binding, verified["broker_execution_binding"],
        )
        tampered = deepcopy(protocol)
        for index, (prefix, payload) in enumerate(tampered["events"]):
            if prefix == "OFFLINE_WORKSPACE_PYC_BROKER_READY ":
                payload["hmac_sha256"] = "0" * 64
                tampered["events"][index] = (prefix, payload)
                break
        rejected = _verify_broker_protocol(tampered)
        self.assertFalse(rejected["validated_pass"])
        self.assertIn("pyc_verifier_nonce_digest_mismatch", rejected["failures"])

    def test_custom_meta_path_loader_workspace_pyc_is_rejected(self):
        self._assert_runner_tokens(
            "sys.meta_path", "workspace_loader_guard_restored",
            "sys_meta_path_changed_during_execution",
        )

    def test_direct_workspace_pyc_open_is_rejected(self):
        self._assert_runner_tokens(
            "workspace_bytecode_open_blocked", "workspace_pyc_bytes_read",
        )

    def test_hardlink_and_inode_alias_workspace_pyc_identity_are_rejected(self):
        result = _run_broker_internal_case("hardlink")
        self.assertEqual(result["code"], "pyc_broker_file_hardlink_rejected")
        self._assert_runner_tokens("workspace_bytecode_hardlink_rejected")

    def test_hash_based_workspace_pyc_execution_is_rejected(self):
        self._assert_runner_tokens(
            "SOURCE_ONLY_REJECT_WORKSPACE_PYC_V2", "== '.pyc'",
            "workspace_bytecode_open_blocked",
        )

    def test_identity_capability_cannot_be_forged(self):
        protocol = _cached_broker_protocol()
        forged = deepcopy(protocol)
        for unused_index, (prefix, payload) in enumerate(forged["events"]):
            if prefix == "OFFLINE_WORKSPACE_PYC_BROKER_CHECKPOINT ":
                payload["inventory_sha256"] = "f" * 64
                break
        result = _verify_broker_protocol(forged)
        self.assertFalse(result["validated_pass"])
        self.assertIn("pyc_verifier_nonce_digest_mismatch", result["failures"])

    def test_identity_capability_cannot_be_reused_after_scope_exit_or_early_close(self):
        reused = _run_broker_internal_case("reuse")
        self.assertEqual(
            reused["code"], "pyc_broker_session_reuse_after_finalize",
        )
        closed = _run_broker_internal_case("closed_fd")
        self.assertEqual(
            closed["code"], "pyc_broker_fd_closed_before_finalize",
        )

    def test_identity_capability_is_absent_from_child_fd_env_argv_and_import_state(self):
        self._assert_runner_tokens(
            "{'close_fds': True}", "['pass_fds'] = ()",
            "'broker_argv_fields': []", "'broker_environment_fields': []",
            "'broker_fds': []", "'broker_modules_in_sys_modules': []",
        )
        for source in self._runner_source_pair():
            child = source[source.index("def _run_test_child"):]
            child_argv = child[:child.index("def ", 5)]
            self.assertNotIn("nonce", child_argv.casefold())

    def test_identity_capability_is_absent_from_globals_closure_frames_gc_and_introspection(self):
        self._assert_runner_tokens(
            "'broker_secrets': []", "'broker_tokens': []",
            "pyc_test_child_capability_surface_nonempty",
        )
        for source in self._runner_source_pair():
            self.assertNotIn("LIMO_PYC_BROKER_NONCE", source)
            self.assertNotIn("LIMO_PYC_BROKER_TOKEN", source)
            self.assertNotIn("LIMO_PYC_BROKER_FD", source)

    def test_identity_capability_rejects_duplicate_nested_and_cross_thread_use(self):
        expected = {
            "nested": "pyc_broker_session_nested_start_forbidden",
            "cross_thread": "pyc_broker_command_wrong_thread",
        }
        for case, code in expected.items():
            with self.subTest(case=case):
                self.assertEqual(_run_broker_internal_case(case)["code"], code)
        broker = _source_text(PYC_BROKER_RELATIVE_PATH)
        self.assertIn("pyc_broker_session_duplicate_start", broker)

    def test_in_place_rewrite_during_same_fd_hash_is_rejected(self):
        result = _run_broker_internal_case("rewrite_during_hash")
        self.assertEqual(result["code"], "pyc_broker_file_drift")
        for runner_relative in (UNITTEST_V2_RELATIVE_PATH, PYTEST_V2_RELATIVE_PATH):
            with self.subTest(runner=runner_relative):
                runner_result = _run_runner_binding_internal_case(
                    runner_relative, "rewrite_during_read",
                )
                self.assertIn(runner_result["code"], (
                    "execution_component_rewrite_replaced_while_reading",
                    "execution_component_rewrite_"
                    "opened_object_changed_while_reading",
                    "execution_component_rewrite_path_fd_changed_while_reading",
                ))

    def test_inventory_identity_drift_before_child_during_child_and_after_child_is_rejected(self):
        protocol = _cached_broker_protocol()
        for event_index in (0, 1, len(protocol["events"]) - 1):
            with self.subTest(event_index=event_index):
                tampered = deepcopy(protocol)
                unused_prefix, payload = tampered["events"][event_index]
                payload["identities"][0]["sha256"] = "0" * 64
                result = _verify_broker_protocol(tampered)
                self.assertFalse(result["validated_pass"])
                self.assertTrue(any(
                    code in result["failures"] for code in (
                        "pyc_verifier_checkpoint_drift",
                        "pyc_verifier_nonce_digest_mismatch",
                    )
                ))

    def test_inventory_missing_extra_duplicate_reordered_or_unknown_role_is_rejected(self):
        inventory = _broker_inventory()
        cases = {
            "missing": inventory[:-1],
            "extra": inventory + [dict(inventory[-1], path="extra.pyc")],
            "duplicate": inventory[:-1] + [dict(inventory[-2])],
            "reordered": list(reversed(inventory)),
        }
        for name, value in cases.items():
            with self.subTest(name=name):
                result = _run_broker_protocol(value)
                self.assertEqual(result["returncode"], 2)
                self.assertEqual(result["stderr"], b"")
                events = self._broker_events_by_prefix(result)
                self.assertEqual(
                    len(events["OFFLINE_WORKSPACE_PYC_BROKER_ERROR "]), 1,
                )
                self.assertTrue(events[
                    "OFFLINE_WORKSPACE_PYC_BROKER_ERROR "
                ][0]["failure_code"].startswith("pyc_broker_manifest_"))

    def test_loader_and_meta_path_replacement_is_rejected(self):
        self._assert_runner_tokens(
            "_meta_path_snapshot", "sys_meta_path_changed_during_execution",
            "workspace_loader_guard_restored",
        )

    def test_loader_get_data_workspace_pyc_is_rejected(self):
        self._assert_runner_tokens(
            "get_data", "workspace_bytecode_open_blocked",
        )

    def test_replacement_between_lstat_and_open_is_rejected(self):
        result = _run_broker_internal_case("replacement_before_open")
        self.assertEqual(
            result["code"], "pyc_broker_path_fd_identity_mismatch",
        )

    def test_replacement_during_same_fd_hash_is_rejected(self):
        result = _run_broker_internal_case("replacement_during_hash")
        self.assertIn(result["code"], (
            "pyc_broker_file_drift",
            "pyc_broker_path_fd_identity_mismatch",
            "pyc_broker_fd_closed_before_finalize",
        ))
        cases = {
            "raw_identity_mismatch": (
                "execution_component_aba_bound_identity_mismatch"),
            "bound_path_mismatch": (
                "runner_execution_component_bound_path_mismatch"),
            "replacement_before_open": (
                "execution_component_aba_changed_before_open"),
            "verifier_aba": (
                "pyc_verifier_load_bound_identity_mismatch"),
        }
        for runner_relative in (UNITTEST_V2_RELATIVE_PATH, PYTEST_V2_RELATIVE_PATH):
            for case, expected_code in cases.items():
                with self.subTest(runner=runner_relative, case=case):
                    runner_result = _run_runner_binding_internal_case(
                        runner_relative, case,
                    )
                    self.assertEqual(expected_code, runner_result["code"])
            positive = _run_runner_binding_internal_case(
                runner_relative, "verifier_positive",
            )
            self.assertIsNone(positive["code"])
            self.assertEqual(
                positive["value"]["size_bytes"],
                positive["value"]["identity"]["size_bytes"],
            )
            self.assertEqual(
                positive["value"]["sha256"],
                positive["value"]["identity"]["sha256"],
            )

    def test_source_file_loader_workspace_pyc_is_rejected(self):
        self._assert_runner_tokens(
            "SourceFileLoader", "workspace_bytecode_open_blocked",
        )

    def test_sourceless_file_loader_workspace_pyc_is_rejected(self):
        self._assert_runner_tokens(
            "SourcelessFileLoader", "workspace_bytecode_open_blocked",
        )

    def test_symlink_and_windows_reparse_workspace_pyc_identity_are_rejected(self):
        result = _run_broker_internal_case("windows_reparse_projection")
        self.assertTrue(result["value"])
        broker = _source_text(PYC_BROKER_RELATIVE_PATH)
        self.assertIn("pyc_broker_file_linklike", broker)
        self.assertIn("FILE_ATTRIBUTE_REPARSE_POINT", broker)

    def test_timestamp_workspace_pyc_execution_is_rejected(self):
        self._assert_runner_tokens(
            "SOURCE_ONLY_REJECT_WORKSPACE_PYC_V2", "workspace_bytecode_open_blocked",
            "workspace_pyc_attempts_blocked",
        )


if __name__ == "__main__":
    unittest.main()

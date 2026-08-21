"""Pure-local static safety audit for the arm and gripper source surface."""

import argparse
import ast
import hashlib
import json
import sys
from pathlib import Path


SCHEMA_ID = "limo.arm_gripper_local_static_audit"
SCHEMA_VERSION = 1

ROS_IMPORT_ROOTS = {"actionlib", "rclpy", "rosgraph", "roslib", "rospy"}
VENDOR_IMPORT_ROOTS = {"pymycobot", "serial"}
DYNAMIC_IMPORT_CALLS = {"__import__", "import_module"}
FILE_IO_OR_ENUMERATION_CALLS = {
    "glob",
    "listdir",
    "open",
    "rglob",
    "scandir",
    "walk",
}
TIMEOUT_THREAD_CALLS = {
    "Thread",
    "ThreadPoolExecutor",
    "ProcessPoolExecutor",
    "alarm",
    "setitimer",
}
REAL_BACKEND_CONSTRUCTORS = {
    "PymycobotArmBackend",
    "PymycobotGripperBackend",
}
ORDINARY_CORE_LOCKS = {"_lock", "_lifecycle_lock"}
EXTERNAL_CALL_HELPERS = {
    "_call_external",
    "_call_external_method",
    "_read_clock",
}
CONFLICT_MARKERS = tuple(character * 7 for character in "<=>")


def _relative(path, root):
    return path.resolve().relative_to(root.resolve()).as_posix()


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _dotted_name(node):
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return ""


def _call_name(node):
    if not isinstance(node, ast.Call):
        return ""
    dotted = _dotted_name(node.func)
    if dotted:
        return dotted
    if isinstance(node.func, ast.Name):
        return node.func.id
    return ""


def _import_roots(tree):
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def _with_lock_names(node):
    names = set()
    if not isinstance(node, (ast.With, ast.AsyncWith)):
        return names
    for item in node.items:
        dotted = _dotted_name(item.context_expr)
        if dotted.startswith("self."):
            names.add(dotted.split(".")[-1])
    return names


def _lock_scope_report(path, tree, kind):
    lock_blocks = 0
    violations = []
    for node in ast.walk(tree):
        lock_names = _with_lock_names(node)
        if not lock_names.intersection(ORDINARY_CORE_LOCKS):
            continue
        lock_blocks += 1
        for child in ast.walk(node):
            if not isinstance(child, ast.Call):
                continue
            name = _call_name(child)
            tail = name.split(".")[-1]
            violation = False
            reason = ""
            if name.startswith("self._backend."):
                violation = True
                reason = "direct backend call under ordinary core lock"
            elif tail in EXTERNAL_CALL_HELPERS:
                violation = True
                reason = "external-call helper under ordinary core lock"
            elif kind == "node" and name.startswith("self._core."):
                violation = True
                reason = "core operation under node lifecycle lock"
            if violation:
                violations.append({
                    "line": getattr(child, "lineno", None),
                    "call": name,
                    "reason": reason,
                })
    return {
        "path": path.as_posix(),
        "ordinary_lock_blocks": lock_blocks,
        "external_call_violations": violations,
    }


def _collect_scope(workspace):
    executor = workspace / "src" / "limo_cleanup_executor"
    interfaces = workspace / "src" / "limo_cleanup_interfaces"
    bringup = workspace / "src" / "limo_cleanup_bringup"
    docs = workspace / "docs"
    audit_tools = workspace / "audit_tools"

    files = set()
    for pattern in (
            "limo_cleanup_executor/*.py",
            "test/test_arm*.py",
            "test/test_gripper*.py",
            "launch/*.py",
            "config/*.json",
            "config/*.yaml"):
        files.update(path for path in executor.glob(pattern) if path.is_file())
    for name in ("package.xml", "setup.py", "setup.cfg"):
        path = executor / name
        if path.is_file():
            files.add(path)
    for directory in (interfaces / "action", interfaces / "msg", interfaces / "srv"):
        if directory.is_dir():
            files.update(path for path in directory.iterdir() if path.is_file())
    for name in ("CMakeLists.txt", "package.xml"):
        path = interfaces / name
        if path.is_file():
            files.add(path)
    for path in (
            bringup / "launch" / "gripper_control.launch.py",
            bringup / "config" / "gripper_safe.yaml",
            audit_tools / "run_pytest_style_tests.py",
            audit_tools / "run_unittest_file_tests.py",
            audit_tools / "arm_gripper_local_static_audit.py",
            audit_tools / "arm_gripper_local_evidence_aggregator.py",
            audit_tools / "arm_gripper_local_evidence_generator.py",
            audit_tools / "arm_gripper_local_v3_policy.json",
            audit_tools / "test_arm_gripper_local_evidence_aggregator.py",
            audit_tools / "test_arm_gripper_local_evidence_generator.py"):
        if path.is_file():
            files.add(path)
    for name in (
            "arm_gripper_field_acceptance_matrix.md",
            "arm_gripper_ros1_noetic_dry_run_checklist.md",
            "arm_motion_release_manifest.md",
            "arm_persistent_safety_latch.md",
            "final_gripper_release_input_checklist.md",
            "final_gripper_release_manifest.md",
            "gripper_control.md",
            "gripper_persistent_safety_latch.md",
            "v3_pick_place_acceptance.md"):
        path = docs / name
        if path.is_file():
            files.add(path)
    return tuple(sorted(files, key=lambda item: _relative(item, workspace)))


def audit(workspace):
    workspace = workspace.resolve()
    executor_source = workspace / "src" / "limo_cleanup_executor" / "limo_cleanup_executor"
    scoped_files = _collect_scope(workspace)
    python_files = tuple(path for path in scoped_files if path.suffix == ".py")

    ast_errors = []
    compile_errors = []
    trees = {}
    for path in python_files:
        relative = _relative(path, workspace)
        try:
            source = path.read_text(encoding="utf-8")
            trees[path] = ast.parse(
                source, filename=relative, feature_version=(3, 8))
        except Exception as error:
            ast_errors.append({
                "path": relative,
                "error": "{}: {}".format(type(error).__name__, error),
            })
            continue
        try:
            compile(source, relative, "exec")
        except Exception as error:
            compile_errors.append({
                "path": relative,
                "error": "{}: {}".format(type(error).__name__, error),
            })

    text_integrity = {
        "conflict_markers": [],
        "trailing_whitespace": [],
        "tab_lines": [],
        "missing_final_newline": [],
    }
    for path in scoped_files:
        relative = _relative(path, workspace)
        try:
            payload = path.read_bytes()
            text = payload.decode("utf-8")
        except (OSError, UnicodeError) as error:
            text_integrity["conflict_markers"].append({
                "path": relative,
                "line": None,
                "error": "unreadable UTF-8 text: {}".format(error),
            })
            continue
        if payload and not payload.endswith(b"\n"):
            text_integrity["missing_final_newline"].append(relative)
        for number, line in enumerate(text.splitlines(), 1):
            if any(marker in line for marker in CONFLICT_MARKERS):
                text_integrity["conflict_markers"].append({
                    "path": relative,
                    "line": number,
                })
            if line.rstrip(" \t") != line:
                text_integrity["trailing_whitespace"].append({
                    "path": relative,
                    "line": number,
                })
            if "\t" in line:
                text_integrity["tab_lines"].append({
                    "path": relative,
                    "line": number,
                })

    backend_paths = (
        executor_source / "arm_backends.py",
        executor_source / "gripper_backends.py",
    )
    runtime_entry_paths = (
        executor_source / "arm_backends.py",
        executor_source / "gripper_backends.py",
        executor_source / "arm_gateway_node.py",
        executor_source / "gripper_gateway_node.py",
        executor_source / "gripper_controller.py",
        workspace / "src" / "limo_cleanup_executor" / "launch" / "arm_gateway_dry_run.launch.py",
        workspace / "src" / "limo_cleanup_executor" / "launch" / "gripper_gateway_dry_run.launch.py",
        workspace / "src" / "limo_cleanup_executor" / "config" / "arm_gateway_dry_run.yaml",
        workspace / "src" / "limo_cleanup_executor" / "config" / "arm_gateway_safe.example.yaml",
        workspace / "src" / "limo_cleanup_executor" / "config" / "gripper_gateway_dry_run.yaml",
        workspace / "src" / "limo_cleanup_bringup" / "launch" / "gripper_control.launch.py",
        workspace / "src" / "limo_cleanup_bringup" / "config" / "gripper_safe.yaml",
    )
    pure_python_paths = tuple(
        executor_source / name for name in (
            "arm_gateway_core.py",
            "gripper_gateway_core.py",
            "gripper_core.py",
            "arm_motion_release_manifest.py",
            "final_gripper_release_manifest.py",
            "arm_safety_latch.py",
            "gripper_safety_latch.py",
            "arm_gripper_field_acceptance.py",
        )
    )

    findings = {
        "backend_vendor_or_dynamic_imports": [],
        "backend_file_io_or_enumeration": [],
        "timeout_thread_wrappers": [],
        "runtime_device_path_entries": [],
        "real_backend_construction_entries": [],
        "pure_python_ros_imports": [],
    }

    for path in backend_paths:
        tree = trees.get(path)
        if tree is None:
            continue
        relative = _relative(path, workspace)
        for root in sorted(_import_roots(tree) & VENDOR_IMPORT_ROOTS):
            findings["backend_vendor_or_dynamic_imports"].append({
                "path": relative,
                "line": None,
                "entry": "import {}".format(root),
            })
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = _call_name(node)
            tail = name.split(".")[-1]
            if tail in DYNAMIC_IMPORT_CALLS:
                findings["backend_vendor_or_dynamic_imports"].append({
                    "path": relative,
                    "line": getattr(node, "lineno", None),
                    "entry": name,
                })
            if tail in FILE_IO_OR_ENUMERATION_CALLS:
                findings["backend_file_io_or_enumeration"].append({
                    "path": relative,
                    "line": getattr(node, "lineno", None),
                    "entry": name,
                })

    production_python = tuple(
        path for path in scoped_files
        if path.parent == executor_source and path.suffix == ".py")
    for path in production_python:
        tree = trees.get(path)
        if tree is None:
            continue
        relative = _relative(path, workspace)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = _call_name(node)
            if name.split(".")[-1] in TIMEOUT_THREAD_CALLS:
                findings["timeout_thread_wrappers"].append({
                    "path": relative,
                    "line": getattr(node, "lineno", None),
                    "entry": name,
                })

    for path in runtime_entry_paths:
        if not path.is_file():
            continue
        relative = _relative(path, workspace)
        source = path.read_text(encoding="utf-8")
        if "/" + "dev/" in source or "\\\\.\\" in source:
            findings["runtime_device_path_entries"].append({
                "path": relative,
                "line": None,
                "entry": "runtime device-path literal",
            })
        tree = trees.get(path)
        if tree is None or path.suffix != ".py":
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = _call_name(node).split(".")[-1]
            if name in REAL_BACKEND_CONSTRUCTORS:
                findings["real_backend_construction_entries"].append({
                    "path": relative,
                    "line": getattr(node, "lineno", None),
                    "entry": name,
                })

    for path in pure_python_paths:
        tree = trees.get(path)
        if tree is None:
            continue
        roots = sorted(_import_roots(tree) & ROS_IMPORT_ROOTS)
        for root in roots:
            findings["pure_python_ros_imports"].append({
                "path": _relative(path, workspace),
                "line": None,
                "entry": root,
            })

    lock_scope = []
    for path, kind in (
            (executor_source / "arm_gateway_core.py", "core"),
            (executor_source / "gripper_gateway_core.py", "core"),
            (executor_source / "arm_gateway_node.py", "node"),
            (executor_source / "gripper_gateway_node.py", "node")):
        tree = trees.get(path)
        if tree is not None:
            report = _lock_scope_report(
                Path(_relative(path, workspace)), tree, kind)
            lock_scope.append(report)

    hashes = {
        _relative(path, workspace): _sha256(path)
        for path in scoped_files
    }
    finding_count = sum(len(items) for items in findings.values())
    integrity_count = sum(len(items) for items in text_integrity.values())
    lock_violation_count = sum(
        len(item["external_call_violations"]) for item in lock_scope)
    passed = not (
        ast_errors
        or compile_errors
        or finding_count
        or integrity_count
        or lock_violation_count
    )
    return {
        "schema_id": SCHEMA_ID,
        "schema_version": SCHEMA_VERSION,
        "passed": passed,
        "workspace": str(workspace),
        "scope": {
            "files": len(scoped_files),
            "python_files": len(python_files),
            "sha256": hashes,
        },
        "python_38_ast": {
            "passed": len(python_files) - len(ast_errors),
            "failed": len(ast_errors),
            "errors": ast_errors,
        },
        "in_memory_compile": {
            "passed": len(python_files) - len(compile_errors),
            "failed": len(compile_errors),
            "errors": compile_errors,
        },
        "text_integrity": text_integrity,
        "findings": findings,
        "lock_scope": lock_scope,
        "totals": {
            "static_findings": finding_count,
            "text_integrity_findings": integrity_count,
            "ordinary_lock_external_call_violations": lock_violation_count,
        },
    }


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--workspace",
        default=str(Path(__file__).resolve().parents[1]),
    )
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    report = audit(Path(args.workspace))
    payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        output = Path(args.output)
        output.write_text(payload, encoding="utf-8", newline="\n")
    sys.stdout.buffer.write(payload.encode("utf-8"))
    sys.stdout.buffer.flush()
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

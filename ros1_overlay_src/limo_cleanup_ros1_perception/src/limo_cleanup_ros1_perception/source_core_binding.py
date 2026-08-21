"""Fail-closed binding between host V2 core and the ROS1 Noetic port.

This module is ROS-independent.  It reopens both source trees and never trusts
paths, sizes, hashes, algorithms, or API declarations merely because the
binding manifest reports them.
"""

import ast
import hashlib
import json
import stat
from pathlib import Path
from typing import Mapping


SCHEMA_VERSION = 1
BINDING_ID = 'limo-v2-ros1-source-core-binding-v2'
ALGORITHM_ID = (
    'python38-ast-dump+utf8-crlf-to-lf+'
    'package-name-replacement-only/v1')
HOST_PACKAGE_NAME = 'limo_cleanup_perception'
ROS1_PACKAGE_NAME = 'limo_cleanup_ros1_perception'
MANIFEST_RELATIVE = (
    'ros1_overlay_src/limo_cleanup_ros1_perception/'
    'config/source_core_binding_v2.json')
BEHAVIOR_TEST_RELATIVE = (
    'src/limo_cleanup_perception/test/test_perception_core.py')

NORMALIZED_EQUIVALENT_MODULES = (
    'evidence_binding.py',
    'image_conversion.py',
    'orchestration_contract.py',
    'perception_frame_io.py',
    'rgbd_contract.py',
    'target_contract.py',
)
PERCEPTION_CORE_SHARED_EXPORTS = (
    'ClassDef:BottleClassification',
    'ClassDef:Detection2D',
    'FunctionDef:bin_opening_region',
    'FunctionDef:bottle_is_in_bin',
    'FunctionDef:classify_bottles',
    'FunctionDef:classify_bottles_with_depth',
    'FunctionDef:intersection_area',
    'FunctionDef:select_target_bin',
    'FunctionDef:select_target_bottle',
)
PERCEPTION_CORE_HOST_ONLY_EXPORTS = (
    'ClassDef:DisposalPhase',
    'ClassDef:DisposalStateMachine',
)
PERCEPTION_CORE_HOST_EXPORTS = tuple(sorted(
    PERCEPTION_CORE_SHARED_EXPORTS + PERCEPTION_CORE_HOST_ONLY_EXPORTS))
PERCEPTION_CORE_ROS1_EXPORTS = tuple(sorted(
    PERCEPTION_CORE_SHARED_EXPORTS))

REQUIRED_PAIR_SPECS = tuple([
    {
        'pair_id': Path(name).stem,
        'mode': 'normalized_ast_equivalent',
        'host_relative_path': (
            'src/limo_cleanup_perception/limo_cleanup_perception/' + name),
        'ros1_relative_path': (
            'ros1_overlay_src/limo_cleanup_ros1_perception/src/'
            'limo_cleanup_ros1_perception/' + name),
    }
    for name in NORMALIZED_EQUIVALENT_MODULES
] + [{
    'pair_id': 'perception_core',
    'mode': 'exact_ast_api_subset',
    'host_relative_path': (
        'src/limo_cleanup_perception/limo_cleanup_perception/'
        'perception_core.py'),
    'ros1_relative_path': (
        'ros1_overlay_src/limo_cleanup_ros1_perception/src/'
        'limo_cleanup_ros1_perception/perception_core.py'),
}])
REQUIRED_PAIR_IDS = tuple(item['pair_id'] for item in REQUIRED_PAIR_SPECS)


class SourceCoreBindingError(ValueError):
    """A stable fail-closed source-binding error."""


def _strict_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise SourceCoreBindingError(
                'source_core_binding_duplicate_json_key:' + key)
        value[key] = item
    return value


def _invalid_constant(value):
    raise SourceCoreBindingError(
        'source_core_binding_non_finite_json:' + value)


def _sha256_bytes(value):
    return hashlib.sha256(value).hexdigest()


def _is_linklike(path):
    path = Path(path)
    try:
        metadata = path.lstat()
    except OSError:
        return False
    if stat.S_ISLNK(metadata.st_mode):
        return True
    attributes = getattr(metadata, 'st_file_attributes', 0)
    return bool(attributes & getattr(
        stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0))


def _linklike_parts(workspace, path):
    workspace = Path(workspace).resolve(strict=True)
    candidate = Path(path)
    found = []
    while candidate != workspace:
        if _is_linklike(candidate):
            try:
                found.append(candidate.relative_to(workspace).as_posix())
            except ValueError:
                found.append(str(candidate))
        parent = candidate.parent
        if parent == candidate:
            break
        candidate = parent
    return sorted(set(found))


def _read_bound_file(workspace, relative_path):
    workspace = Path(workspace).resolve(strict=True)
    if (not isinstance(relative_path, str) or not relative_path
            or Path(relative_path).is_absolute()
            or Path(relative_path).drive
            or '..' in Path(relative_path).parts):
        raise SourceCoreBindingError(
            'source_core_binding_path_escape:' + str(relative_path))
    path = workspace / relative_path
    if _linklike_parts(workspace, path):
        raise SourceCoreBindingError(
            'source_core_binding_link_forbidden:' + relative_path)
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(workspace)
        if not stat.S_ISREG(resolved.stat().st_mode):
            raise OSError('not regular')
        raw = resolved.read_bytes()
    except (OSError, RuntimeError, ValueError):
        raise SourceCoreBindingError(
            'source_core_binding_file_unreadable:' + relative_path)
    return raw, {
        'path': relative_path,
        'size_bytes': len(raw),
        'raw_sha256': _sha256_bytes(raw),
    }


def _normalized_source(raw):
    try:
        value = raw.decode('utf-8')
    except UnicodeDecodeError:
        raise SourceCoreBindingError(
            'source_core_binding_source_not_utf8')
    value = value.replace('\r\n', '\n')
    if '\r' in value:
        raise SourceCoreBindingError(
            'source_core_binding_lone_carriage_return_forbidden')
    return value.replace(ROS1_PACKAGE_NAME, HOST_PACKAGE_NAME)


def _semantic_tree(raw, relative_path):
    source = _normalized_source(raw)
    try:
        tree = ast.parse(
            source, filename=relative_path, feature_version=(3, 8))
    except (SyntaxError, ValueError):
        raise SourceCoreBindingError(
            'source_core_binding_python38_ast_invalid:' + relative_path)
    canonical = ast.dump(
        tree, annotate_fields=True, include_attributes=False).encode('utf-8')
    return tree, _sha256_bytes(canonical)


def _public_exports(tree):
    values = []
    for node in tree.body:
        if (isinstance(node, (ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef))
                and not node.name.startswith('_')):
            values.append(type(node).__name__ + ':' + node.name)
    return tuple(sorted(values))


def _export_semantics(tree):
    result = {}
    for node in tree.body:
        if (isinstance(node, (ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef))
                and not node.name.startswith('_')):
            key = type(node).__name__ + ':' + node.name
            canonical = ast.dump(
                node, annotate_fields=True,
                include_attributes=False).encode('utf-8')
            result[key] = _sha256_bytes(canonical)
    return result


def _algorithm_contract():
    return {
        'algorithm_id': ALGORITHM_ID,
        'python_feature_version': '3.8',
        'text_encoding': 'utf-8-strict',
        'line_ending_normalization': 'CRLF_TO_LF_ONLY',
        'package_name_replacements': [{
            'from': ROS1_PACKAGE_NAME,
            'to': HOST_PACKAGE_NAME,
        }],
        'semantic_representation': (
            'ast.dump(annotate_fields=True,include_attributes=False)'),
    }


def make_source_core_binding_manifest(workspace):
    """Recompute the complete binding from live regular source files."""
    workspace = Path(workspace).resolve(strict=True)
    pairs = []
    for spec in REQUIRED_PAIR_SPECS:
        host_raw, host_identity = _read_bound_file(
            workspace, spec['host_relative_path'])
        ros1_raw, ros1_identity = _read_bound_file(
            workspace, spec['ros1_relative_path'])
        host_tree, host_semantic = _semantic_tree(
            host_raw, spec['host_relative_path'])
        ros1_tree, ros1_semantic = _semantic_tree(
            ros1_raw, spec['ros1_relative_path'])
        host_identity['normalized_semantic_sha256'] = host_semantic
        ros1_identity['normalized_semantic_sha256'] = ros1_semantic
        pair = {
            'pair_id': spec['pair_id'],
            'mode': spec['mode'],
            'algorithm_id': ALGORITHM_ID,
            'host': host_identity,
            'ros1': ros1_identity,
        }
        if spec['mode'] == 'normalized_ast_equivalent':
            if host_semantic != ros1_semantic:
                raise SourceCoreBindingError(
                    'source_core_binding_semantic_mismatch:'
                    + spec['pair_id'])
        elif spec['pair_id'] == 'perception_core':
            host_exports = _public_exports(host_tree)
            ros1_exports = _public_exports(ros1_tree)
            if host_exports != PERCEPTION_CORE_HOST_EXPORTS:
                raise SourceCoreBindingError(
                    'source_core_binding_host_api_drift:perception_core')
            if ros1_exports != PERCEPTION_CORE_ROS1_EXPORTS:
                raise SourceCoreBindingError(
                    'source_core_binding_ros1_api_drift:perception_core')
            host_nodes = _export_semantics(host_tree)
            ros1_nodes = _export_semantics(ros1_tree)
            shared = []
            for name in PERCEPTION_CORE_SHARED_EXPORTS:
                if host_nodes.get(name) != ros1_nodes.get(name):
                    raise SourceCoreBindingError(
                        'source_core_binding_shared_api_semantic_mismatch:'
                        + name)
                shared.append({
                    'export': name,
                    'normalized_semantic_sha256': host_nodes[name],
                })
            test_raw, test_identity = _read_bound_file(
                workspace, BEHAVIOR_TEST_RELATIVE)
            _, test_semantic = _semantic_tree(
                test_raw, BEHAVIOR_TEST_RELATIVE)
            test_identity['normalized_semantic_sha256'] = test_semantic
            pair['api_contract'] = {
                'host_exports': list(PERCEPTION_CORE_HOST_EXPORTS),
                'ros1_exports': list(PERCEPTION_CORE_ROS1_EXPORTS),
                'shared_exports': shared,
                'host_only_exports': list(
                    PERCEPTION_CORE_HOST_ONLY_EXPORTS),
                'ros1_only_exports': [],
                'behavior_test': test_identity,
            }
        pairs.append(pair)
    return {
        'schema_version': SCHEMA_VERSION,
        'binding_id': BINDING_ID,
        'read_only': True,
        'authorizes_motion': False,
        'delivery_ready': False,
        'algorithm': _algorithm_contract(),
        'required_pair_ids': list(REQUIRED_PAIR_IDS),
        'pairs': pairs,
    }


def validate_source_core_binding(workspace, manifest_path=None):
    """Validate the fixed manifest against freshly reopened source pairs."""
    workspace = Path(workspace).resolve(strict=True)
    manifest_expected_path = workspace / MANIFEST_RELATIVE
    failures = []
    if manifest_path is not None:
        try:
            supplied = Path(manifest_path).resolve(strict=True)
        except (OSError, RuntimeError):
            supplied = Path(manifest_path)
        if supplied != manifest_expected_path.resolve():
            failures.append('source_core_binding_manifest_path_override')
    manifest_identity = None
    payload = None
    try:
        raw, manifest_identity = _read_bound_file(
            workspace, MANIFEST_RELATIVE)
        payload = json.loads(
            raw.decode('utf-8'), object_pairs_hook=_strict_object,
            parse_constant=_invalid_constant)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError,
            SourceCoreBindingError) as error:
        failures.append(
            str(error) if isinstance(error, SourceCoreBindingError)
            else 'source_core_binding_manifest_invalid')

    fresh = None
    try:
        fresh = make_source_core_binding_manifest(workspace)
    except SourceCoreBindingError as error:
        failures.append(str(error))

    if not isinstance(payload, Mapping):
        failures.append('source_core_binding_manifest_schema_invalid')
    elif fresh is not None:
        if set(payload) != set(fresh):
            failures.append('source_core_binding_manifest_schema_invalid')
        if payload.get('algorithm') != fresh['algorithm']:
            failures.append('source_core_binding_algorithm_drift')
        if payload.get('required_pair_ids') != list(REQUIRED_PAIR_IDS):
            failures.append('source_core_binding_required_pair_set_invalid')
        pairs = payload.get('pairs')
        if not isinstance(pairs, list):
            failures.append('source_core_binding_pair_set_invalid')
        else:
            pair_ids = []
            specs = {item['pair_id']: item for item in REQUIRED_PAIR_SPECS}
            for index, item in enumerate(pairs):
                if not isinstance(item, Mapping):
                    failures.append(
                        'source_core_binding_pair_invalid:' + str(index))
                    continue
                pair_id = item.get('pair_id')
                if not isinstance(pair_id, str):
                    failures.append(
                        'source_core_binding_pair_id_invalid:' + str(index))
                    continue
                pair_ids.append(pair_id)
                spec = specs.get(pair_id)
                if spec is None:
                    continue
                expected_keys = {
                    'pair_id', 'mode', 'algorithm_id', 'host', 'ros1'}
                if pair_id == 'perception_core':
                    expected_keys.add('api_contract')
                if set(item) != expected_keys:
                    failures.append(
                        'source_core_binding_pair_schema_invalid:' + pair_id)
                if (item.get('mode') != spec['mode']
                        or item.get('algorithm_id') != ALGORITHM_ID):
                    failures.append(
                        'source_core_binding_pair_policy_invalid:' + pair_id)
                for role in ('host', 'ros1'):
                    identity = item.get(role)
                    role_expected_relative = spec[role + '_relative_path']
                    if (not isinstance(identity, Mapping)
                            or set(identity) != {
                                'path', 'size_bytes', 'raw_sha256',
                                'normalized_semantic_sha256'}):
                        failures.append(
                            'source_core_binding_identity_schema_invalid:'
                            + pair_id + ':' + role)
                        continue
                    declared_path = identity.get('path')
                    if (not isinstance(declared_path, str)
                            or Path(declared_path).is_absolute()
                            or Path(declared_path).drive
                            or '..' in Path(declared_path).parts):
                        failures.append(
                            'source_core_binding_declared_path_invalid:'
                            + pair_id + ':' + role)
                    elif declared_path != role_expected_relative:
                        failures.append(
                            'source_core_binding_declared_path_mismatch:'
                            + pair_id + ':' + role)
            if (len(pairs) != len(REQUIRED_PAIR_IDS)
                    or pair_ids != list(REQUIRED_PAIR_IDS)
                    or len(pair_ids) != len(set(pair_ids))):
                failures.append('source_core_binding_pair_set_invalid')
        if payload != fresh:
            failures.append('source_core_binding_live_identity_mismatch')

    failures = sorted(set(failures))
    validated = not failures and payload == fresh
    return {
        'gate_id': 'ROS1_SOURCE_CORE_BINDING',
        'scope': 'host_to_ros1_source_admission',
        'required_for_complete_runtime': True,
        'validated_pass': validated,
        'manifest_path': str(manifest_expected_path),
        'manifest_identity': manifest_identity,
        'algorithm_id': ALGORITHM_ID,
        'required_pair_ids': list(REQUIRED_PAIR_IDS),
        'pair_count': len(REQUIRED_PAIR_IDS),
        'architecture_blockers': (
            [] if validated
            else ['ROS1_SOURCE_CORE_BINDING_NOT_VALIDATED']),
        'delivery_ready': False,
        'failures': failures,
    }

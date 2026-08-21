"""Host-owned trust root for the ROS1 Noetic perception source core.

The production readiness gate must not execute the ROS1 package's own
``source_core_binding.py`` to decide whether the package is admissible.  This
module independently reopens the release-generation manifest, the diagnostic
validator artifact, both source trees, and the bound behavior test.  Every
path, byte identity, AST semantic identity, pair policy, and API subset is
recomputed by host-owned code.

The ROS1 validator remains a useful diagnostic tool, but its return value is
never an input to :func:`validate_ros1_source_core_admission`.
"""

import ast
import hashlib
import json
import stat
from pathlib import Path
from typing import Mapping


ADMISSION_ID = 'limo-v2-ros1-source-core-admission-v2'
GATE_ID = 'ROS1_SOURCE_CORE_ADMISSION_V2'
BINDING_SCHEMA_VERSION = 1
BINDING_ID = 'limo-v2-ros1-source-core-binding-v2'
ALGORITHM_ID = (
    'python38-ast-dump+utf8-crlf-to-lf+'
    'package-name-replacement-only/v1')
HOST_PACKAGE_NAME = 'limo_cleanup_perception'
ROS1_PACKAGE_NAME = 'limo_cleanup_ros1_perception'

MANIFEST_RELATIVE = (
    'ros1_overlay_src/limo_cleanup_ros1_perception/'
    'config/source_core_binding_v2.json')
VALIDATOR_RELATIVE = (
    'ros1_overlay_src/limo_cleanup_ros1_perception/src/'
    'limo_cleanup_ros1_perception/source_core_binding.py')
BEHAVIOR_TEST_RELATIVE = (
    'src/limo_cleanup_perception/test/test_perception_core.py')

# These are host-owned release anchors.  They are deliberately outside the
# ROS1 package and cannot be supplied or overridden by field evidence.
MANIFEST_ANCHOR = {
    'path': MANIFEST_RELATIVE,
    'size_bytes': 10284,
    'sha256': (
        '331d4ea858c417f391bc725db06f51c523f2f040155db7d1c53fa230d4689797'),
}
VALIDATOR_ANCHOR = {
    'path': VALIDATOR_RELATIVE,
    'size_bytes': 16346,
    'sha256': (
        'ad5931734b83c05d5d727ff219ef78471a1c14a76fbf2e66b35d6243656b2311'),
    'ast_semantic_sha256': (
        'f7e3e8d0b953e9e0bc7fd18f63deaa6dbf25a80de87282557802e4d3b653ef20'),
}

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


class SourceCoreAdmissionError(ValueError):
    """Stable fail-closed error raised while reopening bound artifacts."""


def _strict_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise SourceCoreAdmissionError(
                'ros1_source_core_admission_duplicate_json_key:' + key)
        value[key] = item
    return value


def _invalid_constant(value):
    raise SourceCoreAdmissionError(
        'ros1_source_core_admission_non_finite_json:' + value)


def _sha256_bytes(value):
    return hashlib.sha256(value).hexdigest()


def _lower_sha256(value):
    return (isinstance(value, str) and len(value) == 64
            and all(character in '0123456789abcdef' for character in value))


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


def _read_regular_file(workspace, relative_path):
    workspace = Path(workspace).resolve(strict=True)
    if (not isinstance(relative_path, str) or not relative_path
            or Path(relative_path).is_absolute()
            or Path(relative_path).drive
            or '..' in Path(relative_path).parts):
        raise SourceCoreAdmissionError(
            'ros1_source_core_admission_path_escape:' + str(relative_path))
    path = workspace / relative_path
    if _linklike_parts(workspace, path):
        raise SourceCoreAdmissionError(
            'ros1_source_core_admission_link_forbidden:' + relative_path)
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(workspace)
        if not stat.S_ISREG(resolved.stat().st_mode):
            raise OSError('not regular')
        raw = resolved.read_bytes()
    except (OSError, RuntimeError, ValueError):
        raise SourceCoreAdmissionError(
            'ros1_source_core_admission_file_unreadable:' + relative_path)
    return raw, {
        'path': relative_path,
        'size_bytes': len(raw),
        'raw_sha256': _sha256_bytes(raw),
    }


def _normalized_text(raw, replace_package_name=True):
    try:
        value = raw.decode('utf-8')
    except UnicodeDecodeError:
        raise SourceCoreAdmissionError(
            'ros1_source_core_admission_source_not_utf8')
    value = value.replace('\r\n', '\n')
    if '\r' in value:
        raise SourceCoreAdmissionError(
            'ros1_source_core_admission_lone_carriage_return_forbidden')
    if replace_package_name:
        value = value.replace(ROS1_PACKAGE_NAME, HOST_PACKAGE_NAME)
    return value


def _semantic_tree(raw, relative_path, replace_package_name=True):
    source = _normalized_text(raw, replace_package_name)
    try:
        tree = ast.parse(
            source, filename=relative_path, feature_version=(3, 8))
    except (SyntaxError, ValueError):
        raise SourceCoreAdmissionError(
            'ros1_source_core_admission_python38_ast_invalid:'
            + relative_path)
    canonical = ast.dump(
        tree, annotate_fields=True,
        include_attributes=False).encode('utf-8')
    return tree, _sha256_bytes(canonical)


def _public_exports(tree):
    result = []
    for node in tree.body:
        if (isinstance(node, (ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef))
                and not node.name.startswith('_')):
            result.append(type(node).__name__ + ':' + node.name)
    return tuple(sorted(result))


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


def make_live_source_core_manifest(workspace):
    """Independently recompute the v2 binding from live source files."""
    workspace = Path(workspace).resolve(strict=True)
    pairs = []
    for spec in REQUIRED_PAIR_SPECS:
        host_raw, host_identity = _read_regular_file(
            workspace, spec['host_relative_path'])
        ros1_raw, ros1_identity = _read_regular_file(
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
                raise SourceCoreAdmissionError(
                    'ros1_source_core_admission_semantic_mismatch:'
                    + spec['pair_id'])
        elif spec['pair_id'] == 'perception_core':
            host_exports = _public_exports(host_tree)
            ros1_exports = _public_exports(ros1_tree)
            if host_exports != PERCEPTION_CORE_HOST_EXPORTS:
                raise SourceCoreAdmissionError(
                    'ros1_source_core_admission_host_api_drift:'
                    'perception_core')
            if ros1_exports != PERCEPTION_CORE_ROS1_EXPORTS:
                raise SourceCoreAdmissionError(
                    'ros1_source_core_admission_ros1_api_drift:'
                    'perception_core')
            host_nodes = _export_semantics(host_tree)
            ros1_nodes = _export_semantics(ros1_tree)
            shared = []
            for export in PERCEPTION_CORE_SHARED_EXPORTS:
                if host_nodes.get(export) != ros1_nodes.get(export):
                    raise SourceCoreAdmissionError(
                        'ros1_source_core_admission_shared_api_drift:'
                        + export)
                shared.append({
                    'export': export,
                    'normalized_semantic_sha256': host_nodes[export],
                })
            test_raw, test_identity = _read_regular_file(
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
        'schema_version': BINDING_SCHEMA_VERSION,
        'binding_id': BINDING_ID,
        'read_only': True,
        'authorizes_motion': False,
        'delivery_ready': False,
        'algorithm': _algorithm_contract(),
        'required_pair_ids': list(REQUIRED_PAIR_IDS),
        'pairs': pairs,
    }


def _artifact_anchor_failures(identity, anchor, prefix):
    failures = []
    if not _lower_sha256(anchor.get('sha256')):
        failures.append(prefix + '_trust_anchor_invalid')
        return failures
    for key in ('path', 'size_bytes'):
        if identity.get(key) != anchor.get(key):
            failures.append(prefix + '_anchor_mismatch:' + key)
    if identity.get('raw_sha256') != anchor.get('sha256'):
        failures.append(prefix + '_anchor_mismatch:sha256')
    return failures


def _manifest_policy_failures(payload, live):
    failures = []
    expected_keys = {
        'schema_version', 'binding_id', 'read_only', 'authorizes_motion',
        'delivery_ready', 'algorithm', 'required_pair_ids', 'pairs'}
    if not isinstance(payload, Mapping) or set(payload) != expected_keys:
        return ['ros1_source_core_admission_manifest_schema_invalid']
    if (payload.get('schema_version') != BINDING_SCHEMA_VERSION
            or payload.get('binding_id') != BINDING_ID
            or payload.get('read_only') is not True
            or payload.get('authorizes_motion') is not False
            or payload.get('delivery_ready') is not False):
        failures.append(
            'ros1_source_core_admission_manifest_policy_invalid')
    if payload.get('algorithm') != _algorithm_contract():
        failures.append('ros1_source_core_admission_algorithm_invalid')
    if payload.get('required_pair_ids') != list(REQUIRED_PAIR_IDS):
        failures.append('ros1_source_core_admission_required_pairs_invalid')
    pairs = payload.get('pairs')
    if not isinstance(pairs, list):
        failures.append('ros1_source_core_admission_pair_set_invalid')
    else:
        ids = [
            item.get('pair_id') if isinstance(item, Mapping) else None
            for item in pairs]
        if (len(pairs) != len(REQUIRED_PAIR_IDS)
                or ids != list(REQUIRED_PAIR_IDS)
                or len(ids) != len(set(ids))):
            failures.append('ros1_source_core_admission_pair_set_invalid')
        specs = {item['pair_id']: item for item in REQUIRED_PAIR_SPECS}
        for item in pairs:
            if not isinstance(item, Mapping):
                continue
            pair_id = item.get('pair_id')
            spec = specs.get(pair_id)
            if spec is None:
                continue
            expected_pair_keys = {
                'pair_id', 'mode', 'algorithm_id', 'host', 'ros1'}
            if pair_id == 'perception_core':
                expected_pair_keys.add('api_contract')
            if set(item) != expected_pair_keys:
                failures.append(
                    'ros1_source_core_admission_pair_schema_invalid:'
                    + pair_id)
            if (item.get('mode') != spec['mode']
                    or item.get('algorithm_id') != ALGORITHM_ID):
                failures.append(
                    'ros1_source_core_admission_pair_policy_invalid:'
                    + pair_id)
            for role in ('host', 'ros1'):
                identity = item.get(role)
                expected_path = spec[role + '_relative_path']
                if (not isinstance(identity, Mapping)
                        or set(identity) != {
                            'path', 'size_bytes', 'raw_sha256',
                            'normalized_semantic_sha256'}):
                    failures.append(
                        'ros1_source_core_admission_identity_invalid:'
                        + pair_id + ':' + role)
                elif identity.get('path') != expected_path:
                    failures.append(
                        'ros1_source_core_admission_declared_path_invalid:'
                        + pair_id + ':' + role)
    if payload != live:
        failures.append(
            'ros1_source_core_admission_live_binding_mismatch')
    return failures


def validate_ros1_source_core_admission(workspace):
    """Validate the fixed v2 source binding without executing ROS1 code."""
    workspace = Path(workspace).resolve(strict=True)
    failures = []
    manifest_payload = None
    manifest_identity = None
    validator_identity = None
    validator_ast_sha256 = None

    try:
        manifest_raw, manifest_identity = _read_regular_file(
            workspace, MANIFEST_RELATIVE)
        failures.extend(_artifact_anchor_failures(
            manifest_identity, MANIFEST_ANCHOR,
            'ros1_source_core_admission_manifest'))
        manifest_payload = json.loads(
            manifest_raw.decode('utf-8'),
            object_pairs_hook=_strict_object,
            parse_constant=_invalid_constant)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError,
            SourceCoreAdmissionError) as error:
        failures.append(
            str(error) if isinstance(error, SourceCoreAdmissionError)
            else 'ros1_source_core_admission_manifest_invalid')

    try:
        validator_raw, validator_identity = _read_regular_file(
            workspace, VALIDATOR_RELATIVE)
        failures.extend(_artifact_anchor_failures(
            validator_identity, VALIDATOR_ANCHOR,
            'ros1_source_core_admission_validator'))
        _, validator_ast_sha256 = _semantic_tree(
            validator_raw, VALIDATOR_RELATIVE,
            replace_package_name=False)
        expected_ast = VALIDATOR_ANCHOR.get('ast_semantic_sha256')
        if not _lower_sha256(expected_ast):
            failures.append(
                'ros1_source_core_admission_validator_ast_anchor_invalid')
        elif validator_ast_sha256 != expected_ast:
            failures.append(
                'ros1_source_core_admission_validator_ast_anchor_mismatch')
    except SourceCoreAdmissionError as error:
        failures.append(str(error))

    live = None
    try:
        live = make_live_source_core_manifest(workspace)
    except SourceCoreAdmissionError as error:
        failures.append(str(error))
    if live is None:
        failures.append('ros1_source_core_admission_live_binding_unavailable')
    else:
        failures.extend(_manifest_policy_failures(manifest_payload, live))

    failures = sorted(set(failures))
    validated = not failures and manifest_payload == live
    return {
        'gate_id': GATE_ID,
        'admission_id': ADMISSION_ID,
        'scope': 'host_owned_ros1_source_core_admission',
        'required_for_complete_runtime': True,
        'validated_pass': validated,
        'binding_id': BINDING_ID,
        'algorithm_id': ALGORITHM_ID,
        'required_pair_ids': list(REQUIRED_PAIR_IDS),
        'pair_count': len(REQUIRED_PAIR_IDS),
        'manifest_path': str(workspace / MANIFEST_RELATIVE),
        'manifest_identity': manifest_identity,
        'manifest_anchor': dict(MANIFEST_ANCHOR),
        'validator_path': str(workspace / VALIDATOR_RELATIVE),
        'validator_identity': validator_identity,
        'validator_ast_semantic_sha256': validator_ast_sha256,
        'validator_anchor': dict(VALIDATOR_ANCHOR),
        'package_validator_executed': False,
        'package_validator_return_value_trusted': False,
        'host_recomputed_live_binding': live is not None,
        'architecture_blockers': (
            [] if validated else ['ROS1_SOURCE_CORE_BINDING_NOT_VALIDATED']),
        'delivery_ready': False,
        'authorizes_motion': False,
        'failures': failures,
    }

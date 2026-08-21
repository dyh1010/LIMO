#!/usr/bin/env python3
"""Run the frozen V1/bridge offline release matrix and emit evidence.

This entry point never starts ROS and never touches hardware.  The complete
release decision is intentionally Linux/POSIX-only because the bridge tests
and secure release validator exercise fcntl/flock, /proc, memfd and openat
with O_NOFOLLOW.  Other platforms may run ``--self-test`` only.
"""

import argparse
import ast
import datetime as _datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import py_compile
import re
import subprocess
import sys
import tempfile
import time
import unittest


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
V1_ROOT = WORKSPACE_ROOT / 'ros1_overlay_src' / 'limo_v1_navigation'
BRIDGE_ROOT = WORKSPACE_ROOT / 'ros1_overlay_src' / 'limo_cleanup_ros1_base'
SCHEMA = 'limo_v1_frozen_release_readiness/v1'
DECISION_MODEL = 'limo_v1_independent_blocker_attribution/v1'
VENDOR_PROVENANCE_PATH = (
    V1_ROOT / 'docs' / 'V1_ROS1_VENDOR_INCLUDE_BLOCKER.json')
VENDOR_WRAPPER_PATH = V1_ROOT / 'launch' / 'v1_base_sensors.launch'
TOPOLOGY_POLICY_PATH = (
    V1_ROOT / 'src' / 'limo_v1_navigation' / 'topology_policy.py')
RELEASE_DRIFT_PATH = (
    BRIDGE_ROOT / 'docs' / 'V1_TF_EDGE_RELEASE_DRIFT_BLOCKER_2026-08-14.json')
BRIDGE_MAP_BINDING_PATH = (
    BRIDGE_ROOT / 'src' / 'limo_cleanup_ros1_base' / 'map_binding.py')
VENDOR_PROVENANCE_SCHEMA = 'limo_v1_ros1_vendor_include_blocker/v1'
RELEASE_DRIFT_SCHEMA = 'limo_v1_tf_edge_release_drift_blocker/v1'
OUTPUT_SUMMARY_HEAD_LINES = 12
OUTPUT_SUMMARY_TAIL_LINES = 12
OUTPUT_SUMMARY_LINE_CHAR_LIMIT = 512
PYTEST_FAILED_NODE_REPORT_LIMIT = 32
PYTEST_MALFORMED_LINE_REPORT_LIMIT = 32
BRIDGE_RELEASE_HASH_FAILURE_ALLOWLIST = frozenset({
    'test/test_map_binding.py::test_release_files_match_the_frozen_hash_set',
})
BRIDGE_RELEASE_DRIFT_PATHS = frozenset({
    'src/limo_v1_navigation/topology_policy.py',
    'scripts/v1_runtime_preflight.py',
    'launch/v1_runtime_preflight.launch',
})
_URL_CREDENTIAL_PATTERN = re.compile(
    r'(?i)\b([a-z][a-z0-9+.-]*://)([^\s/:@]+):([^\s/@]+)@')
_BEARER_PATTERN = re.compile(
    r'(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+')
_SECRET_VALUE_PATTERN = re.compile(
    r'(?i)\b(password|passwd|pwd|secret|token|api[_-]?key|'
    r'access[_-]?(?:key|token)|client[_-]?secret|authorization)\b'
    r'(\s*[:=]\s*)'
    r'("[^"]*"|\'[^\']*\'|[^\s,;]+)')
_PYTEST_FAILED_PATTERN = re.compile(
    r'^\s*FAILED(?P<separator>\s+|$)(?P<payload>.*)$')

# This report was generated before independent blocker attribution existed.  It
# remains immutable evidence, but a new report must explicitly identify it as
# stale for readiness decisions instead of overwriting or silently replacing
# it.
SUPERSEDED_EVIDENCE_REPORTS = (
    {
        'path': WORKSPACE_ROOT / 'evidence' /
        'v1_frozen_release_readiness_20260814_164500_'
        'vendor_provenance_final_blocked.json',
        'sha256': (
            'c021787447b16d5def65796b3b0bac7883fc683106af1ce30cbb5de90d693012'),
        'reason': (
            'pre-attribution report conflated independent release/vendor '
            'blockers with the two integrated software closures'),
    },
    {
        'path': WORKSPACE_ROOT / 'evidence' /
        'v1_frozen_release_readiness_20260814_172500_'
        'vendor_resolution_attribution_blocked.json',
        'sha256': (
            '1258a75eb74606f524bf61ca383e6f079a4536874b386795567763728de08b33'),
        'reason': (
            'pre-output-attribution report lacked bounded/redacted summaries '
            'and exact bridge failed-node proof'),
    },
    {
        'path': WORKSPACE_ROOT / 'evidence' /
        'v1_frozen_release_readiness_20260814_175500_'
        'safe_bridge_attribution_blocked.json',
        'sha256': (
            '0a7e6db032aba31cc1dd81f25849b61434624df118612ee889cd9c61a69a89de'),
        'reason': (
            'output persistence contract ambiguity corrected by '
            '922d676e8fc0219d62bba7f75578f6877a73ee41db59443e9e4e59059ab41b4d'),
    },
    {
        'path': WORKSPACE_ROOT / 'evidence' /
        'v1_frozen_release_readiness_20260814_175800_'
        'safe_bridge_attribution_final_blocked.json',
        'sha256': (
            '922d676e8fc0219d62bba7f75578f6877a73ee41db59443e9e4e59059ab41b4d'),
        'reason': (
            'authoritative predecessor superseded by the unique successor '
            'that closes the machine-lineage gap'),
    },
)

DIRECT_AUTHORITY_PREDECESSOR = {
    'report': {
        'path': WORKSPACE_ROOT / 'evidence' /
        'v1_frozen_release_readiness_20260814_182000_'
        'lineage_authority_blocked.json',
        'sha256': (
            'a934658607220d878f3a0016b584848e651a5794e69d99f8889d3e1cf603ee63'),
        'bytes': 43526,
        'reason': 'direct report selected by the predecessor authority index',
    },
    'index': {
        'path': WORKSPACE_ROOT / 'evidence' /
        'v1_frozen_release_authority_'
        '61a65c02bd409da8ab4020343c8f71e26b738c82661459dd829cff519d4dc8f5.json',
        'sha256': (
            '2f35564fbd586698fad9bd0ebc5918dd299cf85882dc1ce25cf70b83fecfc4d9'),
        'bytes': 3825,
        'reason': 'direct committed authority predecessor index',
    },
}

CURRENT_AUTHORITATIVE_LIFECYCLE = (
    'CURRENT_AUTHORITATIVE_FOR_READINESS_DECISIONS')
PENDING_AUTHORITY_LIFECYCLE = 'NON_AUTHORITATIVE_PENDING_AUTHORITY_INDEX'
EXPECTED_SUPERSEDED_EVIDENCE_COUNT = 4
PREDECESSOR_AUTHORITY_INDEX_SCHEMA = (
    'limo_v1_frozen_release_authority_index/v1')
AUTHORITY_INDEX_SCHEMA = 'limo_v1_frozen_release_authority_index/v2'
AUTHORITY_CLAIM_SCHEMA = 'limo_v1_frozen_release_authority_claim/v1'
AUTHORITY_ROOT = WORKSPACE_ROOT / 'evidence'


class AuthorityGenerationBlockedError(RuntimeError):
    """Raised when an immutable authority generation cannot safely continue."""

EXPECTED = {
    'v1_frozen_core_unittest': 113,
    'v1_delivery_audit_unittest': 25,
    'v1_package_discovery': 138,
    'bridge_pytest': 122,
    'secure_release_validator': 14,
    'cross_package_groups': 9,
}

# The frozen source-audit set is the two ROS1 packages plus these three shared
# audit entry points.  Cache/output files are never evidence inputs.
SHARED_AUDIT_FILES = (
    WORKSPACE_ROOT / 'scripts' / 'test_ros1_v1_navigation_offline.py',
    WORKSPACE_ROOT / 'scripts' / 'test_ros1_base_bridge_offline.py',
    WORKSPACE_ROOT / 'scripts' / 'audit_ros1_catkin_overlay.py',
)

# These post-freeze tests audit delivery evidence and runbooks.  They must run,
# but must not rewrite the historical statement that the frozen core suite is
# 113 tests.  New test_*.py files fail closed until classified here or in the
# frozen core set.
DELIVERY_AUDIT_TEST_NAMES = frozenset({
    'test_field_authorization_contract.py',
    'test_frozen_release_readiness.py',
    'test_deployment_runbook_contract.py',
})

INTEGRATED_SOFTWARE_CLOSURES = (
    {
        'id': 'ROS1_TOPOLOGY_VERIFIER_NODE_NAME_COLLISION',
        'check': 'integrated_topology_verifier_contract',
        'expected_assertion_count': 8,
        'evidence': [
            ('ros1_overlay_src/limo_cleanup_ros1_base/test/'
             'test_topology_policy.py::test_exact_full_topology_passes'),
            ('ros1_overlay_src/limo_cleanup_ros1_base/scripts/'
             'run_v2_bridged_navigation.py'),
            'scripts/run_ros1_base_bridge_zero_stage.sh',
        ],
        'resolution': (
            'canonical role/name/READY isolation plus exact peer '
            'coexistence; missing, rogue, or wrong-role peers fail closed'),
    },
    {
        'id': 'INSTALLED_RUNNER_WORKSPACE_SCRIPT_PATH_MISSING',
        'check': 'integrated_verifier_install_contract',
        'expected_assertion_count': 7,
        'evidence': [
            ('ros1_overlay_src/limo_cleanup_ros1_base/scripts/'
             'run_v2_bridged_navigation.py'),
            'src/limo_cleanup_base/setup.py',
            ('src/limo_cleanup_base/limo_cleanup_base/'
             'zero_stage_handoff_verifier.py'),
        ],
        'resolution': (
            'the runner uses the installed ROS2 console entry exclusively; '
            'missing entry, nonzero exit, or missing PASS marker blocks '
            'before integrated core startup'),
    },
)

INTEGRATED_AUDIT_FILES = (
    WORKSPACE_ROOT / 'scripts' / 'run_ros1_base_bridge_zero_stage.sh',
    WORKSPACE_ROOT / 'src' / 'limo_cleanup_base' / 'setup.py',
    WORKSPACE_ROOT / 'src' / 'limo_cleanup_base' / 'limo_cleanup_base' /
    'zero_stage_handoff_verifier.py',
    WORKSPACE_ROOT / 'src' / 'limo_cleanup_base' / 'test' /
    'test_zero_stage_handoff_verifier.py',
)

FIELD_ITEMS = (
    'amcl_three_cold_start_convergence',
    'zero_motion_absolute_localization_error',
    'repeat_localization_error',
    'navigation_control_endpoint_error',
    'amcl_estimation_error',
    'physical_total_endpoint_error',
    'cancel_and_driver_timeout',
    'static_obstacle_avoidance',
    'dynamic_obstacle_avoidance',
    'scan_odom_tf_loss',
)


def _utc_now():
    return _datetime.datetime.now(_datetime.timezone.utc).isoformat()


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def _workspace_relative(path):
    path = Path(path).resolve()
    try:
        return path.relative_to(WORKSPACE_ROOT).as_posix()
    except ValueError:
        return str(path)


def _read_json_artifact(path):
    path = Path(path).resolve()
    payload = path.read_bytes()
    return json.loads(payload.decode('utf-8')), _sha256(payload)


def _topology_policy_vendor_trust_anchor(path=TOPOLOGY_POLICY_PATH):
    path = Path(path).resolve()
    raw = path.read_bytes()
    source = raw.decode('utf-8')
    tree = ast.parse(source, filename=str(path))
    expected_names = {
        '_TRUSTED_VENDOR_BLOCKER_SHA256': 'vendor_blocker_sha256',
        '_TRUSTED_VENDOR_WRAPPER_SHA256': 'vendor_wrapper_sha256',
    }
    values = {name: [] for name in expected_names}
    for statement in tree.body:
        if not isinstance(statement, ast.Assign):
            continue
        for target in statement.targets:
            if not isinstance(target, ast.Name) or target.id not in values:
                continue
            value = ast.literal_eval(statement.value)
            if isinstance(value, str):
                values[target.id].append(value)
    result = {
        'path': _workspace_relative(path),
        'source_sha256': _sha256(raw),
    }
    for source_name, result_name in expected_names.items():
        matches = values[source_name]
        if (len(matches) != 1
                or re.fullmatch(r'[0-9a-f]{64}', matches[0]) is None):
            raise ValueError(
                'topology policy must contain one exact {} trust anchor'.format(
                    source_name))
        result[result_name] = matches[0]
    return result


def _immutable_evidence_record(entry, lifecycle):
    path = Path(entry['path']).resolve()
    actual_sha256 = None
    read_error = None
    try:
        actual_sha256 = _sha256(path.read_bytes())
    except OSError as error:
        read_error = '{}: {}'.format(type(error).__name__, error)
    return {
        'path': _workspace_relative(path),
        'expected_sha256': entry['sha256'],
        'actual_sha256': actual_sha256,
        'hash_matches': actual_sha256 == entry['sha256'],
        'lifecycle': lifecycle,
        'reason': entry['reason'],
        'must_not_be_overwritten': True,
        'read_error': read_error,
    }


def _direct_authority_predecessor_state():
    report_entry = DIRECT_AUTHORITY_PREDECESSOR['report']
    index_entry = DIRECT_AUTHORITY_PREDECESSOR['index']
    report = _immutable_evidence_record(
        report_entry, 'LEGACY_PREDECESSOR_REPORT')
    index = _immutable_evidence_record(
        index_entry, 'COMMITTED_PREDECESSOR_AUTHORITY_INDEX')
    errors = []
    for name, row, entry in (
            ('report', report, report_entry),
            ('index', index, index_entry)):
        path = Path(entry['path']).resolve()
        actual_bytes = None
        try:
            actual_bytes = len(path.read_bytes())
        except OSError:
            pass
        row['expected_bytes'] = entry['bytes']
        row['actual_bytes'] = actual_bytes
        row['bytes_match'] = actual_bytes == entry['bytes']
        if row['read_error'] is not None:
            errors.append('{}: {}'.format(name, row['read_error']))
        elif row['hash_matches'] is not True:
            errors.append('{}: SHA-256 mismatch'.format(name))
        elif row['bytes_match'] is not True:
            errors.append('{}: byte count mismatch'.format(name))

    index_payload = None
    if index['read_error'] is None:
        try:
            index_payload = json.loads(
                Path(index_entry['path']).read_text(encoding='utf-8'))
        except (OSError, UnicodeError, ValueError) as error:
            errors.append(
                'index: invalid JSON: {}: {}'.format(
                    type(error).__name__, error))
    if isinstance(index_payload, dict):
        selected = index_payload.get('current_authoritative', {})
        expected_report_path = _workspace_relative(report_entry['path'])
        if index_payload.get('schema') != PREDECESSOR_AUTHORITY_INDEX_SCHEMA:
            errors.append('index: schema mismatch')
        if selected.get('path') != expected_report_path:
            errors.append('index: selected report path mismatch')
        if selected.get('sha256') != report_entry['sha256']:
            errors.append('index: selected report SHA-256 mismatch')
        if selected.get('bytes') != report_entry['bytes']:
            errors.append('index: selected report byte count mismatch')
    elif index['read_error'] is None:
        errors.append('index: parsed payload is not an object')

    verified = not errors
    return {
        'relationship': 'DIRECT_COMMITTED_PREDECESSOR',
        'successor_relationship': 'PROPOSED_SUCCESSOR_TO',
        'report': report,
        'index': index,
        'binding_verified': verified,
        'decision': 'PASS' if verified else 'BLOCKED',
        'errors': errors,
        'last_valid_authority': (
            _workspace_relative(index_entry['path']) if verified else None),
    }


def _evidence_lineage():
    supersedes = [
        _immutable_evidence_record(
            entry, 'STALE_SUPERSEDED_FOR_READINESS_DECISIONS')
        for entry in SUPERSEDED_EVIDENCE_REPORTS]
    errors = []
    if len(supersedes) != EXPECTED_SUPERSEDED_EVIDENCE_COUNT:
        errors.append(
            'expected {} stale reports, found {}'.format(
                EXPECTED_SUPERSEDED_EVIDENCE_COUNT, len(supersedes)))
    for row in supersedes:
        if row['read_error'] is not None:
            errors.append('{}: {}'.format(row['path'], row['read_error']))
        elif row['hash_matches'] is not True:
            errors.append('{}: SHA-256 mismatch'.format(row['path']))
    predecessor = _direct_authority_predecessor_state()
    if predecessor['binding_verified'] is not True:
        errors.extend(
            'predecessor: {}'.format(error)
            for error in predecessor['errors'])
    verified = not errors
    return {
        'exclusive_create_required': True,
        'reserved_paths_never_targets': True,
        'precommit_revalidation_required': True,
        'required_for_software_release_pass': True,
        'blocker_id': 'EVIDENCE_LINEAGE_INTEGRITY_FAILED',
        'expected_stale_count': EXPECTED_SUPERSEDED_EVIDENCE_COUNT,
        'observed_stale_count': len(supersedes),
        'verified': verified,
        'decision': 'PASS' if verified else 'BLOCKED',
        'errors': errors,
        'authority_candidate': None,
        'direct_authority_predecessor': predecessor,
        'supersedes': supersedes,
    }


def _vendor_provenance_state(
        path=VENDOR_PROVENANCE_PATH, wrapper_path=VENDOR_WRAPPER_PATH):
    result = {
        'path': _workspace_relative(path),
        'expected_schema': VENDOR_PROVENANCE_SCHEMA,
        'schema': None,
        'artifact_sha256': None,
        'artifact_status': 'UNREADABLE',
        'ownership_conclusion': None,
        'raw_vendor_bytes_archived': False,
        'raw_vendor_hash_verified': False,
        'resolved_include_chain_verified': False,
        'publisher_pin_status': 'MISSING',
        'topology_policy_trust_anchor': None,
        'consumer_wrapper': {
            'path': _workspace_relative(wrapper_path),
            'artifact_sha256': None,
            'trust_anchor_sha256': None,
            'trust_anchor_matches': False,
            'read_error': None,
        },
        'blocker_trust_anchor_matches': False,
        'wrapper_trust_anchor_matches': False,
        'trust_anchor_matches': False,
        'self_reported_verified_semantics': False,
        'static_bundle_not_verified': True,
        'verification_scope': (
            'BLOCKER/WRAPPER_TRUST_ANCHORS_AND_BLOCKER_SEMANTICS_ONLY; '
            'NO INDEPENDENT SOURCE_MANIFEST/PUBLISHER_PIN/RULES PATHS'),
        'verified': False,
        'decision': 'BLOCKED',
        'failure_code': 'TF_VENDOR_CONTRACT_UNVERIFIED',
        'errors': [],
    }
    try:
        payload, digest = _read_json_artifact(path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        result['errors'].append(
            '{}: {}'.format(type(error).__name__, error))
        return result
    result['artifact_sha256'] = digest
    try:
        trust_anchor = _topology_policy_vendor_trust_anchor()
    except (OSError, UnicodeDecodeError, SyntaxError, ValueError) as error:
        result['errors'].append(
            'topology policy trust anchor unreadable: {}: {}'.format(
                type(error).__name__, error))
    else:
        result['topology_policy_trust_anchor'] = trust_anchor
        result['blocker_trust_anchor_matches'] = (
            digest == trust_anchor['vendor_blocker_sha256'])
        result['consumer_wrapper']['trust_anchor_sha256'] = (
            trust_anchor['vendor_wrapper_sha256'])
        try:
            wrapper_raw = Path(wrapper_path).resolve().read_bytes()
        except OSError as error:
            result['consumer_wrapper']['read_error'] = (
                '{}: {}'.format(type(error).__name__, error))
            result['errors'].append(
                'vendor consumer wrapper cannot be read: {}'.format(error))
        else:
            wrapper_sha256 = _sha256(wrapper_raw)
            result['consumer_wrapper']['artifact_sha256'] = wrapper_sha256
            result['wrapper_trust_anchor_matches'] = (
                wrapper_sha256 == trust_anchor['vendor_wrapper_sha256'])
            result['consumer_wrapper']['trust_anchor_matches'] = (
                result['wrapper_trust_anchor_matches'])
            if not result['wrapper_trust_anchor_matches']:
                result['errors'].append(
                    'vendor consumer wrapper bytes do not match topology '
                    'policy trust anchor')
        result['trust_anchor_matches'] = (
            result['blocker_trust_anchor_matches']
            and result['wrapper_trust_anchor_matches'])
        if not result['blocker_trust_anchor_matches']:
            result['errors'].append(
                'vendor blocker bytes do not match topology policy trust anchor')
    if not isinstance(payload, dict):
        result['errors'].append('vendor blocker must be a JSON object')
        return result
    result['schema'] = payload.get('schema')
    result['artifact_status'] = payload.get('status', 'MISSING')
    result['ownership_conclusion'] = payload.get('ownership_conclusion')
    local = payload.get('current_local_evidence')
    if not isinstance(local, dict):
        local = {}
        result['errors'].append('current_local_evidence is missing')
    result['raw_vendor_bytes_archived'] = (
        local.get('vendor_raw_source_archived') is True)
    result['raw_vendor_hash_verified'] = (
        local.get('current_hash_verified') is True)
    result['resolved_include_chain_verified'] = (
        local.get('resolved_include_chain_verified') is True)
    pin = payload.get('required_installed_tf_publisher_pin')
    if not isinstance(pin, dict):
        pin = {}
        result['errors'].append(
            'required_installed_tf_publisher_pin is missing')
    result['publisher_pin_status'] = pin.get('status', 'MISSING')
    decision = payload.get('decision')
    if not isinstance(decision, dict):
        decision = {}
        result['errors'].append('decision is missing')
    requirements = (
        ('schema mismatch', result['schema'] == VENDOR_PROVENANCE_SCHEMA),
        ('artifact status is not VERIFIED',
         result['artifact_status'] == 'VERIFIED'),
        ('ownership conclusion is not VERIFIED',
         result['ownership_conclusion'] == 'VERIFIED'),
        ('raw vendor bytes are not archived',
         result['raw_vendor_bytes_archived']),
        ('raw vendor hash is not verified',
         result['raw_vendor_hash_verified']),
        ('recursive include chain is not verified',
         result['resolved_include_chain_verified']),
        ('publisher pin is not VERIFIED',
         result['publisher_pin_status'] == 'VERIFIED'),
        ('ownership is not closed', decision.get('ownership_closed') is True),
        ('TF edge runtime is not pass eligible',
         decision.get('tf_edge_runtime_pass_eligible') is True),
    )
    result['self_reported_verified_semantics'] = all(
        passed for _description, passed in requirements)
    result['errors'].extend(
        description for description, passed in requirements if not passed)
    # This frozen runner has no independent source-manifest, publisher-pin,
    # and rules paths.  Therefore even a trust-anchor-matching blocker may only
    # prove which blocker bytes topology_policy trusts; it may never promote
    # vendor provenance from self-reported JSON fields.
    result['errors'].append(
        'static vendor source/pin/rules bundle was not independently verified')
    result['verified'] = False
    result['decision'] = 'BLOCKED'
    return result


def _sealed_release_pin_state(path=BRIDGE_MAP_BINDING_PATH):
    result = {
        'path': _workspace_relative(path),
        'source_sha256': None,
        'total_files': None,
        'matching_files': None,
        'mismatching_files': None,
        'mismatch_paths': [],
        'records': [],
        'valid': False,
        'errors': [],
    }
    try:
        raw = Path(path).resolve().read_bytes()
        source = raw.decode('utf-8')
        tree = ast.parse(source, filename=str(path))
    except (OSError, UnicodeDecodeError, SyntaxError) as error:
        result['errors'].append(
            '{}: {}'.format(type(error).__name__, error))
        return result
    result['source_sha256'] = _sha256(raw)
    assignments = {
        'EXPECTED_RELEASE_SHA256': [],
        'RELEASE_RELATIVE_PATHS': [],
    }
    for statement in tree.body:
        if not isinstance(statement, ast.Assign):
            continue
        for target in statement.targets:
            if not isinstance(target, ast.Name) or target.id not in assignments:
                continue
            try:
                value = ast.literal_eval(statement.value)
            except (ValueError, TypeError, SyntaxError) as error:
                result['errors'].append(
                    '{} is not a literal mapping: {}'.format(
                        target.id, error))
            else:
                assignments[target.id].append(value)
    for name, values in assignments.items():
        if len(values) != 1 or not isinstance(values[0], dict):
            result['errors'].append(
                '{} must have one literal dict assignment'.format(name))
    if result['errors']:
        return result
    expected = assignments['EXPECTED_RELEASE_SHA256'][0]
    relative_paths = assignments['RELEASE_RELATIVE_PATHS'][0]
    if (set(expected) != set(relative_paths)
            or len(expected) != EXPECTED['secure_release_validator']
            or len(set(relative_paths.values())) != len(relative_paths)):
        result['errors'].append(
            'sealed release pin/path mappings are not exact 14-file bijections')
        return result
    root = V1_ROOT.resolve()
    for name in sorted(expected):
        row = {
            'name': name,
            'path': relative_paths[name],
            'expected_sha256': expected[name],
            'actual_sha256': None,
            'matches': False,
            'errors': [],
        }
        if re.fullmatch(r'[0-9a-f]{64}', expected[name] or '') is None:
            row['errors'].append('expected pin is not lowercase SHA-256')
        relative = relative_paths[name]
        if not isinstance(relative, str) or not relative:
            row['errors'].append('relative path is missing')
        else:
            candidate = (V1_ROOT / relative).resolve()
            try:
                resolved_relative = candidate.relative_to(root).as_posix()
            except ValueError:
                row['errors'].append('release path escapes V1 package root')
            else:
                if resolved_relative != relative:
                    row['errors'].append(
                        'release path is not exact canonical relative path')
                try:
                    actual_raw = candidate.read_bytes()
                except OSError as error:
                    row['errors'].append(
                        '{}: {}'.format(type(error).__name__, error))
                else:
                    row['actual_sha256'] = _sha256(actual_raw)
        row['matches'] = (
            row['actual_sha256'] is not None
            and row['actual_sha256'] == row['expected_sha256'])
        result['records'].append(row)
        result['errors'].extend(
            '{}: {}'.format(relative_paths[name], error)
            for error in row['errors'])
    result['total_files'] = len(result['records'])
    result['matching_files'] = sum(
        int(row['matches']) for row in result['records'])
    result['mismatching_files'] = (
        result['total_files'] - result['matching_files'])
    result['mismatch_paths'] = sorted(
        row['path'] for row in result['records'] if not row['matches'])
    result['valid'] = not result['errors']
    return result


def _release_drift_file_binding(
        payload, count_semantics_valid, sealed_state=None):
    binding = {
        'expected_paths': sorted(BRIDGE_RELEASE_DRIFT_PATHS),
        'records': [],
        'sealed_release_pin_state': None,
        'eligible': False,
        'errors': [],
    }
    if sealed_state is None:
        sealed_state = _sealed_release_pin_state()
    binding['sealed_release_pin_state'] = sealed_state
    sealed_by_path = {
        row.get('path'): row for row in sealed_state.get('records', [])
        if isinstance(row, dict)}
    if sealed_state.get('valid') is not True:
        binding['errors'].append(
            'sealed bridge release pin mapping could not be verified')
    files = payload.get('files')
    if not isinstance(files, list):
        binding['errors'].append('drift files must be a list')
        return binding
    observed_paths = []
    root = V1_ROOT.resolve()
    for index, record in enumerate(files):
        row = {
            'index': index,
            'path': None,
            'expected_sha256': None,
            'declared_current_sha256': None,
            'actual_current_sha256': None,
            'current_hash_matches': False,
            'recommended_disposition': None,
            'valid': False,
            'errors': [],
        }
        if not isinstance(record, dict):
            row['errors'].append('record must be an object')
            binding['records'].append(row)
            continue
        relative = record.get('path')
        row['path'] = relative
        row['expected_sha256'] = record.get('expected_sha256')
        row['declared_current_sha256'] = record.get('current_sha256')
        row['recommended_disposition'] = record.get(
            'recommended_disposition')
        if not isinstance(relative, str) or not relative:
            row['errors'].append('path is missing')
        else:
            observed_paths.append(relative)
            candidate = (V1_ROOT / relative).resolve()
            try:
                resolved_relative = candidate.relative_to(root).as_posix()
            except ValueError:
                row['errors'].append('path escapes V1 package root')
            else:
                if resolved_relative != relative:
                    row['errors'].append(
                        'path is not the exact canonical V1 relative path')
                try:
                    actual_raw = candidate.read_bytes()
                except OSError as error:
                    row['errors'].append(
                        '{}: {}'.format(type(error).__name__, error))
                else:
                    row['actual_current_sha256'] = _sha256(actual_raw)
        for field in ('expected_sha256', 'declared_current_sha256'):
            if re.fullmatch(r'[0-9a-f]{64}', row[field] or '') is None:
                row['errors'].append('{} is not lowercase SHA-256'.format(
                    field))
        if (row['expected_sha256'] is not None
                and row['expected_sha256'] ==
                row['declared_current_sha256']):
            row['errors'].append('expected/current hashes do not show drift')
        sealed = sealed_by_path.get(relative)
        if sealed is None:
            row['errors'].append(
                'path is absent from sealed bridge release mapping')
        else:
            if row['expected_sha256'] != sealed.get('expected_sha256'):
                row['errors'].append(
                    'expected hash does not match sealed bridge release pin')
            if row['declared_current_sha256'] != sealed.get('actual_sha256'):
                row['errors'].append(
                    'declared current hash does not match sealed recomputation')
        row['current_hash_matches'] = (
            row['actual_current_sha256'] is not None
            and row['actual_current_sha256'] ==
            row['declared_current_sha256'])
        if not row['current_hash_matches']:
            row['errors'].append(
                'declared current hash does not match actual current bytes')
        if row['recommended_disposition'] != 'KEEP_BLOCKED_DO_NOT_UPDATE_PIN':
            row['errors'].append(
                'recommended disposition is not KEEP_BLOCKED_DO_NOT_UPDATE_PIN')
        row['valid'] = not row['errors']
        binding['records'].append(row)
    if (len(files) != len(BRIDGE_RELEASE_DRIFT_PATHS)
            or len(set(observed_paths)) != len(observed_paths)
            or set(observed_paths) != BRIDGE_RELEASE_DRIFT_PATHS):
        binding['errors'].append(
            'drift file set is not the exact fixed three-file allowlist')
    for row in binding['records']:
        binding['errors'].extend(
            '{}: {}'.format(row['path'] or '<missing>', error)
            for error in row['errors'])
    release_set = payload.get('release_set')
    if not isinstance(release_set, dict):
        release_set = {}
    metadata_exact = (
        payload.get('schema') == RELEASE_DRIFT_SCHEMA
        and payload.get('status') ==
        'BLOCKED_PIN_UPDATE_PROHIBITED_PENDING_ALL_GREEN'
        and payload.get('disposition') == 'do_not_update_pin'
        and payload.get('release_pin_updated') is False
        and payload.get('approval_audit_created') is False
        and count_semantics_valid
        and release_set.get('matching_files') == 11
        and release_set.get('mismatching_files') == 3
        and sealed_state.get('valid') is True
        and sealed_state.get('total_files') == 14
        and sealed_state.get('matching_files') == 11
        and sealed_state.get('mismatching_files') == 3
        and set(sealed_state.get('mismatch_paths', [])) ==
        BRIDGE_RELEASE_DRIFT_PATHS)
    if not metadata_exact:
        binding['errors'].append(
            'drift metadata is not the exact blocked 11-match/3-mismatch state')
    binding['eligible'] = not binding['errors']
    return binding


def _release_integrity_state(path=RELEASE_DRIFT_PATH):
    result = {
        'path': _workspace_relative(path),
        'expected_schema': RELEASE_DRIFT_SCHEMA,
        'schema': None,
        'artifact_sha256': None,
        'artifact_status': 'UNREADABLE',
        'disposition': None,
        'total_files': EXPECTED['secure_release_validator'],
        'matching_files': None,
        'mismatching_files': None,
        'drift_active': True,
        'decision': 'BLOCKED',
        'bridge_release_hash_binding': {
            'expected_paths': sorted(BRIDGE_RELEASE_DRIFT_PATHS),
            'records': [],
            'eligible': False,
            'errors': ['release drift artifact was not parsed'],
        },
        'errors': [],
    }
    try:
        payload, digest = _read_json_artifact(path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        result['errors'].append(
            '{}: {}'.format(type(error).__name__, error))
        return result
    result['artifact_sha256'] = digest
    if not isinstance(payload, dict):
        result['errors'].append('release drift artifact must be a JSON object')
        return result
    result['schema'] = payload.get('schema')
    result['artifact_status'] = payload.get('status', 'MISSING')
    result['disposition'] = payload.get('disposition')
    release_set = payload.get('release_set')
    if not isinstance(release_set, dict):
        release_set = {}
        result['errors'].append('release_set is missing')
    result['total_files'] = release_set.get('total_files')
    result['matching_files'] = release_set.get('matching_files')
    result['mismatching_files'] = release_set.get('mismatching_files')
    count_semantics_valid = (
        isinstance(result['total_files'], int)
        and isinstance(result['matching_files'], int)
        and isinstance(result['mismatching_files'], int)
        and result['total_files'] == EXPECTED['secure_release_validator']
        and result['matching_files'] + result['mismatching_files'] ==
        result['total_files'])
    result['bridge_release_hash_binding'] = _release_drift_file_binding(
        payload, count_semantics_valid)
    clear = (
        result['schema'] == RELEASE_DRIFT_SCHEMA
        and count_semantics_valid
        and result['mismatching_files'] == 0
        and result['artifact_status'] in {
            'VERIFIED_NO_RELEASE_DRIFT', 'CLOSED_NO_RELEASE_DRIFT'}
        and result['disposition'] == 'keep_existing_pin')
    if result['schema'] != RELEASE_DRIFT_SCHEMA:
        result['errors'].append('schema mismatch')
    if not count_semantics_valid:
        result['errors'].append('release_set count semantics are invalid')
    if result['mismatching_files'] != 0:
        result['errors'].append('sealed release hashes are mismatched')
    if result['artifact_status'] not in {
            'VERIFIED_NO_RELEASE_DRIFT', 'CLOSED_NO_RELEASE_DRIFT'}:
        result['errors'].append('release drift artifact is not closed')
    if result['disposition'] != 'keep_existing_pin':
        result['errors'].append('release disposition is not keep_existing_pin')
    result['drift_active'] = not clear
    result['decision'] = 'PASS' if clear else 'BLOCKED'
    return result


def _all_package_files():
    files = []
    for root in (V1_ROOT, BRIDGE_ROOT):
        files.extend(
            path for path in root.rglob('*')
            if path.is_file()
            and '__pycache__' not in path.parts
            and '.pytest_cache' not in path.parts
            and path.suffix != '.pyc'
        )
    return tuple(sorted(set(files), key=lambda path: path.as_posix()))


def _frozen_v1_test_paths():
    paths = tuple(sorted((V1_ROOT / 'test').glob('test_*.py')))
    return tuple(
        path for path in paths
        if path.name not in DELIVERY_AUDIT_TEST_NAMES)


def _delivery_audit_test_paths():
    return tuple(
        V1_ROOT / 'test' / name
        for name in sorted(DELIVERY_AUDIT_TEST_NAMES)
    )


def _current_audit_files():
    """Return every current package/audit input; report the observed count."""
    files = list(_all_package_files())
    files.extend(SHARED_AUDIT_FILES)
    files.extend(INTEGRATED_AUDIT_FILES)
    files.append(Path(__file__).resolve())
    return tuple(sorted(set(files), key=lambda path: path.as_posix()))


def _current_python_files():
    return tuple(
        path for path in _current_audit_files() if path.suffix == '.py')


def _is_authoritative_linux():
    return os.name == 'posix' and platform.system() == 'Linux'


def _redact_output_line(line):
    redaction_count = 0

    def redact_url(match):
        return '{}<REDACTED>:<REDACTED>@'.format(match.group(1))

    line, count = _URL_CREDENTIAL_PATTERN.subn(redact_url, line)
    redaction_count += count
    line, count = _BEARER_PATTERN.subn('Bearer <REDACTED>', line)
    redaction_count += count

    def redact_value(match):
        return '{}{}<REDACTED>'.format(match.group(1), match.group(2))

    line, count = _SECRET_VALUE_PATTERN.subn(redact_value, line)
    redaction_count += count
    truncated = len(line) > OUTPUT_SUMMARY_LINE_CHAR_LIMIT
    if truncated:
        marker = '...<truncated>'
        line = line[:OUTPUT_SUMMARY_LINE_CHAR_LIMIT - len(marker)] + marker
    return line, redaction_count, truncated


def _bounded_output_summary(raw):
    decoded = raw.decode('utf-8', errors='replace')
    lines = decoded.splitlines()
    head_count = min(len(lines), OUTPUT_SUMMARY_HEAD_LINES)
    tail_start = max(head_count, len(lines) - OUTPUT_SUMMARY_TAIL_LINES)
    head_source = lines[:head_count]
    tail_source = lines[tail_start:]
    redactions = 0
    truncated_lines = 0

    def process(source):
        nonlocal redactions, truncated_lines
        result = []
        for line in source:
            safe, count, truncated = _redact_output_line(line)
            redactions += count
            truncated_lines += int(truncated)
            result.append(safe)
        return result

    head = process(head_source)
    tail = process(tail_source)
    return {
        'decode': 'utf-8-replace',
        'head': head,
        'tail': tail,
        'original_line_count': len(lines),
        'selected_line_count': len(head) + len(tail),
        'omitted_middle_line_count': max(
            0, len(lines) - len(head) - len(tail)),
        'head_line_limit': OUTPUT_SUMMARY_HEAD_LINES,
        'tail_line_limit': OUTPUT_SUMMARY_TAIL_LINES,
        'line_char_limit': OUTPUT_SUMMARY_LINE_CHAR_LIMIT,
        'redaction_count': redactions,
        'truncated_line_count': truncated_lines,
    }


def _parse_pytest_failed_nodes(text, returncode, execution_error):
    matches = []
    malformed_line_numbers = []
    malformed_line_count = 0
    failed_prefixed_line_count = 0
    nodeid_redaction_count = 0
    nodeid_truncated_count = 0
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line.lstrip().startswith('FAILED'):
            continue
        failed_prefixed_line_count += 1
        match = _PYTEST_FAILED_PATTERN.match(line)
        if match is None:
            malformed_line_count += 1
            if len(malformed_line_numbers) < PYTEST_MALFORMED_LINE_REPORT_LIMIT:
                malformed_line_numbers.append(line_number)
            continue
        payload = match.group('payload').strip()
        nodeid = payload.split(' - ', 1)[0].rstrip()
        if (not nodeid
                or any(ord(character) < 32 for character in nodeid)):
            malformed_line_count += 1
            if len(malformed_line_numbers) < PYTEST_MALFORMED_LINE_REPORT_LIMIT:
                malformed_line_numbers.append(line_number)
            continue
        safe_nodeid, redactions, truncated = _redact_output_line(nodeid)
        nodeid_redaction_count += redactions
        nodeid_truncated_count += int(truncated)
        matches.append(safe_nodeid)
    unique_failed_nodeids = sorted(set(matches))
    failed_nodeids_truncated = (
        len(unique_failed_nodeids) > PYTEST_FAILED_NODE_REPORT_LIMIT)
    failed_nodeids = unique_failed_nodeids[:PYTEST_FAILED_NODE_REPORT_LIMIT]
    if execution_error is not None:
        parse_status = 'EXECUTION_ERROR'
    elif malformed_line_count:
        parse_status = 'MALFORMED_FAILURE_LINES'
    elif nodeid_redaction_count or nodeid_truncated_count:
        parse_status = 'REDACTED_OR_TRUNCATED_FAILURE_NODE'
    elif failed_nodeids_truncated:
        parse_status = 'TOO_MANY_FAILURE_NODES'
    elif failed_nodeids:
        parse_status = 'PARSED'
    elif returncode == 0:
        parse_status = 'NO_FAILURES'
    else:
        parse_status = 'UNPARSEABLE_FAILURE'
    return {
        'parse_status': parse_status,
        'failed_nodeids': failed_nodeids,
        'unique_failed_node_count': len(unique_failed_nodeids),
        'failed_nodeids_truncated': failed_nodeids_truncated,
        'matched_line_count': len(matches),
        'duplicate_line_count': len(matches) - len(unique_failed_nodeids),
        'failed_prefixed_line_count': failed_prefixed_line_count,
        'malformed_line_count': malformed_line_count,
        'malformed_line_numbers': malformed_line_numbers,
        'malformed_line_numbers_truncated': (
            malformed_line_count > len(malformed_line_numbers)),
        'nodeid_redaction_count': nodeid_redaction_count,
        'nodeid_truncated_count': nodeid_truncated_count,
    }


def _run(name, command, cwd, marker=None, count_pattern=None,
         expected_count=None):
    started = _utc_now()
    start_monotonic = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        stdout = completed.stdout
        stderr = completed.stderr
        returncode = completed.returncode
        execution_error = None
    except OSError as error:
        stdout = b''
        stderr = str(error).encode('utf-8', errors='replace')
        returncode = None
        execution_error = type(error).__name__
    combined = stdout + b'\n' + stderr
    text = combined.decode('utf-8', errors='replace')
    observed_count = None
    if count_pattern is not None:
        match = re.search(count_pattern, text)
        if match is not None:
            observed_count = int(match.group(1))
    marker_ok = marker is None or marker in text
    count_ok = expected_count is None or observed_count == expected_count
    passed = returncode == 0 and marker_ok and count_ok
    if name == 'bridge_pytest':
        pytest_failures = _parse_pytest_failed_nodes(
            text, returncode, execution_error)
    else:
        pytest_failures = {
            'parse_status': 'NOT_APPLICABLE',
            'failed_nodeids': [],
            'matched_line_count': 0,
            'duplicate_line_count': 0,
            'failed_prefixed_line_count': 0,
            'malformed_line_count': 0,
            'malformed_line_numbers': [],
            'nodeid_redaction_count': 0,
            'nodeid_truncated_count': 0,
        }
    return {
        'name': name,
        'status': 'PASS' if passed else 'FAIL',
        'command': list(command),
        'cwd': str(cwd),
        'started_utc': started,
        'finished_utc': _utc_now(),
        'duration_s': round(time.monotonic() - start_monotonic, 6),
        'returncode': returncode,
        'execution_error': execution_error,
        'required_marker': marker,
        'expected_count': expected_count,
        'observed_count': observed_count,
        'stdout_sha256': _sha256(stdout),
        'stderr_sha256': _sha256(stderr),
        'stdout_bytes': len(stdout),
        'stderr_bytes': len(stderr),
        'output_integrity': {
            'returncode': returncode,
            'raw_content_persisted': False,
            'stdout': {
                'sha256': _sha256(stdout),
                'bytes': len(stdout),
            },
            'stderr': {
                'sha256': _sha256(stderr),
                'bytes': len(stderr),
            },
        },
        'output_summary': {
            'redaction_policy': (
                'COMMON_SECRET_TOKEN_PASSWORD_BEARER_URL_CREDENTIALS'),
            'stdout': _bounded_output_summary(stdout),
            'stderr': _bounded_output_summary(stderr),
        },
        'pytest_failures': pytest_failures,
    }


def _run_py_compile(name, paths, expected_count=None):
    if expected_count is not None and len(paths) != expected_count:
        return {
            'name': name,
            'status': 'FAIL',
            'expected_count': expected_count,
            'observed_count': len(paths),
            'errors': ['frozen Python file set count changed'],
        }
    errors = []
    for path in paths:
        try:
            py_compile.compile(str(path), doraise=True)
        except py_compile.PyCompileError as error:
            errors.append('{}: {}'.format(
                path.relative_to(WORKSPACE_ROOT).as_posix(), error.msg))
    return {
        'name': name,
        'status': 'PASS' if not errors else 'FAIL',
        'expected_count': expected_count,
        'observed_count': len(paths),
        'errors': errors,
    }


def _run_whitespace(name, paths, expected_count=None):
    errors = []
    for path in paths:
        try:
            payload = path.read_bytes()
        except OSError as error:
            errors.append('{}: {}'.format(
                path.relative_to(WORKSPACE_ROOT).as_posix(), error))
            continue
        if b'\r\n' in payload or b'\r' in payload:
            errors.append('{}: CR line ending'.format(
                path.relative_to(WORKSPACE_ROOT).as_posix()))
        if payload and not payload.endswith(b'\n'):
            errors.append('{}: missing final newline'.format(
                path.relative_to(WORKSPACE_ROOT).as_posix()))
        for line_number, line in enumerate(payload.split(b'\n'), 1):
            if line.endswith((b' ', b'\t')):
                errors.append('{}:{}: trailing whitespace'.format(
                    path.relative_to(WORKSPACE_ROOT).as_posix(), line_number))
    count_ok = expected_count is None or len(paths) == expected_count
    if not count_ok:
        errors.insert(0, 'frozen whitespace file set count changed')
    return {
        'name': name,
        'status': 'PASS' if count_ok and not errors else 'FAIL',
        'expected_count': expected_count,
        'observed_count': len(paths),
        'issue_count': len(errors),
        'errors': errors,
    }


def _integrated_closure_check(name, assertions):
    errors = []
    for description, condition in assertions:
        if not condition:
            errors.append(description)
    return {
        'name': name,
        'status': 'PASS' if not errors else 'FAIL',
        'assertion_count': len(assertions),
        'errors': errors,
    }


def _integrated_topology_contract():
    policy = (BRIDGE_ROOT / 'src' / 'limo_cleanup_ros1_base' /
              'topology_policy.py').read_text(encoding='utf-8')
    verifier = (BRIDGE_ROOT / 'scripts' /
                'verify_ros1_base_bridge_topology.py').read_text(
                    encoding='utf-8')
    production = (BRIDGE_ROOT / 'scripts' /
                  'run_v2_bridged_navigation.py').read_text(encoding='utf-8')
    zero_stage = INTEGRATED_AUDIT_FILES[0].read_text(encoding='utf-8')
    tests = (BRIDGE_ROOT / 'test' / 'test_topology_policy.py').read_text(
        encoding='utf-8')
    return _integrated_closure_check(
        'integrated_topology_verifier_contract', (
            ('zero-stage canonical node missing',
             "zero_stage_verifier_node: str = '/verify_ros1_base_zero_stage_topology'"
             in policy),
            ('production canonical node missing',
             "production_verifier_node: str = '/verify_ros1_base_bridge_topology'"
             in policy),
            ('zero-stage transition does not allow the canonical production peer',
             'expected.production_verifier_node' in policy
             and "monitor_role == 'zero_stage'" in policy),
            ('production does not require the canonical zero-stage peer',
             'expected.zero_stage_verifier_node' in policy
             and "monitor_role == 'production'" in policy),
            ('zero-stage and navigation READY topics are not isolated',
             "ZERO_STAGE_READY_TOPIC = '/cleanup/base/zero_stage_topology_ready'"
             in verifier
             and "PRODUCTION_READY_TOPIC = '/cleanup/navigation/ros1_topology_ready'"
             in verifier),
            ('zero-stage runner lacks explicit isolated role/name/topic',
             zero_stage.count(
                 '__name:=/verify_ros1_base_zero_stage_topology') == 2
             and zero_stage.count(
                 '_ready_topic:=/cleanup/base/zero_stage_topology_ready') == 2
             and zero_stage.count('_monitor_role:=zero_stage') == 2),
            ('production runner lacks explicit canonical role/name',
             production.count(
                 "'__name:=/verify_ros1_base_bridge_topology'") == 2
             and production.count("'_monitor_role:=production'") == 2),
            ('missing/rogue peer negative contracts are absent',
             'invalid_subscribers' in tests
             and "'/rogue_monitor'" in tests
             and "monitor_role='production'" in tests),
        ))


def _integrated_install_contract():
    runner = (BRIDGE_ROOT / 'scripts' /
              'run_v2_bridged_navigation.py').read_text(encoding='utf-8')
    runner_tests = (BRIDGE_ROOT / 'test' /
                    'test_runner_barrier.py').read_text(encoding='utf-8')
    setup_source = INTEGRATED_AUDIT_FILES[1].read_text(encoding='utf-8')
    module_source = INTEGRATED_AUDIT_FILES[2].read_text(encoding='utf-8')
    module_test = INTEGRATED_AUDIT_FILES[3].read_text(encoding='utf-8')
    try:
        ast.parse(module_source)
        module_syntax_ok = True
    except SyntaxError:
        module_syntax_ok = False
    return _integrated_closure_check(
        'integrated_verifier_install_contract', (
            ('runner does not use the exact installed console entry',
             "'ros2', 'run', 'limo_cleanup_base'" in runner
             and "'zero_stage_handoff_verifier'" in runner),
            ('runner still guesses a workspace script path',
             '_workspace_script' not in runner
             and "parents[3] / 'scripts'" not in runner),
            ('ROS2 setup console entry is missing',
             'zero_stage_handoff_verifier = ' in setup_source
             and 'limo_cleanup_base.zero_stage_handoff_verifier:main'
             in setup_source),
            ('installed verifier module is missing or invalid Python',
             INTEGRATED_AUDIT_FILES[2].is_file() and module_syntax_ok),
            ('installed verifier is not read-only',
             'create_publisher' not in module_source
             and 'create_subscription' not in module_source),
            ('missing-entry/non-PASS fail-closed tests are absent',
             'Package not found' in runner_tests
             and 'ROS2_ZERO_STAGE_HANDOFF_BLOCKED' in runner_tests
             and 'with pytest.raises(RuntimeError' in runner_tests),
            ('ROS2 package contract test is absent',
             'test_handoff_verifier_is_read_only_and_exact_owner_only'
             in module_test),
        ))


def _integrated_closure_checks():
    checks = []
    for name, function in (
            ('integrated_topology_verifier_contract',
             _integrated_topology_contract),
            ('integrated_verifier_install_contract',
             _integrated_install_contract)):
        try:
            checks.append(function())
        except Exception as error:
            checks.append({
                'name': name,
                'status': 'FAIL',
                'assertion_count': 0,
                'errors': ['{}: {}'.format(type(error).__name__, error)],
            })
    return tuple(checks)


def _integrated_closure_attribution(checks):
    by_name = {check.get('name'): check for check in checks}
    resolved = []
    blocked = []
    closure_check_names = set()
    for closure in INTEGRATED_SOFTWARE_CLOSURES:
        check_name = closure['check']
        closure_check_names.add(check_name)
        expected = closure['expected_assertion_count']
        check = by_name.get(check_name)
        observed = check.get('assertion_count') if check else None
        check_status = check.get('status') if check else 'MISSING'
        exact_pass = check_status == 'PASS' and observed == expected
        row = {
            'id': closure['id'],
            'check': check_name,
            'expected_assertion_count': expected,
            'observed_assertion_count': observed,
            'check_status': check_status,
            'status': 'CLOSED' if exact_pass else 'BLOCKED',
        }
        if exact_pass:
            resolved.append(row)
        else:
            row['reason'] = (
                'integrated closure requires an exact PASS with {0}/{0} '
                'assertions'.format(expected))
            blocked.append(row)
    return resolved, blocked, closure_check_names


def _bridge_release_integrity_attribution(check, release_state):
    parser = check.get('pytest_failures')
    if not isinstance(parser, dict):
        return False
    failed = parser.get('failed_nodeids')
    return (
        parser.get('parse_status') == 'PARSED'
        and isinstance(failed, list)
        and set(failed) == BRIDGE_RELEASE_HASH_FAILURE_ALLOWLIST
        and len(failed) == len(BRIDGE_RELEASE_HASH_FAILURE_ALLOWLIST)
        and check.get('execution_error') is None
        and check.get('returncode') == 1
        and check.get('expected_count') == EXPECTED['bridge_pytest']
        and check.get('observed_count') ==
        EXPECTED['bridge_pytest'] - len(BRIDGE_RELEASE_HASH_FAILURE_ALLOWLIST)
        and release_state.get(
            'bridge_release_hash_binding', {}).get('eligible') is True)


def _check_failure_blockers(checks, excluded_names, release_state):
    blockers = []
    for check in checks:
        if (check.get('status') == 'PASS'
                or check.get('name') in excluded_names):
            continue
        name = check.get('name', 'unnamed_check')
        if name == 'secure_release_validator':
            blocker_id = 'SECURE_RELEASE_VALIDATOR_FAILED'
            category = 'release_integrity'
            attribution = 'SECURE_RELEASE_VALIDATOR'
        elif (name == 'bridge_pytest'
              and _bridge_release_integrity_attribution(
                  check, release_state)):
            blocker_id = 'BRIDGE_FROZEN_RELEASE_HASH_ASSERTION_FAILED'
            category = 'release_integrity'
            attribution = (
                'EXACT_FAILED_NODE_ALLOWLIST_AND_THREE_FILE_DRIFT_BINDING')
        else:
            normalized = re.sub(
                r'[^A-Z0-9]+', '_', name.upper()).strip('_')
            blocker_id = 'OFFLINE_CHECK_FAILED_{}'.format(normalized)
            category = 'offline_regression'
            attribution = 'FAIL_CLOSED_GENERIC_OFFLINE_FAILURE'
        blockers.append({
            'id': blocker_id,
            'category': category,
            'attribution': attribution,
            'status': 'BLOCKED',
            'check': name,
            'check_status': check.get('status', 'MISSING'),
            'expected_count': check.get('expected_count'),
            'observed_count': check.get('observed_count'),
            'pytest_failure_parse_status': check.get(
                'pytest_failures', {}).get('parse_status'),
            'pytest_failed_nodeids': check.get(
                'pytest_failures', {}).get('failed_nodeids', []),
        })
    return blockers


def _apply_blocker_attribution(
        report, vendor_state=None, release_state=None):
    checks = report['checks']
    if vendor_state is None:
        vendor_state = _vendor_provenance_state()
    if release_state is None:
        release_state = _release_integrity_state()
    report['vendor_provenance'] = vendor_state
    report['release_integrity'] = release_state

    validator = next(
        (check for check in checks
         if check.get('name') == 'secure_release_validator'), None)
    release_state['secure_release_validator'] = {
        'status': validator.get('status') if validator else 'NOT_RUN',
        'expected_count': (
            validator.get('expected_count') if validator else
            EXPECTED['secure_release_validator']),
        'observed_count': validator.get('observed_count') if validator else None,
    }

    resolved, closure_blockers, closure_names = (
        _integrated_closure_attribution(checks))
    independent = _check_failure_blockers(
        checks, closure_names, release_state)
    if release_state.get('drift_active') is not False:
        independent.append({
            'id': 'V1_FROZEN_RELEASE_HASH_DRIFT',
            'category': 'release_integrity',
            'status': 'BLOCKED',
            'source': release_state.get('path'),
            'artifact_status': release_state.get('artifact_status'),
            'matching_files': release_state.get('matching_files'),
            'mismatching_files': release_state.get('mismatching_files'),
        })
    if vendor_state.get('verified') is not True:
        independent.append({
            'id': 'V1_VENDOR_PROVENANCE_UNVERIFIED',
            'category': 'vendor_provenance',
            'status': 'BLOCKED',
            'source': vendor_state.get('path'),
            'artifact_status': vendor_state.get('artifact_status'),
            'failure_code': vendor_state.get(
                'failure_code', 'TF_VENDOR_CONTRACT_UNVERIFIED'),
        })
    if report.get('platform_blocker'):
        independent.append({
            'id': 'NON_AUTHORITATIVE_PLATFORM',
            'category': 'execution_platform',
            'status': 'BLOCKED',
            'reason': report['platform_blocker'],
        })
    lineage = report.get('evidence_lineage')
    if not isinstance(lineage, dict) or lineage.get('verified') is not True:
        independent.append({
            'id': 'EVIDENCE_LINEAGE_INTEGRITY_FAILED',
            'category': 'release_integrity',
            'status': 'BLOCKED',
            'attribution': 'IMMUTABLE_EVIDENCE_HASH_OR_READ_FAILURE',
            'errors': (
                lineage.get('errors', ['evidence lineage is missing'])
                if isinstance(lineage, dict) else
                ['evidence lineage is missing']),
        })

    active = closure_blockers + independent
    checks_pass = bool(checks) and all(
        check.get('status') == 'PASS' for check in checks)
    report['check_matrix_pass'] = checks_pass
    report['active_software_blockers'] = active
    report['software_release_pass'] = checks_pass and not active
    report['software_release_ready'] = report['software_release_pass']

    combined = report['integrated_combined_deployment']
    combined['closure_status'] = (
        'PASS' if not closure_blockers else 'BLOCKED')
    combined['software_blockers'] = closure_blockers
    combined['resolved_software_blockers'] = resolved
    combined['independent_active_blockers'] = independent
    report['integrated_software_ready'] = (
        report['software_release_pass'] and not closure_blockers)
    combined['software_status'] = (
        'PASS' if report['integrated_software_ready'] else 'BLOCKED')


def _field_acceptance_template():
    return {
        name: {
            'status': 'NOT_RUN',
            'template_only': True,
            'real_machine_evidence': False,
        }
        for name in FIELD_ITEMS
    }


def _authorization_template():
    return {
        'template_only': True,
        'status': 'NOT_RUN',
        'dedicated_field_orchestrator_present': False,
        'execution_ready': False,
        'decision': 'BLOCKED',
        'classes': {
            name: {
                'status': 'NOT_RUN',
                'template_only': True,
                'execution_ready': False,
                'decision': 'BLOCKED',
            }
            for name in (
                'hardware_read_only',
                'zero_motion_localization',
                'real_motion',
            )
        },
    }


def _base_report():
    vendor_state = _vendor_provenance_state()
    release_state = _release_integrity_state()
    independent = []
    if release_state['drift_active']:
        independent.append({
            'id': 'V1_FROZEN_RELEASE_HASH_DRIFT',
            'category': 'release_integrity',
            'status': 'BLOCKED',
            'source': release_state['path'],
        })
    if not vendor_state['verified']:
        independent.append({
            'id': 'V1_VENDOR_PROVENANCE_UNVERIFIED',
            'category': 'vendor_provenance',
            'status': 'BLOCKED',
            'source': vendor_state['path'],
            'failure_code': vendor_state['failure_code'],
        })
    return {
        'schema': SCHEMA,
        'decision_model': DECISION_MODEL,
        'generated_utc': _utc_now(),
        'workspace': str(WORKSPACE_ROOT),
        'evidence_lineage': _evidence_lineage(),
        'platform': {
            'system': platform.system(),
            'release': platform.release(),
            'python': platform.python_version(),
            'os_name': os.name,
        },
        'safety': {
            'ros_started': False,
            'hardware_accessed': False,
            'goal_sent': False,
            'twist_published': False,
        },
        'expected_counts': dict(EXPECTED),
        'checks': [],
        'check_matrix_pass': False,
        'vendor_provenance': vendor_state,
        'release_integrity': release_state,
        'active_software_blockers': independent,
        'software_release_pass': False,
        'software_release_ready': False,
        'integrated_software_ready': False,
        'field_acceptance': _field_acceptance_template(),
        'field_acceptance_complete': False,
        'field_evidence_complete': False,
        'delivery_ready': False,
        'field_authorization': _authorization_template(),
        'deployment': {
            'autostart': False,
            'autostart_policy': 'NO_AUTOSTART',
            'native': {
                'execution_status': 'BLOCKED',
                'template_only': True,
            },
        },
        'integrated_combined_deployment': {
            'software_status': 'BLOCKED',
            'closure_status': 'NOT_EVALUATED',
            'execution_status': 'BLOCKED',
            'template_only': True,
            'software_blockers': [
                {'id': item['id'], 'status': 'BLOCKED'}
                for item in INTEGRATED_SOFTWARE_CLOSURES
            ],
            'resolved_software_blockers': [],
            'independent_active_blockers': independent,
        },
    }


def _json_bytes(value):
    return (json.dumps(
        value, indent=2, sort_keys=True, ensure_ascii=False) + '\n').encode(
            'utf-8')


def _reserved_evidence_paths():
    paths = {
        Path(entry['path']).resolve()
        for entry in SUPERSEDED_EVIDENCE_REPORTS}
    paths.add(Path(DIRECT_AUTHORITY_PREDECESSOR['report']['path']).resolve())
    paths.add(Path(DIRECT_AUTHORITY_PREDECESSOR['index']['path']).resolve())
    return paths


def _write_exclusive_bytes(path, payload):
    target = Path(path).resolve()
    if target in _reserved_evidence_paths():
        raise ValueError(
            'reserved immutable evidence path cannot be a report target: '
            '{}'.format(_workspace_relative(target)))
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(
        str(target), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            descriptor = None
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        if descriptor is not None:
            os.close(descriptor)
    return target


def _write_exclusive(path, report):
    return _write_exclusive_bytes(path, _json_bytes(report))


def _lineage_generation_id():
    lines = [
        'protocol=claim-pending-candidate-committed-index/v2',
        'claim_schema={}'.format(AUTHORITY_CLAIM_SCHEMA),
        'index_schema={}'.format(AUTHORITY_INDEX_SCHEMA),
        'predecessor_report={}'.format(
            DIRECT_AUTHORITY_PREDECESSOR['report']['sha256']),
        'predecessor_index={}'.format(
            DIRECT_AUTHORITY_PREDECESSOR['index']['sha256']),
    ]
    lines.extend(
        'historical_stale={}'.format(value)
        for value in sorted(
            entry['sha256'] for entry in SUPERSEDED_EVIDENCE_REPORTS))
    return _sha256(('\n'.join(lines) + '\n').encode('ascii'))


def _authority_claim_path():
    return Path(AUTHORITY_ROOT).resolve() / (
        'v1_frozen_release_authority_claim_{}.json'.format(
            _lineage_generation_id()))


def _authority_index_path(report_path):
    del report_path
    return Path(AUTHORITY_ROOT).resolve() / (
        'v1_frozen_release_authority_{}.json'.format(
            _lineage_generation_id()))


def _authority_fault(stage):
    del stage


def _prepare_authority_candidate(
        report, report_path, claim_path, index_path):
    lineage = report['evidence_lineage']
    evidence_id = Path(report_path).stem
    evaluated = {
        'software_release_pass': report['software_release_pass'],
        'software_release_ready': report['software_release_ready'],
        'integrated_software_ready': report['integrated_software_ready'],
        'delivery_ready': report['delivery_ready'],
        'field_evidence_complete': report['field_evidence_complete'],
    }
    lineage['authority_candidate'] = {
        'artifact_role': 'READINESS_CANDIDATE',
        'evidence_id': evidence_id,
        'path': _workspace_relative(report_path),
        'claim_path': _workspace_relative(claim_path),
        'authority_index_path': _workspace_relative(index_path),
        'lineage_generation_id': _lineage_generation_id(),
        'lifecycle': PENDING_AUTHORITY_LIFECYCLE,
        'is_current': False,
        'relationship': 'PROPOSED_SUCCESSOR_TO_PREDECESSOR',
        'publication_state': 'PENDING_AUTHORITY_INDEX',
        'release_decision': 'BLOCKED_PENDING_AUTHORITY_INDEX',
        'evaluated_decisions': evaluated,
    }
    lineage['direct_authority_predecessor']['successor_relationship'] = (
        'PROPOSED_SUCCESSOR_TO')
    for stale in lineage['supersedes']:
        stale['retained_by_candidate_evidence_id'] = evidence_id

    report['authority_publication'] = {
        'status': 'PENDING_AUTHORITY_INDEX',
        'authoritative': False,
        'claim_path': _workspace_relative(claim_path),
        'index_path': _workspace_relative(index_path),
        'failure_policy': 'FAIL_CLOSED_NO_AUTOMATIC_RECOVERY',
    }
    report['software_release_pass'] = False
    report['software_release_ready'] = False
    report['integrated_software_ready'] = False
    report['delivery_ready'] = False
    report['field_evidence_complete'] = False
    report['integrated_combined_deployment']['software_status'] = 'BLOCKED'
    return evaluated


def _recorded_path(value):
    path = Path(value)
    return path.resolve() if path.is_absolute() else (WORKSPACE_ROOT / path).resolve()


def _existing_generation_state(claim_path, index_path):
    result = {
        'state': 'CLAIM_INVALID',
        'claim_path': _workspace_relative(claim_path),
        'index_path': _workspace_relative(index_path),
        'candidate_path': None,
    }
    try:
        claim = json.loads(Path(claim_path).read_text(encoding='utf-8'))
    except (OSError, UnicodeError, ValueError):
        return result
    candidate_value = claim.get('candidate', {}).get('path')
    candidate_path = (
        _recorded_path(candidate_value) if isinstance(candidate_value, str)
        else None)
    result['candidate_path'] = (
        _workspace_relative(candidate_path) if candidate_path else None)
    if Path(index_path).exists():
        result['state'] = 'INDEX_PRESENT_EXISTING_GENERATION'
    elif candidate_path is not None and candidate_path.exists():
        result['state'] = 'CANDIDATE_WITHOUT_INDEX'
    else:
        result['state'] = 'CLAIM_WITHOUT_CANDIDATE'
    return result


def _publish_generation_claim(claim_path, index_path, claim):
    try:
        _write_exclusive(claim_path, claim)
    except FileExistsError as error:
        state = _existing_generation_state(claim_path, index_path)
        raise AuthorityGenerationBlockedError(
            '{}: {}'.format(state['state'], json.dumps(
                state, sort_keys=True))) from error


def _publish_authority_index(index_path, index):
    target = Path(index_path).resolve()
    if target in _reserved_evidence_paths():
        raise ValueError('authority index path is reserved')
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = _json_bytes(index)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix='.{}.'.format(target.name), suffix='.tmp',
        dir=str(target.parent))
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            descriptor = None
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        _authority_fault('before_index_link')
        os.link(str(temporary), str(target))
        directory_descriptor = os.open(str(target.parent), os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
        _authority_fault('after_index_link')
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _superseded_predecessor_bundle(predecessor):
    bundle = json.loads(json.dumps(predecessor))
    bundle['relationship'] = 'SUPERSEDED_BY_COMMITTED_SUCCESSOR_INDEX'
    bundle['successor_relationship'] = 'SUPERSEDES_PREDECESSOR_BUNDLE'
    bundle['report']['lifecycle'] = 'SUPERSEDED_PREDECESSOR_REPORT'
    bundle['index']['lifecycle'] = 'SUPERSEDED_PREDECESSOR_INDEX'
    return bundle


def _write_report_bundle(report_path, report):
    target = Path(report_path).resolve()
    authority_root = Path(AUTHORITY_ROOT).resolve()
    if target.parent != authority_root:
        raise ValueError(
            'authoritative candidate must be created directly under {}'.format(
                authority_root))
    claim_path = _authority_claim_path()
    index_path = _authority_index_path(target)

    # Re-read every immutable predecessor immediately before attribution and
    # serialization so a long-running regression cannot reuse an early hash.
    report['evidence_lineage'] = _evidence_lineage()
    _apply_blocker_attribution(
        report, report.get('vendor_provenance'), report.get('release_integrity'))
    if report['evidence_lineage'].get('verified') is not True:
        raise AuthorityGenerationBlockedError(
            'PREDECESSOR_OR_LINEAGE_INVALID: {}'.format(json.dumps(
                report['evidence_lineage'].get('errors', []),
                sort_keys=True)))
    evaluated = _prepare_authority_candidate(
        report, target, claim_path, index_path)
    candidate_bytes = _json_bytes(report)
    candidate_sha256 = _sha256(candidate_bytes)
    claim = {
        'schema': AUTHORITY_CLAIM_SCHEMA,
        'artifact_role': 'AUTHORITY_GENERATION_CLAIM',
        'lifecycle': 'IMMUTABLE_AUTHORITY_CLAIM',
        'is_current': False,
        'created_utc': _utc_now(),
        'lineage_generation_id': _lineage_generation_id(),
        'authority_index_path': _workspace_relative(index_path),
        'candidate': {
            'evidence_id': target.stem,
            'path': _workspace_relative(target),
            'sha256': candidate_sha256,
            'bytes': len(candidate_bytes),
            'schema': SCHEMA,
            'lifecycle': PENDING_AUTHORITY_LIFECYCLE,
        },
        'predecessor_authority_bundle': report[
            'evidence_lineage']['direct_authority_predecessor'],
        'recovery_policy': 'FAIL_CLOSED_MANUAL_AUDIT_REQUIRED',
    }
    _publish_generation_claim(claim_path, index_path, claim)
    _authority_fault('after_claim_publish')
    _write_exclusive_bytes(target, candidate_bytes)
    _authority_fault('after_candidate_publish')

    claim_bytes = Path(claim_path).read_bytes()
    written_candidate = target.read_bytes()
    if (_sha256(written_candidate) != claim['candidate']['sha256']
            or len(written_candidate) != claim['candidate']['bytes']):
        raise AuthorityGenerationBlockedError(
            'candidate bytes do not match the immutable generation claim')
    index = {
        'schema': AUTHORITY_INDEX_SCHEMA,
        'artifact_role': 'AUTHORITY_INDEX',
        'lifecycle': 'COMMITTED_AUTHORITY_INDEX',
        'generated_utc': _utc_now(),
        'lineage_generation_id': _lineage_generation_id(),
        'selected_claim': {
            'path': _workspace_relative(claim_path),
            'sha256': _sha256(claim_bytes),
            'bytes': len(claim_bytes),
            'schema': AUTHORITY_CLAIM_SCHEMA,
        },
        'current_authoritative': {
            'evidence_id': target.stem,
            'path': _workspace_relative(target),
            'sha256': _sha256(written_candidate),
            'bytes': len(written_candidate),
            'lifecycle': CURRENT_AUTHORITATIVE_LIFECYCLE,
            'unique_authoritative_leaf': True,
            'lineage_generation_id': _lineage_generation_id(),
            'uniqueness_basis': (
                'ATOMIC_O_EXCL_CLAIM_AND_FIXED_COMMIT_INDEX'),
        },
        'authority_resolution': (
            'CURRENT_DERIVED_FROM_UNIQUE_VALID_COMMITTED_INDEX'),
        'commit_origin': 'NORMAL_PUBLICATION',
        'supersedes_predecessor_bundle': _superseded_predecessor_bundle(
            report['evidence_lineage']['direct_authority_predecessor']),
        'lineage': {
            'decision': report['evidence_lineage']['decision'],
            'verified': report['evidence_lineage']['verified'],
            'required_for_software_release_pass': True,
            'supersedes': report['evidence_lineage']['supersedes'],
        },
        'software_release_pass': evaluated['software_release_pass'],
        'software_release_ready': evaluated['software_release_ready'],
        'integrated_software_ready': evaluated['integrated_software_ready'],
        'delivery_ready': evaluated['delivery_ready'],
        'field_evidence_complete': evaluated['field_evidence_complete'],
        'candidate_top_level_readiness_forced_blocked': True,
    }
    _publish_authority_index(index_path, index)
    return index


def _mark_self_test_non_authoritative(report, report_path=None):
    lineage = _evidence_lineage()
    lineage['authority_candidate'] = None
    lineage['self_test_artifact'] = {
        'evidence_id': (
            Path(report_path).stem if report_path is not None else None),
        'path': (
            _workspace_relative(report_path)
            if report_path is not None else None),
        'lifecycle': 'NON_AUTHORITATIVE_SELF_TEST',
        'relationship': 'DOES_NOT_SUPERSEDE_RELEASE_EVIDENCE',
        'authority_index_created': False,
    }
    report['evidence_lineage'] = lineage


def _matrix():
    python = sys.executable
    return (
        ('bridge_pytest',
         (python, '-m', 'pytest', '-q'),
         BRIDGE_ROOT,
         '122 passed',
         r'(\d+)\s+passed',
         EXPECTED['bridge_pytest']),
        ('secure_release_validator',
         (python, str(BRIDGE_ROOT / 'test' / 'run_release_validator.py')),
         WORKSPACE_ROOT,
         'VALIDATE_RELEASE_FILES_PASS:14',
         r'VALIDATE_RELEASE_FILES_PASS:(\d+)',
         EXPECTED['secure_release_validator']),
        ('cross_package_groups',
         (python, str(WORKSPACE_ROOT / 'scripts' /
                      'test_ros1_base_bridge_offline.py')),
         WORKSPACE_ROOT,
         'ROS1_BASE_BRIDGE_OFFLINE_TEST_PASS: 9 groups',
         r'ROS1_BASE_BRIDGE_OFFLINE_TEST_PASS:\s+(\d+)\s+groups',
         EXPECTED['cross_package_groups']),
        ('overlay_static',
         (python, str(V1_ROOT / 'scripts' / 'audit_v1_overlay.py')),
         WORKSPACE_ROOT,
         'V1_OVERLAY_STATIC_PASS', None, None),
        ('profile_static',
         (python, str(V1_ROOT / 'scripts' / 'validate_v1_profile.py'),
          '--stage', 'scan'),
         WORKSPACE_ROOT,
         'V1_PROFILE_STATIC_PASS', None, None),
        ('catkin_static',
         (python, str(WORKSPACE_ROOT / 'scripts' /
                      'audit_ros1_catkin_overlay.py')),
         WORKSPACE_ROOT,
         'ROS1_CATKIN_OVERLAY_AUDIT_PASS', None, None),
    )


def _run_unittest_suite(name, paths, expected_count=None):
    loader = unittest.defaultTestLoader
    suite = unittest.TestSuite()
    for path in paths:
        suite.addTests(loader.discover(
            str(path.parent), pattern=path.name,
            top_level_dir=str(path.parent)))
    with open(os.devnull, 'w') as sink:
        result = unittest.TextTestRunner(
            stream=sink, verbosity=0).run(suite)
    passed = result.wasSuccessful()
    if expected_count is not None:
        passed = passed and result.testsRun == expected_count
    return {
        'name': name,
        'status': 'PASS' if passed else 'FAIL',
        'expected_count': expected_count,
        'observed_count': result.testsRun,
        'failure_count': len(result.failures),
        'error_count': len(result.errors),
        'skipped_count': len(result.skipped),
    }


def _run_v1_suites():
    test_root = V1_ROOT / 'test'
    all_paths = tuple(sorted(test_root.glob('test_*.py')))
    core_paths = _frozen_v1_test_paths()
    delivery_paths = _delivery_audit_test_paths()
    missing_delivery = tuple(
        path for path in delivery_paths if not path.is_file())
    if missing_delivery:
        return ({
            'name': 'v1_delivery_audit_classification',
            'status': 'FAIL',
            'expected_count': len(DELIVERY_AUDIT_TEST_NAMES),
            'observed_count': len(delivery_paths) - len(missing_delivery),
            'missing_modules': [path.name for path in missing_delivery],
        },)
    classified = set(core_paths) | set(delivery_paths)
    if set(all_paths) != classified:
        return ({
            'name': 'v1_test_classification',
            'status': 'FAIL',
            'expected_count': len(all_paths),
            'observed_count': len(classified),
            'unclassified': [
                path.name for path in all_paths if path not in classified],
        },)
    return (
        _run_unittest_suite(
            'v1_frozen_core_unittest', core_paths,
            EXPECTED['v1_frozen_core_unittest']),
        _run_unittest_suite(
            'v1_delivery_audit_unittest', delivery_paths,
            EXPECTED['v1_delivery_audit_unittest']),
        _run_unittest_suite(
            'v1_package_discovery', all_paths,
            EXPECTED['v1_package_discovery']),
    )


def run_complete_matrix(report_path):
    report = _base_report()
    if not _is_authoritative_linux():
        report['platform_blocker'] = (
            'Complete evidence requires Linux/POSIX; no checks were skipped '
            'or downgraded to PASS.')
        _apply_blocker_attribution(report)
        index = _write_report_bundle(report_path, report)
        report['authority_commit_result'] = index
        return report, 2
    report['checks'].extend(_run_v1_suites())
    for args in _matrix():
        report['checks'].append(_run(*args))
    report['checks'].extend(_integrated_closure_checks())
    current_files = _current_audit_files()
    report['checks'].append(_run_py_compile(
        'current_audit_py_compile', _current_python_files()))
    report['checks'].append(_run_whitespace(
        'current_audit_no_index_whitespace', current_files))
    _apply_blocker_attribution(report)
    # Field evidence is never inferred from software checks.
    report['field_acceptance_complete'] = False
    report['field_evidence_complete'] = False
    report['delivery_ready'] = False
    index = _write_report_bundle(report_path, report)
    report['authority_commit_result'] = index
    return report, 0 if index['software_release_pass'] else 1


def self_test(report_path=None):
    report = _base_report()
    current_files = _current_audit_files()
    report['checks'] = list(_run_v1_suites()) + [
        _run_py_compile(
            'current_audit_py_compile', _current_python_files()),
        _run_whitespace(
            'current_audit_no_index_whitespace', current_files),
    ]
    report['self_test_only'] = True
    report['software_release_pass'] = False
    report['software_release_ready'] = False
    report['integrated_software_ready'] = False
    report['field_evidence_complete'] = False
    _mark_self_test_non_authoritative(report, report_path)
    if report_path is not None:
        _write_exclusive(report_path, report)
    return report, 0 if all(
        check['status'] == 'PASS' for check in report['checks']) else 1


def parse_args(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--report', type=Path)
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args(argv)
    if not args.self_test and args.report is None:
        parser.error('--report is required for the complete matrix')
    return args


def main(argv=None):
    args = parse_args(argv)
    if args.self_test:
        report, code = self_test(args.report)
    else:
        report, code = run_complete_matrix(args.report)
    authority = report.get('authority_commit_result', {})
    print(json.dumps({
        'schema': report['schema'],
        'decision_model': report['decision_model'],
        'software_release_pass': authority.get(
            'software_release_pass', report['software_release_pass']),
        'software_release_ready': authority.get(
            'software_release_ready', report['software_release_ready']),
        'integrated_software_ready': authority.get(
            'integrated_software_ready', report['integrated_software_ready']),
        'field_acceptance_complete': report['field_acceptance_complete'],
        'field_evidence_complete': report['field_evidence_complete'],
        'delivery_ready': authority.get(
            'delivery_ready', report['delivery_ready']),
        'active_blocker_ids': [
            item['id'] for item in report['active_software_blockers']],
        'integrated_closure_status': report[
            'integrated_combined_deployment']['closure_status'],
        'vendor_provenance_decision': report[
            'vendor_provenance']['decision'],
        'release_integrity_decision': report[
            'release_integrity']['decision'],
        'check_statuses': {
            item['name']: item['status'] for item in report['checks']},
    }, sort_keys=True))
    return code


if __name__ == '__main__':
    raise SystemExit(main())

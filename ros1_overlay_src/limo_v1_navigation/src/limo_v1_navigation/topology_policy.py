"""Exact ROS graph ownership contract for native ROS1 V1 navigation."""

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re
import shlex
import xml.etree.ElementTree as ET


TF_DYNAMIC = 'DYNAMIC'
TF_STATIC_LATCHED = 'STATIC_LATCHED'
TF_STATIC_PERIODIC = 'STATIC_PERIODIC'
_TF_TOPICS = frozenset({'/tf', '/tf_static'})
_TF_BEHAVIORS = frozenset({
    TF_DYNAMIC, TF_STATIC_LATCHED, TF_STATIC_PERIODIC})
_TRUSTED_VENDOR_BLOCKER_SHA256 = (
    'c72ae71479ca93305a6ca9c616ba7cb1b638699ceed7e0f3c0deb7e745e4f21f')
_TRUSTED_VENDOR_WRAPPER_SHA256 = (
    '36d270c0350926825a6648f3f1353bf19ae71c063396314eab48b49a03efa3dd')
_VENDOR_RULES_SEAL = object()
_FIND_INCLUDE_PATTERN = re.compile(
    r'^\$\(find ([A-Za-z][A-Za-z0-9_]*)\)/(.+)$')
_VENDOR_INCLUDE_ARG_PARSER_VERSION = (
    'limo_v1_vendor_include_args/restricted_v1')
_AUDITED_LIMO_BASE_INCLUDE = (
    '$(find limo_base)/launch/limo_base.launch')
_AUDITED_LIMO_START_LOGICAL_PATH = (
    'limo_bringup/launch/limo_start.launch')
_AUDITED_LIMO_BASE_INCLUDE_ARGS = (
    ('port_name', 'ttyTHS0'),
    ('use_mcnamu', 'false'),
    ('pub_odom_tf', 'false'),
)


class TfEdgeValidationError(RuntimeError):
    """Fail-closed TF edge error with a stable diagnostic code."""

    def __init__(self, code, detail):
        self.code = code
        super().__init__('{}: {}'.format(code, detail))


@dataclass(frozen=True)
class TfEdgeObservation:
    """One transform from one received TFMessage connection."""

    message_id: int
    parent_frame: str
    child_frame: str
    authority: str
    topic: str
    source_stamp: float
    receipt_monotonic: float
    translation: tuple
    rotation: tuple
    latching: bool


@dataclass(frozen=True)
class TfEdgeRule:
    """Exact owner, transport, and behavior contract for one TF edge."""

    parent_frame: str
    child_frame: str
    authority: str
    topic: str
    behavior: str
    provenance_verified: bool = True


@dataclass(frozen=True)
class _VerifiedVendorTfRules:
    """Opaque result created only after artifact-byte verification."""

    rules: tuple
    evidence_json: str
    seal: object

    def __post_init__(self):
        if self.seal is not _VENDOR_RULES_SEAL:
            _vendor_error(
                'vendor TF rules were not produced by the artifact loader')

    def __iter__(self):
        return iter(self.rules)

    def __len__(self):
        return len(self.rules)

    def __getitem__(self, index):
        return self.rules[index]

    def evidence_summary(self):
        """Return a detached JSON-compatible provenance record."""
        return json.loads(self.evidence_json)


@dataclass(frozen=True)
class ExpectedTopology:
    """Project-owned topic and owner names."""

    scan_topic: str = '/scan'
    scan_node: str = '/ydlidar_lidar_publisher'
    odom_topic: str = '/odom'
    odom_node: str = '/limo_base_node'
    nav_cmd_topic: str = '/v1/nav_cmd_vel'
    driver_cmd_topic: str = '/v1/driver_cmd_vel'
    map_server_node: str = '/map_server'
    amcl_node: str = '/amcl'
    move_base_node: str = '/move_base'
    guard_node: str = '/v1_cmd_guard'
    bridge_node: str = '/dynamic_bridge'
    bridge_watchdog_node: str = '/cleanup_ros1_safe_cmd_vel_watchdog'
    bridge_verifier_node: str = '/verify_ros1_base_bridge_topology'
    public_cmd_topic: str = '/cmd_vel'
    integrated_request_topic: str = '/cleanup/base/cmd_vel_request'
    integrated_safe_topic: str = '/cleanup/base/safe_cmd_vel'
    integrated_driver_topic: str = '/cleanup/base/driver_cmd_vel'
    public_goal_topic: str = '/move_base_simple/goal'
    private_goal_topic: str = '/v1/private_move_base_simple/goal'
    public_action_prefix: str = '/move_base'
    private_action_prefix: str = '/v1/private_move_base'
    gateway_node: str = '/v1_navigation_gateway'
    localization_manager_node: str = '/v1_localization_manager'
    navigation_adapter_node: str = '/cleanup_ros1_navigation_adapter'
    forbidden_tf_node: str = '/robot_pose_ekf'
    gmapping_node: str = '/slam_gmapping'
    cartographer_node: str = '/cartographer_node'


def _tf_error(code, detail):
    raise TfEdgeValidationError(code, detail)


def _canonical_tf_frame(value, field_name):
    if not isinstance(value, str):
        _tf_error('TF_OBSERVATION_INVALID', '{} must be text'.format(
            field_name))
    frame = value.strip().strip('/')
    if not frame:
        _tf_error('TF_OBSERVATION_INVALID', '{} is empty'.format(
            field_name))
    return frame


def _canonical_tf_authority(value, code='TF_AUTHORITY_UNKNOWN'):
    if not isinstance(value, str):
        _tf_error(code, 'TF authority must be text')
    authority = value.strip().strip('/')
    if not authority:
        _tf_error(code, 'TF connection callerid/authority is missing')
    return '/' + authority


def _finite_tf_number(value, field_name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _tf_error('TF_OBSERVATION_INVALID', '{} must be numeric'.format(
            field_name))
    number = float(value)
    if not math.isfinite(number):
        _tf_error('TF_OBSERVATION_INVALID', '{} must be finite'.format(
            field_name))
    return number


def _tf_vector(value, length, field_name):
    if not isinstance(value, (tuple, list)) or len(value) != length:
        _tf_error(
            'TF_OBSERVATION_INVALID',
            '{} must contain {} numeric values'.format(field_name, length))
    return tuple(
        _finite_tf_number(item, '{}[{}]'.format(field_name, index))
        for index, item in enumerate(value))


def _normalize_tf_observation(observation):
    if not isinstance(observation, TfEdgeObservation):
        _tf_error(
            'TF_OBSERVATION_INVALID',
            'TF evidence must contain TfEdgeObservation values')
    if (
            isinstance(observation.message_id, bool)
            or not isinstance(observation.message_id, int)
            or observation.message_id < 0):
        _tf_error(
            'TF_OBSERVATION_INVALID',
            'message_id must be a nonnegative integer')
    if observation.topic not in _TF_TOPICS:
        _tf_error(
            'TF_OBSERVATION_INVALID',
            'TF topic must be /tf or /tf_static')
    if not isinstance(observation.latching, bool):
        _tf_error(
            'TF_OBSERVATION_INVALID', 'latching must be bool')
    parent = _canonical_tf_frame(
        observation.parent_frame, 'parent_frame')
    child = _canonical_tf_frame(
        observation.child_frame, 'child_frame')
    if parent == child:
        _tf_error(
            'TF_OBSERVATION_INVALID',
            'TF parent and child frames must differ')
    return TfEdgeObservation(
        message_id=observation.message_id,
        parent_frame=parent,
        child_frame=child,
        authority=_canonical_tf_authority(observation.authority),
        topic=observation.topic,
        source_stamp=_finite_tf_number(
            observation.source_stamp, 'source_stamp'),
        receipt_monotonic=_finite_tf_number(
            observation.receipt_monotonic, 'receipt_monotonic'),
        translation=_tf_vector(
            observation.translation, 3, 'translation'),
        rotation=_tf_vector(observation.rotation, 4, 'rotation'),
        latching=observation.latching,
    )


def _normalize_tf_rule(rule, vendor=False):
    if not isinstance(rule, TfEdgeRule):
        _tf_error(
            'TF_VENDOR_CONTRACT_UNVERIFIED' if vendor
            else 'TF_RULE_INVALID',
            'TF rules must contain TfEdgeRule values')
    if vendor and rule.provenance_verified is not True:
        _tf_error(
            'TF_VENDOR_CONTRACT_UNVERIFIED',
            'vendor TF rule provenance is missing or unverified')
    if not isinstance(rule.provenance_verified, bool):
        _tf_error(
            'TF_RULE_INVALID', 'provenance_verified must be bool')
    parent = _canonical_tf_frame(rule.parent_frame, 'rule.parent_frame')
    child = _canonical_tf_frame(rule.child_frame, 'rule.child_frame')
    if parent == child:
        _tf_error('TF_RULE_INVALID', 'TF rule parent and child must differ')
    authority = _canonical_tf_authority(
        rule.authority,
        'TF_VENDOR_CONTRACT_UNVERIFIED' if vendor
        else 'TF_RULE_INVALID')
    if rule.topic not in _TF_TOPICS:
        _tf_error('TF_RULE_INVALID', 'TF rule topic is invalid')
    if rule.behavior not in _TF_BEHAVIORS:
        _tf_error('TF_RULE_INVALID', 'TF rule behavior is invalid')
    expected_topics = {
        TF_DYNAMIC: '/tf',
        TF_STATIC_LATCHED: '/tf_static',
        TF_STATIC_PERIODIC: '/tf',
    }
    if rule.topic != expected_topics[rule.behavior]:
        _tf_error(
            'TF_RULE_INVALID',
            '{} cannot use {}'.format(rule.behavior, rule.topic))
    return TfEdgeRule(
        parent_frame=parent,
        child_frame=child,
        authority=authority,
        topic=rule.topic,
        behavior=rule.behavior,
        provenance_verified=rule.provenance_verified,
    )


def _stage_tf_rules(stage):
    if stage not in (
            'scan', 'mapping', 'localization',
            'navigation_precore', 'navigation'):
        _tf_error('TF_STAGE_INVALID', 'unknown TF stage: {}'.format(stage))
    rules = [TfEdgeRule(
        parent_frame='odom',
        child_frame='base_link',
        authority='/limo_base_node',
        topic='/tf',
        behavior=TF_DYNAMIC,
    )]
    forbidden_edges = set()
    if stage == 'mapping':
        rules.append(TfEdgeRule(
            parent_frame='map',
            child_frame='odom',
            authority='/slam_gmapping',
            topic='/tf',
            behavior=TF_DYNAMIC,
        ))
    elif stage in ('localization', 'navigation'):
        rules.append(TfEdgeRule(
            parent_frame='map',
            child_frame='odom',
            authority='/amcl',
            topic='/tf',
            behavior=TF_DYNAMIC,
        ))
    else:
        forbidden_edges.add(('map', 'odom'))
    return tuple(_normalize_tf_rule(rule) for rule in rules), forbidden_edges


def validate_vendor_tf_rules(vendor_rules):
    """Return normalized vendor rules or fail before any runtime action."""
    if vendor_rules is None:
        _tf_error(
            'TF_VENDOR_CONTRACT_UNVERIFIED',
            'verified vendor TF rules are required')
    try:
        vendor_values = tuple(vendor_rules)
    except TypeError:
        _tf_error(
            'TF_VENDOR_CONTRACT_UNVERIFIED',
            'vendor TF rules must be iterable')
    if not vendor_values:
        _tf_error(
            'TF_VENDOR_CONTRACT_UNVERIFIED',
            'verified vendor TF rules are required')
    normalized = tuple(
        _normalize_tf_rule(rule, vendor=True) for rule in vendor_values)
    laser_rules = [
        rule for rule in normalized
        if (rule.parent_frame, rule.child_frame) == (
            'base_link', 'laser_link')]
    if len(laser_rules) != 1 or laser_rules[0].behavior not in (
            TF_STATIC_LATCHED, TF_STATIC_PERIODIC):
        _tf_error(
            'TF_VENDOR_CONTRACT_UNVERIFIED',
            'one verified static base_link->laser_link rule is required')
    return normalized


def _vendor_error(detail):
    _tf_error('TF_VENDOR_CONTRACT_UNVERIFIED', detail)


def _read_vendor_json(path, label):
    if not path:
        _vendor_error('{} path is missing'.format(label))
    candidate = Path(path)
    if not candidate.is_absolute() or not candidate.is_file():
        _vendor_error(
            '{} must be an existing absolute file'.format(label))
    try:
        raw = candidate.read_bytes()
        payload = json.loads(raw.decode('utf-8'))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        _vendor_error('{} cannot be read: {}'.format(label, exc))
    if not isinstance(payload, dict):
        _vendor_error('{} must contain a JSON object'.format(label))
    return candidate, raw, payload, hashlib.sha256(raw).hexdigest()


def _require_vendor_sha(value, label):
    if (
            not isinstance(value, str) or len(value) != 64
            or any(character not in '0123456789abcdef'
                   for character in value)):
        _vendor_error('{} must be a lowercase SHA-256'.format(label))
    return value


def _vendor_logical_path(value, label):
    if not isinstance(value, str) or not value or '\\' in value:
        _vendor_error('{} must be a nonempty POSIX-style path'.format(label))
    if value.startswith('/'):
        _vendor_error('{} must be package-relative'.format(label))
    parts = value.split('/')
    if any(part in ('', '.', '..') for part in parts):
        _vendor_error('{} contains an unsafe path component'.format(label))
    return '/'.join(parts)


def _include_target(expression):
    if not isinstance(expression, str) or not expression:
        _vendor_error('vendor include expression is invalid')
    match = _FIND_INCLUDE_PATTERN.fullmatch(expression)
    if match is not None:
        logical = _vendor_logical_path(
            '{}/{}'.format(match.group(1), match.group(2)),
            'vendor include target')
        return 'logical_path', logical
    candidate = Path(expression)
    if candidate.is_absolute():
        return 'absolute_path', str(candidate.resolve())
    _vendor_error(
        'vendor include expression is unresolved or unsupported: {}'.format(
            expression))


def _resolve_ros_package_root(package):
    """Resolve the package path that ROS1 would use in this environment."""
    try:
        import rospkg
        output = rospkg.RosPack().get_path(package)
    except Exception as exc:
        _vendor_error('ROS package resolution failed: {}'.format(exc))
    if not isinstance(output, str) or not output:
        _vendor_error('ROS package resolver returned invalid data')
    candidate = Path(output)
    if not candidate.is_absolute() or not candidate.is_dir():
        _vendor_error('ROS package resolver returned an invalid package root')
    return candidate.resolve()


def _resolve_ros_node_executables(package, node_type):
    """Return the exact executables ROS1 would select for pkg/type."""
    try:
        from roslib.packages import find_node
        values = find_node(package, node_type)
    except Exception as exc:
        _vendor_error('ROS node executable resolution failed: {}'.format(exc))
    candidates = tuple(values or ())
    if len(candidates) != 1:
        _vendor_error(
            'ROS node executable resolution is missing or ambiguous')
    resolved = []
    for value in candidates:
        if not isinstance(value, str):
            _vendor_error('ROS node executable resolver returned invalid data')
        candidate = Path(value)
        if not candidate.is_absolute() or not candidate.is_file():
            _vendor_error(
                'ROS node executable resolver returned a missing path')
        resolved.append(candidate.resolve())
    return tuple(resolved)


def _verified_consumer_wrapper():
    """Bind the exact inert V1 wrapper that consumes the vendor include."""
    package_root = _resolve_ros_package_root('limo_v1_navigation')
    wrapper_path = package_root / 'launch' / 'v1_base_sensors.launch'
    if not wrapper_path.is_file():
        _vendor_error('V1 vendor consumer wrapper is missing')
    try:
        raw = wrapper_path.read_bytes()
    except OSError as exc:
        _vendor_error('V1 vendor consumer wrapper cannot be read: {}'.format(
            exc))
    wrapper_sha = hashlib.sha256(raw).hexdigest()
    if wrapper_sha != _TRUSTED_VENDOR_WRAPPER_SHA256:
        _vendor_error('V1 vendor consumer wrapper trust-anchor mismatch')
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        _vendor_error('V1 vendor consumer wrapper XML is invalid: {}'.format(
            exc))
    if root.tag != 'launch' or root.attrib:
        _vendor_error('V1 vendor consumer wrapper root is invalid')
    children = list(root)
    if [child.tag for child in children] != [
            'arg', 'arg', 'arg', 'arg', 'arg', 'group']:
        _vendor_error('V1 vendor consumer wrapper structure is invalid')
    expected_args = (
        {'name': 'enable_hardware', 'default': 'false'},
        {'name': 'hardware_authorization_id', 'default': 'NOT_AUTHORIZED'},
        {'name': 'odom_tf_owner'},
        {'name': 'port_name', 'default': 'ttyTHS0'},
        {'name': 'use_mcnamu', 'default': 'false'},
    )
    if tuple(child.attrib for child in children[:5]) != expected_args:
        _vendor_error('V1 vendor consumer wrapper inert args are invalid')
    group = children[5]
    expected_gate = (
        "$(eval arg('enable_hardware') == 'true' and "
        "arg('hardware_authorization_id') != 'NOT_AUTHORIZED' and "
        "arg('odom_tf_owner') == '/limo_base_node')")
    if group.attrib != {'if': expected_gate}:
        _vendor_error('V1 vendor consumer wrapper gate is invalid')
    group_children = list(group)
    if [child.tag for child in group_children] != ['remap', 'include']:
        _vendor_error('V1 vendor consumer wrapper body is invalid')
    remap, include = group_children
    if remap.attrib != {
            'from': '/cmd_vel', 'to': '/v1/driver_cmd_vel'} or list(remap):
        _vendor_error('V1 vendor consumer wrapper velocity remap is invalid')
    if include.attrib != {
            'file': '$(find limo_bringup)/launch/limo_start.launch'}:
        _vendor_error('V1 vendor consumer wrapper include is invalid')
    include_args = list(include)
    expected_include_args = (
        {'name': 'port_name', 'value': '$(arg port_name)'},
        {'name': 'use_mcnamu', 'value': '$(arg use_mcnamu)'},
        {'name': 'pub_odom_tf', 'value': 'true'},
    )
    if (
            [child.tag for child in include_args] != ['arg', 'arg', 'arg']
            or tuple(child.attrib for child in include_args) !=
            expected_include_args):
        _vendor_error('V1 vendor consumer wrapper forced args are invalid')
    return wrapper_path.resolve(), wrapper_sha, package_root


def _rule_key(rule):
    return (
        rule.parent_frame, rule.child_frame, rule.authority,
        rule.topic, rule.behavior)


def _rules_from_records(records, authority_field):
    if not isinstance(records, list) or not records:
        _vendor_error('vendor TF rule records must be a nonempty list')
    expected = {
        'parent_frame', 'child_frame', authority_field, 'topic', 'behavior'}
    rules = []
    for index, record in enumerate(records):
        if not isinstance(record, dict) or set(record) != expected:
            _vendor_error(
                'vendor TF rule {} has unexpected fields'.format(index))
        rules.append(_normalize_tf_rule(TfEdgeRule(
            parent_frame=record['parent_frame'],
            child_frame=record['child_frame'],
            authority=record[authority_field],
            topic=record['topic'],
            behavior=record['behavior'],
            provenance_verified=True,
        ), vendor=True))
    if len({_rule_key(rule) for rule in rules}) != len(rules):
        _vendor_error('vendor TF rules contain duplicates')
    return tuple(rules)


def _require_verified_vendor_contract(vendor_rules):
    if (
            not isinstance(vendor_rules, _VerifiedVendorTfRules)
            or vendor_rules.seal is not _VENDOR_RULES_SEAL):
        _vendor_error(
            'vendor TF rules must come from verified artifact bytes')
    return validate_vendor_tf_rules(vendor_rules.rules)


def _verified_source_manifest(payload):
    expected = {
        'schema', 'status', 'closure_complete', 'root_artifact_id',
        'artifacts', 'include_edges'}
    if set(payload) != expected:
        _vendor_error('vendor source manifest has unexpected fields')
    if payload['schema'] != 'limo_v1_ros1_vendor_source_manifest/v1':
        _vendor_error('vendor source manifest schema is unsupported')
    if payload['status'] != 'VERIFIED' or payload['closure_complete'] is not True:
        _vendor_error('vendor source manifest is not VERIFIED and complete')
    artifacts = payload['artifacts']
    if not isinstance(artifacts, list) or not artifacts:
        _vendor_error('vendor source manifest artifacts are missing')
    artifact_fields = {
        'id', 'logical_path', 'absolute_path', 'sha256', 'kind'}
    by_id = {}
    ids_by_logical_path = {}
    ids_by_absolute_path = {}
    package_roots = {}
    xml_by_id = {}
    for record in artifacts:
        if not isinstance(record, dict) or set(record) != artifact_fields:
            _vendor_error('vendor source artifact has unexpected fields')
        artifact_id = record['id']
        if not isinstance(artifact_id, str) or not artifact_id or (
                artifact_id in by_id):
            _vendor_error('vendor source artifact id is invalid or duplicate')
        if record['kind'] != 'roslaunch':
            _vendor_error('only archived roslaunch artifacts are accepted')
        logical_path = _vendor_logical_path(
            record['logical_path'], 'vendor source logical_path')
        if logical_path in ids_by_logical_path:
            _vendor_error('vendor source logical_path is duplicated')
        logical_parts = logical_path.split('/')
        if len(logical_parts) < 2:
            _vendor_error(
                'vendor source logical_path must include package and path')
        package = logical_parts[0]
        package_root = package_roots.get(package)
        if package_root is None:
            resolved_root = _resolve_ros_package_root(package)
            try:
                package_root = Path(resolved_root)
            except TypeError:
                _vendor_error('ROS package resolver returned an invalid path')
            if not package_root.is_absolute() or not package_root.is_dir():
                _vendor_error(
                    'ROS package resolver returned a missing package root')
            package_root = package_root.resolve()
            package_roots[package] = package_root
        if not isinstance(record['absolute_path'], str):
            _vendor_error('vendor source absolute_path must be text')
        path = Path(record['absolute_path'])
        if not path.is_absolute() or not path.is_file():
            _vendor_error(
                'vendor raw artifact is missing: {}'.format(
                    logical_path))
        resolved_path = str(path.resolve())
        expected_path = str(
            package_root.joinpath(*logical_parts[1:]).resolve())
        if resolved_path != expected_path:
            _vendor_error(
                'vendor source artifact does not match ROS package resolution')
        if resolved_path in ids_by_absolute_path:
            _vendor_error('vendor raw artifact path is duplicated')
        try:
            raw = path.read_bytes()
        except OSError as exc:
            _vendor_error('vendor raw artifact cannot be read: {}'.format(exc))
        expected_sha = _require_vendor_sha(
            record['sha256'], 'vendor raw artifact sha256')
        if hashlib.sha256(raw).hexdigest() != expected_sha:
            _vendor_error(
                'vendor raw artifact hash mismatch: {}'.format(
                    logical_path))
        try:
            root = ET.fromstring(raw)
        except ET.ParseError as exc:
            _vendor_error('vendor roslaunch XML is invalid: {}'.format(exc))
        if root.tag != 'launch':
            _vendor_error('vendor roslaunch root element must be launch')
        normalized_record = dict(record)
        normalized_record['logical_path'] = logical_path
        normalized_record['absolute_path'] = resolved_path
        by_id[artifact_id] = normalized_record
        ids_by_logical_path[logical_path] = artifact_id
        ids_by_absolute_path[resolved_path] = artifact_id
        xml_by_id[artifact_id] = root
    root_id = payload['root_artifact_id']
    if root_id not in by_id:
        _vendor_error('vendor source root artifact is missing')
    if by_id[root_id]['logical_path'] != (
            'limo_bringup/launch/limo_start.launch'):
        _vendor_error('vendor source root is not limo_start.launch')
    edges = payload['include_edges']
    if not isinstance(edges, list):
        _vendor_error('vendor include_edges must be a list')
    edge_fields = {
        'parent_artifact_id', 'include_expression', 'child_artifact_id'}
    edges_by_parent = {}
    declared_targets = set()
    reachable = {root_id}
    pending = [root_id]
    for edge in edges:
        if not isinstance(edge, dict) or set(edge) != edge_fields:
            _vendor_error('vendor include edge has unexpected fields')
        parent = edge['parent_artifact_id']
        child = edge['child_artifact_id']
        expression = edge['include_expression']
        if parent not in by_id or child not in by_id or not isinstance(
                expression, str) or not expression:
            _vendor_error('vendor include edge is invalid')
        if parent == child:
            _vendor_error('vendor include edge cannot reference itself')
        declared_key = (parent, expression)
        if declared_key in declared_targets:
            _vendor_error('vendor include edge is duplicated or ambiguous')
        declared_targets.add(declared_key)
        target_field, target_value = _include_target(expression)
        if by_id[child][target_field] != target_value:
            _vendor_error(
                'vendor include expression does not bind its child artifact')
        edges_by_parent.setdefault(parent, []).append((expression, child))

    visiting = set()
    visited = set()

    def visit(artifact_id):
        if artifact_id in visiting:
            _vendor_error('vendor include graph contains a cycle')
        if artifact_id in visited:
            return
        visiting.add(artifact_id)
        for _expression, child in edges_by_parent.get(artifact_id, ()):
            visit(child)
        visiting.remove(artifact_id)
        visited.add(artifact_id)

    visit(root_id)
    while pending:
        parent = pending.pop()
        for _expression, child in edges_by_parent.get(parent, ()):
            if child not in reachable:
                reachable.add(child)
                pending.append(child)
    if reachable != set(by_id):
        _vendor_error('vendor source manifest contains unreachable artifacts')
    for artifact_id, root in xml_by_id.items():
        observed = sorted(
            element.attrib.get('file', '')
            for element in root.iter('include'))
        declared = sorted(
            expression for expression, _child
            in edges_by_parent.get(artifact_id, ()))
        if observed != declared:
            _vendor_error(
                'vendor include chain does not match archived bytes')
    return by_id, xml_by_id, package_roots


def _audited_vendor_include_arg_binding(
        artifact_id, artifact, root, include):
    """Resolve only the byte-audited limo_start -> limo_base defaults."""
    children = list(include)
    if not children:
        return None
    if (
            artifact['logical_path'] != _AUDITED_LIMO_START_LOGICAL_PATH
            or include not in list(root)
            or include.attrib != {'file': _AUDITED_LIMO_BASE_INCLUDE}):
        _vendor_error(
            'vendor include child args are outside the audited contract')

    expected_names = tuple(
        name for name, _default in _AUDITED_LIMO_BASE_INCLUDE_ARGS)
    if [child.tag for child in children] != ['arg'] * len(expected_names):
        _vendor_error(
            'audited vendor include args are missing or contain unknown nodes')
    observed_names = tuple(child.attrib.get('name') for child in children)
    if len(set(observed_names)) != len(observed_names):
        _vendor_error('audited vendor include args contain duplicates')
    if observed_names != expected_names:
        _vendor_error('audited vendor include args are missing or unknown')

    root_args = tuple(
        child for child in list(root) if child.tag == 'arg')
    expected_root_attributes = tuple(
        {'name': name, 'default': default}
        for name, default in _AUDITED_LIMO_BASE_INCLUDE_ARGS)
    if (
            tuple(child.attrib for child in root_args) !=
            expected_root_attributes
            or any(list(child) for child in root_args)):
        _vendor_error(
            'audited vendor root arg declarations are missing or unsafe')

    arguments = []
    for child, (name, declared_default) in zip(
            children, _AUDITED_LIMO_BASE_INCLUDE_ARGS):
        expected_attributes = {
            'name': name,
            'default': '$(arg {})'.format(name),
        }
        if child.attrib != expected_attributes or list(child):
            _vendor_error(
                'audited vendor include arg attributes are unresolved or unsafe')
        arguments.append({
            'name': name,
            'include_default_expression': expected_attributes['default'],
            'root_declared_default': declared_default,
            'default_resolution': declared_default,
            'runtime_override_sensitive': True,
        })

    normalized = {
        'parser_version': _VENDOR_INCLUDE_ARG_PARSER_VERSION,
        'artifact_id': artifact_id,
        'artifact_logical_path': artifact['logical_path'],
        'artifact_sha256': artifact['sha256'],
        'include_expression': include.attrib['file'],
        'arguments': arguments,
    }
    normalized_bytes = json.dumps(
        normalized, sort_keys=True, separators=(',', ':')).encode('utf-8')
    normalized['normalized_result_sha256'] = hashlib.sha256(
        normalized_bytes).hexdigest()
    return normalized


def _source_static_rules(xml_by_id, artifacts):
    rules = []
    node_packages = set()
    node_records = []
    include_arg_bindings = []
    for artifact_id, root in xml_by_id.items():
        artifact = artifacts[artifact_id]
        def is_static_tf_node(element):
            return (
                element.tag == 'node'
                and element.attrib.get('type') ==
                'static_transform_publisher'
                and element.attrib.get('pkg') in ('tf', 'tf2_ros'))

        for include in root.iter('include'):
            if set(include.attrib) != {'file'}:
                _vendor_error(
                    'vendor include has unresolved attributes')
            binding = _audited_vendor_include_arg_binding(
                artifact_id, artifact, root, include)
            if binding is not None:
                include_arg_bindings.append(binding)
        for scope in (root,) + tuple(root.iter('group')):
            if not any(True for _include in scope.iter('include')):
                continue
            if scope.attrib:
                _vendor_error(
                    'vendor include inherits unresolved scope attributes')
            if any(child.tag == 'remap' for child in list(scope)):
                _vendor_error(
                    'vendor include inherits unresolved remap')
        for scope in (root,) + tuple(root.iter('group')):
            if (
                    any(child.tag == 'remap' for child in scope)
                    and any(is_static_tf_node(element)
                            for element in scope.iter())):
                _vendor_error(
                    'vendor launch/group TF remap is unresolved')
        for group in root.iter('group'):
            if group.attrib and any(
                        is_static_tf_node(descendant)
                        for descendant in group.iter()):
                _vendor_error(
                    'vendor static TF group attributes are unresolved')
        for node in root.iter('node'):
            package = node.attrib.get('pkg', '')
            node_type = node.attrib.get('type', '')
            if '$(' in package or '$(' in node_type:
                _vendor_error('vendor node package/type is unresolved')
            if (
                    node_type == 'static_transform_publisher'
                    and package not in ('tf', 'tf2_ros')):
                _vendor_error('vendor static TF package is unsupported')
            if node_type != 'static_transform_publisher':
                continue
            if set(node.attrib) != {'pkg', 'type', 'name', 'args'} or list(node):
                _vendor_error(
                    'vendor static TF node has unresolved launch semantics')
            name = node.attrib.get('name', '')
            args = node.attrib.get('args', '')
            if (
                    not name or '$(' in name or '$(' in args
                    or any(node.attrib.get(field) for field in (
                        'ns', 'if', 'unless'))):
                _vendor_error(
                    'vendor static TF callerid/arguments are unresolved')
            try:
                tokens = shlex.split(args)
            except ValueError as exc:
                _vendor_error(
                    'static transform publisher args are invalid: {}'.format(
                        exc))
            if package == 'tf':
                if len(tokens) not in (9, 10):
                    _vendor_error(
                        'legacy static transform args are unresolved')
                parent, child = tokens[-3], tokens[-2]
                topic, behavior = '/tf', TF_STATIC_PERIODIC
            else:
                if len(tokens) not in (8, 9):
                    _vendor_error(
                        'latched static transform args are unresolved')
                parent, child = tokens[-2], tokens[-1]
                topic, behavior = '/tf_static', TF_STATIC_LATCHED
            rule = _normalize_tf_rule(TfEdgeRule(
                parent_frame=parent,
                child_frame=child,
                authority=name,
                topic=topic,
                behavior=behavior,
                provenance_verified=True,
            ), vendor=True)
            rules.append(rule)
            node_packages.add((package, node_type))
            node_records.append({
                'rule': rule,
                'name': name,
                'package': package,
                'node_type': node_type,
                'arguments': args,
            })
    if not rules:
        _vendor_error('archived vendor source has no resolved static TF node')
    include_arg_bindings.sort(key=lambda value: (
        value['artifact_logical_path'], value['include_expression']))
    return (
        tuple(rules), node_packages, tuple(node_records),
        tuple(include_arg_bindings))


def _load_verified_vendor_tf_rules(
        rules_file, source_manifest_file, publisher_pin_file, blocker_file):
    blocker_path, _blocker_raw, blocker, blocker_sha = _read_vendor_json(
        blocker_file, 'installed vendor blocker')
    if blocker_sha != _TRUSTED_VENDOR_BLOCKER_SHA256:
        _vendor_error('installed vendor blocker trust-anchor hash mismatch')
    if blocker.get('schema') != 'limo_v1_ros1_vendor_include_blocker/v1':
        _vendor_error('installed vendor blocker schema is unsupported')
    evidence = blocker.get('current_local_evidence')
    decision = blocker.get('decision')
    installed_pin = blocker.get('required_installed_tf_publisher_pin')
    if not all(isinstance(value, dict) for value in (
            evidence, decision, installed_pin)):
        _vendor_error('installed vendor blocker fields are malformed')
    if (
            blocker.get('status') != 'VERIFIED'
            or blocker.get('ownership_conclusion') != 'VERIFIED'
            or evidence.get('vendor_raw_source_archived') is not True
            or evidence.get('current_hash_verified') is not True
            or evidence.get('resolved_include_chain_verified') is not True
            or evidence.get('installed_vendor_manifest_present') is not True
            or installed_pin.get('status') != 'VERIFIED'
            or decision.get('ownership_closed') is not True
            or decision.get('tf_edge_runtime_pass_eligible') is not True):
        _vendor_error('installed vendor blocker is not verified/closed')
    wrapper_path, wrapper_sha, wrapper_package_root = (
        _verified_consumer_wrapper())

    source_path, _source_raw, source, source_sha = _read_vendor_json(
        source_manifest_file, 'vendor source manifest')
    pin_path, _pin_raw, pin, pin_sha = _read_vendor_json(
        publisher_pin_file, 'vendor publisher pin')
    rules_path, _rules_raw, rules_payload, rules_sha = _read_vendor_json(
        rules_file, 'vendor TF rules manifest')
    if len({source_path.resolve(), pin_path.resolve(), rules_path.resolve()}) != 3:
        _vendor_error('vendor manifests must be three independent files')
    verified = blocker.get('verified_evidence')
    if not isinstance(verified, dict):
        _vendor_error('installed blocker verified_evidence is malformed')
    expected_hashes = {
        'source_manifest_sha256': source_sha,
        'publisher_pin_sha256': pin_sha,
        'rules_manifest_sha256': rules_sha,
    }
    if any(
            _require_vendor_sha(verified.get(name), name) != actual
            for name, actual in expected_hashes.items()):
        _vendor_error('installed blocker hashes do not bind the artifacts')

    artifacts, xml_by_id, package_roots = _verified_source_manifest(source)
    source_rules, node_packages, source_nodes, include_arg_bindings = (
        _source_static_rules(xml_by_id, artifacts))
    source_rules = validate_vendor_tf_rules(source_rules)
    source_keys = tuple(_rule_key(rule) for rule in source_rules)
    if len(set(source_keys)) != len(source_keys):
        _vendor_error('archived vendor source contains duplicate static edges')

    pin_fields = {
        'schema', 'status', 'source_manifest_sha256', 'executable', 'rules'}
    if set(pin) != pin_fields:
        _vendor_error('vendor publisher pin has unexpected fields')
    if (
            pin['schema'] != 'limo_v1_ros1_vendor_tf_publisher_pin/v1'
            or pin['status'] != 'VERIFIED'
            or _require_vendor_sha(
                pin['source_manifest_sha256'],
                'publisher pin source manifest sha256') != source_sha):
        _vendor_error('vendor publisher pin is not verified/bound')
    executable = pin['executable']
    executable_fields = {
        'absolute_path', 'sha256', 'package', 'node_type'}
    if not isinstance(executable, dict) or set(executable) != executable_fields:
        _vendor_error('vendor publisher executable pin is invalid')
    if not all(isinstance(executable.get(field), str) for field in (
            'absolute_path', 'package', 'node_type')):
        _vendor_error('vendor publisher executable fields must be text')
    executable_path = Path(executable['absolute_path'])
    if not executable_path.is_absolute() or not executable_path.is_file():
        _vendor_error('vendor publisher executable is missing')
    executable_path = executable_path.resolve()
    try:
        executable_raw = executable_path.read_bytes()
    except OSError as exc:
        _vendor_error('vendor publisher executable cannot be read: {}'.format(
            exc))
    executable_sha = _require_vendor_sha(
        executable['sha256'], 'vendor publisher executable sha256')
    if hashlib.sha256(executable_raw).hexdigest() != executable_sha:
        _vendor_error('vendor publisher executable hash mismatch')
    if node_packages != {(executable['package'], executable['node_type'])}:
        _vendor_error('vendor publisher executable semantics mismatch source')
    resolved_executables = _resolve_ros_node_executables(
        executable['package'], executable['node_type'])
    try:
        resolved_executables = tuple(
            Path(value).resolve() for value in resolved_executables)
    except (TypeError, OSError):
        _vendor_error('ROS node executable resolver returned invalid paths')
    if len(resolved_executables) != 1:
        _vendor_error(
            'ROS node executable resolution is missing or ambiguous')
    if resolved_executables[0] != executable_path:
        _vendor_error(
            'vendor publisher executable does not match ROS node resolution')
    pin_rules = validate_vendor_tf_rules(
        _rules_from_records(pin['rules'], 'callerid'))
    pin_keys = tuple(_rule_key(rule) for rule in pin_rules)
    if sorted(pin_keys) != sorted(source_keys):
        _vendor_error('vendor publisher pin rules mismatch archived source')

    rules_fields = {
        'schema', 'status', 'source_manifest_sha256',
        'publisher_pin_sha256', 'rules'}
    if set(rules_payload) != rules_fields:
        _vendor_error('vendor TF rules manifest has unexpected fields')
    if (
            rules_payload['schema'] != 'limo_v1_ros1_vendor_tf_rules/v2'
            or rules_payload['status'] != 'VERIFIED'
            or _require_vendor_sha(
                rules_payload['source_manifest_sha256'],
                'TF rules source manifest sha256') != source_sha
            or _require_vendor_sha(
                rules_payload['publisher_pin_sha256'],
                'TF rules publisher pin sha256') != pin_sha):
        _vendor_error('vendor TF rules manifest is not verified/bound')
    rules = validate_vendor_tf_rules(
        _rules_from_records(rules_payload['rules'], 'authority'))
    rule_keys = tuple(_rule_key(rule) for rule in rules)
    if sorted(rule_keys) != sorted(pin_keys):
        _vendor_error('vendor TF rules mismatch publisher pin')

    laser = next(
        rule for rule in rules
        if (rule.parent_frame, rule.child_frame) == (
            'base_link', 'laser_link'))
    laser_source = next(
        record for record in source_nodes
        if (record['rule'].parent_frame, record['rule'].child_frame) == (
            'base_link', 'laser_link'))
    installed_edge = installed_pin.get('edge')
    if not isinstance(installed_edge, dict):
        _vendor_error('installed blocker edge pin is missing')
    if (
            installed_edge.get('parent_frame') != laser.parent_frame
            or installed_edge.get('child_frame') != laser.child_frame
            or installed_edge.get('temporal_semantics') != 'STATIC'
            or installed_pin.get('resolved_callerid') != laser.authority
            or installed_pin.get('selected_topic') != laser.topic
            or installed_pin.get('selected_transport_semantics') !=
            laser.behavior
            or installed_pin.get('package') != executable['package']
            or installed_pin.get('node_type') != executable['node_type']
            or installed_pin.get('executable_absolute_path') !=
            str(executable_path)
            or installed_pin.get('executable_sha256') != executable_sha
            or installed_pin.get('resolved_arguments') !=
            laser_source['arguments']):
        _vendor_error('installed blocker pin semantics mismatch artifacts')

    provenance = {
        'schema': 'limo_v1_ros1_vendor_tf_verified_contract/v1',
        'status': 'VERIFIED',
        'blocker': {
            'path': str(blocker_path.resolve()),
            'sha256': blocker_sha,
            'schema': blocker['schema'],
            'status': blocker['status'],
        },
        'consumer_wrapper': {
            'path': str(wrapper_path),
            'sha256': wrapper_sha,
            'semantic_verdict': 'EXACT_INERT_VENDOR_INCLUDE_GATE',
        },
        'source_manifest': {
            'path': str(source_path.resolve()),
            'sha256': source_sha,
            'schema': source['schema'],
            'status': source['status'],
        },
        'publisher_pin': {
            'path': str(pin_path.resolve()),
            'sha256': pin_sha,
            'schema': pin['schema'],
            'status': pin['status'],
        },
        'rules_manifest': {
            'path': str(rules_path.resolve()),
            'sha256': rules_sha,
            'schema': rules_payload['schema'],
            'status': rules_payload['status'],
        },
        'raw_launch_artifacts': [
            {
                'id': artifact_id,
                'logical_path': record['logical_path'],
                'path': record['absolute_path'],
                'sha256': record['sha256'],
            }
            for artifact_id, record in sorted(artifacts.items())
        ],
        'ros_package_roots': {
            package: str(path)
            for package, path in sorted(dict(
                package_roots,
                limo_v1_navigation=wrapper_package_root).items())
        },
        'publisher_executable': {
            'path': str(executable_path),
            'sha256': executable_sha,
            'package': executable['package'],
            'node_type': executable['node_type'],
        },
        'include_argument_resolution': {
            'parser_version': _VENDOR_INCLUDE_ARG_PARSER_VERSION,
            'binding_count': len(include_arg_bindings),
            'bindings': list(include_arg_bindings),
        },
        'semantic_rule_count': len(rules),
        'binding_verdict': 'BYTE_AND_SEMANTIC_MATCH',
    }
    return _VerifiedVendorTfRules(
        rules=tuple(rules),
        evidence_json=json.dumps(provenance, sort_keys=True),
        seal=_VENDOR_RULES_SEAL)


def load_verified_vendor_tf_rules(
        rules_file, source_manifest_file, publisher_pin_file, blocker_file):
    """Cryptographically and semantically bind vendor TF rules to bytes."""
    try:
        return _load_verified_vendor_tf_rules(
            rules_file, source_manifest_file, publisher_pin_file,
            blocker_file)
    except TfEdgeValidationError as exc:
        if exc.code == 'TF_VENDOR_CONTRACT_UNVERIFIED':
            raise
        _vendor_error(str(exc))
    except (KeyError, TypeError, ValueError) as exc:
        _vendor_error('vendor artifact content is invalid: {}'.format(exc))


def _strictly_increasing(values):
    return all(current > previous
               for previous, current in zip(values, values[1:]))


def _validate_tf_rule_behavior(
        rule, edge_observations, now, timeout,
        source_now, source_timeout, source_future_tolerance):
    ordered = sorted(
        edge_observations,
        key=lambda item: (item.receipt_monotonic, item.message_id))
    expected_latching = rule.behavior == TF_STATIC_LATCHED
    if any(item.latching != expected_latching for item in ordered):
        _tf_error(
            'TF_EDGE_BEHAVIOR_MISMATCH',
            '{}->{} latching does not match {}'.format(
                rule.parent_frame, rule.child_frame, rule.behavior))
    fingerprints = {
        (item.translation, item.rotation) for item in ordered}
    if rule.behavior in (TF_STATIC_LATCHED, TF_STATIC_PERIODIC):
        if len(fingerprints) != 1:
            _tf_error(
                'TF_EDGE_BEHAVIOR_MISMATCH',
                '{}->{} static transform geometry changed'.format(
                    rule.parent_frame, rule.child_frame))
    if rule.behavior in (TF_DYNAMIC, TF_STATIC_PERIODIC):
        if len({item.message_id for item in ordered}) < 2:
            _tf_error(
                'TF_EDGE_BEHAVIOR_MISMATCH',
                '{}->{} lacks repeated TFMessage evidence'.format(
                    rule.parent_frame, rule.child_frame))
        stamps = [item.source_stamp for item in ordered]
        receipts = [item.receipt_monotonic for item in ordered]
        if not _strictly_increasing(stamps):
            _tf_error(
                'TF_EDGE_BEHAVIOR_MISMATCH',
                '{}->{} source stamps do not advance'.format(
                    rule.parent_frame, rule.child_frame))
        if not _strictly_increasing(receipts):
            _tf_error(
                'TF_EDGE_BEHAVIOR_MISMATCH',
                '{}->{} receipt times do not advance'.format(
                    rule.parent_frame, rule.child_frame))
        if timeout is not None:
            age = now - receipts[-1]
            if not 0.0 <= age < timeout:
                _tf_error(
                    'TF_EDGE_BEHAVIOR_MISMATCH',
                    '{}->{} repeated evidence is stale'.format(
                        rule.parent_frame, rule.child_frame))
        if source_timeout is not None:
            source_age = source_now - stamps[-1]
            if not -source_future_tolerance <= source_age < source_timeout:
                _tf_error(
                    'TF_EDGE_SOURCE_TIME_INVALID',
                    '{}->{} source age is outside the accepted window'.format(
                        rule.parent_frame, rule.child_frame))


def validate_tf_edge_evidence(
        observations, stage, vendor_rules=None,
        current_tf_publishers_by_topic=None,
        now_monotonic=None, dynamic_timeout_s=None,
        now_source_time=None, source_timeout_s=None,
        source_future_tolerance_s=None):
    """Validate exact owners and transports for safety-critical TF edges.

    This function is dependency-free and does not alter the existing ROS graph,
    action, velocity, READY, or stop-latch policy.  A verified vendor rule for
    ``base_link -> laser_link`` is mandatory; unresolved vendor source or
    transport therefore remains fail-closed.
    """
    stage_rules, forbidden_edges = _stage_tf_rules(stage)
    normalized_vendor_rules = _require_verified_vendor_contract(vendor_rules)

    rules = stage_rules + normalized_vendor_rules
    rules_by_edge = {}
    rules_by_child = {}
    allowed_edges_by_authority = {}
    for rule in rules:
        edge = (rule.parent_frame, rule.child_frame)
        previous = rules_by_edge.get(edge)
        if previous is not None and previous != rule:
            _tf_error(
                'TF_RULE_INVALID',
                '{}->{} has conflicting rules'.format(*edge))
        previous_child = rules_by_child.get(rule.child_frame)
        if previous_child is not None and previous_child.parent_frame != (
                rule.parent_frame):
            _tf_error(
                'TF_RULE_INVALID',
                '{} has multiple expected parents'.format(rule.child_frame))
        rules_by_edge[edge] = rule
        rules_by_child[rule.child_frame] = rule
        allowed_edges_by_authority.setdefault(rule.authority, set()).add(edge)

    if observations is None:
        _tf_error('TF_EDGE_EVIDENCE_MISSING', 'TF observations are missing')
    try:
        normalized_observations = tuple(
            _normalize_tf_observation(item) for item in observations)
    except TypeError:
        _tf_error(
            'TF_EDGE_EVIDENCE_MISSING', 'TF observations must be iterable')
    if not normalized_observations:
        _tf_error('TF_EDGE_EVIDENCE_MISSING', 'TF observations are empty')

    if (now_monotonic is None) != (dynamic_timeout_s is None):
        _tf_error(
            'TF_OBSERVATION_INVALID',
            'now_monotonic and dynamic_timeout_s must be supplied together')
    now = None
    timeout = None
    if now_monotonic is not None:
        now = _finite_tf_number(now_monotonic, 'now_monotonic')
        timeout = _finite_tf_number(
            dynamic_timeout_s, 'dynamic_timeout_s')
        if timeout <= 0.0:
            _tf_error(
                'TF_OBSERVATION_INVALID',
                'dynamic_timeout_s must be positive')
    source_values = (
        now_source_time, source_timeout_s, source_future_tolerance_s)
    if any(value is not None for value in source_values) and not all(
            value is not None for value in source_values):
        _tf_error(
            'TF_OBSERVATION_INVALID',
            'source-time validation parameters must be supplied together')
    source_now = None
    source_timeout = None
    source_future_tolerance = None
    if now_source_time is not None:
        source_now = _finite_tf_number(
            now_source_time, 'now_source_time')
        source_timeout = _finite_tf_number(
            source_timeout_s, 'source_timeout_s')
        source_future_tolerance = _finite_tf_number(
            source_future_tolerance_s, 'source_future_tolerance_s')
        if source_timeout <= 0.0:
            _tf_error(
                'TF_OBSERVATION_INVALID',
                'source_timeout_s must be positive')
        if source_future_tolerance < 0.0:
            _tf_error(
                'TF_OBSERVATION_INVALID',
                'source_future_tolerance_s must be nonnegative')

    by_edge = {}
    by_child = {}
    observed_by_topic = {topic: set() for topic in _TF_TOPICS}
    for item in normalized_observations:
        edge = (item.parent_frame, item.child_frame)
        by_edge.setdefault(edge, []).append(item)
        by_child.setdefault(item.child_frame, []).append(item)
        observed_by_topic[item.topic].add(item.authority)

    protected_edges = set(rules_by_edge)
    protected_children = set(rules_by_child)
    for child in protected_children:
        values = by_child.get(child, ())
        authorities = {item.authority for item in values}
        parents = {item.parent_frame for item in values}
        if len(authorities) > 1:
            _tf_error(
                'TF_CHILD_MULTIPLE_OWNERS',
                '{} has multiple authorities: {}'.format(
                    child, sorted(authorities)))
        if len(parents) > 1:
            _tf_error(
                'TF_CHILD_MULTIPLE_PARENTS',
                '{} has multiple parents: {}'.format(
                    child, sorted(parents)))
    for edge in protected_edges:
        topics = {item.topic for item in by_edge.get(edge, ())}
        if len(topics) > 1:
            _tf_error(
                'TF_EDGE_MULTIPLE_TOPICS',
                '{}->{} appears on /tf and /tf_static'.format(*edge))
    for item in normalized_observations:
        allowed = allowed_edges_by_authority.get(item.authority)
        edge = (item.parent_frame, item.child_frame)
        if allowed is not None and edge not in allowed:
            _tf_error(
                'TF_AUTHORITY_CONFLICTING_EDGE',
                '{} published unexpected {}->{}'.format(
                    item.authority, item.parent_frame, item.child_frame))

    for edge in forbidden_edges:
        if edge in by_edge:
            _tf_error(
                'TF_EDGE_FORBIDDEN_PRESENT',
                '{}->{} is forbidden in {}'.format(
                    edge[0], edge[1], stage))

    summaries = []
    for edge, rule in sorted(rules_by_edge.items()):
        values = by_edge.get(edge, ())
        if not values:
            _tf_error(
                'TF_EDGE_REQUIRED_MISSING',
                '{}->{} evidence is missing'.format(*edge))
        authorities = {item.authority for item in values}
        if authorities != {rule.authority}:
            _tf_error(
                'TF_EDGE_OWNER_MISMATCH',
                '{}->{} authorities are {}, expected {}'.format(
                    edge[0], edge[1], sorted(authorities), rule.authority))
        topics = {item.topic for item in values}
        if topics != {rule.topic}:
            _tf_error(
                'TF_EDGE_TOPIC_MISMATCH',
                '{}->{} topics are {}, expected {}'.format(
                    edge[0], edge[1], sorted(topics), rule.topic))
        _validate_tf_rule_behavior(
            rule, values, now, timeout,
            source_now, source_timeout, source_future_tolerance)
        summaries.append({
            'parent_frame': edge[0],
            'child_frame': edge[1],
            'authority': rule.authority,
            'topic': rule.topic,
            'behavior': rule.behavior,
            'message_count': len({item.message_id for item in values}),
            'sample_count': len(values),
        })

    # Graph attribution is a coarse completeness check.  Run it only after
    # the edge-specific owner/topic/behavior checks so diagnostics cannot
    # hide a more precise protected-edge contract violation.
    if current_tf_publishers_by_topic is not None:
        if not isinstance(current_tf_publishers_by_topic, dict):
            _tf_error(
                'TF_GRAPH_CAPTURE_MISMATCH',
                'current TF publisher state must be a mapping')
        for topic in _TF_TOPICS:
            try:
                graph_authorities = {
                    _canonical_tf_authority(owner)
                    for owner in current_tf_publishers_by_topic.get(
                        topic, ())}
            except TypeError:
                _tf_error(
                    'TF_GRAPH_CAPTURE_MISMATCH',
                    '{} graph owners must be iterable'.format(topic))
            missing = graph_authorities - observed_by_topic[topic]
            if missing:
                _tf_error(
                    'TF_GRAPH_CAPTURE_MISMATCH',
                    '{} graph publishers lack captured edge evidence: {}'.format(
                        topic, sorted(missing)))
            protected_observed = {
                item.authority for item in normalized_observations
                if item.topic == topic and (
                    (item.parent_frame, item.child_frame) in protected_edges
                    or item.child_frame in protected_children
                    or item.authority in allowed_edges_by_authority)}
            stale = protected_observed - graph_authorities
            if stale:
                _tf_error(
                    'TF_GRAPH_CAPTURE_MISMATCH',
                    '{} protected evidence has no current graph owner: {}'.format(
                        topic, sorted(stale)))

    observed_summaries = []
    for edge, values in sorted(by_edge.items()):
        ordered = sorted(
            values,
            key=lambda item: (item.receipt_monotonic, item.message_id))
        stamps = [item.source_stamp for item in ordered]
        if len(stamps) < 2:
            stamp_behavior = 'SINGLE_SAMPLE'
        elif _strictly_increasing(stamps):
            stamp_behavior = 'STRICTLY_INCREASING'
        elif len(set(stamps)) == 1:
            stamp_behavior = 'CONSTANT'
        else:
            stamp_behavior = 'NON_MONOTONIC'
        reference = ordered[0]
        observed_summaries.append({
            'parent_frame': edge[0],
            'child_frame': edge[1],
            'authorities': sorted({item.authority for item in ordered}),
            'topics': sorted({item.topic for item in ordered}),
            'message_count': len({item.message_id for item in ordered}),
            'sample_count': len(ordered),
            'first_source_stamp': stamps[0],
            'last_source_stamp': stamps[-1],
            'source_stamp_behavior': stamp_behavior,
            'first_receipt_monotonic': ordered[0].receipt_monotonic,
            'last_receipt_monotonic': ordered[-1].receipt_monotonic,
            'reference_translation': list(reference.translation),
            'reference_rotation': list(reference.rotation),
            'geometry_stable': len({
                (item.translation, item.rotation) for item in ordered}) == 1,
            'latching_values': sorted({item.latching for item in ordered}),
        })
    return {
        'status': 'TF_EDGE_TOPOLOGY_PASS',
        'stage': stage,
        'edges': summaries,
        'observed_edges': observed_summaries,
    }


def _owners(mapping, topic):
    return set(mapping.get(topic, ()))


def _action_topic(prefix, suffix):
    return '{}/{}'.format(prefix.rstrip('/'), suffix)


def _require_no_endpoints(publishers, subscribers, topic, description):
    if _owners(publishers, topic) or _owners(subscribers, topic):
        raise RuntimeError('{} is forbidden: {}'.format(description, topic))


def validate_topology(
        publishers, subscribers, tf_publishers, navigation,
        mode='native', active_nodes=None, phase='runtime'):
    """Raise unless every safety-critical endpoint has exact ownership."""
    expected = ExpectedTopology()
    if mode not in ('native', 'integrated'):
        raise RuntimeError('navigation mode must be native or integrated')
    if phase not in ('precore', 'runtime'):
        raise RuntimeError('topology phase must be precore or runtime')
    if _owners(publishers, expected.scan_topic) != {expected.scan_node}:
        raise RuntimeError('/scan must have exactly one accepted publisher')
    if _owners(publishers, expected.odom_topic) != {expected.odom_node}:
        raise RuntimeError('/odom must have exactly one accepted publisher')
    if expected.odom_node not in set(tf_publishers):
        raise RuntimeError('limo_base_node odom TF owner is missing')
    if expected.forbidden_tf_node in set(tf_publishers):
        raise RuntimeError('robot_pose_ekf is a forbidden odom TF owner')
    if _owners(publishers, expected.public_cmd_topic):
        raise RuntimeError('public /cmd_vel publisher is forbidden')
    if _owners(subscribers, expected.public_cmd_topic):
        raise RuntimeError('public /cmd_vel subscriber is forbidden')
    action_suffixes = ('goal', 'cancel', 'status', 'feedback', 'result')
    if phase == 'precore':
        if navigation:
            raise RuntimeError('pre-core topology cannot require navigation')
        for topic in (expected.public_goal_topic, expected.private_goal_topic):
            _require_no_endpoints(
                publishers, subscribers, topic,
                'pre-core simple goal endpoint')
        for prefix in (
                expected.public_action_prefix,
                expected.private_action_prefix):
            for suffix in action_suffixes:
                topic = _action_topic(prefix, suffix)
                _require_no_endpoints(
                    publishers, subscribers, topic,
                    'pre-core move_base action endpoint')
        graph_nodes = set(tf_publishers)
        for mapping in (publishers, subscribers):
            for owners in mapping.values():
                graph_nodes.update(owners)
        for canonical in (
                expected.map_server_node, expected.amcl_node,
                expected.move_base_node,
                expected.guard_node, expected.navigation_adapter_node):
            aliases = {
                node for node in graph_nodes
                if node == canonical or node.startswith(canonical + '_')}
            if aliases:
                raise RuntimeError(
                    '{} must be absent before private core spawn'.format(
                        canonical))
        return

    if not navigation:
        _require_no_endpoints(
            publishers, subscribers, expected.public_goal_topic,
            'public move_base_simple goal endpoint')
        for suffix in action_suffixes:
            public_topic = _action_topic(
                expected.public_action_prefix, suffix)
            _require_no_endpoints(
                publishers, subscribers, public_topic,
                'public move_base action endpoint')
    else:
        if mode == 'native':
            action_prefix = expected.private_action_prefix
            inactive_action_prefix = expected.public_action_prefix
            simple_goal_topic = expected.private_goal_topic
            inactive_simple_goal_topic = expected.public_goal_topic
            action_client = expected.gateway_node
            status_subscribers = {
                expected.gateway_node,
                expected.localization_manager_node,
            }
        else:
            action_prefix = expected.public_action_prefix
            inactive_action_prefix = expected.private_action_prefix
            simple_goal_topic = expected.public_goal_topic
            inactive_simple_goal_topic = expected.private_goal_topic
            action_client = expected.navigation_adapter_node
            status_subscribers = {expected.navigation_adapter_node}

        _require_no_endpoints(
            publishers, subscribers, inactive_simple_goal_topic,
            'inactive-mode move_base_simple goal endpoint')
        for suffix in action_suffixes:
            inactive_topic = _action_topic(inactive_action_prefix, suffix)
            _require_no_endpoints(
                publishers, subscribers, inactive_topic,
                'inactive-mode move_base action endpoint')

        if _owners(publishers, simple_goal_topic):
            raise RuntimeError(
                '{} must have no publishers'.format(simple_goal_topic))
        if _owners(subscribers, simple_goal_topic) != {
                expected.move_base_node}:
            raise RuntimeError(
                '{} must terminate only at move_base'.format(
                    simple_goal_topic))

        expected_action_owners = {
            'goal': (
                {action_client}, {expected.move_base_node}),
            'cancel': (
                {action_client}, {expected.move_base_node}),
            'status': (
                {expected.move_base_node}, status_subscribers),
            'feedback': (
                {expected.move_base_node}, {action_client}),
            'result': (
                {expected.move_base_node}, {action_client}),
        }
        for suffix, (allowed_publishers, allowed_subscribers) in (
                expected_action_owners.items()):
            topic = _action_topic(action_prefix, suffix)
            if _owners(publishers, topic) != allowed_publishers:
                raise RuntimeError(
                    '{} publishers do not match the {} action contract'.format(
                        topic, mode))
            if _owners(subscribers, topic) != allowed_subscribers:
                raise RuntimeError(
                    '{} subscribers do not match the {} action contract'.format(
                        topic, mode))
    if navigation:
        if mode == 'native':
            if _owners(publishers, expected.nav_cmd_topic) != {
                    expected.move_base_node}:
                raise RuntimeError(
                    'move_base must be the sole native request owner')
            if _owners(subscribers, expected.nav_cmd_topic) != {
                    expected.guard_node}:
                raise RuntimeError(
                    'V1 guard must be the sole native request consumer')
            if _owners(publishers, expected.driver_cmd_topic) != {
                    expected.guard_node}:
                raise RuntimeError(
                    'V1 guard must be the sole native driver owner')
            if _owners(subscribers, expected.driver_cmd_topic) != {
                    expected.odom_node}:
                raise RuntimeError(
                    'limo_base_node must be the sole native driver consumer')
            for topic in (
                    expected.integrated_request_topic,
                    expected.integrated_safe_topic,
                    expected.integrated_driver_topic):
                if _owners(publishers, topic) or _owners(subscribers, topic):
                    raise RuntimeError(
                        'integrated speed topic is forbidden in native mode')
        else:
            for topic in (expected.nav_cmd_topic, expected.driver_cmd_topic):
                if _owners(publishers, topic) or _owners(subscribers, topic):
                    raise RuntimeError(
                        'V1 speed topic is forbidden in integrated mode')
            if _owners(publishers, expected.integrated_request_topic) != {
                    expected.move_base_node}:
                raise RuntimeError(
                    'move_base must solely own integrated request output')
            if _owners(subscribers, expected.integrated_request_topic) != {
                    expected.bridge_node}:
                raise RuntimeError(
                    'dynamic bridge must solely consume integrated requests')
            if _owners(publishers, expected.integrated_safe_topic) != {
                    expected.bridge_node}:
                raise RuntimeError(
                    'dynamic bridge must solely own integrated safe commands')
            if _owners(subscribers, expected.integrated_safe_topic) != {
                    expected.bridge_watchdog_node}:
                raise RuntimeError(
                    'bridge watchdog must solely consume safe commands')
            if _owners(publishers, expected.integrated_driver_topic) != {
                    expected.bridge_watchdog_node}:
                raise RuntimeError(
                    'bridge watchdog must solely own integrated driver output')
            expected_driver_consumers = {
                expected.odom_node, expected.bridge_verifier_node}
            if _owners(
                    subscribers,
                    expected.integrated_driver_topic) != expected_driver_consumers:
                raise RuntimeError(
                    'integrated driver consumers do not match the contract')

    if active_nodes is not None:
        nodes = set(active_nodes)
        if navigation:
            common_required_nodes = {
                expected.map_server_node,
                expected.amcl_node,
                expected.move_base_node,
            }
            common_forbidden_nodes = {
                expected.gmapping_node,
                expected.cartographer_node,
                expected.forbidden_tf_node,
            }
            if mode == 'native':
                required_nodes = common_required_nodes | {
                    expected.guard_node,
                    expected.gateway_node,
                    expected.localization_manager_node,
                }
                forbidden_nodes = common_forbidden_nodes | {
                    expected.bridge_watchdog_node,
                    expected.navigation_adapter_node,
                }
            else:
                required_nodes = common_required_nodes | {
                    expected.bridge_node,
                    expected.bridge_watchdog_node,
                    expected.bridge_verifier_node,
                    expected.navigation_adapter_node,
                }
                forbidden_nodes = common_forbidden_nodes | {
                    expected.guard_node,
                    expected.gateway_node,
                    expected.localization_manager_node,
                }
            missing = required_nodes - nodes
            if missing:
                raise RuntimeError(
                    '{} mode is missing required fail-closed nodes: {}'.format(
                        mode, sorted(missing)))
            present = forbidden_nodes & nodes
            if present:
                raise RuntimeError(
                    '{} mode contains forbidden owner/guard nodes: {}'.format(
                        mode, sorted(present)))
        canonical_nodes = [expected.odom_node]
        if navigation:
            canonical_nodes.extend((
                expected.map_server_node,
                expected.amcl_node,
                expected.move_base_node,
            ))
        for canonical in canonical_nodes:
            aliases = {
                node for node in nodes
                if node == canonical or node.startswith(canonical + '_')}
            if aliases != {canonical}:
                raise RuntimeError(
                    '{} must have exactly one canonical instance'.format(
                        canonical))

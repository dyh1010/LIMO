import csv
import hashlib
import json
from pathlib import Path
import re
import shlex
import unittest
import xml.etree.ElementTree as ET


PACKAGE_ROOT = Path(__file__).parents[1]
WORKSPACE_ROOT = PACKAGE_ROOT.parents[1]
BRIDGE_ROOT = (
    WORKSPACE_ROOT / 'ros1_overlay_src' / 'limo_cleanup_ros1_base')
DOCUMENT = (
    PACKAGE_ROOT / 'docs' / 'V1_DEPLOYMENT_DIAGNOSTICS_ROLLBACK.md')
TEMPLATE = (
    PACKAGE_ROOT / 'docs' / 'examples'
    / 'v1_field_session_record_template.json')
OBSERVATION_AUDIT = (
    PACKAGE_ROOT / 'docs' / 'V1_USER_OBSERVED_FIELD_EVIDENCE_AUDIT.md')
CAPTURE_TABLE = (
    PACKAGE_ROOT / 'docs' / 'examples'
    / 'v1_field_minimum_evidence_capture_table.csv')
OBSERVATION_DIRECTORY = (
    WORKSPACE_ROOT / 'evidence' / 'v1_field_observation_20260814')
OBSERVATION_RECORD = OBSERVATION_DIRECTORY / 'user_observed_partial.json'
OBSERVATION_HASHES = OBSERVATION_DIRECTORY / 'SHA256SUMS.txt'
OWNERSHIP_DOCUMENT = (
    PACKAGE_ROOT / 'docs' / 'V1_ROS1_RUNTIME_OWNERSHIP.md')
FIELD_RUNBOOK = PACKAGE_ROOT / 'docs' / 'V1_FIELD_RUNBOOK.md'
OWNERSHIP_TABLE = (
    PACKAGE_ROOT / 'docs' / 'V1_ROS1_RUNTIME_OWNERSHIP.json')
VENDOR_INCLUDE_BLOCKER = (
    PACKAGE_ROOT / 'docs' / 'V1_ROS1_VENDOR_INCLUDE_BLOCKER.json')
PERCEPTION_ONLY_DOCUMENT = (
    PACKAGE_ROOT / 'docs' / 'V1_PERCEPTION_ONLY_FIELD_PACKAGE.md')
PERCEPTION_ONLY_RESULT = (
    PACKAGE_ROOT / 'docs' / 'V1_PERCEPTION_ONLY_RESULT_TEMPLATE.md')

FIELD_RUNBOOK_BRIDGE_HEADING = (
    '### 4.1 Explicit integrated bridge exception (not a native stage)')
FIELD_RUNBOOK_BRIDGE_ALLOWLIST = (
    'scripts/ros1_base_bridge_preflight.sh',
    'scripts/run_ros1_base_bridge_zero_stage.sh',
)
FIELD_RUNBOOK_BRIDGE_REQUIRED_MARKERS = (
    'fresh, independent integrated-bridge authorization',
    'never inherited by a native/current ROS1 stage',
    'existing read-only/zero-chain scope',
    'exact domain and localhost policy already enforced by those scripts',
    'This runbook adds no alternate DDS scope',
    'does not expand either script\'s existing one-time authorization',
    'not native Noetic field or delivery evidence',
)


def _markdown_section_bounds(source, heading):
    """Return the exact section bounds through the next peer heading."""
    heading_pattern = re.compile(
        r'^{}[ \t]*$'.format(re.escape(heading)), re.MULTILINE)
    matches = list(heading_pattern.finditer(source))
    if len(matches) != 1:
        return None
    match = matches[0]
    level = len(heading) - len(heading.lstrip('#'))
    next_heading = re.search(
        r'^#{1,' + str(level) + r'}[ \t]+',
        source[match.end():],
        re.MULTILINE)
    end = len(source)
    if next_heading is not None:
        end = match.end() + next_heading.start()
    return match.start(), end


def _inline_code_spans(line):
    """Extract CommonMark-style backtick code spans from one source line."""
    spans = []
    cursor = 0
    while cursor < len(line):
        opening = line.find('`', cursor)
        if opening < 0:
            break
        opening_end = opening
        while opening_end < len(line) and line[opening_end] == '`':
            opening_end += 1
        delimiter = line[opening:opening_end]
        search = opening_end
        while search < len(line):
            candidate = line.find('`', search)
            if candidate < 0:
                return spans
            candidate_end = candidate
            while candidate_end < len(line) and line[candidate_end] == '`':
                candidate_end += 1
            if candidate_end - candidate == len(delimiter):
                body = line[opening_end:candidate]
                if (len(body) > 2 and body.startswith(' ')
                        and body.endswith(' ') and body.strip()):
                    body = body[1:-1]
                spans.append(body.replace('\t', ' '))
                cursor = candidate_end
                break
            search = candidate_end
        else:
            break
    return spans


def _fenced_code_surfaces(lines):
    """Extract all valid backtick/tilde fences and their occupied lines."""
    surfaces = []
    occupied = set()
    opening_pattern = re.compile(
        r'^(?P<indent> {0,3})(?P<fence>`{3,}|~{3,})(?P<info>.*)$')
    index = 0
    while index < len(lines):
        opening = opening_pattern.match(lines[index])
        if opening is None:
            index += 1
            continue
        fence = opening.group('fence')
        if fence[0] == '`' and '`' in opening.group('info'):
            index += 1
            continue
        closing_pattern = re.compile(
            r'^ {0,3}' + re.escape(fence[0])
            + '{' + str(len(fence)) + r',}[ \t]*$')
        closing = index + 1
        while closing < len(lines):
            if closing_pattern.match(lines[closing]):
                break
            closing += 1
        body_end = min(closing, len(lines))
        surfaces.append('\n'.join(lines[index + 1:body_end]))
        occupied.update(range(index, min(closing + 1, len(lines))))
        index = closing + 1
    return surfaces, occupied


def _command_surfaces(source):
    """Extract CommonMark executable surfaces without executing anything."""
    lines = source.splitlines()
    surfaces, occupied = _fenced_code_surfaces(lines)

    index = 0
    while index < len(lines):
        if index in occupied:
            index += 1
            continue
        if not (lines[index].startswith('    ')
                or lines[index].startswith('\t')):
            index += 1
            continue
        block = []
        while index < len(lines) and index not in occupied:
            line = lines[index]
            if line.startswith('    '):
                block.append(line[4:])
            elif line.startswith('\t'):
                block.append(line[1:])
            elif not line.strip():
                block.append('')
            else:
                break
            occupied.add(index)
            index += 1
        surfaces.append('\n'.join(block))

    prompt_pattern = re.compile(
        r'^ {0,3}(?:\$|>|[\w.-]+@[^: ]+:[^$#]*[$#])\s+')
    for index, line in enumerate(lines):
        if index in occupied:
            continue
        surfaces.extend(_inline_code_spans(line))
        if prompt_pattern.match(line):
            surfaces.append(line)
    return surfaces


def _logical_shell_lines(surface):
    continued = re.sub(r'\\[ \t]*\r?\n[ \t]*', ' ', surface)
    prompt_pattern = re.compile(
        r'^\s*(?:\$|>|[\w.-]+@[^: ]+:[^$#]*[$#])\s+')
    return [
        prompt_pattern.sub('', line).strip()
        for line in continued.splitlines()
        if line.strip()
    ]


def _shell_tokens(line):
    lexer = shlex.shlex(line, posix=True, punctuation_chars=';&|')
    lexer.whitespace_split = True
    lexer.commenters = '#'
    return list(lexer)


def _token_basename(token):
    return token.rsplit('/', 1)[-1]


def _forbidden_ros2_command_kinds(source):
    kinds = set()
    for surface in _command_surfaces(source):
        for line in _logical_shell_lines(surface):
            if re.search(
                    r'(?<![A-Za-z0-9_])ros2(?=\s|["\']|$)', line):
                kinds.add('ros2_cli')
            try:
                tokens = _shell_tokens(line)
            except ValueError:
                kinds.add('unparseable_shell_surface')
                continue
            basenames = [_token_basename(token) for token in tokens]
            if 'ros2' in basenames:
                kinds.add('ros2_cli')
            if 'colcon' in basenames:
                kinds.add('colcon')
            for position, token in enumerate(tokens[:-1]):
                if token in ('source', '.') and re.match(
                        r'^/opt/ros/(?:foxy|humble)/',
                        tokens[position + 1]):
                    kinds.add('foxy_or_humble_source')
    return sorted(kinds)


def _first_command_word(tokens):
    wrappers = {'builtin', 'command', 'env', 'nohup', 'sudo'}
    reserved_prefixes = {
        'do', 'elif', 'else', 'if', 'then', 'until', 'while',
    }
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token in reserved_prefixes or token in ('!', 'time'):
            index += 1
            continue
        if re.match(r'^[A-Za-z_][A-Za-z0-9_]*=', token):
            index += 1
            continue
        if _token_basename(token) in wrappers:
            index += 1
            while index < len(tokens) and (
                    tokens[index].startswith('-')
                    or re.match(
                        r'^[A-Za-z_][A-Za-z0-9_]*=', tokens[index])):
                index += 1
            continue
        return token
    return None


def _native_dynamic_shell_kinds(source):
    kinds = set()
    controls = {';', '&&', '||', '|', '&'}
    shells = {'bash', 'dash', 'ksh', 'sh', 'zsh'}
    for surface in _command_surfaces(source):
        for line in _logical_shell_lines(surface):
            if '$(' in line or '`' in line:
                kinds.add('command_substitution')
            try:
                tokens = _shell_tokens(line)
            except ValueError:
                kinds.add('unparseable_shell_surface')
                continue
            basenames = [_token_basename(token) for token in tokens]
            if any(token in ('eval', 'exec') for token in basenames):
                kinds.add('eval_or_exec')
            for position, token in enumerate(basenames[:-1]):
                if (token in shells and tokens[position + 1].startswith('-')
                        and 'c' in tokens[position + 1][1:]):
                    kinds.add('shell_c_wrapper')
            segment = []
            for token in tokens + [';']:
                if token in controls:
                    command_word = _first_command_word(segment)
                    if command_word is not None and '$' in command_word:
                        kinds.add('dynamic_command_position')
                    segment = []
                else:
                    segment.append(token)
    return sorted(kinds)


def _field_runbook_ros1_cli_contract_errors(source):
    """Host-owned policy for the native ROS1 and bridge documentation split."""
    errors = []
    bounds = _markdown_section_bounds(
        source, FIELD_RUNBOOK_BRIDGE_HEADING)
    if bounds is None:
        errors.append('bridge_section_missing_or_duplicated')
        bridge_section = ''
        bridge_start = bridge_end = -1
        native_source = source
    else:
        bridge_start, bridge_end = bounds
        bridge_section = source[bridge_start:bridge_end]
        native_source = source[:bridge_start] + source[bridge_end:]

    bridge_normalized = ' '.join(bridge_section.split())
    for marker in FIELD_RUNBOOK_BRIDGE_REQUIRED_MARKERS:
        if marker not in bridge_normalized:
            errors.append('bridge_boundary_marker_missing:' + marker)

    for script in FIELD_RUNBOOK_BRIDGE_ALLOWLIST:
        reference = '`{}`'.format(script)
        positions = [
            match.start() for match in re.finditer(
                re.escape(reference), source)]
        if len(positions) != 1:
            errors.append('bridge_allowlist_reference_count:' + script)
        elif not (bridge_start <= positions[0] < bridge_end):
            errors.append('bridge_allowlist_reference_outside_section:' + script)

    discovered_scripts = set(re.findall(
        r'`(scripts/[A-Za-z0-9_.-]+\.sh)`', bridge_section))
    if discovered_scripts != set(FIELD_RUNBOOK_BRIDGE_ALLOWLIST):
        errors.append('bridge_allowlist_changed')

    bridge_executable_surfaces = []
    for surface in _command_surfaces(bridge_section):
        for line in _logical_shell_lines(surface):
            try:
                tokens = _shell_tokens(line)
            except ValueError:
                bridge_executable_surfaces.append('<UNPARSEABLE>')
                continue
            bridge_executable_surfaces.append(' '.join(tokens))
    if sorted(bridge_executable_surfaces) != sorted(
            FIELD_RUNBOOK_BRIDGE_ALLOWLIST):
        errors.append('bridge_executable_surface_changed')

    for kind in _forbidden_ros2_command_kinds(source):
        errors.append('forbidden_command_surface:' + kind)
    for kind in _native_dynamic_shell_kinds(native_source):
        errors.append('forbidden_native_shell_construct:' + kind)
    return sorted(errors)


class DeploymentRunbookContractTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.document = DOCUMENT.read_text(encoding='utf-8')
        cls.template_source = TEMPLATE.read_text(encoding='utf-8')
        cls.template = json.loads(cls.template_source)
        cls.observation_audit = OBSERVATION_AUDIT.read_text(encoding='utf-8')
        cls.observation_source = OBSERVATION_RECORD.read_text(encoding='utf-8')
        cls.observation = json.loads(cls.observation_source)
        cls.ownership_document = OWNERSHIP_DOCUMENT.read_text(encoding='utf-8')
        cls.field_runbook = FIELD_RUNBOOK.read_text(encoding='utf-8')
        cls.ownership = json.loads(OWNERSHIP_TABLE.read_text(encoding='utf-8'))
        cls.vendor_include_blocker = json.loads(
            VENDOR_INCLUDE_BLOCKER.read_text(encoding='utf-8'))
        cls.perception_only_document = PERCEPTION_ONLY_DOCUMENT.read_text(
            encoding='utf-8')
        cls.perception_only_result = PERCEPTION_ONLY_RESULT.read_text(
            encoding='utf-8')
        with CAPTURE_TABLE.open(encoding='utf-8', newline='') as stream:
            cls.capture_rows = list(csv.DictReader(stream))

    def test_session_template_is_fail_closed_and_not_field_evidence(self):
        payload = self.template
        self.assertEqual(
            payload['schema'], 'limo_v1_field_session_record/v1')
        self.assertTrue(payload['template_only'])
        self.assertFalse(payload['real_machine_evidence'])
        self.assertEqual(payload['status'], 'NOT_RUN')
        self.assertFalse(payload['delivery_ready'])
        self.assertFalse(payload['decision']['software_release_pass'])
        self.assertFalse(payload['decision']['field_acceptance_complete'])
        self.assertTrue(
            payload['decision']['all_software_deployment_blockers_closed'])
        self.assertFalse(
            payload['decision']['all_field_deployment_blockers_closed'])
        self.assertFalse(payload['decision']['delivery_ready'])
        self.assertEqual(payload['decision']['status'], 'BLOCKED')
        self.assertFalse(
            payload['release_boundary'][
                'software_pass_implies_field_pass'])
        self.assertFalse(
            payload['release_boundary'][
                'software_pass_implies_delivery_ready'])

    def test_record_creation_and_no_autostart_are_explicit(self):
        creation = self.template['record_creation']
        self.assertTrue(creation['copy_template_to_new_timestamped_file'])
        self.assertTrue(creation['exclusive_create_required'])
        self.assertFalse(creation['overwrite_allowed'])
        release = self.template['release_boundary']
        self.assertEqual(release['autostart_policy'], 'NO_AUTOSTART')
        for mode in self.template['deployment_modes'].values():
            self.assertFalse(mode['autostart'])
        self.assertIn('NO_AUTOSTART', self.document)
        self.assertIn('Do not add an autostart mechanism', self.document)

    def test_native_defaults_are_source_backed_and_not_authorization(self):
        sensors = ET.parse(
            PACKAGE_ROOT / 'launch' / 'v1_base_sensors.launch').getroot()
        navigation = ET.parse(
            PACKAGE_ROOT / 'launch' / 'v1_navigation.launch').getroot()
        sensor_args = {
            item.attrib['name']: item.attrib.get('default')
            for item in sensors.findall('./arg')
        }
        navigation_args = {
            item.attrib['name']: item.attrib.get('default')
            for item in navigation.findall('./arg')
        }
        self.assertEqual(sensor_args['enable_hardware'], 'false')
        for name in (
                'allow_nonzero', 'driver_timeout_verified',
                'enable_goal_gateway', 'allow_goal_forwarding'):
            self.assertEqual(navigation_args[name], 'false')
        move_base = (
            PACKAGE_ROOT / 'config' / 'move_base.yaml').read_text(
                encoding='utf-8')
        self.assertIn('recovery_behavior_enabled: false', move_base)
        self.assertIn('clearing_rotation_allowed: false', move_base)
        native = self.template['deployment_modes']['native']
        self.assertEqual(native['design_audit_status'], 'PASS')
        self.assertEqual(native['execution_status'], 'BLOCKED')
        self.assertIn(
            'These defaults are safety gates, not proof of authorization',
            self.document)
        ownership = self.ownership
        self.assertEqual(
            ownership['schema'], 'limo_v1_ros1_runtime_ownership/v1')
        self.assertEqual(ownership['document_status'], 'PROVISIONAL_BLOCKED')
        self.assertEqual(
            ownership['blocker_code'], 'BLOCKED_ON_VENDOR_INCLUDE')
        self.assertEqual(
            ownership['claim_scope'], 'DESIGN_INTENT_NOT_RUNTIME_VERIFIED')
        baseline = ownership['runtime_baseline']
        self.assertEqual(baseline['default_middleware'], 'ROS1_NOETIC')
        self.assertEqual(baseline['default_mode'], 'native')
        self.assertFalse(baseline['ros2_foxy_live_runtime_assumed'])
        self.assertEqual(baseline['ros2_foxy_allowed_scopes'], [
            'OFFLINE_CODE', 'EXPLICIT_INTEGRATED_BRIDGE_MODE'])
        self.assertFalse(
            baseline['field_access_authorized_by_this_document'])
        rows = {row['id']: row for row in ownership['ownership_rows']}
        self.assertEqual(set(rows), {
            'ros1_master', 'base_driver', 'lidar', 'laser_static_tf',
            'mapping_slam', 'map_server', 'amcl',
            'move_base_and_costmaps', 'localization_manager',
            'goal_gateway', 'velocity_guard', 'public_cmd_vel',
        })
        self.assertEqual(rows['base_driver']['canonical_node'],
                         '/limo_base_node')
        self.assertEqual(rows['amcl']['tf_edges'], ['map->odom'])
        laser = rows['laser_static_tf']
        self.assertIsNone(laser['canonical_node'])
        self.assertEqual(
            laser['historical_candidate_node'],
            '/base_link_to_laser_link')
        self.assertEqual(
            laser['owner_status'],
            'PROVISIONAL_BLOCKED_ON_VENDOR_INCLUDE')
        self.assertEqual(
            laser['tf_transport'],
            'PROVISIONAL_UNRESOLVED_/tf_VS_/tf_static')
        self.assertIsNone(laser['selected_transport'])
        self.assertEqual(
            laser['candidate_transports_pending_pin'], ['/tf', '/tf_static'])
        self.assertFalse(laser['candidate_transports_are_runtime_allowlist'])
        self.assertEqual(laser['temporal_semantics'], 'STATIC')
        self.assertFalse(laser['runtime_pass_eligible'])
        self.assertEqual(laser['publishes'], [])
        for stage in ownership['stage_tf_ownership'].values():
            self.assertEqual(
                stage['base_link_to_laser_link'],
                'PROVISIONAL_BLOCKED_ON_VENDOR_INCLUDE')
        edge_contract = ownership['tf_edge_observation_contract']
        self.assertEqual(
            edge_contract['schema'],
            'limo_v1_ros1_tf_edge_observation/v1')
        self.assertEqual(edge_contract['enforcement_scope'], [
            'V1_RUNTIME_PREFLIGHT',
            'V1_PERCEPTION_ONLY_FIELD_CAPTURE',
        ])
        self.assertFalse(edge_contract['continuous_guard_or_ready_claimed'])
        self.assertEqual(
            edge_contract['observation_granularity'],
            'EACH_TFMESSAGE_EACH_TRANSFORM')
        self.assertEqual(
            edge_contract['authority_source'],
            'connection_header.callerid')
        self.assertEqual(
            edge_contract['topic_source'],
            'CALLBACK_BOUND_EXACT_/tf_OR_/tf_static')
        self.assertEqual(set(edge_contract['required_observation_fields']), {
            'parent_frame', 'child_frame', 'callerid', 'topic',
            'source_stamp', 'receipt_monotonic', 'geometry_fingerprint',
        })
        self.assertEqual(
            edge_contract['protected_child_frames'],
            ['odom', 'base_link', 'laser_link'])
        cardinality = edge_contract['cardinality_rules']
        self.assertEqual(
            cardinality['authorities_per_protected_child'],
            'EXACTLY_ONE_WHEN_REQUIRED_ZERO_WHEN_FORBIDDEN')
        self.assertEqual(
            cardinality['same_edge_across_/tf_and_/tf_static'],
            'FAIL_CLOSED')
        self.assertEqual(
            cardinality[
                'same_authority_conflicting_edge_for_protected_child'],
            'FAIL_CLOSED')
        temporal = edge_contract['temporal_rules']
        self.assertEqual(
            temporal['DYNAMIC_/tf']['source_stamp'],
            'FINITE_STRICTLY_ADVANCING_AND_FRESH')
        self.assertEqual(
            temporal['STATIC_PERIODIC_/tf']['geometry'], 'INVARIANT')
        self.assertEqual(
            temporal['STATIC_LATCHED_/tf_static']['source_stamp'],
            'ZERO_OR_OLD_ALLOWED_NOT_USED_FOR_DYNAMIC_FRESHNESS')
        edge_rules = {
            item['id']: item for item in ownership['tf_edge_rules']}
        self.assertIsNone(
            edge_rules['base_link_to_laser_link']['expected_authority'])
        self.assertFalse(
            edge_rules['base_link_to_laser_link'][
                'candidate_topics_are_runtime_allowlist'])
        self.assertFalse(
            edge_rules['base_link_to_laser_link']['runtime_pass_eligible'])
        self.assertEqual(
            rows['public_cmd_vel']['cardinality'],
            'ZERO_PUBLISHERS_AND_ZERO_SUBSCRIBERS')
        self.assertTrue(all(
            row['duplicate_disposition'] == 'FAIL_CLOSED'
            for row in rows.values()))
        forbidden = {
            item['id'] for item in ownership['forbidden_runtime']}
        self.assertEqual(forbidden, {
            'robot_pose_ekf',
            'slam_during_localization_or_navigation',
            'duplicate_localization_core',
            'duplicate_navigation_core',
            'public_velocity_surface',
            'legacy_vendor_navigation_launch',
            'ros2_native_runtime_owner',
            'bridge_nodes_in_native_mode',
            'native_nodes_in_integrated_mode',
        })
        limits = ownership['verification_limits']
        self.assertTrue(all(value is False for value in limits.values()))
        blocker = self.vendor_include_blocker
        self.assertEqual(
            blocker['schema'], 'limo_v1_ros1_vendor_include_blocker/v1')
        self.assertEqual(blocker['status'], 'BLOCKED_ON_VENDOR_INCLUDE')
        self.assertEqual(blocker['ownership_conclusion'], 'PROVISIONAL')
        self.assertFalse(
            blocker['current_local_evidence']['vendor_raw_source_archived'])
        self.assertFalse(
            blocker['current_local_evidence'][
                'resolved_include_chain_verified'])
        pin = blocker['required_installed_tf_publisher_pin']
        self.assertEqual(pin['status'], 'MISSING')
        self.assertIsNone(pin['resolved_callerid'])
        self.assertIsNone(pin['selected_topic'])
        self.assertEqual(
            pin['candidate_topics_pending_pin'], ['/tf', '/tf_static'])
        self.assertFalse(pin['candidate_topics_are_runtime_allowlist'])
        self.assertFalse(pin['historical_candidate_is_runtime_allowlist'])
        self.assertFalse(pin['runtime_observation_can_create_or_select_pin'])
        rules_artifact = blocker[
            'future_verified_tf_rules_artifact_contract']
        self.assertEqual(
            rules_artifact['schema'],
            'limo_v1_ros1_vendor_tf_rules/v2')
        self.assertIsNone(rules_artifact['default_path'])
        self.assertFalse(rules_artifact['auto_discovery_allowed'])
        self.assertEqual(set(rules_artifact['required_rule_fields']), {
            'parent_frame', 'child_frame', 'authority', 'topic',
            'behavior',
        })
        self.assertFalse(
            rules_artifact['self_reported_provenance_field_allowed'])
        binding = blocker['independent_artifact_binding_contract']
        self.assertEqual(
            binding['source_manifest_schema'],
            'limo_v1_ros1_vendor_source_manifest/v1')
        self.assertEqual(
            binding['publisher_pin_schema'],
            'limo_v1_ros1_vendor_tf_publisher_pin/v1')
        self.assertEqual(
            binding['blocker_status_required_before_any_loader_pass'],
            'VERIFIED')
        self.assertIn(
            'arbitrary well-formed hashes and provenance_verified '
            'self-claims are rejected',
            binding['rules_manifest_requirements'])
        ownership_binding = ownership['vendor_artifact_binding_contract']
        self.assertEqual(
            ownership_binding['status'], 'BLOCKED_ON_VENDOR_INCLUDE')
        self.assertFalse(ownership_binding['runtime_pass_eligible'])
        self.assertEqual(
            ownership_binding['required_absolute_path_inputs'], [
                'vendor_source_manifest_file',
                'vendor_publisher_pin_file',
                'vendor_tf_rules_file',
            ])
        self.assertFalse(
            ownership_binding['hash_format_only_sufficient'])
        self.assertFalse(
            ownership_binding['self_reported_provenance_accepted'])
        self.assertEqual(
            ownership_binding['failure_code'],
            'TF_VENDOR_CONTRACT_UNVERIFIED')
        self.assertTrue(
            ownership_binding['installed_blocker'][
                'exact_bytes_hash_anchored_by_topology_policy'])
        resolution = ownership_binding['required_resolution_evidence']
        self.assertEqual(
            resolution['enforcement'], 'RELEASE_REVIEW_ONLY')
        self.assertFalse(resolution['loader_consumes'])
        self.assertEqual(
            resolution['status'], 'BLOCKED_ON_VENDOR_INCLUDE')
        self.assertEqual(resolution['required_archived_outputs'], [
            'rospack_find_package_roots',
            'roslaunch_--files',
            'roslaunch_--nodes',
            'roslaunch_--dump-params',
        ])
        self.assertFalse(
            resolution['automatically_satisfies_runtime_machine_gate'])
        self.assertFalse(
            resolution['path_or_package_type_text_alone_sufficient'])
        self.assertFalse(
            resolution['runtime_callerid_can_supply_missing_resolution'])
        machine_gate = ownership_binding['runtime_machine_gate']
        self.assertEqual(machine_gate['enforcement'], 'LOADER_FAIL_CLOSED')
        self.assertTrue(
            machine_gate['trusted_installed_blocker_sha256_required'])
        self.assertEqual(machine_gate['required_independent_artifacts'], [
            'vendor_source_manifest_file',
            'vendor_publisher_pin_file',
            'vendor_tf_rules_file',
        ])
        self.assertTrue(machine_gate['strict_supported_xml_subset_required'])
        self.assertEqual(set(machine_gate['unmodelled_constructs_fail_closed']), {
            'include_argument', 'remap', 'namespace_or_condition',
            'substitution', 'launch_prefix',
        })
        self.assertEqual(
            machine_gate['ros_package_root_gate'],
            'ROSPACK_FIND_MUST_MATCH_MANIFEST_ABSOLUTE_PATH')
        self.assertEqual(
            machine_gate['ros_node_executable_gate'],
            'ROSLIB_FIND_NODE_MUST_RETURN_ONE_PATH_MATCHING_PIN')
        self.assertFalse(machine_gate['release_review_dumps_consumed'])
        self.assertTrue(
            rules_artifact[
                'historical_camera_imu_laser_edges_are_candidates_only'])
        self.assertEqual(
            rules_artifact['empty_missing_or_unverified_disposition'],
            'FAIL_CLOSED')
        self.assertEqual(
            blocker['historical_evidence']['limo_start_launch']['sha256'],
            'acd80d07a8169ef15d805a365d1ae72615ced51db32ccf7f5ec94719fede0682')
        self.assertFalse(blocker['decision']['ownership_closed'])
        self.assertFalse(blocker['decision']['field_execution_ready'])
        self.assertFalse(
            blocker['decision']['runtime_tf_observation_can_select_transport'])
        self.assertFalse(
            blocker['decision']['tf_edge_runtime_pass_eligible'])
        self.assertFalse(
            blocker['decision']['continuous_guard_or_ready_tf_edge_claimed'])
        for statement in (
                'default and authoritative field runtime is ROS1 Noetic',
                'Gmapping is permitted only in the explicit mapping stage',
                'zero publishers and zero subscribers',
                '`/amcl_*`', '`/map_server_*`', '`/move_base_*`',
                '`/robot_pose_ekf`', '`limo_navigation_diff.launch`',
                '`PROVISIONAL_BLOCKED / BLOCKED_ON_VENDOR_INCLUDE`',
                'Static wrapper remaps cannot substitute',
                '`tf2_msgs/TFMessage` one transform at a time',
                'one edge observed across both `/tf` and `/tf_static`',
                'not claimed as a continuous guard',
                'TF lookup proves only'):
            self.assertIn(statement, self.ownership_document)
        self._assert_field_runbook_cli_contract()

    def test_integrated_software_closures_are_source_backed_but_field_blocked(self):
        integrated = self.template['deployment_modes']['integrated']
        self.assertEqual(integrated['design_audit_status'], 'PASS')
        self.assertEqual(integrated['execution_status'], 'BLOCKED')
        self.assertEqual(integrated['block_reasons'], [
            'field_authorization_not_admitted',
            'real_machine_preflight_not_run',
        ])
        self.assertEqual(set(integrated['resolved_software_blockers']), {
            'ROS1_TOPOLOGY_VERIFIER_NODE_NAME_COLLISION',
            'INSTALLED_RUNNER_WORKSPACE_SCRIPT_PATH_MISSING'})

        zero_stage = (
            WORKSPACE_ROOT / 'scripts'
            / 'run_ros1_base_bridge_zero_stage.sh').read_text(
                encoding='utf-8')
        runner = (
            BRIDGE_ROOT / 'scripts'
            / 'run_v2_bridged_navigation.py').read_text(encoding='utf-8')
        verifier = (
            BRIDGE_ROOT / 'scripts'
            / 'verify_ros1_base_bridge_topology.py').read_text(
                encoding='utf-8')
        setup = (
            WORKSPACE_ROOT / 'src' / 'limo_cleanup_base' / 'setup.py'
        ).read_text(encoding='utf-8')

        self.assertEqual(
            zero_stage.count(
                '__name:=/verify_ros1_base_zero_stage_topology'), 2)
        self.assertEqual(
            zero_stage.count(
                '_ready_topic:=/cleanup/base/zero_stage_topology_ready'), 2)
        self.assertIn('_continuous:=true', zero_stage)
        self.assertGreaterEqual(
            runner.count('verify_ros1_base_bridge_topology.py'), 2)
        self.assertIn(
            "rospy.init_node('verify_ros1_base_bridge_topology')",
            verifier)
        self.assertIn(
            "'ros2', 'run', 'limo_cleanup_base'", runner)
        self.assertIn("'zero_stage_handoff_verifier'", runner)
        self.assertNotIn('_workspace_script', runner)
        self.assertIn('zero_stage_handoff_verifier = ', setup)
        self.assertIn(
            'Integrated software topology and install-layout blockers are '
            'closed', self.document)
        self.assertIn(
            'software-ready does not make integrated field execution ready',
            self.document)

    def test_authorization_classes_remain_independent_and_blocked(self):
        authorization = self.template['authorization']
        classes = [
            'hardware_read_only',
            'zero_motion_localization',
            'real_motion',
        ]
        self.assertEqual(authorization['required_classes'], classes)
        self.assertEqual(list(authorization['classes']), classes)
        self.assertFalse(
            authorization['dedicated_field_orchestrator_present'])
        self.assertFalse(authorization['execution_ready'])
        for item in authorization['classes'].values():
            self.assertEqual(item['status'], 'NOT_RUN')
            self.assertEqual(item['decision'], 'BLOCKED')
            self.assertIsNone(item['one_use'])
            self.assertIsNone(item['consumed'])
            self.assertIsNone(item['revoked'])
        self.assertIn(
            'a missing value, stale evidence, owner mismatch, expired or',
            self.document)
        self.assertIn('returns to\nBLOCKED', self.document)

    def test_diagnostics_do_not_overclaim_subscriber_capture(self):
        limitations = self.template['diagnostics'][
            'limitations_acknowledged']
        self.assertTrue(all(value is False for value in limitations.values()))
        for text in (
                'It does\nnot prove process ownership',
                'individual no-motion service\nlatency',
                'full scan ranges',
                'obstacle response',
                'physical position'):
            self.assertIn(text, self.document)
        self.assertEqual(
            self.template['preflight']['unknown_process_disposition'],
            'RECORD_AND_BLOCK')
        self.assertFalse(
            self.template['preflight']['unknown_processes_terminated'])
        for source in (
                self.ownership_document,
                self.field_runbook,
                self.perception_only_document,
                self.perception_only_result):
            self.assertIn('BLOCKED_ON_VENDOR_INCLUDE', source)
        self.assertIn(
            'A tf2 lookup proves connectivity only', self.field_runbook)
        self.assertIn(
            'The edge-level authority/topic proof above is a bounded '
            'preflight/field\nsnapshot, not a continuous guard guarantee',
            self.field_runbook)
        self.assertIn(
            'does not prove continuous per-edge TF authority/topic/cardinality',
            self.field_runbook)
        self.assertIn(
            'every transform in each `TFMessage`',
            self.perception_only_document)
        self.assertIn(
            'connection-header `callerid`',
            self.perception_only_document)
        self.assertIn(
            'no edge appears across both `/tf` and `/tf_static`',
            self.perception_only_document)
        self.assertIn(
            'not a\ncontinuous guard or localization-READY monitor',
            self.perception_only_document)
        self.assertIn(
            'Continuous guard/READY TF-edge proof claimed: `false`',
            self.perception_only_result)
        self.assertIn(
            'tf2 lookup succeeds', self.perception_only_result)
        for argument in (
                '--vendor-tf-rules-file',
                '--vendor-source-manifest-file',
                '--vendor-publisher-pin-file'):
            self.assertIn(argument, self.perception_only_document)
        for argument in (
                'vendor_tf_rules_file:=',
                'vendor_source_manifest_file:=',
                'vendor_publisher_pin_file:='):
            self.assertEqual(self.field_runbook.count(argument), 2)
        for source in (
                self.field_runbook,
                self.perception_only_document,
                self.ownership_document):
            self.assertIn('provenance_verified=true', source)
            self.assertIn('fake hash', source)
            self.assertIn('TF_VENDOR_CONTRACT_UNVERIFIED', source)
            self.assertIn('rospack find', source)
            self.assertIn('roslaunch --nodes', source)
            self.assertIn('release-review-only', source)
            self.assertIn('does not', source)
            self.assertIn('unique', source)
            self.assertIn('launch-prefix', source)
        for field in (
                'Installed blocker path, SHA-256, schema, and status',
                'Vendor recursive source manifest path, SHA-256',
                'Installed static-TF publisher pin path, SHA-256',
                'TF rules manifest path, SHA-256',
                'Release-review-only `rospack find` evidence paths and '
                'SHA-256',
                'Release-review approval evidence ID and resolved-node '
                'disposition',
                'Runtime machine-gate `rospack find` and unique `find_node` '
                'verdict',
                'Release-review resolution evidence',
                'Runtime package-root/unique-executable gate',
                'Byte-and-semantic binding verdict',
                'Artifact binding verdict'):
            self.assertIn(field, self.perception_only_result)

    def _assert_field_runbook_cli_contract(self):
        source = self.field_runbook
        self.assertEqual(
            _field_runbook_ros1_cli_contract_errors(source), [])

        bounds = _markdown_section_bounds(
            source, FIELD_RUNBOOK_BRIDGE_HEADING)
        self.assertIsNotNone(bounds)
        bridge_start, bridge_end = bounds
        bridge_section = source[bridge_start:bridge_end]

        def add_to_native_command_block(command):
            marker = 'rosnode list\n'
            self.assertEqual(source.count(marker), 1)
            return source.replace(marker, marker + command + '\n', 1)

        def add_before_bridge(fragment):
            marker = FIELD_RUNBOOK_BRIDGE_HEADING
            self.assertEqual(source.count(marker), 1)
            return source.replace(marker, fragment + '\n\n' + marker, 1)

        first_allowlisted = FIELD_RUNBOOK_BRIDGE_ALLOWLIST[0]
        moved_allowlist = source.replace(
            '- `{}`\n'.format(first_allowlisted), '', 1)
        moved_allowlist = moved_allowlist.replace(
            'Before every native/current ROS1 stage:\n',
            'Before every native/current ROS1 stage:\n\n'
            '`{}`\n'.format(first_allowlisted),
            1)

        mutations = {
            'missing_bridge_section': (
                source[:bridge_start] + source[bridge_end:],
                'bridge_section_missing_or_duplicated'),
            'allowlisted_wrapper_moved_to_native': (
                moved_allowlist,
                'bridge_allowlist_reference_outside_section:'
                + first_allowlisted),
            'extra_bridge_wrapper': (
                source.replace(
                    bridge_section,
                    bridge_section
                    + '\n- `scripts/unreviewed_ros2_bridge.sh`\n',
                    1),
                'bridge_allowlist_changed'),
            'native_direct_global_graph': (
                add_to_native_command_block('ros2 node list'),
                'forbidden_command_surface:ros2_cli'),
            'native_shell_wrapper': (
                add_to_native_command_block(
                    "bash -lc 'ros2 topic list'"),
                'forbidden_command_surface:ros2_cli'),
            'native_line_continuation': (
                add_to_native_command_block('ros2 \\\n  service list'),
                'forbidden_command_surface:ros2_cli'),
            'native_console_prompt': (
                add_to_native_command_block('$ ros2 action list'),
                'forbidden_command_surface:ros2_cli'),
            'native_foxy_source': (
                add_to_native_command_block(
                    'source /opt/ros/foxy/setup.bash'),
                'forbidden_command_surface:foxy_or_humble_source'),
            'native_humble_source': (
                add_to_native_command_block(
                    '. /opt/ros/humble/setup.bash'),
                'forbidden_command_surface:foxy_or_humble_source'),
            'native_colcon': (
                add_to_native_command_block('colcon build'),
                'forbidden_command_surface:colcon'),
        }
        for name, (mutated, expected_error) in mutations.items():
            with self.subTest(name=name):
                errors = _field_runbook_ros1_cli_contract_errors(mutated)
                self.assertIn(expected_error, errors)

        indented_surface_cases = (
            '    ros2 node list',
            '\tros2 node list',
        )
        for surface in indented_surface_cases:
            with self.subTest(
                    name='native_commonmark_indented_block',
                    indentation=repr(surface[:4])):
                self.assertIn(
                    'ros2 node list', _command_surfaces(surface))
                errors = _field_runbook_ros1_cli_contract_errors(
                    add_before_bridge(surface))
                self.assertIn(
                    'forbidden_command_surface:ros2_cli', errors)

        exact_bypass_mutations = {
            'native_tilde_fence': (
                add_before_bridge('~~~bash\nros2 node list\n~~~'),
                'forbidden_command_surface:ros2_cli'),
            'native_shell_concatenated_ros2': (
                add_to_native_command_block("ro''s2 node list"),
                'forbidden_command_surface:ros2_cli'),
            'native_dynamic_command_position': (
                add_to_native_command_block('${ROS_COMMAND} node list'),
                'forbidden_native_shell_construct:'
                'dynamic_command_position'),
        }
        for name, (mutated, expected_error) in exact_bypass_mutations.items():
            with self.subTest(name=name):
                errors = _field_runbook_ros1_cli_contract_errors(mutated)
                self.assertIn(expected_error, errors)

        dynamic_construct_mutations = {
            'native_command_substitution_dollar': (
                'echo $(rosnode list)', 'command_substitution'),
            'native_command_substitution_backtick': (
                'echo `rosnode list`', 'command_substitution'),
            'native_eval': ('eval rosnode list', 'eval_or_exec'),
            'native_exec': ('exec rosnode list', 'eval_or_exec'),
            'native_bash_c': (
                "bash -c 'rosnode list'", 'shell_c_wrapper'),
        }
        for name, (command, kind) in dynamic_construct_mutations.items():
            with self.subTest(name=name):
                errors = _field_runbook_ros1_cli_contract_errors(
                    add_to_native_command_block(command))
                self.assertIn(
                    'forbidden_native_shell_construct:' + kind, errors)

    def test_rollback_order_retains_safety_if_driver_survives(self):
        rollback = self.template['rollback']
        self.assertEqual(rollback['ordered_states'], [
            'STOP_INGRESS',
            'VERIFY_ZERO',
            'STOP_NAV',
            'STOP_DRIVER',
            'VERIFY_UART',
            'STOP_SAFETY',
        ])
        self.assertTrue(
            rollback['retain_safety_chain_if_driver_survives'])
        self.assertFalse(rollback['stop_safety_chain_permitted'])
        self.assertFalse(rollback['unknown_processes_terminated'])
        self.assertEqual(
            rollback['unknown_process_disposition'], 'RECORD_AND_BLOCK')
        self.assertIn(
            'never guess ownership and never terminate an unknown process',
            self.document)
        self.assertIn(
            'Software zero or STOP never substitutes for physical energy',
            self.document)
        self.assertIn(
            'its runner does not\n  own the external zero-stage safety chain',
            self.document)

    def test_field_results_and_user_observation_overlay_are_independent(self):
        field = self.template['field_acceptance']
        expected = {
            'zero_motion_absolute_localization_error',
            'repeat_localization_error',
            'navigation_control_endpoint_error',
            'amcl_estimation_error',
            'physical_total_endpoint_error',
            'cancel_and_driver_timeout',
            'static_obstacle_avoidance',
            'dynamic_obstacle_avoidance',
            'scan_odom_tf_loss',
        }
        self.assertEqual(set(field), expected)
        for result in field.values():
            self.assertEqual(result['status'], 'NOT_RUN')
            self.assertTrue(result['template_only'])
        for statement in (
                'covariance READY is a convergence and chain-health gate',
                'controller endpoint error is requested pose minus final '
                'AMCL estimate',
                'AMCL estimation error is physical truth minus final AMCL '
                'estimate',
                'physical total endpoint error is requested pose minus '
                'physical truth',
                'endpoint success does not prove obstacle avoidance',
                'offline software PASS does not prove any field item'):
            self.assertIn(statement, self.document)

        observation = self.observation
        self.assertEqual(
            observation['schema'],
            'limo_v1_user_observation_increment/v1')
        self.assertEqual(
            observation['record_status'], 'USER_OBSERVED_PARTIAL')
        self.assertFalse(observation['template_only'])
        self.assertFalse(
            observation['formal_real_machine_evidence_archived'])
        self.assertFalse(observation['motion_authorized_by_this_record'])
        self.assertFalse(
            observation['record_created_utc_is_observation_time'])
        self.assertIsNone(observation['observation_occurred_at_utc'])
        self.assertIsNone(observation['session_id'])
        self.assertEqual(observation['artifact_refs'], [])
        self.assertTrue(all(
            value is None
            for value in observation['measured_values'].values()))
        self.assertEqual(observation['classification'], {
            'observation_status': 'USER_OBSERVED',
            'gate_progress': 'PARTIAL',
            'formal_acceptance_result': 'NOT_ASSESSED',
            'formal_readiness_status': 'NOT_RUN',
            'evidence_archive_status': 'UNSEALED',
        })
        self.assertEqual(set(observation['observations']), {
            'posearray_converged',
            'motion_convergence_maintained',
            'point_to_point_navigation_functional',
            'endpoint_deviation_centimeter_level',
        })
        for item in observation['observations'].values():
            self.assertTrue(item['reported'])
            self.assertEqual(item['observation_status'], 'USER_OBSERVED')
            self.assertEqual(item['gate_progress'], 'PARTIAL')
            self.assertTrue(item['closes'])
            self.assertTrue(item['does_not_close'])
        self.assertEqual(
            observation['observations']['posearray_converged'][
                'initialpose_path'], 'UNRESOLVED')
        navigation = observation['observations'][
            'point_to_point_navigation_functional']
        self.assertEqual(
            navigation['ingress'], 'UNRESOLVED_USER_TERM_NAV_GOAL')
        self.assertIsNone(navigation['action_terminal_state'])
        endpoint = observation['observations'][
            'endpoint_deviation_centimeter_level']
        self.assertIsNone(endpoint['endpoint_deviation_m'])
        self.assertEqual(endpoint['endpoint_error_class'], 'UNRESOLVED')

        thresholds = observation['frozen_thresholds']
        self.assertEqual(
            thresholds['amcl_estimation_position_error_max_m'], 0.10)
        self.assertEqual(
            thresholds[
                'navigation_control_endpoint_position_error_max_m'], 0.10)
        self.assertEqual(
            thresholds['physical_total_endpoint_position_error_max_m'],
            0.15)
        self.assertEqual(
            thresholds['repeatability_x_stddev_max_m'], 0.05)
        self.assertEqual(
            thresholds['repeatability_y_stddev_max_m'], 0.05)
        self.assertEqual(
            thresholds['repeatability_circular_yaw_stddev_max_deg'], 5.0)
        self.assertIsNone(thresholds['endpoint_yaw_pass_threshold'])
        self.assertFalse(
            thresholds['covariance_ready_proves_absolute_accuracy'])

        open_gates = observation['formal_gates_still_open']
        self.assertEqual(set(open_gates), {
            'amcl_three_cold_start_convergence',
            'repeat_localization_error',
            'point_to_point_navigation_functional',
            'endpoint_error_triad',
            'cancel_and_driver_timeout',
            'static_obstacle_avoidance',
            'dynamic_obstacle_avoidance',
            'scan_odom_tf_loss',
        })
        self.assertEqual(
            open_gates['amcl_three_cold_start_convergence'][
                'post_ready_samples_per_trial_min'], 30)
        self.assertEqual(
            open_gates['point_to_point_navigation_functional'][
                'required_passes'], 5)
        decision = observation['formal_decision']
        self.assertTrue(all(value is False for value in decision.values()))
        self.assertTrue(all(
            value is False for value in observation['safety'].values()))

        expected_gate_ids = {
            'amcl_three_cold_start_convergence',
            'zero_motion_absolute_localization_error',
            'repeat_localization_error',
            'motion_convergence_during_navigation',
            'point_to_point_navigation_functional',
            'navigation_control_endpoint_error',
            'amcl_estimation_error',
            'physical_total_endpoint_error',
            'cancel_behavior',
            'independent_driver_timeout',
            'static_obstacle_avoidance',
            'dynamic_obstacle_avoidance',
            'scan_loss_stop',
            'odom_loss_stop',
            'tf_loss_stop',
        }
        self.assertEqual(
            {row['gate_id'] for row in self.capture_rows},
            expected_gate_ids)
        self.assertEqual(
            set(self.capture_rows[0]), {
                'gate_id', 'current_observation_status', 'gate_progress',
                'formal_readiness_status', 'required_trials',
                'formal_acceptance_result', 'evidence_archive_status',
                'required_samples_per_trial', 'minimum_raw_artifacts',
                'minimum_fields', 'threshold',
                'offline_evaluable_when_complete',
                'minimum_future_authorization',
            })
        self.assertTrue(all(
            row['formal_readiness_status'] == 'NOT_RUN'
            for row in self.capture_rows))
        self.assertTrue(all(
            row['formal_acceptance_result'] == 'NOT_ASSESSED'
            for row in self.capture_rows))
        self.assertTrue(all(
            row['evidence_archive_status'] == 'UNSEALED'
            for row in self.capture_rows))
        self.assertTrue(all(
            row['offline_evaluable_when_complete'] == 'yes'
            for row in self.capture_rows))
        observed_gate_ids = {
            'amcl_three_cold_start_convergence',
            'motion_convergence_during_navigation',
            'point_to_point_navigation_functional',
            'navigation_control_endpoint_error',
            'amcl_estimation_error',
            'physical_total_endpoint_error',
        }
        for row in self.capture_rows:
            if row['gate_id'] in observed_gate_ids:
                self.assertEqual(
                    row['current_observation_status'], 'USER_OBSERVED')
                self.assertEqual(row['gate_progress'], 'PARTIAL')
            else:
                self.assertEqual(
                    row['current_observation_status'],
                    'NO_USER_OBSERVATION_RECORDED')
                self.assertEqual(row['gate_progress'], 'NONE')

        expected_hash = hashlib.sha256(
            OBSERVATION_RECORD.read_bytes()).hexdigest()
        hash_lines = OBSERVATION_HASHES.read_text(
            encoding='ascii').splitlines()
        self.assertEqual(
            hash_lines,
            ['{}  user_observed_partial.json'.format(expected_hash)])
        for statement in (
                '`USER_OBSERVED`', '`PARTIAL`', '`NOT_ASSESSED`',
                '`UNSEALED`', 'PoseArray', 'point-to-point',
                '3/3', '30', '5/5', '0.10 m', '0.15 m',
                'cancel', 'driver-timeout', 'scan-loss', 'odom-loss',
                'TF-loss'):
            self.assertIn(statement, self.observation_audit)
        self.assertIn(
            'formal acceptance-gate state', self.document)
        self.assertIn(
            'reported centimeter-level residual remains\nnumeric null',
            self.document)

    def test_template_has_no_executable_or_motion_transport_surface(self):
        lowered = self.template_source.lower()
        for forbidden in (
                'roslaunch', 'rosrun', 'rosservice', 'simpleactionclient',
                'publisher(', 'serviceproxy(', '/cmd_vel', '/v1/navigation/',
                'systemctl', 'crontab', 'rc.local', 'killall', 'pkill'):
            self.assertNotIn(forbidden, lowered)
        document_lowered = self.document.lower()
        for forbidden in (
                'systemctl enable', '@reboot', 'respawn="true"',
                'killall ', 'pkill '):
            self.assertNotIn(forbidden, document_lowered)
        self.assertIn(
            'is not an\nexecution entry point', self.document)


if __name__ == '__main__':
    unittest.main()

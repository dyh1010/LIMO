import ast
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock
import xml.etree.ElementTree as ET


PACKAGE_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / 'src'))
sys.path.insert(0, str(PACKAGE_ROOT / 'scripts'))

from audit_v1_overlay import (  # noqa: E402
    audit,
    validate_navigation_base_scope,
)
import v1_perception_only_field as FIELD  # noqa: E402
import v1_runtime_preflight as PREFLIGHT  # noqa: E402
import limo_v1_navigation.topology_policy as TOPOLOGY  # noqa: E402
from limo_v1_navigation.topology_policy import (  # noqa: E402
    TfEdgeValidationError,
)


BRIDGE_ROOT = PACKAGE_ROOT.parent / 'limo_cleanup_ros1_base'
SAFE_VENDOR_WRAPPER_XML = (
    "<launch>\n"
    "  <arg name=\"enable_hardware\" default=\"false\" />\n"
    "  <arg name=\"hardware_authorization_id\" "
    "default=\"NOT_AUTHORIZED\" />\n"
    "  <arg name=\"odom_tf_owner\" />\n"
    "  <arg name=\"port_name\" default=\"ttyTHS0\" />\n"
    "  <arg name=\"use_mcnamu\" default=\"false\" />\n"
    "  <group if=\"$(eval arg('enable_hardware') == 'true' and "
    "arg('hardware_authorization_id') != 'NOT_AUTHORIZED' and "
    "arg('odom_tf_owner') == '/limo_base_node')\">\n"
    "    <remap from=\"/cmd_vel\" to=\"/v1/driver_cmd_vel\" />\n"
    "    <include file=\"$(find limo_bringup)/launch/limo_start.launch\">\n"
    "      <arg name=\"port_name\" value=\"$(arg port_name)\" />\n"
    "      <arg name=\"use_mcnamu\" value=\"$(arg use_mcnamu)\" />\n"
    "      <arg name=\"pub_odom_tf\" value=\"true\" />\n"
    "    </include>\n"
    "  </group>\n"
    "</launch>\n")

AUDITED_VENDOR_ROOT_ARGS_XML = (
    '<arg name="port_name" default="ttyTHS0" />'
    '<arg name="use_mcnamu" default="false" />'
    '<arg name="pub_odom_tf" default="false" />')
AUDITED_VENDOR_INCLUDE_ARGS_XML = (
    '<arg name="port_name" default="$(arg port_name)" />'
    '<arg name="use_mcnamu" default="$(arg use_mcnamu)" />'
    '<arg name="pub_odom_tf" default="$(arg pub_odom_tf)" />')


def _audited_vendor_root_xml(
        include_args=AUDITED_VENDOR_INCLUDE_ARGS_XML,
        include_extra_attributes=''):
    return (
        '<launch>'
        + AUDITED_VENDOR_ROOT_ARGS_XML
        + '<include file="$(find limo_base)/launch/limo_base.launch"'
        + include_extra_attributes + '>'
        + include_args + '</include>'
        + '<include file="$(find ydlidar_ros_driver)/launch/Tmini.launch" />'
        + '<node pkg="tf" type="static_transform_publisher" '
        'name="base_link_to_laser_link" '
        'args="0.105 0 0.08 0 0 0 base_link laser_link 100" />'
        '</launch>\n')


def _write_json(path, payload):
    path.write_text(
        json.dumps(payload, sort_keys=True, separators=(',', ':')) + '\n',
        encoding='utf-8')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _file_sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@contextmanager
def _trusted_vendor_bundle(bundle):
    blocker_path = bundle['blocker_path']

    def resolve_package(package):
        value = bundle['package_roots'].get(package)
        if value is None:
            raise TfEdgeValidationError(
                'TF_VENDOR_CONTRACT_UNVERIFIED',
                'mock ROS package is missing')
        return value

    def resolve_node(package, node_type):
        return bundle['node_executables'].get((package, node_type), ())

    with mock.patch.object(
            TOPOLOGY, '_TRUSTED_VENDOR_BLOCKER_SHA256',
            _file_sha(blocker_path)), mock.patch.object(
                TOPOLOGY, '_TRUSTED_VENDOR_WRAPPER_SHA256',
                bundle['trusted_wrapper_sha256']), mock.patch.object(
                PREFLIGHT, 'VENDOR_BLOCKER_FILE', blocker_path), \
            mock.patch.object(FIELD, 'VENDOR_BLOCKER_FILE', blocker_path), \
            mock.patch.object(
                TOPOLOGY, '_resolve_ros_package_root',
                side_effect=resolve_package), mock.patch.object(
                    TOPOLOGY, '_resolve_ros_node_executables',
                    side_effect=resolve_node):
        yield


def _vendor_bundle(root):
    root.mkdir(parents=True, exist_ok=True)
    packages = root / 'packages'
    package_roots = {
        'limo_v1_navigation': packages / 'limo_v1_navigation',
        'limo_bringup': packages / 'limo_bringup',
        'limo_base': packages / 'limo_base',
        'ydlidar_ros_driver': packages / 'ydlidar_ros_driver',
    }
    raw_root = package_roots['limo_bringup'] / 'launch' / 'limo_start.launch'
    raw_base = package_roots['limo_base'] / 'launch' / 'limo_base.launch'
    raw_lidar = (
        package_roots['ydlidar_ros_driver'] / 'launch' / 'Tmini.launch')
    wrapper = (
        package_roots['limo_v1_navigation'] / 'launch' /
        'v1_base_sensors.launch')
    for raw_path in (wrapper, raw_root, raw_base, raw_lidar):
        raw_path.parent.mkdir(parents=True, exist_ok=True)
    wrapper.write_text(SAFE_VENDOR_WRAPPER_XML, encoding='utf-8')
    raw_root.write_text(
        '<launch>'
        '<include file="$(find limo_base)/launch/limo_base.launch" />'
        '<include file="$(find ydlidar_ros_driver)/launch/Tmini.launch" />'
        '<node pkg="tf" type="static_transform_publisher" '
        'name="base_link_to_laser_link" '
        'args="0.105 0 0.08 0 0 0 base_link laser_link 100" />'
        '</launch>\n', encoding='utf-8')
    raw_base.write_text('<launch></launch>\n', encoding='utf-8')
    raw_lidar.write_text('<launch></launch>\n', encoding='utf-8')
    executable = packages / 'tf' / 'lib' / 'tf' / (
        'static_transform_publisher')
    executable.parent.mkdir(parents=True, exist_ok=True)
    executable.write_bytes(b'synthetic-test-executable\n')

    source_path = root / 'source_manifest.json'
    source = {
        'schema': 'limo_v1_ros1_vendor_source_manifest/v1',
        'status': 'VERIFIED',
        'closure_complete': True,
        'root_artifact_id': 'limo_start',
        'artifacts': [
            {
                'id': 'limo_start',
                'logical_path': 'limo_bringup/launch/limo_start.launch',
                'absolute_path': str(raw_root),
                'sha256': _file_sha(raw_root),
                'kind': 'roslaunch',
            },
            {
                'id': 'limo_base',
                'logical_path': 'limo_base/launch/limo_base.launch',
                'absolute_path': str(raw_base),
                'sha256': _file_sha(raw_base),
                'kind': 'roslaunch',
            },
            {
                'id': 'tmini',
                'logical_path': 'ydlidar_ros_driver/launch/Tmini.launch',
                'absolute_path': str(raw_lidar),
                'sha256': _file_sha(raw_lidar),
                'kind': 'roslaunch',
            },
        ],
        'include_edges': [
            {
                'parent_artifact_id': 'limo_start',
                'include_expression': (
                    '$(find limo_base)/launch/limo_base.launch'),
                'child_artifact_id': 'limo_base',
            },
            {
                'parent_artifact_id': 'limo_start',
                'include_expression': (
                    '$(find ydlidar_ros_driver)/launch/Tmini.launch'),
                'child_artifact_id': 'tmini',
            },
        ],
    }
    source_sha = _write_json(source_path, source)

    pin_path = root / 'publisher_pin.json'
    pin = {
        'schema': 'limo_v1_ros1_vendor_tf_publisher_pin/v1',
        'status': 'VERIFIED',
        'source_manifest_sha256': source_sha,
        'executable': {
            'absolute_path': str(executable),
            'sha256': _file_sha(executable),
            'package': 'tf',
            'node_type': 'static_transform_publisher',
        },
        'rules': [{
            'parent_frame': 'base_link',
            'child_frame': 'laser_link',
            'callerid': '/base_link_to_laser_link',
            'topic': '/tf',
            'behavior': 'STATIC_PERIODIC',
        }],
    }
    pin_sha = _write_json(pin_path, pin)

    rules_path = root / 'rules.json'
    rules = {
        'schema': 'limo_v1_ros1_vendor_tf_rules/v2',
        'status': 'VERIFIED',
        'source_manifest_sha256': source_sha,
        'publisher_pin_sha256': pin_sha,
        'rules': [{
            'parent_frame': 'base_link',
            'child_frame': 'laser_link',
            'authority': '/base_link_to_laser_link',
            'topic': '/tf',
            'behavior': 'STATIC_PERIODIC',
        }],
    }
    rules_sha = _write_json(rules_path, rules)

    blocker_path = root / 'blocker.json'
    blocker = {
        'schema': 'limo_v1_ros1_vendor_include_blocker/v1',
        'status': 'VERIFIED',
        'ownership_conclusion': 'VERIFIED',
        'current_local_evidence': {
            'vendor_raw_source_archived': True,
            'current_hash_verified': True,
            'resolved_include_chain_verified': True,
            'installed_vendor_manifest_present': True,
        },
        'required_installed_tf_publisher_pin': {
            'status': 'VERIFIED',
            'edge': {
                'parent_frame': 'base_link',
                'child_frame': 'laser_link',
                'temporal_semantics': 'STATIC',
            },
            'resolved_callerid': '/base_link_to_laser_link',
            'package': 'tf',
            'node_type': 'static_transform_publisher',
            'executable_absolute_path': str(executable.resolve()),
            'selected_topic': '/tf',
            'selected_transport_semantics': 'STATIC_PERIODIC',
            'executable_sha256': _file_sha(executable),
            'resolved_arguments': (
                '0.105 0 0.08 0 0 0 base_link laser_link 100'),
        },
        'verified_evidence': {
            'source_manifest_sha256': source_sha,
            'publisher_pin_sha256': pin_sha,
            'rules_manifest_sha256': rules_sha,
        },
        'decision': {
            'ownership_closed': True,
            'tf_edge_runtime_pass_eligible': True,
        },
    }
    _write_json(blocker_path, blocker)
    return {
        'raw_root': raw_root,
        'raw_base': raw_base,
        'raw_lidar': raw_lidar,
        'executable': executable,
        'source_path': source_path,
        'pin_path': pin_path,
        'rules_path': rules_path,
        'blocker_path': blocker_path,
        'wrapper': wrapper,
        'trusted_wrapper_sha256': _file_sha(wrapper),
        'package_roots': {
            package: path.resolve()
            for package, path in package_roots.items()
        },
        'node_executables': {
            ('tf', 'static_transform_publisher'): (executable.resolve(),),
        },
    }


def _rebind_vendor_bundle(bundle):
    source_path = bundle['source_path']
    pin_path = bundle['pin_path']
    rules_path = bundle['rules_path']
    blocker_path = bundle['blocker_path']
    source_sha = _file_sha(source_path)
    pin = json.loads(pin_path.read_text(encoding='utf-8'))
    pin['source_manifest_sha256'] = source_sha
    pin_sha = _write_json(pin_path, pin)
    rules = json.loads(rules_path.read_text(encoding='utf-8'))
    rules['source_manifest_sha256'] = source_sha
    rules['publisher_pin_sha256'] = pin_sha
    rules_sha = _write_json(rules_path, rules)
    blocker = json.loads(blocker_path.read_text(encoding='utf-8'))
    blocker['verified_evidence'] = {
        'source_manifest_sha256': source_sha,
        'publisher_pin_sha256': pin_sha,
        'rules_manifest_sha256': rules_sha,
    }
    _write_json(blocker_path, blocker)


def _rebind_blocker_only(bundle):
    blocker_path = bundle['blocker_path']
    blocker = json.loads(blocker_path.read_text(encoding='utf-8'))
    blocker['verified_evidence'] = {
        'source_manifest_sha256': _file_sha(bundle['source_path']),
        'publisher_pin_sha256': _file_sha(bundle['pin_path']),
        'rules_manifest_sha256': _file_sha(bundle['rules_path']),
    }
    _write_json(blocker_path, blocker)


def _rewrite_raw_and_rebind(bundle, key, text):
    raw_path = bundle[key]
    raw_path.write_text(text, encoding='utf-8')
    source = json.loads(
        bundle['source_path'].read_text(encoding='utf-8'))
    for artifact in source['artifacts']:
        if Path(artifact['absolute_path']) == raw_path:
            artifact['sha256'] = _file_sha(raw_path)
            break
    else:
        raise AssertionError('raw artifact is absent from source manifest')
    _write_json(bundle['source_path'], source)
    _rebind_vendor_bundle(bundle)


def _move_static_tf_to_included_base(bundle, root_text):
    _rewrite_raw_and_rebind(bundle, 'raw_root', root_text)
    _rewrite_raw_and_rebind(
        bundle, 'raw_base',
        '<launch><node pkg="tf" type="static_transform_publisher" '
        'name="base_link_to_laser_link" '
        'args="0.105 0 0.08 0 0 0 base_link laser_link 100" />'
        '</launch>\n')


def _rewrite_wrapper(bundle, old, new, reanchor):
    wrapper = bundle['wrapper']
    source = wrapper.read_text(encoding='utf-8')
    if old not in source:
        raise AssertionError('wrapper mutation target is absent')
    wrapper.write_text(source.replace(old, new, 1), encoding='utf-8')
    if reanchor:
        bundle['trusted_wrapper_sha256'] = _file_sha(wrapper)


class LaunchContractTest(unittest.TestCase):

    def test_static_expansion_audit_passes(self):
        manifest = audit()
        self.assertEqual(manifest['status'], 'V1_OVERLAY_STATIC_PASS')
        self.assertEqual(len(manifest['launch_files']), 6)

    def test_launches_are_inert_and_map_is_mandatory(self):
        for name, enable_arg in (
                ('v1_base_sensors.launch', 'enable_hardware'),
                ('v1_mapping.launch', 'enable_mapping'),
                ('v1_localization.launch', 'enable_localization'),
                ('v1_navigation.launch', 'enable_navigation')):
            root = ET.parse(PACKAGE_ROOT / 'launch' / name).getroot()
            argument = root.find("./arg[@name='{}']".format(enable_arg))
            self.assertEqual(argument.attrib['default'], 'false')
            source = (PACKAGE_ROOT / 'launch' / name).read_text(
                encoding='utf-8')
            self.assertIn(
                "arg('{}') == 'true'".format(enable_arg), source)
        for name in ('v1_localization.launch', 'v1_navigation.launch'):
            root = ET.parse(PACKAGE_ROOT / 'launch' / name).getroot()
            for argument_name in ('map_file', 'active_map_id', 'preflight_token'):
                argument = root.find(
                    "./arg[@name='{}']".format(argument_name))
                self.assertNotIn('default', argument.attrib)
        core = ET.parse(
            PACKAGE_ROOT / 'launch' / 'v1_navigation_core.launch').getroot()
        for argument_name in ('map_file', 'active_map_id', 'preflight_token'):
            self.assertNotIn(
                'default', core.find(
                    "./arg[@name='{}']".format(argument_name)).attrib)

    def test_vendor_navigation_does_not_leak(self):
        production_paths = list((PACKAGE_ROOT / 'launch').glob('*.launch'))
        production_paths += [
            path for path in (PACKAGE_ROOT / 'config').glob('*')
            if path.name not in {
                'v1_software_interface.json',
                'v1_software_interface.schema.json',
            }]
        production_paths += list((PACKAGE_ROOT / 'src').rglob('*.py'))
        production_paths += [
            PACKAGE_ROOT / 'scripts' / 'v1_cmd_guard.py',
            PACKAGE_ROOT / 'scripts' / 'v1_runtime_preflight.py',
            PACKAGE_ROOT / 'scripts' / 'validate_v1_profile.py',
        ]
        source = '\n'.join(
            path.read_text(encoding='utf-8')
            for path in production_paths if path.is_file())
        self.assertNotIn('limo_navigation_diff.launch', source)
        self.assertNotIn('/cleanup/navigation', source)
        software_interface = json.loads((
            PACKAGE_ROOT / 'config' / 'v1_software_interface.json'
        ).read_text(encoding='utf-8'))
        integrated_status = next(
            item for item in software_interface['read_only_interfaces']
            if item['id'] == 'integrated_navigation_status')
        self.assertEqual(
            integrated_status['name'], '/cleanup/navigation/bridge_status')
        integrated_command = next(
            item for item in software_interface['controlled_interfaces']
            if item['id'] == 'integrated_navigation_command')
        self.assertTrue(integrated_command['internal_only'])
        self.assertFalse(integrated_command['public_consumer'])
        launch_source = '\n'.join(
            path.read_text(encoding='utf-8')
            for path in (PACKAGE_ROOT / 'launch').glob('*.launch'))
        self.assertNotIn('maps/map1017.yaml', launch_source)
        self.assertNotIn('maps/map02.yaml', launch_source)
        core_source = (
            PACKAGE_ROOT / 'launch' / 'v1_navigation_core.launch'
        ).read_text(encoding='utf-8')
        self.assertIn("'map1017' not in arg('map_file')", core_source)
        self.assertIn(
            "arg('active_map_id') not in ['map02', 'map1017', "
            "'NOT_AVAILABLE_MAP_NOT_FROZEN']", core_source)
        self.assertNotIn('robot_pose_ekf', launch_source)
        profile = json.loads((
            PACKAGE_ROOT / 'config' / 'v1_navigation_profile.yaml'
        ).read_text(encoding='utf-8'))
        self.assertIn('map1017', profile['map_policy']['rejected_map_ids'])

    def test_navigation_base_is_native_only_and_bridge_free(self):
        sources = {
            path.name: path.read_text(encoding='utf-8')
            for path in (PACKAGE_ROOT / 'launch').glob('*.launch')
        }
        validate_navigation_base_scope(sources)
        navigation = sources['v1_navigation.launch']
        root = ET.fromstring(navigation)
        self.assertIsNone(root.find("./arg[@name='mode']"))
        public = navigation + sources['v1_navigation_core.launch']
        self.assertNotIn('/cleanup/base/cmd_vel_request', public)
        self.assertNotIn('cmd_vel_output_topic', public)
        self.assertIn('from="/cmd_vel" to="/v1/nav_cmd_vel"', public)
        self.assertNotIn('limo_cleanup_ros1_base', '\n'.join(sources.values()))
        package_source = (PACKAGE_ROOT / 'package.xml').read_text(
            encoding='utf-8')
        self.assertNotIn('limo_cleanup_ros1_base', package_source)

    def test_public_launch_cli_rejects_integrated_and_output_overrides(self):
        wrapper = ET.parse(
            PACKAGE_ROOT / 'launch' / 'v1_navigation.launch').getroot()
        core = ET.parse(
            PACKAGE_ROOT / 'launch' / 'v1_navigation_core.launch').getroot()
        wrapper_args = {
            argument.attrib['name'] for argument in wrapper.findall('./arg')}
        core_args = {
            argument.attrib['name'] for argument in core.findall('./arg')}
        self.assertNotIn('mode', wrapper_args)
        self.assertNotIn('cmd_vel_output_topic', wrapper_args)
        self.assertNotIn('cmd_vel_output_topic', core_args)
        for forbidden in ('mode', 'cmd_vel_output_topic'):
            self.assertNotIn(forbidden, wrapper_args)
        for path in (PACKAGE_ROOT / 'launch').glob('*.launch'):
            self.assertNotIn(
                '/cleanup/base/cmd_vel_request',
                path.read_text(encoding='utf-8'),
                msg=str(path),
            )

    def test_invalid_navigation_base_mutations_are_blocked(self):
        sources = {
            path.name: path.read_text(encoding='utf-8')
            for path in (PACKAGE_ROOT / 'launch').glob('*.launch')
        }
        bridge_leak = dict(sources)
        bridge_leak['v1_navigation.launch'] = bridge_leak[
            'v1_navigation.launch'].replace(
                '</launch>',
                '<include file="$(find limo_cleanup_ros1_base)/launch/'
                'navigation_bridge_adapter.launch" /></launch>')
        with self.assertRaises(RuntimeError):
            validate_navigation_base_scope(bridge_leak)

        integrated_arg = dict(sources)
        integrated_arg['v1_navigation.launch'] = integrated_arg[
            'v1_navigation.launch'].replace(
                '<arg name="preflight_token" />',
                '<arg name="mode" default="integrated" />'
                '<arg name="preflight_token" />')
        with self.assertRaises(RuntimeError):
            validate_navigation_base_scope(integrated_arg)

        double_move_base = dict(sources)
        double_move_base['v1_navigation_core.launch'] = double_move_base[
            'v1_navigation_core.launch'].replace(
                '<node pkg="move_base"',
                '<node pkg="move_base" type="move_base" name="move_base" />'
                '<node pkg="move_base"', 1)
        with self.assertRaises(RuntimeError):
            validate_navigation_base_scope(double_move_base)

        integrated_output = dict(sources)
        integrated_output['v1_navigation_core.launch'] = integrated_output[
            'v1_navigation_core.launch'].replace(
                'to="/v1/nav_cmd_vel"',
                'to="/cleanup/base/cmd_vel_request"')
        with self.assertRaises(RuntimeError):
            validate_navigation_base_scope(integrated_output)

        core_guard_leak = dict(sources)
        core_guard_leak['v1_navigation_core.launch'] = core_guard_leak[
            'v1_navigation_core.launch'].replace(
                '</group>',
                '<node pkg="limo_v1_navigation" type="v1_cmd_guard.py" '
                'name="v1_cmd_guard" /></group>')
        with self.assertRaises(RuntimeError):
            validate_navigation_base_scope(core_guard_leak)

    def test_amcl_expected_and_bridge_hard_cap_are_consistent(self):
        profile = json.loads((
            PACKAGE_ROOT / 'config' / 'v1_navigation_profile.yaml'
        ).read_text(encoding='utf-8'))
        amcl_lines = (
            PACKAGE_ROOT / 'config' / 'amcl.yaml'
        ).read_text(encoding='utf-8').splitlines()
        amcl_values = [
            float(line.split(':', 1)[1].strip())
            for line in amcl_lines
            if line.strip().startswith('transform_tolerance:')]
        self.assertEqual(amcl_values, [0.05])

        health_tree = ast.parse((
            BRIDGE_ROOT / 'src' / 'limo_cleanup_ros1_base'
            / 'navigation_health.py').read_text(encoding='utf-8'))
        constants = {
            node.targets[0].id: node.value.value
            for node in health_tree.body
            if isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Constant)}
        bridge_expected = constants['EXPECTED_AMCL_TRANSFORM_TOLERANCE']
        bridge_hard_cap = constants['MAX_TF_FUTURE_TOLERANCE']
        profile_expected = profile['tf_timing'][
            'amcl_transform_tolerance_s']
        profile_hard_cap = profile['tf_timing'][
            'source_future_tolerance_s']
        self.assertEqual(bridge_expected, 0.05)
        self.assertEqual(bridge_hard_cap, 0.10)
        self.assertEqual(profile_expected, bridge_expected)
        self.assertEqual(profile_hard_cap, bridge_hard_cap)
        self.assertEqual(amcl_values[0], bridge_expected)

        amcl_source = '\n'.join(amcl_lines)
        self.assertIn('update_min_d: 0.05', amcl_source)
        self.assertIn('update_min_a: 0.10', amcl_source)

    def test_project_configuration_repairs_vendor_mismatches(self):
        planner = (PACKAGE_ROOT / 'config' / 'planner.yaml').read_text(
            encoding='utf-8')
        local = (PACKAGE_ROOT / 'config' / 'local_costmap.yaml').read_text(
            encoding='utf-8')
        common = (PACKAGE_ROOT / 'config' / 'costmap_common.yaml').read_text(
            encoding='utf-8')
        move_base = (PACKAGE_ROOT / 'config' / 'move_base.yaml').read_text(
            encoding='utf-8')
        self.assertIn('GlobalPlanner:', planner)
        self.assertNotIn('NavfnROS:', planner)
        self.assertIn('max_vel_x: 0.18', planner)
        self.assertIn('acc_lim_x: 0.35', planner)
        self.assertIn('controller_frequency: 5.0', planner)
        self.assertIn('global_frame: odom', local)
        self.assertIn('expected_update_rate: 0.30', common)
        self.assertIn('controller_frequency: 5.0', move_base)

    def test_schema_and_profile_are_json_parseable(self):
        schema = json.loads((
            PACKAGE_ROOT / 'config' / 'v1_profile.schema.json'
        ).read_text(encoding='utf-8'))
        profile = json.loads((
            PACKAGE_ROOT / 'config' / 'v1_navigation_profile.yaml'
        ).read_text(encoding='utf-8'))
        self.assertEqual(schema['properties']['schema_version']['const'], 1)
        self.assertEqual(profile['schema_version'], 1)

    def test_integrated_snapshot_interface_matches_native_core_inputs(self):
        interface = json.loads((
            PACKAGE_ROOT / 'config' / 'v1_navigation_interface.json'
        ).read_text(encoding='utf-8'))
        self.assertEqual(
            interface['schema'], 'limo_v1_navigation_interface/v2')
        self.assertFalse(
            interface['integrated_navigation']['installed_launch_entry'])
        self.assertTrue(
            interface['integrated_navigation']['snapshot_required'])
        self.assertEqual(
            interface['integrated_navigation']['precore_stage'],
            'navigation_precore')
        self.assertIn(
            'enable_goal_gateway',
            interface['public_navigation']['wrapper_args'])
        self.assertIn(
            'allow_goal_forwarding',
            interface['public_navigation']['wrapper_args'])

        core = ET.parse(
            PACKAGE_ROOT / 'launch' / 'v1_navigation_core.launch').getroot()
        loads = []
        for node in core.findall('.//node'):
            node_namespace = '/{}'.format(node.attrib['name'])
            for rosparam in node.findall('./rosparam'):
                filename = Path(rosparam.attrib['file']).name
                namespace = rosparam.attrib.get('ns')
                if namespace:
                    namespace = '{}/{}'.format(node_namespace, namespace)
                else:
                    namespace = node_namespace
                loads.append({'file': filename, 'namespace': namespace})
        self.assertEqual(loads, interface['snapshot_rosparam_load_order'])

        actual_hashes = {}
        for filename in interface['snapshot_config_sha256']:
            payload = (PACKAGE_ROOT / 'config' / filename).read_bytes()
            actual_hashes[filename] = hashlib.sha256(payload).hexdigest()
        self.assertEqual(
            actual_hashes, interface['snapshot_config_sha256'])

    def test_runtime_preflight_never_constructs_a_publisher(self):
        source = (
            PACKAGE_ROOT / 'scripts' / 'v1_runtime_preflight.py'
        ).read_text(encoding='utf-8')
        topology_source = (
            PACKAGE_ROOT / 'src' / 'limo_v1_navigation' /
            'topology_policy.py').read_text(encoding='utf-8')
        self.assertNotIn('rospy.Publisher', source)
        self.assertNotIn('publish(', source)
        self.assertNotIn('rospy.ServiceProxy', source)
        self.assertNotIn('SimpleActionClient', source)
        self.assertNotIn('actionlib', source)
        self.assertNotIn('Twist', source)
        self.assertIn('from tf2_msgs.msg import TFMessage', source)
        self.assertIn("callback_args='/tf'", source)
        self.assertIn("callback_args='/tf_static'", source)
        self.assertIn('validate_tf_edge_evidence(', source)
        self.assertIn('current_tf_publishers_by_topic=', source)
        self.assertIn('vendor_tf_rules_file', source)
        self.assertIn('vendor_source_manifest_file', source)
        self.assertIn('vendor_publisher_pin_file', source)
        self.assertIn('load_verified_vendor_tf_rules(', source)
        self.assertIn("'vendor_contract':", source)
        self.assertIn('_resolve_package_root', source)
        self.assertNotIn('blocker_file=', source)
        self.assertIn('tf_observations', source)
        self.assertIn('rospkg.RosPack().get_path(', topology_source)
        self.assertNotIn('subprocess.run(', topology_source)
        self.assertLess(
            source.index('validate_amcl_transform_tolerance('),
            source.index('rospy.Subscriber('))

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_root = root / 'source_pkg'
            (source_root / 'scripts').mkdir(parents=True)
            (source_root / 'config').mkdir()
            (source_root / 'docs').mkdir()
            (source_root / 'package.xml').write_text(
                '<package/>\n', encoding='utf-8')
            source_script = source_root / 'scripts' / 'probe.py'
            source_script.write_text('', encoding='utf-8')
            self.assertEqual(
                PREFLIGHT._resolve_package_root(source_script), source_root)
            self.assertEqual(
                FIELD._resolve_package_root(source_script), source_root)

            prefix = root / 'install'
            install_script = (
                prefix / 'lib' / 'limo_v1_navigation' / 'probe.py')
            install_script.parent.mkdir(parents=True)
            install_script.write_text('', encoding='utf-8')
            share = prefix / 'share' / 'limo_v1_navigation'
            (share / 'config').mkdir(parents=True)
            (share / 'docs').mkdir()
            (share / 'package.xml').write_text(
                '<package/>\n', encoding='utf-8')
            self.assertEqual(
                PREFLIGHT._resolve_package_root(install_script), share)
            self.assertEqual(
                FIELD._resolve_package_root(install_script), share)
            with self.assertRaises(RuntimeError):
                PREFLIGHT._resolve_package_root(root / 'missing' / 'probe.py')
            with self.assertRaises(RuntimeError):
                FIELD._resolve_package_root(root / 'missing' / 'probe.py')

            ros_pack = mock.Mock()
            ros_pack.get_path.return_value = str(source_root)
            rospkg_module = types.ModuleType('rospkg')
            rospkg_module.RosPack = mock.Mock(return_value=ros_pack)
            with mock.patch.dict(sys.modules, {'rospkg': rospkg_module}):
                self.assertEqual(
                    TOPOLOGY._resolve_ros_package_root('source_pkg'),
                    source_root.resolve())
            ros_pack.get_path.assert_called_once_with('source_pkg')

            missing_ros_pack = mock.Mock()
            missing_ros_pack.get_path.return_value = str(root / 'missing_pkg')
            missing_rospkg = types.ModuleType('rospkg')
            missing_rospkg.RosPack = mock.Mock(
                return_value=missing_ros_pack)
            with mock.patch.dict(
                    sys.modules, {'rospkg': missing_rospkg}), \
                    self.assertRaises(TfEdgeValidationError) as raised:
                TOPOLOGY._resolve_ros_package_root('missing_pkg')
            self.assertEqual(
                raised.exception.code, 'TF_VENDOR_CONTRACT_UNVERIFIED')

        loaders = (
            ('runtime_preflight', PREFLIGHT._load_vendor_tf_rules),
            ('perception_only', FIELD._load_vendor_tf_rules),
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            valid = _vendor_bundle(root / 'valid')
            roslib_module = types.ModuleType('roslib')
            roslib_module.__path__ = []
            packages_module = types.ModuleType('roslib.packages')
            roslib_module.packages = packages_module
            executable_alias = str(
                valid['executable'].parent / '..' / 'tf' /
                valid['executable'].name)
            for case, candidates in (
                    ('duplicate_raw_node_candidate', [
                        str(valid['executable']), str(valid['executable'])]),
                    ('alias_raw_node_candidate', [
                        str(valid['executable']), executable_alias])):
                packages_module.find_node = mock.Mock(return_value=candidates)
                with self.subTest(case=case), mock.patch.dict(
                        sys.modules, {
                            'roslib': roslib_module,
                            'roslib.packages': packages_module,
                        }), self.assertRaises(
                            TfEdgeValidationError) as raised:
                    TOPOLOGY._resolve_ros_node_executables(
                        'tf', 'static_transform_publisher')
                self.assertEqual(
                    raised.exception.code, 'TF_VENDOR_CONTRACT_UNVERIFIED')
            for loader_name, loader in loaders:
                with self.subTest(loader=loader_name, case='valid_fixture'):
                    with _trusted_vendor_bundle(valid):
                        rules = loader(
                            str(valid['rules_path']),
                            str(valid['source_path']),
                            str(valid['pin_path']))
                    self.assertEqual(len(rules), 1)
                    self.assertEqual(rules[0].authority,
                                     '/base_link_to_laser_link')
                    provenance = rules.evidence_summary()
                    self.assertEqual(provenance['status'], 'VERIFIED')
                    self.assertEqual(
                        provenance['binding_verdict'],
                        'BYTE_AND_SEMANTIC_MATCH')
                    self.assertEqual(
                        provenance['rules_manifest']['sha256'],
                        _file_sha(valid['rules_path']))
                    self.assertEqual(
                        provenance['ros_package_roots'], {
                            package: str(path)
                            for package, path in sorted(
                                valid['package_roots'].items())
                        })
                    self.assertEqual(
                        provenance['publisher_executable']['path'],
                        str(valid['executable'].resolve()))
                    self.assertEqual(
                        provenance['consumer_wrapper']['path'],
                        str(valid['wrapper'].resolve()))
                    self.assertEqual(
                        provenance['consumer_wrapper']['sha256'],
                        _file_sha(valid['wrapper']))
                with self.subTest(
                        loader=loader_name,
                        case='installed_blocker_still_closed'):
                    with self.assertRaises(TfEdgeValidationError) as raised:
                        loader(
                            str(valid['rules_path']),
                            str(valid['source_path']),
                            str(valid['pin_path']))
                    self.assertEqual(
                        raised.exception.code,
                        'TF_VENDOR_CONTRACT_UNVERIFIED')
                with self.subTest(
                        loader=loader_name,
                        case='blocker_override_not_exposed'):
                    with self.assertRaises(TypeError):
                        loader(
                            str(valid['rules_path']),
                            str(valid['source_path']),
                            str(valid['pin_path']),
                            str(valid['blocker_path']))

            audited_include = _vendor_bundle(root / 'audited_include')
            _rewrite_raw_and_rebind(
                audited_include, 'raw_root', _audited_vendor_root_xml())
            for loader_name, loader in loaders:
                with self.subTest(
                        loader=loader_name,
                        case='audited_include_child_args_accepted'):
                    with _trusted_vendor_bundle(audited_include):
                        rules = loader(
                            str(audited_include['rules_path']),
                            str(audited_include['source_path']),
                            str(audited_include['pin_path']))
                    provenance = rules.evidence_summary()
                    resolution = provenance['include_argument_resolution']
                    self.assertEqual(
                        resolution['parser_version'],
                        'limo_v1_vendor_include_args/restricted_v1')
                    self.assertEqual(resolution['binding_count'], 1)
                    binding = resolution['bindings'][0]
                    self.assertEqual(
                        binding['artifact_sha256'],
                        _file_sha(audited_include['raw_root']))
                    self.assertEqual(
                        [argument['name'] for argument in binding['arguments']],
                        ['port_name', 'use_mcnamu', 'pub_odom_tf'])
                    self.assertEqual(
                        [argument['default_resolution']
                         for argument in binding['arguments']],
                        ['ttyTHS0', 'false', 'false'])
                    self.assertTrue(all(
                        argument['runtime_override_sensitive'] is True
                        for argument in binding['arguments']))
                    normalized = dict(binding)
                    observed_digest = normalized.pop(
                        'normalized_result_sha256')
                    expected_digest = hashlib.sha256(json.dumps(
                        normalized, sort_keys=True,
                        separators=(',', ':')).encode('utf-8')).hexdigest()
                    self.assertEqual(observed_digest, expected_digest)

            variants = []

            fake_hash = _vendor_bundle(root / 'fake_hash')
            payload = json.loads(
                fake_hash['rules_path'].read_text(encoding='utf-8'))
            payload['source_manifest_sha256'] = '0' * 64
            _write_json(fake_hash['rules_path'], payload)
            _rebind_blocker_only(fake_hash)
            variants.append(('formatted_fake_hash', fake_hash, None))

            self_report = _vendor_bundle(root / 'self_report')
            payload = json.loads(
                self_report['rules_path'].read_text(encoding='utf-8'))
            payload['rules'][0]['provenance_verified'] = True
            _write_json(self_report['rules_path'], payload)
            _rebind_blocker_only(self_report)
            variants.append(('self_reported_true', self_report, None))

            missing_reference = _vendor_bundle(root / 'missing_reference')
            payload = json.loads(
                missing_reference['source_path'].read_text(encoding='utf-8'))
            payload['artifacts'][1]['absolute_path'] = str(
                root / 'does_not_exist.launch')
            _write_json(missing_reference['source_path'], payload)
            _rebind_vendor_bundle(missing_reference)
            variants.append(
                ('referenced_artifact_missing', missing_reference, None))

            content_mismatch = _vendor_bundle(root / 'content_mismatch')
            content_mismatch['raw_root'].write_text(
                '<launch></launch>\n', encoding='utf-8')
            variants.append(
                ('referenced_content_hash_mismatch', content_mismatch, None))

            blocked_source = _vendor_bundle(root / 'blocked_source')
            payload = json.loads(
                blocked_source['source_path'].read_text(encoding='utf-8'))
            payload['status'] = 'BLOCKED'
            _write_json(blocked_source['source_path'], payload)
            _rebind_vendor_bundle(blocked_source)
            variants.append(
                ('source_artifact_status_not_verified', blocked_source, None))

            blocked_pin = _vendor_bundle(root / 'blocked_pin')
            payload = json.loads(
                blocked_pin['pin_path'].read_text(encoding='utf-8'))
            payload['status'] = 'BLOCKED'
            _write_json(blocked_pin['pin_path'], payload)
            _rebind_vendor_bundle(blocked_pin)
            variants.append(
                ('publisher_pin_status_not_verified', blocked_pin, None))

            semantic_mismatch = _vendor_bundle(root / 'semantic_mismatch')
            payload = json.loads(
                semantic_mismatch['rules_path'].read_text(encoding='utf-8'))
            payload['rules'][0]['authority'] = '/self_reported_owner'
            _write_json(semantic_mismatch['rules_path'], payload)
            _rebind_blocker_only(semantic_mismatch)
            variants.append(
                ('rules_pin_source_semantic_mismatch', semantic_mismatch, None))

            pin_source_mismatch = _vendor_bundle(root / 'pin_source_mismatch')
            payload = json.loads(
                pin_source_mismatch['pin_path'].read_text(encoding='utf-8'))
            payload['rules'][0]['callerid'] = '/wrong_source_owner'
            _write_json(pin_source_mismatch['pin_path'], payload)
            _rebind_vendor_bundle(pin_source_mismatch)
            variants.append(
                ('publisher_pin_source_semantic_mismatch',
                 pin_source_mismatch, None))

            swapped_child = _vendor_bundle(root / 'swapped_child')
            payload = json.loads(
                swapped_child['source_path'].read_text(encoding='utf-8'))
            payload['include_edges'][0]['child_artifact_id'] = 'tmini'
            payload['include_edges'][1]['child_artifact_id'] = 'limo_base'
            _write_json(swapped_child['source_path'], payload)
            _rebind_vendor_bundle(swapped_child)
            variants.append(
                ('include_expression_child_mismatch', swapped_child, None))

            self_loop = _vendor_bundle(root / 'self_loop')
            payload = json.loads(
                self_loop['source_path'].read_text(encoding='utf-8'))
            payload['include_edges'][0]['child_artifact_id'] = 'limo_start'
            _write_json(self_loop['source_path'], payload)
            _rebind_vendor_bundle(self_loop)
            variants.append(('include_self_loop', self_loop, None))

            cycle = _vendor_bundle(root / 'cycle')
            cycle_expression = str(cycle['raw_root'].resolve())
            _rewrite_raw_and_rebind(
                cycle, 'raw_base',
                '<launch><include file="{}" /></launch>\n'.format(
                    cycle_expression))
            payload = json.loads(
                cycle['source_path'].read_text(encoding='utf-8'))
            payload['include_edges'].append({
                'parent_artifact_id': 'limo_base',
                'include_expression': cycle_expression,
                'child_artifact_id': 'limo_start',
            })
            _write_json(cycle['source_path'], payload)
            _rebind_vendor_bundle(cycle)
            variants.append(('include_cycle', cycle, None))

            unresolved_substitution = _vendor_bundle(
                root / 'unresolved_substitution')
            _rewrite_raw_and_rebind(
                unresolved_substitution, 'raw_root',
                '<launch>'
                '<include file="$(find limo_base)/launch/limo_base.launch" />'
                '<include file="$(find ydlidar_ros_driver)/launch/Tmini.launch" />'
                '<node pkg="tf" type="static_transform_publisher" '
                'name="$(arg tf_name)" '
                'args="0.105 0 0.08 0 0 0 base_link laser_link 100" />'
                '</launch>\n')
            variants.append(
                ('unresolved_static_substitution',
                 unresolved_substitution, None))

            unresolved_namespace = _vendor_bundle(
                root / 'unresolved_namespace')
            _rewrite_raw_and_rebind(
                unresolved_namespace, 'raw_root',
                '<launch>'
                '<include file="$(find limo_base)/launch/limo_base.launch" />'
                '<include file="$(find ydlidar_ros_driver)/launch/Tmini.launch" />'
                '<group ns="robot"><node pkg="tf" '
                'type="static_transform_publisher" '
                'name="base_link_to_laser_link" '
                'args="0.105 0 0.08 0 0 0 base_link laser_link 100" />'
                '</group></launch>\n')
            variants.append(
                ('unresolved_static_namespace', unresolved_namespace, None))

            unresolved_group_attribute = _vendor_bundle(
                root / 'unresolved_group_attribute')
            _rewrite_raw_and_rebind(
                unresolved_group_attribute, 'raw_root',
                '<launch>'
                '<include file="$(find limo_base)/launch/limo_base.launch" />'
                '<include file="$(find ydlidar_ros_driver)/launch/Tmini.launch" />'
                '<group clear_params="true"><node pkg="tf" '
                'type="static_transform_publisher" '
                'name="base_link_to_laser_link" '
                'args="0.105 0 0.08 0 0 0 base_link laser_link 100" />'
                '</group></launch>\n')
            variants.append(
                ('unresolved_static_group_attribute',
                 unresolved_group_attribute, None))

            unresolved_node_package = _vendor_bundle(
                root / 'unresolved_node_package')
            _rewrite_raw_and_rebind(
                unresolved_node_package, 'raw_root',
                '<launch>'
                '<include file="$(find limo_base)/launch/limo_base.launch" />'
                '<include file="$(find ydlidar_ros_driver)/launch/Tmini.launch" />'
                '<node pkg="$(arg tf_package)" '
                'type="static_transform_publisher" '
                'name="base_link_to_laser_link" '
                'args="0.105 0 0.08 0 0 0 base_link laser_link 100" />'
                '</launch>\n')
            variants.append(
                ('unresolved_node_package', unresolved_node_package, None))

            unresolved_node_type = _vendor_bundle(
                root / 'unresolved_node_type')
            _rewrite_raw_and_rebind(
                unresolved_node_type, 'raw_root',
                '<launch>'
                '<include file="$(find limo_base)/launch/limo_base.launch" />'
                '<include file="$(find ydlidar_ros_driver)/launch/Tmini.launch" />'
                '<node pkg="tf" type="$(arg tf_node_type)" '
                'name="base_link_to_laser_link" '
                'args="0.105 0 0.08 0 0 0 base_link laser_link 100" />'
                '</launch>\n')
            variants.append(
                ('unresolved_node_type', unresolved_node_type, None))

            unsupported_static_package = _vendor_bundle(
                root / 'unsupported_static_package')
            _rewrite_raw_and_rebind(
                unsupported_static_package, 'raw_root',
                '<launch>'
                '<include file="$(find limo_base)/launch/limo_base.launch" />'
                '<include file="$(find ydlidar_ros_driver)/launch/Tmini.launch" />'
                '<node pkg="custom_tf" type="static_transform_publisher" '
                'name="base_link_to_laser_link" '
                'args="0.105 0 0.08 0 0 0 base_link laser_link 100" />'
                '</launch>\n')
            variants.append(
                ('unsupported_static_tf_package',
                 unsupported_static_package, None))

            unresolved_condition = _vendor_bundle(
                root / 'unresolved_condition')
            _rewrite_raw_and_rebind(
                unresolved_condition, 'raw_root',
                '<launch>'
                '<include file="$(find limo_base)/launch/limo_base.launch" />'
                '<include file="$(find ydlidar_ros_driver)/launch/Tmini.launch" />'
                '<node if="$(arg publish_tf)" pkg="tf" '
                'type="static_transform_publisher" '
                'name="base_link_to_laser_link" '
                'args="0.105 0 0.08 0 0 0 base_link laser_link 100" />'
                '</launch>\n')
            variants.append(
                ('unresolved_static_condition', unresolved_condition, None))

            unresolved_remap = _vendor_bundle(root / 'unresolved_remap')
            _rewrite_raw_and_rebind(
                unresolved_remap, 'raw_root',
                '<launch>'
                '<include file="$(find limo_base)/launch/limo_base.launch" />'
                '<include file="$(find ydlidar_ros_driver)/launch/Tmini.launch" />'
                '<node pkg="tf" type="static_transform_publisher" '
                'name="base_link_to_laser_link" '
                'args="0.105 0 0.08 0 0 0 base_link laser_link 100">'
                '<remap from="/tf" to="/tf_static" />'
                '</node></launch>\n')
            variants.append(
                ('unresolved_static_remap', unresolved_remap, None))

            include_arg = _vendor_bundle(root / 'include_arg')
            _rewrite_raw_and_rebind(
                include_arg, 'raw_root',
                '<launch>'
                '<include file="$(find limo_base)/launch/limo_base.launch">'
                '<arg name="unexpected" value="true" />'
                '</include>'
                '<include file="$(find ydlidar_ros_driver)/launch/Tmini.launch" />'
                '<node pkg="tf" type="static_transform_publisher" '
                'name="base_link_to_laser_link" '
                'args="0.105 0 0.08 0 0 0 base_link laser_link 100" />'
                '</launch>\n')
            variants.append(('vendor_include_child_arg', include_arg, None))

            unknown_include_arg = _vendor_bundle(
                root / 'unknown_include_arg')
            _rewrite_raw_and_rebind(
                unknown_include_arg, 'raw_root', _audited_vendor_root_xml(
                    include_args=(
                        '<arg name="port_name" '
                        'default="$(arg port_name)" />'
                        '<arg name="use_mcnamu" '
                        'default="$(arg use_mcnamu)" />'
                        '<arg name="unexpected" '
                        'default="$(arg unexpected)" />')))
            variants.append((
                'audited_include_unknown_arg', unknown_include_arg,
                'missing or unknown'))

            duplicate_include_arg = _vendor_bundle(
                root / 'duplicate_include_arg')
            _rewrite_raw_and_rebind(
                duplicate_include_arg, 'raw_root', _audited_vendor_root_xml(
                    include_args=(
                        '<arg name="port_name" '
                        'default="$(arg port_name)" />'
                        '<arg name="port_name" '
                        'default="$(arg port_name)" />'
                        '<arg name="pub_odom_tf" '
                        'default="$(arg pub_odom_tf)" />')))
            variants.append((
                'audited_include_duplicate_arg', duplicate_include_arg,
                'contain duplicates'))

            missing_include_arg = _vendor_bundle(
                root / 'missing_include_arg')
            _rewrite_raw_and_rebind(
                missing_include_arg, 'raw_root', _audited_vendor_root_xml(
                    include_args=(
                        '<arg name="port_name" '
                        'default="$(arg port_name)" />'
                        '<arg name="use_mcnamu" '
                        'default="$(arg use_mcnamu)" />')))
            variants.append((
                'audited_include_missing_arg', missing_include_arg,
                'missing or contain unknown nodes'))

            malicious_child_attribute = _vendor_bundle(
                root / 'malicious_child_attribute')
            _rewrite_raw_and_rebind(
                malicious_child_attribute, 'raw_root',
                _audited_vendor_root_xml(include_args=(
                    '<arg name="port_name" default="$(arg port_name)" '
                    'value="$(env HOME)" />'
                    '<arg name="use_mcnamu" '
                    'default="$(arg use_mcnamu)" />'
                    '<arg name="pub_odom_tf" '
                    'default="$(arg pub_odom_tf)" />')))
            variants.append((
                'audited_include_malicious_child_attribute',
                malicious_child_attribute, 'attributes are unresolved or unsafe'))

            malicious_include_attribute = _vendor_bundle(
                root / 'malicious_include_attribute')
            _rewrite_raw_and_rebind(
                malicious_include_attribute, 'raw_root',
                _audited_vendor_root_xml(
                    include_extra_attributes=' if="$(arg unsafe)"'))
            variants.append((
                'audited_include_malicious_include_attribute',
                malicious_include_attribute,
                'vendor include has unresolved attributes'))

            global_remap = _vendor_bundle(root / 'global_remap')
            _rewrite_raw_and_rebind(
                global_remap, 'raw_root',
                '<launch>'
                '<include file="$(find limo_base)/launch/limo_base.launch" />'
                '<include file="$(find ydlidar_ros_driver)/launch/Tmini.launch" />'
                '<remap from="/tf" to="/tf_static" />'
                '<node pkg="tf" type="static_transform_publisher" '
                'name="base_link_to_laser_link" '
                'args="0.105 0 0.08 0 0 0 base_link laser_link 100" />'
                '</launch>\n')
            variants.append(
                ('vendor_launch_scope_tf_remap', global_remap, None))

            group_remap = _vendor_bundle(root / 'group_remap')
            _rewrite_raw_and_rebind(
                group_remap, 'raw_root',
                '<launch>'
                '<include file="$(find limo_base)/launch/limo_base.launch" />'
                '<include file="$(find ydlidar_ros_driver)/launch/Tmini.launch" />'
                '<group><remap from="/tf" to="/tf_static" />'
                '<node pkg="tf" type="static_transform_publisher" '
                'name="base_link_to_laser_link" '
                'args="0.105 0 0.08 0 0 0 base_link laser_link 100" />'
                '</group></launch>\n')
            variants.append(
                ('vendor_group_scope_tf_remap', group_remap, None))

            inherited_namespace = _vendor_bundle(
                root / 'inherited_namespace')
            _move_static_tf_to_included_base(
                inherited_namespace,
                '<launch><group ns="robot">'
                '<include file="$(find limo_base)/launch/limo_base.launch" />'
                '</group>'
                '<include file="$(find ydlidar_ros_driver)/launch/Tmini.launch" />'
                '</launch>\n')
            variants.append(
                ('vendor_include_inherited_namespace',
                 inherited_namespace, None))

            inherited_group_remap = _vendor_bundle(
                root / 'inherited_group_remap')
            _move_static_tf_to_included_base(
                inherited_group_remap,
                '<launch><group><remap from="/tf" to="/tf_static" />'
                '<include file="$(find limo_base)/launch/limo_base.launch" />'
                '</group>'
                '<include file="$(find ydlidar_ros_driver)/launch/Tmini.launch" />'
                '</launch>\n')
            variants.append(
                ('vendor_include_inherited_group_remap',
                 inherited_group_remap, None))

            inherited_if = _vendor_bundle(root / 'inherited_if')
            _move_static_tf_to_included_base(
                inherited_if,
                '<launch><group if="$(arg publish_tf)">'
                '<include file="$(find limo_base)/launch/limo_base.launch" />'
                '</group>'
                '<include file="$(find ydlidar_ros_driver)/launch/Tmini.launch" />'
                '</launch>\n')
            variants.append(
                ('vendor_include_inherited_if', inherited_if, None))

            inherited_unless = _vendor_bundle(root / 'inherited_unless')
            _move_static_tf_to_included_base(
                inherited_unless,
                '<launch><group unless="$(arg suppress_tf)">'
                '<include file="$(find limo_base)/launch/limo_base.launch" />'
                '</group>'
                '<include file="$(find ydlidar_ros_driver)/launch/Tmini.launch" />'
                '</launch>\n')
            variants.append(
                ('vendor_include_inherited_unless', inherited_unless, None))

            inherited_root_remap = _vendor_bundle(
                root / 'inherited_root_remap')
            _move_static_tf_to_included_base(
                inherited_root_remap,
                '<launch><remap from="/tf" to="/tf_static" />'
                '<include file="$(find limo_base)/launch/limo_base.launch" />'
                '<include file="$(find ydlidar_ros_driver)/launch/Tmini.launch" />'
                '</launch>\n')
            variants.append(
                ('vendor_include_inherited_root_remap',
                 inherited_root_remap, None))

            launch_prefix = _vendor_bundle(root / 'launch_prefix')
            _rewrite_raw_and_rebind(
                launch_prefix, 'raw_root',
                '<launch>'
                '<include file="$(find limo_base)/launch/limo_base.launch" />'
                '<include file="$(find ydlidar_ros_driver)/launch/Tmini.launch" />'
                '<node pkg="tf" type="static_transform_publisher" '
                'name="base_link_to_laser_link" launch-prefix="gdb --args" '
                'args="0.105 0 0.08 0 0 0 base_link laser_link 100" />'
                '</launch>\n')
            variants.append(
                ('vendor_static_tf_launch_prefix', launch_prefix, None))

            executable_mismatch = _vendor_bundle(root / 'executable_mismatch')
            executable_mismatch['executable'].write_bytes(b'changed\n')
            variants.append(
                ('publisher_executable_hash_mismatch',
                 executable_mismatch, None))

            wrapper_byte_mismatch = _vendor_bundle(
                root / 'wrapper_byte_mismatch')
            wrapper_byte_mismatch['wrapper'].write_text(
                SAFE_VENDOR_WRAPPER_XML + '\n', encoding='utf-8')
            variants.append(
                ('consumer_wrapper_byte_mismatch',
                 wrapper_byte_mismatch, None))

            wrapper_include_drift = _vendor_bundle(
                root / 'wrapper_include_drift')
            _rewrite_wrapper(
                wrapper_include_drift,
                '$(find limo_bringup)/launch/limo_start.launch',
                '$(find limo_bringup)/launch/other.launch',
                reanchor=True)
            variants.append(
                ('consumer_wrapper_include_semantic_drift',
                 wrapper_include_drift, None))

            wrapper_remap_drift = _vendor_bundle(
                root / 'wrapper_remap_drift')
            _rewrite_wrapper(
                wrapper_remap_drift,
                'to="/v1/driver_cmd_vel"', 'to="/cmd_vel"',
                reanchor=True)
            variants.append(
                ('consumer_wrapper_remap_semantic_drift',
                 wrapper_remap_drift, None))

            wrapper_forced_arg_drift = _vendor_bundle(
                root / 'wrapper_forced_arg_drift')
            _rewrite_wrapper(
                wrapper_forced_arg_drift,
                '<arg name="pub_odom_tf" value="true" />',
                '<arg name="pub_odom_tf" value="false" />',
                reanchor=True)
            variants.append(
                ('consumer_wrapper_forced_arg_semantic_drift',
                 wrapper_forced_arg_drift, None))

            wrapper_gate_drift = _vendor_bundle(root / 'wrapper_gate_drift')
            _rewrite_wrapper(
                wrapper_gate_drift,
                '<arg name="enable_hardware" default="false" />',
                '<arg name="enable_hardware" default="true" />',
                reanchor=True)
            variants.append(
                ('consumer_wrapper_gate_semantic_drift',
                 wrapper_gate_drift, None))

            package_path_mismatch = _vendor_bundle(
                root / 'package_path_mismatch')
            detached_launch = (
                package_path_mismatch['source_path'].parent /
                'detached_limo_start.launch')
            detached_launch.write_bytes(
                package_path_mismatch['raw_root'].read_bytes())
            payload = json.loads(
                package_path_mismatch['source_path'].read_text(
                    encoding='utf-8'))
            payload['artifacts'][0]['absolute_path'] = str(detached_launch)
            payload['artifacts'][0]['sha256'] = _file_sha(detached_launch)
            _write_json(package_path_mismatch['source_path'], payload)
            _rebind_vendor_bundle(package_path_mismatch)
            variants.append(
                ('source_path_mismatch_ros_package_resolution',
                 package_path_mismatch, None))

            alternate_executable = root / 'alternate_static_transform_publisher'
            alternate_executable.write_bytes(b'alternate-test-executable\n')

            for loader_name, loader in loaders:
                for case, bundle, expected_detail in variants:
                    with self.subTest(loader=loader_name, case=case):
                        with _trusted_vendor_bundle(bundle), \
                                self.assertRaises(
                                    TfEdgeValidationError) as raised:
                            loader(
                                str(bundle['rules_path']),
                                str(bundle['source_path']),
                                str(bundle['pin_path']))
                        self.assertEqual(
                            raised.exception.code,
                            'TF_VENDOR_CONTRACT_UNVERIFIED')
                        if expected_detail is not None:
                            self.assertIn(
                                expected_detail, str(raised.exception))
                with self.subTest(loader=loader_name, case='missing_artifact'):
                    with _trusted_vendor_bundle(valid), \
                            self.assertRaises(TfEdgeValidationError):
                        loader(
                            str(valid['rules_path']), '',
                            str(valid['pin_path']))
                with self.subTest(
                        loader=loader_name, case='nonexistent_artifact_path'):
                    with _trusted_vendor_bundle(valid), \
                            self.assertRaises(TfEdgeValidationError):
                        loader(
                            str(valid['rules_path']),
                            str(root / 'missing_source.json'),
                            str(valid['pin_path']))
                with self.subTest(
                        loader=loader_name,
                        case='self_signed_blocker_without_trust_anchor'):
                    wrapper = PREFLIGHT if loader_name == 'runtime_preflight' \
                        else FIELD
                    with mock.patch.object(
                            wrapper, 'VENDOR_BLOCKER_FILE',
                            valid['blocker_path']), self.assertRaises(
                                TfEdgeValidationError) as raised:
                        loader(
                            str(valid['rules_path']),
                            str(valid['source_path']),
                            str(valid['pin_path']))
                    self.assertEqual(
                        raised.exception.code,
                        'TF_VENDOR_CONTRACT_UNVERIFIED')
                with self.subTest(
                        loader=loader_name,
                        case='ros_package_resolution_missing'):
                    with _trusted_vendor_bundle(valid), mock.patch.object(
                            TOPOLOGY, '_resolve_ros_package_root',
                            return_value=root / 'missing_package'), \
                            self.assertRaises(
                                TfEdgeValidationError) as raised:
                        loader(
                            str(valid['rules_path']),
                            str(valid['source_path']),
                            str(valid['pin_path']))
                    self.assertEqual(
                        raised.exception.code,
                        'TF_VENDOR_CONTRACT_UNVERIFIED')
                for case, resolved_nodes in (
                        ('ros_node_resolution_missing', ()),
                        ('ros_node_resolution_duplicate', (
                            valid['executable'].resolve(),
                            valid['executable'].resolve())),
                        ('ros_node_resolution_ambiguous', (
                            valid['executable'].resolve(),
                            alternate_executable.resolve())),
                        ('ros_node_resolution_path_mismatch', (
                            alternate_executable.resolve(),))):
                    with self.subTest(loader=loader_name, case=case):
                        with _trusted_vendor_bundle(valid), mock.patch.object(
                                TOPOLOGY, '_resolve_ros_node_executables',
                                return_value=resolved_nodes), \
                                self.assertRaises(
                                    TfEdgeValidationError) as raised:
                            loader(
                                str(valid['rules_path']),
                                str(valid['source_path']),
                                str(valid['pin_path']))
                        self.assertEqual(
                            raised.exception.code,
                            'TF_VENDOR_CONTRACT_UNVERIFIED')


if __name__ == '__main__':
    unittest.main()

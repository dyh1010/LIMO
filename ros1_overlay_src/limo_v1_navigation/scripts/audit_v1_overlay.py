#!/usr/bin/env python3
"""Dependency-free static expansion and safety audit for V1 launch files."""

import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / 'src'))

from limo_v1_navigation.config_policy import (  # noqa: E402
    load_profile,
    validate_amcl_transform_tolerance,
)


LAUNCH_NAMES = (
    'v1_base_sensors.launch',
    'v1_mapping.launch',
    'v1_localization.launch',
    'v1_navigation_core.launch',
    'v1_navigation.launch',
    'v1_runtime_preflight.launch',
)
def _arg(root, name):
    return root.find("./arg[@name='{}']".format(name))


def validate_navigation_base_scope(launch_sources):
    """Require one public native-only navigation base without bridge code."""
    joined = '\n'.join(launch_sources.values())
    for forbidden in (
            'limo_cleanup_ros1_base',
            'navigation_bridge_adapter.launch',
            'move_base_private_request.launch'):
        if forbidden in joined:
            raise RuntimeError(
                'V1 navigation base must not include bridge implementation')

    core = ET.fromstring(launch_sources['v1_navigation_core.launch'])
    expected_core_args = {'map_file', 'active_map_id', 'preflight_token'}
    actual_core_args = {
        argument.attrib.get('name') for argument in core.findall('./arg')}
    if actual_core_args != expected_core_args:
        raise RuntimeError('navigation core arguments must be native-only')
    for required_arg in expected_core_args:
        argument = _arg(core, required_arg)
        if argument is None or 'default' in argument.attrib:
            raise RuntimeError(
                'navigation core must require {}'.format(required_arg))
    core_groups = list(core.iter('group'))
    if len(core_groups) != 1:
        raise RuntimeError('navigation core must have exactly one gated group')
    core_group = core_groups[0]
    condition = core_group.attrib.get('if', '')
    for required in (
            "arg('preflight_token')",
            "arg('map_file') != ''",
            "arg('active_map_id') != ''",
            "arg('active_map_id') not in ['map02', 'map1017', 'NOT_AVAILABLE_MAP_NOT_FROZEN']",
            "'map1017' not in arg('map_file')",
            "'map02' not in arg('map_file')",
            "'/limo_bringup/maps/' not in arg('map_file')"):
        if required not in condition:
            raise RuntimeError(
                'navigation core condition missing {}'.format(required))
    core_node_contract = sorted(
        (node.attrib.get('name'), node.attrib.get('pkg'), node.attrib.get('type'))
        for node in core_group.iter('node'))
    if core_node_contract != sorted((
            ('map_server', 'map_server', 'map_server'),
            ('amcl', 'amcl', 'amcl'),
            ('move_base', 'move_base', 'move_base'))):
        raise RuntimeError(
            'navigation core may only own map_server, AMCL, and move_base')
    remaps = [
        (remap.attrib.get('from'), remap.attrib.get('to'))
        for remap in core_group.find(
            "./node[@name='move_base']").findall(
            'remap')]
    if remaps != [
            ('move_base', '/v1/private_move_base'),
            ('move_base_simple/goal', '/v1/private_move_base_simple/goal'),
            ('/cmd_vel', '/v1/nav_cmd_vel')]:
        raise RuntimeError(
            'navigation core must privately remap the sole move_base output')
    if list(core.iter('include')):
        raise RuntimeError('navigation core must not include another launch')

    root = ET.fromstring(launch_sources['v1_navigation.launch'])
    if _arg(root, 'mode') is not None:
        raise RuntimeError('public navigation wrapper must reject mode overrides')
    public_sources = (
        launch_sources['v1_navigation.launch']
        + launch_sources['v1_navigation_core.launch'])
    if ('/cleanup/base/cmd_vel_request' in public_sources
            or 'cmd_vel_output_topic' in public_sources):
        raise RuntimeError('public navigation launches must be native-only')
    core_includes = [
        include for include in root.iter('include')
        if include.attrib.get('file') == (
            '$(find limo_v1_navigation)/launch/v1_navigation_core.launch')]
    if len(core_includes) != 1:
        raise RuntimeError('navigation wrapper must include core exactly once')
    include_groups = [
        group for group in root.iter('group')
        if core_includes[0] in list(group.iter('include'))]
    if len(include_groups) != 1:
        raise RuntimeError('navigation core include must be in one mode group')
    include_condition = include_groups[0].attrib.get('if', '')
    for required in (
            "arg('enable_navigation') == 'true'",
            "arg('preflight_token')"):
        if required not in include_condition:
            raise RuntimeError(
                'navigation wrapper mode condition missing {}'.format(
                    required))
    mode_params = [
        param for param in include_groups[0].iter('param')
        if param.attrib.get('name') == '/v1/navigation_mode']
    if (len(mode_params) != 1
            or mode_params[0].attrib.get('value') != 'native'):
        raise RuntimeError('navigation wrapper must export native mode')
    include_args = {
        argument.attrib.get('name'): argument.attrib.get('value')
        for argument in core_includes[0].findall('arg')}
    if set(include_args) != {'map_file', 'active_map_id', 'preflight_token'}:
        raise RuntimeError('navigation wrapper core interface is incomplete')
    wrapper_nodes = [node.attrib.get('name') for node in root.iter('node')]
    if wrapper_nodes.count('v1_cmd_guard') != 1:
        raise RuntimeError('native wrapper must own exactly one V1 guard')
    if any(name in wrapper_nodes for name in (
            'map_server', 'amcl', 'move_base')):
        raise RuntimeError('navigation wrapper must not duplicate core nodes')
    guard_group = next(
        (group for group in root.iter('group')
         if any(node.attrib.get('name') == 'v1_cmd_guard'
                for node in group.iter('node'))), None)
    if (guard_group is None
            or "arg('preflight_token')" not in guard_group.attrib.get('if', '')):
        raise RuntimeError('V1 guard must share the native startup gate')


def audit():
    profile = load_profile(
        PACKAGE_ROOT / 'config' / 'v1_navigation_profile.yaml')
    validate_amcl_transform_tolerance(
        profile, PACKAGE_ROOT / 'config' / 'amcl.yaml')
    manifest = {'launch_files': {}, 'profile_schema_version': 1}
    launch_sources = {}
    for name in LAUNCH_NAMES:
        path = PACKAGE_ROOT / 'launch' / name
        source = path.read_text(encoding='utf-8')
        launch_sources[name] = source
        root = ET.fromstring(source)
        nodes = [node.attrib.get('name') for node in root.iter('node')]
        includes = [node.attrib.get('file') for node in root.iter('include')]
        rosparams = [node.attrib.get('file') for node in root.iter('rosparam')]
        remaps = [
            (node.attrib.get('from'), node.attrib.get('to'))
            for node in root.iter('remap')]
        manifest['launch_files'][name] = {
            'nodes': nodes,
            'includes': includes,
            'rosparams': rosparams,
            'remaps': remaps,
        }

    joined = '\n'.join(launch_sources.values())
    if 'maps/map1017.yaml' in joined or 'maps/map02.yaml' in joined:
        raise RuntimeError('vendor map hardcoding is forbidden')
    if 'robot_pose_ekf' in joined:
        raise RuntimeError('robot_pose_ekf is forbidden in the V1 overlay')
    if 'limo_navigation_diff.launch' in joined:
        raise RuntimeError('vendor navigation launch must not be included')
    if '/cleanup/base/cmd_vel_request' in joined:
        raise RuntimeError(
            'installed V1 launch files must not expose the bridge request topic')
    validate_navigation_base_scope(launch_sources)

    base = ET.parse(
        PACKAGE_ROOT / 'launch' / 'v1_base_sensors.launch').getroot()
    owner = _arg(base, 'odom_tf_owner')
    if owner is None or 'default' in owner.attrib:
        raise RuntimeError('odom_tf_owner must be mandatory')
    base_source = (PACKAGE_ROOT / 'launch' / 'v1_base_sensors.launch').read_text(
        encoding='utf-8')
    if '<arg name="pub_odom_tf" value="true"' not in base_source:
        raise RuntimeError('base driver must own odom TF')
    if ('from="/cmd_vel" to="/v1/driver_cmd_vel"'
            not in base_source):
        raise RuntimeError('base command subscriber must be private')

    for name in ('v1_localization.launch', 'v1_navigation.launch'):
        root = ET.parse(PACKAGE_ROOT / 'launch' / name).getroot()
        for required in ('map_file', 'active_map_id', 'preflight_token'):
            argument = _arg(root, required)
            if argument is None or 'default' in argument.attrib:
                raise RuntimeError(
                    '{} must require {}'.format(name, required))
    navigation_source = launch_sources['v1_navigation.launch']
    navigation_core_source = launch_sources['v1_navigation_core.launch']
    for required in (
            'global_planner/GlobalPlanner',
            'base_local_planner/TrajectoryPlannerROS',
            'from="/cmd_vel" to="/v1/nav_cmd_vel"'):
        if required not in navigation_core_source:
            raise RuntimeError('navigation core missing {}'.format(required))
    if 'driver_timeout_verified' not in navigation_source:
        raise RuntimeError('native wrapper missing driver timeout proof')
    navigation_root = ET.fromstring(navigation_source)
    for name in ('enable_goal_gateway', 'allow_goal_forwarding'):
        argument = _arg(navigation_root, name)
        if argument is None or argument.attrib.get('default') != 'false':
            raise RuntimeError('{} must default false'.format(name))
    if '/v1/private_move_base' not in navigation_core_source:
        raise RuntimeError('move_base action namespace must be private')
    gateway_source = (
        PACKAGE_ROOT / 'scripts' / 'v1_navigation_gateway.py'
    ).read_text(encoding='utf-8')
    for required in (
            "'/v1/private_move_base'",
            "'/v1/localization/ready'",
            "'/v1/cmd_guard/stop_latched'",
            'GoalGenerationGate',
            'goal forwarding is disabled'):
        if required not in gateway_source:
            raise RuntimeError(
                'navigation gateway contract missing {}'.format(required))
    for forbidden in ('Twist', '/cmd_vel'):
        if forbidden in gateway_source:
            raise RuntimeError(
                'navigation gateway must never expose {}'.format(forbidden))
    manager_source = (
        PACKAGE_ROOT / 'scripts' / 'v1_localization_manager.py'
    ).read_text(encoding='utf-8')
    for required in (
            "'/initialpose'", "'/v1/validated_initialpose'",
            "'/request_nomotion_update'",
            "'/v1/private_move_base/status'", 'nomotion_generation'):
        if required not in manager_source:
            raise RuntimeError(
                'localization manager contract missing {}'.format(required))
    for forbidden in ('Twist', 'send_goal', '/cmd_vel'):
        if forbidden in manager_source:
            raise RuntimeError(
                'localization manager must never expose {}'.format(forbidden))

    if profile['motion']['max_linear_x_mps'] >= 0.6:
        raise RuntimeError('vendor speed leaked into the V1 profile')
    manifest['status'] = 'V1_OVERLAY_STATIC_PASS'
    return manifest


def main():
    try:
        manifest = audit()
    except (OSError, RuntimeError, ValueError, ET.ParseError) as exc:
        print('V1_OVERLAY_STATIC_BLOCKED: {}'.format(exc), file=sys.stderr)
        return 1
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

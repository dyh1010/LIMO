import ast
from pathlib import Path


PACKAGE_ROOT = Path(__file__).parents[1]
CONSUMER = (
    PACKAGE_ROOT / 'limo_cleanup_base' / 'navigation_intent_consumer.py')
LAUNCH = PACKAGE_ROOT / 'launch' / 'navigation_intent_bridge.launch.py'
WAYPOINT_TEMPLATE = (
    PACKAGE_ROOT / 'config' / 'v1_navigation_waypoints.example.yaml')


def test_consumer_uses_exact_string_interface_and_has_no_velocity_output():
    source = CONSUMER.read_text(encoding='utf-8')
    tree = ast.parse(source)
    assert "'/cleanup/navigation_intent'" in source
    assert 'String' in source
    assert 'Twist' not in source
    assert 'PoseStamped' not in source
    publisher_types = []
    for node in ast.walk(tree):
        if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == 'create_publisher'
                and node.args
                and isinstance(node.args[0], ast.Name)):
            publisher_types.append(node.args[0].id)
    assert sorted(publisher_types) == ['Bool', 'String']
    for legacy in ('/goal', '/rearm', '/stop', '/cancel'):
        assert '/cleanup/navigation{}'.format(legacy) not in source
    assert '/cleanup/navigation/bridge_command' in source
    assert '/cleanup/navigation/bridge_status' in source


def test_launch_is_default_disabled_and_requires_map_inputs():
    source = LAUNCH.read_text(encoding='utf-8')
    assert "'enable_navigation_intent_bridge', default_value='false'" in source
    assert "DeclareLaunchArgument('waypoint_file', default_value='')" in source
    assert "DeclareLaunchArgument('active_v1_map_id', default_value='')" in source
    assert "DeclareLaunchArgument('epoch_state_file', default_value='')" in source
    assert "executable='navigation_topology_verifier'" in source
    assert "DeclareLaunchArgument('goal_timeout', default_value='120.0')" in source
    assert "'goal_timeout': ParameterValue(" in source
    template = WAYPOINT_TEMPLATE.read_text(encoding='utf-8')
    assert 'NOT_AVAILABLE_MAP_NOT_FROZEN' in template
    assert 'waypoints: {}' in template
    assert 'x:' not in template
    assert 'y:' not in template
    assert 'yaw:' not in template


def test_malformed_protocol_messages_latch_stop_and_revoke_authorization():
    source = CONSUMER.read_text(encoding='utf-8')
    status_callback = source[
        source.index('    def _on_status'):source.index('    def _on_intent')]
    intent_callback = source[
        source.index('    def _on_intent'):source.index('    def _on_timer')]
    for callback in (status_callback, intent_callback):
        assert 'except ValueError as error:' in callback
        assert 'self._latch_safe_stop(' in callback
    latch = source[
        source.index('    def _latch_safe_stop'):
        source.index('    def _on_status')]
    assert 'self.policy.latch_fault()' in latch
    assert 'self._publish_authorization(False)' in latch

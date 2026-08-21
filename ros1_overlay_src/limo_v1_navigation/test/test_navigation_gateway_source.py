import ast
from pathlib import Path
import unittest


PACKAGE_ROOT = Path(__file__).parents[1]
SCRIPT = PACKAGE_ROOT / 'scripts' / 'v1_navigation_gateway.py'


class NavigationGatewaySourceTest(unittest.TestCase):

    def test_gateway_has_goal_cancel_status_but_never_publishes_velocity(self):
        source = SCRIPT.read_text(encoding='utf-8')
        tree = ast.parse(source)
        self.assertIn('SimpleActionClient', source)
        self.assertIn('send_goal', source)
        self.assertIn('cancel_all_goals', source)
        self.assertIn("'/v1/navigation/status'", source)
        self.assertIn("'/v1/navigation/error'", source)
        self.assertNotIn('Twist', source)
        self.assertNotIn('/cmd_vel', source)
        publishers = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == 'Publisher']
        self.assertEqual(len(publishers), 2)

    def test_goal_forwarding_is_disabled_by_default_and_ready_gated(self):
        source = SCRIPT.read_text(encoding='utf-8')
        self.assertIn("'~enabled', False", source)
        self.assertIn("'~allow_goal_forwarding', False", source)
        self.assertIn('goal forwarding is disabled', source)
        self.assertIn("'/v1/localization/ready'", source)
        self.assertIn("'/v1/private_move_base'", source)
        self.assertIn('self.gate.submit(', source)
        self.assertLess(source.index('self.gate.submit('), source.index('send_goal('))
        self.assertIn('GoalGenerationGate', source)
        self.assertIn('self.goal_gate.commit(', source)
        self.assertIn('self.goal_gate.invalidate(', source)
        self.assertIn('threading.RLock()', source)
        self.assertIn("'/v1/cmd_guard/stop_latched'", source)
        self.assertIn('command_guard_heartbeat_stale', source)
        self.assertIn('self._guard_health(now)', source)
        self.assertIn('generation != self.active_goal_generation', source)
        self.assertIn("request_id = 'gateway-{}'", source)
        self.assertNotIn('header.seq must be', source)


if __name__ == '__main__':
    unittest.main()

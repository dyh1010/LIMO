import ast
from pathlib import Path
import unittest


PACKAGE_ROOT = Path(__file__).parents[1]
SCRIPT = PACKAGE_ROOT / 'scripts' / 'v1_diagnostic_capture.py'


class DiagnosticCaptureSourceTest(unittest.TestCase):

    def test_capture_is_subscriber_only_and_cannot_command_motion(self):
        source = SCRIPT.read_text(encoding='utf-8')
        tree = ast.parse(source)
        self.assertIn('rospy.Subscriber', source)
        self.assertNotIn('rospy.Publisher', source)
        self.assertNotIn('ServiceProxy', source)
        self.assertNotIn('SimpleActionClient', source)
        self.assertNotIn('send_goal', source)
        self.assertNotIn('Twist', source)
        self.assertNotIn('/cmd_vel', source)
        self.assertNotIn('rospy.sleep', source)
        self.assertIn('time.monotonic()', source)
        self.assertIn('finally:', source)
        self.assertIn('subscriber.unregister()', source)
        self.assertIn('threading.RLock()', source)
        self.assertIn("event='capture_initialization_failed'", source)
        self.assertIn('unregister_errors', source)
        publisher_calls = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == 'Publisher']
        self.assertEqual(publisher_calls, [])

    def test_capture_creates_only_a_new_timestamped_absolute_output(self):
        source = SCRIPT.read_text(encoding='utf-8')
        self.assertIn('output directory must be absolute', source)
        self.assertIn('timestamped output file already exists', source)
        self.assertIn('resolve(strict=True)', source)
        self.assertIn('output path escaped the requested directory', source)
        self.assertIn("strftime(", source)
        self.assertIn(".open('x'", source)


if __name__ == '__main__':
    unittest.main()

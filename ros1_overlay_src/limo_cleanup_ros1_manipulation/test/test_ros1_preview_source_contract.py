"""Static contract for the ROS1/Noetic preview-only adapter."""

import ast
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]


class Ros1PreviewSourceContractTest(unittest.TestCase):
    """Keep the new integration ROS1-only and incapable of device motion."""

    def test_package_is_catkin_ros1_noetic_shape(self):
        package = ET.fromstring((
            PACKAGE_ROOT / 'package.xml').read_text(encoding='utf-8'))
        dependencies = {
            item.text for item in package.findall('depend') if item.text
        }
        self.assertEqual('limo_cleanup_ros1_manipulation', package.findtext('name'))
        self.assertIn('rospy', dependencies)
        self.assertIn('std_msgs', dependencies)
        self.assertIn('limo_cleanup_ros1_perception', dependencies)
        cmake = (PACKAGE_ROOT / 'CMakeLists.txt').read_text(encoding='utf-8')
        self.assertIn('find_package(catkin REQUIRED COMPONENTS', cmake)
        self.assertIn('catkin_python_setup()', cmake)
        self.assertIn('catkin_install_python', cmake)

    def test_no_ros2_or_vendor_runtime_in_new_package(self):
        forbidden = (
            'rclpy', 'ament_', 'launch_ros', 'pymycobot', '/dev/',
            'serial.Serial', 'socket.', 'subprocess.', 'os.system',
        )
        runtime_paths = [
            PACKAGE_ROOT / 'package.xml',
            PACKAGE_ROOT / 'CMakeLists.txt',
            PACKAGE_ROOT / 'setup.py',
        ]
        for relative_root in ('src', 'scripts', 'config', 'launch'):
            runtime_paths.extend(
                path for path in (PACKAGE_ROOT / relative_root).rglob('*')
                if path.is_file())
        for path in sorted(runtime_paths):
            source = path.read_text(encoding='utf-8')
            for token in forbidden:
                self.assertNotIn(token, source, '{} contains {}'.format(path, token))

    def test_core_has_no_ros_imports(self):
        path = (
            PACKAGE_ROOT / 'src' / 'limo_cleanup_ros1_manipulation'
            / 'fixed_bottle_pick_core.py')
        tree = ast.parse(
            path.read_text(encoding='utf-8'), filename=str(path),
            feature_version=(3, 8))
        imports = set()
        for item in ast.walk(tree):
            if isinstance(item, ast.Import):
                imports.update(alias.name.split('.')[0] for alias in item.names)
            elif isinstance(item, ast.ImportFrom) and item.module:
                imports.add(item.module.split('.')[0])
        self.assertFalse(imports & {'rospy', 'rclpy', 'actionlib', 'tf', 'tf2_ros'})

    def test_preview_node_can_only_publish_non_executable_json(self):
        source = (PACKAGE_ROOT / 'scripts' / 'fixed_bottle_pick_preview_node.py').read_text(
            encoding='utf-8')
        self.assertIn('import rospy', source)
        self.assertIn('from limo_cleanup_ros1_perception.msg import PerceptionFrame', source)
        self.assertIn("'/cleanup/perception/frames'", source)
        self.assertNotIn("'/cleanup/perception/frame'", source)
        self.assertIn("'/cleanup/manipulation/pick_preview'", source)
        self.assertIn("rospy.get_param('~gripper_source_path')", source)
        self.assertIn('validate_gripper_source_bytes(', source)
        self.assertIn("'execution_permitted': False", source)
        self.assertNotIn('ServiceProxy', source)
        self.assertNotIn('SimpleActionClient', source)
        self.assertNotIn('Publisher(\'/cleanup/arm', source)
        self.assertNotIn('Publisher(\'/cleanup/gripper', source)

    def test_committed_policy_binds_user_gripper_and_keeps_all_motion_off(self):
        source = (PACKAGE_ROOT / 'config' / 'fixed_bottle_pick_offline.json').read_text(
            encoding='utf-8')
        self.assertIn(
            '62508BEA0CB96817099DC8EFDE10FEB034CAD7A844A95FEFDD29A3F57A6BBD18',
            source)
        self.assertIn('"bottle_60mm_target": 5', source)
        self.assertIn('"speed": 30', source)
        self.assertIn('"protect_current": 300', source)
        self.assertIn('"moving_required": true', source)
        self.assertIn('"allow_arm_motion": false', source)
        self.assertIn('"allow_gripper_motion": false', source)
        self.assertIn('"vendor_backend_allowed": false', source)
        self.assertIn('"device_access_allowed": false', source)


if __name__ == '__main__':
    unittest.main()

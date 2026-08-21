#!/usr/bin/env python3

"""Pure source contract for the disabled-by-default Catkin preview."""

import ast
from pathlib import Path
import unittest
import xml.etree.ElementTree as ElementTree


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PACKAGE_ROOT.parents[1]
AUTHORITATIVE_ROOT = (
    WORKSPACE_ROOT / 'src' / 'limo_cleanup_voice' / 'limo_cleanup_voice')


class Ros1VoicePackageContractTests(unittest.TestCase):
    def test_catkin_metadata_is_ros1_noetic_shape(self):
        package = ElementTree.parse(
            str(PACKAGE_ROOT / 'package.xml')).getroot()
        self.assertEqual(package.findtext('name'), 'limo_cleanup_ros1_voice')
        self.assertEqual(package.findtext('buildtool_depend'), 'catkin')
        dependencies = {item.text for item in package.findall('depend')}
        self.assertEqual(dependencies, {'rospy', 'std_msgs'})
        cmake = (PACKAGE_ROOT / 'CMakeLists.txt').read_text(
            encoding='utf-8')
        self.assertIn('catkin_python_setup()', cmake)
        self.assertIn('catkin_install_python(PROGRAMS', cmake)
        self.assertNotIn('ament', cmake)

    def test_setup_installs_authoritative_package_without_copy(self):
        source = (PACKAGE_ROOT / 'setup.py').read_text(encoding='utf-8')
        tree = ast.parse(source)
        self.assertIsInstance(tree, ast.Module)
        self.assertIn("packages=['limo_cleanup_voice']", source)
        self.assertIn("AUTHORITATIVE_PACKAGE_RELATIVE", source)
        self.assertIn(
            "Path('..') / 'limo_cleanup_voice' / 'limo_cleanup_voice'", source)
        self.assertIn("AUTHORITATIVE_PACKAGE_RELATIVE.as_posix()", source)
        self.assertNotIn("package_dir={'limo_cleanup_voice': str(", source)
        self.assertTrue(AUTHORITATIVE_ROOT.is_dir())

    def test_launch_is_absent_by_default_and_mock_only(self):
        launch_path = PACKAGE_ROOT / 'launch' / 'voice_offline_mock.launch'
        launch = ElementTree.parse(str(launch_path)).getroot()
        arguments = {
            item.attrib['name']: item.attrib.get('default')
            for item in launch.findall('arg')
        }
        self.assertEqual(arguments['enable_offline_adapter'], 'false')
        self.assertEqual(arguments['text_input_topic'],
                         '/voice_mock/text_input')
        group = launch.find('group')
        self.assertEqual(group.attrib.get('if'),
                         '$(arg enable_offline_adapter)')
        node = group.find('node')
        parameters = {
            item.attrib['name']: item.attrib['value']
            for item in node.findall('param')
        }
        self.assertEqual(parameters, {
            'profile': 'offline_text_mock',
            'allow_ros_publish': 'false',
            'allow_production_outputs': 'false',
        })

    def test_installed_entrypoint_retains_zero_publish_wrapper(self):
        entrypoint = (
            PACKAGE_ROOT / 'scripts' / 'voice_ros1_noetic_adapter.py'
        ).read_text(encoding='utf-8')
        wrapper = (
            AUTHORITATIVE_ROOT / 'ros1_noetic_adapter_node.py'
        ).read_text(encoding='utf-8')
        combined = entrypoint + wrapper
        self.assertIn('ros1_noetic_adapter_node import main', entrypoint)
        self.assertIn('rospy.Subscriber', wrapper)
        self.assertNotIn('rospy.Publisher', wrapper)
        for forbidden in (
                'cmd_vel', 'geometry_msgs', 'Twist', 'actionlib',
                '/move_base', '/dev/', 'serial'):
            self.assertNotIn(forbidden, combined)


if __name__ == '__main__':
    unittest.main()

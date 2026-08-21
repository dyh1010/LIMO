import unittest
from pathlib import Path


WORKSPACE_SRC = Path(__file__).resolve().parents[2]
INTERFACES = WORKSPACE_SRC / 'limo_cleanup_interfaces'


class GripperInterfaceContractTest(unittest.TestCase):
    def read(self, relative):
        return (INTERFACES / relative).read_text(encoding='utf-8')

    def lines(self, relative):
        return {
            line.strip()
            for line in self.read(relative).splitlines()
            if line.strip() and not line.lstrip().startswith('#')
        }

    def test_gateway_interfaces_are_registered(self):
        cmake = self.read('CMakeLists.txt')
        for relative in (
                'msg/GripperState.msg',
                'action/ExecuteGripperMotion.action',
                'srv/StopGripper.srv',
                'srv/AcknowledgeGripperFault.srv'):
            self.assertIn('"{}"'.format(relative), cmake)

    def test_action_requires_session_authorization_and_tool_revision(self):
        action = self.read('action/ExecuteGripperMotion.action')
        for field in (
                'string expected_tool_revision',
                'string authorization_id',
                'string expected_session_id',
                'string command_id',
                'string final_state'):
            self.assertIn(field, action)
        self.assertIn('TARGET_NORMALIZED_POSITION=1', action)
        self.assertIn('TARGET_JAW_OPENING_M=2', action)

    def test_stop_and_ack_are_separate_contracts(self):
        stop = self.read('srv/StopGripper.srv')
        ack = self.read('srv/AcknowledgeGripperFault.srv')
        self.assertIn('string reason', stop)
        self.assertIn('string expected_session_id', stop)
        self.assertNotIn('authorization_id', stop)
        self.assertIn('string authorization_id', ack)
        self.assertIn('string expected_session_id', ack)

    def test_state_exposes_validity_identity_and_physical_escalation(self):
        state_lines = self.lines('msg/GripperState.msg')
        for field in (
                'string STATE_PHYSICAL_ESTOP_REQUIRED='
                'PHYSICAL_ESTOP_REQUIRED',
                'bool valid',
                'string session_id',
                'uint64 sample_sequence',
                'builtin_interfaces/Time sample_stamp',
                'string tool_model',
                'string tool_revision',
                'string controller_identity',
                'string transport_identity',
                'string protocol_identity',
                'string controller_boot_id',
                'bool jaw_opening_valid',
                'bool motor_current_valid',
                'bool grip_force_valid',
                'string active_command_id',
                'string fault_reason'):
            self.assertIn(field, state_lines)

    def test_interfaces_contain_no_legacy_hardware_defaults(self):
        combined = '\n'.join(self.read(relative) for relative in (
            'msg/GripperState.msg',
            'action/ExecuteGripperMotion.action',
            'srv/StopGripper.srv',
            'srv/AcknowledgeGripperFault.srv',
        ))
        for forbidden in (
                'pymycobot', 'gripper_type', '/dev/', '255',
                'SG90', 'MG90S', 'MG996R'):
            self.assertNotIn(forbidden, combined)


if __name__ == '__main__':
    unittest.main()

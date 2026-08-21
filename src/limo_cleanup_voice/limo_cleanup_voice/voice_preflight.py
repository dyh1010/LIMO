# Copyright 2026 DYH
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""LEGACY_ROS2_OFFLINE_ONLY packaging preflight, never a Noetic gate."""

import argparse
import importlib
import json
from pathlib import Path

from .command_parser import parse_command
from .voice_contract import (
    TRASH_BIN_WAYPOINT,
    WAKE_WORD,
    navigation_stop_payload,
    navigation_waypoint_payload,
)


PINNED_NO_HARDWARE_SETTINGS = (
    "'use_mock_perception': 'true'",
    "'use_real_perception': 'false'",
    "'use_mock_executor': 'true'",
    "'executor_dry_run': 'true'",
    "'allow_arm_motion': 'false'",
    "'use_gripper_controller': 'false'",
    "'allow_gripper_motion': 'false'",
    "'use_tracked_base_controller': 'false'",
    "'allow_base_motion': 'false'",
)

RUNTIME_SOURCE_FILES = (
    'command_parser.py',
    'semantic_agent.py',
    'voice_asr_node.py',
    'voice_corpus_readiness.py',
    'voice_dialogue_node.py',
    'voice_priority_stop_node.py',
    'voice_semantic_agent_node.py',
    'voice_tts_node.py',
    'voice_contract.py',
)

FORBIDDEN_RUNTIME_TOKENS = (
    'geometry_msgs',
    'FollowJointTrajectory',
    'nav2_msgs',
    'power_on',
)


def _record(checks, name, passed, detail):
    checks.append({
        'name': name,
        'passed': bool(passed),
        'detail': detail,
    })


def _default_package_root():
    from ament_index_python.packages import get_package_share_directory
    return Path(get_package_share_directory('limo_cleanup_voice'))


def _load_bridge_parser():
    module = importlib.import_module(
        'limo_cleanup_base.navigation_intent_policy')
    return module.parse_navigation_intent


def run_preflight(package_root=None, bridge_parser=None):
    """Run deterministic read-only checks and return a JSON-safe report."""
    root = Path(package_root or _default_package_root()).resolve()
    source_runtime = root / 'limo_cleanup_voice'
    runtime_root = (
        source_runtime if source_runtime.is_dir()
        else Path(__file__).resolve().parent
    )
    checks = []

    required_paths = (
        root / 'launch' / 'full_system_with_voice.launch.py',
        root / 'launch' / 'voice_dialogue.launch.py',
        root / 'config' / 'voice_dialogue.yaml',
        root / 'docs' / 'VOICE_DEPLOYMENT_ROLLBACK.md',
        root / 'docs' / 'VOICE_FIELD_ACCEPTANCE_TEMPLATE.md',
    )
    missing = [str(path) for path in required_paths if not path.is_file()]
    _record(
        checks, 'required_files', not missing,
        'all required files present' if not missing else ', '.join(missing))

    full_launch = required_paths[0].read_text(encoding='utf-8')
    missing_pins = [
        item for item in PINNED_NO_HARDWARE_SETTINGS
        if item not in full_launch
    ]
    _record(
        checks, 'no_hardware_launch_pins', not missing_pins,
        'all mock/dry-run pins present' if not missing_pins
        else ', '.join(missing_pins))

    runtime_source = '\n'.join(
        (runtime_root / name).read_text(encoding='utf-8')
        for name in RUNTIME_SOURCE_FILES
    )
    forbidden = [
        token for token in FORBIDDEN_RUNTIME_TOKENS
        if token in runtime_source
    ]
    _record(
        checks, 'no_motion_runtime_dependencies', not forbidden,
        'no forbidden runtime dependencies' if not forbidden
        else ', '.join(forbidden))

    cases = {
        'wake_word': parse_command(
            WAKE_WORD + '，到垃圾桶旁边去',
            wake_words=[WAKE_WORD], require_wake_word=True).name,
        'missing_wake_word': parse_command(
            '到垃圾桶旁边去',
            wake_words=[WAKE_WORD], require_wake_word=True).name,
        'stop': parse_command(
            '停下', wake_words=[WAKE_WORD],
            require_wake_word=True).name,
        'speaker_relative': parse_command(
            WAKE_WORD + '，到这里来',
            wake_words=[WAKE_WORD], require_wake_word=True).name,
    }
    expected_cases = {
        'wake_word': 'navigate_to_bin',
        'missing_wake_word': 'ignored',
        'stop': 'stop_task',
        'speaker_relative': 'unsupported',
    }
    _record(
        checks, 'v2_vocabulary', cases == expected_cases,
        json.dumps(cases, ensure_ascii=False, sort_keys=True))

    stop_payload = navigation_stop_payload()
    waypoint_payload = navigation_waypoint_payload(TRASH_BIN_WAYPOINT)
    exact_payloads = (
        stop_payload == {
            'action': 'cancel_navigation',
            'request_safe_stop': True,
        }
        and waypoint_payload == {
            'action': 'navigate_to_waypoint',
            'target_id': 'trash_bin_staging',
            'target_source': 'fixed_map_waypoint',
        }
    )
    _record(
        checks, 'exact_navigation_payloads', exact_payloads,
        json.dumps(
            [stop_payload, waypoint_payload],
            ensure_ascii=False, sort_keys=True))

    try:
        parser = bridge_parser or _load_bridge_parser()
        parser(json.dumps(stop_payload, ensure_ascii=False))
        parser(json.dumps(waypoint_payload, ensure_ascii=False))
        bridge_ok = True
        bridge_detail = 'VOICE_BRIDGE_EXACT_PAYLOAD_READONLY_PASS'
    except Exception as error:  # noqa: BLE001
        bridge_ok = False
        bridge_detail = '{}: {}'.format(type(error).__name__, error)
    _record(
        checks, 'bridge_parser_readonly', bridge_ok, bridge_detail)

    report = {
        'status': 'PASS' if all(item['passed'] for item in checks) else 'FAIL',
        'mode': 'read_only_no_hardware',
        'package_root': str(root),
        'checks': checks,
    }
    return report


def main(args=None):
    """Run the deployment preflight without opening devices or ROS nodes."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package-root')
    parser.add_argument('--json-output')
    parsed = parser.parse_args(args)
    report = run_preflight(parsed.package_root)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered)
    if parsed.json_output:
        Path(parsed.json_output).write_text(
            rendered + '\n', encoding='utf-8')
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())

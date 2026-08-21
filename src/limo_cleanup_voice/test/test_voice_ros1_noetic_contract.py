"""Source contract for the blocked ROS1/Noetic voice runtime port."""

import hashlib
import json
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = (
    PACKAGE_ROOT / 'fixtures' / 'voice_ros1_noetic_runtime_contract.json'
)
VALID_ROS1_TYPES = {'std_msgs/String', 'std_msgs/Bool'}


def _contract():
    return json.loads(CONTRACT_PATH.read_text(encoding='utf-8'))


def _topics():
    return {item['name']: item for item in _contract()['topics']}


def _endpoint_nodes(topic):
    return {
        endpoint['node']
        for role in ('publishers', 'subscribers')
        for endpoint in topic[role]
    }


def test_ros1_contract_remains_blocked_and_offline_is_not_field_evidence():
    contract = _contract()

    assert contract['schema_version'] == 2
    assert contract['runtime_baseline'] == 'ros1_noetic'
    assert contract['implementation_status'] == (
        'BLOCKED_ROS1_ADAPTER_OFFLINE_ONLY')
    assert contract['field_delivery_ready'] is False
    assert contract['offline_evidence_is_field_evidence'] is False
    assert contract['profiles']['production_noetic']['authorized'] is False
    assert contract['safety']['live_ros_authorized'] is False
    assert contract['safety']['hardware_authorized'] is False


def test_every_legacy_ros2_entrypoint_has_the_machine_marker():
    contract = _contract()
    marker = contract['legacy_marker']
    paths = contract['legacy_ros2_entrypoints']

    assert marker == 'LEGACY_ROS2_OFFLINE_ONLY'
    assert len(paths) == len(set(paths))
    for relative_path in paths:
        source_path = PACKAGE_ROOT / relative_path
        assert source_path.is_file(), relative_path
        assert marker in source_path.read_text(encoding='utf-8'), relative_path


def test_ros_independence_claim_excludes_rclpy_wrappers():
    contract = _contract()
    independence = contract['ros_independence']

    assert 'pure modules only' in independence['claim']
    assert 'voice_contract.py' in independence['pure_modules']
    assert 'voice_wav_transcription_run.py' in independence['pure_modules']
    assert 'ros1_noetic_adapter.py' in independence['pure_modules']
    assert 'ros1_audio_input.py' in independence['pure_modules']
    assert 'tts_prompt_contract.py' in independence['pure_modules']
    assert 'voice_dialogue_node.py' not in independence['pure_modules']
    assert 'voice_priority_stop_node.py' in (
        independence[
            'legacy_wrappers_require_ros2_import_stubs_for_offline_tests'])


def test_topic_types_and_all_endpoint_owners_are_explicit():
    contract = _contract()
    topics = contract['topics']
    names = [topic['name'] for topic in topics]
    owners = {
        node['name']
        for group in ('planned_nodes', 'external_nodes')
        for node in contract[group]
    }

    assert len(names) == len(set(names))
    for topic in topics:
        assert topic['type'] in VALID_ROS1_TYPES
        assert '(' not in topic['type']
        assert topic['encoding']
        assert topic['profiles']
        assert _endpoint_nodes(topic) <= owners
        for publisher in topic['publishers']:
            assert publisher['queue_size'] >= 1
            assert isinstance(publisher['latch'], bool)
        for subscriber in topic['subscribers']:
            assert subscriber['queue_size'] >= 1
            assert isinstance(subscriber['tcp_nodelay'], bool)


def test_mock_profile_resolves_ordinary_outputs_and_production_is_empty():
    contract = _contract()
    topics = _topics()
    profile = contract['profiles']['offline_text_mock']

    for production, mock_name in profile['ordinary_remaps'].items():
        production_topic = topics[production]
        mock_topic = topics[mock_name]
        assert production_topic['publishers'] == []
        assert production_topic['subscribers'] == []
        assert mock_topic['publishers'] == [{
            'node': '/voice_dialogue',
            'queue_size': 1,
            'latch': False,
        }]
        assert mock_topic['subscribers'] == []
        assert 'mock_sink' in mock_topic['boundary']

    assert topics['/voice/mock_input_enable']['publishers'][0]['node'] == (
        '/voice_mock_topology_guard')
    assert 'continuous_guard' in (
        topics['/voice/mock_topology_status']['boundary'])


def test_stop_request_bypasses_dialogue_and_ack_is_external_observation():
    topics = _topics()
    request = topics['/voice/priority_stop_request']
    ack = topics['/voice/stop_ack']

    assert request['publishers'][0]['node'] == '/voice_priority_stop'
    assert request['subscribers'] == [{
        'node': '/cleanup_ros1_stop_gate',
        'queue_size': 1,
        'tcp_nodelay': True,
    }]
    assert '/voice_dialogue' not in _endpoint_nodes(request)
    assert ack['publishers'][0]['node'] == '/cleanup_ros1_stop_gate'
    assert ack['subscribers'][0]['node'] == '/voice_priority_stop'
    assert '/voice_dialogue' not in _endpoint_nodes(ack)


def test_stop_retry_ack_and_concurrency_contracts_are_fail_closed():
    contract = _contract()
    stop = contract['stop_delivery_contract']
    concurrency = contract['concurrency_contract']

    assert stop['first_publish_waits_for_agent'] is False
    assert stop['repeat_count'] == 3
    assert stop['repeat_attempts_are_transport_retries'] is True
    assert stop['downstream_side_effects_max_once_per_event'] is True
    assert stop['ack_correlation'] == ['event_id', 'process_instance_id']
    assert stop['identity_fields_are_inside_json'] is True
    assert stop['stop_request_schema_version'] == 3
    assert stop['stop_ack_schema_version'] == 2
    assert stop['ack_source_allowlist'] == ['cleanup_ros1_stop_gate']
    assert stop['ack_source_allowlist_locked'] is True
    assert stop['ack_future_wall_tolerance_sec'] == 5.0
    assert stop['ack_future_wall_tolerance_locked'] is True
    assert stop['ack_freshness_clock'] == 'receiver_local_monotonic_deadline'
    assert 'future_wall_time_beyond_tolerance' in stop['reject_ack']
    assert stop['dialogue_failure_must_not_block_stop_consumer'] is True
    assert concurrency['stop_epoch_barrier'] is True
    assert concurrency[
        'confirmation_commit_requires_unchanged_stop_epoch'] is True


def test_no_command_or_event_topic_is_latched():
    topics = _topics()
    allowed_latched = {
        '/voice/mock_input_enable',
        '/cleanup/status',
        '/voice/asr_status',
        '/voice/status',
        '/voice/stop_status',
        '/voice/tts_status',
        '/voice/mock_topology_status',
    }

    for topic in topics.values():
        for publisher in topic['publishers']:
            if publisher['latch']:
                assert topic['name'] in allowed_latched
    assert topics['/voice/intent']['publishers'][0]['latch'] is False
    assert topics['/voice/priority_stop_request'][
        'publishers'][0]['latch'] is False


def test_diagnostic_topics_have_complete_ros1_transport_contracts():
    topics = _topics()
    diagnostics = {
        '/voice/asr_status',
        '/voice/status',
        '/voice/stop_status',
        '/voice/tts_status',
        '/voice/mock_topology_status',
    }

    for name in diagnostics:
        topic = topics[name]
        assert topic['type'] == 'std_msgs/String'
        assert topic['encoding'].startswith('strict_json_')
        assert len(topic['publishers']) == 1
        assert topic['publishers'][0]['queue_size'] == 1
        assert topic['publishers'][0]['latch'] is True


def test_voice_owns_no_services_actions_motion_or_move_base_client():
    contract = _contract()
    rendered = json.dumps(contract, ensure_ascii=False).casefold()
    ownership = contract['external_action_ownership']['/move_base']
    stop_gate = next(
        node for node in contract['external_nodes']
        if node['name'] == '/cleanup_ros1_stop_gate')
    cancel_relay = stop_gate['required_navigation_cancel_relay']

    assert contract['services'] == []
    assert contract['actions'] == []
    assert contract['external_action_ownership']['voice_action_clients'] == []
    assert contract['external_action_ownership']['voice_action_servers'] == []
    assert ownership['server_node'] == '/move_base'
    assert ownership['only_allowed_client'] == (
        '/cleanup_ros1_navigation_adapter')
    assert ownership['voice_clients'] == []
    assert stop_gate['allowed_action_clients'] == []
    assert cancel_relay['target_node'] == (
        '/cleanup_ros1_navigation_adapter')
    assert cancel_relay['interface_status'] == 'NOT_IMPLEMENTED'
    assert cancel_relay['identity_fields'] == [
        'process_instance_id', 'event_id']
    assert cancel_relay['side_effects_max_once_per_event'] is True
    assert cancel_relay[
        'transport_retries_do_not_repeat_side_effect'] is True
    assert 'cmd_vel' not in rendered
    assert 'geometry_msgs/twist' not in rendered
    assert '/dev/' not in rendered


def test_minimal_adapter_is_ros_free_zero_publish_and_source_bound():
    contract = _contract()
    adapter = contract['adapter_implementation']
    core_path = PACKAGE_ROOT / adapter['core_path']
    wrapper_path = PACKAGE_ROOT / adapter['wrapper_path']
    core_source = core_path.read_text(encoding='utf-8')
    wrapper_source = wrapper_path.read_text(encoding='utf-8')

    assert core_path.is_file()
    assert wrapper_path.is_file()
    assert adapter['core_status'] == 'IMPLEMENTED_ROS_FREE'
    assert adapter['wrapper_status'] == (
        'CATKIN_TARGET_BUILD_VALIDATED_OFFLINE_ONLY')
    assert adapter['catkin_preview_package_path'] == (
        'ros1_overlay_src/limo_cleanup_ros1_voice')
    assert adapter['catkin_preview_default_enabled'] is False
    assert adapter['catkin_preview_build_validated'] is True
    assert adapter['catkin_preview_live_ros_validated'] is False
    assert adapter['default_profile'] == 'offline_text_mock'
    assert adapter['require_wake_word_locked_true'] is True
    assert adapter['canonical_wake_word'] == '小莫小莫'
    assert adapter['asr_boundary_wake_aliases'] == ['小沫小沫']
    assert adapter['asr_aliases_are_user_facing_commands'] is False
    assert adapter['asr_alias_match_policy'] == (
        'complete_command_prefix_only')
    assert adapter['production_outputs_enabled'] is False
    assert adapter['actual_publish_count'] == 0
    assert adapter['publishers'] == []
    assert adapter['services'] == []
    assert adapter['actions'] == []
    assert adapter['explicit_lock'] is True
    assert adapter['stop_epoch_barrier'] is True
    assert adapter['ack_source_allowlist'] == ['cleanup_ros1_stop_gate']
    assert adapter['ack_source_allowlist_locked'] is True
    assert adapter['ack_future_wall_tolerance_sec'] == 5.0
    assert adapter['ack_future_wall_tolerance_locked'] is True
    assert adapter['process_instance_id_is_inside_json'] is True
    assert adapter['process_instance_id_uses_public_wire_validator'] is True
    assert adapter['stop_request_schema_version'] == 3
    assert adapter['stop_ack_schema_version'] == 2
    audio = adapter['audio_input_boundary']
    assert audio == {
        'status': 'IMPLEMENTED_PLAN_ONLY_NO_EXECUTION',
        'capture_device': 'hw:0,0',
        'sample_format': 'S16_LE',
        'native_sample_rate_hz': 48000,
        'native_channels': 2,
        'asr_sample_rate_hz': 16000,
        'asr_channels': 1,
        'selected_channel': 1,
        'max_capture_duration_sec': 10,
        'conversion_tool': 'sox',
        'online_plughw_downmix_allowed': False,
        'microphone_opened_by_adapter': False,
        'actual_process_count': 0,
        'actual_publish_count': 0,
        'live_ros_graph_used': False,
        'field_runtime_ready': False,
    }
    assert 'import rospy' not in core_source
    assert 'rospy.Publisher' not in wrapper_source
    assert 'cmd_vel' not in (core_source + wrapper_source).casefold()
    actual_source_hashes = {
        'core': hashlib.sha256(core_path.read_bytes()).hexdigest(),
        'wrapper': hashlib.sha256(wrapper_path.read_bytes()).hexdigest(),
        'voice_contract': hashlib.sha256((
            PACKAGE_ROOT / 'limo_cleanup_voice' / 'voice_contract.py'
        ).read_bytes()).hexdigest(),
        'audio_input': hashlib.sha256((
            PACKAGE_ROOT / 'limo_cleanup_voice' / 'ros1_audio_input.py'
        ).read_bytes()).hexdigest(),
    }
    assert adapter['source_sha256'] == actual_source_hashes

    preview_root = (
        PACKAGE_ROOT.parents[1]
        / 'ros1_overlay_src' / 'limo_cleanup_ros1_voice')
    actual_preview_hashes = {
        'package_xml': hashlib.sha256((
            preview_root / 'package.xml').read_bytes()).hexdigest(),
        'cmake': hashlib.sha256((
            preview_root / 'CMakeLists.txt').read_bytes()).hexdigest(),
        'setup': hashlib.sha256((
            preview_root / 'setup.py').read_bytes()).hexdigest(),
        'entrypoint': hashlib.sha256((
            preview_root / 'scripts' / 'voice_ros1_noetic_adapter.py'
        ).read_bytes()).hexdigest(),
        'launch': hashlib.sha256((
            preview_root / 'launch' / 'voice_offline_mock.launch'
        ).read_bytes()).hexdigest(),
        'source_contract_test': hashlib.sha256((
            preview_root / 'test' / 'test_ros1_voice_package_contract.py'
        ).read_bytes()).hexdigest(),
    }
    assert adapter['catkin_preview_source_sha256'] == actual_preview_hashes
    target_evidence = adapter['catkin_target_build_evidence']
    workspace_root = PACKAGE_ROOT.parents[2]
    evidence_path = workspace_root / target_evidence['path']
    collector_path = workspace_root / target_evidence['collector_path']
    evidence = json.loads(evidence_path.read_text(encoding='utf-8'))
    assert hashlib.sha256(evidence_path.read_bytes()).hexdigest() == (
        target_evidence['sha256'])
    current_collector_sha256 = hashlib.sha256(
        collector_path.read_bytes()).hexdigest()
    assert evidence['collector']['sha256'] == (
        target_evidence['collector_sha256'])
    assert current_collector_sha256 == (
        target_evidence['current_collector_sha256'])
    assert current_collector_sha256 == target_evidence['collector_sha256']
    assert target_evidence['historical_build_passed'] is True
    assert target_evidence['current_source_identity_exact'] is True
    assert target_evidence['current_collector_identity_exact'] is True
    assert evidence['collector']['sha256'] == (
        target_evidence['collector_sha256'])
    assert evidence['platform']['machine'] == 'aarch64'
    assert evidence['passed'] is True
    assert evidence['actual_publish_count'] == 0
    assert evidence['isolation']['live_ros_graph_used'] is False
    assert evidence['field_runtime_ready'] is False


def test_asr_accuracy_regression_and_ros1_block_are_both_hard_gates():
    contract = _contract()
    asr = contract['asr_evidence_contract']

    assert asr['recommended_current_mode'] == (
        'unrestricted_first_complete_endpoint')
    assert asr['legacy_default_use_restricted_grammar'] is False
    assert asr[
        'restricted_grammar_requires_explicit_boolean_true'] is True
    assert asr['small_cn_first_complete_real_wav_exact'] == '4/4'
    assert asr['small_cn_first_complete_micro_cer'] == 0.0
    assert asr['small_cn_first_complete_independent_runs'] == 2
    assert asr['small_cn_first_complete_field_default'] is False
    assert asr['frozen_all_endpoints_baseline_exact'] == '2/4'
    assert asr['frozen_all_endpoints_baseline_micro_cer'] == 0.357143
    actual_legacy_hashes = {
        'voice_asr_node': hashlib.sha256((
            PACKAGE_ROOT / 'limo_cleanup_voice' / 'voice_asr_node.py'
        ).read_bytes()).hexdigest(),
        'voice_dialogue_config': hashlib.sha256((
            PACKAGE_ROOT / 'config' / 'voice_dialogue.yaml'
        ).read_bytes()).hexdigest(),
    }
    assert asr['legacy_artifact_sha256'] == actual_legacy_hashes
    assert asr['bottle_restricted_grammar_status'] == (
        'BLOCKED_ACCURACY_REGRESSION')
    assert asr['existing_bottle_recording_ground_truth'] == '捡矿泉水瓶'
    assert asr['spoken_bottle_only_ground_truth_available'] is False
    assert asr['canonical_alias_preserved'] is True
    assert asr['full_cn_candidate_real_voice_exact'] == '29/37'
    assert asr['full_cn_candidate_micro_cer'] == 0.069498
    assert asr['full_cn_candidate_semantic_pass'] == '37/37'
    assert asr['full_cn_candidate_public_negative_pass'] == '80/80'
    assert asr['full_cn_candidate_noise_negative_pass'] == '14/14'
    assert asr['full_cn_candidate_dynamic_grammar_supported'] is False
    assert asr['full_cn_candidate_field_default'] is False
    assert asr['safety_pass_cannot_override_accuracy_failure'] is True
    assert contract['field_delivery_ready'] is False


def test_stop_endpoint_candidate_is_hash_bound_and_offline_only():
    contract = _contract()
    candidate = contract['asr_evidence_contract']['stop_endpoint_candidate']
    workspace_root = PACKAGE_ROOT.parents[2]

    assert candidate['status'] == (
        'OFFLINE_SAFE_ENDPOINT_FALLBACK_PASS_FAST_PATH_BLOCKED')
    assert candidate['isolated_from_general_asr'] is True
    assert candidate['general_asr_mode_unchanged'] is True
    assert candidate['field_default'] is False
    assert candidate['live_ros_validated'] is False
    assert candidate['real_human_stop_detected'] == '4/4'
    assert candidate['real_human_negative_false_triggers'] == '0/80'
    assert candidate['partial_stop_detected'] == '0/4'
    assert candidate['partial_negative_false_triggers'] == '1/80'
    assert candidate['endpoint_after_word_ms_p95_nearest_rank'] == 430.0
    assert candidate['actual_publish_count'] == 0
    assert candidate['production_publish_count'] == 0
    assert candidate['software_timing_is_robot_end_to_end_evidence'] is False
    assert candidate['ros_free_ingress_status'] == (
        'IMPLEMENTED_NOT_CATKIN_INSTALLED_NOT_ROS_OWNER')
    assert candidate['ros_free_ingress_endpoint_only'] is True
    assert candidate['ros_free_ingress_rejects_partial'] is True
    assert candidate['ros_free_ingress_preserves_same_stream_context'] is True
    assert candidate[
        'ros_free_ingress_ordinary_text_never_enters_dialogue'] is True
    ingress_path = (
        workspace_root / candidate['ros_free_ingress']['path']).resolve()
    ingress_source = ingress_path.read_text(encoding='utf-8').casefold()
    assert 'import rospy' not in ingress_source
    assert 'rospy.publisher' not in ingress_source
    assert 'cmd_vel' not in ingress_source
    assert 'geometry_msgs' not in ingress_source
    assert '/dev/' not in ingress_source

    loaded = {}
    for name in (
            'candidate_manifest', 'streaming_report', 'runner',
            'model_config', 'ros_free_ingress'):
        identity = candidate[name]
        path = (workspace_root / identity['path']).resolve(strict=True)
        assert hashlib.sha256(path.read_bytes()).hexdigest() == (
            identity['sha256'])
        if path.suffix == '.json':
            loaded[name] = json.loads(path.read_text(encoding='utf-8'))

    report = loaded['streaming_report']
    summary = report['summaries']['stop_disambiguation_grammar']['endpoint']
    assert report['status'] == 'BLOCKED'
    assert report['delivery_ready'] is False
    assert summary['positive_detected_count'] == 4
    assert summary['positive_case_count'] == 4
    assert summary['negative_false_trigger_count'] == 0
    assert summary['negative_case_count'] == 80
    assert summary['after_word_ms_p95_nearest_rank'] == 430.0
    assert report['passing_candidates'] == []
    assert report['safety']['actual_publish_count'] == 0


def test_actual_runtime_files_remain_truthfully_legacy_ros2():
    package_xml = (PACKAGE_ROOT / 'package.xml').read_text(encoding='utf-8')
    launch_source = (
        PACKAGE_ROOT / 'launch' / 'voice_dialogue.launch.py'
    ).read_text(encoding='utf-8')
    aggregate_source = (
        PACKAGE_ROOT / 'limo_cleanup_voice' / 'voice_regression_aggregate.py'
    ).read_text(encoding='utf-8')
    smoke_source = (
        PACKAGE_ROOT / 'scripts' / 'smoke_test_voice_text.sh'
    ).read_text(encoding='utf-8')

    assert 'rclpy' in package_xml
    assert 'ament_python' in package_xml
    assert 'launch_ros' in launch_source
    assert '/opt/ros/humble' in aggregate_source
    assert 'LIMO_ALLOW_LEGACY_ROS2_OFFLINE' in smoke_source
    assert 'BLOCKED_LEGACY_ROS2_OFFLINE_ONLY' in smoke_source

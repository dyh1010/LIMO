"""Tests for the hashed final Voice V2 delivery evidence gate."""

import json
import shutil
from pathlib import Path

import pytest

from limo_cleanup_voice.voice_delivery_evidence import (
    BASELINE,
    BOTTLE_ONLY,
    evaluate_final_delivery,
    main,
    sha256_file,
)


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PACKAGE_ROOT.parents[2]
REAL_MANIFEST = (
    WORKSPACE_ROOT
    / 'voice_model_lab_20260814'
    / 'final_voice_delivery_manifest_20260814.json'
)
CAPTURED_MANIFEST = (
    WORKSPACE_ROOT
    / 'voice_model_lab_20260814'
    / 'final_voice_delivery_manifest_20260821_v1.json'
)


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8',
    )


def _sandbox(tmp_path):
    manifest = json.loads(REAL_MANIFEST.read_text(encoding='utf-8'))
    workspace = tmp_path / 'workspace'
    paths = {}
    for name, item in manifest['inputs'].items():
        source = WORKSPACE_ROOT / item['path']
        destination = workspace / item['path']
        destination.parent.mkdir(parents=True, exist_ok=True)
        if name == 'ros1_private_mock_graph_report':
            for sidecar in source.parent.iterdir():
                if sidecar.is_file():
                    shutil.copy2(sidecar, destination.parent / sidecar.name)
        shutil.copy2(source, destination)
        paths[name] = destination
    manifest_path = (
        workspace
        / 'voice_model_lab_20260814'
        / 'final_voice_delivery_manifest_test.json'
    )
    _write_json(manifest_path, manifest)
    return manifest_path, manifest, paths


def _refresh_input_hash(manifest, name, path):
    manifest['inputs'][name]['sha256'] = sha256_file(path)


def manifest_hash(name):
    manifest = json.loads(REAL_MANIFEST.read_text(encoding='utf-8'))
    return manifest['inputs'][name]['sha256']


def test_real_final_evidence_is_blocked_by_accuracy_and_ros1():
    report = evaluate_final_delivery(REAL_MANIFEST)

    assert report['status'] == 'BLOCKED'
    assert report['delivery_ready'] is False
    assert report['overall_pass'] is False
    assert report['selected_candidate'] == (
        'unrestricted_first_complete_endpoint')
    assert report['gates']['artifact_integrity_and_schema'] is True
    assert report['inputs']['final_evidence_runner']['sha256'] == (
        manifest_hash('final_evidence_runner'))
    assert report['gates']['model_intake'] is True
    assert report['gates']['mock_safety_state_machine'] is True
    assert report['gates']['field_negative_prompt_plan_review'] is True
    assert report['gates']['field_negative_human_recordings_ready'] is False
    assert report['gates']['candidate_semantic_safety'] is True
    assert report['gates'][
        'candidate_not_regressed_vs_unrestricted'] is True
    assert report['gates']['candidate_absolute_accuracy'] is True
    assert report['gates'][
        'critical_mineral_water_bottle_phrase_exact'] is True
    assert report['gates']['selected_candidate_allowed'] is True
    assert report['gates'][
        'experimental_endpoint_candidate_reproducible'] is True
    assert report['gates'][
        'stop_endpoint_offline_fallback_evidence'] is True
    assert report['gates']['human_voice_37_semantic_safety'] is True
    assert report['gates']['ros1_private_mock_graph_acceptance'] is True
    assert report['gates']['ros1_noetic_target_offline_build'] is True
    endpoint = report['experimental_endpoint_candidate']
    assert endpoint['candidate'] == 'unrestricted_first_complete_endpoint'
    assert endpoint['independent_run_count'] == 2
    assert endpoint['exact_match_count'] == 4
    assert endpoint['case_count'] == 4
    assert endpoint['micro_cer'] == 0.0
    assert endpoint['semantic_safety_pass_count'] == 4
    assert endpoint['actual_publish_count'] == 0
    assert endpoint['field_delivery_promoted'] is False
    assert endpoint['frozen_all_endpoints_baseline_preserved'] is True
    stop_endpoint = report['stop_endpoint']
    assert stop_endpoint['passed'] is True
    assert stop_endpoint['real_human_stop_detected'] == '4/4'
    assert stop_endpoint[
        'real_human_negative_false_triggers'] == '0/80'
    assert stop_endpoint['endpoint_after_word_ms_p50'] == 375.0
    assert stop_endpoint[
        'endpoint_after_word_ms_p95_nearest_rank'] == 430.0
    assert stop_endpoint['endpoint_after_word_ms_max'] == 430.0
    assert stop_endpoint['partial_stop_detected'] == '0/4'
    assert stop_endpoint['partial_negative_false_triggers'] == '1/80'
    assert stop_endpoint['partial_fast_path_promoted'] is False
    assert stop_endpoint['field_default'] is False
    assert stop_endpoint['live_ros_validated'] is False
    assert stop_endpoint['actual_publish_count'] == 0
    assert stop_endpoint[
        'software_timing_is_robot_end_to_end_evidence'] is False
    human = report['human_voice_37']
    assert human['passed'] is True
    assert human['case_count'] == 37
    assert human['exact_match_count'] == 28
    assert human['micro_cer'] == 0.081081
    assert human['semantic_pass_count'] == 37
    assert human['natural_stop_exact_match_count'] == 6
    assert human['natural_stop_case_count'] == 6
    assert human['actual_publish_count'] == 0
    assert human['production_publish_count'] == 0
    assert human['field_delivery_promoted'] is False
    graph = report['ros1_private_mock_graph']
    assert graph == {
        'passed': True,
        'master_uri': 'http://127.0.0.1:11389',
        'node_count': 2,
        'topic_count': 3,
        'actual_publish_count': 0,
        'production_publish_count': 0,
        'hardware_used': False,
        'field_runtime_ready': False,
    }
    assert report['gates']['ros1_runtime_contract_schema'] is True
    assert report['gates']['ros1_field_runtime_ready'] is False
    assert report['mock_safety']['mock_only'] is True
    assert report['mock_safety']['semantic_sequence']['passed'] is True
    assert report['mock_safety']['semantic_sequence']['step_count'] == 9
    assert report['mock_safety']['semantic_sequence'][
        'actual_publish_count'] == 0
    assert report['mock_safety'][
        'is_live_stop_end_to_end_evidence'] is False
    assert report['field_negative']['plan_passed'] is True
    assert report['field_negative']['human_corpus_ready'] is False
    assert report['field_negative']['direct_adapter_review_passed'] is True
    assert report['field_negative']['prompt_mock_pass_count'] == 80
    assert report['field_negative']['prompt_mock_fail_count'] == 0
    assert report['field_negative']['actual_publish_count'] == 0
    assert report['field_negative']['production_publish_count'] == 0
    assert report['field_negative']['human_audio_files_inspected'] == 27
    assert report['field_negative']['asr_observation_count'] == 27
    assert report['field_negative']['prompt_is_ground_truth'] is False
    assert report['field_negative']['is_live_or_field_evidence'] is False
    assert report['mock_safety']['source_sha256']['command_parser'] == (
        manifest_hash('command_parser_source'))
    assert report['ros1_runtime']['implementation_status'] == (
        'BLOCKED_ROS1_ADAPTER_OFFLINE_ONLY')
    assert report['ros1_runtime']['actual_publish_count'] == 0
    assert report['ros1_runtime']['adapter_source_sha256'] == {
        'core': manifest_hash('ros1_adapter_core'),
        'wrapper': manifest_hash('ros1_adapter_wrapper'),
        'voice_contract': manifest_hash('voice_contract_source'),
        'audio_input': manifest_hash('ros1_audio_input'),
    }
    assert report['ros1_runtime']['legacy_asr_artifact_sha256'] == {
        'voice_asr_node': manifest_hash('legacy_asr_source'),
        'voice_dialogue_config': manifest_hash('legacy_asr_config'),
    }
    assert report['ros1_runtime']['catkin_preview_source_sha256'] == {
        'package_xml': manifest_hash('ros1_catkin_package_xml'),
        'cmake': manifest_hash('ros1_catkin_cmake'),
        'setup': manifest_hash('ros1_catkin_setup'),
        'entrypoint': manifest_hash('ros1_catkin_entrypoint'),
        'launch': manifest_hash('ros1_catkin_launch'),
        'source_contract_test': manifest_hash(
            'ros1_catkin_contract_test'),
    }
    assert report['ros1_runtime'][
        'catkin_preview_build_validated'] is True
    target = report['ros1_noetic_target_build']
    assert target['passed'] is True
    assert target['source_identity_current'] is True
    assert target['blocking_reasons'] == []
    assert target['target_architecture'] == 'aarch64'
    assert target['source_contract_passed'] == '4/4'
    assert target['actual_publish_count'] == 0
    assert target['live_ros_graph_used'] is False
    assert target['hardware_used'] is False
    assert target['field_runtime_ready'] is False


def test_complete_human_negative_corpus_passes_offline_gate_only():
    report = evaluate_final_delivery(CAPTURED_MANIFEST)

    assert report['status'] == 'BLOCKED'
    assert report['delivery_ready'] is False
    assert report['overall_pass'] is False
    assert report['gates']['field_negative_prompt_plan_review'] is True
    assert report['gates']['field_negative_human_recordings_ready'] is True
    assert report['field_negative']['plan_passed'] is True
    assert report['field_negative']['human_corpus_ready'] is True
    assert report['field_negative']['delivery_promoted'] is False
    assert report['field_negative']['human_audio_files_inspected'] == 80
    assert report['field_negative']['asr_observation_count'] == 80
    assert report['field_negative']['actual_publish_count'] == 0
    assert report['field_negative']['production_publish_count'] == 0
    assert report['gates']['ros1_field_runtime_ready'] is False
    assert report['blocking_issues'] == [
        'ROS1/Noetic adapter remains offline-only and field BLOCKED']


def test_target_collector_binds_audio_input_without_capture_execution():
    manifest = json.loads(REAL_MANIFEST.read_text(encoding='utf-8'))
    relative = manifest['inputs'][
        'ros1_noetic_target_build_collector']['path']
    source = (WORKSPACE_ROOT / relative).read_text(encoding='utf-8')

    assert "/ros1_audio_input.py'" in source
    assert 'plan_audio_input' in source
    assert "'audio_input_plan_exact'" in source
    assert "'actual_process_count': audio_plan.actual_process_count" in source
    assert "audio_plan.capture_argv" in source
    assert "audio_plan.conversion_argv" in source
    assert "_run(audio_plan.capture_argv" not in source
    assert "_run(audio_plan.conversion_argv" not in source


def test_bottle_only_candidate_is_rejected_by_real_wav_regression(tmp_path):
    manifest_path, manifest, _ = _sandbox(tmp_path)
    manifest['selected_candidate'] = BOTTLE_ONLY
    _write_json(manifest_path, manifest)

    report = evaluate_final_delivery(manifest_path)

    assert report['status'] == 'BLOCKED'
    assert report['gates'][
        'candidate_not_regressed_vs_unrestricted'] is False
    assert report['gates']['candidate_absolute_accuracy'] is False
    assert report['gates'][
        'critical_mineral_water_bottle_phrase_exact'] is False
    assert report['gates']['selected_candidate_allowed'] is False


def test_human_voice_stop_semantic_tamper_fails_closed(tmp_path):
    manifest_path, manifest, paths = _sandbox(tmp_path)
    report_path = paths['user_voice_37_evaluation']
    human = json.loads(report_path.read_text(encoding='utf-8'))
    stop_case = next(
        item for item in human['cases'] if item['category'] == 'stop')
    stop_case['variants'][
        'unrestricted_first_complete_endpoint']['semantics'][
            'priority_stop_detected'] = False
    _write_json(report_path, human)
    _refresh_input_hash(manifest, 'user_voice_37_evaluation', report_path)
    _write_json(manifest_path, manifest)

    report = evaluate_final_delivery(manifest_path)

    assert report['status'] == 'BLOCKED'
    assert report['gates'] == {'artifact_integrity_and_schema': False}
    assert 'natural STOP case mismatch' in report['blocking_issues'][0]


def test_private_mock_graph_sidecar_drift_fails_closed(tmp_path):
    manifest_path, manifest, paths = _sandbox(tmp_path)
    topics_path = paths['ros1_private_mock_graph_report'].parent \
        / 'topics_after.txt'
    topics_path.write_text(
        topics_path.read_text(encoding='utf-8') + '/cmd_vel\n',
        encoding='utf-8',
    )
    _write_json(manifest_path, manifest)

    report = evaluate_final_delivery(manifest_path)

    assert report['status'] == 'BLOCKED'
    assert report['gates'] == {'artifact_integrity_and_schema': False}
    assert 'sidecar mismatch: topics_after.txt' in (
        report['blocking_issues'][0])


def test_bad_required_artifact_hash_fails_before_evidence_use(tmp_path):
    manifest_path, manifest, _ = _sandbox(tmp_path)
    manifest['inputs']['ab_ground_truth_evaluation']['sha256'] = '0' * 64
    _write_json(manifest_path, manifest)

    report = evaluate_final_delivery(manifest_path)

    assert report['gates'] == {'artifact_integrity_and_schema': False}
    assert report['delivery_ready'] is False
    assert 'SHA-256 mismatch' in report['blocking_issues'][0]


def test_missing_required_ab_artifact_fails_closed(tmp_path):
    manifest_path, manifest, _ = _sandbox(tmp_path)
    manifest['inputs']['ab_ground_truth_evaluation']['path'] = (
        'voice_model_lab_20260814/reports/missing_ab.json')
    _write_json(manifest_path, manifest)

    report = evaluate_final_delivery(manifest_path)

    assert report['gates'] == {'artifact_integrity_and_schema': False}
    assert 'input is missing' in report['blocking_issues'][0]


def test_missing_noetic_target_build_artifact_fails_closed(tmp_path):
    manifest_path, manifest, _ = _sandbox(tmp_path)
    manifest['inputs']['ros1_noetic_target_build_evidence']['path'] = (
        'voice_model_lab_20260814/reports/missing_target_build.json')
    _write_json(manifest_path, manifest)

    report = evaluate_final_delivery(manifest_path)

    assert report['gates'] == {'artifact_integrity_and_schema': False}
    assert 'input is missing' in report['blocking_issues'][0]


def test_noetic_target_build_cannot_claim_live_ros_or_field(tmp_path):
    manifest_path, manifest, paths = _sandbox(tmp_path)
    target_path = paths['ros1_noetic_target_build_evidence']
    target = json.loads(target_path.read_text(encoding='utf-8'))
    target['isolation']['live_ros_graph_used'] = True
    target['field_runtime_ready'] = True
    _write_json(target_path, target)
    _refresh_input_hash(
        manifest, 'ros1_noetic_target_build_evidence', target_path)
    _write_json(manifest_path, manifest)

    report = evaluate_final_delivery(manifest_path)

    assert report['gates'] == {'artifact_integrity_and_schema': False}
    assert 'isolation contract mismatch' in report['blocking_issues'][0]


def test_noetic_target_build_rejects_unexpected_package_count(tmp_path):
    manifest_path, manifest, paths = _sandbox(tmp_path)
    target_path = paths['ros1_noetic_target_build_evidence']
    target = json.loads(target_path.read_text(encoding='utf-8'))
    target['catkin_build']['output'] = target[
        'catkin_build']['output'].replace(
            'All 2 packages succeeded!', 'All 3 packages succeeded!')
    _write_json(target_path, target)
    _refresh_input_hash(
        manifest, 'ros1_noetic_target_build_evidence', target_path)
    _write_json(manifest_path, manifest)

    report = evaluate_final_delivery(manifest_path)

    assert report['gates'] == {'artifact_integrity_and_schema': False}
    assert 'Catkin build output is invalid' in report['blocking_issues'][0]


def test_mock_pass_cannot_substitute_for_real_ab_evidence(tmp_path):
    manifest_path, manifest, paths = _sandbox(tmp_path)
    mock_path = paths['mock_safety_acceptance']
    manifest['inputs']['ab_ground_truth_evaluation']['path'] = (
        manifest['inputs']['mock_safety_acceptance']['path'])
    manifest['inputs']['ab_ground_truth_evaluation']['sha256'] = (
        sha256_file(mock_path))
    _write_json(manifest_path, manifest)

    report = evaluate_final_delivery(manifest_path)

    assert report['gates'] == {'artifact_integrity_and_schema': False}
    assert 'A/B report status or mode is invalid' in (
        report['blocking_issues'][0])


def test_forged_filename_provenance_is_rejected(tmp_path):
    manifest_path, manifest, paths = _sandbox(tmp_path)
    ab_path = paths['ab_ground_truth_evaluation']
    ab_report = json.loads(ab_path.read_text(encoding='utf-8'))
    ab_report['ground_truth_provenance']['filename_inference_used'] = True
    _write_json(ab_path, ab_report)
    _refresh_input_hash(manifest, 'ab_ground_truth_evaluation', ab_path)
    _write_json(manifest_path, manifest)

    report = evaluate_final_delivery(manifest_path)

    assert report['gates'] == {'artifact_integrity_and_schema': False}
    assert 'provenance flag' in report['blocking_issues'][0]


def test_ab_summary_metric_drift_is_rejected(tmp_path):
    manifest_path, manifest, paths = _sandbox(tmp_path)
    ab_path = paths['ab_ground_truth_evaluation']
    ab_report = json.loads(ab_path.read_text(encoding='utf-8'))
    summary = ab_report['summary'][BASELINE]['accuracy_all_cases']
    summary['exact_match_count'] = 4
    summary['exact_match_rate'] = 1.0
    summary['micro_cer'] = 0.0
    summary['all_exact'] = True
    _write_json(ab_path, ab_report)
    _refresh_input_hash(manifest, 'ab_ground_truth_evaluation', ab_path)
    _write_json(manifest_path, manifest)

    report = evaluate_final_delivery(manifest_path)

    assert report['gates'] == {'artifact_integrity_and_schema': False}
    assert 'summary exact count drift' in report['blocking_issues'][0]


def test_missing_semantic_sequence_fails_closed(tmp_path):
    manifest_path, manifest, paths = _sandbox(tmp_path)
    mock_path = paths['mock_safety_acceptance']
    mock_report = json.loads(mock_path.read_text(encoding='utf-8'))
    mock_report.pop('semantic_sequence')
    _write_json(mock_path, mock_report)
    _refresh_input_hash(manifest, 'mock_safety_acceptance', mock_path)
    _write_json(manifest_path, manifest)

    report = evaluate_final_delivery(manifest_path)

    assert report['gates'] == {'artifact_integrity_and_schema': False}
    assert 'semantic_sequence is missing' in report['blocking_issues'][0]


def test_semantic_sequence_publish_attempt_fails_closed(tmp_path):
    manifest_path, manifest, paths = _sandbox(tmp_path)
    mock_path = paths['mock_safety_acceptance']
    mock_report = json.loads(mock_path.read_text(encoding='utf-8'))
    mock_report['semantic_sequence']['actual_publish_count'] = 1
    _write_json(mock_path, mock_report)
    _refresh_input_hash(manifest, 'mock_safety_acceptance', mock_path)
    _write_json(manifest_path, manifest)

    report = evaluate_final_delivery(manifest_path)

    assert report['status'] == 'BLOCKED'
    assert report['gates']['mock_safety_state_machine'] is False


def test_semantic_sequence_failed_step_fails_closed(tmp_path):
    manifest_path, manifest, paths = _sandbox(tmp_path)
    mock_path = paths['mock_safety_acceptance']
    mock_report = json.loads(mock_path.read_text(encoding='utf-8'))
    mock_report['semantic_sequence']['steps'][0]['passed'] = False
    _write_json(mock_path, mock_report)
    _refresh_input_hash(manifest, 'mock_safety_acceptance', mock_path)
    _write_json(manifest_path, manifest)

    report = evaluate_final_delivery(manifest_path)

    assert report['gates'] == {'artifact_integrity_and_schema': False}
    assert 'contains a failed step' in report['blocking_issues'][0]


def test_semantic_sequence_forged_provenance_fails_closed(tmp_path):
    manifest_path, manifest, paths = _sandbox(tmp_path)
    mock_path = paths['mock_safety_acceptance']
    mock_report = json.loads(mock_path.read_text(encoding='utf-8'))
    mock_report['semantic_sequence']['provenance'][
        'filename_inference_used'] = True
    _write_json(mock_path, mock_report)
    _refresh_input_hash(manifest, 'mock_safety_acceptance', mock_path)
    _write_json(manifest_path, manifest)

    report = evaluate_final_delivery(manifest_path)

    assert report['gates'] == {'artifact_integrity_and_schema': False}
    assert 'filename inference' in report['blocking_issues'][0]


def test_semantic_sequence_unbound_asr_hash_fails_closed(tmp_path):
    manifest_path, manifest, paths = _sandbox(tmp_path)
    mock_path = paths['mock_safety_acceptance']
    mock_report = json.loads(mock_path.read_text(encoding='utf-8'))
    mock_report['semantic_sequence']['provenance'][
        'asr_evidence_sha256'] = '0' * 64
    _write_json(mock_path, mock_report)
    _refresh_input_hash(manifest, 'mock_safety_acceptance', mock_path)
    _write_json(manifest_path, manifest)

    report = evaluate_final_delivery(manifest_path)

    assert report['gates'] == {'artifact_integrity_and_schema': False}
    assert 'ASR evidence hash is not bound' in report['blocking_issues'][0]


def test_mock_report_cannot_substitute_for_changed_semantic_source(tmp_path):
    manifest_path, manifest, paths = _sandbox(tmp_path)
    source_path = paths['semantic_agent_source']
    source_path.write_text(
        source_path.read_text(encoding='utf-8') + '\n# drift\n',
        encoding='utf-8',
    )
    _refresh_input_hash(manifest, 'semantic_agent_source', source_path)
    _write_json(manifest_path, manifest)

    report = evaluate_final_delivery(manifest_path)

    assert report['gates'] == {'artifact_integrity_and_schema': False}
    assert 'source hash is not bound' in report['blocking_issues'][0]


def test_mock_report_cannot_substitute_for_changed_parser_source(tmp_path):
    manifest_path, manifest, paths = _sandbox(tmp_path)
    source_path = paths['command_parser_source']
    source_path.write_text(
        source_path.read_text(encoding='utf-8') + '\n# drift\n',
        encoding='utf-8',
    )
    _refresh_input_hash(manifest, 'command_parser_source', source_path)
    _write_json(manifest_path, manifest)

    report = evaluate_final_delivery(manifest_path)

    assert report['gates'] == {'artifact_integrity_and_schema': False}
    assert 'command_parser' in report['blocking_issues'][0]
    assert 'source hash is not bound' in report['blocking_issues'][0]


def test_ros1_contract_cannot_substitute_for_changed_adapter_source(tmp_path):
    manifest_path, manifest, paths = _sandbox(tmp_path)
    source_path = paths['ros1_adapter_core']
    source_path.write_text(
        source_path.read_text(encoding='utf-8') + '\n# drift\n',
        encoding='utf-8',
    )
    _refresh_input_hash(manifest, 'ros1_adapter_core', source_path)
    _write_json(manifest_path, manifest)

    report = evaluate_final_delivery(manifest_path)

    assert report['status'] == 'BLOCKED'
    assert report['gates']['artifact_integrity_and_schema'] is True
    assert report['gates']['ros1_noetic_target_offline_build'] is False
    assert report['ros1_noetic_target_build'][
        'source_identity_current'] is False
    assert any(
        'Noetic target source identity mismatch' in reason
        for reason in report['ros1_noetic_target_build'][
            'blocking_reasons'])


def test_ros1_contract_cannot_substitute_for_changed_audio_input_source(
        tmp_path):
    manifest_path, manifest, paths = _sandbox(tmp_path)
    source_path = paths['ros1_audio_input']
    source_path.write_text(
        source_path.read_text(encoding='utf-8') + '\n# drift\n',
        encoding='utf-8',
    )
    _refresh_input_hash(manifest, 'ros1_audio_input', source_path)
    _write_json(manifest_path, manifest)

    report = evaluate_final_delivery(manifest_path)

    assert report['status'] == 'BLOCKED'
    assert report['gates']['artifact_integrity_and_schema'] is True
    assert report['gates']['ros1_runtime_contract_schema'] is False
    assert report['ros1_runtime']['runtime_ready'] is False


def test_ros1_contract_cannot_substitute_for_changed_legacy_asr_source(
        tmp_path):
    manifest_path, manifest, paths = _sandbox(tmp_path)
    source_path = paths['legacy_asr_source']
    source_path.write_text(
        source_path.read_text(encoding='utf-8') + '\n# drift\n',
        encoding='utf-8',
    )
    _refresh_input_hash(manifest, 'legacy_asr_source', source_path)
    _write_json(manifest_path, manifest)

    report = evaluate_final_delivery(manifest_path)

    assert report['status'] == 'BLOCKED'
    assert report['gates']['ros1_runtime_contract_schema'] is False
    assert report['ros1_runtime']['runtime_ready'] is False


def test_endpoint_candidate_transcript_drift_fails_closed(tmp_path):
    manifest_path, manifest, paths = _sandbox(tmp_path)
    report_path = paths['endpoint_candidate_run_1']
    candidate = json.loads(report_path.read_text(encoding='utf-8'))
    candidate['cases'][0]['variants'][
        'unrestricted_first_complete_endpoint']['transcript'] += '伪造'
    _write_json(report_path, candidate)
    _refresh_input_hash(manifest, 'endpoint_candidate_run_1', report_path)
    _write_json(manifest_path, manifest)

    report = evaluate_final_delivery(manifest_path)

    assert report['status'] == 'BLOCKED'
    assert report['gates'] == {'artifact_integrity_and_schema': False}
    assert 'endpoint candidate' in report['blocking_issues'][0]


def test_missing_or_bad_hash_field_negative_input_fails_integrity(tmp_path):
    mutations = (
        lambda manifest: manifest['inputs'].pop('field_negative_prompt_plan'),
        lambda manifest: manifest['inputs'][
            'field_negative_prompt_plan'].update({'sha256': '0' * 64}),
    )
    for mutate in mutations:
        manifest_path, manifest, _ = _sandbox(tmp_path)
        mutate(manifest)
        _write_json(manifest_path, manifest)

        report = evaluate_final_delivery(manifest_path)

        assert report['status'] == 'BLOCKED'
        assert report['delivery_ready'] is False
        assert report['gates'] == {'artifact_integrity_and_schema': False}
        tmp_path = tmp_path / 'next'


def test_nonzero_field_negative_mock_publish_is_a_hard_failure(tmp_path):
    manifest_path, manifest, paths = _sandbox(tmp_path)
    review_path = paths['field_negative_prompt_review']
    review = json.loads(review_path.read_text(encoding='utf-8'))
    review['counts']['actual_publish_count'] = 1
    review['cases'][0]['actual_publish_count'] = 1
    _write_json(review_path, review)
    _refresh_input_hash(manifest, 'field_negative_prompt_review', review_path)
    _write_json(manifest_path, manifest)

    report = evaluate_final_delivery(manifest_path)

    assert report['status'] == 'BLOCKED'
    assert report['delivery_ready'] is False
    assert report['gates']['field_negative_prompt_plan_review'] is False
    assert report['field_negative']['actual_publish_count'] == 1


def test_field_negative_asr_false_trigger_is_a_hard_failure(tmp_path):
    manifest_path, manifest, paths = _sandbox(tmp_path)
    observations_path = paths['field_negative_observations']
    observations = json.loads(
        observations_path.read_text(encoding='utf-8'))
    observations['cases'][0]['priority_stop_detected'] = True
    observations['cases'][0]['semantic_false_trigger'] = True
    observations['cases'][0]['adapter_state'] = 'priority_stop_internal'
    _write_json(observations_path, observations)
    _refresh_input_hash(
        manifest, 'field_negative_observations', observations_path)
    readiness_path = paths['field_negative_readiness']
    readiness = json.loads(readiness_path.read_text(encoding='utf-8'))
    readiness['inputs']['observations']['sha256'] = sha256_file(
        observations_path)
    _write_json(readiness_path, readiness)
    _refresh_input_hash(manifest, 'field_negative_readiness', readiness_path)
    _write_json(manifest_path, manifest)

    report = evaluate_final_delivery(manifest_path)

    assert report['status'] == 'BLOCKED'
    assert report['gates']['field_negative_prompt_plan_review'] is False
    assert report['field_negative']['human_corpus_ready'] is False


def test_prompt_plan_cannot_substitute_for_human_negative_audio(tmp_path):
    manifest_path, manifest, paths = _sandbox(tmp_path)
    readiness_path = paths['field_negative_readiness']
    readiness = json.loads(readiness_path.read_text(encoding='utf-8'))
    readiness['status'] = 'PASS'
    readiness['delivery_ready'] = True
    readiness['offline_corpus_gate_passed'] = True
    readiness['blocking_issues'] = []
    _write_json(readiness_path, readiness)
    _refresh_input_hash(manifest, 'field_negative_readiness', readiness_path)
    _write_json(manifest_path, manifest)

    report = evaluate_final_delivery(manifest_path)

    assert report['status'] == 'BLOCKED'
    assert report['delivery_ready'] is False
    assert report['gates']['field_negative_prompt_plan_review'] is False
    assert report['gates']['field_negative_human_recordings_ready'] is False
    assert report['field_negative']['delivery_promoted'] is False


def test_positive_command_in_negative_plan_fails_direct_adapter_review(
        tmp_path):
    manifest_path, manifest, paths = _sandbox(tmp_path)
    plan_path = paths['field_negative_prompt_plan']
    plan = json.loads(plan_path.read_text(encoding='utf-8'))
    plan['prompts'][0]['recording_prompt'] = '停下'
    _write_json(plan_path, plan)
    _refresh_input_hash(manifest, 'field_negative_prompt_plan', plan_path)
    review_path = paths['field_negative_prompt_review']
    review = json.loads(review_path.read_text(encoding='utf-8'))
    review['inputs']['prompt_plan']['sha256'] = sha256_file(plan_path)
    _write_json(review_path, review)
    _refresh_input_hash(manifest, 'field_negative_prompt_review', review_path)
    _write_json(manifest_path, manifest)

    report = evaluate_final_delivery(manifest_path)

    assert report['status'] == 'BLOCKED'
    assert report['delivery_ready'] is False
    assert report['gates']['field_negative_prompt_plan_review'] is False
    assert report['field_negative']['direct_adapter_review_passed'] is False


def test_changed_final_runner_copy_cannot_substitute_for_imported_source(
        tmp_path):
    manifest_path, manifest, paths = _sandbox(tmp_path)
    runner_path = paths['final_evidence_runner']
    runner_path.write_text(
        runner_path.read_text(encoding='utf-8') + '\n# drift\n',
        encoding='utf-8',
    )
    _refresh_input_hash(manifest, 'final_evidence_runner', runner_path)
    _write_json(manifest_path, manifest)

    report = evaluate_final_delivery(manifest_path)

    assert report['status'] == 'BLOCKED'
    assert report['gates'] == {'artifact_integrity_and_schema': False}
    assert 'runner hash does not match' in report['blocking_issues'][0]


def test_output_is_exclusive_even_when_current_delivery_is_blocked(tmp_path):
    output = tmp_path / 'final.json'

    assert main([
        '--manifest', str(REAL_MANIFEST),
        '--json-output', str(output),
    ]) == 1
    stored = json.loads(output.read_text(encoding='utf-8'))
    assert stored['status'] == 'BLOCKED'
    assert stored['delivery_ready'] is False
    with pytest.raises(SystemExit):
        main([
            '--manifest', str(REAL_MANIFEST),
            '--json-output', str(output),
        ])


def _rewrite_stop_report(manifest_path, manifest, paths, mutate):
    report_path = paths['stop_streaming_report']
    candidate_path = paths['stop_candidate_manifest']
    report = json.loads(report_path.read_text(encoding='utf-8'))
    mutate(report)
    _write_json(report_path, report)
    _refresh_input_hash(manifest, 'stop_streaming_report', report_path)
    candidate = json.loads(candidate_path.read_text(encoding='utf-8'))
    candidate['evidence']['streaming_report_sha256'] = (
        manifest['inputs']['stop_streaming_report']['sha256'])
    _write_json(candidate_path, candidate)
    _refresh_input_hash(manifest, 'stop_candidate_manifest', candidate_path)
    _write_json(manifest_path, manifest)


def test_missing_required_stop_streaming_report_fails_closed(tmp_path):
    manifest_path, manifest, paths = _sandbox(tmp_path)
    paths['stop_streaming_report'].unlink()
    _write_json(manifest_path, manifest)

    report = evaluate_final_delivery(manifest_path)

    assert report['gates'] == {'artifact_integrity_and_schema': False}
    assert 'stop_streaming_report input is missing' in (
        report['blocking_issues'][0])


def test_bad_stop_streaming_report_hash_fails_closed(tmp_path):
    manifest_path, manifest, _ = _sandbox(tmp_path)
    manifest['inputs']['stop_streaming_report']['sha256'] = '0' * 64
    _write_json(manifest_path, manifest)

    report = evaluate_final_delivery(manifest_path)

    assert report['gates'] == {'artifact_integrity_and_schema': False}
    assert 'stop_streaming_report SHA-256 mismatch' in (
        report['blocking_issues'][0])


def test_stop_endpoint_four_of_four_regression_fails_closed(tmp_path):
    manifest_path, manifest, paths = _sandbox(tmp_path)

    def mutate(report):
        positive = next(item for item in report['cases']
                        if item['expected_stop'] is True)
        positive['variants'][
            'stop_disambiguation_grammar']['endpoint_trigger'] = None

    _rewrite_stop_report(manifest_path, manifest, paths, mutate)
    report = evaluate_final_delivery(manifest_path)

    assert report['gates'] == {'artifact_integrity_and_schema': False}
    assert 'positive endpoint trigger is invalid' in report[
        'blocking_issues'][0]


def test_stop_endpoint_negative_false_trigger_fails_closed(tmp_path):
    manifest_path, manifest, paths = _sandbox(tmp_path)

    def mutate(report):
        negative = next(item for item in report['cases']
                        if item['expected_stop'] is False)
        negative['variants']['stop_disambiguation_grammar'][
            'endpoint_trigger'] = {
                'kind': 'endpoint', 'text': '停下',
                'audio_consumed_sec': 1.0,
                'recognized_last_word_end_sec': 0.8,
                'after_word_ms': 200.0, 'endpoint_kind': 'result',
                'prior_segment_count': 0,
            }

    _rewrite_stop_report(manifest_path, manifest, paths, mutate)
    report = evaluate_final_delivery(manifest_path)

    assert report['gates'] == {'artifact_integrity_and_schema': False}
    assert 'human negative false trigger' in report['blocking_issues'][0]


def test_stop_endpoint_latency_tamper_fails_closed(tmp_path):
    manifest_path, manifest, paths = _sandbox(tmp_path)

    def mutate(report):
        positive = next(item for item in report['cases']
                        if item['expected_stop'] is True)
        positive['variants']['stop_disambiguation_grammar'][
            'endpoint_trigger']['after_word_ms'] = 10.0

    _rewrite_stop_report(manifest_path, manifest, paths, mutate)
    report = evaluate_final_delivery(manifest_path)

    assert report['gates'] == {'artifact_integrity_and_schema': False}
    assert 'latency drift' in report['blocking_issues'][0]


def test_stop_partial_fast_path_promotion_fails_closed(tmp_path):
    manifest_path, manifest, paths = _sandbox(tmp_path)

    def mutate(report):
        report['passing_candidates'] = [
            {'variant': 'stop_disambiguation_grammar',
             'trigger_channel': 'partial'}]

    _rewrite_stop_report(manifest_path, manifest, paths, mutate)
    report = evaluate_final_delivery(manifest_path)

    assert report['gates'] == {'artifact_integrity_and_schema': False}
    assert 'fast path was promoted' in report['blocking_issues'][0]


def test_stop_candidate_live_or_field_promotion_fails_closed(tmp_path):
    manifest_path, manifest, paths = _sandbox(tmp_path)
    candidate_path = paths['stop_candidate_manifest']
    candidate = json.loads(candidate_path.read_text(encoding='utf-8'))
    candidate['field_delivery_ready'] = True
    candidate['safety']['live_ros_used'] = True
    _write_json(candidate_path, candidate)
    _refresh_input_hash(manifest, 'stop_candidate_manifest', candidate_path)
    _write_json(manifest_path, manifest)

    report = evaluate_final_delivery(manifest_path)

    assert report['gates'] == {'artifact_integrity_and_schema': False}
    assert 'delivery boundary mismatch' in report['blocking_issues'][0]


def test_mock_pass_cannot_substitute_for_stop_real_wav_report(tmp_path):
    manifest_path, manifest, paths = _sandbox(tmp_path)
    shutil.copy2(
        paths['mock_safety_acceptance'], paths['stop_streaming_report'])
    _refresh_input_hash(
        manifest, 'stop_streaming_report', paths['stop_streaming_report'])
    candidate_path = paths['stop_candidate_manifest']
    candidate = json.loads(candidate_path.read_text(encoding='utf-8'))
    candidate['evidence']['streaming_report_sha256'] = (
        manifest['inputs']['stop_streaming_report']['sha256'])
    _write_json(candidate_path, candidate)
    _refresh_input_hash(manifest, 'stop_candidate_manifest', candidate_path)
    _write_json(manifest_path, manifest)

    report = evaluate_final_delivery(manifest_path)

    assert report['gates'] == {'artifact_integrity_and_schema': False}
    assert 'STOP streaming report boundary mismatch' in (
        report['blocking_issues'][0])


def test_stop_negative_coverage_cannot_be_replaced_by_duplicates(tmp_path):
    manifest_path, manifest, paths = _sandbox(tmp_path)

    def mutate(report):
        negative = next(item for item in report['cases']
                        if item.get('coverage') == 'negated')
        negative['coverage'] = 'near_soundalike'

    _rewrite_stop_report(manifest_path, manifest, paths, mutate)
    report = evaluate_final_delivery(manifest_path)

    assert report['gates'] == {'artifact_integrity_and_schema': False}
    assert 'positive/negative split mismatch' in report[
        'blocking_issues'][0]


def test_ros1_contract_cannot_self_promote_to_field_ready(tmp_path):
    manifest_path, manifest, paths = _sandbox(tmp_path)
    contract_path = paths['ros1_runtime_contract']
    contract = json.loads(contract_path.read_text(encoding='utf-8'))
    contract['implementation_status'] = 'READY'
    contract['field_delivery_ready'] = True
    _write_json(contract_path, contract)
    _refresh_input_hash(manifest, 'ros1_runtime_contract', contract_path)
    _write_json(manifest_path, manifest)

    report = evaluate_final_delivery(manifest_path)

    assert report['status'] == 'BLOCKED'
    assert report['delivery_ready'] is False
    assert report['overall_pass'] is False
    assert report['gates']['artifact_integrity_and_schema'] is True
    assert report['gates']['ros1_runtime_contract_schema'] is False
    assert report['gates']['ros1_field_runtime_ready'] is False

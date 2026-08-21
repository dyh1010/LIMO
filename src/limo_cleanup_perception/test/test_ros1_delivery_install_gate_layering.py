"""Layered ROS1 delivery-gate regressions for offline release evidence."""

import importlib.util
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).parents[3]
SCRIPT = ROOT / 'scripts/run_perception_v2_frozen_regression.py'
SPEC = importlib.util.spec_from_file_location(
    'ros1_delivery_install_gate_layering_target', SCRIPT)
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)


FIELD_EVIDENCE_MISSING = 'ROS1_NOETIC_FIELD_INSTALL_EVIDENCE_MISSING'
BUILD_INSTALL_NOT_VERIFIED = 'ROS1_NOETIC_BUILD_INSTALL_NOT_VERIFIED'


def _source_audit():
    return {
        'gate_id': RUNNER.ROS1_FIELD_INSTALL_GATE_ID,
        'scope': 'field_delivery',
        'required_for_delivery': True,
        'pass': True,
        'complete_runtime': True,
        'architecture_blockers': [],
        'failures': [],
        'capability_matrix': {
            'diagnostic_only': True,
            'authoritative_for_runtime_admission': False,
            'implementation_validated': False,
        },
    }


def _canonical_admission():
    binding = {
        'binding_kind': 'canonical_project_overlay',
        'test_only': False,
        'canonical_source_root': (
            'ros1_overlay_src/limo_cleanup_ros1_perception'),
        'source_set_sha256': '1' * 64,
        'contract_sha256': '2' * 64,
        'binding_sha256': '3' * 64,
    }
    return {
        'gate_id': RUNNER.ROS1_CANONICAL_SOURCE_ADMISSION_GATE_ID,
        'validated_pass': True,
        'fresh_canonical_binding': binding,
        'manifest_identity': {
            'path': RUNNER.ROS1_CANONICAL_SOURCE_ADMISSION_RELATIVE,
            'size_bytes': 1,
            'sha256': '4' * 64,
        },
        'failures': [],
    }


def _build_not_verified():
    return {
        'evidence_path': str(ROOT / 'missing-noetic-build-evidence.json'),
        'evidence_identity': None,
        'valid_environment_blocker_evidence': False,
        'shell_entered': None,
        'build_started': None,
        'source_build_failure': None,
        'environment_blockers': [],
        'formal_state_observation': {
            'formal_four_scene_frame_denominator': 0,
            'formal_tf_pass': False,
            'formal_3d_pass': False,
        },
        'failures': ['ros1_build_attempt_evidence_missing'],
    }


def _run_layered_gate(install_validation, evidence_name):
    source_audit = _source_audit()

    class FakeReadiness:
        EXPECTED_MODEL_SHA256 = {}

        @staticmethod
        def audit_ros1_noetic_field_source_contract(workspace):
            assert Path(workspace).resolve() == ROOT.resolve()
            return source_audit

        @staticmethod
        def validate_ros1_noetic_field_install_evidence(
                evidence_path, **kwargs):
            assert Path(evidence_path).name == evidence_name
            assert kwargs['source_audit'] is source_audit
            assert kwargs['canonical_source_binding'][
                'binding_sha256'] == '3' * 64
            assert kwargs['allow_test_synthetic_binding'] is False
            return install_validation

    with patch.object(
            RUNNER, '_load_perception_readiness',
            return_value=FakeReadiness()), patch.object(
                RUNNER, 'validate_ros1_canonical_source_admission',
                return_value=_canonical_admission()), patch.object(
                    RUNNER, 'validate_ros1_build_environment_evidence',
                    return_value=_build_not_verified()):
        gate = RUNNER.validate_ros1_delivery_install_gates(
            ROOT,
            {
                'source_set_sha256': '5' * 64,
                'entries': [],
            },
            field_install_evidence=(ROOT / evidence_name),
            build_attempt_evidence=(
                ROOT / 'missing-noetic-build-evidence.json'))

    summary = RUNNER.make_delivery_gate_summary(
        {'validated_pass': False, 'failures': []},
        {'validated_pass': False, 'failures': []},
        gate,
        evidence_authority={
            'validated_pass': True,
            'current_evidence': {
                'evidence_id': 'offline-test-only',
                'status': 'CURRENT_BLOCKED_OFFLINE_BASELINE',
                'scope': 'blocked_offline_release_selection',
            },
            'current_identity': {
                'path': 'offline-test-only.json',
                'size_bytes': 1,
                'sha256': '6' * 64,
            },
            'failures': [],
        })
    return gate, summary


def _assert_field_and_build_layers(gate, summary):
    assert gate['validated_pass'] is False
    assert gate['source_contract']['pass'] is True
    assert gate['canonical_source_admission']['validated_pass'] is True
    assert gate['architecture_blockers'] == []
    assert gate['field_evidence_blockers'] == [FIELD_EVIDENCE_MISSING]
    assert gate['build_install_blockers'] == [BUILD_INSTALL_NOT_VERIFIED]

    assert summary['delivery_ready'] is False
    assert summary['ros1_field_gate']['source_contract_pass'] is True
    assert summary['ros1_field_gate']['install_evidence_pass'] is False
    assert summary['architecture_blockers'] == []
    assert summary['field_evidence_blockers'] == [FIELD_EVIDENCE_MISSING]
    assert summary['build_install_blockers'] == [BUILD_INSTALL_NOT_VERIFIED]
    assert FIELD_EVIDENCE_MISSING in summary['delivery_blockers']
    assert BUILD_INSTALL_NOT_VERIFIED in summary['delivery_blockers']
    assert RUNNER.ROS1_RUNTIME_ARCHITECTURE_BLOCKER not in (
        summary['delivery_blockers'])


def test_live_source_and_canonical_pass_keep_missing_field_evidence_layered():
    install_validation = {
        'gate_id': RUNNER.ROS1_FIELD_INSTALL_GATE_ID,
        'scope': 'field_delivery',
        'required_for_delivery': True,
        'claimed_result': None,
        'validated_pass': False,
        'architecture_blockers': [],
        'installed_artifact_count': 0,
        'failures': ['ros1_field_install_evidence_missing'],
    }
    gate, summary = _run_layered_gate(
        install_validation, 'missing-field-install.json')
    _assert_field_and_build_layers(gate, summary)
    assert RUNNER.ROS1_RUNTIME_ARCHITECTURE_BLOCKER not in gate['failures']


def test_legacy_field_evidence_runtime_blocker_cannot_reopen_architecture():
    install_validation = {
        'gate_id': RUNNER.ROS1_FIELD_INSTALL_GATE_ID,
        'scope': 'field_delivery',
        'required_for_delivery': True,
        'claimed_result': 'BLOCKED_ARCHITECTURE',
        'validated_pass': False,
        'architecture_blockers': [
            RUNNER.ROS1_RUNTIME_ARCHITECTURE_BLOCKER],
        'installed_artifact_count': 8,
        'failures': [RUNNER.ROS1_RUNTIME_ARCHITECTURE_BLOCKER],
    }
    gate, summary = _run_layered_gate(
        install_validation, 'legacy-field-install-evidence.json')
    _assert_field_and_build_layers(gate, summary)
    assert gate['install_validation']['architecture_blockers'] == [
        RUNNER.ROS1_RUNTIME_ARCHITECTURE_BLOCKER]
    assert RUNNER.ROS1_RUNTIME_ARCHITECTURE_BLOCKER not in (
        gate['architecture_blockers'])


def test_host_validated_install_closes_only_the_install_layer():
    install_validation = {
        'gate_id': RUNNER.ROS1_FIELD_INSTALL_GATE_ID,
        'scope': 'field_delivery',
        'required_for_delivery': True,
        'claimed_result': 'PASS',
        'validated_pass': True,
        'architecture_blockers': [],
        'build_install_blockers': [],
        'field_evidence_blockers': [],
        'installed_artifact_count': 1,
        'failures': [],
    }
    gate, summary = _run_layered_gate(
        install_validation, 'host-validated-field-install.json')

    assert gate['validated_pass'] is True
    assert gate['install_validation']['validated_pass'] is True
    assert gate['architecture_blockers'] == []
    assert gate['build_install_blockers'] == []
    assert gate['field_evidence_blockers'] == []

    assert summary['ros1_field_gate']['validated_pass'] is True
    assert summary['ros1_field_gate']['install_evidence_pass'] is True
    assert summary['delivery_ready'] is False
    assert summary['formal_field_evidence_gate'] == {
        'formal_four_scene_frame_denominator': 0,
        'formal_tf_pass': False,
        'formal_3d_pass': False,
        'formal_latency_pass': False,
        'validated_pass': False,
        'diagnostic_or_historical_evidence_cannot_close_gate': True,
    }
    assert 'FORMAL_FOUR_SCENE_DENOMINATOR_ZERO' in (
        summary['delivery_blockers'])
    assert 'FORMAL_TF_NOT_VALIDATED' in summary['delivery_blockers']
    assert 'FORMAL_3D_NOT_VALIDATED' in summary['delivery_blockers']
    assert 'FORMAL_LATENCY_NOT_VALIDATED' in summary['delivery_blockers']

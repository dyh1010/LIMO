import copy
import hashlib
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from limo_cleanup_executor.final_gripper_release_manifest import (  # noqa
    ManifestLoadError,
    SECTION_NAMES,
    canonical_cad_inventory_sha256,
    load_manifest,
    loads_manifest,
    main,
    validate_manifest,
    validate_manifest_bindings,
    validate_manifest_structure,
)


MANIFEST_PATH = (
    PACKAGE_ROOT / 'config' / 'final_gripper_release_manifest.json')


def digest(label):
    return hashlib.sha256(label.encode('utf-8')).hexdigest()


EXECUTION_EVIDENCE_IDS = {
    'backend_method_contract_sha256':
        'EVIDENCE-BACKEND-METHOD-CONTRACT',
    'stop_isolation_architecture_sha256':
        'EVIDENCE-STOP-ISOLATION-ARCHITECTURE',
    'hung_command_stop_test_report_sha256':
        'EVIDENCE-HUNG-COMMAND-STOP-REPORT',
}


def canonical_json_bytes(value):
    return (json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(',', ':'),
    ) + '\n').encode('utf-8')


def issue_codes(result):
    return {
        item.code for item in tuple(result.errors) + tuple(result.blockers)}


def accepted_review(section):
    return {
        'reviewed': True,
        'evidence_ids': ['EVIDENCE-' + section.upper()],
        'reviewer': 'Release Reviewer',
        'reviewed_at_utc': '2026-08-14T01:02:03Z',
        'disposition': 'ACCEPTED',
    }


def evidence_record(section):
    return {
        'evidence_id': 'EVIDENCE-' + section.upper(),
        'sections': [section],
        'source': 'Controlled release authority',
        'artifact': 'controlled/{}.pdf'.format(section),
        'artifact_sha256': digest('evidence-' + section),
        'method': 'CONTROLLED_DOCUMENT',
        'result': 'Reviewed values accepted for the exact tool revision',
        'reviewer': 'Release Reviewer',
        'reviewed_at_utc': '2026-08-14T01:02:03Z',
        'applicability': 'FINAL-GRIPPER-R1-SERIAL-001',
        'disposition': 'ACCEPTED',
    }


def envelope(label):
    return {
        'frame': 'gripper_mount',
        'minimum_m': [-0.05, -0.04, -0.02],
        'maximum_m': [0.05, 0.04, 0.12],
        'artifact_sha256': digest('envelope-' + label),
    }


def feedback_capability(supported, unit=None):
    if not supported:
        return {
            'support': 'UNSUPPORTED',
            'unit': None,
            'encoding': None,
            'range': None,
            'resolution': None,
            'update_rate_hz': None,
            'validity_specification': None,
        }
    return {
        'support': 'SUPPORTED',
        'unit': unit or 'dimensionless',
        'encoding': 'Exact protocol field encoding under revision control',
        'range': 'Reviewed legal range and invalid sentinels',
        'resolution': 'Reviewed quantization or exact discrete values',
        'update_rate_hz': 'At least 20 Hz under the reviewed timing contract',
        'validity_specification':
            'Explicit validity bit and fail-closed invalid-value handling',
    }


def reviewed_manifest():
    manifest = load_manifest(MANIFEST_PATH)
    manifest['release_requested'] = True
    manifest['release_approved'] = True
    manifest['tool_identity'].update({
        'tool_model': 'LIMO-FINAL-REPLACEMENT-GRIPPER',
        'tool_revision': 'R1',
        'assembly_configuration': 'R1 production assembly',
        'serial_or_lot': 'SERIAL-001',
        'tool_architecture': 'COMPLETE_REPLACEMENT',
        'complete_replacement': True,
        'ag_retention_map_sha256': None,
        'review': accepted_review('tool_identity'),
    })
    manifest['controller_firmware'].update({
        'actuator_manufacturer': 'Example Actuator Manufacturer',
        'actuator_model': 'ACT-4100',
        'actuator_hardware_revision': 'HW-R2',
        'controller_manufacturer': 'Example Controller Manufacturer',
        'controller_model': 'CTRL-4200',
        'controller_hardware_revision': 'HW-R3',
        'controller_serial': 'CTRL-SERIAL-001',
        'firmware_revision': 'FW-4.2.1',
        'compatibility_matrix_sha256': digest('compatibility'),
        'review': accepted_review('controller_firmware'),
    })
    manifest['transport_protocol'].update({
        'transport_type': 'RS-485',
        'physical_layer_specification': 'Isolated half-duplex 3.3 V logic',
        'protocol_name': 'FINAL-GRIPPER-PROTOCOL',
        'protocol_revision': 'P2',
        'protocol_definition_sha256': digest('protocol'),
        'native_command_unit': 'encoder_tick',
        'timing_and_addressing_specification': '1 Mbps, address 17',
        'frame_and_integrity_specification': 'Little-endian CRC-16 frames',
        'ack_nak_specification': 'Command-ID correlated ACK or NAK',
        'command_id_specification': '128-bit caller-generated ID',
        'ordering_and_replay_specification':
            'Reject duplicates, replay, and out-of-order commands',
        'watchdog_and_disconnect_specification':
            '200 ms watchdog enters the documented safe output state',
        'review': accepted_review('transport_protocol'),
    })
    manifest['cad_sources'].update({
        'neutral_assembly_path': 'controlled/final_gripper_r1.step',
        'neutral_assembly_sha256': digest('neutral-cad'),
        'controlled_bom_sha256': digest('bom'),
        'controlled_drawing_sha256': digest('drawing'),
        'review': accepted_review('cad_sources'),
    })
    manifest['units']['review'] = accepted_review('units')
    manifest['flange_tcp'].update({
        'flange_interface_drawing_sha256': digest('flange'),
        'fastener_stack_specification_sha256': digest('fasteners'),
        'flange_to_mount_transform': {
            'translation_m': [0.001, 0.002, 0.003],
            'rotation_xyzw': [0.0, 0.0, 0.0, 1.0],
        },
        'mount_to_tcp_transform': {
            'translation_m': [0.0, 0.0, 0.101],
            'rotation_xyzw': [0.0, 0.0, 0.0, 1.0],
        },
        'tcp_opening_dependency': {
            'mode': 'FIXED',
            'calibration_sha256': digest('tcp-calibration'),
            'valid_opening_range_m': {
                'minimum': 0.01,
                'maximum': 0.06,
            },
        },
        'review': accepted_review('flange_tcp'),
    })
    manifest['motion_limits'].update({
        'native_command_range': {
            'minimum': 10,
            'maximum': 4090,
            'unit': 'encoder_tick',
            'direction': 'INCREASING_COMMAND_OPENS',
        },
        'jaw_opening_range_m': {
            'minimum': 0.01,
            'maximum': 0.06,
        },
        'joints': [
            {
                'name': 'left_finger_joint',
                'lower_rad': -0.4,
                'upper_rad': 0.4,
                'max_velocity_rad_s': 0.5,
                'max_acceleration_rad_s2': 1.2,
            },
            {
                'name': 'right_finger_joint',
                'lower_rad': -0.4,
                'upper_rad': 0.4,
                'max_velocity_rad_s': 0.5,
                'max_acceleration_rad_s2': 1.2,
            },
        ],
        'named_poses': {
            'open': {
                'left_finger_joint': 0.3,
                'right_finger_joint': -0.3,
            },
            'mid': {
                'left_finger_joint': 0.0,
                'right_finger_joint': 0.0,
            },
            'closed': {
                'left_finger_joint': -0.3,
                'right_finger_joint': 0.3,
            },
        },
        'closing_force_limit_n': 12.3,
        'command_to_opening_calibration_sha256': digest('opening-calibration'),
        'hard_limit_evidence_sha256': digest('hard-limits'),
        'review': accepted_review('motion_limits'),
    })
    manifest['mass_properties'].update({
        'installed_tool_mass_kg': 0.238,
        'mass_measurement_uncertainty_kg': 0.002,
        'center_of_mass': {
            'frame': 'gripper_mount',
            'xyz_m': [0.0, 0.0, 0.045],
        },
        'inertia_tensor': {
            'frame': 'gripper_mount',
            'ixx': 0.0011,
            'iyy': 0.0012,
            'izz': 0.0013,
            'ixy': 0.00001,
            'ixz': 0.00002,
            'iyz': 0.00003,
        },
        'includes_adapter_fasteners_cable': True,
        'mass_property_report_sha256': digest('mass-properties'),
        'review': accepted_review('mass_properties'),
    })
    manifest['collision_cable_envelope'].update({
        'visual_mesh_manifest_sha256': digest('visual-meshes'),
        'collision_mesh_manifest_sha256': digest('collision-meshes'),
        'open_envelope': envelope('open'),
        'mid_envelope': envelope('mid'),
        'closed_envelope': envelope('closed'),
        'cable_envelope': envelope('cable'),
        'cable_minimum_bend_radius_m': 0.025,
        'cable_strain_relief_verified': True,
        'interference_review_passed': True,
        'review': accepted_review('collision_cable_envelope'),
    })
    manifest['electrical'].update({
        'rated_supply_voltage_v': {'minimum': 11.0, 'maximum': 13.0},
        'absolute_supply_voltage_v': {'minimum': 10.0, 'maximum': 14.0},
        'idle_current_a': 0.1,
        'startup_current_a': 0.3,
        'rated_current_a': 0.4,
        'peak_current_a': 1.2,
        'stall_current_a': 2.0,
        'conductor_cross_section_mm2': 0.2,
        'fuse_or_current_limit_a': 2.5,
        'connector_pinout_sha256': digest('pinout'),
        'polarity_and_grounding':
            'Pin 1 positive, pin 2 signal return, shield chassis-bonded',
        'protection_specification_sha256': digest('protection'),
        'hot_plug_policy': 'PROHIBITED',
        'energy_isolation_specification_sha256': digest('isolation'),
        'static_inspection_passed': True,
        'review': accepted_review('electrical'),
    })
    manifest['passive_power_loss_safety'].update({
        'backdrivability': 'CONDITION_DEPENDENT',
        'brake': 'PRESENT',
        'self_locking': 'CONDITION_DEPENDENT',
        'loss_of_power_jaw_behavior': 'RETAINS',
        'object_drop_hazard':
            'Residual drop hazard controlled by the reviewed exclusion zone',
        'secondary_retention_or_exclusion':
            'No suspended load; guarded exclusion zone is mandatory',
        'loss_of_power_hazard_analysis_sha256':
            digest('loss-of-power-hazard-analysis'),
        'passive_safety_static_inspection_sha256':
            digest('passive-safety-static-inspection'),
        'controlled_review_passed': True,
        'review': accepted_review('passive_power_loss_safety'),
    })
    manifest['contact_human_safety'].update({
        'pad_material': 'Controlled silicone compound CS-40',
        'pad_compliance': '40 Shore A nominal per controlled specification',
        'pad_retention': 'Keyed carrier plus captive mechanical retention',
        'allowable_contact_pressure':
            'Limited by the reviewed gripper force and contact-area analysis',
        'cleaning_and_chemical_compatibility':
            'Neutral detergent only per controlled material specification',
        'pinch_hazard_review_passed': True,
        'shear_hazard_review_passed': True,
        'crush_hazard_review_passed': True,
        'entanglement_hazard_review_passed': True,
        'sharp_edge_guarding_review_passed': True,
        'contact_interface_specification_sha256':
            digest('contact-interface-specification'),
        'hazard_guarding_inspection_sha256':
            digest('hazard-guarding-inspection'),
        'review': accepted_review('contact_human_safety'),
    })
    manifest['durability_maintenance'].update({
        'rated_cycle_life_cycles': 250000,
        'rated_duty_cycle': 'S3 25 percent, reviewed ambient range',
        'gear_bearing_load_life_basis':
            'Controlled supplier ratings with assembly load calculation',
        'wear_limit_specification':
            'Replace at the controlled wear gauge rejection limit',
        'backlash_limit_specification':
            'Maximum reviewed jaw lost motion per maintenance plan',
        'lubrication_specification':
            'Controlled lubricant, quantity, interval, and contamination rule',
        'fastener_locking_and_torque_mark_policy':
            'Specified locking method, torque, witness marks, and replacement',
        'inspection_interval':
            'Before use and at the cycle/time interval in the maintenance plan',
        'replacement_criteria':
            'Replace on wear, damage, leakage, looseness, or limit exceedance',
        'approved_spares_revision_control':
            'Only BOM-listed spare revisions under configuration control',
        'maintenance_plan_sha256': digest('maintenance-plan'),
        'initial_static_condition_sha256':
            digest('initial-static-condition'),
        'initial_static_inspection_passed': True,
        'review': accepted_review('durability_maintenance'),
    })
    manifest['backend_execution_safety'].update({
        'release_binding': {
            'runtime_release_id': 'gripper-runtime-r1',
            'release_manifest_sha256': digest('gripper-runtime-release-r1'),
        },
        'motion_profile_binding': {
            'profile_id': 'gripper-motion-profile-r1',
            'runtime_release_id': 'gripper-runtime-r1',
            'profile_manifest_sha256': digest('gripper-motion-profile-r1'),
            'approved_speed_grades': [5, 10],
        },
        'method_deadlines_s': {
            'read_state': 0.1,
            'command_position': 0.25,
            'stop': 0.1,
            'close': 0.25,
        },
        'method_timeout_handling': {
            'read_state': 'CANCELLABLE',
            'command_position': 'BOUNDED_ABANDONMENT',
            'stop': 'CANCELLABLE',
            'close': 'BOUNDED_ABANDONMENT',
        },
        'stop_isolation': {
            'independent_executor': True,
            'independent_lock_domain': True,
            'not_queued_behind_normal_commands': True,
            'hung_command_stop_deadline_s': 0.1,
            'hung_command_stop_deadline_verified': True,
            'deadline_miss_fails_closed': True,
        },
        'backend_method_contract_sha256':
            digest('backend-method-contract'),
        'stop_isolation_architecture_sha256':
            digest('stop-isolation-architecture'),
        'hung_command_stop_test_report_sha256':
            digest('hung-command-stop-test-report'),
        'review': accepted_review('backend_execution_safety'),
    })
    manifest['feedback_contract'].update({
        'field_capabilities': {
            'connected': feedback_capability(True),
            'valid': feedback_capability(True),
            'enabled': feedback_capability(True),
            'moving': feedback_capability(True),
            'opened_limit': feedback_capability(False),
            'closed_limit': feedback_capability(False),
            'normalized_position': feedback_capability(True, 'normalized'),
            'jaw_opening_m': feedback_capability(False),
            'supply_voltage_v': feedback_capability(False),
            'motor_current_a': feedback_capability(False),
            'grip_force_n': feedback_capability(False),
            'temperature_c': feedback_capability(False),
            'fault_code': feedback_capability(True, 'controller_fault_code'),
        },
        'source_timestamp_specification':
            'Controller-monotonic sample time with documented epoch',
        'receive_timestamp_specification':
            'Gateway monotonic receive time captured before validation',
        'sequence_specification':
            'Strictly increasing unsigned sequence per controller boot',
        'invalid_value_specification':
            'No magic values; invalid or absent fields remain unsupported',
        'fault_dictionary_sha256': digest('fault-dictionary'),
        'fault_latch_and_recovery_specification':
            'Fault classes, latching, local ACK and restart requirements',
        'command_feedback_correlation_specification':
            'Every accepted command is correlated by exact command ID',
        'controller_restart_specification':
            'Boot identity change invalidates session and authorization',
        'normalized_position_command_supported': True,
        'jaw_opening_command_supported': False,
        'command_capability_specification_sha256':
            digest('command-capability-specification'),
        'review': accepted_review('feedback_contract'),
    })
    manifest['stop_stationary_ack']['stop'].update({
        'request_mechanism': 'Dedicated command-ID correlated STOP frame',
        'acknowledgement_mechanism': 'Matching local STOP ACK frame',
        'ack_timeout_s': 0.25,
        'safe_output_state': 'Output disabled and command state latched',
    })
    manifest['stop_stationary_ack']['stationary'].update({
        'feedback_signal': 'jaw_encoder',
        'feedback_unit': 'encoder_tick',
        'position_tolerance_native': 2,
        'minimum_consecutive_samples': 3,
        'dwell_s': 0.2,
        'sample_period_s': 0.05,
        'timeout_s': 1.0,
    })
    manifest['stop_stationary_ack']['review'] = accepted_review(
        'stop_stationary_ack')
    manifest['transport_owner'].update({
        'owner_identity': 'limo-final-gripper-gateway',
        'ownership_scope': 'controller bus address 17 and all command frames',
        'arbitration_mechanism': 'Exclusive OS lock and controller lease',
        'owner_lock_artifact_sha256': digest('owner-lock'),
        'ownership_evidence_sha256': digest('owner-evidence'),
        'sole_owner_verified': True,
        'review': accepted_review('transport_owner'),
    })
    manifest['legacy_input_policy'].update({
        'denylist_scan_passed': True,
        'review': accepted_review('legacy_input_policy'),
    })
    manifest['evidence_records'] = [
        evidence_record(section) for section in SECTION_NAMES
    ]
    for suffix, label in (
            ('RUNTIME-RELEASE', 'backend-runtime-release'),
            ('MOTION-PROFILE', 'backend-motion-profile')):
        record = evidence_record('backend_execution_safety')
        record.update({
            'evidence_id': (
                'EVIDENCE-BACKEND_EXECUTION_SAFETY-' + suffix),
            'artifact': 'controlled/{}.json'.format(label),
            'artifact_sha256': digest('evidence-' + label),
            'result': (
                'Reviewed exact backend runtime/profile binding artifact'),
        })
        manifest['evidence_records'].append(record)
        manifest['backend_execution_safety']['review'][
            'evidence_ids'].append(record['evidence_id'])
    for field, evidence_id in EXECUTION_EVIDENCE_IDS.items():
        record = evidence_record('backend_execution_safety')
        record.update({
            'evidence_id': evidence_id,
            'artifact': 'controlled/{}.json'.format(
                field[:-len('_sha256')]),
            'artifact_sha256': digest(evidence_id),
            'result': 'Machine-readable backend execution safety evidence',
        })
        manifest['evidence_records'].append(record)
        manifest['backend_execution_safety']['review'][
            'evidence_ids'].append(record['evidence_id'])
    return manifest


def execution_binding(manifest):
    section = manifest['backend_execution_safety']
    return {
        'runtime_release_id':
            section['release_binding']['runtime_release_id'],
        'release_manifest_sha256':
            section['release_binding']['release_manifest_sha256'],
        'motion_profile_id':
            section['motion_profile_binding']['profile_id'],
        'motion_profile_manifest_sha256':
            section['motion_profile_binding']['profile_manifest_sha256'],
        'approved_speed_grades':
            section['motion_profile_binding']['approved_speed_grades'],
    }


def execution_artifact(field, manifest):
    section = manifest['backend_execution_safety']
    binding = execution_binding(manifest)
    if field == 'backend_method_contract_sha256':
        methods = {}
        for method in ('read_state', 'command_position', 'stop', 'close'):
            handling = section['method_timeout_handling'][method]
            methods[method] = {
                'deadline_s': section['method_deadlines_s'][method],
                'timeout_handling': handling,
                'native_deadline_enforced': True,
                'native_timeout_implementation': (
                    'NATIVE_CANCEL'
                    if handling == 'CANCELLABLE'
                    else 'NATIVE_BOUNDED_CALL'),
                'python_timeout_thread_used': False,
            }
        return {
            'schema_id': 'limo.gripper_backend_method_contract',
            'schema_version': 1,
            'binding': binding,
            'methods': methods,
        }
    if field == 'stop_isolation_architecture_sha256':
        return {
            'schema_id': 'limo.gripper_stop_isolation_architecture',
            'schema_version': 1,
            'binding': binding,
            'motion_executor_id': 'motion-executor-r1',
            'stop_executor_id': 'stop-executor-r1',
            'motion_channel_id': 'motion-channel-r1',
            'stop_channel_id': 'stop-channel-r1',
            'motion_lock_domain_id': 'motion-lock-r1',
            'stop_lock_domain_id': 'stop-lock-r1',
            'independent_executor': True,
            'independent_channel': True,
            'independent_lock_domain': True,
            'stop_not_queued_behind_normal_commands': True,
            'shared_adapter_lock': False,
        }
    if field == 'hung_command_stop_test_report_sha256':
        return {
            'schema_id': 'limo.gripper_hung_command_stop_report',
            'schema_version': 1,
            'binding': binding,
            'command_method': 'command_position',
            'command_call_id': 'blocked-command-001',
            'stop_call_id': 'independent-stop-001',
            'motion_send_entered_at_s': 10.0,
            'stop_requested_at_s': 10.02,
            'stop_completed_at_s': 10.06,
            'motion_send_released_at_s': 10.50,
            'stop_deadline_s': section['stop_isolation'][
                'hung_command_stop_deadline_s'],
            'stop_completed': True,
            'stop_completed_before_send_release': True,
            'late_command_result_rejected': True,
            'deadline_miss_fails_closed': True,
            'physical_isolation_required_on_failure': True,
            'final_state': 'FAULT_LATCHED',
        }
    raise AssertionError('unknown execution artifact field: ' + field)


def write_bound_release_fixture(
        directory, manifest=None, bind_section_claims=True):
    root = Path(directory)
    artifact_root = root / 'artifacts'
    cad_root = root / 'cad'
    artifact_root.mkdir()
    cad_root.mkdir()
    if manifest is None:
        manifest = reviewed_manifest()

    evidence_hash_by_section = {}
    evidence_hash_by_id = {}
    for index, record in enumerate(manifest['evidence_records']):
        relative = 'evidence/{}.txt'.format(index)
        payload = 'controlled evidence {}\n'.format(index).encode('utf-8')
        path = artifact_root / Path(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        record['artifact'] = relative
        record['artifact_sha256'] = hashlib.sha256(payload).hexdigest()
        evidence_hash_by_id[
            record['evidence_id']] = record['artifact_sha256']
        for section in record['sections']:
            evidence_hash_by_section.setdefault(
                section, record['artifact_sha256'])

    def bind_section_claim_hashes(value, section):
        if type(value) is dict:
            for key, item in value.items():
                if (
                        key.endswith('_sha256')
                        and key not in (
                            'assembly_sha256',
                            'source_snapshot_sha256',
                            'neutral_assembly_sha256',
                        )
                        and item is not None):
                    value[key] = evidence_hash_by_section[section]
                else:
                    bind_section_claim_hashes(item, section)
        elif type(value) is list:
            for item in value:
                bind_section_claim_hashes(item, section)

    if bind_section_claims:
        for section in SECTION_NAMES:
            bind_section_claim_hashes(manifest[section], section)
        backend = manifest['backend_execution_safety']
        backend['release_binding']['release_manifest_sha256'] = (
            evidence_hash_by_id[
                'EVIDENCE-BACKEND_EXECUTION_SAFETY-RUNTIME-RELEASE'])
        backend['motion_profile_binding']['profile_manifest_sha256'] = (
            evidence_hash_by_id[
                'EVIDENCE-BACKEND_EXECUTION_SAFETY-MOTION-PROFILE'])
        records_by_id = {
            record['evidence_id']: record
            for record in manifest['evidence_records']
        }
        for field, evidence_id in EXECUTION_EVIDENCE_IDS.items():
            record = records_by_id[evidence_id]
            payload = canonical_json_bytes(execution_artifact(field, manifest))
            relative = 'execution/{}.json'.format(field[:-len('_sha256')])
            path = artifact_root / Path(relative)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
            artifact_hash = hashlib.sha256(payload).hexdigest()
            record['artifact'] = relative
            record['artifact_sha256'] = artifact_hash
            backend[field] = artifact_hash

    neutral_relative = 'neutral/final_gripper_r1.step'
    neutral_payload = b'controlled neutral assembly\n'
    neutral_path = artifact_root / Path(neutral_relative)
    neutral_path.parent.mkdir(parents=True, exist_ok=True)
    neutral_path.write_bytes(neutral_payload)
    manifest['cad_sources']['neutral_assembly_path'] = neutral_relative
    manifest['cad_sources']['neutral_assembly_sha256'] = hashlib.sha256(
        neutral_payload).hexdigest()

    cad_entries = []
    for relative, role, payload in (
            ('part_a.SLDPRT', 'PART', b'part-a\n'),
            ('assembly.SLDASM', 'ASSEMBLY', b'assembly\n')):
        path = cad_root / Path(relative)
        path.write_bytes(payload)
        cad_entries.append({
            'path': relative,
            'role': role,
            'sha256': hashlib.sha256(payload).hexdigest(),
            'size_bytes': len(payload),
        })
    cad_entries.sort(key=lambda entry: entry['path'])
    assembly = next(
        entry for entry in cad_entries if entry['role'] == 'ASSEMBLY')
    manifest['cad_sources'].update({
        'source_snapshot_name': 'pure-local-bound-fixture',
        'source_snapshot_sha256': canonical_cad_inventory_sha256(cad_entries),
        'file_count': len(cad_entries),
        'total_size_bytes': sum(entry['size_bytes'] for entry in cad_entries),
        'assembly_path': assembly['path'],
        'assembly_sha256': assembly['sha256'],
        'files': cad_entries,
    })
    manifest['tool_identity']['assembly_sha256'] = assembly['sha256']
    return manifest, artifact_root, cad_root


def rewrite_execution_artifact(
        manifest, artifact_root, field, mutate=None, raw_payload=None):
    evidence_id = EXECUTION_EVIDENCE_IDS[field]
    record = next(
        item for item in manifest['evidence_records']
        if item['evidence_id'] == evidence_id)
    path = artifact_root / Path(record['artifact'])
    if raw_payload is None:
        value = json.loads(path.read_text(encoding='utf-8'))
        mutate(value)
        payload = canonical_json_bytes(value)
    else:
        payload = raw_payload
    path.write_bytes(payload)
    artifact_hash = hashlib.sha256(payload).hexdigest()
    record['artifact_sha256'] = artifact_hash
    manifest['backend_execution_safety'][field] = artifact_hash


class FinalGripperReleaseManifestTest(unittest.TestCase):
    def test_blocked_manifest_is_schema_valid_and_release_blocked(self):
        manifest = load_manifest(MANIFEST_PATH)
        result = validate_manifest(manifest)
        self.assertTrue(result.schema_valid)
        self.assertFalse(result.release_ready)
        self.assertFalse(result.errors)
        self.assertGreaterEqual(len(result.blockers), 100)
        self.assertEqual(
            manifest['tool_identity']['tool_architecture'],
            'COMPLETE_REPLACEMENT')
        self.assertIs(
            manifest['tool_identity']['complete_replacement'], True)
        self.assertIs(
            manifest['tool_identity']['legacy_ag_components_retained'], False)
        self.assertIsNone(
            manifest['tool_identity']['ag_retention_map_sha256'])
        self.assertIn('FIRMWARE_REVISION_UNKNOWN', issue_codes(result))
        self.assertIn('TRANSPORT_OWNER_NOT_UNIQUE', issue_codes(result))
        self.assertIn('STOP_SEMANTICS_INCOMPLETE', issue_codes(result))
        self.assertIn('NEUTRAL_CAD_UNKNOWN', issue_codes(result))
        self.assertIn('ARTIFACT_ROOT_REQUIRED', issue_codes(result))
        self.assertIn('CAD_ROOT_REQUIRED', issue_codes(result))
        self.assertIn('PASSIVE_SAFETY_UNKNOWN', issue_codes(result))
        self.assertIn(
            'CONTACT_HUMAN_SAFETY_REVIEW_NOT_PASSED', issue_codes(result))
        self.assertIn(
            'DURABILITY_MAINTENANCE_UNKNOWN', issue_codes(result))
        self.assertIn(
            'BACKEND_METHOD_DEADLINES_UNKNOWN', issue_codes(result))
        self.assertIn('STOP_ISOLATION_NOT_PROVEN', issue_codes(result))
        self.assertNotIn(
            'TOOL_ARCHITECTURE_UNRESOLVED', issue_codes(result))
        self.assertIn('FEEDBACK_FIELD_SUPPORT_UNKNOWN', issue_codes(result))
        self.assertIn('FAULT_DICTIONARY_UNKNOWN', issue_codes(result))

    def test_fully_reviewed_synthetic_manifest_passes_structure_only(self):
        result = validate_manifest_structure(reviewed_manifest())
        self.assertTrue(result.schema_valid)
        self.assertTrue(result.release_ready, result.as_dict())
        self.assertEqual((), result.errors)
        self.assertEqual((), result.blockers)

    def test_fully_reviewed_synthetic_manifest_fails_complete_gate(self):
        result = validate_manifest(reviewed_manifest())
        self.assertTrue(result.schema_valid)
        self.assertFalse(result.release_ready)
        self.assertEqual((), result.errors)
        self.assertIn('ARTIFACT_ROOT_REQUIRED', issue_codes(result))
        self.assertIn('CAD_ROOT_REQUIRED', issue_codes(result))

    def test_real_local_artifacts_and_cad_pass_complete_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest, artifact_root, cad_root = write_bound_release_fixture(
                directory)
            result = validate_manifest(
                manifest,
                artifact_root=artifact_root,
                cad_root=cad_root,
            )
        self.assertTrue(result.schema_valid)
        self.assertTrue(result.release_ready, result.as_dict())
        self.assertEqual((), result.errors)
        self.assertEqual((), result.blockers)

    def test_fabricated_artifact_and_neutral_paths_fail_binding(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifact_root = root / 'artifacts'
            cad_root = root / 'cad'
            artifact_root.mkdir()
            cad_root.mkdir()
            manifest = reviewed_manifest()
            result = validate_manifest(
                manifest,
                artifact_root=artifact_root,
                cad_root=cad_root,
            )
        self.assertFalse(result.release_ready)
        self.assertIn('ARTIFACT_FILE_MISSING', issue_codes(result))
        self.assertIn('CAD_FILE_MISSING', issue_codes(result))

    def test_tampered_artifact_and_cad_fail_binding(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest, artifact_root, cad_root = write_bound_release_fixture(
                directory)
            (artifact_root / manifest['evidence_records'][0][
                'artifact']).write_bytes(b'tampered evidence\n')
            (cad_root / manifest['cad_sources']['files'][0][
                'path']).write_bytes(b'tampered cad\n')
            result = validate_manifest_bindings(
                manifest,
                artifact_root=artifact_root,
                cad_root=cad_root,
            )
        self.assertFalse(result.release_ready)
        self.assertIn('ARTIFACT_FILE_HASH_MISMATCH', issue_codes(result))
        self.assertIn('CAD_FILE_HASH_MISMATCH', issue_codes(result))

    def test_undeclared_cad_file_fails_binding(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest, artifact_root, cad_root = write_bound_release_fixture(
                directory)
            (cad_root / 'undeclared.SLDPRT').write_bytes(b'undeclared\n')
            result = validate_manifest_bindings(
                manifest,
                artifact_root=artifact_root,
                cad_root=cad_root,
            )
        self.assertIn('CAD_ROOT_UNDECLARED_FILE', issue_codes(result))

    def test_synthetic_section_claim_hash_fails_full_binding(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest, artifact_root, cad_root = write_bound_release_fixture(
                directory)
            manifest['controller_firmware'][
                'compatibility_matrix_sha256'] = digest(
                    'unbound synthetic compatibility claim')
            result = validate_manifest(
                manifest,
                artifact_root=artifact_root,
                cad_root=cad_root,
            )
        issues = [
            issue for issue in result.blockers
            if issue.code == 'UNBOUND_DECLARED_HASH'
        ]
        self.assertEqual(1, len(issues), result.as_dict())
        self.assertEqual(
            '$.controller_firmware.compatibility_matrix_sha256',
            issues[0].path,
        )

    def test_cross_section_evidence_hash_borrowing_fails_binding(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest, artifact_root, cad_root = write_bound_release_fixture(
                directory)
            evidence_by_section = {
                record['sections'][0]: record
                for record in manifest['evidence_records']
            }
            manifest['controller_firmware'][
                'compatibility_matrix_sha256'] = evidence_by_section[
                    'mass_properties']['artifact_sha256']
            result = validate_manifest(
                manifest,
                artifact_root=artifact_root,
                cad_root=cad_root,
            )
        scoped = [
            issue for issue in result.blockers
            if issue.code == 'HASH_EVIDENCE_SCOPE_MISMATCH'
        ]
        self.assertEqual(1, len(scoped), result.as_dict())
        self.assertEqual(
            '$.controller_firmware.compatibility_matrix_sha256',
            scoped[0].path,
        )

    def test_explicit_multi_section_evidence_may_bind_both_sections(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest, artifact_root, cad_root = write_bound_release_fixture(
                directory)
            evidence_by_section = {
                record['sections'][0]: record
                for record in manifest['evidence_records']
            }
            shared = evidence_by_section['mass_properties']
            shared['sections'].append('controller_firmware')
            manifest['controller_firmware'][
                'compatibility_matrix_sha256'] = shared['artifact_sha256']
            result = validate_manifest(
                manifest,
                artifact_root=artifact_root,
                cad_root=cad_root,
            )
        self.assertTrue(result.release_ready, result.as_dict())

    def test_cad_hash_cannot_satisfy_non_cad_section_claim(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest, artifact_root, cad_root = write_bound_release_fixture(
                directory)
            manifest['controller_firmware'][
                'compatibility_matrix_sha256'] = manifest['cad_sources'][
                    'files'][0]['sha256']
            result = validate_manifest(
                manifest,
                artifact_root=artifact_root,
                cad_root=cad_root,
            )
        self.assertIn(
            'HASH_EVIDENCE_SCOPE_MISMATCH', issue_codes(result))

    def test_evidence_hash_cannot_satisfy_cad_file_claim(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest, artifact_root, cad_root = write_bound_release_fixture(
                directory)
            first_cad = manifest['cad_sources']['files'][0]
            first_cad['sha256'] = manifest['evidence_records'][0][
                'artifact_sha256']
            result = validate_manifest_bindings(
                manifest,
                artifact_root=artifact_root,
                cad_root=cad_root,
            )
        self.assertIn('CAD_FILE_HASH_MISMATCH', issue_codes(result))
        self.assertIn('UNBOUND_DECLARED_HASH', issue_codes(result))

    def test_original_synthetic_manifest_has_unbound_claim_hashes(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest, artifact_root, cad_root = write_bound_release_fixture(
                directory,
                bind_section_claims=False,
            )
            result = validate_manifest_bindings(
                manifest,
                artifact_root=artifact_root,
                cad_root=cad_root,
            )
        unbound = [
            issue for issue in result.blockers
            if issue.code == 'UNBOUND_DECLARED_HASH'
        ]
        self.assertEqual(34, len(unbound), result.as_dict())

    def test_binding_rejects_relative_and_device_roots(self):
        manifest = reviewed_manifest()
        for artifact_root, cad_root, code in (
                ('relative/artifacts', Path.cwd(),
                 'ARTIFACT_ROOT_NOT_ABSOLUTE'),
                (Path.cwd(), 'relative/cad', 'CAD_ROOT_NOT_ABSOLUTE'),
                ('/dev', Path.cwd(), 'ARTIFACT_ROOT_UNSAFE')):
            with self.subTest(code=code):
                result = validate_manifest_bindings(
                    manifest,
                    artifact_root=artifact_root,
                    cad_root=cad_root,
                )
                self.assertIn(code, issue_codes(result))

    def test_manifest_cad_snapshot_matches_canonical_inventory(self):
        manifest = load_manifest(MANIFEST_PATH)
        cad = manifest['cad_sources']
        self.assertEqual(35, len(cad['files']))
        self.assertEqual(8058955, sum(
            entry['size_bytes'] for entry in cad['files']))
        self.assertEqual(
            cad['source_snapshot_sha256'],
            canonical_cad_inventory_sha256(cad['files']))
        assembly = [
            entry for entry in cad['files']
            if entry['role'] == 'ASSEMBLY']
        self.assertEqual(1, len(assembly))
        self.assertEqual('齿轮箱.SLDASM', assembly[0]['path'])
        self.assertEqual(cad['assembly_sha256'], assembly[0]['sha256'])

    def test_duplicate_json_key_is_rejected(self):
        with self.assertRaises(ManifestLoadError) as context:
            loads_manifest('{"schema_id": 1, "schema_id": 2}')
        self.assertEqual('DUPLICATE_KEY', context.exception.code)

    def test_nan_and_infinity_are_rejected(self):
        for token in ('NaN', 'Infinity', '-Infinity'):
            with self.subTest(token=token):
                with self.assertRaises(ManifestLoadError) as context:
                    loads_manifest('{"value": ' + token + '}')
                self.assertEqual(
                    'NON_FINITE_JSON_NUMBER', context.exception.code)

    def test_invalid_json_is_rejected(self):
        with self.assertRaises(ManifestLoadError) as context:
            loads_manifest('{')
        self.assertEqual('INVALID_JSON', context.exception.code)

    def test_invalid_calendar_timestamp_is_rejected(self):
        manifest = reviewed_manifest()
        manifest['created_at_utc'] = '2026-13-40T25:61:61Z'
        result = validate_manifest_structure(manifest)
        self.assertIn('INVALID_UTC_TIMESTAMP', issue_codes(result))

    def test_unknown_top_level_key_is_rejected(self):
        manifest = reviewed_manifest()
        manifest['guessed_servo_value'] = 17
        result = validate_manifest_structure(manifest)
        self.assertIn('UNKNOWN_KEY', issue_codes(result))
        self.assertFalse(result.schema_valid)

    def test_missing_top_level_key_is_rejected(self):
        manifest = reviewed_manifest()
        del manifest['electrical']
        result = validate_manifest_structure(manifest)
        self.assertIn('MISSING_KEY', issue_codes(result))

    def test_unknown_nested_key_is_rejected(self):
        manifest = reviewed_manifest()
        manifest['electrical']['assumed_voltage'] = 12
        result = validate_manifest_structure(manifest)
        self.assertIn('UNKNOWN_KEY', issue_codes(result))

    def test_boolean_is_not_accepted_as_number(self):
        manifest = reviewed_manifest()
        manifest['mass_properties']['installed_tool_mass_kg'] = True
        result = validate_manifest_structure(manifest)
        self.assertIn('TYPE_MISMATCH', issue_codes(result))

    def test_invalid_sha256_is_rejected(self):
        manifest = reviewed_manifest()
        manifest['controller_firmware']['compatibility_matrix_sha256'] = 'abc'
        result = validate_manifest_structure(manifest)
        self.assertIn('INVALID_HASH', issue_codes(result))

    def test_cad_count_mismatch_is_rejected(self):
        manifest = reviewed_manifest()
        manifest['cad_sources']['file_count'] = 34
        result = validate_manifest_structure(manifest)
        self.assertIn('CAD_COUNT_MISMATCH', issue_codes(result))

    def test_cad_snapshot_hash_is_mandatory(self):
        manifest = reviewed_manifest()
        manifest['cad_sources']['source_snapshot_sha256'] = None
        result = validate_manifest_structure(manifest)
        self.assertIn('REQUIRED_VALUE_UNKNOWN', issue_codes(result))

    def test_cad_assembly_hash_is_mandatory(self):
        manifest = reviewed_manifest()
        manifest['cad_sources']['assembly_sha256'] = None
        result = validate_manifest_structure(manifest)
        self.assertIn('REQUIRED_VALUE_UNKNOWN', issue_codes(result))

    def test_cad_size_mismatch_is_rejected(self):
        manifest = reviewed_manifest()
        manifest['cad_sources']['total_size_bytes'] += 1
        result = validate_manifest_structure(manifest)
        self.assertIn('CAD_SIZE_MISMATCH', issue_codes(result))

    def test_cad_snapshot_hash_mismatch_is_rejected(self):
        manifest = reviewed_manifest()
        manifest['cad_sources']['files'][0]['size_bytes'] += 1
        manifest['cad_sources']['total_size_bytes'] += 1
        result = validate_manifest_structure(manifest)
        self.assertIn('CAD_SNAPSHOT_HASH_MISMATCH', issue_codes(result))

    def test_each_cad_file_hash_is_mandatory(self):
        manifest = reviewed_manifest()
        manifest['cad_sources']['files'][0]['sha256'] = None
        result = validate_manifest_structure(manifest)
        self.assertIn('REQUIRED_VALUE_UNKNOWN', issue_codes(result))

    def test_cad_assembly_hash_mismatch_is_rejected(self):
        manifest = reviewed_manifest()
        manifest['cad_sources']['assembly_sha256'] = digest('wrong-assembly')
        result = validate_manifest_structure(manifest)
        self.assertIn('CAD_ASSEMBLY_HASH_MISMATCH', issue_codes(result))
        self.assertIn('ASSEMBLY_IDENTITY_MISMATCH', issue_codes(result))

    def test_cad_path_traversal_is_rejected(self):
        manifest = reviewed_manifest()
        manifest['cad_sources']['neutral_assembly_path'] = '../escape.step'
        result = validate_manifest_structure(manifest)
        self.assertIn('UNSAFE_RELATIVE_PATH', issue_codes(result))

    def test_unit_mismatch_is_rejected(self):
        manifest = reviewed_manifest()
        manifest['units']['mass'] = 'g'
        result = validate_manifest_structure(manifest)
        self.assertIn('UNIT_MISMATCH', issue_codes(result))

    def test_firmware_revision_cannot_be_implicit(self):
        manifest = reviewed_manifest()
        manifest['controller_firmware']['firmware_revision'] = None
        result = validate_manifest_structure(manifest)
        self.assertIn('FIRMWARE_REVISION_UNKNOWN', issue_codes(result))

    def test_manifest_is_explicitly_complete_replacement_only(self):
        for architecture, complete, retained, expected_code in (
                (None, False, False, 'TOOL_ARCHITECTURE_UNRESOLVED'),
                ('ORIGINAL_AG_RETAINED', False, True, 'INVALID_ENUM'),
                ('COMPLETE_REPLACEMENT', False, False,
                 'REQUIRED_ASSERTION_FALSE'),
                ('COMPLETE_REPLACEMENT', True, True,
                 'LEGACY_AG_RETENTION_UNRESOLVED')):
            with self.subTest(architecture=architecture):
                manifest = reviewed_manifest()
                identity = manifest['tool_identity']
                identity['tool_architecture'] = architecture
                identity['complete_replacement'] = complete
                identity['legacy_ag_components_retained'] = retained
                result = validate_manifest_structure(manifest)
                self.assertIn(expected_code, issue_codes(result))
                self.assertFalse(result.release_ready)

    def test_ag_retention_map_is_forbidden_in_replacement_manifest(self):
        manifest = reviewed_manifest()
        manifest['tool_identity']['ag_retention_map_sha256'] = digest(
            'ag-retention-map')
        result = validate_manifest_structure(manifest)
        self.assertIn(
            'AG_RETENTION_MAP_FORBIDDEN_FOR_REPLACEMENT',
            issue_codes(result),
        )
        self.assertFalse(result.release_ready)

    def test_each_feedback_support_classification_is_mandatory(self):
        manifest = reviewed_manifest()
        for field_name in tuple(manifest['feedback_contract'][
                'field_capabilities']):
            with self.subTest(field_name=field_name):
                case = copy.deepcopy(manifest)
                case['feedback_contract']['field_capabilities'][field_name][
                    'support'] = None
                result = validate_manifest_structure(case)
                self.assertIn(
                    'FEEDBACK_FIELD_SUPPORT_UNKNOWN', issue_codes(result))
                self.assertFalse(result.release_ready)

    def test_mandatory_feedback_fields_cannot_be_unsupported(self):
        for field_name in (
                'connected', 'valid', 'enabled', 'moving',
                'normalized_position', 'fault_code'):
            with self.subTest(field_name=field_name):
                manifest = reviewed_manifest()
                manifest['feedback_contract']['field_capabilities'][
                    field_name] = feedback_capability(False)
                result = validate_manifest_structure(manifest)
                self.assertIn(
                    'MANDATORY_FEEDBACK_FIELD_UNSUPPORTED',
                    issue_codes(result),
                )
                self.assertFalse(result.release_ready)

    def test_supported_feedback_requires_complete_field_contract(self):
        manifest = reviewed_manifest()
        manifest['feedback_contract']['field_capabilities'][
            'normalized_position']['resolution'] = None
        result = validate_manifest_structure(manifest)
        self.assertIn(
            'FEEDBACK_FIELD_CONTRACT_UNKNOWN', issue_codes(result))
        self.assertFalse(result.release_ready)

    def test_unsupported_feedback_cannot_claim_runtime_details(self):
        manifest = reviewed_manifest()
        manifest['feedback_contract']['field_capabilities'][
            'motor_current_a']['unit'] = 'A'
        result = validate_manifest_structure(manifest)
        self.assertIn(
            'UNSUPPORTED_FEEDBACK_HAS_CONTRACT', issue_codes(result))
        self.assertFalse(result.release_ready)

    def test_fault_and_command_capability_evidence_are_mandatory(self):
        for key, code in (
                ('fault_dictionary_sha256', 'FAULT_DICTIONARY_UNKNOWN'),
                ('command_capability_specification_sha256',
                 'COMMAND_CAPABILITY_EVIDENCE_UNKNOWN')):
            with self.subTest(key=key):
                manifest = reviewed_manifest()
                manifest['feedback_contract'][key] = None
                result = validate_manifest_structure(manifest)
                self.assertIn(code, issue_codes(result))
                self.assertFalse(result.release_ready)

    def test_jaw_command_requires_supported_jaw_feedback(self):
        manifest = reviewed_manifest()
        manifest['feedback_contract'][
            'jaw_opening_command_supported'] = True
        result = validate_manifest_structure(manifest)
        self.assertIn(
            'JAW_COMMAND_WITHOUT_FEEDBACK_CONTRACT', issue_codes(result))
        self.assertFalse(result.release_ready)

    def test_transport_owner_must_be_unique(self):
        manifest = reviewed_manifest()
        manifest['transport_owner']['sole_owner_verified'] = False
        result = validate_manifest_structure(manifest)
        self.assertIn('TRANSPORT_OWNER_NOT_UNIQUE', issue_codes(result))

    def test_stop_semantics_must_define_timeout(self):
        manifest = reviewed_manifest()
        manifest['stop_stationary_ack']['stop']['ack_timeout_s'] = None
        result = validate_manifest_structure(manifest)
        self.assertIn('STOP_SEMANTICS_INCOMPLETE', issue_codes(result))

    def test_software_stop_cannot_claim_physical_estop(self):
        manifest = reviewed_manifest()
        manifest['stop_stationary_ack']['stop'][
            'software_stop_is_not_physical_estop'] = False
        result = validate_manifest_structure(manifest)
        self.assertIn('STOP_SEMANTICS_UNSAFE', issue_codes(result))

    def test_stationary_timeout_must_exceed_dwell(self):
        manifest = reviewed_manifest()
        stationary = manifest['stop_stationary_ack']['stationary']
        stationary['timeout_s'] = stationary['dwell_s']
        result = validate_manifest_structure(manifest)
        self.assertIn('STATIONARY_TIMEOUT_INVALID', issue_codes(result))

    def test_stationary_requires_multiple_samples(self):
        manifest = reviewed_manifest()
        manifest['stop_stationary_ack']['stationary'][
            'minimum_consecutive_samples'] = 1
        result = validate_manifest_structure(manifest)
        self.assertIn('VALUE_OUT_OF_RANGE', issue_codes(result))

    def test_ack_cannot_enable_or_resume(self):
        for key in ('may_enable_output', 'may_resume_motion',
                    'may_retry_command'):
            with self.subTest(key=key):
                manifest = reviewed_manifest()
                manifest['stop_stationary_ack']['ack'][key] = True
                result = validate_manifest_structure(manifest)
                self.assertIn('ACK_SEMANTICS_UNSAFE', issue_codes(result))

    def test_acceleration_limit_is_mandatory_and_positive(self):
        manifest = reviewed_manifest()
        manifest['motion_limits']['joints'][0][
            'max_acceleration_rad_s2'] = 0
        result = validate_manifest_structure(manifest)
        self.assertIn('VALUE_OUT_OF_RANGE', issue_codes(result))

    def test_named_pose_must_stay_inside_joint_limits(self):
        manifest = reviewed_manifest()
        manifest['motion_limits']['named_poses']['open'][
            'left_finger_joint'] = 0.41
        result = validate_manifest_structure(manifest)
        self.assertIn('NAMED_POSE_OUT_OF_LIMITS', issue_codes(result))

    def test_tcp_quaternion_must_be_normalized(self):
        manifest = reviewed_manifest()
        manifest['flange_tcp']['mount_to_tcp_transform'][
            'rotation_xyzw'] = [0.0, 0.0, 0.0, 2.0]
        result = validate_manifest_structure(manifest)
        self.assertIn('INVALID_QUATERNION', issue_codes(result))

    def test_inertia_tensor_must_be_physically_plausible(self):
        manifest = reviewed_manifest()
        manifest['mass_properties']['inertia_tensor']['ixx'] = 1.0
        result = validate_manifest_structure(manifest)
        self.assertIn('INVALID_INERTIA_TENSOR', issue_codes(result))

    def test_electrical_absolute_range_must_contain_rated_range(self):
        manifest = reviewed_manifest()
        manifest['electrical']['absolute_supply_voltage_v'] = {
            'minimum': 12.0,
            'maximum': 12.5,
        }
        result = validate_manifest_structure(manifest)
        self.assertIn('ELECTRICAL_RANGE_INCONSISTENT', issue_codes(result))

    def test_electrical_current_order_is_checked(self):
        manifest = reviewed_manifest()
        manifest['electrical']['rated_current_a'] = 1.5
        result = validate_manifest_structure(manifest)
        self.assertIn('ELECTRICAL_CURRENT_ORDER_INVALID', issue_codes(result))

    def test_new_safety_sections_reject_unknown_keys(self):
        for section in (
                'passive_power_loss_safety',
                'contact_human_safety',
                'durability_maintenance',
                'backend_execution_safety',
                'feedback_contract'):
            with self.subTest(section=section):
                manifest = reviewed_manifest()
                manifest[section]['uncontrolled_claim'] = True
                result = validate_manifest_structure(manifest)
                self.assertIn('UNKNOWN_KEY', issue_codes(result))
                self.assertFalse(result.schema_valid)

    def test_passive_power_loss_unknowns_fail_closed(self):
        cases = (
            ('backdrivability', 'PASSIVE_SAFETY_UNKNOWN'),
            ('brake', 'PASSIVE_SAFETY_UNKNOWN'),
            ('self_locking', 'PASSIVE_SAFETY_UNKNOWN'),
            ('loss_of_power_jaw_behavior', 'PASSIVE_SAFETY_UNKNOWN'),
            ('object_drop_hazard', 'PASSIVE_SAFETY_UNKNOWN'),
            ('secondary_retention_or_exclusion', 'PASSIVE_SAFETY_UNKNOWN'),
            ('loss_of_power_hazard_analysis_sha256',
             'PASSIVE_SAFETY_EVIDENCE_UNKNOWN'),
            ('passive_safety_static_inspection_sha256',
             'PASSIVE_SAFETY_EVIDENCE_UNKNOWN'),
        )
        for key, code in cases:
            with self.subTest(key=key):
                manifest = reviewed_manifest()
                manifest['passive_power_loss_safety'][key] = None
                result = validate_manifest_structure(manifest)
                self.assertIn(code, issue_codes(result))
                self.assertFalse(result.release_ready)

    def test_passive_power_loss_review_false_fails_closed(self):
        manifest = reviewed_manifest()
        manifest['passive_power_loss_safety'][
            'controlled_review_passed'] = False
        result = validate_manifest_structure(manifest)
        self.assertIn(
            'PASSIVE_SAFETY_REVIEW_NOT_PASSED', issue_codes(result))
        self.assertFalse(result.release_ready)

    def test_passive_power_loss_enums_are_explicit(self):
        manifest = reviewed_manifest()
        manifest['passive_power_loss_safety'][
            'loss_of_power_jaw_behavior'] = 'UNPREDICTABLE'
        result = validate_manifest_structure(manifest)
        self.assertIn('INVALID_ENUM', issue_codes(result))
        self.assertFalse(result.schema_valid)

    def test_contact_human_safety_unknowns_fail_closed(self):
        for key in (
                'pad_material',
                'pad_compliance',
                'pad_retention',
                'allowable_contact_pressure',
                'cleaning_and_chemical_compatibility'):
            with self.subTest(key=key):
                manifest = reviewed_manifest()
                manifest['contact_human_safety'][key] = None
                result = validate_manifest_structure(manifest)
                self.assertIn(
                    'CONTACT_HUMAN_SAFETY_UNKNOWN', issue_codes(result))
                self.assertFalse(result.release_ready)
        for key in (
                'contact_interface_specification_sha256',
                'hazard_guarding_inspection_sha256'):
            with self.subTest(key=key):
                manifest = reviewed_manifest()
                manifest['contact_human_safety'][key] = None
                result = validate_manifest_structure(manifest)
                self.assertIn(
                    'CONTACT_HUMAN_SAFETY_EVIDENCE_UNKNOWN',
                    issue_codes(result),
                )
                self.assertFalse(result.release_ready)

    def test_each_contact_hazard_review_false_fails_closed(self):
        for key in (
                'pinch_hazard_review_passed',
                'shear_hazard_review_passed',
                'crush_hazard_review_passed',
                'entanglement_hazard_review_passed',
                'sharp_edge_guarding_review_passed'):
            with self.subTest(key=key):
                manifest = reviewed_manifest()
                manifest['contact_human_safety'][key] = False
                result = validate_manifest_structure(manifest)
                self.assertIn(
                    'CONTACT_HUMAN_SAFETY_REVIEW_NOT_PASSED',
                    issue_codes(result),
                )
                self.assertFalse(result.release_ready)

    def test_durability_maintenance_unknowns_fail_closed(self):
        for key in (
                'rated_cycle_life_cycles',
                'rated_duty_cycle',
                'gear_bearing_load_life_basis',
                'wear_limit_specification',
                'backlash_limit_specification',
                'lubrication_specification',
                'fastener_locking_and_torque_mark_policy',
                'inspection_interval',
                'replacement_criteria',
                'approved_spares_revision_control'):
            with self.subTest(key=key):
                manifest = reviewed_manifest()
                manifest['durability_maintenance'][key] = None
                result = validate_manifest_structure(manifest)
                self.assertIn(
                    'DURABILITY_MAINTENANCE_UNKNOWN', issue_codes(result))
                self.assertFalse(result.release_ready)
        for key in (
                'maintenance_plan_sha256',
                'initial_static_condition_sha256'):
            with self.subTest(key=key):
                manifest = reviewed_manifest()
                manifest['durability_maintenance'][key] = None
                result = validate_manifest_structure(manifest)
                self.assertIn(
                    'DURABILITY_MAINTENANCE_EVIDENCE_UNKNOWN',
                    issue_codes(result),
                )
                self.assertFalse(result.release_ready)

    def test_durability_false_and_zero_fail_closed(self):
        manifest = reviewed_manifest()
        manifest['durability_maintenance'][
            'initial_static_inspection_passed'] = False
        result = validate_manifest_structure(manifest)
        self.assertIn(
            'DURABILITY_STATIC_INSPECTION_NOT_PASSED', issue_codes(result))
        manifest = reviewed_manifest()
        manifest['durability_maintenance']['rated_cycle_life_cycles'] = 0
        result = validate_manifest_structure(manifest)
        self.assertIn('VALUE_OUT_OF_RANGE', issue_codes(result))

    def test_new_section_hash_cannot_borrow_cross_section_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest, artifact_root, cad_root = write_bound_release_fixture(
                directory)
            evidence_by_section = {
                record['sections'][0]: record
                for record in manifest['evidence_records']
            }
            manifest['passive_power_loss_safety'][
                'loss_of_power_hazard_analysis_sha256'] = (
                    evidence_by_section['contact_human_safety'][
                        'artifact_sha256'])
            result = validate_manifest(
                manifest,
                artifact_root=artifact_root,
                cad_root=cad_root,
            )
        scoped = [
            issue for issue in result.blockers
            if issue.code == 'HASH_EVIDENCE_SCOPE_MISMATCH'
        ]
        self.assertEqual(1, len(scoped), result.as_dict())
        self.assertEqual(
            '$.passive_power_loss_safety.'
            'loss_of_power_hazard_analysis_sha256',
            scoped[0].path,
        )

    def test_each_backend_method_deadline_is_mandatory_and_positive(self):
        for method in (
                'read_state', 'command_position', 'stop', 'close'):
            with self.subTest(method=method, value=None):
                manifest = reviewed_manifest()
                manifest['backend_execution_safety'][
                    'method_deadlines_s'][method] = None
                result = validate_manifest_structure(manifest)
                self.assertIn(
                    'BACKEND_METHOD_DEADLINES_UNKNOWN', issue_codes(result))
                self.assertFalse(result.release_ready)
            with self.subTest(method=method, value=0):
                manifest = reviewed_manifest()
                manifest['backend_execution_safety'][
                    'method_deadlines_s'][method] = 0
                result = validate_manifest_structure(manifest)
                self.assertIn('VALUE_OUT_OF_RANGE', issue_codes(result))

    def test_backend_release_and_profile_bindings_are_exact_and_required(self):
        cases = (
            (
                lambda section: section['release_binding'].__setitem__(
                    'runtime_release_id', None),
                'BACKEND_RELEASE_BINDING_UNKNOWN',
            ),
            (
                lambda section: section['release_binding'].__setitem__(
                    'release_manifest_sha256', None),
                'BACKEND_RELEASE_BINDING_UNKNOWN',
            ),
            (
                lambda section: section['motion_profile_binding'].__setitem__(
                    'profile_id', None),
                'BACKEND_PROFILE_BINDING_UNKNOWN',
            ),
            (
                lambda section: section['motion_profile_binding'].__setitem__(
                    'profile_manifest_sha256', None),
                'BACKEND_PROFILE_BINDING_UNKNOWN',
            ),
            (
                lambda section: section['motion_profile_binding'].__setitem__(
                    'approved_speed_grades', None),
                'BACKEND_APPROVED_SPEED_GRADES_UNKNOWN',
            ),
        )
        for mutate, code in cases:
            with self.subTest(code=code):
                manifest = reviewed_manifest()
                mutate(manifest['backend_execution_safety'])
                result = validate_manifest_structure(manifest)
                self.assertIn(code, issue_codes(result))
                self.assertFalse(result.release_ready)

    def test_stale_or_forged_backend_profile_binding_is_rejected(self):
        cases = (
            (
                lambda section: section['motion_profile_binding'].__setitem__(
                    'runtime_release_id', 'stale-runtime'),
                'BACKEND_PROFILE_RUNTIME_MISMATCH',
            ),
            (
                lambda section: section['motion_profile_binding'].__setitem__(
                    'profile_manifest_sha256',
                    section['release_binding']['release_manifest_sha256']),
                'BACKEND_BINDING_HASH_REUSE',
            ),
            (
                lambda section: section['motion_profile_binding'].__setitem__(
                    'approved_speed_grades', [10, 5]),
                'BACKEND_APPROVED_SPEED_GRADES_NOT_EXACT',
            ),
            (
                lambda section: section['motion_profile_binding'].__setitem__(
                    'approved_speed_grades', [5, 5]),
                'BACKEND_APPROVED_SPEED_GRADES_NOT_EXACT',
            ),
            (
                lambda section: section['motion_profile_binding'].__setitem__(
                    'approved_speed_grades', [0]),
                'VALUE_OUT_OF_RANGE',
            ),
        )
        for mutate, code in cases:
            with self.subTest(code=code):
                manifest = reviewed_manifest()
                mutate(manifest['backend_execution_safety'])
                result = validate_manifest_structure(manifest)
                self.assertIn(code, issue_codes(result))
                self.assertFalse(result.release_ready)

    def test_each_backend_method_requires_timeout_handling(self):
        for method in (
                'read_state', 'command_position', 'stop', 'close'):
            with self.subTest(method=method, value=None):
                manifest = reviewed_manifest()
                manifest['backend_execution_safety'][
                    'method_timeout_handling'][method] = None
                result = validate_manifest_structure(manifest)
                self.assertIn(
                    'BACKEND_METHOD_CANCELLATION_UNKNOWN',
                    issue_codes(result),
                )
                self.assertFalse(result.release_ready)
            with self.subTest(method=method, value='UNBOUNDED'):
                manifest = reviewed_manifest()
                manifest['backend_execution_safety'][
                    'method_timeout_handling'][method] = 'UNBOUNDED'
                result = validate_manifest_structure(manifest)
                self.assertIn('INVALID_ENUM', issue_codes(result))

    def test_stop_isolation_assertions_fail_closed(self):
        for key in (
                'independent_executor',
                'independent_lock_domain',
                'not_queued_behind_normal_commands',
                'hung_command_stop_deadline_verified',
                'deadline_miss_fails_closed'):
            with self.subTest(key=key):
                manifest = reviewed_manifest()
                manifest['backend_execution_safety'][
                    'stop_isolation'][key] = False
                result = validate_manifest_structure(manifest)
                self.assertIn(
                    'STOP_ISOLATION_NOT_PROVEN', issue_codes(result))
                self.assertFalse(result.release_ready)

    def test_hung_command_stop_deadline_is_mandatory_and_positive(self):
        for value, code in (
                (None, 'STOP_ISOLATION_UNKNOWN'),
                (0, 'VALUE_OUT_OF_RANGE')):
            with self.subTest(value=value):
                manifest = reviewed_manifest()
                manifest['backend_execution_safety']['stop_isolation'][
                    'hung_command_stop_deadline_s'] = value
                result = validate_manifest_structure(manifest)
                self.assertIn(code, issue_codes(result))
                self.assertFalse(result.release_ready)

    def test_backend_execution_evidence_hashes_are_mandatory(self):
        for key in (
                'backend_method_contract_sha256',
                'stop_isolation_architecture_sha256',
                'hung_command_stop_test_report_sha256'):
            with self.subTest(key=key):
                manifest = reviewed_manifest()
                manifest['backend_execution_safety'][key] = None
                result = validate_manifest_structure(manifest)
                self.assertIn(
                    'BACKEND_EXECUTION_EVIDENCE_UNKNOWN',
                    issue_codes(result),
                )
                self.assertFalse(result.release_ready)

    def test_backend_hash_cannot_borrow_other_section_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest, artifact_root, cad_root = write_bound_release_fixture(
                directory)
            evidence_by_section = {
                record['sections'][0]: record
                for record in manifest['evidence_records']
            }
            manifest['backend_execution_safety'][
                'hung_command_stop_test_report_sha256'] = (
                    evidence_by_section['stop_stationary_ack'][
                        'artifact_sha256'])
            result = validate_manifest(
                manifest,
                artifact_root=artifact_root,
                cad_root=cad_root,
            )
        scoped = [
            issue for issue in result.blockers
            if issue.code == 'HASH_EVIDENCE_SCOPE_MISMATCH'
        ]
        self.assertEqual(1, len(scoped), result.as_dict())
        self.assertEqual(
            '$.backend_execution_safety.'
            'hung_command_stop_test_report_sha256',
            scoped[0].path,
        )

    def test_backend_execution_hash_cannot_authenticate_arbitrary_text(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest, artifact_root, cad_root = write_bound_release_fixture(
                directory)
            rewrite_execution_artifact(
                manifest,
                artifact_root,
                'hung_command_stop_test_report_sha256',
                raw_payload=b'controlled evidence but no machine contract\n',
            )
            result = validate_manifest(
                manifest,
                artifact_root=artifact_root,
                cad_root=cad_root,
            )
        self.assertFalse(result.release_ready)
        self.assertIn(
            'BACKEND_EXECUTION_ARTIFACT_INVALID_JSON', issue_codes(result))

    def test_backend_method_artifact_rejects_non_native_timeout_evidence(self):
        mutations = (
            lambda value: value['methods']['command_position'].__setitem__(
                'python_timeout_thread_used', True),
            lambda value: value['methods']['command_position'].__setitem__(
                'native_timeout_implementation', 'PYTHON_TIMEOUT_THREAD'),
            lambda value: value['methods']['stop'].__setitem__(
                'deadline_s', 99.0),
            lambda value: value['methods']['read_state'].__setitem__(
                'native_deadline_enforced', False),
        )
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index), \
                    tempfile.TemporaryDirectory() as directory:
                manifest, artifact_root, cad_root = (
                    write_bound_release_fixture(directory))
                rewrite_execution_artifact(
                    manifest,
                    artifact_root,
                    'backend_method_contract_sha256',
                    mutate=mutate,
                )
                result = validate_manifest(
                    manifest,
                    artifact_root=artifact_root,
                    cad_root=cad_root,
                )
                self.assertFalse(result.release_ready)
                self.assertIn(
                    'BACKEND_METHOD_CONTRACT_NOT_PROVEN',
                    issue_codes(result),
                )

    def test_stop_architecture_requires_executor_channel_and_lock_isolation(self):
        mutations = (
            lambda value: value.__setitem__(
                'stop_executor_id', value['motion_executor_id']),
            lambda value: value.__setitem__(
                'stop_channel_id', value['motion_channel_id']),
            lambda value: value.__setitem__(
                'stop_lock_domain_id', value['motion_lock_domain_id']),
            lambda value: value.__setitem__('independent_channel', False),
            lambda value: value.__setitem__('shared_adapter_lock', True),
        )
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index), \
                    tempfile.TemporaryDirectory() as directory:
                manifest, artifact_root, cad_root = (
                    write_bound_release_fixture(directory))
                rewrite_execution_artifact(
                    manifest,
                    artifact_root,
                    'stop_isolation_architecture_sha256',
                    mutate=mutate,
                )
                result = validate_manifest(
                    manifest,
                    artifact_root=artifact_root,
                    cad_root=cad_root,
                )
                self.assertFalse(result.release_ready)
                self.assertIn(
                    'STOP_ISOLATION_ARCHITECTURE_NOT_PROVEN',
                    issue_codes(result),
                )

    def test_hung_send_report_rejects_late_stop_and_stale_binding(self):
        cases = (
            (
                lambda value: value['binding'].__setitem__(
                    'runtime_release_id', 'stale-runtime'),
                'BACKEND_EXECUTION_BINDING_MISMATCH',
            ),
            (
                lambda value: value.__setitem__(
                    'stop_completed_at_s',
                    value['motion_send_released_at_s'] + 0.1),
                'HUNG_COMMAND_STOP_PROBE_NOT_PROVEN',
            ),
            (
                lambda value: value.__setitem__(
                    'stop_completed_at_s',
                    value['stop_requested_at_s']
                    + value['stop_deadline_s'] + 0.01),
                'HUNG_COMMAND_STOP_PROBE_NOT_PROVEN',
            ),
            (
                lambda value: value.__setitem__(
                    'late_command_result_rejected', False),
                'HUNG_COMMAND_STOP_PROBE_NOT_PROVEN',
            ),
            (
                lambda value: value.__setitem__('final_state', 'STOPPING'),
                'HUNG_COMMAND_STOP_PROBE_NOT_PROVEN',
            ),
        )
        for index, (mutate, code) in enumerate(cases):
            with self.subTest(index=index), \
                    tempfile.TemporaryDirectory() as directory:
                manifest, artifact_root, cad_root = (
                    write_bound_release_fixture(directory))
                rewrite_execution_artifact(
                    manifest,
                    artifact_root,
                    'hung_command_stop_test_report_sha256',
                    mutate=mutate,
                )
                result = validate_manifest(
                    manifest,
                    artifact_root=artifact_root,
                    cad_root=cad_root,
                )
                self.assertFalse(result.release_ready)
                self.assertIn(code, issue_codes(result))

    def test_review_requires_evidence_reference(self):
        manifest = reviewed_manifest()
        manifest['tool_identity']['review']['evidence_ids'] = []
        result = validate_manifest_structure(manifest)
        self.assertIn('REVIEW_EVIDENCE_MISSING', issue_codes(result))
        self.assertIn('ORPHAN_EVIDENCE', issue_codes(result))

    def test_evidence_scope_must_cover_section(self):
        manifest = reviewed_manifest()
        manifest['evidence_records'][0]['sections'] = ['units']
        result = validate_manifest_structure(manifest)
        self.assertIn('EVIDENCE_SCOPE_MISMATCH', issue_codes(result))

    def test_unaccepted_evidence_blocks_release(self):
        manifest = reviewed_manifest()
        manifest['evidence_records'][0]['disposition'] = 'REJECTED'
        result = validate_manifest_structure(manifest)
        self.assertIn('EVIDENCE_NOT_ACCEPTED', issue_codes(result))

    def test_unreviewed_section_blocks_release_requested_true(self):
        manifest = reviewed_manifest()
        manifest['tool_identity']['review'] = {
            'reviewed': False,
            'evidence_ids': [],
            'reviewer': None,
            'reviewed_at_utc': None,
            'disposition': None,
        }
        result = validate_manifest_structure(manifest)
        self.assertIn('REVIEW_INCOMPLETE', issue_codes(result))
        self.assertFalse(result.release_ready)

    def test_ag_name_is_fail_closed(self):
        manifest = reviewed_manifest()
        manifest['controller_firmware']['actuator_model'] = (
            'mycobot_gripper_ag')
        result = validate_manifest_structure(manifest)
        self.assertIn('LEGACY_INPUT_DETECTED', issue_codes(result))

    def test_generic_servo_guess_is_fail_closed(self):
        manifest = reviewed_manifest()
        manifest['controller_firmware']['actuator_model'] = 'MG996R'
        result = validate_manifest_structure(manifest)
        self.assertIn('LEGACY_INPUT_DETECTED', issue_codes(result))

    def test_atom_and_shared_arm_transport_are_fail_closed(self):
        for value in (
                'Atom transport',
                'shared-arm transport',
                'shared_arm_transport'):
            with self.subTest(value=value):
                manifest = reviewed_manifest()
                manifest['transport_protocol']['transport_type'] = value
                result = validate_manifest_structure(manifest)
                self.assertIn('LEGACY_INPUT_DETECTED', issue_codes(result))

    def test_generic_and_hobby_servo_descriptions_are_fail_closed(self):
        for value in (
                'generic servo',
                'generic hobby servo X',
                'HOBBY-SERVO-X',
                'servo model unknown',
                'unbranded RC servomotor',
                '通用舵机',
                '未知型号舵机'):
            with self.subTest(value=value):
                manifest = reviewed_manifest()
                manifest['controller_firmware']['actuator_model'] = value
                result = validate_manifest_structure(manifest)
                self.assertIn('LEGACY_INPUT_DETECTED', issue_codes(result))

    def test_textual_legacy_values_are_fail_closed(self):
        forbidden_text = (
            'gripper_type = 1',
            'native command range 0 - 100',
            '255 is fully open',
            'opening is 20--45 mm',
            'tool weighs 100 g',
            'generated estimate 68.84 mm',
            'TCP (0, 0.0931, 0.0025)',
            'gripper_torque: 500',
            'protect_current = 200',
        )
        for value in forbidden_text:
            with self.subTest(value=value):
                manifest = reviewed_manifest()
                manifest['evidence_records'][0]['result'] = value
                result = validate_manifest_structure(manifest)
                self.assertIn('LEGACY_INPUT_DETECTED', issue_codes(result))

    def test_unicode_compatibility_cannot_hide_retired_ag_inputs(self):
        forbidden_text = (
            'ｍｙｃｏｂｏｔ＿ｇｒｉｐｐｅｒ＿ａｇ',
            'ｇｒｉｐｐｅｒ＿ｔｙｐｅ＝１',
            'native command range ０ − １００',
            '２５５ is fully open',
            'opening is ２０—４５ ｍｍ',
            'gripper\u200b_type = 1',
        )
        for value in forbidden_text:
            with self.subTest(value=value):
                manifest = reviewed_manifest()
                manifest['evidence_records'][0]['result'] = value
                result = validate_manifest_structure(manifest)
                self.assertIn('LEGACY_INPUT_DETECTED', issue_codes(result))

    def test_retired_ag_command_range_is_fail_closed(self):
        manifest = reviewed_manifest()
        native = manifest['motion_limits']['native_command_range']
        native['minimum'] = 0
        native['maximum'] = 100
        result = validate_manifest_structure(manifest)
        self.assertIn('LEGACY_INPUT_DETECTED', issue_codes(result))

    def test_retired_ag_opening_range_is_fail_closed(self):
        manifest = reviewed_manifest()
        manifest['motion_limits']['jaw_opening_range_m'] = {
            'minimum': 0.02,
            'maximum': 0.045,
        }
        result = validate_manifest_structure(manifest)
        self.assertIn('LEGACY_INPUT_DETECTED', issue_codes(result))

    def test_historical_mass_values_are_fail_closed(self):
        for mass in (0.1, 0.115, 0.17):
            with self.subTest(mass=mass):
                manifest = reviewed_manifest()
                manifest['mass_properties']['installed_tool_mass_kg'] = mass
                result = validate_manifest_structure(manifest)
                self.assertIn('LEGACY_INPUT_DETECTED', issue_codes(result))

    def test_generated_tcp_is_fail_closed(self):
        manifest = reviewed_manifest()
        manifest['flange_tcp']['mount_to_tcp_transform'][
            'translation_m'] = [0, 0.0931, 0.0025]
        result = validate_manifest_structure(manifest)
        self.assertIn('LEGACY_INPUT_DETECTED', issue_codes(result))

    def test_cli_returns_two_for_blocked_manifest_and_writes_report(self):
        with tempfile.TemporaryDirectory() as directory:
            report_path = Path(directory) / 'report.json'
            output = StringIO()
            with redirect_stdout(output):
                status = main([
                    str(MANIFEST_PATH), '--report', str(report_path)])
            self.assertEqual(2, status)
            report = json.loads(report_path.read_text(encoding='utf-8'))
            self.assertFalse(report['release_ready'])
            self.assertTrue(report['schema_valid'])
            self.assertGreaterEqual(report['blocker_count'], 100)
            self.assertEqual(report, json.loads(output.getvalue()))

    def test_cli_returns_zero_for_reviewed_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest, artifact_root, cad_root = write_bound_release_fixture(
                directory)
            manifest_path = Path(directory) / 'manifest.json'
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False),
                encoding='utf-8')
            with redirect_stdout(StringIO()):
                status = main([
                    str(manifest_path),
                    '--artifact-root', str(artifact_root),
                    '--cad-root', str(cad_root),
                ])
            self.assertEqual(0, status)

    def test_validation_does_not_mutate_manifest(self):
        manifest = reviewed_manifest()
        before = copy.deepcopy(manifest)
        validate_manifest_structure(manifest)
        self.assertEqual(before, manifest)


if __name__ == '__main__':
    unittest.main()

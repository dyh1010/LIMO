#!/usr/bin/env python3
"""Run the frozen ROS-independent V2 perception regression fail closed.

This command never imports a ROS client library, opens a camera, or starts a
node.  It runs the frozen offline test inventory, validates source and install
artifacts, and writes exactly one machine-readable report using exclusive
creation.  A passing offline regression is deliberately not field delivery
readiness.
"""

import argparse
import ast
import configparser
import hashlib
import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time
import traceback
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath


REPORT_KIND = 'perception_v2_frozen_offline_regression'
REPORT_SCHEMA_VERSION = 1
EXPECTED_TEST_COUNT = 141
EXPECTED_UNITTEST_COUNT = 108
EXPECTED_PYTEST_STYLE_COUNT = 33
EXPECTED_BASE_PYTEST_STYLE_COUNT = 27
EXPECTED_SELECTED_PYTEST_STYLE_COUNT = 6
EXPECTED_AST_COUNT = 59
EXPECTED_ROS1_TEST_COUNT = 29
EXPECTED_ROS1_AST_COUNT = 5
EXPECTED_GRAND_TEST_COUNT = 197
EXPECTED_POST_FIX_TEST_COUNT = 63
EXPECTED_POST_FIX_PERCEPTION_AST_COUNT = 6
EXPECTED_POST_FIX_ROS1_AST_COUNT = 19
EXPECTED_CURRENT_GENERATION_TEST_COUNT = 144
EXPECTED_CURRENT_GENERATION_PHYSICAL_TEST_COUNT = 147
EXPECTED_CURRENT_GENERATION_PERCEPTION_AST_COUNT = 9
EXPECTED_CURRENT_GENERATION_ROS1_AST_COUNT = 4
COMMAND_TIMEOUT_SEC = 900
COMMAND_OUTPUT_EDGE_CHARS = 2000
PYTEST_FILE_RESULT_PREFIX = 'OFFLINE_PYTEST_FILE_RESULT '
PYTEST_FILE_RESULT_SCHEMA_VERSION = 'offline_pytest_file_result/v1'
PYTEST_FILE_RESULT_RUNNER_KIND = 'offline_pytest_style_single_file'
PYTEST_STYLE_HELPER_RELATIVE = 'audit_tools/run_pytest_style_tests.py'
UNITTEST_FILE_RESULT_PREFIX = 'OFFLINE_UNITTEST_FILE_RESULT '
UNITTEST_FILE_RESULT_SCHEMA_VERSION = 'offline_unittest_file_result/v1'
UNITTEST_FILE_RESULT_RUNNER_KIND = 'stdlib_unittest_single_file_isolated'
WSL_UNITTEST_TARGET_MANIFEST_SCHEMA_VERSION = (
    'current_generation_wsl_unittest_target_manifest/v1')
UNITTEST_STYLE_HELPER_RELATIVE = 'audit_tools/run_unittest_file_tests.py'
PYTEST_STYLE_IMPORT_ROOTS = (
    'src/limo_cleanup_perception',
    'src/limo_cleanup_interfaces',
    '.',
)
PYTEST_STYLE_ENVIRONMENT_ALLOWLIST = frozenset({
    'COMSPEC',
    'LANG',
    'LC_ALL',
    'PATH',
    'PATHEXT',
    'SYSTEMDRIVE',
    'SYSTEMROOT',
    'TEMP',
    'TMP',
    'TMPDIR',
    'WINDIR',
})
UNITTEST_STYLE_IMPORT_ROOTS = (
    'src/limo_cleanup_perception',
    'ros1_overlay_src/limo_cleanup_ros1_perception/src',
    '.',
)
WSL_DISTRIBUTION = 'Ubuntu'
WSL_PYTHON_TARGET_IDENTITY = {
    'path': '/usr/bin/python3.14',
    'size_bytes': 7477096,
    'sha256': (
        'fa9796cd3a30878e11a2f40372f773d3fcd913fff35e5bee8dd9a036e22e93ab'),
}
WSL_PYTHON_VERSION = [3, 14, 4]
WSL_PYTHON_ENTRIES = ('/usr/bin/python3', '/usr/bin/python3.14')
EXACT_CLI_TEST_RELATIVE = (
    'src/limo_cleanup_perception/test/'
    'test_ros1_noetic_field_readiness_exact_cli.py')
EXACT_CLI_TEST_COUNT = 11
EXACT_CLI_POSIX_CASE_ID = (
    EXACT_CLI_TEST_RELATIVE + '::Ros1NoeticFieldReadinessExactCliTest.'
    'test_linklike_python_root_is_rejected_before_probe_load')
HOST_READINESS_TEST_RELATIVE = (
    'src/limo_cleanup_perception/test/test_ros1_noetic_field_readiness.py')
HOST_READINESS_POSIX_CASE_IDS = (
    HOST_READINESS_TEST_RELATIVE + '::Ros1NoeticFieldReadinessTest.'
    'test_linklike_authority_probe_rejects_before_fake_runner',
    HOST_READINESS_TEST_RELATIVE + '::Ros1NoeticFieldReadinessTest.'
    'test_linklike_artifact_is_rejected_when_platform_supports_links',
)
EXACT_CLI_POSIX_COMPANION_SUITE_ID = (
    'ros1_noetic_field_readiness_exact_cli_posix_companion')
HOST_READINESS_POSIX_SUITE_BY_CASE_ID = {
    HOST_READINESS_POSIX_CASE_IDS[0]: (
        'ros1_noetic_field_readiness_host_'
        'linklike_authority_posix_companion'),
    HOST_READINESS_POSIX_CASE_IDS[1]: (
        'ros1_noetic_field_readiness_host_'
        'linklike_artifact_posix_companion'),
}
ROS1_ISOLATED_PROBE_PYTHON3_SUITE_ID = 'rosbag1_isolated_probe_python3'
ROS1_ISOLATED_PROBE_PYTHON3_14_SUITE_ID = (
    'rosbag1_isolated_probe_python3_14')
ROS1_ISOLATED_PROBE_TEST_RELATIVE = (
    'ros1_overlay_src/limo_cleanup_ros1_perception/test/'
    'test_rosbag1_isolated_probe.py')
ROS1_ISOLATED_PROBE_TEST_COUNT = 18

ROS2_MIGRATION_INSTALL_GATE_ID = (
    'ROS2_AMENT_MIGRATION_OFFLINE_INSTALL_GATE')
ROS1_FIELD_INSTALL_GATE_ID = 'ROS1_NOETIC_FIELD_INSTALL'
ROS1_RUNTIME_ARCHITECTURE_BLOCKER = (
    'ROS1_NOETIC_PERCEPTION_RUNTIME_NOT_IMPLEMENTED')
ROS1_FIELD_INSTALL_EVIDENCE_MISSING_BLOCKER = (
    'ROS1_NOETIC_FIELD_INSTALL_EVIDENCE_MISSING')
ROS1_FIELD_INSTALL_EVIDENCE_NOT_VALIDATED_BLOCKER = (
    'ROS1_NOETIC_FIELD_INSTALL_EVIDENCE_NOT_VALIDATED')
ROS1_BUILD_INSTALL_NOT_VERIFIED_BLOCKER = (
    'ROS1_NOETIC_BUILD_INSTALL_NOT_VERIFIED')
ROS1_BUILD_ENVIRONMENT_BLOCKER = (
    'WSL_E_ACCESSDENIED_BEFORE_SHELL_OR_BUILD')
ROS1_BUILD_ATTEMPT_RELATIVE = (
    'evidence/ros1_noetic_isolated_build_attempt_20260814T100918Z_v1.json')
ROS1_BUILD_ATTEMPT_EXPECTED_SIZE_BYTES = 9310
ROS1_BUILD_ATTEMPT_EXPECTED_SHA256 = (
    '8e432d3d70300bbc8fccf4ccd1274d03b79b4fc43100d055afb7f8d7594e4a77')
DEFAULT_ROS1_FIELD_INSTALL_EVIDENCE_RELATIVE = (
    'evidence/ros1_noetic_field_install_evidence.json')
ROS1_CANONICAL_SOURCE_ADMISSION_RELATIVE = (
    'evidence/perception_v2_offline_20260813/'
    'ros1_noetic_canonical_source_admission_20260815_v5.json')
ROS1_CANONICAL_SOURCE_ADMISSION_GATE_ID = (
    'ROS1_NOETIC_CANONICAL_SOURCE_ADMISSION')
ROS1_CANONICAL_ADMISSION_MANIFEST_MISSING = (
    'ROS1_FIELD_INSTALL_CANONICAL_SOURCE_ADMISSION_MANIFEST_MISSING')
ROS1_CANONICAL_ADMISSION_MANIFEST_INVALID = (
    'ROS1_FIELD_INSTALL_CANONICAL_SOURCE_ADMISSION_MANIFEST_INVALID')
ROS1_CANONICAL_ADMISSION_MANIFEST_LINK_FORBIDDEN = (
    'ROS1_FIELD_INSTALL_CANONICAL_SOURCE_ADMISSION_MANIFEST_LINK_FORBIDDEN')
ROS1_CANONICAL_ADMISSION_MANIFEST_IDENTITY_NOT_BOUND = (
    'ROS1_FIELD_INSTALL_CANONICAL_SOURCE_ADMISSION_MANIFEST_IDENTITY_NOT_BOUND')
ROS1_CANONICAL_ADMISSION_BINDING_UNAVAILABLE = (
    'ROS1_FIELD_INSTALL_CANONICAL_SOURCE_BINDING_UNAVAILABLE')
ROS1_CANONICAL_ADMISSION_BINDING_MISMATCH = (
    'ROS1_FIELD_INSTALL_CANONICAL_SOURCE_ADMISSION_BINDING_MISMATCH')

EVIDENCE_AUTHORITY_GATE_ID = 'PERCEPTION_V2_EVIDENCE_AUTHORITY_SELECTION'
EVIDENCE_AUTHORITY_INDEX_RELATIVE = (
    'evidence/perception_v2_offline_20260813/'
    'perception_v2_evidence_authority_index_20260814_v1.json')
EVIDENCE_AUTHORITY_SCHEMA_VERSION = (
    'perception_v2_evidence_authority_index/v1')
EVIDENCE_AUTHORITY_INDEX_ID = (
    'perception-v2-evidence-authority-20260814-v1')
EVIDENCE_AUTHORITY_INDEX_KIND = 'immutable_evidence_lineage_authority'
EVIDENCE_AUTHORITY_LINEAGE = (
    'perception_v2_ros1_canonical_source_binding')
EVIDENCE_AUTHORITY_CURRENT_ID = 'ros1_canonical_source_binding_v7'
EVIDENCE_AUTHORITY_CURRENT_STATUS = 'CURRENT_BLOCKED_OFFLINE_BASELINE'
EVIDENCE_AUTHORITY_CURRENT_SCOPE = (
    'offline_regression_only_not_field_3d_tf_build_or_runtime')

# Filled from the exclusively-created authority index.  Unlike an identity
# declared inside that JSON, this out-of-band identity prevents a modified
# index from remaining self-consistent.  The production loader refuses to
# select evidence unless both values match.
EVIDENCE_AUTHORITY_INDEX_EXPECTED_SIZE_BYTES = 2620
EVIDENCE_AUTHORITY_INDEX_EXPECTED_SHA256 = (
    'b4fcfb11c37cf44a4be61cd14d4cf1e28eee5657037887e403a021e9959a5283')

EXPECTED_EVIDENCE_AUTHORITY_ENTRIES = (
    {
        'evidence_id': 'ros1_canonical_source_binding_v6',
        'path': (
            'evidence/perception_v2_offline_20260813/'
            'frozen_offline_regression_20260814_'
            'ros1_canonical_source_binding_v6.json'),
        'size_bytes': 188673,
        'sha256': (
            'd2cb327499c79cd6f90f1ac7f72a9edb52dac85d08cb8dc563d1e078776b6239'),
        'lifecycle': 'STALE',
        'status': 'STALE_FAILED_REGRESSION',
        'is_current': False,
        'current_baseline': False,
        'scope': EVIDENCE_AUTHORITY_CURRENT_SCOPE,
        'regression_passed': False,
        'delivery_ready': False,
        'authorizes_field_delivery': False,
    },
    {
        'evidence_id': 'ros1_canonical_source_binding_v6_final',
        'path': (
            'evidence/perception_v2_offline_20260813/'
            'frozen_offline_regression_20260814_'
            'ros1_canonical_source_binding_v6_final.json'),
        'size_bytes': 189637,
        'sha256': (
            'dd7290195cdd6776eb8d8e6d8db4c4cbeb8b87f49be760b7c39fdc9392181a87'),
        'lifecycle': 'SUPERSEDED',
        'status': 'NON_CURRENT_SUPERSEDED_INTERMEDIATE',
        'is_current': False,
        'current_baseline': False,
        'scope': EVIDENCE_AUTHORITY_CURRENT_SCOPE,
        'regression_passed': False,
        'delivery_ready': False,
        'authorizes_field_delivery': False,
    },
    {
        'evidence_id': EVIDENCE_AUTHORITY_CURRENT_ID,
        'path': (
            'evidence/perception_v2_offline_20260813/'
            'frozen_offline_regression_20260814_'
            'ros1_canonical_source_binding_v7.json'),
        'size_bytes': 190747,
        'sha256': (
            'dac31ed678ff7c3a8f4494c5b865f89a41715ee5555e80ef12a8ba4b895f6789'),
        'lifecycle': 'CURRENT',
        'status': EVIDENCE_AUTHORITY_CURRENT_STATUS,
        'is_current': True,
        'current_baseline': True,
        'scope': EVIDENCE_AUTHORITY_CURRENT_SCOPE,
        'regression_passed': False,
        'delivery_ready': False,
        'authorizes_field_delivery': False,
    },
)

GIT_ENVIRONMENT_AUDIT_KEYS = (
    'GIT_CONFIG_COUNT',
    'GIT_CONFIG_PARAMETERS',
    'GIT_CONFIG',
    'GIT_CONFIG_SYSTEM',
    'GIT_CONFIG_GLOBAL',
    'GIT_CONFIG_NOSYSTEM',
    'GIT_DIR',
    'GIT_COMMON_DIR',
    'GIT_WORK_TREE',
    'GIT_INDEX_FILE',
    'GIT_OBJECT_DIRECTORY',
    'GIT_ALTERNATE_OBJECT_DIRECTORIES',
    'GIT_QUARANTINE_PATH',
    'GIT_NAMESPACE',
    'GIT_REPLACE_REF_BASE',
    'GIT_SHALLOW_FILE',
    'GIT_CEILING_DIRECTORIES',
    'GIT_DISCOVERY_ACROSS_FILESYSTEM',
)
GIT_ENVIRONMENT_AUDIT_PREFIXES = (
    'GIT_', 'GIT_CONFIG_KEY_', 'GIT_CONFIG_VALUE_',
)
GIT_REPOSITORY_REDIRECTION_KEYS = frozenset({
    'GIT_DIR',
    'GIT_COMMON_DIR',
    'GIT_WORK_TREE',
    'GIT_INDEX_FILE',
    'GIT_OBJECT_DIRECTORY',
    'GIT_ALTERNATE_OBJECT_DIRECTORIES',
    'GIT_QUARANTINE_PATH',
    'GIT_NAMESPACE',
    'GIT_REPLACE_REF_BASE',
    'GIT_SHALLOW_FILE',
})

UNITTEST_TARGETS = (
    ('src.limo_cleanup_perception.test.test_evidence_binding', 3),
    ('src.limo_cleanup_perception.test.test_image_conversion', 4),
    ('src.limo_cleanup_perception.test.test_orchestration_contract', 5),
    ('src.limo_cleanup_perception.test.test_perception_core', 13),
    ('src.limo_cleanup_perception.test.test_perception_evaluator', 19),
    ('src.limo_cleanup_perception.test.test_perception_frame_io', 2),
    ('src.limo_cleanup_perception.test.test_perception_readiness', 28),
    ('src.limo_cleanup_perception.test.test_rgbd_bag_indexer', 20),
    ('src.limo_cleanup_perception.test.test_source_release_chain', 1),
    ('src.limo_cleanup_perception.test.test_target_contract', 7),
    ('src.limo_cleanup_perception.test.test_typed_raw_binding', 6),
)

PYTEST_STYLE_FILES = (
    ('test_dual_model_source_contract.py', 5),
    ('test_offline_dual_detector_source_contract.py', 1),
    ('test_orchestration_source_contract.py', 2),
    ('test_perception_collector_source_contract.py', 2),
    ('test_rgbd_contract.py', 9),
    ('test_source_manifest_script.py', 2),
    ('test_task_actions.py', 6),
)

# These six exact IDs are part of the frozen 141 baseline.  New source-contract
# tests may be added without silently changing this release denominator; they
# must be deliberately promoted in a future frozen baseline revision.
PYTEST_STYLE_TARGETS = (
    ('test_perception_readiness_source_contract.py', (
        'test_installed_layout_without_workspace_source_fails_closed',
        'test_package_declares_python_runtime_dependencies',
        'test_perception_package_publishers_remain_on_exact_read_only_allowlist',
        'test_readiness_is_pure_offline_and_has_no_motion_api',
        'test_report_is_fail_closed_read_only_and_exclusive',
        'test_setup_installs_python38_readiness_entry_and_fixtures',
    )),
)

ENVIRONMENT_ONLY_TEST_FILES = {
    'test_copyright.py',
    'test_detection_gate.py',
    'test_flake8.py',
    'test_pep257.py',
}
POST_FREEZE_TEST_FILES = {
    'test_camera_query_allowlist.py',
    'test_frozen_regression_runner.py',
    'test_perception_field_intake.py',
    'test_ros1_dabai_runtime_contract.py',
}
POST_FREEZE_TEST_COUNTS = {
    'test_camera_query_allowlist.py': 5,
    'test_frozen_regression_runner.py': 7,
    'test_perception_field_intake.py': 10,
    'test_ros1_dabai_runtime_contract.py': 5,
}
POST_FREEZE_PYTEST_STYLE_FILES = (
    'test_camera_query_allowlist.py',
    'test_frozen_regression_runner.py',
    'test_ros1_dabai_runtime_contract.py',
)
POST_FREEZE_UNITTEST_MODULES = (
    'src.limo_cleanup_perception.test.test_perception_field_intake',
)

# Supplemental validators are deliberately outside the current 195-test
# release denominator.  Older 194-test evidence remains immutable historical
# evidence; the new rosbag-envelope test is admitted only by this source
# generation.  Supplemental tests retain an independent denominator.
SUPPLEMENTAL_UNITTEST_TARGETS = (
    ('src.limo_cleanup_perception.test.test_ros1_field_install_gate', 10),
)
SUPPLEMENTAL_UNITTEST_SELECTED_IDS = (
    'src.limo_cleanup_perception.test.test_ros1_field_install_gate.'
    'Ros1FieldInstallGateTest.'
    'test_complete_synthetic_install_cannot_clear_runtime_blocker',
    'src.limo_cleanup_perception.test.test_ros1_field_install_gate.'
    'Ros1FieldInstallGateTest.'
    'test_indexer_only_source_package_is_architecture_blocked',
    'src.limo_cleanup_perception.test.test_ros1_field_install_gate.'
    'Ros1FieldInstallGateTest.'
    'test_source_contract_rejects_missing_required_assets',
    'src.limo_cleanup_perception.test.test_ros1_field_install_gate.'
    'Ros1FieldInstallGateTest.'
    'test_source_contract_rejects_rclpy_and_ament_only_runtime',
    'src.limo_cleanup_perception.test.test_ros1_field_install_gate.'
    'Ros1FieldInstallGateTest.'
    'test_synthetic_install_is_neither_runtime_nor_delivery_ready',
    'src.limo_cleanup_perception.test.test_ros1_field_install_gate.'
    'Ros1FieldInstallGateTest.'
    'test_validator_live_audit_rejects_indexer_only_workspace',
    'src.limo_cleanup_perception.test.test_ros1_field_install_gate.'
    'Ros1FieldInstallGateTest.'
    'test_validator_rejects_installed_artifact_hash_mismatch',
    'src.limo_cleanup_perception.test.test_ros1_field_install_gate.'
    'Ros1FieldInstallGateTest.'
    'test_validator_rejects_linklike_or_non_regular_artifact',
    'src.limo_cleanup_perception.test.test_ros1_field_install_gate.'
    'Ros1FieldInstallGateTest.'
    'test_validator_rejects_ros2_ament_prefix_masquerading_as_ros1',
    'src.limo_cleanup_perception.test.test_ros1_field_install_gate.'
    'Ros1FieldInstallGateTest.'
    'test_validator_rejects_unentered_environment_and_exit_mismatch',
)

# These trust-root/runtime suites remain outside the current 195+10 baseline.
# They are mandatory for every new run, but retain an independent denominator
# so historical 194+10/57-test evidence is never relabelled.
POST_FIX_PYTEST_STYLE_FILES = (
    ('ros1_model_binding_contract', 'test_ros1_model_binding_contract.py', 18),
    ('ros1_semantic_readiness', 'test_ros1_semantic_readiness.py', 23),
)
POST_FIX_SELECTED_PYTEST_STYLE_TARGETS = (
    ('ros1_runtime_source_contract', 'test_ros1_runtime_source_contract.py', (
        'test_actual_overlay_source_implementation_passes_but_field_stays_blocked',
        'test_source_audit_rejects_missing_ros2_link_and_model_hash_drift',
        'test_messages_and_wrappers_expose_only_typed_read_only_observations',
        'test_ros1_adapter_has_exact_read_only_publish_surface',
        'test_observation_contract_rejects_frame_stamp_depth_and_tf_errors',
        'test_observation_id_is_deterministic_and_identity_bound',
        'test_field_readiness_requires_four_formal_live_audited_scenes',
    )),
)
POST_FIX_UNITTEST_TARGETS = (
    ('ros1_source_integrity_trust_root',
     'src.limo_cleanup_perception.test.test_ros1_source_integrity_trust_root',
     15),
)

# This generation is mandatory for current source, but is intentionally kept
# outside both the current 195+10 baseline and the current 63-test post-fix
# denominator.  Older 194+10/57-test reports remain immutable.  The one
# source-admission test shares a file with the historical selected suite, so
# its exact test ID is independently selected.
CURRENT_GENERATION_PYTEST_STYLE_FILES = (
    ('ros1_formal_rosbag1_admission',
     'test_ros1_formal_rosbag1_admission.py', 18),
    ('ros1_delivery_install_gate_layering',
     'test_ros1_delivery_install_gate_layering.py', 3),
)
CURRENT_GENERATION_SELECTED_PYTEST_STYLE_TARGETS = (
    ('ros1_formal_rosbag1_source_admission',
     'test_ros1_runtime_source_contract.py', (
         'test_formal_rosbag1_source_admission_rejects_drift_and_legacy_manifest',
     )),
    ('readiness_bundle_manifest_binding',
     'test_perception_readiness_source_contract.py', (
         'test_bundle_template_uses_the_frozen_six_topic_manifest_identity',
     )),
)
CURRENT_GENERATION_UNITTEST_TARGETS = (
    ('diagnostic_evidence_lineage',
     'src.limo_cleanup_perception.test.test_diagnostic_evidence_lineage', 9),
    ('ros1_runtime_behavior',
     'src.limo_cleanup_perception.test.test_ros1_runtime_behavior', 10),
    ('ros1_runtime_implementation_admission',
     'src.limo_cleanup_perception.test.'
     'test_ros1_runtime_implementation_admission', 20),
    ('ros1_noetic_field_readiness_host',
     'src.limo_cleanup_perception.test.test_ros1_noetic_field_readiness', 22),
)
CURRENT_GENERATION_SELECTED_UNITTEST_TARGETS = (
    ('ros1_field_install_new_gates',
     'src.limo_cleanup_perception.test.test_ros1_field_install_gate', (
         'src.limo_cleanup_perception.test.test_ros1_field_install_gate.'
         'Ros1FieldInstallGateTest.'
         'test_host_fresh_import_probe_executes_and_binds_evidence_module',
         'src.limo_cleanup_perception.test.test_ros1_field_install_gate.'
         'Ros1FieldInstallGateTest.'
         'test_distribution_artifact_and_junit_are_host_recomputed',
         'src.limo_cleanup_perception.test.test_ros1_field_install_gate.'
         'Ros1FieldInstallGateTest.'
         'test_build_source_space_is_exactly_the_audited_isolation_root',
         'src.limo_cleanup_perception.test.test_ros1_field_install_gate.'
         'Ros1FieldInstallGateTest.'
         'test_validator_recomputes_runtime_dependency_inventory',
         'src.limo_cleanup_perception.test.test_ros1_field_install_gate.'
         'Ros1FieldInstallGateTest.'
         'test_validator_requires_isolated_prefix_import_smoke',
     )),
)
CURRENT_GENERATION_ROS1_UNITTEST_TARGETS = (
    ('ros1_adapter_pure_fake',
     'ros1_overlay_src/limo_cleanup_ros1_perception/test/'
     'test_ros1_adapter_pure_fake.py', 2),
    ('ros1_runtime_install_contract',
     'ros1_overlay_src/limo_cleanup_ros1_perception/test/'
     'test_runtime_install_contract.py', 6),
)

# Strict file/interpreter evidence added by this successor generation.  The
# Windows exact suite has one explicitly platform-composed symlink case; its
# POSIX execution is an additional physical observation, not another logical
# test.  The probe suite is intentionally executed under both declared WSL
# entry paths, even though both currently resolve to the same anchored target.
CURRENT_GENERATION_EXACT_UNITTEST_TARGET = (
    'ros1_noetic_field_readiness_exact_cli',
    EXACT_CLI_TEST_RELATIVE,
    EXACT_CLI_TEST_COUNT,
)
CURRENT_GENERATION_WSL_UNITTEST_TARGETS = (
    (EXACT_CLI_POSIX_COMPANION_SUITE_ID,
     EXACT_CLI_TEST_RELATIVE, '/usr/bin/python3',
     (EXACT_CLI_POSIX_CASE_ID,)),
    (HOST_READINESS_POSIX_SUITE_BY_CASE_ID[
         HOST_READINESS_POSIX_CASE_IDS[0]],
     HOST_READINESS_TEST_RELATIVE, '/usr/bin/python3',
     (HOST_READINESS_POSIX_CASE_IDS[0],)),
    (HOST_READINESS_POSIX_SUITE_BY_CASE_ID[
         HOST_READINESS_POSIX_CASE_IDS[1]],
     HOST_READINESS_TEST_RELATIVE, '/usr/bin/python3',
     (HOST_READINESS_POSIX_CASE_IDS[1],)),
    (ROS1_ISOLATED_PROBE_PYTHON3_SUITE_ID,
     ROS1_ISOLATED_PROBE_TEST_RELATIVE,
     '/usr/bin/python3', None),
    (ROS1_ISOLATED_PROBE_PYTHON3_14_SUITE_ID,
     ROS1_ISOLATED_PROBE_TEST_RELATIVE,
     '/usr/bin/python3.14', None),
)

POST_FIX_PERCEPTION_AST_FILES = (
    'src/limo_cleanup_perception/limo_cleanup_perception/'
    'ros1_source_core_admission.py',
    'src/limo_cleanup_perception/limo_cleanup_perception/'
    'stdlib_attestation.py',
    'src/limo_cleanup_perception/test/test_ros1_model_binding_contract.py',
    'src/limo_cleanup_perception/test/test_ros1_runtime_source_contract.py',
    'src/limo_cleanup_perception/test/test_ros1_semantic_readiness.py',
    'src/limo_cleanup_perception/test/'
    'test_ros1_source_integrity_trust_root.py',
)

CURRENT_GENERATION_PERCEPTION_AST_FILES = (
    'src/limo_cleanup_perception/limo_cleanup_perception/'
    'diagnostic_evidence_lineage.py',
    'src/limo_cleanup_perception/test/test_diagnostic_evidence_lineage.py',
    'src/limo_cleanup_perception/test/test_ros1_formal_rosbag1_admission.py',
    'src/limo_cleanup_perception/test/'
    'test_ros1_delivery_install_gate_layering.py',
    'src/limo_cleanup_perception/test/test_ros1_runtime_behavior.py',
    'src/limo_cleanup_perception/test/'
    'test_ros1_runtime_implementation_admission.py',
    'src/limo_cleanup_perception/limo_cleanup_perception/'
    'ros1_noetic_field_readiness.py',
    'src/limo_cleanup_perception/test/test_ros1_noetic_field_readiness.py',
    EXACT_CLI_TEST_RELATIVE,
)

CURRENT_GENERATION_ROS1_AST_FILES = tuple(
    relative for _suite_id, relative, _expected
    in CURRENT_GENERATION_ROS1_UNITTEST_TARGETS) + (
        'ros1_overlay_src/limo_cleanup_ros1_perception/src/'
        'limo_cleanup_ros1_perception/rosbag1_isolated_probe.py',
        ROS1_ISOLATED_PROBE_TEST_RELATIVE,
    )

ROS1_INDEXER_TEST = (
    'ros1_overlay_src/limo_cleanup_ros1_perception/test/'
    'test_rosbag1_rgbd_indexer.py')
ROS1_AST_FILES = (
    'ros1_overlay_src/limo_cleanup_ros1_perception/setup.py',
    'ros1_overlay_src/limo_cleanup_ros1_perception/scripts/'
    'rosbag1_rgbd_indexer.py',
    'ros1_overlay_src/limo_cleanup_ros1_perception/src/'
    'limo_cleanup_ros1_perception/__init__.py',
    'ros1_overlay_src/limo_cleanup_ros1_perception/src/'
    'limo_cleanup_ros1_perception/rosbag1_rgbd_indexer.py',
    ROS1_INDEXER_TEST,
)

POST_FIX_ROS1_AST_FILES = (
    'ros1_overlay_src/limo_cleanup_ros1_perception/scripts/'
    'dual_model_detector.py',
    'ros1_overlay_src/limo_cleanup_ros1_perception/scripts/'
    'perception_frame_adapter.py',
    'ros1_overlay_src/limo_cleanup_ros1_perception/scripts/'
    'perception_frame_collector.py',
    'ros1_overlay_src/limo_cleanup_ros1_perception/scripts/'
    'perception_readiness.py',
    'ros1_overlay_src/limo_cleanup_ros1_perception/scripts/'
    'typed_raw_binding.py',
    'ros1_overlay_src/limo_cleanup_ros1_perception/src/'
    'limo_cleanup_ros1_perception/dual_model_detector.py',
    'ros1_overlay_src/limo_cleanup_ros1_perception/src/'
    'limo_cleanup_ros1_perception/evidence_binding.py',
    'ros1_overlay_src/limo_cleanup_ros1_perception/src/'
    'limo_cleanup_ros1_perception/image_conversion.py',
    'ros1_overlay_src/limo_cleanup_ros1_perception/src/'
    'limo_cleanup_ros1_perception/model_binding_contract.py',
    'ros1_overlay_src/limo_cleanup_ros1_perception/src/'
    'limo_cleanup_ros1_perception/orchestration_contract.py',
    'ros1_overlay_src/limo_cleanup_ros1_perception/src/'
    'limo_cleanup_ros1_perception/perception_core.py',
    'ros1_overlay_src/limo_cleanup_ros1_perception/src/'
    'limo_cleanup_ros1_perception/perception_frame_collector.py',
    'ros1_overlay_src/limo_cleanup_ros1_perception/src/'
    'limo_cleanup_ros1_perception/perception_frame_io.py',
    'ros1_overlay_src/limo_cleanup_ros1_perception/src/'
    'limo_cleanup_ros1_perception/perception_readiness.py',
    'ros1_overlay_src/limo_cleanup_ros1_perception/src/'
    'limo_cleanup_ros1_perception/rgbd_contract.py',
    'ros1_overlay_src/limo_cleanup_ros1_perception/src/'
    'limo_cleanup_ros1_perception/ros1_adapter.py',
    'ros1_overlay_src/limo_cleanup_ros1_perception/src/'
    'limo_cleanup_ros1_perception/source_core_binding.py',
    'ros1_overlay_src/limo_cleanup_ros1_perception/src/'
    'limo_cleanup_ros1_perception/target_contract.py',
    'ros1_overlay_src/limo_cleanup_ros1_perception/src/'
    'limo_cleanup_ros1_perception/typed_raw_binding.py',
)

# This is the exact 59-file Python-3.8 syntax scope accepted before this
# regression harness and its dedicated self-test were added.  The harness and
# self-test are separately hashed and tested; they must not silently change the
# frozen AST denominator.
FROZEN_AST_FILES = (
    'src/limo_cleanup_perception/setup.py',
    'src/limo_cleanup_perception/limo_cleanup_perception/__init__.py',
    'src/limo_cleanup_perception/limo_cleanup_perception/detection_gate.py',
    'src/limo_cleanup_perception/limo_cleanup_perception/dual_model_detector.py',
    'src/limo_cleanup_perception/limo_cleanup_perception/evidence_binding.py',
    'src/limo_cleanup_perception/limo_cleanup_perception/image_conversion.py',
    'src/limo_cleanup_perception/limo_cleanup_perception/mock_perception.py',
    'src/limo_cleanup_perception/limo_cleanup_perception/offline_dual_detector.py',
    'src/limo_cleanup_perception/limo_cleanup_perception/orchestration_contract.py',
    'src/limo_cleanup_perception/limo_cleanup_perception/perception_core.py',
    'src/limo_cleanup_perception/limo_cleanup_perception/perception_evaluator.py',
    'src/limo_cleanup_perception/limo_cleanup_perception/perception_frame_collector.py',
    'src/limo_cleanup_perception/limo_cleanup_perception/perception_frame_io.py',
    'src/limo_cleanup_perception/limo_cleanup_perception/perception_readiness.py',
    'src/limo_cleanup_perception/limo_cleanup_perception/rgbd_bag_indexer.py',
    'src/limo_cleanup_perception/limo_cleanup_perception/rgbd_contract.py',
    'src/limo_cleanup_perception/limo_cleanup_perception/target_contract.py',
    'src/limo_cleanup_perception/limo_cleanup_perception/task_actions.py',
    'src/limo_cleanup_perception/limo_cleanup_perception/typed_raw_binding.py',
    'src/limo_cleanup_perception/test/test_copyright.py',
    'src/limo_cleanup_perception/test/test_detection_gate.py',
    'src/limo_cleanup_perception/test/test_dual_model_source_contract.py',
    'src/limo_cleanup_perception/test/test_evidence_binding.py',
    'src/limo_cleanup_perception/test/test_flake8.py',
    'src/limo_cleanup_perception/test/test_image_conversion.py',
    'src/limo_cleanup_perception/test/test_offline_dual_detector_source_contract.py',
    'src/limo_cleanup_perception/test/test_orchestration_contract.py',
    'src/limo_cleanup_perception/test/test_orchestration_source_contract.py',
    'src/limo_cleanup_perception/test/test_pep257.py',
    'src/limo_cleanup_perception/test/test_perception_collector_source_contract.py',
    'src/limo_cleanup_perception/test/test_perception_core.py',
    'src/limo_cleanup_perception/test/test_perception_evaluator.py',
    'src/limo_cleanup_perception/test/test_perception_frame_io.py',
    'src/limo_cleanup_perception/test/test_perception_readiness.py',
    'src/limo_cleanup_perception/test/test_perception_readiness_source_contract.py',
    'src/limo_cleanup_perception/test/test_rgbd_bag_indexer.py',
    'src/limo_cleanup_perception/test/test_rgbd_contract.py',
    'src/limo_cleanup_perception/test/test_source_manifest_script.py',
    'src/limo_cleanup_perception/test/test_source_release_chain.py',
    'src/limo_cleanup_perception/test/test_target_contract.py',
    'src/limo_cleanup_perception/test/test_task_actions.py',
    'src/limo_cleanup_perception/test/test_typed_raw_binding.py',
    'scripts/audit_ros1_catkin_overlay.py',
    'scripts/generate_perception_source_manifest.py',
    'scripts/perception_release_policy.py',
    'scripts/perception_release_preflight.py',
    'scripts/run_v1_frozen_offline_regression.py',
    'scripts/smoke_test_tracked_base.py',
    'scripts/smoke_test_tracked_zero_launch.py',
    'scripts/test_ros1_base_bridge_offline.py',
    'scripts/test_ros1_v1_navigation_offline.py',
    'scripts/touch_only_smoke_probe.py',
    'scripts/training/prelabel.py',
    'scripts/training/prepare_dataset.py',
    'scripts/training/train_nongfu.py',
    'scripts/verify_ros1_bridge_ros2_zero_output.py',
    'scripts/verify_ros2_zero_stage_handoff.py',
    'scripts/verify_tracked_stage2_topology.py',
    'scripts/verify_tracked_zero_output.py',
)

EXPECTED_CONSOLE_ENTRIES = {
    'detection_gate': 'limo_cleanup_perception.detection_gate:main',
    'dual_model_detector': 'limo_cleanup_perception.dual_model_detector:main',
    'mock_perception': 'limo_cleanup_perception.mock_perception:main',
    'offline_dual_detector': 'limo_cleanup_perception.offline_dual_detector:main',
    'perception_evaluator': 'limo_cleanup_perception.perception_evaluator:main',
    'perception_frame_collector': (
        'limo_cleanup_perception.perception_frame_collector:main'),
    'perception_readiness': 'limo_cleanup_perception.perception_readiness:main',
    'rgbd_bag_indexer': 'limo_cleanup_perception.rgbd_bag_indexer:main',
    'typed_raw_binding': 'limo_cleanup_perception.typed_raw_binding:main',
}

CORE_FIXTURES = {
    'dabai_camera_query_allowlist.json',
    'orchestration_typed_frames.json',
    'perception_field_intake.schema.json',
    'perception_field_intake_template.json',
    'perception_readiness_bundle_template.json',
    'perception_readiness_missing_bundle.json',
    'perception_readiness_negative_cases.json',
    'rgbd_expected_topics.json',
}

PUBLISHER_ALLOWLIST = {
    'detection_gate.py': 2,
    'dual_model_detector.py': 3,
    'mock_perception.py': 1,
}

OFFLINE_TOOLS = (
    'evidence_binding.py',
    'perception_evaluator.py',
    'perception_frame_io.py',
    'perception_readiness.py',
    'rgbd_bag_indexer.py',
    'rgbd_contract.py',
    'target_contract.py',
    'typed_raw_binding.py',
)

EXCLUDED_SNAPSHOT_PARTS = {'__pycache__', '.pytest_cache'}
EXCLUDED_SNAPSHOT_SUFFIXES = {'.pyc', '.pyo'}


def _sha256_bytes(value):
    return hashlib.sha256(value).hexdigest()


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _relative(path, workspace):
    return Path(path).resolve().relative_to(workspace.resolve()).as_posix()


def _is_linklike(path):
    path = Path(path)
    try:
        value = path.lstat()
    except OSError:
        return False
    if stat.S_ISLNK(value.st_mode):
        return True
    attributes = getattr(value, 'st_file_attributes', 0)
    return bool(attributes & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0))


def _identity(path, relative_to=None):
    path = Path(path)
    result = {
        'path': (path.relative_to(relative_to).as_posix()
                 if relative_to is not None else str(path)),
        'size_bytes': path.stat().st_size,
        'sha256': sha256_file(path),
    }
    return result


def _canonical_set_sha256(entries):
    canonical = json.dumps(
        entries, ensure_ascii=False, sort_keys=True,
        separators=(',', ':')).encode('utf-8')
    return _sha256_bytes(canonical)


def _snapshot_paths(workspace, report_path=None):
    workspace = Path(workspace).resolve(strict=True)
    excluded_report = (None if report_path is None
                       else Path(report_path).resolve())
    paths = set()
    for relative_root in (
            'src/limo_cleanup_interfaces', 'src/limo_cleanup_perception',
            'ros1_overlay_src/limo_cleanup_ros1_perception'):
        root = workspace / relative_root
        if not root.is_dir():
            continue
        for path in root.rglob('*'):
            relative = path.relative_to(root)
            if (not path.is_file()
                    or set(relative.parts).intersection(
                        EXCLUDED_SNAPSHOT_PARTS)
                    or path.suffix.lower() in EXCLUDED_SNAPSHOT_SUFFIXES):
                continue
            paths.add(path.resolve())
    for relative in FROZEN_AST_FILES:
        if relative.startswith('scripts/'):
            paths.add((workspace / relative).resolve())
    for relative in (
            'scripts/run_perception_v2_frozen_regression.py',
            'audit_tools/run_pytest_style_tests.py',
            UNITTEST_STYLE_HELPER_RELATIVE,
            'docs/PERCEPTION_V2_FIELD_READINESS_RUNBOOK.md',
            'docs/PERCEPTION_V2_ROS1_NOETIC_FIELD_RUNBOOK.md'):
        path = workspace / relative
        if path.is_file():
            paths.add(path.resolve())
    evidence = workspace / 'evidence/perception_v2_offline_20260813'
    if evidence.is_dir():
        paths.update(path.resolve() for path in evidence.rglob('*.json'))
    field_evidence = workspace / 'evidence/perception_v2_field_20260814'
    if field_evidence.is_dir():
        paths.update(
            path.resolve() for path in field_evidence.rglob('*.json'))
    if excluded_report is not None:
        paths.discard(excluded_report)
    return tuple(sorted(paths, key=lambda item: str(item).lower()))


def snapshot_inputs(workspace, report_path=None):
    workspace = Path(workspace).resolve(strict=True)
    entries = []
    failures = []
    for path in _snapshot_paths(workspace, report_path=report_path):
        try:
            if _is_linklike(path):
                failures.append('source_link_forbidden:' + _relative(
                    path, workspace))
                continue
            entries.append(_identity(path, relative_to=workspace))
        except (OSError, ValueError) as error:
            failures.append(
                'source_snapshot_unreadable:{}:{}'.format(
                    str(path), type(error).__name__))
    return {
        'entries': entries,
        'file_count': len(entries),
        'source_set_sha256': _canonical_set_sha256(entries),
        'failures': failures,
    }


def compare_snapshots(before, after):
    first = {item['path']: item for item in before['entries']}
    second = {item['path']: item for item in after['entries']}
    return {
        'added': sorted(set(second) - set(first)),
        'removed': sorted(set(first) - set(second)),
        'modified': sorted(
            path for path in set(first).intersection(second)
            if first[path] != second[path]),
        'unchanged': (
            before['source_set_sha256'] == after['source_set_sha256']
            and before['file_count'] == after['file_count']
            and not before['failures'] and not after['failures']),
    }


def _parametrize_case_count(function):
    count = 1
    for decorator in function.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        name = decorator.func
        parts = []
        while isinstance(name, ast.Attribute):
            parts.append(name.attr)
            name = name.value
        if isinstance(name, ast.Name):
            parts.append(name.id)
        if not parts or parts[0] != 'parametrize' or len(decorator.args) < 2:
            continue
        values = ast.literal_eval(decorator.args[1])
        count *= len(values)
    return count


def count_static_test_cases(path):
    tree = ast.parse(Path(path).read_text(encoding='utf-8'))
    count = 0
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith('test_'):
                count += _parametrize_case_count(node)
        elif isinstance(node, ast.ClassDef):
            for child in node.body:
                if (isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and child.name.startswith('test_')):
                    count += _parametrize_case_count(child)
    return count


def _pytest_parametrize_shape(function):
    """Return whether a test is parametrized and its static case count."""
    count = 1
    parametrized = False
    for decorator in function.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        name = decorator.func
        parts = []
        while isinstance(name, ast.Attribute):
            parts.append(name.attr)
            name = name.value
        if isinstance(name, ast.Name):
            parts.append(name.id)
        if (not parts or parts[0] != 'parametrize'
                or len(decorator.args) < 2):
            continue
        values = ast.literal_eval(decorator.args[1])
        if not isinstance(values, (list, tuple)) or not values:
            raise ValueError('pytest parametrize values must be non-empty')
        parametrized = True
        count *= len(values)
    return parametrized, count


def static_pytest_case_ids(path, workspace, selected_names=None):
    """Recompute exact case IDs for one pytest-style source file.

    IDs are workspace-relative so two same-named files cannot substitute for
    one another.  The helper process must return this exact ordered list.
    """
    workspace = Path(workspace).resolve(strict=True)
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = workspace / candidate
    if _is_linklike(candidate):
        raise ValueError('pytest target link is forbidden')
    resolved = candidate.resolve(strict=True)
    try:
        relative = resolved.relative_to(workspace).as_posix()
    except ValueError:
        raise ValueError('pytest target escapes workspace')
    mode = resolved.stat().st_mode
    if not stat.S_ISREG(mode):
        raise ValueError('pytest target is not a regular file')
    tree = ast.parse(
        resolved.read_text(encoding='utf-8'), filename=str(resolved),
        feature_version=8)
    requested = None
    if selected_names is not None:
        requested = tuple(selected_names)
        if (not requested or len(set(requested)) != len(requested)
                or any(
                    not isinstance(name, str) or not name.startswith('test_')
                    for name in requested)):
            raise ValueError('selected pytest IDs are invalid')
        requested = frozenset(requested)
    seen_names = set()
    found_names = set()
    case_ids = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not node.name.startswith('test_'):
            continue
        if node.name in seen_names:
            raise ValueError('duplicate pytest test function: ' + node.name)
        seen_names.add(node.name)
        if requested is not None and node.name not in requested:
            continue
        found_names.add(node.name)
        parametrized, count = _pytest_parametrize_shape(node)
        base = '{}::{}'.format(relative, node.name)
        if parametrized:
            case_ids.extend(
                '{}[{}]'.format(base, index) for index in range(count))
        else:
            case_ids.append(base)
    if requested is not None and found_names != requested:
        raise ValueError('selected pytest ID is absent from target')
    if not case_ids or len(set(case_ids)) != len(case_ids):
        raise ValueError('pytest target has zero or duplicate case IDs')
    return tuple(sorted(case_ids))


def _pytest_style_environment(environment=None):
    """Return the minimal inherited environment for isolated test files."""
    source = os.environ if environment is None else environment
    allowed = {}
    for key, value in source.items():
        if str(key).upper() in PYTEST_STYLE_ENVIRONMENT_ALLOWLIST:
            allowed[str(key)] = str(value)
    allowed['PYTHONDONTWRITEBYTECODE'] = '1'
    allowed['PYTHONHASHSEED'] = '0'
    allowed['PYTHONIOENCODING'] = 'utf-8'
    return allowed


def _pytest_target_identity(path, workspace):
    workspace = Path(workspace).resolve(strict=True)
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = workspace / candidate
    if _is_linklike(candidate):
        raise ValueError('pytest target link is forbidden')
    resolved = candidate.resolve(strict=True)
    try:
        resolved.relative_to(workspace)
    except ValueError:
        raise ValueError('pytest target escapes workspace')
    if not stat.S_ISREG(resolved.stat().st_mode):
        raise ValueError('pytest target is not a regular file')
    return _identity(resolved, relative_to=workspace)


def _strict_pytest_marker(result):
    stdout_lines = _command_output_text(result.get('stdout', '')).splitlines()
    stderr_lines = _command_output_text(result.get('stderr', '')).splitlines()
    stdout_markers = [
        line for line in stdout_lines
        if line.startswith(PYTEST_FILE_RESULT_PREFIX)]
    stderr_markers = [
        line for line in stderr_lines
        if line.startswith(PYTEST_FILE_RESULT_PREFIX)]
    markers = stdout_markers + stderr_markers
    failures = []
    if not markers:
        failures.append('pytest_file_result_marker_missing')
        return None, None, failures
    if len(markers) != 1:
        failures.append('pytest_file_result_marker_count_mismatch')
        return None, None, failures
    if stderr_markers:
        failures.append('pytest_file_result_marker_not_stdout')
    raw = markers[0][len(PYTEST_FILE_RESULT_PREFIX):]
    try:
        payload = json.loads(
            raw, object_pairs_hook=_strict_object,
            parse_constant=_invalid_json_constant)
    except (TypeError, ValueError, json.JSONDecodeError):
        failures.append('pytest_file_result_marker_invalid_json')
        return None, raw, failures
    return payload, raw, failures


def _is_plain_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def validate_pytest_file_result(
        workspace, path, expected_ids, result, pre_identity=None):
    """Validate one helper subprocess result against host-recomputed facts."""
    workspace = Path(workspace).resolve(strict=True)
    expected_ids = tuple(expected_ids)
    failures = []
    if not expected_ids or len(set(expected_ids)) != len(expected_ids):
        failures.append('pytest_file_expected_ids_invalid')
    try:
        expected_identity = _pytest_target_identity(path, workspace)
    except (OSError, ValueError):
        expected_identity = None
        failures.append('pytest_file_target_identity_unavailable')
    if pre_identity is None:
        pre_identity = expected_identity
    if (pre_identity is None or expected_identity is None
            or pre_identity != expected_identity):
        failures.append('pytest_file_source_changed_during_execution')

    payload, raw_marker, marker_failures = _strict_pytest_marker(result)
    failures.extend(marker_failures)
    exact_keys = {
        'schema_version', 'runner_kind', 'path', 'size_bytes', 'sha256',
        'expected_ids', 'executed_ids', 'collected', 'passed', 'failed',
        'skipped', 'exit', 'result',
    }
    collected = 0
    passed = 0
    failed = 0
    skipped = 0
    executed_ids = []
    if not isinstance(payload, dict):
        if payload is not None:
            failures.append('pytest_file_result_payload_not_object')
    else:
        if set(payload) != exact_keys:
            failures.append('pytest_file_result_schema_mismatch')
        if payload.get('schema_version') != PYTEST_FILE_RESULT_SCHEMA_VERSION:
            failures.append('pytest_file_result_schema_version_mismatch')
        if payload.get('runner_kind') != PYTEST_FILE_RESULT_RUNNER_KIND:
            failures.append('pytest_file_result_runner_kind_mismatch')
        if (expected_identity is None
                or payload.get('path') != expected_identity['path']):
            failures.append('pytest_file_result_path_mismatch')
        if (expected_identity is None
                or not _is_plain_int(payload.get('size_bytes'))
                or payload.get('size_bytes') != expected_identity['size_bytes']):
            failures.append('pytest_file_result_size_mismatch')
        marker_sha = payload.get('sha256')
        if (expected_identity is None or not isinstance(marker_sha, str)
                or re.fullmatch(r'[0-9a-f]{64}', marker_sha) is None
                or marker_sha != expected_identity['sha256']):
            failures.append('pytest_file_result_hash_mismatch')
        marker_expected = payload.get('expected_ids')
        if (not isinstance(marker_expected, list)
                or marker_expected != list(expected_ids)
                or len(set(marker_expected)) != len(marker_expected)):
            failures.append('pytest_file_result_expected_ids_mismatch')
        marker_executed = payload.get('executed_ids')
        if isinstance(marker_executed, list) and all(
                isinstance(item, str) for item in marker_executed):
            executed_ids = marker_executed
        if (not isinstance(marker_executed, list)
                or marker_executed != list(expected_ids)
                or len(set(marker_executed)) != len(marker_executed)):
            failures.append('pytest_file_result_executed_ids_mismatch')
        count_values = []
        for key in ('collected', 'passed', 'failed', 'skipped', 'exit'):
            value = payload.get(key)
            if not _is_plain_int(value) or value < 0:
                failures.append('pytest_file_result_invalid_count:' + key)
                value = 0
            count_values.append(value)
        collected, passed, failed, skipped, marker_exit = count_values
        if collected == 0:
            failures.append('pytest_file_result_zero_denominator')
        if (collected != len(expected_ids)
                or collected != len(executed_ids)
                or collected != passed + failed + skipped):
            failures.append('pytest_file_result_count_invariant_failed')
        if (passed != len(expected_ids) or failed != 0 or skipped != 0):
            failures.append('pytest_file_result_not_all_passed')
        if marker_exit != result.get('exit_code'):
            failures.append('pytest_file_result_exit_mismatch')
        if payload.get('result') != 'PASS':
            failures.append('pytest_file_result_status_mismatch')
    if (result.get('exit_code') != 0 or result.get('timed_out')):
        failures.append('pytest_file_subprocess_failed')
    failures = list(dict.fromkeys(failures))
    return {
        'path': (None if expected_identity is None
                 else expected_identity['path']),
        'pre_identity': pre_identity,
        'post_identity': expected_identity,
        'source_unchanged': (
            pre_identity is not None and pre_identity == expected_identity),
        'expected_ids': list(expected_ids),
        'executed_ids': list(executed_ids),
        'collected': collected,
        'passed': passed,
        'failed': failed,
        'skipped': skipped,
        'marker_json_sha256': (
            None if raw_marker is None
            else _sha256_bytes(raw_marker.encode('utf-8'))),
        'marker_json_length_bytes': (
            0 if raw_marker is None else len(raw_marker.encode('utf-8'))),
        'marker_payload': payload,
        'command': _record_command(result),
        'failures': failures,
        'validated_pass': not failures,
    }


def validate_pytest_file_record_inventory(records, expected_paths):
    """Reject substitution, omission, duplication and equal-count swaps."""
    expected_paths = list(expected_paths)
    failures = []
    actual_paths = [record.get('path') for record in records]
    if actual_paths != expected_paths:
        failures.append('pytest_file_record_order_or_path_mismatch')
    if len(actual_paths) != len(set(actual_paths)):
        failures.append('pytest_file_record_duplicate_path')
    hashes = []
    for record in records:
        identity = record.get('post_identity')
        hashes.append(
            identity.get('sha256') if isinstance(identity, dict) else None)
    non_null_hashes = [value for value in hashes if value is not None]
    if len(non_null_hashes) != len(set(non_null_hashes)):
        failures.append('pytest_file_record_duplicate_hash')
    if not records or len(records) != len(expected_paths):
        failures.append('pytest_file_record_denominator_mismatch')
    if any(not record.get('validated_pass') for record in records):
        failures.append('pytest_file_record_contains_invalid_result')
    return list(dict.fromkeys(failures))


def _strict_unittest_marker(result):
    stdout_lines = _command_output_text(result.get('stdout', '')).splitlines()
    stderr_lines = _command_output_text(result.get('stderr', '')).splitlines()
    stdout_markers = [
        line for line in stdout_lines
        if line.startswith(UNITTEST_FILE_RESULT_PREFIX)]
    stderr_markers = [
        line for line in stderr_lines
        if line.startswith(UNITTEST_FILE_RESULT_PREFIX)]
    failures = []
    if len(stdout_markers) != 1 or stderr_markers:
        failures.append('unittest_file_result_marker_count_or_stream_mismatch')
        return None, None, failures
    if [line for line in stdout_lines if line.strip()] != stdout_markers:
        failures.append('unittest_file_result_stdout_noise')
    raw = stdout_markers[0][len(UNITTEST_FILE_RESULT_PREFIX):]
    try:
        payload = json.loads(
            raw, object_pairs_hook=_strict_object,
            parse_constant=_invalid_json_constant)
    except (TypeError, ValueError, json.JSONDecodeError):
        failures.append('unittest_file_result_marker_invalid_json')
        return None, raw, failures
    return payload, raw, failures


def _expected_host_executable_identity():
    if not sys.executable:
        raise ValueError('host_sys_executable_missing')
    entry = Path(os.path.abspath(sys.executable))
    current = entry
    seen = set()
    link_chain = []
    for _unused in range(64):
        key = os.path.normcase(os.path.abspath(os.fspath(current)))
        if key in seen:
            raise ValueError('host_sys_executable_link_cycle')
        seen.add(key)
        metadata = current.lstat()
        if not stat.S_ISLNK(metadata.st_mode):
            break
        raw_destination = os.readlink(os.fspath(current))
        destination = Path(raw_destination)
        if not destination.is_absolute():
            destination = current.parent / destination
        destination = Path(os.path.abspath(os.fspath(destination)))
        link_chain.append({
            'path': str(current),
            'link_target': raw_destination,
            'next_path': str(destination),
        })
        current = destination
    else:
        raise ValueError('host_sys_executable_link_chain_too_long')
    target = entry.resolve(strict=True)
    if target != current.resolve(strict=True):
        raise ValueError('host_sys_executable_link_chain_resolution_mismatch')
    target_metadata = target.lstat()
    if (stat.S_ISLNK(target_metadata.st_mode)
            or not stat.S_ISREG(target_metadata.st_mode)):
        raise ValueError('host_sys_executable_target_not_regular')
    entry_metadata = entry.lstat()
    return {
        'entry_path': str(entry),
        'entry_is_symlink': stat.S_ISLNK(entry_metadata.st_mode),
        'entry_lstat_size_bytes': entry_metadata.st_size,
        'entry_link_chain': link_chain,
        'resolved_target': {
            'path': str(target),
            'size_bytes': target_metadata.st_size,
            'sha256': sha256_file(target),
            'regular_file': True,
            'is_symlink': False,
        },
        'isolated': True,
        'no_bytecode': True,
        'version': [
            sys.version_info.major, sys.version_info.minor,
            sys.version_info.micro],
    }


def _expected_child_absolute_path(expected_workspace, relative_path):
    """Resolve one audited test path in the child platform's path syntax."""
    if (not isinstance(expected_workspace, str) or not expected_workspace
            or not isinstance(relative_path, str) or not relative_path):
        raise ValueError('unittest_child_path_input_invalid')
    posix_relative = PurePosixPath(relative_path)
    if posix_relative.is_absolute() or '..' in posix_relative.parts:
        raise ValueError('unittest_child_relative_path_invalid')
    if expected_workspace.startswith('/'):
        posix_workspace = PurePosixPath(expected_workspace)
        if not posix_workspace.is_absolute():
            raise ValueError('unittest_child_workspace_not_absolute')
        return str(posix_workspace.joinpath(posix_relative))
    native_relative = Path(*posix_relative.parts)
    return str(
        (Path(expected_workspace) / native_relative).resolve(strict=True))


def _valid_unittest_file_identity(
        value, expected_identity, expected_absolute_path):
    return (
        isinstance(value, dict)
        and set(value) == {
            'path', 'size_bytes', 'sha256', 'regular_file', 'is_symlink'}
        and value.get('path') == expected_absolute_path
        and value.get('regular_file') is True
        and value.get('is_symlink') is False
        and value.get('size_bytes') == expected_identity['size_bytes']
        and value.get('sha256') == expected_identity['sha256'])


def _unittest_executable_identity_failures(value, expected):
    """Compare a child interpreter report with one host-owned exact anchor."""
    failures = []
    exact_keys = {
        'entry_path', 'entry_is_symlink', 'entry_lstat_size_bytes',
        'entry_link_chain', 'resolved_target', 'isolated', 'no_bytecode',
        'version',
    }
    target_keys = {
        'path', 'size_bytes', 'sha256', 'regular_file', 'is_symlink'}
    if (not isinstance(value, dict) or not isinstance(expected, dict)
            or set(value) != exact_keys or set(expected) != exact_keys):
        failures.append('unittest_file_result_executable_schema_mismatch')
        return failures
    actual_target = value.get('resolved_target')
    expected_target = expected.get('resolved_target')
    if (not isinstance(actual_target, dict)
            or not isinstance(expected_target, dict)
            or set(actual_target) != target_keys
            or set(expected_target) != target_keys):
        failures.append('unittest_file_result_executable_schema_mismatch')
    actual_chain = value.get('entry_link_chain')
    expected_chain = expected.get('entry_link_chain')
    if (not isinstance(actual_chain, list)
            or actual_chain != expected_chain):
        failures.append('unittest_file_result_executable_chain_invalid')
    if value != expected:
        failures.append('unittest_file_result_executable_identity_mismatch')
    return list(dict.fromkeys(failures))


def validate_unittest_file_result(
        workspace, path, expected_ids, result, *, pre_identity=None,
        expected_executable=None, expected_workspace=None,
        allowed_skipped_ids=(), record_id=None, platform=None):
    """Validate one strict unittest child against host-recomputed facts."""
    workspace = Path(workspace).resolve(strict=True)
    expected_ids = tuple(expected_ids)
    allowed_skipped_ids = frozenset(allowed_skipped_ids)
    failures = []
    if (not expected_ids or len(expected_ids) != len(set(expected_ids))
            or not allowed_skipped_ids.issubset(expected_ids)):
        failures.append('unittest_file_expected_ids_invalid')
    try:
        expected_identity = _pytest_target_identity(path, workspace)
        full_discovered_ids = static_unittest_case_ids(path, workspace)
    except (OSError, SyntaxError, ValueError):
        expected_identity = None
        full_discovered_ids = ()
        failures.append('unittest_file_target_identity_unavailable')
    if pre_identity is None:
        pre_identity = expected_identity
    if (pre_identity is None or expected_identity is None
            or pre_identity != expected_identity):
        failures.append('unittest_file_source_changed_during_execution')
    if expected_executable is None:
        try:
            expected_executable = _expected_host_executable_identity()
        except (OSError, RuntimeError, ValueError):
            expected_executable = None
            failures.append('unittest_file_executable_identity_unavailable')
    if expected_workspace is None:
        expected_workspace = str(workspace)
    try:
        expected_absolute_path = _expected_child_absolute_path(
            expected_workspace, expected_identity['path'])
    except (OSError, TypeError, ValueError):
        expected_absolute_path = None
        failures.append('unittest_file_expected_child_path_invalid')

    payload, raw_marker, marker_failures = _strict_unittest_marker(result)
    failures.extend(marker_failures)
    exact_keys = {
        'schema_version', 'runner_kind', 'selection_mode', 'workspace',
        'import_roots', 'path', 'resolved_path', 'size_bytes', 'sha256',
        'target_identity_before', 'target_identity_after', 'requested_ids',
        'expected_ids', 'executed_ids', 'passed_ids', 'failed_ids',
        'skipped_ids', 'discovered_ids', 'discovered', 'collected', 'passed',
        'failed', 'skipped', 'exit', 'result', 'failures', 'executable',
        'python', 'environment', 'environment_unchanged_during_execution',
        'environment_restored', 'stdout_marker_count',
    }
    collected = passed = failed = skipped = 0
    executed_ids = []
    passed_ids = []
    failed_ids = []
    skipped_ids = []
    executable = None
    environment = None
    if not isinstance(payload, dict):
        if payload is not None:
            failures.append('unittest_file_result_payload_not_object')
    else:
        if set(payload) != exact_keys:
            failures.append('unittest_file_result_schema_mismatch')
        if payload.get('schema_version') != UNITTEST_FILE_RESULT_SCHEMA_VERSION:
            failures.append('unittest_file_result_schema_version_mismatch')
        if payload.get('runner_kind') != UNITTEST_FILE_RESULT_RUNNER_KIND:
            failures.append('unittest_file_result_runner_kind_mismatch')
        if payload.get('selection_mode') != 'selected_ids':
            failures.append('unittest_file_result_selection_mode_mismatch')
        if payload.get('workspace') != expected_workspace:
            failures.append('unittest_file_result_workspace_mismatch')
        if payload.get('import_roots') != list(UNITTEST_STYLE_IMPORT_ROOTS):
            failures.append('unittest_file_result_import_roots_mismatch')
        if (expected_identity is None
                or payload.get('path') != expected_identity['path']):
            failures.append('unittest_file_result_path_mismatch')
        if (expected_identity is None
                or payload.get('size_bytes') != expected_identity['size_bytes']):
            failures.append('unittest_file_result_size_mismatch')
        if (expected_identity is None
                or payload.get('sha256') != expected_identity['sha256']):
            failures.append('unittest_file_result_hash_mismatch')
        before_identity = payload.get('target_identity_before')
        after_identity = payload.get('target_identity_after')
        if (expected_identity is None
                or not _valid_unittest_file_identity(
                    before_identity, expected_identity,
                    expected_absolute_path)
                or after_identity != before_identity):
            failures.append('unittest_file_result_target_identity_mismatch')
        if (not isinstance(before_identity, dict)
                or payload.get('resolved_path') != expected_absolute_path
                or before_identity.get('path') != expected_absolute_path):
            failures.append('unittest_file_result_resolved_path_mismatch')
        for key in ('requested_ids', 'expected_ids', 'executed_ids'):
            if payload.get(key) != list(expected_ids):
                failures.append('unittest_file_result_{}_mismatch'.format(key))
        if payload.get('discovered_ids') != list(full_discovered_ids):
            failures.append('unittest_file_result_discovered_ids_mismatch')
        if payload.get('discovered') != len(full_discovered_ids):
            failures.append('unittest_file_result_discovered_count_mismatch')
        executed_ids = (
            payload.get('executed_ids')
            if isinstance(payload.get('executed_ids'), list) else [])
        passed_ids = (
            payload.get('passed_ids')
            if isinstance(payload.get('passed_ids'), list) else [])
        failed_ids = (
            payload.get('failed_ids')
            if isinstance(payload.get('failed_ids'), list) else [])
        skipped_ids = (
            payload.get('skipped_ids')
            if isinstance(payload.get('skipped_ids'), list) else [])
        outcome_ids = passed_ids + failed_ids + skipped_ids
        if (len(outcome_ids) != len(set(outcome_ids))
                or set(outcome_ids) != set(expected_ids)):
            failures.append('unittest_file_result_outcome_partition_mismatch')
        if failed_ids:
            failures.append('unittest_file_result_failed_ids_present')
        if not set(skipped_ids).issubset(allowed_skipped_ids):
            failures.append('unittest_file_result_unapproved_skip')
        if set(passed_ids) != set(expected_ids) - set(skipped_ids):
            failures.append('unittest_file_result_passed_ids_mismatch')
        count_values = []
        for key in ('discovered', 'collected', 'passed', 'failed', 'skipped',
                    'exit', 'stdout_marker_count'):
            value = payload.get(key)
            if not _is_plain_int(value) or value < 0:
                failures.append('unittest_file_result_invalid_count:' + key)
                value = 0
            count_values.append(value)
        (_discovered, collected, passed, failed, skipped,
         marker_exit, marker_count) = count_values
        if collected == 0:
            failures.append('unittest_file_result_zero_denominator')
        if (collected != len(expected_ids)
                or collected != len(executed_ids)
                or collected != passed + failed + skipped
                or passed != len(passed_ids)
                or failed != len(failed_ids)
                or skipped != len(skipped_ids)):
            failures.append('unittest_file_result_count_invariant_failed')
        if marker_exit != result.get('exit_code') or marker_count != 1:
            failures.append('unittest_file_result_exit_or_marker_mismatch')
        expected_status = 'PASS_WITH_SKIPS' if skipped_ids else 'PASS'
        if payload.get('result') != expected_status:
            failures.append('unittest_file_result_status_mismatch')
        if payload.get('failures') != []:
            failures.append('unittest_file_result_child_failures_present')

        executable = payload.get('executable')
        if payload.get('python') != executable or not isinstance(
                executable, dict):
            failures.append('unittest_file_result_executable_schema_mismatch')
        else:
            failures.extend(_unittest_executable_identity_failures(
                executable, expected_executable))
        environment = payload.get('environment')
        if (not isinstance(environment, dict)
                or environment.get('clean') is not True
                or environment.get('contaminated_keys') != []
                or environment.get('cwd') != expected_workspace
                or payload.get('environment_unchanged_during_execution')
                is not True
                or payload.get('environment_restored') is not True):
            failures.append('unittest_file_result_environment_invalid')
    if (result.get('exit_code') != 0 or result.get('timed_out')):
        failures.append('unittest_file_subprocess_failed')
    failures = list(dict.fromkeys(failures))
    return {
        'record_id': record_id,
        'platform': platform,
        'path': None if expected_identity is None else expected_identity['path'],
        'pre_identity': pre_identity,
        'post_identity': expected_identity,
        'source_unchanged': (
            pre_identity is not None and pre_identity == expected_identity),
        'expected_ids': list(expected_ids),
        'executed_ids': list(executed_ids),
        'passed_ids': list(passed_ids),
        'failed_ids': list(failed_ids),
        'skipped_ids': list(skipped_ids),
        'collected': collected,
        'passed': passed,
        'failed': failed,
        'skipped': skipped,
        'executable': executable,
        'environment': environment,
        'marker_json_sha256': (
            None if raw_marker is None
            else _sha256_bytes(raw_marker.encode('utf-8'))),
        'marker_json_length_bytes': (
            0 if raw_marker is None else len(raw_marker.encode('utf-8'))),
        'marker_payload': payload,
        'command': _record_command(result),
        'failures': failures,
        'validated_pass': not failures,
    }


def _build_pytest_execution_plan(workspace, present_post_freeze):
    """Build one ordered unique process plan across all release layers."""
    workspace = Path(workspace).resolve(strict=True)
    test_root = workspace / 'src/limo_cleanup_perception/test'
    plan = []
    by_path = {}
    failures = []

    def add(filename, selected_names, scope, suite_id, expected_count):
        path = test_root / filename
        relative = path.relative_to(workspace).as_posix()
        try:
            ids = static_pytest_case_ids(
                path, workspace, selected_names=selected_names)
        except (OSError, SyntaxError, ValueError) as error:
            failures.append(
                'pytest_file_plan_invalid:{}:{}'.format(
                    relative, type(error).__name__))
            return
        if len(ids) != expected_count:
            failures.append('pytest_file_plan_count_mismatch:' + relative)
        entry = by_path.get(relative)
        if entry is None:
            entry = {
                'path': path,
                'relative_path': relative,
                'expected_ids': [],
                'allocations': [],
            }
            by_path[relative] = entry
            plan.append(entry)
        overlap = set(entry['expected_ids']).intersection(ids)
        if overlap:
            failures.append('pytest_file_plan_duplicate_case_allocation:'
                            + relative)
        entry['expected_ids'].extend(ids)
        entry['expected_ids'] = sorted(set(entry['expected_ids']))
        entry['allocations'].append({
            'scope': scope,
            'suite_id': suite_id,
            'expected_ids': list(ids),
        })

    for filename, expected in PYTEST_STYLE_FILES:
        add(filename, None, 'frozen_full', filename, expected)
    for filename, names in PYTEST_STYLE_TARGETS:
        add(filename, names, 'frozen_selected', filename, len(names))
    for filename in POST_FREEZE_PYTEST_STYLE_FILES:
        if filename in present_post_freeze:
            add(
                filename, None, 'post_freeze', filename,
                POST_FREEZE_TEST_COUNTS[filename])
    for suite_id, filename, expected in POST_FIX_PYTEST_STYLE_FILES:
        add(filename, None, 'post_fix', suite_id, expected)
    for suite_id, filename, names in POST_FIX_SELECTED_PYTEST_STYLE_TARGETS:
        add(filename, names, 'post_fix', suite_id, len(names))
    for suite_id, filename, expected in CURRENT_GENERATION_PYTEST_STYLE_FILES:
        add(filename, None, 'current_generation', suite_id, expected)
    for suite_id, filename, names in (
            CURRENT_GENERATION_SELECTED_PYTEST_STYLE_TARGETS):
        add(filename, names, 'current_generation', suite_id, len(names))
    for entry in plan:
        try:
            full_ids = static_pytest_case_ids(
                entry['path'], workspace, selected_names=None)
        except (OSError, SyntaxError, ValueError) as error:
            failures.append(
                'pytest_file_plan_full_inventory_invalid:{}:{}'.format(
                    entry['relative_path'], type(error).__name__))
            continue
        if tuple(entry['expected_ids']) != full_ids:
            failures.append(
                'pytest_file_plan_incomplete_static_case_coverage:'
                + entry['relative_path'])
    return plan, failures


def _execute_pytest_file_plan(
        workspace, plan, command_runner, inherited_environment=None):
    workspace = Path(workspace).resolve(strict=True)
    environment = _pytest_style_environment(inherited_environment)
    helper = workspace / PYTEST_STYLE_HELPER_RELATIVE
    records = []
    for entry in plan:
        path = entry['path']
        try:
            pre_identity = _pytest_target_identity(path, workspace)
        except (OSError, ValueError):
            pre_identity = None
        argv = [
            sys.executable, '-I', '-B', str(helper), '--single-file',
            '--workspace', str(workspace), '--target', str(path),
        ]
        for root in PYTEST_STYLE_IMPORT_ROOTS:
            argv.extend(('--import-root', root))
        for case_id in entry['expected_ids']:
            argv.extend(('--expected-id', case_id))
        result = command_runner(argv, workspace, environment)
        record = validate_pytest_file_result(
            workspace, path, entry['expected_ids'], result,
            pre_identity=pre_identity)
        record['allocations'] = entry['allocations']
        records.append(record)
    inventory_failures = validate_pytest_file_record_inventory(
        records, [entry['relative_path'] for entry in plan])
    structural_failures = [
        failure for failure in inventory_failures
        if failure != 'pytest_file_record_contains_invalid_result']
    if structural_failures:
        for record in records:
            record['validated_pass'] = False
    return records, inventory_failures


def _pytest_allocation_reports(records):
    reports = {}
    failures = []
    for record in records:
        executed = set(record.get('executed_ids', []))
        for allocation in record.get('allocations', []):
            scope = allocation['scope']
            suite_id = allocation['suite_id']
            expected_ids = list(allocation['expected_ids'])
            key = (scope, suite_id)
            if key in reports:
                failures.append(
                    'pytest_file_allocation_duplicate:{}:{}'.format(
                        scope, suite_id))
                continue
            observed = len(executed.intersection(expected_ids))
            valid = (
                record.get('validated_pass') is True
                and observed == len(expected_ids))
            reports[key] = {
                'runner': 'isolated_pytest_style_file',
                'expected': len(expected_ids),
                'expected_ids': expected_ids,
                'collected': observed,
                'passed': len(expected_ids) if valid else 0,
                'failed': 0 if valid else max(1, len(expected_ids) - observed),
                'skipped': 0,
                'validated_pass': valid,
                'file_path': record.get('path'),
                'file_identity': record.get('post_identity'),
                'command': record.get('command'),
            }
    return reports, failures


def _pytest_scope_totals(allocation_reports, scope):
    selected = [
        value for (actual_scope, _suite_id), value
        in allocation_reports.items() if actual_scope == scope]
    return {
        'expected': sum(value['expected'] for value in selected),
        'collected': sum(value['collected'] for value in selected),
        'passed': sum(value['passed'] for value in selected),
        'failed': sum(value['failed'] for value in selected),
        'skipped': sum(value['skipped'] for value in selected),
        'validated_pass': bool(selected) and all(
            value['validated_pass'] for value in selected),
    }


def static_unittest_ids(path, module):
    """Return exact unittest IDs declared by one source file."""
    tree = ast.parse(Path(path).read_text(encoding='utf-8'))
    result = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith('test_'):
                result.append(module + '.' + node.name)
        elif isinstance(node, ast.ClassDef):
            for child in node.body:
                if (isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and child.name.startswith('test_')):
                    result.append(
                        '{}.{}.{}'.format(module, node.name, child.name))
    return tuple(sorted(result))


def static_unittest_case_ids(
        path, workspace, selected_names=None):
    """Return stable workspace-relative unittest IDs for one exact file."""
    workspace = Path(workspace).resolve(strict=True)
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = workspace / candidate
    if _is_linklike(candidate):
        raise ValueError('unittest target link is forbidden')
    resolved = candidate.resolve(strict=True)
    try:
        relative = resolved.relative_to(workspace).as_posix()
    except ValueError:
        raise ValueError('unittest target escapes workspace')
    if not stat.S_ISREG(resolved.stat().st_mode):
        raise ValueError('unittest target is not a regular file')
    tree = ast.parse(
        resolved.read_text(encoding='utf-8'), filename=str(resolved),
        feature_version=8)
    by_suffix = {}
    case_ids = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.name.startswith('test_'):
                continue
            suffix = node.name
            case_id = '{}::{}'.format(relative, suffix)
            by_suffix.setdefault(suffix, []).append(case_id)
            case_ids.append(case_id)
        elif isinstance(node, ast.ClassDef):
            for child in node.body:
                if (not isinstance(
                        child, (ast.FunctionDef, ast.AsyncFunctionDef))
                        or not child.name.startswith('test_')):
                    continue
                suffix = '{}.{}'.format(node.name, child.name)
                case_id = '{}::{}'.format(relative, suffix)
                by_suffix.setdefault(suffix, []).append(case_id)
                case_ids.append(case_id)
    if not case_ids or len(case_ids) != len(set(case_ids)):
        raise ValueError('unittest target has zero or duplicate case IDs')
    full_ids = tuple(sorted(case_ids))
    if selected_names is None:
        return full_ids
    requested = tuple(selected_names)
    if not requested or len(requested) != len(set(requested)):
        raise ValueError('selected unittest IDs are invalid')
    normalized = []
    for name in requested:
        if not isinstance(name, str) or not name:
            raise ValueError('selected unittest ID is invalid')
        if name.startswith(relative + '::'):
            candidate_id = name
        else:
            suffix = name.rsplit('::', 1)[-1]
            if suffix not in by_suffix:
                parts = name.split('.')
                suffix = '.'.join(parts[-2:]) if len(parts) > 1 else parts[-1]
            matches = by_suffix.get(suffix, [])
            if len(matches) != 1:
                raise ValueError('selected unittest ID is absent or ambiguous')
            candidate_id = matches[0]
        if candidate_id not in full_ids:
            raise ValueError('selected unittest ID is absent from target')
        normalized.append(candidate_id)
    if len(normalized) != len(set(normalized)):
        raise ValueError('selected unittest IDs normalize to duplicates')
    return tuple(sorted(normalized))


def _build_current_unittest_execution_plan(workspace):
    """Build the ordered unique Windows current-generation unittest plan."""
    workspace = Path(workspace).resolve(strict=True)
    test_root = workspace / 'src/limo_cleanup_perception/test'
    plan = []
    by_path = {}
    failures = []

    def add(suite_id, path, selected_names, expected):
        path = Path(path)
        if not path.is_absolute():
            path = workspace / path
        try:
            ids = static_unittest_case_ids(
                path, workspace, selected_names=selected_names)
            relative = path.resolve(strict=True).relative_to(
                workspace).as_posix()
        except (OSError, SyntaxError, ValueError) as error:
            failures.append(
                'unittest_file_plan_invalid:{}:{}'.format(
                    suite_id, type(error).__name__))
            return
        if len(ids) != expected:
            failures.append('unittest_file_plan_count_mismatch:' + suite_id)
        entry = by_path.get(relative)
        if entry is None:
            entry = {
                'path': path,
                'relative_path': relative,
                'expected_ids': [],
                'allocations': [],
            }
            by_path[relative] = entry
            plan.append(entry)
        overlap = set(entry['expected_ids']).intersection(ids)
        if overlap:
            failures.append(
                'unittest_file_plan_duplicate_case_allocation:' + relative)
        entry['expected_ids'].extend(ids)
        entry['expected_ids'] = sorted(set(entry['expected_ids']))
        entry['allocations'].append({
            'scope': 'current_generation',
            'suite_id': suite_id,
            'expected_ids': list(ids),
        })

    for suite_id, module, expected in CURRENT_GENERATION_UNITTEST_TARGETS:
        add(
            suite_id, test_root / (module.rsplit('.', 1)[-1] + '.py'),
            None, expected)
    for suite_id, module, names in (
            CURRENT_GENERATION_SELECTED_UNITTEST_TARGETS):
        add(
            suite_id, test_root / (module.rsplit('.', 1)[-1] + '.py'),
            names, len(names))
    for suite_id, relative, expected in (
            CURRENT_GENERATION_ROS1_UNITTEST_TARGETS):
        add(suite_id, workspace / relative, None, expected)
    suite_id, relative, expected = CURRENT_GENERATION_EXACT_UNITTEST_TARGET
    add(suite_id, workspace / relative, None, expected)
    return plan, failures


def _windows_path_to_wsl(path):
    """Translate one resolved local drive path without invoking a shell."""
    resolved = Path(path).resolve(strict=True)
    drive = resolved.drive
    if os.name != 'nt' or not re.fullmatch(r'[A-Za-z]:', drive):
        raise ValueError('wsl_path_requires_windows_drive')
    tail = '/'.join(resolved.parts[1:]).replace('\\', '/')
    return '/mnt/{}/{}'.format(drive[0].lower(), tail)


def _wsl_unittest_argv(
        workspace, path, expected_ids, executable_entry, wsl_launcher):
    workspace = Path(workspace).resolve(strict=True)
    helper = workspace / UNITTEST_STYLE_HELPER_RELATIVE
    argv = [
        str(wsl_launcher), '--distribution', WSL_DISTRIBUTION, '--exec',
        '/usr/bin/env', '-i', 'HOME=/tmp', 'LANG=C.UTF-8',
        'LC_ALL=C.UTF-8', 'PATH=/usr/bin:/bin',
        'PYTHONDONTWRITEBYTECODE=1', executable_entry, '-I', '-B',
        _windows_path_to_wsl(helper), '--workspace',
        _windows_path_to_wsl(workspace), '--target',
        _windows_path_to_wsl(path),
    ]
    for root in UNITTEST_STYLE_IMPORT_ROOTS:
        argv.extend(('--import-root', root))
    for case_id in expected_ids:
        argv.extend(('--expected-id', case_id))
    return argv


def _execute_current_unittest_file_plan(
        workspace, plan, command_runner, inherited_environment=None):
    workspace = Path(workspace).resolve(strict=True)
    environment = _pytest_style_environment(inherited_environment)
    helper = workspace / UNITTEST_STYLE_HELPER_RELATIVE
    try:
        helper_identity = _pytest_target_identity(helper, workspace)
    except (OSError, ValueError):
        helper_identity = None
    records = []
    for entry in plan:
        path = entry['path']
        try:
            pre_identity = _pytest_target_identity(path, workspace)
        except (OSError, ValueError):
            pre_identity = None
        argv = [
            sys.executable, '-I', '-B', str(helper), '--workspace',
            str(workspace), '--target', str(path),
        ]
        for root in UNITTEST_STYLE_IMPORT_ROOTS:
            argv.extend(('--import-root', root))
        for case_id in entry['expected_ids']:
            argv.extend(('--expected-id', case_id))
        result = command_runner(argv, workspace, environment)
        if entry['relative_path'] == EXACT_CLI_TEST_RELATIVE:
            allowed_skips = (EXACT_CLI_POSIX_CASE_ID,)
        elif entry['relative_path'] == HOST_READINESS_TEST_RELATIVE:
            allowed_skips = HOST_READINESS_POSIX_CASE_IDS
        else:
            allowed_skips = ()
        record = validate_unittest_file_result(
            workspace, path, entry['expected_ids'], result,
            pre_identity=pre_identity,
            expected_executable=_expected_host_executable_identity(),
            expected_workspace=str(workspace),
            allowed_skipped_ids=allowed_skips,
            record_id='windows:' + entry['relative_path'],
            platform='windows')
        record['allocations'] = entry['allocations']
        record['helper_identity'] = helper_identity
        records.append(record)
    expected_record_ids = [
        'windows:' + entry['relative_path'] for entry in plan]
    failures = []
    actual_record_ids = [record.get('record_id') for record in records]
    if actual_record_ids != expected_record_ids:
        failures.append('unittest_file_record_order_or_id_mismatch')
    if len(actual_record_ids) != len(set(actual_record_ids)):
        failures.append('unittest_file_record_duplicate_id')
    if not records or len(records) != len(plan):
        failures.append('unittest_file_record_denominator_mismatch')
    if any(record.get('validated_pass') is not True for record in records):
        failures.append('unittest_file_record_contains_invalid_result')
    try:
        helper_after = _pytest_target_identity(helper, workspace)
    except (OSError, ValueError):
        helper_after = None
    if helper_identity is None or helper_after != helper_identity:
        failures.append('unittest_file_helper_identity_changed')
    return records, list(dict.fromkeys(failures))


def _expected_wsl_executable_identity(entry):
    if entry == '/usr/bin/python3':
        entry_is_symlink = True
        entry_lstat_size_bytes = len('python3.14'.encode('utf-8'))
        entry_link_chain = [{
            'path': '/usr/bin/python3',
            'link_target': 'python3.14',
            'next_path': '/usr/bin/python3.14',
        }]
    elif entry == '/usr/bin/python3.14':
        entry_is_symlink = False
        entry_lstat_size_bytes = WSL_PYTHON_TARGET_IDENTITY['size_bytes']
        entry_link_chain = []
    else:
        raise ValueError('unsupported_wsl_python_entry')
    return {
        'entry_path': entry,
        'entry_is_symlink': entry_is_symlink,
        'entry_lstat_size_bytes': entry_lstat_size_bytes,
        'entry_link_chain': entry_link_chain,
        'resolved_target': {
            **WSL_PYTHON_TARGET_IDENTITY,
            'regular_file': True,
            'is_symlink': False,
        },
        'isolated': True,
        'no_bytecode': True,
        'version': list(WSL_PYTHON_VERSION),
    }


def _expected_current_generation_wsl_unittest_targets():
    return (
        (EXACT_CLI_POSIX_COMPANION_SUITE_ID,
         EXACT_CLI_TEST_RELATIVE, '/usr/bin/python3',
         (EXACT_CLI_POSIX_CASE_ID,)),
        (HOST_READINESS_POSIX_SUITE_BY_CASE_ID[
             HOST_READINESS_POSIX_CASE_IDS[0]],
         HOST_READINESS_TEST_RELATIVE, '/usr/bin/python3',
         (HOST_READINESS_POSIX_CASE_IDS[0],)),
        (HOST_READINESS_POSIX_SUITE_BY_CASE_ID[
             HOST_READINESS_POSIX_CASE_IDS[1]],
         HOST_READINESS_TEST_RELATIVE, '/usr/bin/python3',
         (HOST_READINESS_POSIX_CASE_IDS[1],)),
        (ROS1_ISOLATED_PROBE_PYTHON3_SUITE_ID,
         ROS1_ISOLATED_PROBE_TEST_RELATIVE, '/usr/bin/python3', None),
        (ROS1_ISOLATED_PROBE_PYTHON3_14_SUITE_ID,
         ROS1_ISOLATED_PROBE_TEST_RELATIVE, '/usr/bin/python3.14', None),
    )


def validate_current_generation_wsl_unittest_target_manifest(targets=None):
    """Validate the exact ordered set consumed by composites and totals."""
    expected = _expected_current_generation_wsl_unittest_targets()
    actual_source = (
        CURRENT_GENERATION_WSL_UNITTEST_TARGETS
        if targets is None else targets)
    failures = []
    try:
        actual = tuple(actual_source)
    except TypeError:
        actual = ()
        failures.append('wsl_unittest_target_manifest_mismatch')
    if actual != expected:
        failures.append('wsl_unittest_target_manifest_mismatch')
    actual_record_ids = []
    for item in actual:
        if (not isinstance(item, tuple) or len(item) != 4
                or not isinstance(item[0], str)):
            failures.append('wsl_unittest_target_manifest_mismatch')
            continue
        actual_record_ids.append(item[0])
    expected_record_ids = [item[0] for item in expected]
    if (actual_record_ids != expected_record_ids
            or len(actual_record_ids) != len(set(actual_record_ids))):
        failures.append('wsl_unittest_target_manifest_mismatch')
    unallocated_record_ids = sorted(
        set(actual_record_ids) - set(expected_record_ids))
    if unallocated_record_ids:
        failures.append('wsl_unittest_unallocated_record')
    failures = list(dict.fromkeys(failures))
    return {
        'schema_version': WSL_UNITTEST_TARGET_MANIFEST_SCHEMA_VERSION,
        'expected_record_ids': expected_record_ids,
        'actual_record_ids': actual_record_ids,
        'expected_target_count': len(expected),
        'actual_target_count': len(actual),
        'unallocated_record_ids': unallocated_record_ids,
        'posix_companion_physical_count': (
            1 + len(HOST_READINESS_POSIX_CASE_IDS)),
        'failures': failures,
        'validated_pass': not failures,
    }


def _resolve_wsl_launcher(environment=None):
    source = os.environ if environment is None else environment
    candidate = shutil.which('wsl.exe', path=source.get('PATH'))
    if not candidate:
        raise OSError('wsl.exe not found')
    path = Path(candidate)
    if _is_linklike(path):
        raise OSError('wsl.exe linklike')
    resolved = path.resolve(strict=True)
    if not stat.S_ISREG(resolved.stat().st_mode):
        raise OSError('wsl.exe not regular')
    return resolved, _identity(resolved)


def _execute_wsl_current_unittests(
        workspace, command_runner, inherited_environment=None):
    workspace = Path(workspace).resolve(strict=True)
    target_manifest = (
        validate_current_generation_wsl_unittest_target_manifest())
    if target_manifest['validated_pass'] is not True:
        return {}, list(target_manifest['failures'])
    targets = tuple(CURRENT_GENERATION_WSL_UNITTEST_TARGETS)
    environment = _pytest_style_environment(inherited_environment)
    helper = workspace / UNITTEST_STYLE_HELPER_RELATIVE
    try:
        helper_identity = _pytest_target_identity(helper, workspace)
        launcher, launcher_identity = _resolve_wsl_launcher(
            inherited_environment)
    except (OSError, ValueError):
        return {}, ['wsl_unittest_launcher_or_helper_identity_unavailable']
    records = {}
    failures = []
    for suite_id, relative, executable_entry, selected_ids in targets:
        path = workspace / relative
        try:
            expected_ids = static_unittest_case_ids(
                path, workspace, selected_names=selected_ids)
            pre_identity = _pytest_target_identity(path, workspace)
        except (OSError, SyntaxError, ValueError):
            failures.append('wsl_unittest_static_identity_invalid:' + suite_id)
            continue
        argv = _wsl_unittest_argv(
            workspace, path, expected_ids, executable_entry, launcher)
        result = command_runner(argv, workspace, environment)
        record = validate_unittest_file_result(
            workspace, path, expected_ids, result,
            pre_identity=pre_identity,
            expected_executable=_expected_wsl_executable_identity(
                executable_entry),
            expected_workspace=_windows_path_to_wsl(workspace),
            allowed_skipped_ids=(), record_id=suite_id,
            platform='posix_wsl')
        record['wsl_distribution'] = WSL_DISTRIBUTION
        record['requested_executable_entry'] = executable_entry
        record['wsl_launcher_identity'] = launcher_identity
        record['helper_identity'] = helper_identity
        records[suite_id] = record
        if record.get('validated_pass') is not True:
            failures.append('wsl_unittest_record_invalid:' + suite_id)
    expected_suite_ids = [
        item[0] for item in _expected_current_generation_wsl_unittest_targets()]
    if list(records) != expected_suite_ids:
        failures.append('wsl_unittest_record_order_or_denominator_mismatch')
    unallocated_record_ids = sorted(set(records) - set(expected_suite_ids))
    if unallocated_record_ids:
        failures.append('wsl_unittest_unallocated_record')
    try:
        launcher_after = _identity(launcher)
        helper_after = _pytest_target_identity(helper, workspace)
    except (OSError, ValueError):
        launcher_after = None
        helper_after = None
    if launcher_after != launcher_identity:
        failures.append('wsl_unittest_launcher_identity_changed')
    if helper_after != helper_identity:
        failures.append('wsl_unittest_helper_identity_changed')
    return records, list(dict.fromkeys(failures))


def _unittest_allocation_reports(records):
    reports = {}
    failures = []
    for record in records:
        passed_ids = set(record.get('passed_ids', []))
        failed_ids = set(record.get('failed_ids', []))
        skipped_ids = set(record.get('skipped_ids', []))
        for allocation in record.get('allocations', []):
            key = (allocation['scope'], allocation['suite_id'])
            if key in reports:
                failures.append(
                    'unittest_file_allocation_duplicate:{}:{}'.format(*key))
                continue
            expected_ids = list(allocation['expected_ids'])
            expected_set = set(expected_ids)
            reports[key] = {
                'runner': 'isolated_unittest_file',
                'expected': len(expected_ids),
                'expected_ids': expected_ids,
                'collected': len(expected_set.intersection(
                    set(record.get('executed_ids', [])))),
                'passed': len(expected_set.intersection(passed_ids)),
                'failed': len(expected_set.intersection(failed_ids)),
                'skipped': len(expected_set.intersection(skipped_ids)),
                'skipped_ids': sorted(expected_set.intersection(skipped_ids)),
                'validated_pass': record.get('validated_pass') is True,
                'file_path': record.get('path'),
                'file_identity': record.get('post_identity'),
                'executable': record.get('executable'),
                'command': record.get('command'),
            }
    return reports, failures


def _valid_composite_file_identity(value, expected_relative_path):
    return (
        isinstance(value, dict)
        and set(value) == {'path', 'size_bytes', 'sha256'}
        and value.get('path') == expected_relative_path
        and _is_plain_int(value.get('size_bytes'))
        and value.get('size_bytes') > 0
        and isinstance(value.get('sha256'), str)
        and re.fullmatch(r'[0-9a-f]{64}', value.get('sha256')) is not None)


def _valid_platform_unittest_record_provenance(
        record, *, expected_record_id, expected_platform,
        expected_relative_path, expected_executable,
        expected_requested_executable_entry=None,
        expected_wsl_distribution=None):
    if not isinstance(record, dict):
        return False
    post_identity = record.get('post_identity')
    helper_identity = record.get('helper_identity')
    if (record.get('record_id') != expected_record_id
            or record.get('platform') != expected_platform
            or record.get('path') != expected_relative_path
            or record.get('source_unchanged') is not True
            or record.get('pre_identity') != post_identity
            or not _valid_composite_file_identity(
                post_identity, expected_relative_path)
            or not _valid_composite_file_identity(
                helper_identity, UNITTEST_STYLE_HELPER_RELATIVE)
            or _unittest_executable_identity_failures(
                record.get('executable'), expected_executable)):
        return False
    if expected_platform == 'posix_wsl':
        if (record.get('requested_executable_entry')
                != expected_requested_executable_entry
                or record.get('wsl_distribution')
                != expected_wsl_distribution):
            return False
    return True


def _exact_platform_composite(windows_record, posix_record, expected_ids):
    expected_ids = list(expected_ids)
    failures = []
    if not isinstance(windows_record, dict):
        failures.append('exact_composite_windows_record_missing')
        windows_record = {}
    if not isinstance(posix_record, dict):
        failures.append('exact_composite_posix_record_missing')
        posix_record = {}
    try:
        expected_host_executable = _expected_host_executable_identity()
        expected_posix_executable = _expected_wsl_executable_identity(
            '/usr/bin/python3')
    except (OSError, RuntimeError, ValueError):
        expected_host_executable = None
        expected_posix_executable = None
    if not _valid_platform_unittest_record_provenance(
            windows_record,
            expected_record_id='windows:' + EXACT_CLI_TEST_RELATIVE,
            expected_platform='windows',
            expected_relative_path=EXACT_CLI_TEST_RELATIVE,
            expected_executable=expected_host_executable):
        failures.append('exact_composite_windows_provenance_mismatch')
    if not _valid_platform_unittest_record_provenance(
            posix_record,
            expected_record_id=EXACT_CLI_POSIX_COMPANION_SUITE_ID,
            expected_platform='posix_wsl',
            expected_relative_path=EXACT_CLI_TEST_RELATIVE,
            expected_executable=expected_posix_executable,
            expected_requested_executable_entry='/usr/bin/python3',
            expected_wsl_distribution=WSL_DISTRIBUTION):
        failures.append('exact_composite_posix_provenance_mismatch')
    if windows_record.get('validated_pass') is not True:
        failures.append('exact_composite_windows_record_invalid')
    if posix_record.get('validated_pass') is not True:
        failures.append('exact_composite_posix_record_invalid')
    if windows_record.get('expected_ids') != expected_ids:
        failures.append('exact_composite_windows_ids_mismatch')
    skipped_ids = windows_record.get('skipped_ids', [])
    if skipped_ids not in ([], [EXACT_CLI_POSIX_CASE_ID]):
        failures.append('exact_composite_windows_skip_invalid')
    if (posix_record.get('expected_ids') != [EXACT_CLI_POSIX_CASE_ID]
            or posix_record.get('passed_ids') != [EXACT_CLI_POSIX_CASE_ID]
            or posix_record.get('failed') != 0
            or posix_record.get('skipped') != 0):
        failures.append('exact_composite_posix_companion_not_passed')
    if (posix_record.get('record_id')
            != EXACT_CLI_POSIX_COMPANION_SUITE_ID
            or posix_record.get('post_identity')
            != windows_record.get('post_identity')
            or posix_record.get('helper_identity')
            != windows_record.get('helper_identity')):
        failures.append('exact_composite_source_helper_or_record_mismatch')
    windows_passed = set(windows_record.get('passed_ids', []))
    logical_passed = windows_passed | set(posix_record.get('passed_ids', []))
    if logical_passed != set(expected_ids):
        failures.append('exact_composite_logical_id_coverage_mismatch')
    failures = list(dict.fromkeys(failures))
    return {
        'runner': 'platform_composite_isolated_unittest',
        'expected': len(expected_ids),
        'expected_ids': expected_ids,
        'collected': len(expected_ids) if not failures else 0,
        'passed': len(expected_ids) if not failures else 0,
        'failed': 0 if not failures else max(1, len(expected_ids)),
        'skipped': 0,
        'validated_pass': not failures,
        'raw_windows': windows_record,
        'raw_posix_companion': posix_record,
        'physical_collected': (
            windows_record.get('collected', 0)
            + posix_record.get('collected', 0)),
        'physical_passed': (
            windows_record.get('passed', 0) + posix_record.get('passed', 0)),
        'physical_failed': (
            windows_record.get('failed', 0) + posix_record.get('failed', 0)),
        'physical_skipped': (
            windows_record.get('skipped', 0) + posix_record.get('skipped', 0)),
        'failures': failures,
    }


def _host_readiness_platform_composite(
        windows_record, posix_records, expected_ids):
    """Bind two Windows link skips to two exact POSIX PASS records."""
    expected_ids = list(expected_ids)
    failures = []
    if not isinstance(windows_record, dict):
        failures.append('host_composite_windows_record_missing')
        windows_record = {}
    try:
        expected_host_executable = _expected_host_executable_identity()
        expected_posix_executable = _expected_wsl_executable_identity(
            '/usr/bin/python3')
    except (OSError, RuntimeError, ValueError):
        expected_host_executable = None
        expected_posix_executable = None
    if not _valid_platform_unittest_record_provenance(
            windows_record,
            expected_record_id='windows:' + HOST_READINESS_TEST_RELATIVE,
            expected_platform='windows',
            expected_relative_path=HOST_READINESS_TEST_RELATIVE,
            expected_executable=expected_host_executable):
        failures.append('host_composite_windows_provenance_mismatch')
    if windows_record.get('validated_pass') is not True:
        failures.append('host_composite_windows_record_invalid')
    if windows_record.get('expected_ids') != expected_ids:
        failures.append('host_composite_windows_ids_mismatch')
    skipped_ids = windows_record.get('skipped_ids', [])
    if (not isinstance(skipped_ids, list)
            or not set(skipped_ids).issubset(HOST_READINESS_POSIX_CASE_IDS)):
        failures.append('host_composite_windows_skip_invalid')
    if (not isinstance(posix_records, dict)
            or set(posix_records) != set(HOST_READINESS_POSIX_CASE_IDS)):
        failures.append('host_composite_posix_record_set_mismatch')
        posix_records = {} if not isinstance(posix_records, dict) else posix_records
    posix_passed = set()
    observed_record_ids = []
    for case_id in HOST_READINESS_POSIX_CASE_IDS:
        record = posix_records.get(case_id)
        if not isinstance(record, dict):
            failures.append('host_composite_posix_record_missing:' + case_id)
            continue
        observed_record_ids.append(record.get('record_id'))
        if not _valid_platform_unittest_record_provenance(
                record,
                expected_record_id=(
                    HOST_READINESS_POSIX_SUITE_BY_CASE_ID[case_id]),
                expected_platform='posix_wsl',
                expected_relative_path=HOST_READINESS_TEST_RELATIVE,
                expected_executable=expected_posix_executable,
                expected_requested_executable_entry='/usr/bin/python3',
                expected_wsl_distribution=WSL_DISTRIBUTION):
            failures.append(
                'host_composite_posix_provenance_mismatch:' + case_id)
        if (record.get('validated_pass') is not True
                or record.get('expected_ids') != [case_id]
                or record.get('passed_ids') != [case_id]
                or record.get('failed') != 0
                or record.get('skipped') != 0):
            failures.append('host_composite_posix_companion_not_passed:' + case_id)
        else:
            posix_passed.add(case_id)
        if (record.get('post_identity') != windows_record.get('post_identity')
                or record.get('helper_identity')
                != windows_record.get('helper_identity')):
            failures.append('host_composite_source_or_helper_identity_mismatch')
    if len(observed_record_ids) != len(set(observed_record_ids)):
        failures.append('host_composite_duplicate_posix_companion')
    windows_passed = set(windows_record.get('passed_ids', []))
    if windows_passed | posix_passed != set(expected_ids):
        failures.append('host_composite_logical_id_coverage_mismatch')
    failures = list(dict.fromkeys(failures))
    records = [
        record for record in posix_records.values()
        if isinstance(record, dict)]
    return {
        'runner': 'platform_composite_isolated_unittest',
        'expected': len(expected_ids),
        'expected_ids': expected_ids,
        'collected': len(expected_ids) if not failures else 0,
        'passed': len(expected_ids) if not failures else 0,
        'failed': 0 if not failures else max(1, len(expected_ids)),
        'skipped': 0,
        'validated_pass': not failures,
        'raw_windows': windows_record,
        'raw_posix_companions': posix_records,
        'physical_collected': (
            windows_record.get('collected', 0)
            + sum(record.get('collected', 0) for record in records)),
        'physical_passed': (
            windows_record.get('passed', 0)
            + sum(record.get('passed', 0) for record in records)),
        'physical_failed': (
            windows_record.get('failed', 0)
            + sum(record.get('failed', 0) for record in records)),
        'physical_skipped': (
            windows_record.get('skipped', 0)
            + sum(record.get('skipped', 0) for record in records)),
        'failures': failures,
    }


def validate_frozen_inventory(workspace):
    workspace = Path(workspace).resolve(strict=True)
    failures = []
    wsl_target_manifest = (
        validate_current_generation_wsl_unittest_target_manifest())
    failures.extend(wsl_target_manifest['failures'])
    expected_companion_physical_count = (
        1 + len(HOST_READINESS_POSIX_CASE_IDS))
    if (EXPECTED_CURRENT_GENERATION_PHYSICAL_TEST_COUNT
            != EXPECTED_CURRENT_GENERATION_TEST_COUNT
            + expected_companion_physical_count):
        failures.append(
            'current_generation_physical_manifest_total_mismatch')
    test_root = workspace / 'src/limo_cleanup_perception/test'
    supplemental_counts = {}
    post_fix_counts = {}
    current_generation_counts = {}
    supplemental_files = {
        module.rsplit('.', 1)[-1] + '.py'
        for module, _expected in SUPPLEMENTAL_UNITTEST_TARGETS
    }
    post_fix_files = {
        filename for _suite_id, filename, _expected
        in POST_FIX_PYTEST_STYLE_FILES
    }
    post_fix_files.update(
        filename for _suite_id, filename, _names
        in POST_FIX_SELECTED_PYTEST_STYLE_TARGETS)
    post_fix_files.update(
        module.rsplit('.', 1)[-1] + '.py'
        for _suite_id, module, _expected in POST_FIX_UNITTEST_TARGETS)
    current_generation_files = {
        filename for _suite_id, filename, _expected
        in CURRENT_GENERATION_PYTEST_STYLE_FILES
    }
    current_generation_files.update(
        filename for _suite_id, filename, _names
        in CURRENT_GENERATION_SELECTED_PYTEST_STYLE_TARGETS)
    current_generation_files.update(
        module.rsplit('.', 1)[-1] + '.py'
        for _suite_id, module, _expected
        in CURRENT_GENERATION_UNITTEST_TARGETS)
    current_generation_files.update(
        module.rsplit('.', 1)[-1] + '.py'
        for _suite_id, module, _names
        in CURRENT_GENERATION_SELECTED_UNITTEST_TARGETS)
    current_generation_files.add(Path(EXACT_CLI_TEST_RELATIVE).name)
    expected_test_files = {
        module.rsplit('.', 1)[-1] + '.py' for module, _ in UNITTEST_TARGETS
    }
    expected_test_files.update(name for name, _ in PYTEST_STYLE_FILES)
    expected_test_files.update(name for name, _ in PYTEST_STYLE_TARGETS)
    expected_test_files.update(ENVIRONMENT_ONLY_TEST_FILES)
    actual_test_files = {path.name for path in test_root.glob('test_*.py')}
    missing_post_freeze = POST_FREEZE_TEST_FILES - actual_test_files
    missing_supplemental = supplemental_files - actual_test_files
    missing_post_fix = post_fix_files - actual_test_files
    missing_current_generation = (
        current_generation_files - actual_test_files)
    failures.extend(
        'post_freeze_test_file_missing:' + name
        for name in sorted(missing_post_freeze))
    failures.extend(
        'supplemental_test_file_missing:' + name
        for name in sorted(missing_supplemental))
    failures.extend(
        'post_fix_test_file_missing:' + name
        for name in sorted(missing_post_fix))
    failures.extend(
        'current_generation_test_file_missing:' + name
        for name in sorted(missing_current_generation))
    if (not expected_test_files.issubset(actual_test_files)
            or not (actual_test_files - expected_test_files).issubset(
                POST_FREEZE_TEST_FILES | supplemental_files
                | post_fix_files | current_generation_files)):
        failures.append('frozen_test_file_inventory_mismatch')

    module_counts = {}
    for module, expected in UNITTEST_TARGETS:
        filename = module.rsplit('.', 1)[-1] + '.py'
        path = test_root / filename
        try:
            actual = count_static_test_cases(path)
        except (OSError, SyntaxError, ValueError):
            actual = -1
        module_counts[filename] = actual
        if actual != expected:
            failures.append('frozen_test_count_mismatch:' + filename)
    for filename, expected in PYTEST_STYLE_FILES:
        path = test_root / filename
        try:
            actual = count_static_test_cases(path)
        except (OSError, SyntaxError, ValueError):
            actual = -1
        module_counts[filename] = actual
        if actual != expected:
            failures.append('frozen_test_count_mismatch:' + filename)
    for filename, names in PYTEST_STYLE_TARGETS:
        path = test_root / filename
        try:
            tree = ast.parse(path.read_text(encoding='utf-8'))
            actual_names = {
                node.name for node in tree.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
        except (OSError, SyntaxError):
            actual_names = set()
        selected = set(names)
        module_counts[filename] = len(selected)
        if len(selected) != len(names) or not selected.issubset(actual_names):
            failures.append('frozen_test_id_mismatch:' + filename)
    total = sum(value for value in module_counts.values() if value >= 0)
    if total != EXPECTED_TEST_COUNT:
        failures.append('frozen_test_total_mismatch')

    ros1_test_path = workspace / ROS1_INDEXER_TEST
    try:
        ros1_test_count = count_static_test_cases(ros1_test_path)
    except (OSError, SyntaxError, ValueError):
        ros1_test_count = -1
    if ros1_test_count != EXPECTED_ROS1_TEST_COUNT:
        failures.append('ros1_test_count_mismatch')
    if (EXPECTED_TEST_COUNT + sum(POST_FREEZE_TEST_COUNTS.values())
            + EXPECTED_ROS1_TEST_COUNT != EXPECTED_GRAND_TEST_COUNT):
        failures.append('internal_grand_test_count_mismatch')

    expected_ast = set(FROZEN_AST_FILES)
    if len(expected_ast) != EXPECTED_AST_COUNT:
        failures.append('internal_ast_manifest_count_mismatch')
    ast_failures = []
    for relative in FROZEN_AST_FILES:
        path = workspace / relative
        try:
            source = path.read_text(encoding='utf-8')
            ast.parse(source, filename=str(path), feature_version=8)
            compile(source, str(path), 'exec')
        except (OSError, SyntaxError, ValueError) as error:
            ast_failures.append(
                '{}:{}'.format(relative, type(error).__name__))
    if ast_failures:
        failures.append('python38_ast_or_compile_failed')

    present_post_freeze = sorted(
        name for name in POST_FREEZE_TEST_FILES
        if (test_root / name).is_file())
    post_freeze_ast_failures = []
    for name in present_post_freeze:
        path = test_root / name
        try:
            source = path.read_text(encoding='utf-8')
            ast.parse(source, filename=str(path), feature_version=8)
            compile(source, str(path), 'exec')
            if count_static_test_cases(path) != POST_FREEZE_TEST_COUNTS[name]:
                failures.append('post_freeze_test_count_mismatch:' + name)
        except (OSError, SyntaxError, ValueError) as error:
            post_freeze_ast_failures.append(
                '{}:{}'.format(name, type(error).__name__))
    if post_freeze_ast_failures:
        failures.append('post_freeze_python38_ast_or_compile_failed')

    supplemental_ast_failures = []
    for module, expected in SUPPLEMENTAL_UNITTEST_TARGETS:
        filename = module.rsplit('.', 1)[-1] + '.py'
        path = test_root / filename
        try:
            source = path.read_text(encoding='utf-8')
            ast.parse(source, filename=str(path), feature_version=8)
            compile(source, str(path), 'exec')
            declared_ids = set(static_unittest_ids(path, module))
            selected_ids = set(SUPPLEMENTAL_UNITTEST_SELECTED_IDS)
            actual = len(selected_ids)
            if (len(selected_ids) != len(SUPPLEMENTAL_UNITTEST_SELECTED_IDS)
                    or not selected_ids.issubset(declared_ids)):
                actual = -1
        except (OSError, SyntaxError, ValueError) as error:
            actual = -1
            supplemental_ast_failures.append(
                '{}:{}'.format(filename, type(error).__name__))
        supplemental_counts[filename] = actual
        if actual != expected:
            failures.append('supplemental_test_count_mismatch:' + filename)
    if supplemental_ast_failures:
        failures.append('supplemental_python38_ast_or_compile_failed')

    post_fix_perception_ast_failures = []
    if (len(set(POST_FIX_PERCEPTION_AST_FILES))
            != EXPECTED_POST_FIX_PERCEPTION_AST_COUNT):
        failures.append('internal_post_fix_perception_ast_count_mismatch')
    expected_post_fix_by_file = {
        filename: expected for _suite_id, filename, expected
        in POST_FIX_PYTEST_STYLE_FILES
    }
    expected_post_fix_by_file.update({
        module.rsplit('.', 1)[-1] + '.py': expected
        for _suite_id, module, expected in POST_FIX_UNITTEST_TARGETS
    })
    for relative in POST_FIX_PERCEPTION_AST_FILES:
        path = workspace / relative
        try:
            source = path.read_text(encoding='utf-8')
            ast.parse(source, filename=str(path), feature_version=8)
            compile(source, str(path), 'exec')
            if path.name in expected_post_fix_by_file:
                actual = count_static_test_cases(path)
                post_fix_counts[path.name] = actual
                if actual != expected_post_fix_by_file[path.name]:
                    failures.append(
                        'post_fix_test_count_mismatch:' + path.name)
        except (OSError, SyntaxError, ValueError) as error:
            post_fix_perception_ast_failures.append(
                '{}:{}'.format(relative, type(error).__name__))
            if path.name in expected_post_fix_by_file:
                post_fix_counts[path.name] = -1
    for _suite_id, filename, names in POST_FIX_SELECTED_PYTEST_STYLE_TARGETS:
        path = test_root / filename
        try:
            tree = ast.parse(path.read_text(encoding='utf-8'))
            actual_names = {
                node.name for node in tree.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
        except (OSError, SyntaxError):
            actual_names = set()
        selected = set(names)
        if len(selected) != len(names) or not selected.issubset(actual_names):
            failures.append('post_fix_test_id_mismatch:' + filename)
            post_fix_counts[filename] = -1
        else:
            post_fix_counts[filename] = len(names)
    if post_fix_perception_ast_failures:
        failures.append('post_fix_perception_python38_ast_or_compile_failed')
    if (sum(value for value in post_fix_counts.values() if value >= 0)
            != EXPECTED_POST_FIX_TEST_COUNT):
        failures.append('post_fix_test_total_mismatch')

    current_generation_ast_failures = []
    if (len(set(CURRENT_GENERATION_PERCEPTION_AST_FILES))
            != EXPECTED_CURRENT_GENERATION_PERCEPTION_AST_COUNT):
        failures.append(
            'internal_current_generation_perception_ast_count_mismatch')
    expected_current_by_file = {
        filename: expected for _suite_id, filename, expected
        in CURRENT_GENERATION_PYTEST_STYLE_FILES
    }
    expected_current_by_file.update({
        module.rsplit('.', 1)[-1] + '.py': expected
        for _suite_id, module, expected
        in CURRENT_GENERATION_UNITTEST_TARGETS
    })
    for relative in CURRENT_GENERATION_PERCEPTION_AST_FILES:
        path = workspace / relative
        try:
            source = path.read_text(encoding='utf-8')
            ast.parse(source, filename=str(path), feature_version=8)
            compile(source, str(path), 'exec')
            if path.name in expected_current_by_file:
                actual = count_static_test_cases(path)
                current_generation_counts[path.name] = actual
                if actual != expected_current_by_file[path.name]:
                    failures.append(
                        'current_generation_test_count_mismatch:'
                        + path.name)
        except (OSError, SyntaxError, ValueError) as error:
            current_generation_ast_failures.append(
                '{}:{}'.format(relative, type(error).__name__))
            if path.name in expected_current_by_file:
                current_generation_counts[path.name] = -1
    for _suite_id, filename, names in (
            CURRENT_GENERATION_SELECTED_PYTEST_STYLE_TARGETS):
        path = test_root / filename
        try:
            tree = ast.parse(path.read_text(encoding='utf-8'))
            actual_names = {
                node.name for node in tree.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
        except (OSError, SyntaxError):
            actual_names = set()
        selected = set(names)
        if len(selected) != len(names) or not selected.issubset(actual_names):
            failures.append(
                'current_generation_test_id_mismatch:' + filename)
            current_generation_counts[filename] = -1
        else:
            current_generation_counts[filename] = len(names)
    for suite_id, module, names in (
            CURRENT_GENERATION_SELECTED_UNITTEST_TARGETS):
        path = test_root / (module.rsplit('.', 1)[-1] + '.py')
        try:
            actual_ids = set(static_unittest_ids(path, module))
        except (OSError, SyntaxError, ValueError):
            actual_ids = set()
        selected_ids = set(names)
        if (len(selected_ids) != len(names)
                or not selected_ids.issubset(actual_ids)):
            failures.append(
                'current_generation_test_id_mismatch:' + suite_id)
            current_generation_counts[suite_id] = -1
        else:
            current_generation_counts[suite_id] = len(names)
    for suite_id, relative, expected in (
            CURRENT_GENERATION_ROS1_UNITTEST_TARGETS):
        path = workspace / relative
        try:
            actual = count_static_test_cases(path)
        except (OSError, SyntaxError, ValueError):
            actual = -1
        current_generation_counts[suite_id] = actual
        if actual != expected:
            failures.append(
                'current_generation_test_count_mismatch:' + suite_id)
    exact_path = workspace / EXACT_CLI_TEST_RELATIVE
    try:
        exact_count = count_static_test_cases(exact_path)
    except (OSError, SyntaxError, ValueError):
        exact_count = -1
    current_generation_counts[
        CURRENT_GENERATION_EXACT_UNITTEST_TARGET[0]] = exact_count
    if exact_count != EXACT_CLI_TEST_COUNT:
        failures.append(
            'current_generation_test_count_mismatch:'
            + CURRENT_GENERATION_EXACT_UNITTEST_TARGET[0])
    probe_path = workspace / ROS1_ISOLATED_PROBE_TEST_RELATIVE
    try:
        probe_count = count_static_test_cases(probe_path)
    except (OSError, SyntaxError, ValueError):
        probe_count = -1
    for probe_suite_id in (
            ROS1_ISOLATED_PROBE_PYTHON3_SUITE_ID,
            ROS1_ISOLATED_PROBE_PYTHON3_14_SUITE_ID):
        current_generation_counts[probe_suite_id] = probe_count
        if probe_count != ROS1_ISOLATED_PROBE_TEST_COUNT:
            failures.append(
                'current_generation_test_count_mismatch:' + probe_suite_id)
    if current_generation_ast_failures:
        failures.append(
            'current_generation_perception_python38_ast_or_compile_failed')
    if (sum(
            value for value in current_generation_counts.values()
            if value >= 0) != EXPECTED_CURRENT_GENERATION_TEST_COUNT):
        failures.append('current_generation_test_total_mismatch')

    ros1_ast_failures = []
    if len(set(ROS1_AST_FILES)) != EXPECTED_ROS1_AST_COUNT:
        failures.append('internal_ros1_ast_manifest_count_mismatch')
    for relative in ROS1_AST_FILES:
        path = workspace / relative
        try:
            source = path.read_text(encoding='utf-8')
            ast.parse(source, filename=str(path), feature_version=8)
            compile(source, str(path), 'exec')
        except (OSError, SyntaxError, ValueError) as error:
            ros1_ast_failures.append(
                '{}:{}'.format(relative, type(error).__name__))
    if ros1_ast_failures:
        failures.append('ros1_python38_ast_or_compile_failed')

    post_fix_ros1_ast_failures = []
    if (len(set(POST_FIX_ROS1_AST_FILES))
            != EXPECTED_POST_FIX_ROS1_AST_COUNT):
        failures.append('internal_post_fix_ros1_ast_count_mismatch')
    for relative in POST_FIX_ROS1_AST_FILES:
        path = workspace / relative
        try:
            source = path.read_text(encoding='utf-8')
            ast.parse(source, filename=str(path), feature_version=8)
            compile(source, str(path), 'exec')
        except (OSError, SyntaxError, ValueError) as error:
            post_fix_ros1_ast_failures.append(
                '{}:{}'.format(relative, type(error).__name__))
    if post_fix_ros1_ast_failures:
        failures.append('post_fix_ros1_python38_ast_or_compile_failed')

    current_generation_ros1_ast_failures = []
    if (len(set(CURRENT_GENERATION_ROS1_AST_FILES))
            != EXPECTED_CURRENT_GENERATION_ROS1_AST_COUNT):
        failures.append(
            'internal_current_generation_ros1_ast_count_mismatch')
    for relative in CURRENT_GENERATION_ROS1_AST_FILES:
        path = workspace / relative
        try:
            source = path.read_text(encoding='utf-8')
            ast.parse(source, filename=str(path), feature_version=8)
            compile(source, str(path), 'exec')
        except (OSError, SyntaxError, ValueError) as error:
            current_generation_ros1_ast_failures.append(
                '{}:{}'.format(relative, type(error).__name__))
    if current_generation_ros1_ast_failures:
        failures.append(
            'current_generation_ros1_python38_ast_or_compile_failed')

    ros1_python = {
        path.relative_to(workspace).as_posix()
        for path in (workspace / (
            'ros1_overlay_src/limo_cleanup_ros1_perception')).rglob('*.py')
        if not set(path.parts).intersection(EXCLUDED_SNAPSHOT_PARTS)
    }
    expected_ros1_python = (
        set(ROS1_AST_FILES) | set(POST_FIX_ROS1_AST_FILES)
        | set(CURRENT_GENERATION_ROS1_AST_FILES))
    if ros1_python != expected_ros1_python:
        failures.append('python38_ros1_inventory_mismatch')

    perception_python = {
        path.relative_to(workspace).as_posix()
        for path in (workspace / 'src/limo_cleanup_perception').rglob('*.py')
        if not set(path.parts).intersection(EXCLUDED_SNAPSHOT_PARTS)
    }
    expected_perception = {
        item for item in FROZEN_AST_FILES
        if item.startswith('src/limo_cleanup_perception/')
    }
    expected_perception.update(
        'src/limo_cleanup_perception/test/' + name
        for name in present_post_freeze)
    expected_perception.update(
        'src/limo_cleanup_perception/test/' + name
        for name in supplemental_files)
    expected_perception.update(POST_FIX_PERCEPTION_AST_FILES)
    expected_perception.update(CURRENT_GENERATION_PERCEPTION_AST_FILES)
    if perception_python != expected_perception:
        failures.append('python38_perception_inventory_mismatch')
    scripts_python = {
        path.relative_to(workspace).as_posix()
        for path in (workspace / 'scripts').rglob('*.py')
        if not set(path.parts).intersection(EXCLUDED_SNAPSHOT_PARTS)
    }
    expected_scripts = {
        item for item in FROZEN_AST_FILES if item.startswith('scripts/')
    }
    expected_scripts.add('scripts/run_perception_v2_frozen_regression.py')
    if scripts_python != expected_scripts:
        failures.append('python38_scripts_inventory_mismatch')

    post_fix_source_files = set(POST_FIX_PERCEPTION_AST_FILES) | set(
        POST_FIX_ROS1_AST_FILES)
    current_generation_source_files = set(
        CURRENT_GENERATION_PERCEPTION_AST_FILES)
    current_generation_ros1_source_files = set(
        CURRENT_GENERATION_ROS1_AST_FILES)
    generation_source_files = (
        post_fix_source_files | current_generation_source_files
        | current_generation_ros1_source_files)
    snapshotted = {
        path.relative_to(workspace).as_posix()
        for path in _snapshot_paths(workspace)
    }
    if not generation_source_files.issubset(snapshotted):
        failures.append('post_fix_source_snapshot_inventory_mismatch')
    return {
        'expected_test_count': EXPECTED_TEST_COUNT,
        'actual_static_test_count': total,
        'module_counts': module_counts,
        'expected_ast_files': EXPECTED_AST_COUNT,
        'ast_passed_files': EXPECTED_AST_COUNT - len(ast_failures),
        'ast_failures': ast_failures,
        'post_freeze_ast_files': present_post_freeze,
        'post_freeze_ast_passed_files': (
            len(present_post_freeze) - len(post_freeze_ast_failures)),
        'post_freeze_ast_failures': post_freeze_ast_failures,
        'supplemental_test_counts': supplemental_counts,
        'supplemental_test_count': sum(
            value for value in supplemental_counts.values() if value >= 0),
        'supplemental_ast_passed_files': (
            len(SUPPLEMENTAL_UNITTEST_TARGETS)
            - len(supplemental_ast_failures)),
        'supplemental_ast_failures': supplemental_ast_failures,
        'supplemental_included_in_grand_total': False,
        'post_fix_test_counts': post_fix_counts,
        'post_fix_test_count': sum(
            value for value in post_fix_counts.values() if value >= 0),
        'expected_post_fix_test_count': EXPECTED_POST_FIX_TEST_COUNT,
        'post_fix_perception_ast_files': list(
            POST_FIX_PERCEPTION_AST_FILES),
        'post_fix_perception_ast_passed_files': (
            EXPECTED_POST_FIX_PERCEPTION_AST_COUNT
            - len(post_fix_perception_ast_failures)),
        'post_fix_perception_ast_failures': (
            post_fix_perception_ast_failures),
        'post_fix_included_in_grand_total': False,
        'current_generation_test_counts': current_generation_counts,
        'current_generation_test_count': sum(
            value for value in current_generation_counts.values()
            if value >= 0),
        'expected_current_generation_test_count': (
            EXPECTED_CURRENT_GENERATION_TEST_COUNT),
        'expected_current_generation_physical_test_count': (
            EXPECTED_CURRENT_GENERATION_PHYSICAL_TEST_COUNT),
        'current_generation_wsl_unittest_target_manifest': (
            wsl_target_manifest),
        'current_generation_perception_ast_files': list(
            CURRENT_GENERATION_PERCEPTION_AST_FILES),
        'current_generation_perception_ast_passed_files': (
            EXPECTED_CURRENT_GENERATION_PERCEPTION_AST_COUNT
            - len(current_generation_ast_failures)),
        'current_generation_perception_ast_failures': (
            current_generation_ast_failures),
        'current_generation_included_in_grand_total': False,
        'current_generation_included_in_post_fix_total': False,
        'expected_ros1_test_count': EXPECTED_ROS1_TEST_COUNT,
        'actual_ros1_static_test_count': ros1_test_count,
        'expected_ros1_ast_files': EXPECTED_ROS1_AST_COUNT,
        'ros1_ast_passed_files': (
            EXPECTED_ROS1_AST_COUNT - len(ros1_ast_failures)),
        'ros1_ast_failures': ros1_ast_failures,
        'post_fix_ros1_ast_files': list(POST_FIX_ROS1_AST_FILES),
        'post_fix_ros1_ast_passed_files': (
            EXPECTED_POST_FIX_ROS1_AST_COUNT
            - len(post_fix_ros1_ast_failures)),
        'post_fix_ros1_ast_failures': post_fix_ros1_ast_failures,
        'current_generation_ros1_ast_files': list(
            CURRENT_GENERATION_ROS1_AST_FILES),
        'current_generation_ros1_ast_passed_files': (
            EXPECTED_CURRENT_GENERATION_ROS1_AST_COUNT
            - len(current_generation_ros1_ast_failures)),
        'current_generation_ros1_ast_failures': (
            current_generation_ros1_ast_failures),
        'total_ros1_ast_files': len(expected_ros1_python),
        'total_ros1_ast_passed_files': (
            len(expected_ros1_python) - len(ros1_ast_failures)
            - len(post_fix_ros1_ast_failures)
            - len(current_generation_ros1_ast_failures)),
        'post_fix_source_snapshot_files': sorted(post_fix_source_files),
        'current_generation_source_snapshot_files': sorted(
            current_generation_source_files
            | current_generation_ros1_source_files),
        'expected_grand_test_count': EXPECTED_GRAND_TEST_COUNT,
        'failures': failures,
    }


def _strict_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('duplicate JSON key: ' + key)
        value[key] = item
    return value


def _invalid_json_constant(value):
    raise ValueError('non-finite JSON constant: ' + value)


def _authority_entry_value_matches(actual, expected):
    if isinstance(expected, bool):
        return actual is expected
    return actual == expected


def _authority_path_linklike_parts(workspace, path):
    workspace = Path(workspace).resolve(strict=True)
    candidate = Path(path)
    parts = []
    while candidate != workspace:
        if _is_linklike(candidate):
            try:
                parts.append(candidate.relative_to(workspace).as_posix())
            except ValueError:
                parts.append(str(candidate))
        parent = candidate.parent
        if parent == candidate:
            break
        candidate = parent
    return sorted(set(parts))


def _validate_authority_evidence_payload(evidence_id, payload):
    failures = []
    if not isinstance(payload, dict):
        return ['evidence_authority_artifact_payload_invalid:' + evidence_id]
    if payload.get('report_kind') != REPORT_KIND:
        failures.append(
            'evidence_authority_artifact_report_kind_invalid:' + evidence_id)
    if payload.get('delivery_ready') is not False:
        failures.append(
            'evidence_authority_artifact_delivery_claim:' + evidence_id)
    if payload.get('regression_passed') is not False:
        failures.append(
            'evidence_authority_artifact_regression_state_invalid:'
            + evidence_id)
    if payload.get('delivery_scope') != EVIDENCE_AUTHORITY_CURRENT_SCOPE:
        failures.append(
            'evidence_authority_artifact_scope_invalid:' + evidence_id)
    test_matrix = payload.get('test_matrix')
    if not isinstance(test_matrix, dict):
        failures.append(
            'evidence_authority_artifact_test_matrix_missing:' + evidence_id)
        test_matrix = {}
    if evidence_id == 'ros1_canonical_source_binding_v6':
        if not test_matrix.get('failures'):
            failures.append(
                'evidence_authority_stale_failure_not_proven:' + evidence_id)
    elif evidence_id in (
            'ros1_canonical_source_binding_v6_final',
            EVIDENCE_AUTHORITY_CURRENT_ID):
        if (test_matrix.get('grand_total_passed') != 194
                or test_matrix.get('grand_total_collected') != 194
                or test_matrix.get('supplemental_passed') != 10
                or test_matrix.get('supplemental_collected') != 10
                or test_matrix.get('failures') != []):
            failures.append(
                'evidence_authority_offline_matrix_invalid:' + evidence_id)
    if evidence_id == EVIDENCE_AUTHORITY_CURRENT_ID:
        delivery = payload.get('delivery_gate_summary')
        formal = (
            delivery.get('formal_field_evidence_gate', {})
            if isinstance(delivery, dict) else {})
        ros1_field = (
            delivery.get('ros1_field_gate', {})
            if isinstance(delivery, dict) else {})
        source_drift = payload.get('source_drift')
        diff_check = payload.get('diff_check')
        diff_command = (
            diff_check.get('command', {})
            if isinstance(diff_check, dict) else {})
        if (not isinstance(delivery, dict)
                or delivery.get('delivery_ready') is not False
                or formal.get('formal_four_scene_frame_denominator') != 0
                or formal.get('formal_tf_pass') is not False
                or formal.get('formal_3d_pass') is not False
                or formal.get('validated_pass') is not False
                or ros1_field.get('validated_pass') is not False
                or not isinstance(source_drift, dict)
                or source_drift.get('unchanged') is not True
                or not isinstance(diff_check, dict)
                or diff_check.get('failures') != []
                or diff_command.get('exit_code') != 0):
            failures.append(
                'evidence_authority_current_scope_not_blocked:'
                + evidence_id)
    return failures


def validate_evidence_authority_index(workspace_root, authority_index):
    """Resolve exactly one immutable, blocked offline baseline.

    This function validates the index contents and reopens all three bound
    artifacts.  It intentionally returns no selected evidence when any check
    fails, even if a malformed index happens to contain one current marker.
    The index file identity itself is checked by
    :func:`load_and_resolve_evidence_authority_index`.
    """
    workspace = Path(workspace_root).resolve(strict=True)
    failures = []
    identities = []
    declared_current_id = None
    candidate_current = None
    candidate_current_identity = None
    if not isinstance(authority_index, dict):
        return {
            'gate_id': EVIDENCE_AUTHORITY_GATE_ID,
            'scope': 'offline_evidence_selection_authority',
            'validated_pass': False,
            'failures': ['evidence_authority_index_payload_invalid'],
            'declared_current_evidence_id': None,
            'current_evidence': None,
            'current_identity': None,
            'artifact_identities': [],
            'authorizes_field_delivery': False,
            'delivery_ready': False,
        }

    expected_top = {
        'schema_version': EVIDENCE_AUTHORITY_SCHEMA_VERSION,
        'index_id': EVIDENCE_AUTHORITY_INDEX_ID,
        'index_kind': EVIDENCE_AUTHORITY_INDEX_KIND,
        'evidence_lineage': EVIDENCE_AUTHORITY_LINEAGE,
        'immutable': True,
        'current_evidence_id': EVIDENCE_AUTHORITY_CURRENT_ID,
    }
    if set(authority_index) != set(expected_top).union({
            'selection_policy', 'entries'}):
        failures.append('evidence_authority_top_level_keys_mismatch')
    for key, expected in expected_top.items():
        if not _authority_entry_value_matches(
                authority_index.get(key), expected):
            failures.append('evidence_authority_top_level_mismatch:' + key)
    declared_current_id = authority_index.get('current_evidence_id')

    expected_policy = {
        'exactly_one_current': True,
        'accept_only_index_selected_current': True,
        'filename_mtime_selection_forbidden': True,
        'current_required_status': EVIDENCE_AUTHORITY_CURRENT_STATUS,
        'current_required_scope': EVIDENCE_AUTHORITY_CURRENT_SCOPE,
        'authorizes_field_delivery': False,
    }
    policy = authority_index.get('selection_policy')
    if not isinstance(policy, dict):
        failures.append('evidence_authority_selection_policy_missing')
    else:
        if set(policy) != set(expected_policy):
            failures.append(
                'evidence_authority_selection_policy_keys_mismatch')
        for key, expected in expected_policy.items():
            if not _authority_entry_value_matches(
                    policy.get(key), expected):
                failures.append(
                    'evidence_authority_selection_policy_mismatch:' + key)

    entries = authority_index.get('entries')
    if not isinstance(entries, list):
        failures.append('evidence_authority_entries_invalid')
        entries = []
    if len(entries) != len(EXPECTED_EVIDENCE_AUTHORITY_ENTRIES):
        failures.append('evidence_authority_entry_count_mismatch')

    expected_by_id = {
        item['evidence_id']: item
        for item in EXPECTED_EVIDENCE_AUTHORITY_ENTRIES}
    ids = []
    paths = []
    for position, item in enumerate(entries):
        if not isinstance(item, dict):
            continue
        evidence_id = item.get('evidence_id')
        declared_path = item.get('path')
        if isinstance(evidence_id, str):
            ids.append(evidence_id)
        else:
            failures.append(
                'evidence_authority_evidence_id_invalid:' + str(position))
        if isinstance(declared_path, str):
            paths.append(declared_path)
        else:
            failures.append(
                'evidence_authority_artifact_path_invalid:' + str(position))
    if len(ids) != len(set(ids)):
        failures.append('evidence_authority_duplicate_evidence_id')
    if len(paths) != len(set(paths)):
        failures.append('evidence_authority_duplicate_path')
    if set(ids) != set(expected_by_id):
        failures.append('evidence_authority_entry_set_mismatch')

    current_entries = []
    current_baselines = []
    for position, entry in enumerate(entries):
        if not isinstance(entry, dict):
            failures.append(
                'evidence_authority_entry_invalid:' + str(position))
            continue
        evidence_id = entry.get('evidence_id')
        diagnostic_id = (
            evidence_id if isinstance(evidence_id, str)
            else 'entry-' + str(position))
        required_state = (
            'lifecycle', 'status', 'is_current', 'current_baseline')
        if any(key not in entry for key in required_state):
            failures.append(
                'evidence_authority_status_or_lifecycle_missing')
        if entry.get('is_current') is True:
            current_entries.append(entry)
        if entry.get('current_baseline') is True:
            current_baselines.append(entry)
        expected = expected_by_id.get(evidence_id)
        if expected is None:
            continue
        if set(entry) != set(expected):
            failures.append(
                'evidence_authority_entry_keys_mismatch:' + diagnostic_id)
        for key, expected_value in expected.items():
            if not _authority_entry_value_matches(
                    entry.get(key), expected_value):
                failures.append(
                    'evidence_authority_entry_binding_mismatch:{}:{}'.format(
                        diagnostic_id, key))

        declared_path = entry.get('path')
        if not isinstance(declared_path, str):
            failures.append(
                'evidence_authority_artifact_path_invalid:' + diagnostic_id)
            continue
        relative = Path(declared_path)
        if (relative.is_absolute() or relative.drive
                or '..' in relative.parts):
            failures.append(
                'evidence_authority_artifact_path_escape:' + diagnostic_id)
            continue
        artifact = workspace / relative
        linklike_parts = _authority_path_linklike_parts(workspace, artifact)
        if linklike_parts:
            failures.append(
                'evidence_authority_artifact_link_forbidden:' + diagnostic_id)
            continue
        try:
            resolved = artifact.resolve(strict=True)
            resolved.relative_to(workspace)
            mode = resolved.stat().st_mode
            if not stat.S_ISREG(mode):
                raise OSError('not a regular file')
            artifact_bytes = resolved.read_bytes()
            identity = {
                'path': resolved.relative_to(workspace).as_posix(),
                'size_bytes': len(artifact_bytes),
                'sha256': _sha256_bytes(artifact_bytes),
            }
        except (OSError, RuntimeError, ValueError):
            failures.append(
                'evidence_authority_artifact_unreadable:' + diagnostic_id)
            continue
        identities.append(dict(identity, evidence_id=diagnostic_id))
        if identity['path'] != declared_path:
            failures.append(
                'evidence_authority_artifact_path_mismatch:' + diagnostic_id)
        if identity['size_bytes'] != entry.get('size_bytes'):
            failures.append(
                'evidence_authority_artifact_size_mismatch:' + diagnostic_id)
        if identity['sha256'] != entry.get('sha256'):
            failures.append(
                'evidence_authority_artifact_sha256_mismatch:'
                + diagnostic_id)
        try:
            payload = json.loads(
                artifact_bytes.decode('utf-8'),
                object_pairs_hook=_strict_object,
                parse_constant=_invalid_json_constant)
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
            failures.append(
                'evidence_authority_artifact_json_invalid:' + diagnostic_id)
        else:
            failures.extend(_validate_authority_evidence_payload(
                diagnostic_id, payload))
        if evidence_id == EVIDENCE_AUTHORITY_CURRENT_ID:
            candidate_current = dict(entry)
            candidate_current_identity = dict(identity)

    if len(current_entries) != 1:
        failures.append('evidence_authority_current_count_invalid')
    if len(current_baselines) != 1:
        failures.append(
            'evidence_authority_current_baseline_count_invalid')
    if (len(current_entries) == 1 and len(current_baselines) == 1
            and current_entries[0].get('evidence_id')
            != current_baselines[0].get('evidence_id')):
        failures.append('evidence_authority_current_marker_mismatch')
    if (len(current_entries) != 1
            or current_entries[0].get('evidence_id')
            != declared_current_id
            or declared_current_id != EVIDENCE_AUTHORITY_CURRENT_ID):
        failures.append('evidence_authority_current_id_mismatch')

    failures = sorted(set(failures))
    validated_pass = not failures
    return {
        'gate_id': EVIDENCE_AUTHORITY_GATE_ID,
        'scope': 'offline_evidence_selection_authority',
        'validated_pass': validated_pass,
        'failures': failures,
        'declared_current_evidence_id': declared_current_id,
        'selection_policy': expected_policy,
        'current_evidence': (
            candidate_current if validated_pass else None),
        'current_identity': (
            candidate_current_identity if validated_pass else None),
        'artifact_identities': sorted(
            identities, key=lambda item: item.get('evidence_id', '')),
        'accept_only_index_selected_current': True,
        'filename_mtime_selection_forbidden': True,
        'authorizes_field_delivery': False,
        'delivery_ready': False,
    }


def load_and_resolve_evidence_authority_index(workspace_root):
    """Load the fixed authority index and fail closed on any trust drift."""
    workspace = Path(workspace_root).resolve(strict=True)
    declared = workspace / EVIDENCE_AUTHORITY_INDEX_RELATIVE
    failures = []
    index_identity = None
    index_bytes = None
    payload = None
    try:
        if _authority_path_linklike_parts(workspace, declared):
            failures.append('evidence_authority_index_link_forbidden')
        resolved = declared.resolve(strict=True)
        relative = resolved.relative_to(workspace).as_posix()
        if relative != EVIDENCE_AUTHORITY_INDEX_RELATIVE:
            failures.append('evidence_authority_index_path_mismatch')
        if not stat.S_ISREG(resolved.stat().st_mode):
            failures.append('evidence_authority_index_not_regular')
        index_bytes = resolved.read_bytes()
        index_identity = {
            'path': relative,
            'size_bytes': len(index_bytes),
            'sha256': _sha256_bytes(index_bytes),
        }
    except (OSError, RuntimeError, ValueError):
        resolved = declared
        failures.append('evidence_authority_index_missing_or_unreadable')

    if (EVIDENCE_AUTHORITY_INDEX_EXPECTED_SIZE_BYTES is None
            or EVIDENCE_AUTHORITY_INDEX_EXPECTED_SHA256 is None):
        failures.append('evidence_authority_trust_anchor_unconfigured')
    elif index_identity is not None:
        if (index_identity.get('size_bytes')
                != EVIDENCE_AUTHORITY_INDEX_EXPECTED_SIZE_BYTES):
            failures.append('evidence_authority_index_size_mismatch')
        if (index_identity.get('sha256')
                != EVIDENCE_AUTHORITY_INDEX_EXPECTED_SHA256):
            failures.append('evidence_authority_index_sha256_mismatch')

    if index_bytes is not None:
        try:
            payload = json.loads(
                index_bytes.decode('utf-8'),
                object_pairs_hook=_strict_object,
                parse_constant=_invalid_json_constant)
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
            failures.append('evidence_authority_index_invalid_json')
    validation = validate_evidence_authority_index(workspace, payload)
    failures.extend(validation.get('failures', []))
    failures = sorted(set(failures))
    validated_pass = not failures
    validation.update({
        'index_path': str(resolved),
        'index_relative_path': EVIDENCE_AUTHORITY_INDEX_RELATIVE,
        'index_identity': index_identity,
        'expected_index_identity': {
            'path': EVIDENCE_AUTHORITY_INDEX_RELATIVE,
            'size_bytes': EVIDENCE_AUTHORITY_INDEX_EXPECTED_SIZE_BYTES,
            'sha256': EVIDENCE_AUTHORITY_INDEX_EXPECTED_SHA256,
        },
        'validated_pass': validated_pass,
        'failures': failures,
        'current_evidence': (
            validation.get('current_evidence') if validated_pass else None),
        'current_identity': (
            validation.get('current_identity') if validated_pass else None),
    })
    return validation


def write_evidence_authority_index_exclusive(path, payload):
    """Write canonical authority JSON once; never replace existing bytes."""
    path = Path(path)
    serialized = (json.dumps(
        payload, ensure_ascii=False, indent=2, sort_keys=True) + '\n').encode(
            'utf-8')
    with path.open('xb') as stream:
        stream.write(serialized)
        stream.flush()
        os.fsync(stream.fileno())
    return {
        'path': str(path.resolve()),
        'size_bytes': len(serialized),
        'sha256': _sha256_bytes(serialized),
    }


def _delivery_values(value):
    values = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key == 'delivery_ready':
                values.append(child)
            values.extend(_delivery_values(child))
    elif isinstance(value, list):
        for child in value:
            values.extend(_delivery_values(child))
    return values


def _schema_delivery_ready_is_false(schema):
    if not isinstance(schema, dict):
        return False
    properties = schema.get('properties')
    if not isinstance(properties, dict):
        return False
    declaration = properties.get('delivery_ready')
    return (isinstance(declaration, dict)
            and declaration.get('const') is False)


def validate_json_files(workspace, report_path=None):
    workspace = Path(workspace).resolve(strict=True)
    excluded = None if report_path is None else Path(report_path).resolve()
    paths = set((workspace / 'src/limo_cleanup_perception').rglob('*.json'))
    ros1_config = (
        workspace / 'ros1_overlay_src/limo_cleanup_ros1_perception/config')
    if ros1_config.is_dir():
        paths.update(ros1_config.rglob('*.json'))
    evidence = workspace / 'evidence/perception_v2_offline_20260813'
    if evidence.is_dir():
        paths.update(evidence.rglob('*.json'))
    field_evidence = workspace / 'evidence/perception_v2_field_20260814'
    if field_evidence.is_dir():
        paths.update(field_evidence.rglob('*.json'))
    paths = sorted(
        (path for path in paths if path.resolve() != excluded),
        key=lambda item: str(item).lower())
    failures = []
    entries = []
    delivery_claims = 0
    for path in paths:
        relative = path.relative_to(workspace).as_posix()
        try:
            payload = json.loads(
                path.read_text(encoding='utf-8'),
                object_pairs_hook=_strict_object,
                parse_constant=_invalid_json_constant)
            if isinstance(payload, dict) and '$schema' in payload:
                if not _schema_delivery_ready_is_false(payload):
                    failures.append(
                        'json_schema_delivery_ready_not_const_false:'
                        + relative)
            else:
                values = _delivery_values(payload)
                delivery_claims += len(values)
                if any(value is not False for value in values):
                    failures.append(
                        'json_delivery_ready_not_false:' + relative)
            entries.append(_identity(path, relative_to=workspace))
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
            failures.append(
                'strict_json_invalid:{}:{}'.format(
                    relative, type(error).__name__))
    if not paths:
        failures.append('strict_json_scope_empty')
    return {
        'files_checked': len(paths),
        'files_passed': len(paths) - len([
            item for item in failures if item.startswith('strict_json_invalid:')]),
        'delivery_ready_claims': delivery_claims,
        'entries': entries,
        'failures': failures,
    }


def validate_xml_files(workspace):
    workspace = Path(workspace).resolve(strict=True)
    paths = (
        workspace / 'src/limo_cleanup_interfaces/package.xml',
        workspace / 'src/limo_cleanup_perception/package.xml',
        workspace / (
            'ros1_overlay_src/limo_cleanup_ros1_perception/package.xml'),
    )
    failures = []
    entries = []
    for path in paths:
        try:
            root = ET.parse(str(path)).getroot()
            if root.tag != 'package':
                raise ValueError('root is not package')
            entries.append(_identity(path, relative_to=workspace))
        except (OSError, ET.ParseError, ValueError) as error:
            failures.append(
                'xml_invalid:{}:{}'.format(
                    path.relative_to(workspace).as_posix(),
                    type(error).__name__))
    return {
        'files_checked': len(paths),
        'files_passed': len(paths) - len(failures),
        'entries': entries,
        'failures': failures,
    }


def _setup_call(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            function = node.func
            if ((isinstance(function, ast.Name) and function.id == 'setup')
                    or (isinstance(function, ast.Attribute)
                        and function.attr == 'setup')):
                return node
    raise ValueError('setup() call not found')


def _keyword(call, name):
    for item in call.keywords:
        if item.arg == name:
            return item.value
    raise ValueError('setup keyword missing: ' + name)


def _ros2_migration_gate_metadata(validated_pass):
    return {
        'gate_id': ROS2_MIGRATION_INSTALL_GATE_ID,
        'scope': 'offline_migration',
        'required_for_field_delivery': False,
        'substitutes_for_ros1_field': False,
        'claimed_result': None,
        'validated_pass': bool(validated_pass),
        'validated_result': 'PASS' if validated_pass else 'BLOCKED',
        'legacy_fields_preserved': True,
        'legacy_install_scope': 'ros2_ament_migration_only',
    }


def validate_install_declarations(workspace):
    workspace = Path(workspace).resolve(strict=True)
    failures = []
    fixture_names = set()
    console_entries = {}
    try:
        setup_path = workspace / 'src/limo_cleanup_perception/setup.py'
        tree = ast.parse(setup_path.read_text(encoding='utf-8'))
        call = _setup_call(tree)
        python_requires = ast.literal_eval(_keyword(call, 'python_requires'))
        if python_requires != '>=3.8':
            failures.append('python_requires_not_gte_3_8')
        entry_points = ast.literal_eval(_keyword(call, 'entry_points'))
        values = entry_points.get('console_scripts')
        if not isinstance(values, (list, tuple)):
            raise ValueError('console_scripts is not a sequence')
        for raw in values:
            match = re.fullmatch(r'\s*([A-Za-z0-9_]+)\s*=\s*(\S+)\s*', raw)
            if match is None or match.group(1) in console_entries:
                raise ValueError('invalid or duplicate console entry')
            console_entries[match.group(1)] = match.group(2)
        if console_entries != EXPECTED_CONSOLE_ENTRIES:
            failures.append('console_entry_declaration_mismatch')
        data_files_node = _keyword(call, 'data_files')
        fixture_names = {
            value.value.rsplit('/', 1)[-1]
            for value in ast.walk(data_files_node)
            if isinstance(value, ast.Constant)
            and isinstance(value.value, str)
            and value.value.startswith('fixtures/')
            and value.value.endswith('.json')
        }
        actual_fixtures = {
            path.name for path in (
                workspace / 'src/limo_cleanup_perception/fixtures').glob('*.json')
        }
        if not CORE_FIXTURES.issubset(fixture_names):
            failures.append('core_fixture_declaration_missing')
        if fixture_names != actual_fixtures:
            failures.append('fixture_install_declaration_mismatch')
    except (OSError, SyntaxError, ValueError, TypeError) as error:
        failures.append('setup_declaration_invalid:' + type(error).__name__)

    interface_root = workspace / 'src/limo_cleanup_interfaces'
    interface_definitions = sorted(
        path.relative_to(interface_root).as_posix()
        for directory, suffix in (
            ('msg', '.msg'), ('action', '.action'), ('srv', '.srv'))
        for path in (interface_root / directory).glob('*' + suffix))
    try:
        cmake = (interface_root / 'CMakeLists.txt').read_text(encoding='utf-8')
        declared = sorted(set(re.findall(
            r'"((?:msg|action|srv)/[^"\r\n]+\.(?:msg|action|srv))"',
            cmake)))
        if declared != interface_definitions:
            failures.append('interface_cmake_declaration_mismatch')
    except OSError as error:
        failures.append('interface_cmake_unreadable:' + type(error).__name__)

    required_dependencies = {
        'rclpy', 'limo_cleanup_interfaces', 'sensor_msgs', 'std_msgs',
        'python3-numpy', 'python3-opencv',
    }
    try:
        root = ET.parse(str(
            workspace / 'src/limo_cleanup_perception/package.xml')).getroot()
        dependencies = {
            (node.text or '').strip()
            for tag in ('depend', 'exec_depend', 'build_depend')
            for node in root.findall(tag)
        }
        if not required_dependencies.issubset(dependencies):
            failures.append('perception_runtime_dependency_missing')
    except (OSError, ET.ParseError):
        failures.append('perception_package_xml_unreadable')
    result = {
        'python_requires': '>=3.8',
        'console_entries': console_entries,
        'fixture_names': sorted(fixture_names),
        'interface_definitions': interface_definitions,
        'failures': failures,
    }
    result.update(_ros2_migration_gate_metadata(not failures))
    return result


def _check_copy(source, installed, label, record, failures):
    source = Path(source)
    installed = Path(installed)
    try:
        if _is_linklike(installed):
            failures.append('installed_artifact_link_forbidden:' + label)
            return
        if not installed.is_file():
            failures.append('installed_artifact_missing:' + label)
            return
        source_identity = _identity(source)
        installed_identity = _identity(installed)
    except OSError:
        failures.append('installed_artifact_unreadable:' + label)
        return
    matches = (
        source_identity['size_bytes'] == installed_identity['size_bytes']
        and source_identity['sha256'] == installed_identity['sha256'])
    record.append({
        'name': label,
        'source_size_bytes': source_identity['size_bytes'],
        'source_sha256': source_identity['sha256'],
        'installed_size_bytes': installed_identity['size_bytes'],
        'installed_sha256': installed_identity['sha256'],
        'matches': matches,
    })
    if not matches:
        failures.append('installed_artifact_stale:' + label)


def _find_site_package(prefix, package_name):
    candidates = []
    try:
        for pattern in (
                'lib/python*/site-packages/' + package_name,
                'Lib/site-packages/' + package_name):
            for path in prefix.glob(pattern):
                try:
                    if path.is_dir() and not _is_linklike(path):
                        candidates.append(path)
                except OSError:
                    continue
        unique = sorted(set(path.resolve() for path in candidates))
    except OSError:
        return None
    return unique[0] if len(unique) == 1 else None


def _find_metadata_file(prefix, filename):
    candidates = []
    try:
        for pattern in (
                'lib/python*/site-packages/limo_cleanup_perception-*.dist-info/'
                + filename,
                'lib/python*/site-packages/limo_cleanup_perception-*.egg-info/'
                + filename,
                'Lib/site-packages/limo_cleanup_perception-*.dist-info/'
                + filename,
                'Lib/site-packages/limo_cleanup_perception-*.egg-info/'
                + filename):
            for path in prefix.glob(pattern):
                try:
                    if path.is_file() and not _is_linklike(path):
                        candidates.append(path)
                except OSError:
                    continue
        unique = sorted(set(path.resolve() for path in candidates))
    except OSError:
        return None
    return unique[0] if len(unique) == 1 else None


def validate_install(workspace, install_base, declarations):
    workspace = Path(workspace).resolve(strict=True)
    install_base = Path(install_base).resolve(strict=False)
    failures = []
    copies = []
    try:
        install_base_valid = install_base.is_dir()
    except OSError:
        install_base_valid = False
    if not install_base_valid:
        result = {
            'install_base': str(install_base),
            'isolated_non_symlink_install': False,
            'isolated_paths_valid': False,
            'copies': copies,
            'failures': ['install_base_missing'],
        }
        result.update(_ros2_migration_gate_metadata(False))
        return result
    prefixes = {
        name: install_base / name for name in (
            'limo_cleanup_interfaces', 'limo_cleanup_perception')
    }
    for name, prefix in prefixes.items():
        try:
            prefix_is_dir = prefix.is_dir()
            prefix_is_link = _is_linklike(prefix)
        except OSError:
            failures.append('install_access_blocked:' + name)
            continue
        if not prefix_is_dir:
            failures.append('isolated_install_prefix_missing:' + name)
        elif prefix_is_link:
            failures.append('isolated_install_prefix_link_forbidden:' + name)

    perception_prefix = prefixes['limo_cleanup_perception']
    interfaces_prefix = prefixes['limo_cleanup_interfaces']
    source_perception = workspace / 'src/limo_cleanup_perception'
    source_interfaces = workspace / 'src/limo_cleanup_interfaces'
    _check_copy(
        source_perception / 'package.xml',
        perception_prefix / 'share/limo_cleanup_perception/package.xml',
        'perception:package.xml', copies, failures)
    _check_copy(
        source_interfaces / 'package.xml',
        interfaces_prefix / 'share/limo_cleanup_interfaces/package.xml',
        'interfaces:package.xml', copies, failures)

    installed_python = _find_site_package(
        perception_prefix, 'limo_cleanup_perception')
    source_python = source_perception / 'limo_cleanup_perception'
    source_modules = {path.name: path for path in source_python.glob('*.py')}
    if installed_python is None:
        failures.append('installed_python_package_missing_or_ambiguous')
    else:
        try:
            installed_modules = {
                path.name for path in installed_python.glob('*.py')
            }
        except OSError:
            installed_modules = set()
            failures.append('install_access_blocked:python_modules')
        if installed_modules != set(source_modules):
            failures.append('installed_python_module_inventory_mismatch')
        for name, source in sorted(source_modules.items()):
            _check_copy(
                source, installed_python / name, 'python:' + name,
                copies, failures)

    fixture_root = perception_prefix / 'share/limo_cleanup_perception/fixtures'
    declared_fixtures = set(declarations.get('fixture_names', ()))
    try:
        installed_fixtures = (
            {path.name for path in fixture_root.glob('*.json')}
            if fixture_root.is_dir() else set())
    except OSError:
        installed_fixtures = set()
        failures.append('install_access_blocked:fixtures')
    if installed_fixtures != declared_fixtures:
        failures.append('installed_fixture_inventory_mismatch')
    for name in sorted(declared_fixtures):
        _check_copy(
            source_perception / 'fixtures' / name,
            fixture_root / name, 'fixture:' + name, copies, failures)

    for relative in declarations.get('interface_definitions', ()):
        _check_copy(
            source_interfaces / relative,
            interfaces_prefix / 'share/limo_cleanup_interfaces' / relative,
            'interface:' + relative, copies, failures)

    entry_points_path = _find_metadata_file(
        perception_prefix, 'entry_points.txt')
    if entry_points_path is None or _is_linklike(entry_points_path):
        failures.append('installed_entry_points_missing_or_linked')
    else:
        parser = configparser.ConfigParser()
        parser.optionxform = str
        try:
            parser.read(str(entry_points_path), encoding='utf-8')
            installed_entries = dict(parser.items('console_scripts'))
            installed_entries = {
                key.strip(): value.strip()
                for key, value in installed_entries.items()
            }
            if installed_entries != EXPECTED_CONSOLE_ENTRIES:
                failures.append('installed_console_entry_mismatch')
        except (OSError, configparser.Error, KeyError):
            failures.append('installed_entry_points_invalid')

    metadata_path = (_find_metadata_file(perception_prefix, 'METADATA')
                     or _find_metadata_file(perception_prefix, 'PKG-INFO'))
    if metadata_path is None or _is_linklike(metadata_path):
        failures.append('installed_python_metadata_missing_or_linked')
    else:
        try:
            metadata_text = metadata_path.read_text(encoding='utf-8')
            match = re.search(
                r'^Requires-Python:\s*(\S+)\s*$', metadata_text, re.MULTILINE)
            if match is None or match.group(1) != '>=3.8':
                failures.append('installed_python_requires_mismatch')
        except OSError:
            failures.append('installed_python_metadata_unreadable')

    launcher_root = perception_prefix / 'lib/limo_cleanup_perception'
    for name in sorted(EXPECTED_CONSOLE_ENTRIES):
        variants = (
            launcher_root / name,
            launcher_root / (name + '.exe'),
            launcher_root / (name + '-script.py'),
        )
        existing = []
        for path in variants:
            try:
                if path.is_file():
                    existing.append(path)
            except OSError:
                failures.append(
                    'install_access_blocked:console_launcher:' + name)
        if len(existing) != 1:
            failures.append('installed_console_launcher_missing:' + name)
        elif _is_linklike(existing[0]):
            failures.append('installed_console_launcher_link_forbidden:' + name)
    result = {
        'install_base': str(install_base),
        'isolated_non_symlink_install': not failures,
        'isolated_paths_valid': all(
            prefix.is_dir() and not _is_linklike(prefix)
            for prefix in prefixes.values()),
        'copies_checked': len(copies),
        'copies': copies,
        'failures': failures,
    }
    result.update(_ros2_migration_gate_metadata(not failures))
    return result


def validate_security(workspace):
    workspace = Path(workspace).resolve(strict=True)
    source_root = (
        workspace / 'src/limo_cleanup_perception/limo_cleanup_perception')
    failures = []
    actual_publishers = {}
    forbidden_calls = {
        'create_client', 'create_service', 'ActionClient', 'ActionServer',
        'send_goal_async', 'call_async',
    }

    def call_name(node):
        function = node.func
        if isinstance(function, ast.Name):
            return function.id
        if isinstance(function, ast.Attribute):
            return function.attr
        return ''

    for path in sorted(source_root.glob('*.py')):
        text = path.read_text(encoding='utf-8')
        try:
            tree = ast.parse(text)
        except SyntaxError:
            failures.append('security_ast_invalid:' + path.name)
            continue
        publisher_count = sum(
            1 for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and call_name(node) == 'create_publisher')
        if publisher_count:
            actual_publishers[path.name] = publisher_count
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = call_name(node)
            if name in forbidden_calls:
                failures.append(
                    'control_or_rpc_call_forbidden:{}:{}'.format(
                        path.name, name))
    if actual_publishers != PUBLISHER_ALLOWLIST:
        failures.append('publisher_allowlist_mismatch')
    for name in OFFLINE_TOOLS:
        text = (source_root / name).read_text(encoding='utf-8')
        try:
            tree = ast.parse(text)
        except SyntaxError:
            failures.append('offline_tool_ast_invalid:' + name)
            continue
        ros_imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                ros_imports.extend(
                    item.name for item in node.names
                    if item.name == 'rclpy' or item.name.startswith('rclpy.'))
            elif (isinstance(node, ast.ImportFrom)
                  and isinstance(node.module, str)
                  and (node.module == 'rclpy'
                       or node.module.startswith('rclpy.'))):
                ros_imports.append(node.module)
        for module in sorted(set(ros_imports)):
            failures.append(
                'offline_tool_ros_import_forbidden:{}:{}'.format(
                    name, module))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name_value = call_name(node)
            if name_value in {
                    'create_publisher', 'publish', 'create_subscription'}:
                failures.append(
                    'offline_tool_ros_api_forbidden:{}:{}'.format(
                        name, name_value))
    collector_path = source_root / 'perception_frame_collector.py'
    collector = collector_path.read_text(encoding='utf-8')
    try:
        collector_tree = ast.parse(collector, filename=str(collector_path))
    except SyntaxError:
        collector_tree = None
    collector_calls = [] if collector_tree is None else [
        call_name(node) for node in ast.walk(collector_tree)
        if isinstance(node, ast.Call)]
    collector_subscriptions = collector_calls.count('create_subscription')
    if (collector_tree is None or collector_subscriptions != 1
            or 'create_publisher' in collector_calls
            or 'publish' in collector_calls):
        failures.append('collector_not_subscribe_only')
    ros1_indexer_path = workspace / (
        'ros1_overlay_src/limo_cleanup_ros1_perception/src/'
        'limo_cleanup_ros1_perception/rosbag1_rgbd_indexer.py')
    ros1_offline_checked = 0
    if not ros1_indexer_path.is_file():
        failures.append('ros1_indexer_source_missing')
    else:
        ros1_offline_checked = 1
        ros1_text = ros1_indexer_path.read_text(encoding='utf-8')
        try:
            ast.parse(ros1_text, filename=str(ros1_indexer_path),
                      feature_version=8)
            compile(ros1_text, str(ros1_indexer_path), 'exec')
        except (SyntaxError, ValueError):
            failures.append('ros1_indexer_python38_invalid')
        for token in (
                'import rospy', 'rospy.init_node', 'rospy.Publisher',
                'rospy.Subscriber', 'rospy.Service', 'rosgraph',
                'create_publisher(', '.publish(', 'cmd_vel', 'move_base',
                'JointTrajectory', 'GripperCommand'):
            if token in ros1_text:
                failures.append(
                    'ros1_offline_tool_control_surface_forbidden:' + token)
    return {
        'publisher_allowlist': actual_publishers,
        'offline_tools_checked': len(OFFLINE_TOOLS),
        'ros1_offline_tools_checked': ros1_offline_checked,
        'collector_subscriptions': collector_subscriptions,
        'ros_control_publishers_authorized': False,
        'failures': failures,
    }


def _command_result(argv, cwd, environment):
    started = time.monotonic()
    command_cwd = str(Path(cwd).resolve())
    try:
        completed = subprocess.run(
            argv, cwd=command_cwd, env=environment,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, universal_newlines=True,
            timeout=COMMAND_TIMEOUT_SEC, check=False)
        return {
            'argv': list(argv),
            'cwd': command_cwd,
            'exit_code': completed.returncode,
            'timed_out': False,
            'duration_sec': time.monotonic() - started,
            'stdout': completed.stdout,
            'stderr': completed.stderr,
        }
    except subprocess.TimeoutExpired as error:
        return {
            'argv': list(argv),
            'cwd': command_cwd,
            'exit_code': None,
            'timed_out': True,
            'duration_sec': time.monotonic() - started,
            'stdout': error.stdout or '',
            'stderr': error.stderr or '',
        }
    except OSError as error:
        return {
            'argv': list(argv),
            'cwd': command_cwd,
            'exit_code': None,
            'timed_out': False,
            'duration_sec': time.monotonic() - started,
            'stdout': '',
            'stderr': '{}: {}'.format(type(error).__name__, error),
        }


def _command_output_text(value):
    if value is None:
        return ''
    if isinstance(value, bytes):
        return value.decode('utf-8', errors='replace')
    if isinstance(value, str):
        return value
    return str(value)


def _command_output_record(value):
    text = _command_output_text(value)
    encoded = text.encode('utf-8', errors='replace')
    return {
        'length_chars': len(text),
        'length_bytes': len(encoded),
        'sha256': _sha256_bytes(encoded),
        'head': text[:COMMAND_OUTPUT_EDGE_CHARS],
        'tail': text[-COMMAND_OUTPUT_EDGE_CHARS:],
    }


def _record_command(result):
    stdout = _command_output_record(result.get('stdout', ''))
    stderr = _command_output_record(result.get('stderr', ''))
    return {
        'argv': result.get('argv', []),
        'cwd': result.get('cwd'),
        'exit_code': result.get('exit_code'),
        'timed_out': bool(result.get('timed_out')),
        'duration_sec': result.get('duration_sec'),
        'stdout_length_chars': stdout['length_chars'],
        'stdout_length_bytes': stdout['length_bytes'],
        'stdout_sha256': stdout['sha256'],
        'stdout_head': stdout['head'],
        'stdout_tail': stdout['tail'],
        'stderr_length_chars': stderr['length_chars'],
        'stderr_length_bytes': stderr['length_bytes'],
        'stderr_sha256': stderr['sha256'],
        'stderr_head': stderr['head'],
        'stderr_tail': stderr['tail'],
    }


def run_test_commands(workspace, command_runner=_command_result):
    workspace = Path(workspace).resolve(strict=True)
    environment = dict(os.environ)
    environment['PYTHONDONTWRITEBYTECODE'] = '1'
    environment['PYTHONPATH'] = os.pathsep.join((
        str(workspace / 'src/limo_cleanup_perception'), str(workspace)))
    unittest_argv = [sys.executable, '-B', '-m', 'unittest', '-v']
    unittest_argv.extend(module for module, _ in UNITTEST_TARGETS)
    unittest_result = command_runner(unittest_argv, workspace, environment)

    present_post_freeze = {
        name: workspace / 'src/limo_cleanup_perception/test' / name
        for name in sorted(POST_FREEZE_TEST_FILES)
        if (workspace / 'src/limo_cleanup_perception/test' / name).is_file()
    }
    pytest_plan, pytest_plan_failures = _build_pytest_execution_plan(
        workspace, present_post_freeze)
    pytest_file_records, pytest_inventory_failures = (
        _execute_pytest_file_plan(
            workspace, pytest_plan, command_runner,
            inherited_environment=os.environ))
    pytest_allocations, pytest_allocation_failures = (
        _pytest_allocation_reports(pytest_file_records))
    post_unittest_result = None
    post_unittest_modules = [
        module for module in POST_FREEZE_UNITTEST_MODULES
        if (workspace / 'src/limo_cleanup_perception/test'
            / (module.rsplit('.', 1)[-1] + '.py')).is_file()
    ]
    if post_unittest_modules:
        post_unittest_argv = [
            sys.executable, '-B', '-m', 'unittest', '-v',
        ]
        post_unittest_argv.extend(post_unittest_modules)
        post_unittest_result = command_runner(
            post_unittest_argv, workspace, environment)

    supplemental_modules = [
        module for module, _expected in SUPPLEMENTAL_UNITTEST_TARGETS
        if (workspace / 'src/limo_cleanup_perception/test'
            / (module.rsplit('.', 1)[-1] + '.py')).is_file()
    ]
    supplemental_result = None
    if supplemental_modules:
        supplemental_argv = [
            sys.executable, '-B', '-m', 'unittest', '-v',
        ]
        supplemental_argv.extend(SUPPLEMENTAL_UNITTEST_SELECTED_IDS)
        supplemental_result = command_runner(
            supplemental_argv, workspace, environment)

    post_fix_results = {}
    for suite_id, module, expected in POST_FIX_UNITTEST_TARGETS:
        path = (workspace / 'src/limo_cleanup_perception/test'
                / (module.rsplit('.', 1)[-1] + '.py'))
        if not path.is_file():
            continue
        argv = [sys.executable, '-B', '-m', 'unittest', '-v', module]
        post_fix_results[suite_id] = {
            'runner': 'unittest',
            'expected': expected,
            'result': command_runner(argv, workspace, environment),
        }

    current_unittest_plan, current_unittest_plan_failures = (
        _build_current_unittest_execution_plan(workspace))
    current_unittest_records, current_unittest_record_failures = (
        _execute_current_unittest_file_plan(
            workspace, current_unittest_plan, command_runner,
            inherited_environment=os.environ))
    current_unittest_allocations, current_unittest_allocation_failures = (
        _unittest_allocation_reports(current_unittest_records))
    wsl_unittest_records, wsl_unittest_failures = (
        _execute_wsl_current_unittests(
            workspace, command_runner, inherited_environment=os.environ))

    ros1_unittest_argv = [
        sys.executable, '-B', str(workspace / ROS1_INDEXER_TEST), '-v',
    ]
    ros1_unittest_result = command_runner(
        ros1_unittest_argv, workspace, environment)

    failures = []
    failures.extend(current_unittest_plan_failures)
    failures.extend(current_unittest_record_failures)
    failures.extend(current_unittest_allocation_failures)
    failures.extend(wsl_unittest_failures)
    unittest_text = (
        unittest_result.get('stdout', '') + '\n'
        + unittest_result.get('stderr', ''))
    unittest_match = re.search(r'Ran\s+(\d+)\s+tests?', unittest_text)
    unittest_count = int(unittest_match.group(1)) if unittest_match else None
    if (unittest_result.get('exit_code') != 0
            or unittest_result.get('timed_out')
            or unittest_count != EXPECTED_UNITTEST_COUNT
            or re.search(r'^OK\s*$', unittest_text, re.MULTILINE) is None):
        failures.append('frozen_unittest_failed_or_count_mismatch')

    failures.extend(pytest_plan_failures)
    failures.extend(pytest_inventory_failures)
    failures.extend(pytest_allocation_failures)
    for record in pytest_file_records:
        for failure in record.get('failures', []):
            failures.append(
                'pytest_style_file_failed:{}:{}'.format(
                    record.get('path') or 'unknown', failure))

    frozen_style = _pytest_scope_totals(
        pytest_allocations, 'frozen_full')
    if (not frozen_style['validated_pass']
            or frozen_style['expected'] != EXPECTED_BASE_PYTEST_STYLE_COUNT
            or frozen_style['collected'] != EXPECTED_BASE_PYTEST_STYLE_COUNT
            or frozen_style['passed'] != EXPECTED_BASE_PYTEST_STYLE_COUNT
            or frozen_style['failed'] != 0
            or frozen_style['skipped'] != 0):
        failures.append('frozen_pytest_style_failed_or_count_mismatch')

    frozen_selected = _pytest_scope_totals(
        pytest_allocations, 'frozen_selected')
    if (not frozen_selected['validated_pass']
            or frozen_selected['expected']
            != EXPECTED_SELECTED_PYTEST_STYLE_COUNT
            or frozen_selected['collected']
            != EXPECTED_SELECTED_PYTEST_STYLE_COUNT
            or frozen_selected['passed']
            != EXPECTED_SELECTED_PYTEST_STYLE_COUNT
            or frozen_selected['failed'] != 0
            or frozen_selected['skipped'] != 0):
        failures.append(
            'frozen_selected_pytest_style_failed_or_count_mismatch')

    post_style = _pytest_scope_totals(
        pytest_allocations, 'post_freeze')
    expected_post_style = sum(
        POST_FREEZE_TEST_COUNTS[name]
        for name in POST_FREEZE_PYTEST_STYLE_FILES
        if name in present_post_freeze)
    if (not post_style['validated_pass']
            or post_style['expected'] != expected_post_style
            or post_style['collected'] != expected_post_style
            or post_style['passed'] != expected_post_style
            or post_style['failed'] != 0
            or post_style['skipped'] != 0):
        failures.append('post_freeze_pytest_style_failed')

    post_unittest_count = 0
    if post_unittest_result is not None:
        post_unittest_text = (
            post_unittest_result.get('stdout', '') + '\n'
            + post_unittest_result.get('stderr', ''))
        post_unittest_match = re.search(
            r'Ran\s+(\d+)\s+tests?', post_unittest_text)
        post_unittest_count = (
            int(post_unittest_match.group(1))
            if post_unittest_match else 0)
        expected_post_unittest = sum(
            POST_FREEZE_TEST_COUNTS[module.rsplit('.', 1)[-1] + '.py']
            for module in post_unittest_modules)
        if (post_unittest_result.get('exit_code') != 0
                or post_unittest_result.get('timed_out')
                or post_unittest_count != expected_post_unittest
                or re.search(
                    r'^OK\s*$', post_unittest_text,
                    re.MULTILINE) is None):
            failures.append('post_freeze_unittest_failed')

    supplemental_count = 0
    expected_supplemental = sum(
        expected for module, expected in SUPPLEMENTAL_UNITTEST_TARGETS
        if module in supplemental_modules)
    if supplemental_result is None:
        failures.append('supplemental_unittest_missing')
    else:
        supplemental_text = (
            supplemental_result.get('stdout', '') + '\n'
            + supplemental_result.get('stderr', ''))
        supplemental_match = re.search(
            r'Ran\s+(\d+)\s+tests?', supplemental_text)
        supplemental_count = (
            int(supplemental_match.group(1)) if supplemental_match else 0)
        if (supplemental_result.get('exit_code') != 0
                or supplemental_result.get('timed_out')
                or supplemental_count != expected_supplemental
                or expected_supplemental != sum(
                    expected for _module, expected
                    in SUPPLEMENTAL_UNITTEST_TARGETS)
                or re.search(
                    r'^OK\s*$', supplemental_text,
                    re.MULTILINE) is None):
            failures.append('supplemental_unittest_failed_or_count_mismatch')

    post_fix_collected = 0
    post_fix_passed = 0
    post_fix_suite_reports = {}
    expected_post_fix_suites = {
        suite_id: ('pytest_style', expected)
        for suite_id, _filename, expected in POST_FIX_PYTEST_STYLE_FILES
    }
    expected_post_fix_suites.update({
        suite_id: ('selected_pytest_style', len(names))
        for suite_id, _filename, names
        in POST_FIX_SELECTED_PYTEST_STYLE_TARGETS
    })
    expected_post_fix_suites.update({
        suite_id: ('unittest', expected)
        for suite_id, _module, expected in POST_FIX_UNITTEST_TARGETS
    })
    for suite_id, (runner, expected) in expected_post_fix_suites.items():
        allocation = pytest_allocations.get(('post_fix', suite_id))
        invocation = post_fix_results.get(suite_id)
        collected = 0
        passed = 0
        valid = False
        command = None
        failed = max(1, expected)
        skipped = 0
        if runner in ('pytest_style', 'selected_pytest_style'):
            if allocation is not None:
                collected = allocation['collected']
                passed = allocation['passed']
                failed = allocation['failed']
                skipped = allocation['skipped']
                valid = (
                    allocation['validated_pass']
                    and allocation['expected'] == expected
                    and collected == expected and passed == expected
                    and failed == 0 and skipped == 0)
                command = allocation['command']
            if not valid:
                failures.append(
                    'post_fix_suite_failed_or_count_mismatch:' + suite_id)
        elif invocation is None:
            failures.append('post_fix_suite_missing:' + suite_id)
        else:
            result = invocation['result']
            command = _record_command(result)
            output = result.get('stdout', '') + '\n' + result.get(
                'stderr', '')
            match = re.search(r'Ran\s+(\d+)\s+tests?', output)
            collected = int(match.group(1)) if match else 0
            valid = (
                result.get('exit_code') == 0
                and not result.get('timed_out')
                and collected == expected
                and re.search(
                    r'^OK\s*$', output, re.MULTILINE) is not None)
            passed = collected if valid else 0
            failed = 0 if valid else max(1, expected - collected)
            if not valid:
                failures.append(
                    'post_fix_suite_failed_or_count_mismatch:' + suite_id)
        post_fix_collected += collected
        post_fix_passed += passed if valid else 0
        post_fix_suite_reports[suite_id] = {
            'runner': runner,
            'expected': expected,
            'collected': collected,
            'passed': passed if valid else 0,
            'failed': 0 if valid else max(1, expected - collected),
            'skipped': skipped,
            'validated_pass': valid,
            'command': command,
        }
    if sum(
            expected for _runner, expected
            in expected_post_fix_suites.values()) != EXPECTED_POST_FIX_TEST_COUNT:
        failures.append('post_fix_internal_total_mismatch')
    if post_fix_collected != EXPECTED_POST_FIX_TEST_COUNT:
        failures.append('post_fix_executed_total_mismatch')

    current_generation_collected = 0
    current_generation_passed = 0
    current_generation_suite_reports = {}
    exact_windows_allocation = current_unittest_allocations.get(
        ('current_generation', CURRENT_GENERATION_EXACT_UNITTEST_TARGET[0]))
    exact_windows_record = next((
        record for record in current_unittest_records
        if record.get('path') == EXACT_CLI_TEST_RELATIVE), None)
    exact_posix_record = wsl_unittest_records.get(
        EXACT_CLI_POSIX_COMPANION_SUITE_ID)
    exact_expected_ids = (
        [] if exact_windows_allocation is None
        else exact_windows_allocation.get('expected_ids', []))
    exact_composite = _exact_platform_composite(
        exact_windows_record, exact_posix_record, exact_expected_ids)
    if exact_composite['failures']:
        failures.extend(exact_composite['failures'])
    host_suite_id = 'ros1_noetic_field_readiness_host'
    host_windows_allocation = current_unittest_allocations.get(
        ('current_generation', host_suite_id))
    host_windows_record = next((
        record for record in current_unittest_records
        if record.get('path') == HOST_READINESS_TEST_RELATIVE), None)
    host_companion_records = {
        HOST_READINESS_POSIX_CASE_IDS[0]: wsl_unittest_records.get(
            HOST_READINESS_POSIX_SUITE_BY_CASE_ID[
                HOST_READINESS_POSIX_CASE_IDS[0]]),
        HOST_READINESS_POSIX_CASE_IDS[1]: wsl_unittest_records.get(
            HOST_READINESS_POSIX_SUITE_BY_CASE_ID[
                HOST_READINESS_POSIX_CASE_IDS[1]]),
    }
    host_expected_ids = (
        [] if host_windows_allocation is None
        else host_windows_allocation.get('expected_ids', []))
    host_composite = _host_readiness_platform_composite(
        host_windows_record, host_companion_records, host_expected_ids)
    if host_composite['failures']:
        failures.extend(host_composite['failures'])
    expected_current_generation_suites = {
        suite_id: ('pytest_style', expected)
        for suite_id, _filename, expected
        in CURRENT_GENERATION_PYTEST_STYLE_FILES
    }
    expected_current_generation_suites.update({
        suite_id: ('selected_pytest_style', len(names))
        for suite_id, _filename, names
        in CURRENT_GENERATION_SELECTED_PYTEST_STYLE_TARGETS
    })
    expected_current_generation_suites.update({
        suite_id: ('isolated_unittest_file', expected)
        for suite_id, _module, expected
        in CURRENT_GENERATION_UNITTEST_TARGETS
    })
    expected_current_generation_suites.update({
        suite_id: ('isolated_unittest_file', len(names))
        for suite_id, _module, names
        in CURRENT_GENERATION_SELECTED_UNITTEST_TARGETS
    })
    expected_current_generation_suites.update({
        suite_id: ('isolated_unittest_file', expected)
        for suite_id, _relative, expected
        in CURRENT_GENERATION_ROS1_UNITTEST_TARGETS
    })
    expected_current_generation_suites[
        CURRENT_GENERATION_EXACT_UNITTEST_TARGET[0]] = (
            'platform_composite_unittest', EXACT_CLI_TEST_COUNT)
    expected_current_generation_suites[host_suite_id] = (
        'platform_composite_unittest', 22)
    expected_current_generation_suites.update({
        suite_id: ('wsl_isolated_unittest_file', ROS1_ISOLATED_PROBE_TEST_COUNT)
        for suite_id in (
            ROS1_ISOLATED_PROBE_PYTHON3_SUITE_ID,
            ROS1_ISOLATED_PROBE_PYTHON3_14_SUITE_ID)
    })
    for suite_id, (runner, expected) in (
            expected_current_generation_suites.items()):
        allocation = pytest_allocations.get(
            ('current_generation', suite_id))
        report_value = None
        if runner in ('pytest_style', 'selected_pytest_style'):
            if allocation is not None:
                valid = (
                    allocation['validated_pass']
                    and allocation['expected'] == expected
                    and allocation['collected'] == expected
                    and allocation['passed'] == expected
                    and allocation['failed'] == 0
                    and allocation['skipped'] == 0)
                report_value = dict(allocation)
                report_value['validated_pass'] = valid
        elif runner == 'isolated_unittest_file':
            report_value = current_unittest_allocations.get(
                ('current_generation', suite_id))
            valid = (
                isinstance(report_value, dict)
                and report_value.get('validated_pass') is True
                and report_value.get('expected') == expected
                and report_value.get('collected') == expected
                and report_value.get('passed') == expected
                and report_value.get('failed') == 0
                and report_value.get('skipped') == 0)
        elif runner == 'platform_composite_unittest':
            report_value = (
                exact_composite
                if suite_id == CURRENT_GENERATION_EXACT_UNITTEST_TARGET[0]
                else host_composite)
            valid = (
                report_value.get('validated_pass') is True
                and report_value.get('expected') == expected
                and report_value.get('collected') == expected
                and report_value.get('passed') == expected
                and report_value.get('failed') == 0
                and report_value.get('skipped') == 0)
        elif runner == 'wsl_isolated_unittest_file':
            record = wsl_unittest_records.get(suite_id)
            report_value = {
                'runner': runner,
                'expected': expected,
                'expected_ids': (
                    [] if not isinstance(record, dict)
                    else record.get('expected_ids', [])),
                'collected': (
                    0 if not isinstance(record, dict)
                    else record.get('collected', 0)),
                'passed': (
                    0 if not isinstance(record, dict)
                    else record.get('passed', 0)),
                'failed': (
                    max(1, expected) if not isinstance(record, dict)
                    else record.get('failed', max(1, expected))),
                'skipped': (
                    0 if not isinstance(record, dict)
                    else record.get('skipped', 0)),
                'validated_pass': (
                    isinstance(record, dict)
                    and record.get('validated_pass') is True),
                'file_path': (
                    None if not isinstance(record, dict)
                    else record.get('path')),
                'file_identity': (
                    None if not isinstance(record, dict)
                    else record.get('post_identity')),
                'executable': (
                    None if not isinstance(record, dict)
                    else record.get('executable')),
                'command': (
                    None if not isinstance(record, dict)
                    else record.get('command')),
            }
            valid = (
                report_value['validated_pass']
                and report_value['collected'] == expected
                and report_value['passed'] == expected
                and report_value['failed'] == 0
                and report_value['skipped'] == 0)
        else:
            valid = False
        if report_value is None:
            report_value = {
                'runner': runner, 'expected': expected, 'collected': 0,
                'passed': 0, 'failed': max(1, expected), 'skipped': 0,
                'validated_pass': False, 'command': None,
            }
        if not valid:
            failures.append(
                'current_generation_suite_failed_or_count_mismatch:'
                + suite_id)
        current_generation_collected += report_value.get('collected', 0)
        current_generation_passed += (
            report_value.get('passed', 0) if valid else 0)
        current_generation_suite_reports[suite_id] = report_value
    if sum(
            expected for _runner, expected
            in expected_current_generation_suites.values()
            ) != EXPECTED_CURRENT_GENERATION_TEST_COUNT:
        failures.append('current_generation_internal_total_mismatch')
    if current_generation_collected != EXPECTED_CURRENT_GENERATION_TEST_COUNT:
        failures.append('current_generation_executed_total_mismatch')
    current_generation_physical_collected = (
        sum(value['collected'] for value in current_generation_suite_reports.values())
        - exact_composite.get('collected', 0)
        - host_composite.get('collected', 0)
        + (0 if not isinstance(exact_windows_record, dict)
           else exact_windows_record.get('collected', 0))
        + (0 if not isinstance(host_windows_record, dict)
           else host_windows_record.get('collected', 0))
        + (0 if not isinstance(exact_posix_record, dict)
           else exact_posix_record.get('collected', 0))
        + sum(
            record.get('collected', 0)
            for record in host_companion_records.values()
            if isinstance(record, dict)))
    current_generation_physical_passed = (
        sum(value['passed'] for value in current_generation_suite_reports.values())
        - exact_composite.get('passed', 0)
        - host_composite.get('passed', 0)
        + (0 if not isinstance(exact_windows_record, dict)
           else exact_windows_record.get('passed', 0))
        + (0 if not isinstance(exact_posix_record, dict)
           else exact_posix_record.get('passed', 0))
        + (0 if not isinstance(host_windows_record, dict)
           else host_windows_record.get('passed', 0))
        + sum(
            record.get('passed', 0)
            for record in host_companion_records.values()
            if isinstance(record, dict)))
    current_generation_physical_failed = (
        sum(value['failed'] for value in current_generation_suite_reports.values())
        - exact_composite.get('failed', 0)
        - host_composite.get('failed', 0)
        + (0 if not isinstance(exact_windows_record, dict)
           else exact_windows_record.get('failed', 0))
        + (0 if not isinstance(exact_posix_record, dict)
           else exact_posix_record.get('failed', 0))
        + (0 if not isinstance(host_windows_record, dict)
           else host_windows_record.get('failed', 0))
        + sum(
            record.get('failed', 0)
            for record in host_companion_records.values()
            if isinstance(record, dict)))
    current_generation_physical_skipped = (
        (0 if not isinstance(exact_windows_record, dict)
         else exact_windows_record.get('skipped', 0))
        + (0 if not isinstance(exact_posix_record, dict)
           else exact_posix_record.get('skipped', 0))
        + (0 if not isinstance(host_windows_record, dict)
           else host_windows_record.get('skipped', 0))
        + sum(
            record.get('skipped', 0)
            for record in host_companion_records.values()
            if isinstance(record, dict)))
    if (current_generation_physical_collected
            != EXPECTED_CURRENT_GENERATION_PHYSICAL_TEST_COUNT
            or current_generation_physical_failed != 0
            or current_generation_physical_passed
            + current_generation_physical_skipped
            != EXPECTED_CURRENT_GENERATION_PHYSICAL_TEST_COUNT):
        failures.append('current_generation_physical_total_mismatch')

    post_freeze_collected = post_style['collected'] + post_unittest_count
    expected_post_freeze = sum(
        POST_FREEZE_TEST_COUNTS[name] for name in present_post_freeze)
    if post_freeze_collected != expected_post_freeze:
        failures.append('post_freeze_total_mismatch')

    ros1_unittest_text = (
        ros1_unittest_result.get('stdout', '') + '\n'
        + ros1_unittest_result.get('stderr', ''))
    ros1_unittest_match = re.search(
        r'Ran\s+(\d+)\s+tests?', ros1_unittest_text)
    ros1_unittest_count = (
        int(ros1_unittest_match.group(1)) if ros1_unittest_match else 0)
    if (ros1_unittest_result.get('exit_code') != 0
            or ros1_unittest_result.get('timed_out')
            or ros1_unittest_count != EXPECTED_ROS1_TEST_COUNT
            or re.search(
                r'^OK\s*$', ros1_unittest_text, re.MULTILINE) is None):
        failures.append('ros1_unittest_failed_or_count_mismatch')

    total = (
        (unittest_count or 0) + frozen_style['passed']
        + frozen_selected['passed'])
    if total != EXPECTED_TEST_COUNT:
        failures.append('frozen_executed_test_total_mismatch')
    grand_total = total + post_freeze_collected + ros1_unittest_count
    if grand_total != EXPECTED_GRAND_TEST_COUNT:
        failures.append('ros_independent_grand_total_mismatch')
    mandatory_logical_collected = (
        grand_total + supplemental_count + post_fix_collected
        + current_generation_collected)
    mandatory_logical_expected = (
        EXPECTED_GRAND_TEST_COUNT
        + sum(expected for _module, expected
              in SUPPLEMENTAL_UNITTEST_TARGETS)
        + EXPECTED_POST_FIX_TEST_COUNT
        + EXPECTED_CURRENT_GENERATION_TEST_COUNT)
    if mandatory_logical_collected != mandatory_logical_expected:
        failures.append('mandatory_logical_total_mismatch')
    return {
        'unittest': _record_command(unittest_result),
        'pytest_style_file_execution_policy': {
            'one_isolated_process_per_unique_file': True,
            'python_isolated_flag': True,
            'python_no_bytecode_flag': True,
            'fixed_cwd': str(workspace),
            'environment_allowlist': sorted(
                PYTEST_STYLE_ENVIRONMENT_ALLOWLIST),
            'import_roots': list(PYTEST_STYLE_IMPORT_ROOTS),
            'marker_prefix': PYTEST_FILE_RESULT_PREFIX,
            'filename_or_total_only_selection_forbidden': True,
        },
        'pytest_style_file_records': pytest_file_records,
        'pytest_style_file_inventory': {
            'ordered_paths': [
                entry['relative_path'] for entry in pytest_plan],
            'unique_file_count': len(pytest_plan),
            'failures': (
                pytest_plan_failures + pytest_inventory_failures
                + pytest_allocation_failures),
        },
        'unittest_file_execution_policy': {
            'one_isolated_process_per_file_and_interpreter': True,
            'python_isolated_flag': True,
            'python_no_bytecode_flag': True,
            'fixed_cwd': str(workspace),
            'environment_allowlist': sorted(
                PYTEST_STYLE_ENVIRONMENT_ALLOWLIST),
            'import_roots': list(UNITTEST_STYLE_IMPORT_ROOTS),
            'marker_prefix': UNITTEST_FILE_RESULT_PREFIX,
            'windows_exact_skip_allowlist': [EXACT_CLI_POSIX_CASE_ID],
            'windows_host_readiness_skip_allowlist': list(
                HOST_READINESS_POSIX_CASE_IDS),
            'posix_companion_required': True,
            'skip_is_never_counted_as_pass': True,
            'wsl_distribution': WSL_DISTRIBUTION,
            'wsl_python_entries': list(WSL_PYTHON_ENTRIES),
            'wsl_python_target_identity': dict(WSL_PYTHON_TARGET_IDENTITY),
            'filename_mtime_or_total_only_selection_forbidden': True,
        },
        'unittest_file_records': current_unittest_records,
        'unittest_file_inventory': {
            'ordered_paths': [
                entry['relative_path'] for entry in current_unittest_plan],
            'unique_file_count': len(current_unittest_plan),
            'failures': (
                current_unittest_plan_failures
                + current_unittest_record_failures
                + current_unittest_allocation_failures),
        },
        'wsl_unittest_file_records': wsl_unittest_records,
        'wsl_unittest_file_failures': wsl_unittest_failures,
        'pytest_style': frozen_style,
        'selected_pytest_style': frozen_selected,
        'post_freeze_pytest_style': post_style,
        'post_freeze_unittest': (
            None if post_unittest_result is None
            else _record_command(post_unittest_result)),
        'supplemental_unittest': (
            None if supplemental_result is None
            else _record_command(supplemental_result)),
        'post_fix_suites': post_fix_suite_reports,
        'ros1_unittest': _record_command(ros1_unittest_result),
        'unittest_passed': unittest_count if not failures or (
            'frozen_unittest_failed_or_count_mismatch' not in failures) else 0,
        'pytest_style_passed': (
            frozen_style['passed'] + frozen_selected['passed']),
        'post_freeze_collected': post_freeze_collected,
        'post_freeze_passed': (
            post_style['passed'] + post_unittest_count
            if not any(item.startswith('post_freeze_') for item in failures)
            else 0),
        'post_freeze_failed': (
            0 if not any(item.startswith('post_freeze_') for item in failures)
            else max(1, expected_post_freeze - post_freeze_collected)),
        'supplemental_collected': supplemental_count,
        'supplemental_passed': (
            supplemental_count
            if not any(item.startswith('supplemental_') for item in failures)
            else 0),
        'supplemental_failed': (
            0 if not any(item.startswith('supplemental_') for item in failures)
            else max(1, expected_supplemental - supplemental_count)),
        'supplemental_expected_total': sum(
            expected for _module, expected in SUPPLEMENTAL_UNITTEST_TARGETS),
        'supplemental_included_in_grand_total': False,
        'post_fix_collected': post_fix_collected,
        'post_fix_passed': post_fix_passed,
        'post_fix_failed': EXPECTED_POST_FIX_TEST_COUNT - post_fix_passed,
        'post_fix_expected_total': EXPECTED_POST_FIX_TEST_COUNT,
        'post_fix_included_in_grand_total': False,
        'current_generation_suites': current_generation_suite_reports,
        'current_generation_collected': current_generation_collected,
        'current_generation_passed': current_generation_passed,
        'current_generation_failed': (
            EXPECTED_CURRENT_GENERATION_TEST_COUNT
            - current_generation_passed),
        'current_generation_expected_total': (
            EXPECTED_CURRENT_GENERATION_TEST_COUNT),
        'current_generation_physical_collected': (
            current_generation_physical_collected),
        'current_generation_physical_passed': (
            current_generation_physical_passed),
        'current_generation_physical_failed': (
            current_generation_physical_failed),
        'current_generation_physical_skipped': (
            current_generation_physical_skipped),
        'current_generation_physical_expected_total': (
            EXPECTED_CURRENT_GENERATION_PHYSICAL_TEST_COUNT),
        'current_generation_included_in_grand_total': False,
        'current_generation_included_in_post_fix_total': False,
        'ros1_unittest_passed': (
            ros1_unittest_count
            if 'ros1_unittest_failed_or_count_mismatch' not in failures
            else 0),
        'ros1_expected_total': EXPECTED_ROS1_TEST_COUNT,
        'total_passed': total if not failures else min(total, EXPECTED_TEST_COUNT),
        'expected_total': EXPECTED_TEST_COUNT,
        'grand_total_collected': grand_total,
        'grand_total_passed': grand_total if not failures else 0,
        'expected_grand_total': EXPECTED_GRAND_TEST_COUNT,
        'mandatory_logical_collected': (
            mandatory_logical_collected),
        'mandatory_logical_passed': (
            grand_total + supplemental_count + post_fix_passed
            + current_generation_passed if not failures else 0),
        'mandatory_logical_expected_total': (
            mandatory_logical_expected),
        'mandatory_physical_expected_total': (
            EXPECTED_GRAND_TEST_COUNT
            + sum(expected for _module, expected
                  in SUPPLEMENTAL_UNITTEST_TARGETS)
            + EXPECTED_POST_FIX_TEST_COUNT
            + EXPECTED_CURRENT_GENERATION_PHYSICAL_TEST_COUNT),
        'failures': failures,
    }


def _load_offline_test_runner(workspace):
    path = Path(workspace) / 'audit_tools/run_pytest_style_tests.py'
    spec = importlib.util.spec_from_file_location(
        'perception_v2_selected_test_support', str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError('cannot load offline test support')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _selected_pytest_style_main(argv):
    if len(argv) < 2:
        print('selected test runner requires a file and test IDs',
              file=sys.stderr)
        return 2
    path = Path(argv[0]).resolve(strict=True)
    selected = tuple(argv[1:])
    workspace = Path(__file__).resolve().parents[1]
    support = _load_offline_test_runner(workspace)
    support.install_pytest_stub()
    support.install_ros_import_stubs()
    module = support.load_module(path, 1)
    support.OFFLINE_FIXTURES.update({
        name: function
        for name, function in vars(module).items()
        if callable(function)
        and getattr(function, '__offline_fixture__', False)
    })
    passed = 0
    failed = 0
    for name in selected:
        function = vars(module).get(name)
        if not callable(function) or not name.startswith('test_'):
            failed += 1
            print('FAIL {}::{} missing selected test'.format(path.name, name))
            continue
        cleanups = []
        try:
            arguments = {}
            cleanups = support.add_supported_fixtures(function, arguments)
            support.invoke(function, arguments)
        except Exception:
            failed += 1
            print('FAIL {}::{}'.format(path.name, name))
            traceback.print_exc()
        else:
            passed += 1
            print('PASS {}::{}'.format(path.name, name))
        finally:
            for cleanup in reversed(cleanups):
                cleanup()
    print(
        'SELECTED_PYTEST_STYLE collected={} passed={} failed={}'.format(
            len(selected), passed, failed))
    return 1 if failed else 0


def _git_environment_audit(environment):
    actual_by_name = {}
    for key, value in environment.items():
        original = str(key)
        normalized = str(key).upper()
        if not normalized.startswith('GIT_'):
            continue
        actual_by_name.setdefault(normalized, []).append(
            (original, _command_output_text(value)))
    entries = []
    for normalized in sorted(GIT_ENVIRONMENT_AUDIT_KEYS):
        if normalized not in actual_by_name:
            entries.append({
                'name': normalized,
                'normalized_name': normalized,
                'present': False,
                'value_length_chars': 0,
                'value_length_bytes': 0,
                'value_sha256': None,
            })
    for normalized in sorted(actual_by_name):
        for original, value in sorted(actual_by_name[normalized]):
            encoded = value.encode('utf-8', errors='replace')
            entries.append({
                'name': original,
                'normalized_name': normalized,
                'present': True,
                'value_length_chars': len(value),
                'value_length_bytes': len(encoded),
                'value_sha256': _sha256_bytes(encoded),
            })
    return {
        'audited_exact_keys': list(GIT_ENVIRONMENT_AUDIT_KEYS),
        'audited_prefixes': list(GIT_ENVIRONMENT_AUDIT_PREFIXES),
        'entries': entries,
        'case_collisions': [
            {
                'normalized_name': name,
                'key_names': sorted(original for original, _ in values),
            }
            for name, values in sorted(actual_by_name.items())
            if len(values) > 1
        ],
    }


def _repository_git_metadata(workspace):
    def record(relative):
        path = workspace / relative
        if not path.is_file():
            return {'path': relative, 'present': False}
        result = _identity(path, relative_to=workspace)
        result['present'] = True
        return result

    return {
        'git_config': record('.git/config'),
        'gitattributes': record('.gitattributes'),
        'uses_repository_git_config': True,
        'uses_repository_gitattributes': True,
    }


def _git_command_prefix(git_executable, workspace):
    return [
        str(git_executable),
        '-c', 'safe.directory=',
        '-c', 'safe.directory={}'.format(workspace),
        '-C', str(workspace),
    ]


def _parse_git_toplevel(value):
    text = _command_output_text(value).strip()
    lines = text.splitlines()
    if len(lines) != 1 or not lines[0].strip():
        return None, 'git_repository_toplevel_output_invalid'
    try:
        toplevel = Path(lines[0].strip()).resolve(strict=True)
    except (OSError, RuntimeError):
        return None, 'git_repository_toplevel_unresolvable'
    return toplevel, None


def _paths_identical(left, right):
    return os.path.normcase(str(left)) == os.path.normcase(str(right))


def _git_failure_classification(result):
    if result.get('timed_out'):
        return 'timeout'
    exit_code = result.get('exit_code')
    if exit_code == 0:
        return None
    output = '{}\n{}'.format(
        _command_output_text(result.get('stdout', '')),
        _command_output_text(result.get('stderr', ''))).lower()
    if 'dubious ownership' in output:
        return 'dubious_ownership'
    if exit_code == 129 and ('--no-index' in output or 'usage: git diff' in output):
        return 'no_index_usage_exit_129'
    return 'nonzero_exit'


def run_diff_check(workspace, command_runner=_command_result):
    workspace = Path(workspace).resolve(strict=True)
    inherited_environment = dict(os.environ)
    git_environment = _git_environment_audit(inherited_environment)
    present_git_entries = [
        item for item in git_environment['entries'] if item['present']]
    redirection_keys = sorted({
        item['normalized_name'] for item in present_git_entries
        if item['normalized_name'] in GIT_REPOSITORY_REDIRECTION_KEYS
    })
    removed_git_keys = sorted(item['name'] for item in present_git_entries)
    environment = {
        key: value for key, value in inherited_environment.items()
        if not str(key).upper().startswith('GIT_')
    }
    environment['PYTHONDONTWRITEBYTECODE'] = '1'
    safe_git_keys = sorted(
        key for key in environment if str(key).upper().startswith('GIT_'))
    common = {
        'inherited_git_environment': git_environment,
        'removed_git_environment_keys': removed_git_keys,
        'safe_environment_git_keys': safe_git_keys,
        'repository_redirection_keys_present': redirection_keys,
        'repository_context': _repository_git_metadata(workspace),
        'safe_directory': str(workspace),
        'environment_policy': (
            'record_git_metadata_remove_all_git_environment_and_reject_'
            'repository_redirection_then_use_command_scoped_safe_directory'),
    }
    if redirection_keys:
        result = {
            'argv': [], 'cwd': str(workspace), 'exit_code': None,
            'timed_out': False, 'duration_sec': 0.0, 'stdout': '',
            'stderr': (
                'repository redirection environment is forbidden: '
                + ','.join(redirection_keys)),
        }
        common.update({
            'resolved_executable': None,
            'repository_probe_command': None,
            'repository_probe_failure_classification': None,
            'repository_toplevel': None,
            'repository_toplevel_matches_workspace': False,
            'diff_failure_classification': None,
            'command': _record_command(result),
            'failures': ['git_repository_redirection_environment_present'],
        })
        return common
    git_candidate = shutil.which('git', path=environment.get('PATH'))
    if git_candidate is None:
        result = {
            'argv': [], 'cwd': str(workspace), 'exit_code': None,
            'timed_out': False,
            'duration_sec': 0.0, 'stdout': '',
            'stderr': 'git executable was not found on PATH',
        }
        common.update({
            'resolved_executable': None,
            'repository_probe_command': None,
            'repository_probe_failure_classification': None,
            'repository_toplevel': None,
            'repository_toplevel_matches_workspace': False,
            'diff_failure_classification': None,
            'command': _record_command(result),
            'failures': ['git_executable_not_found'],
        })
        return common
    try:
        git_executable = Path(git_candidate).resolve(strict=True)
        if not git_executable.is_file():
            raise OSError('resolved git executable is not a file')
        resolved_executable = _identity(git_executable)
    except OSError as error:
        result = {
            'argv': [str(git_candidate)], 'cwd': str(workspace),
            'exit_code': None,
            'timed_out': False, 'duration_sec': 0.0, 'stdout': '',
            'stderr': '{}: {}'.format(type(error).__name__, error),
        }
        common.update({
            'resolved_executable': None,
            'repository_probe_command': None,
            'repository_probe_failure_classification': None,
            'repository_toplevel': None,
            'repository_toplevel_matches_workspace': False,
            'diff_failure_classification': None,
            'command': _record_command(result),
            'failures': ['git_executable_unresolvable'],
        })
        return common

    command_prefix = _git_command_prefix(git_executable, workspace)
    probe_result = command_runner(
        command_prefix + ['rev-parse', '--show-toplevel'],
        workspace, environment)
    probe_result = dict(probe_result)
    probe_result.setdefault('cwd', str(workspace))
    probe_failures = []
    repository_toplevel = None
    if probe_result.get('exit_code') != 0 or probe_result.get('timed_out'):
        probe_failures.append('git_repository_probe_failed')
    else:
        parsed_toplevel, parse_failure = _parse_git_toplevel(
            probe_result.get('stdout', ''))
        if parse_failure:
            probe_failures.append(parse_failure)
        else:
            repository_toplevel = parsed_toplevel
            if not _paths_identical(repository_toplevel, workspace):
                probe_failures.append('git_repository_toplevel_mismatch')
    if probe_failures:
        result = {
            'argv': command_prefix + ['diff', '--check'],
            'cwd': str(workspace), 'exit_code': None,
            'timed_out': False, 'duration_sec': 0.0, 'stdout': '',
            'stderr': 'diff was not run because repository probe failed',
        }
        common.update({
            'resolved_executable': resolved_executable,
            'repository_probe_command': _record_command(probe_result),
            'repository_probe_failure_classification': (
                _git_failure_classification(probe_result)),
            'repository_toplevel': (
                str(repository_toplevel)
                if repository_toplevel is not None else None),
            'repository_toplevel_matches_workspace': False,
            'diff_failure_classification': None,
            'command': _record_command(result),
            'failures': probe_failures,
        })
        return common

    result = command_runner(
        command_prefix + ['diff', '--check'], workspace, environment)
    result = dict(result)
    result.setdefault('cwd', str(workspace))
    failures = []
    if result.get('exit_code') != 0 or result.get('timed_out'):
        failures.append('git_diff_check_failed')
    common.update({
        'resolved_executable': resolved_executable,
        'repository_probe_command': _record_command(probe_result),
        'repository_probe_failure_classification': None,
        'repository_toplevel': str(repository_toplevel),
        'repository_toplevel_matches_workspace': True,
        'diff_failure_classification': _git_failure_classification(result),
        'command': _record_command(result),
        'failures': failures,
    })
    return common


def _python_identity():
    path = Path(sys.executable)
    result = {
        'path': str(path),
        'version': sys.version,
        'version_info': list(sys.version_info[:3]),
    }
    try:
        result.update({
            'size_bytes': path.stat().st_size,
            'sha256': sha256_file(path),
        })
    except OSError:
        result['identity_unreadable'] = True
    return result


def _load_perception_readiness(workspace):
    workspace = Path(workspace).resolve(strict=True)
    package_root = workspace / 'src/limo_cleanup_perception'
    path = package_root / (
        'limo_cleanup_perception/perception_readiness.py')
    spec = importlib.util.spec_from_file_location(
        'perception_v2_ros1_field_gate_support', str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError('cannot load perception readiness validators')
    module = importlib.util.module_from_spec(spec)
    inserted = str(package_root) not in sys.path
    if inserted:
        sys.path.insert(0, str(package_root))
    try:
        spec.loader.exec_module(module)
    finally:
        if inserted:
            try:
                sys.path.remove(str(package_root))
            except ValueError:
                pass
    return module


def validate_ros1_build_environment_evidence(workspace, evidence_path=None):
    workspace = Path(workspace).resolve(strict=True)
    path = Path(evidence_path) if evidence_path is not None else (
        workspace / ROS1_BUILD_ATTEMPT_RELATIVE)
    failures = []
    try:
        path = path.resolve(strict=True)
    except (OSError, RuntimeError):
        return {
            'evidence_path': str(path),
            'evidence_identity': None,
            'valid_environment_blocker_evidence': False,
            'shell_entered': None,
            'build_started': None,
            'source_build_failure': None,
            'environment_blockers': [],
            'formal_state_observation': None,
            'failures': ['ros1_build_attempt_evidence_missing'],
        }
    try:
        identity = _identity(path, relative_to=workspace)
    except (OSError, ValueError):
        identity = None
        failures.append('ros1_build_attempt_evidence_unreadable')
    if identity is not None and (
            identity['size_bytes'] != ROS1_BUILD_ATTEMPT_EXPECTED_SIZE_BYTES
            or identity['sha256'] != ROS1_BUILD_ATTEMPT_EXPECTED_SHA256):
        failures.append('ros1_build_attempt_evidence_identity_mismatch')
    try:
        payload = json.loads(
            path.read_text(encoding='utf-8'),
            object_pairs_hook=_strict_object,
            parse_constant=_invalid_json_constant)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        payload = {}
        failures.append('ros1_build_attempt_evidence_invalid_json')
    attempt = payload.get('attempt')
    if (payload.get('report_kind')
            != 'perception_v2_ros1_noetic_isolated_build_attempt'
            or payload.get('runtime_family') != 'ROS1'
            or payload.get('ros_distro') != 'noetic'
            or payload.get('result') != 'BLOCKED_ENVIRONMENT_BEFORE_BUILD'
            or payload.get('formal_acceptance') is not False
            or payload.get('delivery_ready') is not False
            or not isinstance(attempt, dict)
            or attempt.get('error_code') != 'E_ACCESSDENIED'
            or attempt.get('linux_instance_entered') is not False
            or attempt.get('configure_started') is not False
            or attempt.get('build_started') is not False
            or attempt.get('tests_started') is not False
            or attempt.get('install_started') is not False
            or attempt.get('source_build_failure') is not False):
        failures.append('ros1_build_attempt_environment_semantics_invalid')
    formal_state = payload.get('formal_state')
    if not isinstance(formal_state, dict):
        formal_state = None
        failures.append('ros1_build_attempt_formal_state_missing')
    valid = not failures
    return {
        'evidence_path': str(path),
        'evidence_identity': identity,
        'valid_environment_blocker_evidence': valid,
        'shell_entered': (
            attempt.get('linux_instance_entered')
            if isinstance(attempt, dict) else None),
        'build_started': (
            attempt.get('build_started')
            if isinstance(attempt, dict) else None),
        'source_build_failure': (
            attempt.get('source_build_failure')
            if isinstance(attempt, dict) else None),
        'environment_blockers': (
            [ROS1_BUILD_ENVIRONMENT_BLOCKER] if valid else []),
        'formal_state_observation': formal_state,
        'failures': sorted(set(failures)),
    }


def validate_ros1_canonical_source_admission(
        workspace, readiness, source_audit, release_source_snapshot=None):
    """Bind field admission to the live canonical project ROS1 overlay.

    The field evidence may name an isolated build copy, but it never selects
    the expected source.  This gate creates that expectation from the current
    project overlay, then requires the separately frozen admission manifest to
    contain the exact same binding.
    """
    workspace = Path(workspace).resolve(strict=True)
    declared_path = workspace / ROS1_CANONICAL_SOURCE_ADMISSION_RELATIVE
    failures = []
    fresh_binding = None
    if (readiness is None
            or not hasattr(readiness, 'make_ros1_canonical_source_binding')):
        failures.append(ROS1_CANONICAL_ADMISSION_BINDING_UNAVAILABLE)
    else:
        try:
            fresh_binding = readiness.make_ros1_canonical_source_binding(
                workspace=workspace, source_audit=source_audit,
                test_only=False)
        except Exception as error:
            failures.append(
                ROS1_CANONICAL_ADMISSION_BINDING_UNAVAILABLE + ':'
                + type(error).__name__)
    if (not isinstance(fresh_binding, dict)
            or fresh_binding.get('binding_kind')
            != 'canonical_project_overlay'
            or fresh_binding.get('test_only') is not False
            or fresh_binding.get('canonical_source_root')
            != 'ros1_overlay_src/limo_cleanup_ros1_perception'):
        if fresh_binding is not None:
            failures.append(ROS1_CANONICAL_ADMISSION_BINDING_UNAVAILABLE)
        fresh_binding = None

    manifest_path = None
    manifest_identity = None
    manifest_binding = None
    linklike_parts = []
    candidate = declared_path
    while candidate != workspace:
        if _is_linklike(candidate):
            try:
                linklike_parts.append(candidate.relative_to(
                    workspace).as_posix())
            except ValueError:
                linklike_parts.append(str(candidate))
        candidate = candidate.parent
    if linklike_parts:
        failures.append(ROS1_CANONICAL_ADMISSION_MANIFEST_LINK_FORBIDDEN)
    try:
        manifest_path = declared_path.resolve(strict=True)
    except (OSError, RuntimeError):
        failures.append(ROS1_CANONICAL_ADMISSION_MANIFEST_MISSING)
    if manifest_path is not None:
        try:
            if manifest_path.relative_to(workspace) != Path(
                    ROS1_CANONICAL_SOURCE_ADMISSION_RELATIVE):
                failures.append(
                    ROS1_CANONICAL_ADMISSION_MANIFEST_LINK_FORBIDDEN)
            manifest_identity = _identity(
                manifest_path, relative_to=workspace)
            manifest_binding = json.loads(
                manifest_path.read_text(encoding='utf-8'),
                object_pairs_hook=_strict_object,
                parse_constant=_invalid_json_constant)
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
            failures.append(ROS1_CANONICAL_ADMISSION_MANIFEST_INVALID)
            manifest_binding = None
    if (fresh_binding is not None and manifest_binding is not None
            and manifest_binding != fresh_binding):
        failures.append(ROS1_CANONICAL_ADMISSION_BINDING_MISMATCH)
    snapshot_entries = (
        release_source_snapshot.get('entries', [])
        if isinstance(release_source_snapshot, dict) else [])
    matching_snapshot_entries = [
        item for item in snapshot_entries
        if isinstance(item, dict)
        and item.get('path') == ROS1_CANONICAL_SOURCE_ADMISSION_RELATIVE]
    manifest_snapshot_entry = (
        matching_snapshot_entries[0]
        if len(matching_snapshot_entries) == 1 else None)
    if (manifest_identity is not None
            and manifest_snapshot_entry != manifest_identity):
        failures.append(
            ROS1_CANONICAL_ADMISSION_MANIFEST_IDENTITY_NOT_BOUND)
    validated_pass = (
        fresh_binding is not None
        and manifest_binding == fresh_binding
        and not failures)
    return {
        'gate_id': ROS1_CANONICAL_SOURCE_ADMISSION_GATE_ID,
        'scope': 'field_delivery_source_admission',
        'required_for_field_delivery': True,
        'field_evidence_can_override': False,
        'manifest_relative_path': ROS1_CANONICAL_SOURCE_ADMISSION_RELATIVE,
        'manifest_path': str(
            manifest_path if manifest_path is not None else declared_path),
        'manifest_identity': manifest_identity,
        'release_snapshot_source_set_sha256': (
            release_source_snapshot.get('source_set_sha256')
            if isinstance(release_source_snapshot, dict) else None),
        'manifest_snapshot_entry': manifest_snapshot_entry,
        'manifest_binding': manifest_binding,
        'fresh_canonical_binding': fresh_binding,
        'manifest_content_matches_fresh_binding': (
            fresh_binding is not None
            and manifest_binding == fresh_binding),
        'manifest_identity_bound_to_release_snapshot': (
            manifest_identity is not None
            and manifest_snapshot_entry == manifest_identity),
        'linklike_path_parts': sorted(set(linklike_parts)),
        'validated_pass': validated_pass,
        'failures': sorted(set(failures)),
    }


def validate_ros1_delivery_install_gates(
        workspace, source_snapshot, field_install_evidence=None,
        build_attempt_evidence=None):
    workspace = Path(workspace).resolve(strict=True)
    field_path = (
        Path(field_install_evidence) if field_install_evidence is not None
        else workspace / DEFAULT_ROS1_FIELD_INSTALL_EVIDENCE_RELATIVE)
    release_binding = {
        'release_id': 'perception-v2-' + source_snapshot[
            'source_set_sha256'][:16],
        'source_set_sha256': source_snapshot['source_set_sha256'],
    }
    failures = []
    try:
        readiness = _load_perception_readiness(workspace)
    except Exception as error:
        readiness = None
        source_audit = {
            'gate_id': ROS1_FIELD_INSTALL_GATE_ID,
            'scope': 'field_delivery',
            'required_for_delivery': True,
            'pass': False,
            'architecture_blockers': [ROS1_RUNTIME_ARCHITECTURE_BLOCKER],
            'failures': [
                'ros1_field_source_validator_exception:'
                + type(error).__name__],
        }
        failures.append('ros1_field_validator_unavailable')
    else:
        try:
            source_audit = (
                readiness.audit_ros1_noetic_field_source_contract(
                    workspace=workspace))
        except Exception as error:
            source_audit = {
                'gate_id': ROS1_FIELD_INSTALL_GATE_ID,
                'scope': 'field_delivery',
                'required_for_delivery': True,
                'pass': False,
                'architecture_blockers': [
                    ROS1_RUNTIME_ARCHITECTURE_BLOCKER],
                'failures': [
                    'ros1_field_source_validator_exception:'
                    + type(error).__name__],
            }
            failures.append('ros1_field_source_validator_unavailable')
    canonical_admission = validate_ros1_canonical_source_admission(
        workspace, readiness, source_audit,
        release_source_snapshot=source_snapshot)
    canonical_binding = canonical_admission.get(
        'fresh_canonical_binding')
    if isinstance(canonical_binding, dict):
        release_binding.update({
            'expected_ros1_source_set_sha256': canonical_binding.get(
                'source_set_sha256'),
            'expected_ros1_contract_sha256': canonical_binding.get(
                'contract_sha256'),
            'canonical_source_binding_sha256': canonical_binding.get(
                'binding_sha256'),
            'canonical_source_admission_manifest_sha256': (
                canonical_admission.get('manifest_identity') or {}).get(
                    'sha256'),
        })
    if readiness is not None:
        try:
            install_validation = (
                readiness.validate_ros1_noetic_field_install_evidence(
                    field_path,
                    release_binding=release_binding,
                    expected_model_hashes=readiness.EXPECTED_MODEL_SHA256,
                    now_unix_sec=time.time(),
                    workspace=workspace,
                    source_audit=source_audit,
                    canonical_source_binding=canonical_binding,
                    allow_test_synthetic_binding=False))
        except Exception as error:
            install_validation = {
                'gate_id': ROS1_FIELD_INSTALL_GATE_ID,
                'scope': 'field_delivery',
                'required_for_delivery': True,
                'claimed_result': None,
                'validated_pass': False,
                'architecture_blockers': (
                    [ROS1_RUNTIME_ARCHITECTURE_BLOCKER]
                    if source_audit.get('pass') is not True else []),
                'installed_artifact_count': 0,
                'failures': [
                    'ros1_field_install_validator_exception:'
                    + type(error).__name__],
            }
            failures.append('ros1_field_install_validator_unavailable')
    else:
        install_validation = {
            'gate_id': ROS1_FIELD_INSTALL_GATE_ID,
            'scope': 'field_delivery',
            'required_for_delivery': True,
            'claimed_result': None,
            'validated_pass': False,
            'architecture_blockers': [ROS1_RUNTIME_ARCHITECTURE_BLOCKER],
            'installed_artifact_count': 0,
            'failures': [
                'ros1_field_install_validator_not_loaded'],
        }
    source_pass = source_audit.get('pass') is True
    canonical_admission_pass = (
        canonical_admission.get('validated_pass') is True)
    install_pass = install_validation.get('validated_pass') is True
    if not source_pass:
        failures.append('ros1_field_source_contract_blocked')
    if not canonical_admission_pass:
        failures.append('ros1_canonical_source_admission_blocked')
        failures.extend(canonical_admission.get('failures', []))
    if not install_pass:
        failures.append('ros1_field_install_evidence_blocked')

    # Source implementation authority is live and external to field-install
    # evidence.  A missing or stale install report may retain an old source
    # blocker as provenance, but it cannot reopen a source architecture gate
    # that the live audit plus canonical admission have closed.
    source_implementation_pass = source_pass and canonical_admission_pass
    architecture_blockers = sorted(set(
        source_audit.get('architecture_blockers', [])))
    if (not source_implementation_pass
            and ROS1_RUNTIME_ARCHITECTURE_BLOCKER not in
            architecture_blockers):
        architecture_blockers.append(ROS1_RUNTIME_ARCHITECTURE_BLOCKER)
        architecture_blockers.sort()
    historical_source_observations = []
    install_architecture = install_validation.get('architecture_blockers', [])
    install_failures = install_validation.get('failures', [])
    if (source_implementation_pass
            and ROS1_RUNTIME_ARCHITECTURE_BLOCKER in set(
                list(install_architecture) + list(install_failures))):
        historical_source_observations.append({
            'code': ROS1_RUNTIME_ARCHITECTURE_BLOCKER,
            'source': 'field_install_evidence_validation',
            'status': 'HISTORICAL_SUPERSEDED_OBSERVATION',
            'is_current': False,
            'authoritative_for_source_implementation': False,
        })

    evidence_missing = (
        not field_path.is_file()
        or 'ros1_field_install_evidence_missing' in install_failures)
    field_evidence_blockers = []
    if not install_pass:
        field_evidence_blockers.append(
            ROS1_FIELD_INSTALL_EVIDENCE_MISSING_BLOCKER
            if evidence_missing
            else ROS1_FIELD_INSTALL_EVIDENCE_NOT_VALIDATED_BLOCKER)
    build_install_blockers = (
        [] if install_pass else [ROS1_BUILD_INSTALL_NOT_VERIFIED_BLOCKER])
    environment = validate_ros1_build_environment_evidence(
        workspace, evidence_path=build_attempt_evidence)
    return {
        'gate_id': ROS1_FIELD_INSTALL_GATE_ID,
        'scope': 'field_delivery',
        'required_for_delivery': True,
        'substitutes_with_ros2_migration_gate': False,
        'release_binding': release_binding,
        'field_install_evidence_path': str(field_path.resolve()),
        'canonical_source_admission': canonical_admission,
        'source_contract': source_audit,
        'install_validation': install_validation,
        'validated_pass': (
            source_pass and canonical_admission_pass and install_pass),
        'source_implementation_pass': source_implementation_pass,
        'architecture_blockers': architecture_blockers,
        'build_install_blockers': build_install_blockers,
        'field_evidence_blockers': field_evidence_blockers,
        'historical_source_observations': historical_source_observations,
        'install_validation_observation': {
            'status': (
                'MISSING_FIELD_INSTALL_EVIDENCE'
                if evidence_missing else 'UNVERIFIED_FIELD_INSTALL_EVIDENCE'),
            'is_current_source_authority': False,
            'architecture_blockers_authoritative': False,
            'superseded_by_live_source_and_canonical_admission': (
                source_implementation_pass),
        },
        'build_environment_evidence': environment,
        'failures': sorted(set(failures)),
    }


def make_delivery_gate_summary(
        declarations, install, ros1_field, evidence_authority=None):
    ros2_pass = (
        declarations.get('validated_pass') is True
        and install.get('validated_pass') is True)
    ros1_pass = ros1_field.get('validated_pass') is True
    environment = ros1_field.get('build_environment_evidence', {})
    active_environment_blockers = (
        environment.get('environment_blockers', []) if not ros1_pass else [])
    formal_state = environment.get('formal_state_observation') or {}
    formal_denominator = formal_state.get(
        'formal_four_scene_frame_denominator', 0)
    formal_tf_pass = formal_state.get('formal_tf_pass') is True
    formal_3d_pass = formal_state.get('formal_3d_pass') is True
    formal_latency_pass = formal_state.get('formal_latency_pass') is True
    formal_pass = (
        isinstance(formal_denominator, int) and formal_denominator >= 120
        and formal_tf_pass and formal_3d_pass and formal_latency_pass)
    canonical_admission = ros1_field.get(
        'canonical_source_admission', {})
    canonical_admission_pass = (
        canonical_admission.get('validated_pass') is True)
    authority = (
        evidence_authority if isinstance(evidence_authority, dict) else {})
    authority_pass = authority.get('validated_pass') is True
    authority_current = authority.get('current_evidence') or {}
    blockers = []
    architecture_blockers = sorted(set(
        ros1_field.get('architecture_blockers', [])))
    build_install_blockers = sorted(set(
        ros1_field.get('build_install_blockers', [])))
    field_evidence_blockers = sorted(set(
        ros1_field.get('field_evidence_blockers', [])))
    formal_field_blockers = []
    if not authority_pass:
        blockers.append('EVIDENCE_AUTHORITY_INDEX_NOT_VALIDATED')
    else:
        blockers.append('CURRENT_BASELINE_BLOCKED_OFFLINE_ONLY')
    if not ros1_pass:
        blockers.append('ROS1_NOETIC_FIELD_INSTALL_NOT_VALIDATED')
    if not canonical_admission_pass:
        blockers.append('ROS1_CANONICAL_SOURCE_ADMISSION_NOT_VALIDATED')
    blockers.extend(architecture_blockers)
    blockers.extend(build_install_blockers)
    blockers.extend(field_evidence_blockers)
    blockers.extend(active_environment_blockers)
    if not formal_pass:
        blockers.append(
            'FORMAL_FOUR_SCENE_DENOMINATOR_ZERO'
            if formal_denominator == 0
            else 'FORMAL_FOUR_SCENE_DENOMINATOR_INSUFFICIENT')
        if not formal_tf_pass:
            blockers.append('FORMAL_TF_NOT_VALIDATED')
        if not formal_3d_pass:
            blockers.append('FORMAL_3D_NOT_VALIDATED')
        if not formal_latency_pass:
            blockers.append('FORMAL_LATENCY_NOT_VALIDATED')
    formal_field_blockers.extend(
        item for item in blockers if item.startswith('FORMAL_'))
    return {
        'delivery_ready': False,
        'required_field_gates': [
            EVIDENCE_AUTHORITY_GATE_ID,
            ROS1_CANONICAL_SOURCE_ADMISSION_GATE_ID,
            ROS1_FIELD_INSTALL_GATE_ID,
            'FORMAL_FOUR_SCENE_RGBD_TF_3D'],
        'evidence_authority_gate': {
            'gate_id': EVIDENCE_AUTHORITY_GATE_ID,
            'scope': 'offline_evidence_selection_authority',
            'required_for_evidence_consumers': True,
            'accept_only_index_selected_current': True,
            'filename_mtime_selection_forbidden': True,
            'validated_pass': authority_pass,
            'current_evidence_id': authority_current.get('evidence_id'),
            'current_status': authority_current.get('status'),
            'current_scope': authority_current.get('scope'),
            'current_identity': authority.get('current_identity'),
            'authorizes_field_delivery': False,
            'delivery_ready': False,
            'failures': authority.get('failures', []),
        },
        'ros2_migration_gate': {
            'gate_id': ROS2_MIGRATION_INSTALL_GATE_ID,
            'scope': 'offline_migration',
            'required_for_field_delivery': False,
            'substitutes_for_ros1_field': False,
            'validated_pass': ros2_pass,
            'declaration_failure_count': len(
                declarations.get('failures', [])),
            'installed_artifact_failure_count': len(
                install.get('failures', [])),
        },
        'ros1_field_gate': {
            'gate_id': ROS1_FIELD_INSTALL_GATE_ID,
            'scope': 'field_delivery',
            'required_for_field_delivery': True,
            'validated_pass': ros1_pass,
            'source_contract_pass': (
                ros1_field.get('source_contract', {}).get('pass') is True),
            'install_evidence_pass': (
                ros1_field.get('install_validation', {}).get(
                    'validated_pass') is True),
            'source_implementation_pass': (
                ros1_field.get('source_implementation_pass') is True),
            'build_install_blockers': build_install_blockers,
            'field_evidence_blockers': field_evidence_blockers,
        },
        'ros1_canonical_source_admission_gate': {
            'gate_id': ROS1_CANONICAL_SOURCE_ADMISSION_GATE_ID,
            'required_for_field_delivery': True,
            'field_evidence_can_override': False,
            'manifest_path': canonical_admission.get('manifest_path'),
            'manifest_identity': canonical_admission.get(
                'manifest_identity'),
            'fresh_binding_sha256': (
                canonical_admission.get('fresh_canonical_binding') or {}
            ).get('binding_sha256'),
            'validated_pass': canonical_admission_pass,
            'failures': canonical_admission.get('failures', []),
        },
        'environment_gate': {
            'historical_attempt_evidence_valid': environment.get(
                'valid_environment_blocker_evidence') is True,
            'source_build_failure': environment.get('source_build_failure'),
            'active_blockers': active_environment_blockers,
        },
        'formal_field_evidence_gate': {
            'formal_four_scene_frame_denominator': formal_denominator,
            'formal_tf_pass': formal_tf_pass,
            'formal_3d_pass': formal_3d_pass,
            'formal_latency_pass': formal_latency_pass,
            'validated_pass': formal_pass,
            'diagnostic_or_historical_evidence_cannot_close_gate': True,
        },
        'architecture_blockers': architecture_blockers,
        'build_install_blockers': build_install_blockers,
        'field_evidence_blockers': field_evidence_blockers,
        'formal_field_blockers': sorted(set(formal_field_blockers)),
        'delivery_blockers': sorted(set(blockers)),
    }


def _base_report(workspace, install_base):
    return {
        'schema_version': REPORT_SCHEMA_VERSION,
        'report_kind': REPORT_KIND,
        'generated_at_unix_sec': time.time(),
        'workspace_root': str(Path(workspace).resolve()),
        'install_base': str(Path(install_base).resolve()),
        'read_only': True,
        'authorizes_motion': False,
        'publishes_ros_messages': False,
        'ros_graph_started': False,
        'camera_opened': False,
        'hardware_connected': False,
        'delivery_ready': False,
        'delivery_scope': (
            'offline_regression_only_not_field_3d_tf_build_or_runtime'),
        'regression_passed': False,
        'failures': [],
        'python': _python_identity(),
    }


def run_regression(workspace, install_base, report_path=None,
                   command_runner=_command_result,
                   ros1_field_install_evidence=None,
                   ros1_build_attempt_evidence=None):
    workspace = Path(workspace).resolve(strict=True)
    report = _base_report(workspace, install_base)
    before = snapshot_inputs(workspace, report_path=report_path)
    report['source_snapshot_before'] = before
    failures = list(before['failures'])

    evidence_authority = load_and_resolve_evidence_authority_index(workspace)
    report['evidence_authority_selection'] = evidence_authority
    failures.extend(evidence_authority['failures'])

    inventory = validate_frozen_inventory(workspace)
    report['frozen_inventory'] = inventory
    failures.extend(inventory['failures'])

    tests = run_test_commands(workspace, command_runner=command_runner)
    report['test_matrix'] = tests
    failures.extend(tests['failures'])

    json_result = validate_json_files(workspace, report_path=report_path)
    report['strict_json'] = json_result
    failures.extend(json_result['failures'])

    xml_result = validate_xml_files(workspace)
    report['xml'] = xml_result
    failures.extend(xml_result['failures'])

    declarations = validate_install_declarations(workspace)
    report['install_declarations'] = declarations
    failures.extend(declarations['failures'])

    install = validate_install(workspace, install_base, declarations)
    report['installed_artifacts'] = install
    failures.extend(install['failures'])

    ros1_field = validate_ros1_delivery_install_gates(
        workspace, before,
        field_install_evidence=ros1_field_install_evidence,
        build_attempt_evidence=ros1_build_attempt_evidence)
    report['ros1_field_install_validation'] = ros1_field
    failures.extend(ros1_field['failures'])
    if ros1_field.get('build_environment_evidence', {}).get('failures'):
        failures.append('ros1_build_environment_evidence_invalid')
    report['install_gates'] = {
        ROS2_MIGRATION_INSTALL_GATE_ID: {
            'scope': 'offline_migration',
            'required_for_field_delivery': False,
            'substitutes_for_ros1_field': False,
            'declarations_validated_pass': (
                declarations.get('validated_pass') is True),
            'installed_artifacts_validated_pass': (
                install.get('validated_pass') is True),
        },
        ROS1_CANONICAL_SOURCE_ADMISSION_GATE_ID: {
            'scope': 'field_delivery_source_admission',
            'required_for_field_delivery': True,
            'field_evidence_can_override': False,
            'validated_pass': (
                ros1_field.get('canonical_source_admission', {}).get(
                    'validated_pass') is True),
            'manifest_identity': ros1_field.get(
                'canonical_source_admission', {}).get(
                    'manifest_identity'),
            'fresh_binding_sha256': (
                ros1_field.get('canonical_source_admission', {}).get(
                    'fresh_canonical_binding') or {}).get('binding_sha256'),
        },
        ROS1_FIELD_INSTALL_GATE_ID: {
            'scope': 'field_delivery',
            'required_for_field_delivery': True,
            'substitutes_with_ros2_migration_gate': False,
            'source_contract_pass': (
                ros1_field.get('source_contract', {}).get('pass') is True),
            'installed_artifacts_validated_pass': (
                ros1_field.get('install_validation', {}).get(
                    'validated_pass') is True),
            'validated_pass': ros1_field.get('validated_pass') is True,
        },
    }
    report['delivery_gate_summary'] = make_delivery_gate_summary(
        declarations, install, ros1_field,
        evidence_authority=evidence_authority)
    report['architecture_blockers'] = report[
        'delivery_gate_summary']['architecture_blockers']
    report['environment_blockers'] = report[
        'delivery_gate_summary']['environment_gate']['active_blockers']

    security = validate_security(workspace)
    report['security'] = security
    failures.extend(security['failures'])

    diff = run_diff_check(workspace, command_runner=command_runner)
    report['diff_check'] = diff
    failures.extend(diff['failures'])

    after = snapshot_inputs(workspace, report_path=report_path)
    drift = compare_snapshots(before, after)
    report['source_snapshot_after'] = after
    report['source_drift'] = drift
    failures.extend(after['failures'])
    if not drift['unchanged']:
        failures.append('source_changed_during_regression')

    # The ledger intentionally binds inputs, not its own recursively defined
    # digest.  Hash the finished report externally after exclusive creation.
    report['hash_ledger'] = {
        'source_file_count': after['file_count'],
        'source_set_sha256': after['source_set_sha256'],
        'evidence_authority_index': {
            'gate_id': EVIDENCE_AUTHORITY_GATE_ID,
            'index_identity': evidence_authority.get('index_identity'),
            'expected_index_identity': evidence_authority.get(
                'expected_index_identity'),
            'current_evidence': evidence_authority.get('current_evidence'),
            'current_identity': evidence_authority.get('current_identity'),
            'accept_only_index_selected_current': True,
            'validated_pass': (
                evidence_authority.get('validated_pass') is True),
        },
        'json_artifacts': json_result['entries'],
        'xml_artifacts': xml_result['entries'],
        'installed_copies': install['copies'],
        'ros2_migration_gate_id': ROS2_MIGRATION_INSTALL_GATE_ID,
        'ros1_field_contract': {
            'path': ros1_field.get('source_contract', {}).get(
                'contract_path'),
            'sha256': ros1_field.get('source_contract', {}).get(
                'contract_sha256'),
            'source_set_sha256': ros1_field.get('source_contract', {}).get(
                'source_set_sha256'),
        },
        'ros1_canonical_source_admission': {
            'manifest_relative_path': ros1_field.get(
                'canonical_source_admission', {}).get(
                    'manifest_relative_path'),
            'manifest_identity': ros1_field.get(
                'canonical_source_admission', {}).get(
                    'manifest_identity'),
            'manifest_snapshot_entry': ros1_field.get(
                'canonical_source_admission', {}).get(
                    'manifest_snapshot_entry'),
            'release_snapshot_source_set_sha256': ros1_field.get(
                'canonical_source_admission', {}).get(
                    'release_snapshot_source_set_sha256'),
            'binding': ros1_field.get(
                'canonical_source_admission', {}).get(
                    'fresh_canonical_binding'),
            'validated_pass': ros1_field.get(
                'canonical_source_admission', {}).get(
                    'validated_pass') is True,
        },
        'ros1_build_attempt_evidence': ros1_field.get(
            'build_environment_evidence', {}).get('evidence_identity'),
        'python_executable': report['python'],
    }
    report['failures'] = sorted(set(failures))
    report['regression_passed'] = not report['failures']
    # Formal delivery readiness is never granted by this offline command.
    report['delivery_ready'] = False
    return report


def _write_reserved_report(stream, report):
    json.dump(report, stream, ensure_ascii=False, indent=2, sort_keys=True)
    stream.write('\n')
    stream.flush()
    os.fsync(stream.fileno())


def main(argv=None):
    effective_argv = list(sys.argv[1:] if argv is None else argv)
    if (effective_argv
            and effective_argv[0] == '--internal-selected-pytest-style'):
        return _selected_pytest_style_main(effective_argv[1:])
    parser = argparse.ArgumentParser(
        description='Run the frozen V2 perception offline regression.')
    parser.add_argument(
        '--workspace', type=Path,
        default=Path(__file__).resolve().parents[1])
    parser.add_argument('--install-base', type=Path)
    parser.add_argument('--ros1-field-install-evidence', type=Path)
    parser.add_argument('--ros1-build-attempt-evidence', type=Path)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args(effective_argv)
    workspace = args.workspace.resolve(strict=True)
    install_base = (args.install_base or (workspace / 'install')).resolve()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    try:
        # Reserve the evidence path for the whole run.  A crash can leave an
        # empty/incomplete file, which is fail closed and never overwritten.
        with args.report.open('x', encoding='utf-8') as stream:
            try:
                report = run_regression(
                    workspace, install_base, report_path=args.report,
                    ros1_field_install_evidence=(
                        args.ros1_field_install_evidence),
                    ros1_build_attempt_evidence=(
                        args.ros1_build_attempt_evidence))
            except Exception as error:  # keep unexpected failures fail closed
                report = _base_report(workspace, install_base)
                report['failures'] = [
                    'runner_exception:' + type(error).__name__]
                report['exception_message'] = str(error)
            _write_reserved_report(stream, report)
    except FileExistsError:
        print('report path must not already exist', file=sys.stderr)
        return 2
    print(json.dumps({
        'report': str(args.report.resolve()),
        'regression_passed': report['regression_passed'],
        'delivery_ready': False,
        'failure_count': len(report['failures']),
    }, sort_keys=True))
    return 0 if report['regression_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

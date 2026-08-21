#!/usr/bin/env python3
"""Contracts for the frozen offline release evidence entry point."""

import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock


PACKAGE_ROOT = Path(__file__).parents[1]
WORKSPACE_ROOT = PACKAGE_ROOT.parents[1]
RUNNER_PATH = WORKSPACE_ROOT / 'scripts' / 'run_v1_frozen_offline_regression.py'
TEMPLATE_PATH = PACKAGE_ROOT / 'docs' / 'V1_FROZEN_RELEASE_READINESS.json'

SPEC = importlib.util.spec_from_file_location('frozen_runner', RUNNER_PATH)
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)


class FrozenReleaseReadinessTests(unittest.TestCase):

    @staticmethod
    def _verified_vendor():
        return {
            'path': 'synthetic/vendor.json',
            'artifact_status': 'VERIFIED',
            'verified': True,
            'decision': 'PASS',
            'failure_code': None,
            'errors': [],
        }

    @staticmethod
    def _clear_release():
        return {
            'path': 'synthetic/release-drift.json',
            'artifact_status': 'VERIFIED_NO_RELEASE_DRIFT',
            'matching_files': 14,
            'mismatching_files': 0,
            'drift_active': False,
            'decision': 'PASS',
            'errors': [],
        }

    @staticmethod
    def _exact_closures():
        return tuple({
            'name': item['check'],
            'status': 'PASS',
            'assertion_count': item['expected_assertion_count'],
            'errors': [],
        } for item in RUNNER.INTEGRATED_SOFTWARE_CLOSURES)

    @staticmethod
    def _bridge_failure(
            nodes, parse_status='PARSED', returncode=1,
            expected_count=122, observed_count=121,
            execution_error=None):
        return {
            'name': 'bridge_pytest',
            'status': 'FAIL',
            'returncode': returncode,
            'execution_error': execution_error,
            'expected_count': expected_count,
            'observed_count': observed_count,
            'pytest_failures': {
                'parse_status': parse_status,
                'failed_nodeids': list(nodes),
                'matched_line_count': len(nodes),
                'duplicate_line_count': 0,
            },
        }

    def test_template_never_claims_delivery_or_field_evidence(self):
        payload = json.loads(TEMPLATE_PATH.read_text(encoding='utf-8'))
        self.assertEqual(payload['schema'], RUNNER.SCHEMA)
        self.assertEqual(payload['decision_model'], RUNNER.DECISION_MODEL)
        self.assertFalse(payload['check_matrix_pass'])
        output_contract = payload['external_check_output_contract']
        self.assertFalse(output_contract['raw_output_content_persisted'])
        self.assertTrue(output_contract['redacted_summary_content_persisted'])
        self.assertEqual(output_contract['summary_head_line_limit'], 12)
        self.assertEqual(output_contract['summary_tail_line_limit'], 12)
        self.assertEqual(output_contract['summary_line_char_limit'], 512)
        self.assertIn('stdout_sha256', output_contract['raw_integrity_fields'])
        bridge_contract = payload['bridge_failure_attribution_contract']
        self.assertEqual(
            set(bridge_contract['allowed_failed_nodeids']),
            RUNNER.BRIDGE_RELEASE_HASH_FAILURE_ALLOWLIST)
        self.assertTrue(bridge_contract['exact_set_required'])
        self.assertEqual(bridge_contract['returncode_required'], 1)
        self.assertEqual(bridge_contract['expected_count_required'], 122)
        self.assertEqual(bridge_contract['observed_count_required'], 121)
        self.assertIsNone(bridge_contract['execution_error_required'])
        self.assertEqual(
            bridge_contract['fallback_category'], 'offline_regression')
        self.assertFalse(payload['software_release_pass'])
        self.assertFalse(payload['software_release_ready'])
        self.assertFalse(payload['integrated_software_ready'])
        self.assertFalse(payload['field_acceptance_complete'])
        self.assertFalse(payload['field_evidence_complete'])
        self.assertFalse(payload['delivery_ready'])
        self.assertEqual(set(payload['field_acceptance']), set(RUNNER.FIELD_ITEMS))
        for item in payload['field_acceptance'].values():
            self.assertEqual(item['status'], 'NOT_RUN')
            self.assertTrue(item['template_only'])
            self.assertFalse(item['real_machine_evidence'])
        authorization = payload['field_authorization']
        self.assertEqual(authorization['status'], 'NOT_RUN')
        self.assertFalse(authorization['execution_ready'])
        self.assertEqual(authorization['decision'], 'BLOCKED')
        self.assertFalse(
            authorization['dedicated_field_orchestrator_present'])
        self.assertEqual(
            set(authorization['classes']), {
                'hardware_read_only', 'zero_motion_localization',
                'real_motion'})
        self.assertFalse(payload['deployment']['autostart'])
        self.assertEqual(
            payload['deployment']['autostart_policy'], 'NO_AUTOSTART')
        self.assertEqual(
            payload['deployment']['native']['execution_status'], 'BLOCKED')
        integrated = payload['integrated_combined_deployment']
        self.assertEqual(integrated['software_status'], 'TEMPLATE_ONLY')
        self.assertEqual(integrated['closure_status'], 'PASS')
        self.assertEqual(integrated['execution_status'], 'BLOCKED')
        self.assertEqual(integrated['software_blockers'], [])
        expected_blockers = {
            'V1_FROZEN_RELEASE_HASH_DRIFT',
            'V1_VENDOR_PROVENANCE_UNVERIFIED',
        }
        self.assertEqual(
            {item['id'] for item in payload['active_software_blockers']},
            expected_blockers)
        self.assertEqual(
            {item['id'] for item in integrated[
                'independent_active_blockers']}, expected_blockers)
        self.assertEqual(
            {item['check']: item['expected_assertion_count']
             for item in integrated['resolved_software_blockers']}, {
                 'integrated_topology_verifier_contract': 8,
                 'integrated_verifier_install_contract': 7,
             })
        vendor = payload['vendor_provenance']
        self.assertFalse(vendor['verified'])
        self.assertTrue(vendor['static_bundle_not_verified'])
        self.assertEqual(vendor['decision'], 'BLOCKED')
        self.assertIsNone(vendor['trust_anchor_matches'])
        self.assertIsNone(vendor['blocker_trust_anchor_matches'])
        self.assertIsNone(vendor['wrapper_trust_anchor_matches'])
        self.assertIsNone(
            vendor['consumer_wrapper']['trust_anchor_matches'])
        release = payload['release_integrity']
        self.assertTrue(release['drift_active'])
        self.assertEqual(release['decision'], 'BLOCKED')
        self.assertEqual(
            release['secure_release_validator']['status'], 'NOT_RUN')
        self.assertFalse(
            release['bridge_release_hash_binding']['eligible'])
        self.assertEqual(
            set(release['bridge_release_hash_binding']['expected_paths']),
            RUNNER.BRIDGE_RELEASE_DRIFT_PATHS)
        template_seal = release[
            'bridge_release_hash_binding']['sealed_release_pin_state']
        self.assertFalse(template_seal['valid'])
        self.assertEqual(template_seal['total_files'], 14)
        self.assertIsNone(template_seal['source_sha256'])
        lineage = payload['evidence_lineage']
        self.assertTrue(lineage['template_only'])
        self.assertTrue(lineage['exclusive_create_required'])
        self.assertTrue(lineage['reserved_paths_never_targets'])
        self.assertTrue(lineage['precommit_revalidation_required'])
        self.assertTrue(lineage['required_for_software_release_pass'])
        self.assertEqual(
            lineage['blocker_id'], 'EVIDENCE_LINEAGE_INTEGRITY_FAILED')
        self.assertEqual(lineage['decision'], 'NOT_EVALUATED')
        self.assertFalse(lineage['verified'])
        self.assertNotIn('current_authoritative', lineage)
        self.assertIsNone(lineage['authority_candidate'])
        protocol = lineage['authority_protocol']
        self.assertTrue(protocol['claim_precedes_candidate'])
        self.assertFalse(protocol['candidate_is_current'])
        self.assertEqual(
            protocol['candidate_lifecycle'],
            'NON_AUTHORITATIVE_PENDING_AUTHORITY_INDEX')
        self.assertEqual(protocol['claim_schema'], RUNNER.AUTHORITY_CLAIM_SCHEMA)
        self.assertEqual(protocol['index_schema'], RUNNER.AUTHORITY_INDEX_SCHEMA)
        predecessor = lineage['direct_authority_predecessor']
        self.assertFalse(predecessor['binding_verified'])
        self.assertEqual(predecessor['decision'], 'NOT_EVALUATED')
        self.assertEqual(
            predecessor['report']['expected_sha256'],
            RUNNER.DIRECT_AUTHORITY_PREDECESSOR['report']['sha256'])
        self.assertEqual(
            predecessor['index']['expected_sha256'],
            RUNNER.DIRECT_AUTHORITY_PREDECESSOR['index']['sha256'])
        expected = {
            RUNNER._workspace_relative(entry['path']): (
                entry['sha256'], entry['reason'])
            for entry in RUNNER.SUPERSEDED_EVIDENCE_REPORTS}
        self.assertEqual(len(expected), 4)
        self.assertEqual(len(lineage['supersedes']), 4)
        self.assertEqual(
            {stale['path'] for stale in lineage['supersedes']}, set(expected))
        for stale in lineage['supersedes']:
            self.assertEqual(
                stale['lifecycle'],
                'STALE_SUPERSEDED_FOR_READINESS_DECISIONS')
            self.assertIsNone(stale['actual_sha256'])
            self.assertEqual(
                (stale['expected_sha256'], stale['reason']),
                expected[stale['path']])
            self.assertIsNone(stale['retained_by_candidate_evidence_id'])

    def test_current_file_audits_cover_all_packages_and_runner(self):
        files = set(RUNNER._current_audit_files())
        self.assertIn(RUNNER_PATH.resolve(), files)
        self.assertTrue(set(RUNNER.SHARED_AUDIT_FILES).issubset(files))
        self.assertTrue(set(RUNNER.INTEGRATED_AUDIT_FILES).issubset(files))
        for root in (RUNNER.V1_ROOT, RUNNER.BRIDGE_ROOT):
            expected = {
                path for path in root.rglob('*')
                if path.is_file()
                and '__pycache__' not in path.parts
                and '.pytest_cache' not in path.parts
                and path.suffix != '.pyc'}
            self.assertTrue(expected.issubset(files))
        self.assertEqual(
            set(RUNNER._current_python_files()),
            {path for path in files if path.suffix == '.py'})

    def test_matrix_has_every_required_check_and_exact_counts(self):
        rows = {row[0]: row for row in RUNNER._matrix()}
        self.assertEqual(
            set(rows), {
                'bridge_pytest', 'secure_release_validator',
                'cross_package_groups', 'overlay_static', 'profile_static',
                'catkin_static'})
        self.assertEqual(rows['bridge_pytest'][-1], 122)
        self.assertEqual(rows['secure_release_validator'][-1], 14)
        self.assertEqual(rows['cross_package_groups'][-1], 9)
        stdout = ('password=DUMMY_PASSWORD\n'
                  'Authorization: Bearer DUMMY_BEARER\n'
                  'https://dummy-user:dummy-pass@example.invalid/path\n'
                  + ('x' * 700) + '\n'
                  + '\n'.join(
                      'middle-{}'.format(index) for index in range(30))
                  + '\nFAILED test/test_other.py::test_param[value with space] '
                  '- AssertionError\n'
                  'FAILED test/test_map_binding.py::'
                  'test_release_files_match_the_frozen_hash_set\n'
                  'FAILED test/test_map_binding.py::'
                  'test_release_files_match_the_frozen_hash_set\n').encode(
                      'utf-8')
        stderr = b'token=DUMMY_STDERR_TOKEN\n'
        completed = mock.Mock(stdout=stdout, stderr=stderr, returncode=1)
        with mock.patch.object(
                RUNNER.subprocess, 'run', return_value=completed):
            captured = RUNNER._run(
                'bridge_pytest', ('python3', '-m', 'pytest', '-q'),
                WORKSPACE_ROOT, marker='122 passed',
                count_pattern=r'(\d+)\s+passed', expected_count=122)
        self.assertEqual(captured['returncode'], 1)
        self.assertEqual(captured['stdout_bytes'], len(stdout))
        self.assertEqual(captured['stderr_bytes'], len(stderr))
        self.assertEqual(captured['stdout_sha256'], RUNNER._sha256(stdout))
        self.assertEqual(captured['stderr_sha256'], RUNNER._sha256(stderr))
        self.assertFalse(
            captured['output_integrity']['raw_content_persisted'])
        self.assertNotIn('raw_output', captured)
        serialized = json.dumps(captured, sort_keys=True)
        for forbidden_secret in (
                'DUMMY_PASSWORD', 'DUMMY_BEARER', 'dummy-user',
                'dummy-pass', 'DUMMY_STDERR_TOKEN'):
            self.assertNotIn(forbidden_secret, serialized)
        summaries = captured['output_summary']
        self.assertGreaterEqual(summaries['stdout']['redaction_count'], 3)
        self.assertEqual(summaries['stderr']['redaction_count'], 1)
        self.assertGreater(summaries['stdout']['omitted_middle_line_count'], 0)
        self.assertGreaterEqual(
            summaries['stdout']['truncated_line_count'], 1)
        for stream in ('stdout', 'stderr'):
            selected = (summaries[stream]['head']
                        + summaries[stream]['tail'])
            self.assertLessEqual(len(selected), 24)
            self.assertTrue(all(len(line) <= 512 for line in selected))
        self.assertEqual(
            captured['pytest_failures']['failed_nodeids'], [
                'test/test_map_binding.py::'
                'test_release_files_match_the_frozen_hash_set',
                'test/test_other.py::test_param[value with space]',
            ])
        self.assertEqual(
            captured['pytest_failures']['parse_status'], 'PARSED')
        self.assertEqual(
            captured['pytest_failures']['duplicate_line_count'], 1)
        malformed = RUNNER._parse_pytest_failed_nodes(
            'FAILED\nFAILEDX hidden\nFAILED test/test_map_binding.py::'
            'test_release_files_match_the_frozen_hash_set', 1, None)
        self.assertEqual(
            malformed['parse_status'], 'MALFORMED_FAILURE_LINES')
        self.assertEqual(malformed['malformed_line_count'], 2)
        unparseable = RUNNER._parse_pytest_failed_nodes(
            'collection aborted before failure summary', 1, None)
        self.assertEqual(
            unparseable['parse_status'], 'UNPARSEABLE_FAILURE')
        sensitive_node = RUNNER._parse_pytest_failed_nodes(
            'FAILED test/test_x.py::test_case[token=DUMMY_NODE_SECRET]',
            1, None)
        self.assertEqual(
            sensitive_node['parse_status'],
            'REDACTED_OR_TRUNCATED_FAILURE_NODE')
        self.assertNotIn(
            'DUMMY_NODE_SECRET', json.dumps(sensitive_node))
        self.assertEqual(
            RUNNER.EXPECTED['v1_frozen_core_unittest'], 113)
        self.assertEqual(
            RUNNER.EXPECTED['v1_delivery_audit_unittest'], 25)
        self.assertEqual(RUNNER.EXPECTED['v1_package_discovery'], 138)
        self.assertEqual(
            {item['check']: item['expected_assertion_count']
             for item in RUNNER.INTEGRATED_SOFTWARE_CLOSURES}, {
                 'integrated_topology_verifier_contract': 8,
                 'integrated_verifier_install_contract': 7,
             })
        vendor = RUNNER._vendor_provenance_state()
        self.assertEqual(
            vendor['artifact_status'], 'BLOCKED_ON_VENDOR_INCLUDE')
        self.assertFalse(vendor['verified'])
        self.assertEqual(
            vendor['failure_code'], 'TF_VENDOR_CONTRACT_UNVERIFIED')
        self.assertTrue(vendor['trust_anchor_matches'])
        self.assertTrue(vendor['blocker_trust_anchor_matches'])
        self.assertTrue(vendor['wrapper_trust_anchor_matches'])
        self.assertTrue(
            vendor['consumer_wrapper']['trust_anchor_matches'])
        self.assertEqual(
            vendor['consumer_wrapper']['artifact_sha256'],
            vendor['topology_policy_trust_anchor'][
                'vendor_wrapper_sha256'])
        self.assertTrue(vendor['static_bundle_not_verified'])
        self.assertFalse(vendor['self_reported_verified_semantics'])
        with tempfile.TemporaryDirectory() as directory:
            fake_path = Path(directory) / 'self-edited-blocker.json'
            fake = json.loads(
                RUNNER.VENDOR_PROVENANCE_PATH.read_text(encoding='utf-8'))
            fake['status'] = 'VERIFIED'
            fake['ownership_conclusion'] = 'VERIFIED'
            local = fake['current_local_evidence']
            local['vendor_raw_source_archived'] = True
            local['current_hash_verified'] = True
            local['resolved_include_chain_verified'] = True
            fake['required_installed_tf_publisher_pin']['status'] = 'VERIFIED'
            fake['decision']['ownership_closed'] = True
            fake['decision']['tf_edge_runtime_pass_eligible'] = True
            fake_path.write_text(
                json.dumps(fake, sort_keys=True) + '\n', encoding='utf-8')
            self_edited = RUNNER._vendor_provenance_state(fake_path)
            self.assertTrue(
                self_edited['self_reported_verified_semantics'])
            self.assertFalse(
                self_edited['blocker_trust_anchor_matches'])
            self.assertTrue(self_edited['wrapper_trust_anchor_matches'])
            self.assertFalse(self_edited['trust_anchor_matches'])
            self.assertTrue(self_edited['static_bundle_not_verified'])
            self.assertFalse(self_edited['verified'])
            self.assertEqual(self_edited['decision'], 'BLOCKED')
        with tempfile.TemporaryDirectory() as directory:
            fake_wrapper = Path(directory) / 'v1_base_sensors.launch'
            fake_wrapper.write_text(
                '<launch><group if="false" /></launch>\n',
                encoding='utf-8')
            wrapper_mismatch = RUNNER._vendor_provenance_state(
                wrapper_path=fake_wrapper)
            self.assertTrue(
                wrapper_mismatch['blocker_trust_anchor_matches'])
            self.assertFalse(
                wrapper_mismatch['wrapper_trust_anchor_matches'])
            self.assertFalse(wrapper_mismatch['trust_anchor_matches'])
            self.assertTrue(wrapper_mismatch['static_bundle_not_verified'])
            self.assertFalse(wrapper_mismatch['verified'])
            self.assertEqual(wrapper_mismatch['decision'], 'BLOCKED')
        release = RUNNER._release_integrity_state()
        self.assertTrue(release['drift_active'])
        self.assertEqual(release['total_files'], 14)
        self.assertEqual(release['matching_files'], 11)
        self.assertEqual(release['mismatching_files'], 3)
        binding = release['bridge_release_hash_binding']
        self.assertTrue(binding['eligible'])
        sealed = binding['sealed_release_pin_state']
        self.assertTrue(sealed['valid'])
        self.assertEqual(sealed['total_files'], 14)
        self.assertEqual(sealed['matching_files'], 11)
        self.assertEqual(sealed['mismatching_files'], 3)
        self.assertEqual(
            set(sealed['mismatch_paths']),
            RUNNER.BRIDGE_RELEASE_DRIFT_PATHS)
        self.assertEqual(
            {item['path'] for item in binding['records']},
            RUNNER.BRIDGE_RELEASE_DRIFT_PATHS)
        self.assertTrue(all(item['valid'] for item in binding['records']))
        self.assertTrue(all(
            item['actual_current_sha256'] ==
            item['declared_current_sha256']
            for item in binding['records']))
        source_drift = json.loads(
            RUNNER.RELEASE_DRIFT_PATH.read_text(encoding='utf-8'))
        drift_mutations = {
            'extra': lambda item: item['files'].append(
                dict(item['files'][0], path='config/amcl.yaml')),
            'different': lambda item: item['files'][0].update(
                path='config/amcl.yaml'),
            'missing': lambda item: item['files'].pop(),
            'hash_mismatch': lambda item: item['files'][0].update(
                current_sha256='0' * 64),
            'fake_expected_hash': lambda item: item['files'][0].update(
                expected_sha256='f' * 64),
            'wrong_disposition': lambda item: item['files'][0].update(
                recommended_disposition='accept_new_release'),
            'release_set_not_object': lambda item: item.update(
                release_set='not-an-object'),
        }
        with tempfile.TemporaryDirectory() as directory:
            for case, mutate in drift_mutations.items():
                with self.subTest(drift_binding=case):
                    payload = json.loads(json.dumps(source_drift))
                    mutate(payload)
                    path = Path(directory) / '{}.json'.format(case)
                    path.write_text(
                        json.dumps(payload, sort_keys=True) + '\n',
                        encoding='utf-8')
                    rejected = RUNNER._release_integrity_state(path)
                    self.assertFalse(
                        rejected['bridge_release_hash_binding']['eligible'])
                    self.assertTrue(
                        rejected['bridge_release_hash_binding']['errors'])
        fourth_drift = json.loads(json.dumps(sealed))
        fourth_record = next(
            item for item in fourth_drift['records'] if item['matches'])
        fourth_record['actual_sha256'] = '0' * 64
        fourth_record['matches'] = False
        fourth_drift['matching_files'] = 10
        fourth_drift['mismatching_files'] = 4
        fourth_drift['mismatch_paths'] = sorted(
            list(fourth_drift['mismatch_paths']) + [fourth_record['path']])
        fourth_binding = RUNNER._release_drift_file_binding(
            source_drift, True, sealed_state=fourth_drift)
        self.assertFalse(fourth_binding['eligible'])
        self.assertTrue(fourth_binding['errors'])
        missing = RUNNER.V1_ROOT / 'test' / 'test_missing_delivery_audit.py'
        with mock.patch.object(
                RUNNER, '_delivery_audit_test_paths',
                return_value=(missing,)):
            checks = RUNNER._run_v1_suites()
        self.assertEqual(len(checks), 1)
        self.assertEqual(checks[0]['status'], 'FAIL')
        self.assertEqual(
            checks[0]['name'], 'v1_delivery_audit_classification')
        self.assertEqual(
            checks[0]['missing_modules'], ['test_missing_delivery_audit.py'])

    def test_non_linux_complete_run_is_blocked_without_executing_checks(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'blocked.json'
            with mock.patch.object(
                    RUNNER, 'AUTHORITY_ROOT', Path(directory)), mock.patch.object(
                        RUNNER, '_is_authoritative_linux', return_value=False), mock.patch.object(
                        RUNNER, '_run') as run_mock:
                report, code = RUNNER.run_complete_matrix(target)
            self.assertEqual(code, 2)
            self.assertFalse(report['software_release_pass'])
            self.assertFalse(report['software_release_ready'])
            self.assertFalse(report['integrated_software_ready'])
            self.assertFalse(report['delivery_ready'])
            self.assertEqual(report['checks'], [])
            self.assertIn(
                'NON_AUTHORITATIVE_PLATFORM',
                {item['id'] for item in report['active_software_blockers']})
            run_mock.assert_not_called()
            written = json.loads(target.read_text(encoding='utf-8'))
            self.assertIn('Linux/POSIX', written['platform_blocker'])

    def test_report_creation_is_exclusive(self):
        stale_before = {
            Path(stale['path']): Path(stale['path']).read_bytes()
            for stale in RUNNER.SUPERSEDED_EVIDENCE_REPORTS}
        predecessor_before = {
            Path(entry['path']): Path(entry['path']).read_bytes()
            for entry in RUNNER.DIRECT_AUTHORITY_PREDECESSOR.values()}
        lineage_state = RUNNER._evidence_lineage()
        self.assertTrue(lineage_state['verified'])
        self.assertEqual(lineage_state['decision'], 'PASS')
        self.assertEqual(lineage_state['errors'], [])
        predecessor = lineage_state['direct_authority_predecessor']
        self.assertTrue(predecessor['binding_verified'])
        self.assertEqual(predecessor['decision'], 'PASS')
        self.assertEqual(predecessor['errors'], [])
        for row in (predecessor['report'], predecessor['index']):
            self.assertTrue(row['hash_matches'])
            self.assertTrue(row['bytes_match'])
            self.assertIsNone(row['read_error'])
            with self.assertRaises(ValueError):
                RUNNER._write_exclusive(
                    RUNNER.WORKSPACE_ROOT / row['path'],
                    {'forbidden': True})
        lineage = lineage_state['supersedes']
        self.assertEqual(len(lineage), 4)
        expected = {
            RUNNER._workspace_relative(stale['path']): (
                stale['sha256'], stale['reason'])
            for stale in RUNNER.SUPERSEDED_EVIDENCE_REPORTS}
        self.assertEqual({row['path'] for row in lineage}, set(expected))
        for row in lineage:
            self.assertEqual(
                row['lifecycle'],
                'STALE_SUPERSEDED_FOR_READINESS_DECISIONS')
            self.assertTrue(row['hash_matches'])
            self.assertEqual(
                (row['actual_sha256'], row['reason']), expected[row['path']])
            self.assertTrue(row['must_not_be_overwritten'])
            self.assertIsNone(row['read_error'])
            with self.assertRaises(ValueError):
                RUNNER._write_exclusive(
                    RUNNER.WORKSPACE_ROOT / row['path'],
                    {'forbidden': True})
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'evidence.json'
            RUNNER._write_exclusive(target, {'first': True})
            with self.assertRaises(FileExistsError):
                RUNNER._write_exclusive(target, {'second': True})
            self.assertEqual(
                json.loads(target.read_text(encoding='utf-8')), {'first': True})

            authority_root = Path(directory) / 'authority_success'
            authority_root.mkdir()
            with mock.patch.object(RUNNER, 'AUTHORITY_ROOT', authority_root):
                report_target = authority_root / 'candidate.json'
                report = RUNNER._base_report()
                index = RUNNER._write_report_bundle(report_target, report)
                claim_path = RUNNER._authority_claim_path()
                index_path = RUNNER._authority_index_path(report_target)
                candidate_text = report_target.read_text(encoding='utf-8')
                claim_text = claim_path.read_text(encoding='utf-8')
                written = json.loads(candidate_text)
                written_claim = json.loads(claim_text)
                written_index = json.loads(
                    index_path.read_text(encoding='utf-8'))
                candidate = written['evidence_lineage']['authority_candidate']
                self.assertEqual(
                    candidate['lifecycle'],
                    'NON_AUTHORITATIVE_PENDING_AUTHORITY_INDEX')
                self.assertFalse(candidate['is_current'])
                self.assertFalse(written['software_release_pass'])
                self.assertNotIn(
                    'CURRENT_AUTHORITATIVE_FOR_READINESS_DECISIONS',
                    candidate_text)
                self.assertNotIn('unique_authoritative_leaf', candidate_text)
                self.assertNotIn(
                    'CURRENT_AUTHORITATIVE_FOR_READINESS_DECISIONS',
                    claim_text)
                self.assertEqual(
                    written_claim['candidate']['sha256'],
                    RUNNER._sha256(report_target.read_bytes()))
                self.assertEqual(
                    written_claim['candidate']['bytes'],
                    len(report_target.read_bytes()))
                self.assertEqual(written_index, index)
                self.assertEqual(
                    written_index['selected_claim']['sha256'],
                    RUNNER._sha256(claim_path.read_bytes()))
                self.assertEqual(
                    written_index['current_authoritative']['sha256'],
                    RUNNER._sha256(report_target.read_bytes()))
                self.assertEqual(
                    written_index['current_authoritative']['bytes'],
                    len(report_target.read_bytes()))
                self.assertEqual(
                    written_index['current_authoritative']['lifecycle'],
                    'CURRENT_AUTHORITATIVE_FOR_READINESS_DECISIONS')
                self.assertTrue(
                    written_index['current_authoritative'][
                        'unique_authoritative_leaf'])
                self.assertEqual(
                    written_index['current_authoritative']['uniqueness_basis'],
                    'ATOMIC_O_EXCL_CLAIM_AND_FIXED_COMMIT_INDEX')
                predecessor_bundle = written_index[
                    'supersedes_predecessor_bundle']
                self.assertEqual(
                    predecessor_bundle['report']['lifecycle'],
                    'SUPERSEDED_PREDECESSOR_REPORT')
                self.assertEqual(
                    predecessor_bundle['index']['lifecycle'],
                    'SUPERSEDED_PREDECESSOR_INDEX')
                sibling = authority_root / 'parallel_leaf.json'
                with self.assertRaises(
                        RUNNER.AuthorityGenerationBlockedError):
                    RUNNER._write_report_bundle(
                        sibling, RUNNER._base_report())
                self.assertFalse(sibling.exists())

            concurrent_root = Path(directory) / 'authority_concurrent'
            concurrent_root.mkdir()
            barrier = threading.Barrier(3)
            claim_ready = threading.Event()
            release_winner = threading.Event()
            loser_done = threading.Event()
            results = []
            results_lock = threading.Lock()

            def checkpoint(stage):
                if stage == 'after_claim_publish':
                    claim_ready.set()
                    if not release_winner.wait(5):
                        raise AssertionError('winner checkpoint timed out')

            def worker(name):
                candidate_path = concurrent_root / '{}.json'.format(name)
                try:
                    barrier.wait(5)
                    result = RUNNER._write_report_bundle(
                        candidate_path, RUNNER._base_report())
                    outcome = ('success', name, result)
                except BaseException as error:  # test captures worker failures
                    outcome = ('error', name, error)
                    if isinstance(
                            error, RUNNER.AuthorityGenerationBlockedError):
                        loser_done.set()
                with results_lock:
                    results.append(outcome)

            with mock.patch.object(
                    RUNNER, 'AUTHORITY_ROOT', concurrent_root), mock.patch.object(
                        RUNNER, '_authority_fault', side_effect=checkpoint):
                threads = [
                    threading.Thread(target=worker, args=(name,))
                    for name in ('alpha', 'beta')]
                for thread in threads:
                    thread.start()
                barrier.wait(5)
                self.assertTrue(claim_ready.wait(5))
                self.assertTrue(loser_done.wait(5))
                release_winner.set()
                for thread in threads:
                    thread.join(5)
                    self.assertFalse(thread.is_alive())
                self.assertEqual(
                    [item[0] for item in results].count('success'), 1)
                self.assertEqual(
                    [item[0] for item in results].count('error'), 1)
                loser = next(item for item in results if item[0] == 'error')
                self.assertIsInstance(
                    loser[2], RUNNER.AuthorityGenerationBlockedError)
                self.assertEqual(
                    sum((concurrent_root / '{}.json'.format(name)).exists()
                        for name in ('alpha', 'beta')), 1)
                self.assertTrue(RUNNER._authority_claim_path().exists())
                self.assertTrue(
                    RUNNER._authority_index_path(None).exists())

            for stage, expect_candidate, expect_index in (
                    ('after_claim_publish', False, False),
                    ('after_candidate_publish', True, False),
                    ('before_index_link', True, False),
                    ('after_index_link', True, True)):
                with self.subTest(authority_fault=stage):
                    fault_root = Path(directory) / 'fault_{}'.format(stage)
                    fault_root.mkdir()
                    fault_target = fault_root / 'candidate.json'

                    def fail_at(point, selected=stage):
                        if point == selected:
                            raise RuntimeError('fault at {}'.format(point))

                    with mock.patch.object(
                            RUNNER, 'AUTHORITY_ROOT', fault_root), mock.patch.object(
                                RUNNER, '_authority_fault', side_effect=fail_at):
                        with self.assertRaises(RuntimeError):
                            RUNNER._write_report_bundle(
                                fault_target, RUNNER._base_report())
                        fault_claim = RUNNER._authority_claim_path()
                        fault_index = RUNNER._authority_index_path(None)
                    self.assertTrue(fault_claim.exists())
                    self.assertEqual(fault_target.exists(), expect_candidate)
                    self.assertEqual(fault_index.exists(), expect_index)
                    if fault_target.exists():
                        fault_text = fault_target.read_text(encoding='utf-8')
                        self.assertNotIn(
                            'CURRENT_AUTHORITATIVE_FOR_READINESS_DECISIONS',
                            fault_text)
                        self.assertNotIn(
                            'unique_authoritative_leaf', fault_text)
                        self.assertFalse(json.loads(
                            fault_text)['software_release_pass'])
                    contender = fault_root / 'contender.json'
                    with mock.patch.object(
                            RUNNER, 'AUTHORITY_ROOT', fault_root):
                        with self.assertRaises(
                                RUNNER.AuthorityGenerationBlockedError):
                            RUNNER._write_report_bundle(
                                contender, RUNNER._base_report())
                    self.assertFalse(contender.exists())

            self_target = Path(directory) / 'self_test.json'
            self_report = RUNNER._base_report()
            RUNNER._mark_self_test_non_authoritative(
                self_report, self_target)
            RUNNER._write_exclusive(self_target, self_report)
            self_written = json.loads(
                self_target.read_text(encoding='utf-8'))
            self.assertNotIn(
                'current_authoritative', self_written['evidence_lineage'])
            self.assertEqual(
                self_written['evidence_lineage']['self_test_artifact'][
                    'lifecycle'],
                'NON_AUTHORITATIVE_SELF_TEST')
            self.assertFalse(
                self_written['evidence_lineage']['self_test_artifact'][
                    'authority_index_created'])

            reserved = Path(directory) / 'reserved.json'
            reserved_entry = ({
                'path': reserved,
                'sha256': '0' * 64,
                'reason': 'reserved test path'},)
            with mock.patch.object(
                    RUNNER, 'SUPERSEDED_EVIDENCE_REPORTS', reserved_entry):
                with self.assertRaises(ValueError):
                    RUNNER._write_exclusive(reserved, {'forbidden': True})
            self.assertFalse(reserved.exists())

            for case, create_file, expected_hash in (
                    ('missing', False, '0' * 64),
                    ('mismatch', True, '0' * 64)):
                with self.subTest(lineage_failure=case):
                    candidate = Path(directory) / '{}.json'.format(case)
                    if create_file:
                        candidate.write_text('different', encoding='utf-8')
                    entry = ({
                        'path': candidate,
                        'sha256': expected_hash,
                        'reason': '{} evidence'.format(case)},)
                    with mock.patch.object(
                            RUNNER, 'SUPERSEDED_EVIDENCE_REPORTS', entry), mock.patch.object(
                                RUNNER, 'EXPECTED_SUPERSEDED_EVIDENCE_COUNT', 1):
                        failed_lineage = RUNNER._evidence_lineage()
                    self.assertFalse(failed_lineage['verified'])
                    self.assertEqual(failed_lineage['decision'], 'BLOCKED')

            blocked_lineage = RUNNER._evidence_lineage()
            blocked_lineage['verified'] = False
            blocked_lineage['decision'] = 'BLOCKED'
            blocked_lineage['errors'] = ['precommit lineage mismatch']
            blocked_directory = Path(directory) / 'precommit'
            blocked_directory.mkdir()
            blocked_target = blocked_directory / 'precommit_blocked.json'
            blocked_report = RUNNER._base_report()
            with mock.patch.object(
                    RUNNER, 'AUTHORITY_ROOT', blocked_directory), mock.patch.object(
                        RUNNER, '_evidence_lineage', return_value=blocked_lineage):
                with self.assertRaises(
                        RUNNER.AuthorityGenerationBlockedError):
                    RUNNER._write_report_bundle(
                        blocked_target, blocked_report)
                self.assertFalse(RUNNER._authority_claim_path().exists())
                self.assertFalse(
                    RUNNER._authority_index_path(None).exists())
            self.assertFalse(blocked_target.exists())
        for path, before in stale_before.items():
            self.assertEqual(path.read_bytes(), before)
        for path, before in predecessor_before.items():
            self.assertEqual(path.read_bytes(), before)

    def test_software_pass_never_implies_field_or_delivery_ready(self):
        passing = {
            'name': 'mock', 'status': 'PASS', 'expected_count': None,
            'observed_count': None}
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'pass.json'
            with mock.patch.object(
                    RUNNER, 'AUTHORITY_ROOT', Path(directory)), mock.patch.object(
                        RUNNER, '_is_authoritative_linux', return_value=True), mock.patch.object(
                        RUNNER, '_matrix', return_value=(('mock', (), WORKSPACE_ROOT,
                                                         None, None, None),)), mock.patch.object(
                            RUNNER, '_run', return_value=passing), mock.patch.object(
                                RUNNER, '_run_v1_suites', return_value=(passing,)), mock.patch.object(
                                    RUNNER, '_run_py_compile', return_value=passing), mock.patch.object(
                                        RUNNER, '_run_whitespace', return_value=passing), mock.patch.object(
                                            RUNNER, '_vendor_provenance_state',
                                            return_value=self._verified_vendor()), mock.patch.object(
                                                RUNNER, '_release_integrity_state',
                                                return_value=self._clear_release()):
                report, code = RUNNER.run_complete_matrix(target)
            self.assertEqual(code, 0)
            self.assertFalse(report['software_release_pass'])
            self.assertFalse(report['software_release_ready'])
            self.assertFalse(report['integrated_software_ready'])
            authority = report['authority_commit_result']
            self.assertTrue(authority['software_release_pass'])
            self.assertTrue(authority['software_release_ready'])
            self.assertTrue(authority['integrated_software_ready'])
            self.assertEqual(report['active_software_blockers'], [])
            integrated = report['integrated_combined_deployment']
            self.assertEqual(integrated['closure_status'], 'PASS')
            self.assertEqual(integrated['software_blockers'], [])
            self.assertEqual(
                {item['id'] for item in integrated[
                    'resolved_software_blockers']},
                {item['id'] for item in RUNNER.INTEGRATED_SOFTWARE_CLOSURES})
            self.assertFalse(report['field_acceptance_complete'])
            self.assertFalse(report['field_evidence_complete'])
            self.assertFalse(report['delivery_ready'])
            for item in report['field_acceptance'].values():
                self.assertEqual(item['status'], 'NOT_RUN')
                self.assertTrue(item['template_only'])
                self.assertFalse(item['real_machine_evidence'])

    def test_integrated_closures_fail_closed_and_do_not_imply_field_ready(self):
        closures = RUNNER._integrated_closure_checks()
        self.assertEqual(
            {item['name'] for item in closures}, {
                'integrated_topology_verifier_contract',
                'integrated_verifier_install_contract'})
        self.assertTrue(all(item['status'] == 'PASS' for item in closures))
        report = RUNNER._base_report()
        self.assertFalse(report['integrated_software_ready'])
        self.assertEqual(
            report['integrated_combined_deployment']['execution_status'],
            'BLOCKED')
        with mock.patch.object(
                RUNNER, '_integrated_topology_contract', return_value={
                    'name': 'integrated_topology_verifier_contract',
                    'status': 'FAIL', 'errors': ['peer contract missing']}):
            failed = RUNNER._integrated_closure_checks()
        self.assertEqual(failed[0]['status'], 'FAIL')
        with mock.patch.object(
                RUNNER, '_integrated_install_contract',
                side_effect=FileNotFoundError('missing installed module')):
            failed = RUNNER._integrated_closure_checks()
        self.assertEqual(failed[1]['status'], 'FAIL')
        self.assertIn('FileNotFoundError', failed[1]['errors'][0])

        exact = list(self._exact_closures())
        passing = {'name': 'profile_static', 'status': 'PASS'}

        with self.subTest('release drift is independent of exact closures'):
            report = RUNNER._base_report()
            report['checks'] = exact + [passing]
            drift = self._clear_release()
            drift.update({
                'artifact_status':
                'BLOCKED_PIN_UPDATE_PROHIBITED_PENDING_ALL_GREEN',
                'matching_files': 11,
                'mismatching_files': 3,
                'drift_active': True,
                'decision': 'BLOCKED',
            })
            RUNNER._apply_blocker_attribution(
                report, self._verified_vendor(), drift)
            integrated = report['integrated_combined_deployment']
            self.assertEqual(integrated['closure_status'], 'PASS')
            self.assertEqual(integrated['software_blockers'], [])
            self.assertEqual(len(integrated['resolved_software_blockers']), 2)
            self.assertFalse(report['software_release_pass'])
            self.assertEqual(
                {item['id'] for item in report['active_software_blockers']},
                {'V1_FROZEN_RELEASE_HASH_DRIFT'})

        with self.subTest('one unrelated check failure is attributed exactly'):
            report = RUNNER._base_report()
            failed_profile = {'name': 'profile_static', 'status': 'FAIL'}
            report['checks'] = exact + [failed_profile]
            RUNNER._apply_blocker_attribution(
                report, self._verified_vendor(), self._clear_release())
            integrated = report['integrated_combined_deployment']
            self.assertEqual(integrated['closure_status'], 'PASS')
            self.assertEqual(integrated['software_blockers'], [])
            self.assertFalse(report['software_release_pass'])
            self.assertEqual(
                [item['id'] for item in report['active_software_blockers']],
                ['OFFLINE_CHECK_FAILED_PROFILE_STATIC'])

        with self.subTest('secure validator is release integrity'):
            report = RUNNER._base_report()
            failed_validator = {
                'name': 'secure_release_validator', 'status': 'FAIL',
                'expected_count': 14, 'observed_count': 11}
            report['checks'] = exact + [failed_validator]
            RUNNER._apply_blocker_attribution(
                report, self._verified_vendor(), self._clear_release())
            blocker = report['active_software_blockers'][0]
            self.assertEqual(
                blocker['id'], 'SECURE_RELEASE_VALIDATOR_FAILED')
            self.assertEqual(blocker['category'], 'release_integrity')
            self.assertFalse(report['software_release_pass'])

        allowed = next(iter(
            RUNNER.BRIDGE_RELEASE_HASH_FAILURE_ALLOWLIST))
        bound_drift = RUNNER._release_integrity_state()
        with self.subTest('exact bridge pin-only failure is release integrity'):
            report = RUNNER._base_report()
            report['checks'] = exact + [self._bridge_failure([allowed])]
            RUNNER._apply_blocker_attribution(
                report, self._verified_vendor(), bound_drift)
            bridge = next(
                item for item in report['active_software_blockers']
                if item.get('check') == 'bridge_pytest')
            self.assertEqual(
                bridge['id'],
                'BRIDGE_FROZEN_RELEASE_HASH_ASSERTION_FAILED')
            self.assertEqual(bridge['category'], 'release_integrity')
            self.assertEqual(
                bridge['attribution'],
                'EXACT_FAILED_NODE_ALLOWLIST_AND_THREE_FILE_DRIFT_BINDING')

        bridge_negative_cases = {
            'extra_node': self._bridge_failure([
                allowed, 'test/test_other.py::test_unrelated']),
            'different_node': self._bridge_failure([
                'test/test_other.py::test_unrelated']),
            'missing_node': self._bridge_failure([]),
            'malformed_line': self._bridge_failure(
                [allowed], parse_status='MALFORMED_FAILURE_LINES'),
            'wrong_returncode': self._bridge_failure(
                [allowed], returncode=2),
            'wrong_count': self._bridge_failure(
                [allowed], observed_count=120),
            'execution_error': self._bridge_failure(
                [allowed], execution_error='OSError'),
        }
        for case, bridge_check in bridge_negative_cases.items():
            with self.subTest(bridge_failure=case):
                report = RUNNER._base_report()
                report['checks'] = exact + [bridge_check]
                RUNNER._apply_blocker_attribution(
                    report, self._verified_vendor(),
                    RUNNER._release_integrity_state())
                bridge = next(
                    item for item in report['active_software_blockers']
                    if item.get('check') == 'bridge_pytest')
                self.assertEqual(bridge['category'], 'offline_regression')
                self.assertEqual(
                    bridge['id'], 'OFFLINE_CHECK_FAILED_BRIDGE_PYTEST')

        with self.subTest('exact node without drift binding is generic'):
            report = RUNNER._base_report()
            report['checks'] = exact + [self._bridge_failure([allowed])]
            unbound = RUNNER._release_integrity_state()
            unbound['bridge_release_hash_binding']['eligible'] = False
            RUNNER._apply_blocker_attribution(
                report, self._verified_vendor(), unbound)
            bridge = next(
                item for item in report['active_software_blockers']
                if item.get('check') == 'bridge_pytest')
            self.assertEqual(bridge['category'], 'offline_regression')

        with self.subTest('closure requires the exact assertion denominator'):
            report = RUNNER._base_report()
            wrong_topology = dict(exact[0], assertion_count=7)
            report['checks'] = [wrong_topology, exact[1], passing]
            RUNNER._apply_blocker_attribution(
                report, self._verified_vendor(), self._clear_release())
            integrated = report['integrated_combined_deployment']
            self.assertEqual(integrated['closure_status'], 'BLOCKED')
            self.assertEqual(
                [item['id'] for item in integrated['software_blockers']],
                ['ROS1_TOPOLOGY_VERIFIER_NODE_NAME_COLLISION'])
            self.assertEqual(
                [item['id'] for item in integrated[
                    'resolved_software_blockers']],
                ['INSTALLED_RUNNER_WORKSPACE_SCRIPT_PATH_MISSING'])

    def test_source_contains_no_ros_or_motion_api(self):
        source = RUNNER_PATH.read_text(encoding='utf-8')
        for forbidden in (
                'import rospy', 'roslaunch', 'roscore', 'Publisher(',
                'ServiceProxy(', 'SimpleActionClient(', 'Twist(', '/cmd_vel',
                'send_goal('):
            self.assertNotIn(forbidden, source)


if __name__ == '__main__':
    unittest.main()

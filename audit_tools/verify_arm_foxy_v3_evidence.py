"""Verify the preserved local Foxy v3 evidence without external access."""

import hashlib
import tarfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_ROOT = (
    PROJECT_ROOT / 'docs' / 'evidence' / 'arm_foxy_dryrun_20260813_v3')
SUMMARY_PATH = (
    EVIDENCE_ROOT / 'arm_foxy_dryrun_20260813_v3_summary.log')
MANIFEST_PATH = EVIDENCE_ROOT / 'SHA256SUMS.txt'
README_PATH = EVIDENCE_ROOT / 'README.md'
BUNDLE_PATH = PROJECT_ROOT / 'arm_foxy_dryrun_20260813_v3.tar.gz'
RUNNER_PATH = PROJECT_ROOT / 'scripts' / 'run_uploaded_arm_foxy_dry_run.sh'
VERIFIER_PATH = (
    PROJECT_ROOT / 'scripts' / 'verify_arm_gateway_foxy_dry_run.sh')


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _require(condition, detail):
    if not condition:
        raise RuntimeError(detail)
    print('PASS ' + detail)


def main():
    readme = README_PATH.read_text(encoding='utf-8')
    summary = SUMMARY_PATH.read_text(encoding='utf-8')
    manifest_lines = [
        line for line in MANIFEST_PATH.read_text(
            encoding='utf-8').splitlines()
        if line.strip()
    ]

    _require(
        'ERROR: required command missing: ros2' in summary,
        'summary records ros2 missing before build')
    _require(
        'TARGET_V3_RUN_EXIT status=2' in summary,
        'summary records runner status 2')
    _require(
        'TARGET_FOXY_ARM_DRY_RUN_FAIL status=2' in summary,
        'summary records final failure status 2')
    _require(
        'FOXY_ARM_DRY_RUN_START' not in summary,
        'summary has no build-stage start marker')
    _require(
        'TARGET_FOXY_ARM_DRY_RUN_PASS' not in summary,
        'summary has no pass claim')
    _require(
        'build/test/smoke: not entered' in readme
        and 'v3 remains `FAIL-before-build`' in readme,
        'README fixes v3 at FAIL-before-build')
    _require(
        '- rerun permitted: no' in readme,
        'README forbids a v3 rerun')
    _require(
        'task-specific residual processes: `UNKNOWN/BLOCKED`' in readme,
        'README keeps residual status UNKNOWN/BLOCKED')
    _require(
        'runner deletion and broad task-process zero-residual status remain'
        in readme,
        'README keeps runner deletion unproved')
    _require(
        'No further target connection is' in readme,
        'README prohibits target reconnection for evidence')
    _require(
        'handoff notes reported' in readme
        and 'must not be treated as\nrelease evidence' in readme
        and 'read-only shell proved' not in readme,
        'post-source observation is handoff-only')

    _require(len(manifest_lines) == 12, 'manifest has 12 entries')
    for line in manifest_lines:
        expected, relative = line.split('  ', 1)
        path = EVIDENCE_ROOT / relative
        _require(path.is_file(), 'manifest file exists: ' + relative)
        _require(
            _sha256(path) == expected,
            'manifest hash matches: ' + relative)

    _require(
        _sha256(SUMMARY_PATH) in readme,
        'README records the summary hash')
    _require(
        _sha256(BUNDLE_PATH) in readme,
        'README records the bundle hash')
    _require(
        _sha256(RUNNER_PATH) in readme,
        'README records the runner hash')

    with tarfile.open(BUNDLE_PATH, 'r:gz') as archive:
        archived = archive.extractfile(
            'scripts/verify_arm_gateway_foxy_dry_run.sh')
        _require(archived is not None, 'bundle contains the verifier')
        archived_verifier = archived.read().decode('utf-8')
    current_verifier = VERIFIER_PATH.read_text(encoding='utf-8')
    command_loop = 'for required_command in awk colcon grep ps python3 ros2'
    _require(
        archived_verifier.index(command_loop)
        < archived_verifier.index('source "$ros_setup"'),
        'archived verifier checked commands before sourcing Foxy')
    _require(
        current_verifier.index('source "$ros_setup"')
        < current_verifier.index(command_loop),
        'current verifier sources Foxy before command checks')

    print(
        'ARM_FOXY_V3_EVIDENCE PASS manifest_entries={} '
        'result=FAIL-before-build residual=UNKNOWN/BLOCKED'.format(
            len(manifest_lines)))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

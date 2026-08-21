#!/usr/bin/env python3
"""Create one exclusive canonical interfaces/perception build-input manifest."""

import argparse
import hashlib
import json
import os
from pathlib import Path


PACKAGE_ROOTS = (
    ('interfaces', 'src/limo_cleanup_interfaces'),
    ('perception', 'src/limo_cleanup_perception'),
)
EXCLUDED_PARTS = {'__pycache__', '.pytest_cache'}
EXCLUDED_SUFFIXES = {'.pyc', '.pyo'}


def discover_files(root):
    """Return every regular build/test/install input in the two packages."""
    files = {}
    for package, relative_root in PACKAGE_ROOTS:
        package_root = (root / relative_root).resolve(strict=True)
        for marker in ('COLCON_IGNORE', 'AMENT_IGNORE', 'CATKIN_IGNORE'):
            if (package_root / marker).exists():
                raise ValueError('package ignore marker is forbidden: ' + marker)
        for path in sorted(package_root.rglob('*')):
            relative = path.relative_to(package_root)
            if (path.is_symlink()
                    or not path.is_file()
                    or set(relative.parts).intersection(EXCLUDED_PARTS)
                    or path.suffix.lower() in EXCLUDED_SUFFIXES):
                continue
            workspace_relative = path.relative_to(root).as_posix()
            files[package + ':' + relative.as_posix()] = workspace_relative
    if not files:
        raise ValueError('no package build inputs were discovered')
    return files


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--release-id', required=True)
    parser.add_argument('--generated-at-unix-sec', type=float, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit('output path must not already exist')
    root = args.workspace.resolve(strict=True)
    files = discover_files(root)
    entries = []
    for name in sorted(files):
        path = (root / files[name]).resolve(strict=True)
        if not path.is_file():
            raise SystemExit('source path is not a regular file: ' + str(path))
        entries.append({
            'name': name,
            'path': files[name],
            'size_bytes': path.stat().st_size,
            'sha256': sha256_file(path),
        })
    source_set = [{
        key: item[key] for key in ('name', 'size_bytes', 'sha256')}
        for item in entries]
    canonical = json.dumps(
        source_set, ensure_ascii=False, sort_keys=True,
        separators=(',', ':')).encode('utf-8')
    report = {
        'schema_version': 1,
        'release_id': args.release_id,
        'generated_at_unix_sec': args.generated_at_unix_sec,
        'read_only': True,
        'authorizes_motion': False,
        'publishes_ros_messages': False,
        'scope': 'complete_interfaces_and_perception_package_inputs',
        'package_roots': [value for _, value in PACKAGE_ROOTS],
        'required_source_names': sorted(files),
        'entries': entries,
        'source_set_sha256': hashlib.sha256(canonical).hexdigest(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

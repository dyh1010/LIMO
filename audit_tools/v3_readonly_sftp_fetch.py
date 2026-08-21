#!/usr/bin/env python3
"""Fetch an explicit remote file allowlist for V3 provenance, read-only."""

import argparse
import base64
import hashlib
import json
import os
import pathlib
import stat
import sys
from datetime import datetime, timezone

import paramiko


SCHEMA = 'limo_v3_readonly_sftp_capture/v1'
PASSWORD_ENV = 'V3_SSH_PASSWORD'
BINARY_FLAG = getattr(os, 'O_BINARY', 0)


def _fingerprint(key):
    digest = hashlib.sha256(key.asbytes()).digest()
    return 'SHA256:' + base64.b64encode(digest).decode('ascii').rstrip('=')


class ExactFingerprintPolicy(paramiko.MissingHostKeyPolicy):
    """Accept only the exact independently scanned server-key fingerprint."""

    def __init__(self, expected):
        self.expected = expected

    def missing_host_key(self, client, hostname, key):
        actual = _fingerprint(key)
        if actual != self.expected:
            raise paramiko.SSHException(
                'server host-key fingerprint mismatch: expected {}, got {}'.format(
                    self.expected, actual))


def _mode_record(value):
    return {
        'octal': format(stat.S_IMODE(value), '04o'),
        'regular_file': stat.S_ISREG(value),
        'symlink': stat.S_ISLNK(value),
    }


def _write_exclusive(path, payload, mode=0o600):
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | BINARY_FLAG
    descriptor = os.open(str(path), flags, mode)
    try:
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _download_one(sftp, remote_path, local_path):
    lstat_result = sftp.lstat(remote_path)
    canonical_path = sftp.normalize(remote_path)
    stat_result = sftp.stat(remote_path)
    link_target = None
    if stat.S_ISLNK(lstat_result.st_mode):
        link_target = sftp.readlink(remote_path)
    digest = hashlib.sha256()
    byte_count = 0
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | BINARY_FLAG
    descriptor = os.open(str(local_path), flags, 0o600)
    try:
        with sftp.open(remote_path, 'rb') as remote_file:
            while True:
                chunk = remote_file.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
                byte_count += len(chunk)
                view = memoryview(chunk)
                while view:
                    written = os.write(descriptor, view)
                    view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    if byte_count != stat_result.st_size:
        raise ValueError(
            'remote size changed during read: {} expected {}, got {}'.format(
                remote_path, stat_result.st_size, byte_count))
    local_size = local_path.stat().st_size
    local_sha256 = hashlib.sha256(local_path.read_bytes()).hexdigest()
    if local_size != byte_count or local_sha256 != digest.hexdigest():
        raise ValueError(
            'local capture identity mismatch: {} remote {}/{} local {}/{}'.format(
                remote_path, byte_count, digest.hexdigest(),
                local_size, local_sha256))
    return {
        'remote_path': remote_path,
        'canonical_path': canonical_path,
        'symlink_target': link_target,
        'lstat': {
            'size_bytes': lstat_result.st_size,
            'mtime_epoch': int(lstat_result.st_mtime),
            'mode': _mode_record(lstat_result.st_mode),
        },
        'stat': {
            'size_bytes': stat_result.st_size,
            'mtime_epoch': int(stat_result.st_mtime),
            'mode': _mode_record(stat_result.st_mode),
        },
        'captured_bytes': byte_count,
        'sha256': digest.hexdigest(),
        'local_identity': {
            'size_bytes': local_size,
            'sha256': local_sha256,
            'matches_remote_capture': True,
        },
        'local_file': local_path.name,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', required=True)
    parser.add_argument('--user', required=True)
    parser.add_argument('--host-key-sha256', required=True)
    parser.add_argument('--remote-path', action='append', required=True)
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--timeout', type=float, default=20.0)
    args = parser.parse_args()

    password = os.environ.pop(PASSWORD_ENV, None)
    if not password:
        raise SystemExit('missing in-memory {}'.format(PASSWORD_ENV))
    output_dir = pathlib.Path(args.output_dir)
    if not output_dir.is_absolute():
        raise SystemExit('--output-dir must be absolute')
    remote_paths = tuple(args.remote_path)
    if len(remote_paths) != len(set(remote_paths)):
        raise SystemExit('duplicate --remote-path is forbidden')
    if any(not pathlib.PurePosixPath(path).is_absolute()
           for path in remote_paths):
        raise SystemExit('every --remote-path must be an absolute POSIX path')
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(
        ExactFingerprintPolicy(args.host_key_sha256))
    try:
        client.connect(
            hostname=args.host,
            username=args.user,
            password=password,
            look_for_keys=False,
            allow_agent=False,
            timeout=args.timeout,
            auth_timeout=args.timeout,
            banner_timeout=args.timeout,
        )
        negotiated_key = client.get_transport().get_remote_server_key()
        negotiated_fingerprint = _fingerprint(negotiated_key)
        if negotiated_fingerprint != args.host_key_sha256:
            raise paramiko.SSHException(
                'negotiated host-key fingerprint mismatch: expected {}, '
                'got {}'.format(
                    args.host_key_sha256, negotiated_fingerprint))
        output_dir.mkdir(mode=0o700, parents=False, exist_ok=False)
        rows = []
        with client.open_sftp() as sftp:
            for index, remote_path in enumerate(remote_paths):
                basename = pathlib.PurePosixPath(remote_path).name
                local_name = 'artifact_{:02d}_{}'.format(index, basename)
                rows.append(_download_one(
                    sftp, remote_path, output_dir / local_name))
        manifest = {
            'schema': SCHEMA,
            'captured_utc': datetime.now(timezone.utc).isoformat(),
            'transport': 'SFTP_READ_ONLY_EXPLICIT_ALLOWLIST',
            'host': args.host,
            'user': args.user,
            'server_key': {
                'algorithm': negotiated_key.get_name(),
                'sha256': negotiated_fingerprint,
                'out_of_band_verified': False,
                'verification_note': (
                    'Exact first-seen fingerprint from the immediately preceding '
                    'read-only ssh-keyscan; user supplied the host address.'),
            },
            'remote_command_executed': False,
            'ros_graph_queried': False,
            'hardware_accessed': False,
            'files': rows,
        }
        encoded = (json.dumps(
            manifest, indent=2, sort_keys=True) + '\n').encode('utf-8')
        manifest_path = output_dir / 'capture_manifest.json'
        _write_exclusive(manifest_path, encoded)
        print(json.dumps({
            'manifest_path': str(manifest_path),
            'file_count': len(rows),
            'server_key_sha256': negotiated_fingerprint,
            'status': 'PASS_READ_ONLY_CAPTURE',
        }, sort_keys=True))
        return 0
    finally:
        client.close()


if __name__ == '__main__':
    raise SystemExit(main())

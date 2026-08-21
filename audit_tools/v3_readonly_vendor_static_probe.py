#!/usr/bin/env python3
"""Run fixed, non-starting ROS1 vendor provenance probes over SSH."""

import argparse
import base64
import hashlib
import json
import os
import pathlib
import sys
from datetime import datetime, timezone

import paramiko


SCHEMA = 'limo_v3_readonly_vendor_static_probe/v1'
PASSWORD_ENV = 'V3_SSH_PASSWORD'
BINARY_FLAG = getattr(os, 'O_BINARY', 0)
COMMON = """set -e
. /opt/ros/noetic/setup.bash
. /home/agilex/agilex_ws/devel/setup.bash
export ROS_MASTER_URI=http://127.0.0.1:1
export ROS_IP=127.0.0.1
"""
LAUNCH = (
    'limo_bringup limo_start.launch '
    'port_name:=ttyTHS0 use_mcnamu:=false pub_odom_tf:=true')
PROFILES = {
    'identity': """set -e
printf 'USER=%s\\n' "$(id -un)"
printf 'HOSTNAME=%s\\n' "$(hostname)"
uname -srmo
if [ -r /etc/os-release ]; then
  . /etc/os-release
  printf 'OS=%s %s\\n' "$ID" "$VERSION_ID"
fi
if [ -r /opt/ros/noetic/setup.bash ]; then
  printf 'NOETIC_SETUP=PRESENT\\n'
else
  printf 'NOETIC_SETUP=MISSING\\n'
  exit 3
fi
""",
    'package_resolution': COMMON + """printf 'ROS_DISTRO=%s\\n' "${ROS_DISTRO:-}"
printf 'ROS_VERSION=%s\\n' "${ROS_VERSION:-}"
printf 'ROS_PACKAGE_PATH=%s\\n' "${ROS_PACKAGE_PATH:-}"
for pkg in limo_bringup limo_base ydlidar_ros_driver tf; do
  p="$(rospack find "$pkg")"
  printf 'PACKAGE[%s]=%s\\n' "$pkg" "$p"
done
python3 - <<'PY'
import json
from roslib.packages import find_node
print('FIND_NODE=' + json.dumps(
    find_node('tf', 'static_transform_publisher'), sort_keys=True))
PY
""",
    'roslaunch_files': COMMON + 'roslaunch --files ' + LAUNCH + '\n',
    'roslaunch_nodes': COMMON + 'roslaunch --nodes ' + LAUNCH + '\n',
    'roslaunch_dump_params': (
        COMMON + 'roslaunch --dump-params ' + LAUNCH + '\n'),
}


def _fingerprint(key):
    digest = hashlib.sha256(key.asbytes()).digest()
    return 'SHA256:' + base64.b64encode(digest).decode('ascii').rstrip('=')


class ExactFingerprintPolicy(paramiko.MissingHostKeyPolicy):

    def __init__(self, expected):
        self.expected = expected

    def missing_host_key(self, client, hostname, key):
        actual = _fingerprint(key)
        if actual != self.expected:
            raise paramiko.SSHException(
                'server host-key fingerprint mismatch: expected {}, got {}'.format(
                    self.expected, actual))


def _write_exclusive(path, payload):
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | BINARY_FLAG
    descriptor = os.open(str(path), flags, 0o600)
    try:
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    written = path.read_bytes()
    if written != payload:
        raise ValueError('exclusive output bytes changed after write')
    return {
        'path': path.name,
        'bytes': len(written),
        'sha256': hashlib.sha256(written).hexdigest(),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', required=True)
    parser.add_argument('--user', required=True)
    parser.add_argument('--host-key-sha256', required=True)
    parser.add_argument('--profile', action='append', required=True,
                        choices=sorted(PROFILES))
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--timeout', type=float, default=30.0)
    args = parser.parse_args()

    password = os.environ.pop(PASSWORD_ENV, None)
    if not password:
        raise SystemExit('missing in-memory {}'.format(PASSWORD_ENV))
    if len(args.profile) != len(set(args.profile)):
        raise SystemExit('duplicate --profile is forbidden')
    output_dir = pathlib.Path(args.output_dir)
    if not output_dir.is_absolute():
        raise SystemExit('--output-dir must be absolute')

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
        key = client.get_transport().get_remote_server_key()
        actual_fingerprint = _fingerprint(key)
        if actual_fingerprint != args.host_key_sha256:
            raise paramiko.SSHException(
                'negotiated host-key fingerprint mismatch: expected {}, '
                'got {}'.format(args.host_key_sha256, actual_fingerprint))
        output_dir.mkdir(mode=0o700, parents=False, exist_ok=False)
        results = []
        for profile in args.profile:
            command = PROFILES[profile]
            stdin, stdout, stderr = client.exec_command(
                command, timeout=args.timeout)
            stdin.close()
            stdout_bytes = stdout.read()
            stderr_bytes = stderr.read()
            return_code = stdout.channel.recv_exit_status()
            stdout_identity = _write_exclusive(
                output_dir / '{}.stdout'.format(profile), stdout_bytes)
            stderr_identity = _write_exclusive(
                output_dir / '{}.stderr'.format(profile), stderr_bytes)
            results.append({
                'profile': profile,
                'command': command,
                'return_code': return_code,
                'stdout': stdout_identity,
                'stderr': stderr_identity,
                'status': 'PASS' if return_code == 0 else 'FAIL',
            })
        manifest = {
            'schema': SCHEMA,
            'captured_utc': datetime.now(timezone.utc).isoformat(),
            'host': args.host,
            'user': args.user,
            'server_key': {
                'algorithm': key.get_name(),
                'sha256': actual_fingerprint,
                'out_of_band_verified': False,
            },
            'scope': 'FIXED_NONSTARTING_ROS1_STATIC_PROFILES',
            'ros_graph_queried': False,
            'hardware_accessed': False,
            'profiles': results,
        }
        manifest_bytes = (json.dumps(
            manifest, indent=2, sort_keys=True) + '\n').encode('utf-8')
        manifest_identity = _write_exclusive(
            output_dir / 'probe_manifest.json', manifest_bytes)
        failed = [row['profile'] for row in results
                  if row['return_code'] != 0]
        print(json.dumps({
            'status': 'PASS' if not failed else 'FAIL',
            'failed_profiles': failed,
            'manifest': manifest_identity,
        }, sort_keys=True))
        return 0 if not failed else 1
    finally:
        client.close()


if __name__ == '__main__':
    raise SystemExit(main())

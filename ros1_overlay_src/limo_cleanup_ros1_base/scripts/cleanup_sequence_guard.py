#!/usr/bin/env python3
"""Atomically enforce the base shutdown sequence for the shell runner."""

import argparse
import os
from pathlib import Path
import tempfile

from limo_cleanup_ros1_base.cleanup_sequence import next_cleanup_state


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--state-file', required=True)
    parser.add_argument('--event', required=True)
    arguments = parser.parse_args()
    path = Path(arguments.state_file)
    current = path.read_text(encoding='ascii').strip() if path.exists() else 'running'
    try:
        next_state = next_cleanup_state(current, arguments.event)
    except RuntimeError as error:
        print('CLEANUP_SEQUENCE_BLOCKED: {}'.format(error))
        return 1
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=path.name + '.', suffix='.tmp', dir=str(path.parent))
    try:
        with os.fdopen(descriptor, 'w', encoding='ascii') as stream:
            stream.write(next_state + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, str(path))
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    print('CLEANUP_SEQUENCE_STATE={}'.format(next_state))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

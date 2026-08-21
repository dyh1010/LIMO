"""Durable, hardware-free evidence journal for a future arm field runner."""

import json
import math
import os
import time


SCHEMA = 'limo_arm_motion_journal/v1'
SAMPLE_SCHEMA = 'limo_arm_post_send_sample/v1'


def _exact_finite_number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _write_all(descriptor, data):
    offset = 0
    while offset < len(data):
        written = os.write(descriptor, data[offset:])
        if written <= 0:
            raise OSError('journal write made no progress')
        offset += written


class DurableMotionJournal:
    """Exclusive JSONL journal; every accepted record is fsynced immediately."""

    def __init__(self, path, motion_id, authorization):
        if type(path) is not str or not path:
            raise ValueError('journal path must be a non-empty string')
        if type(motion_id) is not str or not motion_id:
            raise ValueError('motion_id must be a non-empty string')
        if type(authorization) is not str or not authorization:
            raise ValueError('authorization must be a non-empty string')
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        flags |= getattr(os, 'O_BINARY', 0)
        self._descriptor = os.open(path, flags, 0o600)
        self._sequence = 0
        try:
            self.append('journal_opened', {
                'motion_id': motion_id,
                'authorization': authorization,
            })
        except BaseException:
            self.close()
            raise

    def append(self, event, payload):
        if self._descriptor is None:
            raise RuntimeError('journal is closed')
        if type(event) is not str or not event:
            raise ValueError('event must be a non-empty string')
        if type(payload) is not dict:
            raise ValueError('payload must be an exact dict')
        record = {
            'schema': SCHEMA,
            'sequence': self._sequence,
            'monotonic_ns': time.monotonic_ns(),
            'event': event,
            'payload': payload,
        }
        encoded = (json.dumps(
            record, allow_nan=False, ensure_ascii=False, sort_keys=True,
            separators=(',', ':')) + '\n').encode('utf-8')
        _write_all(self._descriptor, encoded)
        os.fsync(self._descriptor)
        self._sequence += 1
        return record

    def close(self):
        if self._descriptor is not None:
            descriptor = self._descriptor
            self._descriptor = None
            os.close(descriptor)

    def __enter__(self):
        return self

    def __exit__(self, unused_type, unused_value, unused_traceback):
        self.close()


def record_post_send_sample_and_classify(
        journal, sample, before_angles, target_joint, target_deg,
        other_joint_tolerance_deg=0.7, target_tolerance_deg=0.8):
    """Persist the raw sample first, then return one fail-closed decision."""
    if not isinstance(journal, DurableMotionJournal):
        raise TypeError('journal must be DurableMotionJournal')
    if type(sample) is not dict:
        raise TypeError('sample must be an exact dict')
    journal.append('post_send_sample', {
        'sample_schema': SAMPLE_SCHEMA,
        'sample': sample,
    })

    if sample.get('connected') != 1:
        return 'FAULT_CONNECTED'
    error = sample.get('error')
    if type(error) is not int or error != 0:
        return 'FAULT_ERROR'
    moving = sample.get('moving')
    if type(moving) is not int or moving not in (0, 1):
        return 'FAULT_MOVING_INVALID'
    angles = sample.get('angles_deg')
    if (type(angles) is not list or len(angles) != 6
            or not all(_exact_finite_number(value) for value in angles)):
        return 'FAULT_ANGLES_INVALID'
    if (type(before_angles) is not list or len(before_angles) != 6
            or not all(_exact_finite_number(value) for value in before_angles)):
        raise ValueError('before_angles must contain six finite numbers')
    if type(target_joint) is not int or target_joint not in range(1, 7):
        raise ValueError('target_joint must be an integer from 1 through 6')
    if not _exact_finite_number(target_deg):
        raise ValueError('target_deg must be finite')

    target_index = target_joint - 1
    for index, (before, after) in enumerate(zip(before_angles, angles)):
        if index == target_index:
            continue
        if abs(after - before) > other_joint_tolerance_deg:
            return 'FAULT_OTHER_JOINT_CHANGED'
    if abs(angles[target_index] - target_deg) <= target_tolerance_deg:
        return 'TARGET_STATIONARY' if moving == 0 else 'TARGET_MOVING'
    return 'IN_PROGRESS' if moving == 1 else 'FAULT_STOPPED_OFF_TARGET'


def record_stop_outcome(journal, stop_called, stop_return, exception_name=None):
    """Persist STOP evidence without claiming that software STOP is physical."""
    if type(stop_called) is not bool:
        raise ValueError('stop_called must be bool')
    payload = {
        'stop_called': stop_called,
        'stop_return_repr': repr(stop_return),
        'exception_name': exception_name,
        'physical_stop_proven': False,
    }
    journal.append('software_stop_outcome', payload)
    return payload

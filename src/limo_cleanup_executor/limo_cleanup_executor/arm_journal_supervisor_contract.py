"""Fail-closed contract between an arm runner and an isolated journal worker.

This module performs no I/O and starts no process.  It deliberately does not
claim that ``fsync`` is bounded.  A future supervisor must execute journal I/O
in a separately terminable process and present the acknowledgement described
here before it may classify a post-send sample.
"""

import math
import time


ACK_SCHEMA = 'limo_arm_journal_durable_ack/v1'
WAITING = 'WAITING_FOR_DURABLE_ACK'
DURABLE = 'DURABLE_ACK_ACCEPTED'
PHYSICAL_ISOLATION_REQUIRED = 'PHYSICAL_ISOLATION_REQUIRED'


def _sha256(value):
    return (type(value) is str and len(value) == 64
            and all(character in '0123456789abcdef' for character in value))


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


class BoundedJournalAckGate:
    """One-shot epoch gate; missing or invalid durable ACK latches blocked."""

    _ACK_KEYS = frozenset({
        'schema', 'motion_id', 'epoch', 'sample_sha256',
        'worker_release_sha256', 'record_sha256', 'journal_sequence',
        'durable_fsync',
    })

    def __init__(self, motion_id, worker_release_sha256, deadline_s,
                 clock=None):
        if type(motion_id) is not str or not motion_id:
            raise ValueError('motion_id must be a non-empty exact string')
        if not _sha256(worker_release_sha256):
            raise ValueError('worker release must be an exact lowercase sha256')
        if not _finite(deadline_s) or deadline_s <= 0:
            raise ValueError('deadline_s must be finite and positive')
        if clock is None:
            clock = time.monotonic
        if not callable(clock):
            raise TypeError('clock must be callable')
        self._motion_id = motion_id
        self._worker_release_sha256 = worker_release_sha256
        self._deadline_s = float(deadline_s)
        self._clock = clock
        self._epoch = 0
        self._sample_sha256 = None
        self._deadline = None
        self._state = None
        self._physical_stop_required = False

    @property
    def state(self):
        return self._state

    @property
    def physical_stop_required(self):
        return self._physical_stop_required

    @property
    def classification_permitted(self):
        return self._state == DURABLE and not self._physical_stop_required

    def reserve(self, sample_sha256):
        if self._state is not None:
            raise RuntimeError('journal gate is one-shot')
        if not _sha256(sample_sha256):
            raise ValueError('sample must be bound by an exact lowercase sha256')
        now = self._read_clock_or_latch()
        self._epoch += 1
        self._sample_sha256 = sample_sha256
        self._deadline = now + self._deadline_s
        self._state = WAITING
        return {
            'motion_id': self._motion_id,
            'epoch': self._epoch,
            'sample_sha256': self._sample_sha256,
            'worker_release_sha256': self._worker_release_sha256,
            'deadline_monotonic': self._deadline,
        }

    def accept(self, acknowledgement):
        if self._state != WAITING:
            self._latch()
            return False
        now = self._read_clock_or_latch()
        if self._state == PHYSICAL_ISOLATION_REQUIRED:
            return False
        if now > self._deadline:
            self._latch()
            return False
        if type(acknowledgement) is not dict:
            self._latch()
            return False
        if frozenset(acknowledgement) != self._ACK_KEYS:
            self._latch()
            return False
        valid = (
            acknowledgement['schema'] == ACK_SCHEMA
            and type(acknowledgement['schema']) is str
            and acknowledgement['motion_id'] == self._motion_id
            and type(acknowledgement['motion_id']) is str
            and type(acknowledgement['epoch']) is int
            and acknowledgement['epoch'] == self._epoch
            and acknowledgement['sample_sha256'] == self._sample_sha256
            and _sha256(acknowledgement['sample_sha256'])
            and acknowledgement['worker_release_sha256']
            == self._worker_release_sha256
            and _sha256(acknowledgement['worker_release_sha256'])
            and _sha256(acknowledgement['record_sha256'])
            and type(acknowledgement['journal_sequence']) is int
            and acknowledgement['journal_sequence'] >= 1
            and acknowledgement['durable_fsync'] is True
        )
        if not valid:
            self._latch()
            return False
        self._state = DURABLE
        return True

    def expire(self):
        if self._state != WAITING:
            return self._state
        now = self._read_clock_or_latch()
        if self._state == WAITING and now >= self._deadline:
            self._latch()
        return self._state

    def close(self):
        """Close cannot turn an unresolved durable write into a safe result."""
        if self._state != DURABLE:
            self._latch()
        return self._state

    def _read_clock_or_latch(self):
        try:
            now = self._clock()
        except BaseException:
            self._latch()
            raise RuntimeError('supervisor clock failed')
        if not _finite(now):
            self._latch()
            raise RuntimeError('supervisor clock is not finite')
        return float(now)

    def _latch(self):
        self._state = PHYSICAL_ISOLATION_REQUIRED
        self._physical_stop_required = True

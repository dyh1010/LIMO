"""Pure atomic command, status, epoch, and authorization policies."""

import json
import math
import os
import tempfile
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from limo_cleanup_base.navigation_intent_policy import MapWaypoint
from limo_cleanup_base.strict_json import loads_strict


PROTOCOL_VERSION = 'cleanup_navigation_bridge/v3'
TERMINAL_STATES = frozenset({
    'succeeded',
    'aborted',
    'preempted',
    'rejected',
    'unavailable',
    'stopped',
})
INACTIVE_READY_STATES = TERMINAL_STATES | {'ready'}


@dataclass(frozen=True)
class BridgeStatus:
    """Validated ROS1 adapter heartbeat."""

    state: str
    epoch: int
    nonce: str
    server_ready: bool
    scan_fresh: bool
    tf_ready: bool


class EpochStore:
    """Atomically persist a strictly increasing bridge command epoch."""

    def __init__(self, path: str):
        self.path = Path(path)
        if not path:
            raise ValueError('epoch_state_file is required')

    @contextmanager
    def _exclusive_lock(self):
        lock_path = self.path.with_name(self.path.name + '.lock')
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open('a+b') as stream:
            if os.name == 'posix':
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
            else:
                import msvcrt
                stream.seek(0, os.SEEK_END)
                if stream.tell() == 0:
                    stream.write(b'\0')
                    stream.flush()
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
                try:
                    yield
                finally:
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)

    def allocate(self) -> int:
        with self._exclusive_lock():
            current = 0
            if self.path.exists():
                raw_value = self.path.read_text(encoding='ascii').strip()
                if not raw_value.isdigit():
                    raise ValueError('epoch state file is corrupt')
                current = int(raw_value)
            next_epoch = current + 1
            if next_epoch > 2 ** 63 - 1:
                raise ValueError('epoch state is exhausted')
            self.path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=self.path.name + '.',
                suffix='.tmp',
                dir=str(self.path.parent),
            )
            try:
                with os.fdopen(
                        descriptor, 'w', encoding='ascii', newline='\n'
                ) as stream:
                    stream.write('{}\n'.format(next_epoch))
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary_name, str(self.path))
            finally:
                if os.path.exists(temporary_name):
                    os.unlink(temporary_name)
            return next_epoch


class CancelRetryPolicy:
    """Bound retries of one idempotent cancel until a non-active ACK."""

    def __init__(self, interval: float, timeout: float):
        values = (interval, timeout)
        if not all(math.isfinite(value) for value in values):
            raise ValueError('cancel retry timing must be finite')
        if interval <= 0.0 or timeout <= interval:
            raise ValueError('cancel retry timeout must exceed interval')
        self.interval = interval
        self.timeout = timeout
        self._lock = threading.RLock()
        self.clear()

    def clear(self) -> None:
        with self._lock:
            self.epoch = None
            self.payload = None
            self.started_at = -1.0
            self.last_sent_at = -1.0
            self.retry_exhausted = False

    @property
    def active(self) -> bool:
        with self._lock:
            return self.payload is not None

    def start(self, epoch: int, payload: str, now: float) -> None:
        with self._lock:
            if self.payload is not None:
                return
            if not math.isfinite(now) or now < 0.0:
                raise ValueError('cancel retry start time is invalid')
            self.epoch = epoch
            self.payload = payload
            self.started_at = now
            self.last_sent_at = now
            self.retry_exhausted = False

    def acknowledge(self, status: BridgeStatus) -> bool:
        with self._lock:
            if (
                    self.payload is not None
                    and status.epoch == self.epoch
                    and status.state in {'stopped', 'preempted'}):
                self.clear()
                return True
            return False

    def next_payload(self, now: float) -> Optional[str]:
        with self._lock:
            if self.payload is None or not math.isfinite(now) or now < 0.0:
                return None
            if now < self.last_sent_at:
                self.retry_exhausted = True
                return None
            if now - self.started_at >= self.timeout:
                # Retry transmission is bounded, but the CANCELLING barrier is
                # sticky until the exact cancel epoch is acknowledged stopped.
                self.retry_exhausted = True
                return None
            if now - self.last_sent_at >= self.interval:
                self.last_sent_at = now
                return self.payload
            return None

    def run_if_clear(self, callback):
        """Run one dispatch allocation atomically against cancel start/ACK."""
        with self._lock:
            if self.payload is not None:
                return False, None
            return True, callback()


def _finite(value, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError('{} must be a number'.format(name))
    value = float(value)
    if not math.isfinite(value):
        raise ValueError('{} must be finite'.format(name))
    return value


def build_cancel_command(epoch: int) -> str:
    """Build a highest-priority idempotent cancel command."""
    if not isinstance(epoch, int) or isinstance(epoch, bool) or epoch <= 0:
        raise ValueError('cancel epoch must be a positive integer')
    return json.dumps({
        'protocol': PROTOCOL_VERSION,
        'operation': 'cancel',
        'epoch': epoch,
    }, sort_keys=True, separators=(',', ':'))


def build_dispatch_command(
        epoch: int,
        nonce: str,
        waypoint: MapWaypoint) -> str:
    """Build one atomic nonce-bound goal dispatch command."""
    if not isinstance(epoch, int) or isinstance(epoch, bool) or epoch <= 0:
        raise ValueError('dispatch epoch must be a positive integer')
    if not isinstance(nonce, str) or len(nonce) < 16:
        raise ValueError('dispatch nonce is missing or too short')
    return json.dumps({
        'protocol': PROTOCOL_VERSION,
        'operation': 'dispatch_goal',
        'epoch': epoch,
        'nonce': nonce,
        'map_id': waypoint.map_id,
        'goal': {
            'frame_id': waypoint.frame_id,
            'x': _finite(waypoint.x, 'goal.x'),
            'y': _finite(waypoint.y, 'goal.y'),
            'yaw': _finite(waypoint.yaw, 'goal.yaw'),
        },
    }, sort_keys=True, separators=(',', ':'))


def parse_bridge_status(payload: str) -> BridgeStatus:
    """Accept only the internal v3 ROS1 adapter status schema."""
    data = loads_strict(payload, 'bridge status')
    if not isinstance(data, dict):
        raise ValueError('bridge status must be an object')
    expected_keys = {
        'protocol', 'state', 'epoch', 'nonce', 'server_ready',
        'scan_fresh', 'tf_ready'}
    if set(data) != expected_keys:
        raise ValueError('bridge status fields do not match v3 schema')
    if (
            not isinstance(data['protocol'], str)
            or data['protocol'] != PROTOCOL_VERSION):
        raise ValueError('unsupported bridge status protocol')
    state = data['state']
    allowed_states = INACTIVE_READY_STATES | {'active'}
    if not isinstance(state, str) or state not in allowed_states:
        raise ValueError('unsupported bridge status state')
    epoch = data['epoch']
    if not isinstance(epoch, int) or isinstance(epoch, bool) or epoch < 0:
        raise ValueError('bridge status epoch must be a nonnegative integer')
    nonce = data['nonce']
    if not isinstance(nonce, str) or len(nonce) < 16:
        raise ValueError('bridge status nonce is missing or too short')
    for field in ('server_ready', 'scan_fresh', 'tf_ready'):
        if data[field] is not True and data[field] is not False:
            raise ValueError(
                'bridge status {} must be boolean'.format(field))
    return BridgeStatus(
        state=state,
        epoch=epoch,
        nonce=nonce,
        server_ready=bool(data['server_ready']),
        scan_fresh=bool(data['scan_fresh']),
        tf_ready=bool(data['tf_ready']),
    )


class NavigationAuthorizationPolicy:
    """Authorize motion only for a fresh active ack of the pending epoch."""

    def __init__(self):
        self.pending_epoch = None
        self.pending_time = -1.0
        self.pending_acknowledged = False
        self.status = None
        self.status_time = -1.0
        self.fault_latched = False
        self.fault_epoch = 0
        self.highest_status_epoch = 0
        self._nonce_epochs = {}
        self._faulted_nonces = set()
        self._lock = threading.RLock()

    def dispatch(self, epoch: int, nonce: str, now: float) -> None:
        with self._lock:
            if not math.isfinite(now) or now < 0.0:
                raise ValueError('dispatch time must be finite and nonnegative')
            context = self.dispatch_context(now, 1e308)
            if context is None:
                raise RuntimeError('dispatch requires a healthy inactive status')
            if not isinstance(epoch, int) or isinstance(epoch, bool):
                raise ValueError('dispatch epoch must be an integer')
            if epoch <= max(self.highest_status_epoch, self.fault_epoch):
                raise RuntimeError('dispatch epoch must advance past fault history')
            if nonce != context.nonce or nonce in self._faulted_nonces:
                raise RuntimeError('dispatch nonce is stale, replayed, or mismatched')
            self.pending_epoch = epoch
            self.pending_time = now
            self.pending_acknowledged = False
            self.status = None
            self.status_time = -1.0
            self.fault_latched = False

    def cancel(self) -> None:
        """Treat every explicit cancel as sticky revocation."""
        self.latch_fault()

    def latch_fault(self, status: Optional[BridgeStatus] = None) -> None:
        """Sticky revocation; only a new epoch+nonce dispatch can clear it."""
        with self._lock:
            epochs = [self.fault_epoch, self.highest_status_epoch]
            if self.pending_epoch is not None:
                epochs.append(self.pending_epoch)
            if status is not None:
                epochs.append(status.epoch)
                self._faulted_nonces.add(status.nonce)
            if self.status is not None:
                epochs.append(self.status.epoch)
                self._faulted_nonces.add(self.status.nonce)
            self.fault_epoch = max(epochs)
            self.pending_epoch = None
            self.pending_time = -1.0
            self.pending_acknowledged = False
            self.status = status
            self.status_time = -1.0
            self.fault_latched = True

    def update(self, status: BridgeStatus, now: float) -> bool:
        """Accept one status heartbeat or sticky-revoke on any anomaly."""
        with self._lock:
            return self._update_locked(status, now)

    def _update_locked(self, status: BridgeStatus, now: float) -> bool:
        if not math.isfinite(now) or now < 0.0:
            self.latch_fault(status)
            return False
        previous_epoch = self._nonce_epochs.get(status.nonce)
        if previous_epoch is not None and previous_epoch != status.epoch:
            self.latch_fault(status)
            return False
        self._nonce_epochs[status.nonce] = status.epoch
        if status.epoch < self.highest_status_epoch:
            self.latch_fault(status)
            return False
        if (
                self.fault_latched
                and status.state == 'active'
                and status.epoch <= self.fault_epoch):
            self.latch_fault(status)
            return False
        self.highest_status_epoch = max(
            self.highest_status_epoch, status.epoch)
        self.status = status
        self.status_time = now
        if (
                not status.server_ready
                or not status.scan_fresh
                or not status.tf_ready
                or status.state == 'unavailable'):
            self.latch_fault(status)
            return False
        if (
                self.pending_epoch is not None
                and status.epoch == self.pending_epoch
                and status.state == 'active'):
            self.pending_acknowledged = True
            return True
        if (
                self.pending_epoch is not None
                and status.state == 'active'
                and status.epoch != self.pending_epoch):
            self.latch_fault(status)
            return False
        if (
                self.pending_epoch is not None
                and status.epoch >= self.pending_epoch
                and status.state != 'active'):
            self.pending_epoch = None
            self.pending_time = -1.0
            self.pending_acknowledged = False
            if status.state in {'aborted', 'rejected', 'unavailable'}:
                self.latch_fault(status)
                return False
        return True

    def authorization(self, now: float, timeout: float) -> bool:
        with self._lock:
            stale = (
                self.pending_epoch is None
                or self.fault_latched
                or self.status is None
                or not math.isfinite(now)
                or not math.isfinite(timeout)
                or timeout <= 0.0
                or self.status_time < 0.0
                or now < self.status_time
                or now - self.status_time >= timeout)
            if stale:
                if (
                        self.pending_epoch is not None
                        and self.status is not None
                        and self.status.state == 'active'):
                    self.latch_fault(self.status)
                return False
            return (
                self.status.state == 'active'
                and self.status.server_ready
                and self.status.scan_fresh
                and self.status.tf_ready
                and self.status.epoch == self.pending_epoch
            )

    def pending_expired(self, now: float, timeout: float) -> bool:
        """Latch expiry for either a missing ACK or a lost active heartbeat."""
        with self._lock:
            if (
                self.pending_epoch is None
                or not math.isfinite(now)
                or not math.isfinite(timeout)
                or timeout <= 0.0):
                return False
            if not self.pending_acknowledged:
                expired = (
                    self.pending_time >= 0.0
                    and now >= self.pending_time
                    and now - self.pending_time >= timeout
                )
            else:
                expired = (
                    self.status is not None
                    and self.status.state == 'active'
                    and self.status.epoch == self.pending_epoch
                    and self.status_time >= 0.0
                    and now >= self.status_time
                    and now - self.status_time >= timeout
                )
            if expired:
                self.latch_fault(self.status)
            return expired

    def goal_expired(self, now: float, timeout: float) -> bool:
        """Require every dispatched goal to finish before a total deadline."""
        with self._lock:
            expired = (
            self.pending_epoch is not None
            and math.isfinite(now)
            and math.isfinite(timeout)
            and timeout > 0.0
            and self.pending_time >= 0.0
            and now >= self.pending_time
            and now - self.pending_time >= timeout)
            if expired:
                self.latch_fault(self.status)
            return expired

    def dispatch_context(
            self,
            now: float,
            timeout: float) -> Optional[BridgeStatus]:
        with self._lock:
            if (
                self.status is None
                or not math.isfinite(now)
                or not math.isfinite(timeout)
                or timeout <= 0.0
                or self.status_time < 0.0
                or now < self.status_time
                or now - self.status_time >= timeout
                or not self.status.server_ready
                or not self.status.scan_fresh
                or not self.status.tf_ready
                or self.status.state not in INACTIVE_READY_STATES):
                return None
            if self.status.nonce in self._faulted_nonces:
                return None
            return self.status

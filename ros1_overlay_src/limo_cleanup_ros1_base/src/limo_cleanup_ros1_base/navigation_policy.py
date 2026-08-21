"""Pure atomic, replay-resistant ROS1 navigation bridge policy."""

import json
import math
import threading
import uuid
from dataclasses import dataclass
from typing import Optional

from limo_cleanup_ros1_base.strict_json import loads_strict


PROTOCOL_VERSION = 'cleanup_navigation_bridge/v3'
REJECTED_MAP_IDS = frozenset({
    'map02',
    'map1017',
    'NOT_AVAILABLE_MAP_NOT_FROZEN',
})
TERMINAL_STATES = frozenset({
    'succeeded',
    'aborted',
    'preempted',
    'rejected',
    'unavailable',
    'stopped',
})


@dataclass(frozen=True)
class PoseValues:
    """Transport-independent pose fields needed for validation."""

    frame_id: str
    position_x: float
    position_y: float
    position_z: float
    orientation_x: float
    orientation_y: float
    orientation_z: float
    orientation_w: float


@dataclass(frozen=True)
class BridgeCommand:
    """Validated atomic bridge command."""

    operation: str
    epoch: int
    nonce: str = ''
    map_id: str = ''
    pose: Optional[PoseValues] = None
    fingerprint: str = ''


def validate_navigation_goal(
        pose: PoseValues,
        allowed_frame: str = 'map',
        quaternion_tolerance: float = 1e-3) -> None:
    """Reject non-finite, wrong-frame, or invalid-orientation goals."""
    if pose.frame_id != allowed_frame:
        raise ValueError(
            'navigation goal frame must be {}, got {}'.format(
                allowed_frame, pose.frame_id or '<empty>'))
    values = (
        pose.position_x,
        pose.position_y,
        pose.position_z,
        pose.orientation_x,
        pose.orientation_y,
        pose.orientation_z,
        pose.orientation_w,
    )
    if not all(math.isfinite(value) for value in values):
        raise ValueError('navigation goal pose must be finite')
    quaternion_norm = math.sqrt(
        pose.orientation_x ** 2
        + pose.orientation_y ** 2
        + pose.orientation_z ** 2
        + pose.orientation_w ** 2)
    if abs(quaternion_norm - 1.0) > quaternion_tolerance:
        raise ValueError(
            'navigation goal quaternion must be normalized, norm={}'.format(
                quaternion_norm))


def _positive_epoch(value) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError('bridge command epoch must be a positive integer')
    return value


def _number(value, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError('{} must be a number'.format(name))
    value = float(value)
    if not math.isfinite(value):
        raise ValueError('{} must be finite'.format(name))
    return value


def parse_bridge_command(payload: str) -> BridgeCommand:
    """Parse the exact internal atomic bridge command schema."""
    data = loads_strict(payload, 'bridge command')
    if not isinstance(data, dict):
        raise ValueError('bridge command must be an object')
    if (
            not isinstance(data.get('protocol'), str)
            or data.get('protocol') != PROTOCOL_VERSION):
        raise ValueError('unsupported bridge command protocol')
    operation = data.get('operation')
    if not isinstance(operation, str):
        raise ValueError('bridge command operation must be a string')
    epoch = _positive_epoch(data.get('epoch'))
    if operation == 'cancel':
        if set(data) != {'protocol', 'operation', 'epoch'}:
            raise ValueError('cancel command fields do not match v3 schema')
        return BridgeCommand(operation=operation, epoch=epoch)
    if operation != 'dispatch_goal':
        raise ValueError('unsupported bridge command operation')
    if set(data) != {
            'protocol', 'operation', 'epoch', 'nonce', 'map_id', 'goal'}:
        raise ValueError('dispatch command fields do not match v3 schema')
    nonce = data['nonce']
    if not isinstance(nonce, str) or len(nonce) < 16:
        raise ValueError('dispatch nonce is missing or too short')
    map_id = data['map_id']
    if (
            not isinstance(map_id, str)
            or not map_id.strip()
            or map_id != map_id.strip()
            or map_id in REJECTED_MAP_IDS):
        raise ValueError('dispatch map_id is missing, unsafe, or rejected')
    goal = data['goal']
    if not isinstance(goal, dict) or set(goal) != {
            'frame_id', 'x', 'y', 'yaw'}:
        raise ValueError('dispatch goal fields do not match v3 schema')
    if not isinstance(goal['frame_id'], str):
        raise ValueError('dispatch goal frame_id must be a string')
    yaw = _number(goal['yaw'], 'goal.yaw')
    pose = PoseValues(
        frame_id=goal['frame_id'],
        position_x=_number(goal['x'], 'goal.x'),
        position_y=_number(goal['y'], 'goal.y'),
        position_z=0.0,
        orientation_x=0.0,
        orientation_y=0.0,
        orientation_z=math.sin(yaw / 2.0),
        orientation_w=math.cos(yaw / 2.0),
    )
    validate_navigation_goal(pose)
    fingerprint = json.dumps(
        data, sort_keys=True, separators=(',', ':'))
    return BridgeCommand(
        operation=operation,
        epoch=epoch,
        nonce=nonce,
        map_id=map_id,
        pose=pose,
        fingerprint=fingerprint,
    )


class AtomicNavigationProtocol:
    """Consume each nonce once and reject stale, reordered, or replayed goals."""

    def __init__(self, nonce_factory=None):
        self.nonce_factory = nonce_factory or (lambda: uuid.uuid4().hex)
        self.nonce = self._new_nonce()
        self.highest_epoch = 0
        self.state = 'stopped'
        self.active_epoch = None
        self.active_fingerprint = None

    def _new_nonce(self):
        nonce = str(self.nonce_factory())
        if len(nonce) < 16:
            raise ValueError('nonce factory returned an unsafe nonce')
        return nonce

    def _rotate_nonce(self):
        self.nonce = self._new_nonce()

    def cancel(self, epoch: int) -> None:
        """Always honor cancel; stale cancel can only make the system safer."""
        self.highest_epoch = max(self.highest_epoch, int(epoch))
        self.active_epoch = None
        self.active_fingerprint = None
        self.state = 'stopped'
        self._rotate_nonce()

    def reject(self, epoch: int = 0) -> None:
        """Fail closed and invalidate every previously issued capability."""
        self.highest_epoch = max(self.highest_epoch, int(epoch))
        self.active_epoch = None
        self.active_fingerprint = None
        self.state = 'rejected'
        self._rotate_nonce()

    def accept(
            self,
            command: BridgeCommand,
            navigation_ready: bool,
            active_map_id: str = '') -> str:
        """Return accepted, duplicate, or cancelled; raise on unsafe input."""
        if command.operation == 'cancel':
            self.cancel(command.epoch)
            return 'cancelled'
        if (
                self.state == 'active'
                and command.epoch == self.active_epoch
                and command.fingerprint == self.active_fingerprint):
            return 'duplicate'
        if not bool(navigation_ready):
            self.reject(command.epoch)
            raise RuntimeError('navigation health gate is unavailable')
        if self.state == 'active':
            self.reject(command.epoch)
            raise RuntimeError('another navigation epoch is active')
        if command.epoch <= self.highest_epoch:
            self.reject(command.epoch)
            raise RuntimeError('navigation epoch is stale or replayed')
        if command.nonce != self.nonce:
            self.reject(command.epoch)
            raise RuntimeError('navigation nonce is stale or replayed')
        if command.pose is None:
            self.reject(command.epoch)
            raise RuntimeError('dispatch goal is missing')
        if command.map_id != active_map_id:
            self.reject(command.epoch)
            raise RuntimeError('dispatch map_id does not match active map')
        self.highest_epoch = command.epoch
        self.active_epoch = command.epoch
        self.active_fingerprint = command.fingerprint
        self.state = 'active'
        self._rotate_nonce()
        return 'accepted'

    def complete(self, epoch: int, state: str) -> bool:
        """Latch a terminal result only for the currently active epoch."""
        if state not in TERMINAL_STATES - {'stopped', 'unavailable'}:
            raise ValueError('unsupported terminal navigation state')
        if self.state != 'active' or self.active_epoch != epoch:
            return False
        self.active_epoch = None
        self.active_fingerprint = None
        self.state = state
        self._rotate_nonce()
        return True

    def set_navigation_ready(self, ready: bool) -> bool:
        """Fail closed when move_base, scan, or TF readiness disappears."""
        if ready:
            if self.state == 'unavailable':
                self.state = 'ready'
                self._rotate_nonce()
                return True
            return False
        if self.state != 'unavailable':
            self.active_epoch = None
            self.active_fingerprint = None
            self.state = 'unavailable'
            self._rotate_nonce()
            return True
        return False

    def status_payload(
            self,
            server_ready: bool,
            scan_fresh: bool,
            tf_ready: bool) -> str:
        """Build the exact ROS1 heartbeat/result schema."""
        return json.dumps({
            'protocol': PROTOCOL_VERSION,
            'state': self.state,
            'epoch': self.highest_epoch,
            'nonce': self.nonce,
            'server_ready': bool(server_ready),
            'scan_fresh': bool(scan_fresh),
            'tf_ready': bool(tf_ready),
        }, sort_keys=True, separators=(',', ':'))


class GoalGenerationGate:
    """Linearize goal sends against cancel/fault generation invalidation."""

    def __init__(self):
        self._lock = threading.RLock()
        self._generation = 0

    def reserve(self):
        """Reserve the current generation for a not-yet-sent goal."""
        with self._lock:
            return self._generation

    def invalidate(self, cancel_callback=None):
        """Invalidate every reserved send before executing cancellation."""
        with self._lock:
            self._generation += 1
            if cancel_callback is not None:
                cancel_callback()
            return self._generation

    def commit(self, generation, send_callback):
        """Run send_callback only if no cancel/fault has invalidated it."""
        with self._lock:
            if generation != self._generation:
                return False
            send_callback()
            return True

    def is_current(self, generation):
        """Return whether a result callback still belongs to the live goal."""
        with self._lock:
            return generation == self._generation

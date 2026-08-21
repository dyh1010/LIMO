"""Dependency-free READY-gated point-to-point navigation policy."""

from dataclasses import dataclass
import math
import threading


IDLE = 'IDLE'
ACTIVE = 'ACTIVE'
SUCCEEDED = 'SUCCEEDED'
CANCELED = 'CANCELED'
FAILED = 'FAILED'
BLOCKED = 'BLOCKED'


@dataclass(frozen=True)
class GoalRequest:
    request_id: str
    frame_id: str
    x: float
    y: float
    yaw: float


@dataclass(frozen=True)
class GateDecision:
    accepted: bool
    reason: str


class GoalGenerationGate:
    """Linearize a pending action send against every stop invalidation."""

    def __init__(self):
        self._lock = threading.RLock()
        self._generation = 0

    def reserve(self):
        """Capture the generation for one accepted, not-yet-sent goal."""
        with self._lock:
            return self._generation

    def invalidate(self, cancel_callback=None):
        """Invalidate pending sends before invoking the action cancellation."""
        with self._lock:
            self._generation += 1
            if cancel_callback is not None:
                cancel_callback()
            return self._generation

    def commit(self, generation, send_callback):
        """Send only while the reservation is still the current generation."""
        with self._lock:
            if generation != self._generation:
                return False
            send_callback()
            return True

    def is_current(self, generation):
        with self._lock:
            return generation == self._generation


def validate_goal(goal):
    if not isinstance(goal, GoalRequest):
        raise ValueError('goal must be GoalRequest')
    if not isinstance(goal.request_id, str) or not goal.request_id.strip():
        raise ValueError('request_id must be non-empty')
    if len(goal.request_id) > 128:
        raise ValueError('request_id is too long')
    if goal.frame_id != 'map':
        raise ValueError('goal frame must be map')
    for name, value in (('x', goal.x), ('y', goal.y), ('yaw', goal.yaw)):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError('{} must be numeric'.format(name))
        if not math.isfinite(float(value)):
            raise ValueError('{} must be finite'.format(name))
    return goal


class NavigationGate:
    """One-goal fail-closed gate with explicit rearm and cancel priority."""

    def __init__(self):
        self.state = BLOCKED
        self.reason = 'startup_latched'
        self.localization_ready = False
        self.localization_seen = False
        self.localization_receive = None
        self.action_server_ready = False
        self.armed = False
        self.active_goal = None
        self.last_request_id = None
        self.cancel_required = False

    def update_localization(self, ready, received_monotonic):
        if not isinstance(ready, bool):
            raise ValueError('localization ready must be bool')
        if not isinstance(received_monotonic, (int, float)) or not math.isfinite(
                received_monotonic):
            raise ValueError('localization receive time must be finite')
        was_ready = self.localization_ready
        self.localization_ready = ready
        self.localization_seen = True
        self.localization_receive = float(received_monotonic)
        if was_ready and not ready:
            self.trip('localization_ready_lost')

    def update_action_server(self, ready):
        self.action_server_ready = bool(ready)
        if not self.action_server_ready and self.active_goal is not None:
            self.trip('move_base_action_server_lost')

    def health_ready(self, now, localization_timeout_s):
        if not self.localization_seen or self.localization_receive is None:
            return False, 'localization_ready_missing'
        age = now - self.localization_receive
        if not math.isfinite(age) or age < 0.0 or age >= localization_timeout_s:
            return False, 'localization_ready_stale'
        if not self.localization_ready:
            return False, 'localization_not_ready'
        if not self.action_server_ready:
            return False, 'move_base_action_server_unavailable'
        return True, 'healthy'

    def arm(self, now, localization_timeout_s):
        healthy, reason = self.health_ready(now, localization_timeout_s)
        if not healthy or self.active_goal is not None:
            return GateDecision(False, reason if not healthy else 'goal_active')
        self.armed = True
        self.state = IDLE
        self.reason = 'armed'
        self.cancel_required = False
        return GateDecision(True, 'armed')

    def submit(self, goal, now, localization_timeout_s):
        validate_goal(goal)
        healthy, reason = self.health_ready(now, localization_timeout_s)
        if not self.armed:
            return GateDecision(False, 'gate_not_armed')
        if not healthy:
            self.trip(reason)
            return GateDecision(False, reason)
        if self.active_goal is not None:
            return GateDecision(False, 'goal_already_active')
        if goal.request_id == self.last_request_id:
            return GateDecision(False, 'duplicate_request_id')
        self.active_goal = goal
        self.last_request_id = goal.request_id
        self.state = ACTIVE
        self.reason = 'goal_accepted'
        self.cancel_required = False
        return GateDecision(True, 'goal_accepted')

    def cancel(self, reason='operator_cancel'):
        had_goal = self.active_goal is not None
        self.active_goal = None
        self.armed = False
        self.state = CANCELED if had_goal else BLOCKED
        self.reason = str(reason)
        self.cancel_required = True
        return GateDecision(had_goal, self.reason)

    def tick(self, now, localization_timeout_s):
        """Actively trip an armed/active gate when readiness becomes stale."""
        healthy, reason = self.health_ready(now, localization_timeout_s)
        if not healthy and (self.armed or self.active_goal is not None):
            self.trip(reason)
        return GateDecision(healthy, reason)

    def trip(self, reason):
        self.active_goal = None
        self.armed = False
        self.state = BLOCKED
        self.reason = str(reason)
        self.cancel_required = True

    def complete(self, terminal_state, reason):
        if terminal_state not in (SUCCEEDED, CANCELED, FAILED):
            raise ValueError('invalid terminal navigation state')
        self.active_goal = None
        self.armed = False
        self.state = terminal_state
        self.reason = str(reason)
        self.cancel_required = terminal_state != SUCCEEDED

    def status(self, now, localization_timeout_s):
        healthy, health_reason = self.health_ready(
            now, localization_timeout_s)
        return {
            'state': self.state,
            'reason': self.reason,
            'armed': self.armed,
            'localization_ready': self.localization_ready,
            'localization_health': health_reason,
            'action_server_ready': self.action_server_ready,
            'active_request_id': (
                self.active_goal.request_id if self.active_goal else None),
            'last_request_id': self.last_request_id,
            'cancel_required': self.cancel_required,
            'goal_open': bool(self.armed and healthy
                              and self.active_goal is None),
        }

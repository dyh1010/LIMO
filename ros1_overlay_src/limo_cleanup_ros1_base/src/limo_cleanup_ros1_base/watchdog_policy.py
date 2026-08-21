"""Pure fail-closed policy used by the ROS1 bridge watchdog."""

import math
import threading
from dataclasses import dataclass
from typing import Callable, Optional, Tuple


@dataclass(frozen=True)
class TwistValues:
    """Transport-independent representation of geometry_msgs/Twist."""

    linear_x: float = 0.0
    linear_y: float = 0.0
    linear_z: float = 0.0
    angular_x: float = 0.0
    angular_y: float = 0.0
    angular_z: float = 0.0

    def as_tuple(self) -> Tuple[float, float, float, float, float, float]:
        return (
            self.linear_x,
            self.linear_y,
            self.linear_z,
            self.angular_x,
            self.angular_y,
            self.angular_z,
        )


ZERO_TWIST = TwistValues()


@dataclass(frozen=True)
class WatchdogLimits:
    """Limits applied again on the ROS1 side of the bridge."""

    lease_timeout: float = 0.25
    max_linear_speed: float = 0.12
    max_angular_speed: float = 0.35
    unsupported_axis_epsilon: float = 1e-6


def validate_limits(limits: WatchdogLimits) -> None:
    """Reject invalid limits instead of silently weakening the guard."""
    for name, value in (
            ('lease_timeout', limits.lease_timeout),
            ('max_linear_speed', limits.max_linear_speed),
            ('max_angular_speed', limits.max_angular_speed),
            ('unsupported_axis_epsilon', limits.unsupported_axis_epsilon)):
        if not math.isfinite(value) or value <= 0.0:
            raise ValueError('{} must be finite and positive'.format(name))


def validate_twist(command: TwistValues, limits: WatchdogLimits) -> None:
    """Require finite skid-steer commands with no unsupported axes."""
    validate_limits(limits)
    names = (
        'linear.x',
        'linear.y',
        'linear.z',
        'angular.x',
        'angular.y',
        'angular.z',
    )
    for name, value in zip(names, command.as_tuple()):
        if not math.isfinite(value):
            raise ValueError('{} must be finite'.format(name))
    unsupported = (
        ('linear.y', command.linear_y),
        ('linear.z', command.linear_z),
        ('angular.x', command.angular_x),
        ('angular.y', command.angular_y),
    )
    invalid = [
        name for name, value in unsupported
        if abs(value) > limits.unsupported_axis_epsilon
    ]
    if invalid:
        raise ValueError(
            'tracked mode rejects unsupported axes: {}'.format(
                ', '.join(invalid)))


def _bounded(value: float, limit: float) -> float:
    return max(-limit, min(limit, value))


def limited_twist(
        command: TwistValues,
        limits: WatchdogLimits) -> TwistValues:
    """Apply ROS1 defense-in-depth speed limits after validation."""
    validate_twist(command, limits)
    return TwistValues(
        linear_x=_bounded(command.linear_x, limits.max_linear_speed),
        angular_z=_bounded(command.angular_z, limits.max_angular_speed),
    )


class FailClosedWatchdog:
    """Lease-based command holder that always starts and expires at zero."""

    def __init__(
            self,
            allow_nonzero: bool = False,
            limits: WatchdogLimits = WatchdogLimits()):
        validate_limits(limits)
        self.allow_nonzero = bool(allow_nonzero)
        self.limits = limits
        self._command = ZERO_TWIST
        self._received_at: Optional[float] = None
        self._generation = 0
        self._lock = threading.RLock()

    def _clear_locked(self) -> TwistValues:
        self._generation += 1
        self._command = ZERO_TWIST
        self._received_at = None
        return ZERO_TWIST

    def clear(self) -> TwistValues:
        """Invalidate the lease and return an immediate zero command."""
        with self._lock:
            return self._clear_locked()

    def clear_snapshot(self):
        """Invalidate and return the new generation with zero."""
        with self._lock:
            return self._generation + 1, self._clear_locked()

    def accept(self, command: TwistValues, now: float) -> TwistValues:
        """Accept one fresh command or fail closed on any invalid input."""
        return self.accept_snapshot(command, now)[1]

    def accept_snapshot(self, command: TwistValues, now: float):
        """Accept and return the generation that owns the resulting lease."""
        with self._lock:
            if not math.isfinite(now) or now < 0.0:
                return self._generation + 1, self._clear_locked()
            try:
                safe_command = limited_twist(command, self.limits)
            except ValueError:
                self._clear_locked()
                raise
            if not self.allow_nonzero and safe_command != ZERO_TWIST:
                return self._generation + 1, self._clear_locked()
            self._generation += 1
            self._command = safe_command
            self._received_at = now
            return self._generation, safe_command

    def output(self, now: float) -> TwistValues:
        """Return the leased command only while its monotonic lease is valid."""
        return self.output_snapshot(now)[1]

    def output_snapshot(self, now: float):
        """Return a generation-tagged output for stale callback rejection."""
        with self._lock:
            if (
                    self._received_at is None
                    or not math.isfinite(now)
                    or now < self._received_at
                    or now - self._received_at >= self.limits.lease_timeout):
                return self._generation + 1, self._clear_locked()
            return self._generation, self._command

    def is_generation_current(self, generation: int) -> bool:
        """Reject a queued callback after any clear/fault/new command."""
        with self._lock:
            return generation == self._generation

    def generation(self) -> int:
        """Return the generation observed when a callback begins."""
        with self._lock:
            return self._generation


class GenerationPublishGate:
    """Linearize queued watchdog work against stop, fault, and teardown.

    ROS callbacks can begin before a higher-priority stop and only acquire the
    node lock afterwards.  Every nonzero callback therefore carries the policy
    generation observed at callback entry.  Publication happens while holding
    this gate and is allowed only if that generation is still current, the
    gate is enabled, and shutdown has not begun.
    """

    def __init__(
            self,
            publisher: Callable[[TwistValues], None],
            allow_nonzero: bool = False,
            limits: WatchdogLimits = WatchdogLimits()):
        self._lock = threading.RLock()
        self._publisher = publisher
        self._policy = FailClosedWatchdog(allow_nonzero, limits)
        self._enabled = True
        self._shutdown = False

    @property
    def policy(self) -> FailClosedWatchdog:
        """Expose read-only policy inspection for diagnostics/tests."""
        return self._policy

    def observe_generation(self) -> int:
        """Capture the lease generation at callback entry."""
        with self._lock:
            return self._policy.generation()

    def _publish_if_current_locked(
            self, generation: int, output: TwistValues) -> bool:
        if (
                not self._enabled
                or self._shutdown
                or not self._policy.is_generation_current(generation)):
            return False
        self._publisher(output)
        return True

    def publish_initial_zero(self) -> bool:
        """Publish the startup zero through the same final gate."""
        with self._lock:
            generation, output = self._policy.clear_snapshot()
            return self._publish_if_current_locked(generation, output)

    def handle_command(
            self,
            command: TwistValues,
            now: float,
            observed_generation: int) -> bool:
        """Accept one callback only if it was not overtaken by a stop.

        A zero command is itself a higher-priority stop and always invalidates
        older work.  Nonzero work must still match the generation captured at
        callback entry.
        """
        with self._lock:
            if not self._enabled or self._shutdown:
                return False
            try:
                safe_command = limited_twist(command, self._policy.limits)
            except ValueError:
                self._fault_locked()
                raise
            if safe_command == ZERO_TWIST:
                generation, output = self._policy.accept_snapshot(
                    ZERO_TWIST, now)
                return self._publish_if_current_locked(generation, output)
            if not self._policy.is_generation_current(observed_generation):
                return False
            generation, output = self._policy.accept_snapshot(command, now)
            return self._publish_if_current_locked(generation, output)

    def handle_timer(self, now: float, observed_generation: int) -> bool:
        """Publish a lease sample only for the timer's entry generation."""
        with self._lock:
            if (
                    not self._enabled
                    or self._shutdown
                    or not self._policy.is_generation_current(
                        observed_generation)):
                return False
            generation, output = self._policy.output_snapshot(now)
            return self._publish_if_current_locked(generation, output)

    def cancel(self) -> None:
        """Invalidate all queued work and publish the authoritative zero."""
        with self._lock:
            generation, output = self._policy.clear_snapshot()
            if self._enabled and not self._shutdown:
                self._publisher(output)
            assert self._policy.is_generation_current(generation)

    def _fault_locked(self) -> None:
        self._enabled = False
        generation, output = self._policy.clear_snapshot()
        self._publisher(output)
        assert self._policy.is_generation_current(generation)

    def fault(self) -> None:
        """Latch disabled, invalidate queued work, and publish final zero."""
        with self._lock:
            if self._shutdown:
                return
            self._fault_locked()

    def shutdown(self) -> None:
        """Atomically disable teardown and make zero the final publication."""
        with self._lock:
            if self._shutdown:
                return
            self._shutdown = True
            self._enabled = False
            generation, output = self._policy.clear_snapshot()
            self._publisher(output)
            assert self._policy.is_generation_current(generation)

import math
from pathlib import Path
import sys
import threading

import pytest


PACKAGE_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / 'src'))

from limo_cleanup_ros1_base.watchdog_policy import (  # noqa: E402
    FailClosedWatchdog,
    GenerationPublishGate,
    TwistValues,
    WatchdogLimits,
    ZERO_TWIST,
)


def test_watchdog_starts_at_zero_without_a_lease():
    watchdog = FailClosedWatchdog()
    assert watchdog.output(0.0) == ZERO_TWIST


def test_zero_only_mode_rejects_nonzero_and_clears_previous_lease():
    watchdog = FailClosedWatchdog(allow_nonzero=False)
    assert watchdog.accept(ZERO_TWIST, 1.0) == ZERO_TWIST
    assert watchdog.accept(TwistValues(linear_x=0.01), 1.1) == ZERO_TWIST
    assert watchdog.output(1.11) == ZERO_TWIST


def test_motion_mode_clamps_and_expires_on_monotonic_lease():
    watchdog = FailClosedWatchdog(
        allow_nonzero=True,
        limits=WatchdogLimits(
            lease_timeout=0.25,
            max_linear_speed=0.12,
            max_angular_speed=0.35,
        ),
    )
    accepted = watchdog.accept(
        TwistValues(linear_x=0.5, angular_z=-1.0), 10.0)
    assert accepted == TwistValues(linear_x=0.12, angular_z=-0.35)
    assert watchdog.output(10.249999) == accepted
    assert watchdog.output(10.25) == ZERO_TWIST
    assert watchdog.output(10.50) == ZERO_TWIST


def test_stop_or_cancel_zero_has_priority_over_a_fresh_nonzero_lease():
    watchdog = FailClosedWatchdog(allow_nonzero=True)
    watchdog.accept(TwistValues(linear_x=0.05), 1.0)
    assert watchdog.output(1.01).linear_x == 0.05
    assert watchdog.accept(ZERO_TWIST, 1.02) == ZERO_TWIST
    assert watchdog.output(1.021) == ZERO_TWIST
    assert watchdog.output(1.20) == ZERO_TWIST


@pytest.mark.parametrize(
    'command',
    [
        TwistValues(linear_y=0.001),
        TwistValues(linear_z=0.001),
        TwistValues(angular_x=0.001),
        TwistValues(angular_y=0.001),
        TwistValues(linear_x=math.nan),
        TwistValues(angular_z=math.inf),
    ],
)
def test_invalid_commands_raise_and_clear_the_lease(command):
    watchdog = FailClosedWatchdog(allow_nonzero=True)
    watchdog.accept(TwistValues(linear_x=0.01), 1.0)
    with pytest.raises(ValueError):
        watchdog.accept(command, 1.1)
    assert watchdog.output(1.11) == ZERO_TWIST


def test_time_reversal_and_nonfinite_time_fail_closed():
    watchdog = FailClosedWatchdog(allow_nonzero=True)
    watchdog.accept(TwistValues(linear_x=0.01), 2.0)
    assert watchdog.output(1.9) == ZERO_TWIST
    watchdog.accept(TwistValues(linear_x=0.01), 3.0)
    assert watchdog.output(math.nan) == ZERO_TWIST


def test_fault_generation_invalidates_queued_nonzero_publish():
    watchdog = FailClosedWatchdog(
        allow_nonzero=True,
        limits=WatchdogLimits(lease_timeout=0.25),
    )
    generation, command = watchdog.accept_snapshot(
        TwistValues(linear_x=0.05), 1.0)
    barrier = threading.Barrier(2)
    cleared = threading.Event()
    published = []

    def queued_callback():
        barrier.wait()
        cleared.wait(timeout=2.0)
        if watchdog.is_generation_current(generation):
            published.append(command)

    thread = threading.Thread(target=queued_callback)
    thread.start()
    barrier.wait()
    new_generation, zero = watchdog.clear_snapshot()
    cleared.set()
    thread.join(timeout=2.0)
    assert new_generation != generation
    assert zero == ZERO_TWIST
    assert published == []
    assert watchdog.output(1.01) == ZERO_TWIST


def _race_stale_work_after_zero(transition):
    published = []
    gate = GenerationPublishGate(
        published.append,
        allow_nonzero=True,
        limits=WatchdogLimits(lease_timeout=0.25),
    )
    gate.publish_initial_zero()
    published.clear()
    generation = gate.observe_generation()
    entered = threading.Barrier(2)
    resume = threading.Event()
    result = []

    def stale_callback():
        entered.wait()
        resume.wait(timeout=2.0)
        result.append(gate.handle_command(
            TwistValues(linear_x=0.05), 1.0, generation))

    worker = threading.Thread(target=stale_callback)
    worker.start()
    entered.wait()
    transition(gate)
    resume.set()
    worker.join(timeout=2.0)
    assert result == [False]
    assert published == [ZERO_TWIST]


def test_shutdown_zero_is_final_after_queued_callback_resumes():
    _race_stale_work_after_zero(lambda gate: gate.shutdown())


def test_fault_zero_is_final_after_queued_callback_resumes():
    _race_stale_work_after_zero(lambda gate: gate.fault())


def test_cancel_zero_invalidates_queued_nonzero_callback():
    _race_stale_work_after_zero(lambda gate: gate.cancel())


def test_lease_expiry_invalidates_older_callback_and_stays_zero():
    published = []
    gate = GenerationPublishGate(
        published.append,
        allow_nonzero=True,
        limits=WatchdogLimits(lease_timeout=0.25),
    )
    first_generation = gate.observe_generation()
    assert gate.handle_command(
        TwistValues(linear_x=0.05), 1.0, first_generation)
    stale_generation = gate.observe_generation()
    assert gate.handle_timer(1.25, stale_generation)
    assert published[-1] == ZERO_TWIST
    assert not gate.handle_command(
        TwistValues(linear_x=0.05), 1.1, stale_generation)
    assert published[-1] == ZERO_TWIST


def test_worker_teardown_rejects_timer_snapshot_after_final_zero():
    published = []
    gate = GenerationPublishGate(published.append, allow_nonzero=True)
    observed = gate.observe_generation()
    entered = threading.Barrier(2)
    resume = threading.Event()

    def stale_timer():
        entered.wait()
        resume.wait(timeout=2.0)
        gate.handle_timer(0.1, observed)

    worker = threading.Thread(target=stale_timer)
    worker.start()
    entered.wait()
    gate.shutdown()
    resume.set()
    worker.join(timeout=2.0)
    assert published == [ZERO_TWIST]

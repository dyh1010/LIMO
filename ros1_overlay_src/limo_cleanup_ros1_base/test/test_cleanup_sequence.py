from pathlib import Path
import sys

import pytest


PACKAGE_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / 'src'))

from limo_cleanup_ros1_base.cleanup_sequence import next_cleanup_state  # noqa: E402


def test_only_producer_zero_driver_safety_order_completes():
    state = 'running'
    for event in (
            'producers_stopped', 'zero_proven', 'driver_gone',
            'stop_safety', 'cleanup_complete'):
        state = next_cleanup_state(state, event)
    assert state == 'complete'


def test_driver_failure_stickily_forbids_stopping_safety_chain():
    state = next_cleanup_state('running', 'producers_stopped')
    state = next_cleanup_state(state, 'zero_proven')
    state = next_cleanup_state(state, 'driver_failed')
    assert state == 'retain_safety'
    for event in ('stop_safety', 'cleanup_complete', 'driver_gone'):
        with pytest.raises(RuntimeError):
            next_cleanup_state(state, event)


def test_early_failure_without_driver_can_still_clean_owned_safety_nodes():
    state = next_cleanup_state('running', 'producers_stopped')
    state = next_cleanup_state(state, 'driver_absent')
    state = next_cleanup_state(state, 'stop_safety')
    assert next_cleanup_state(state, 'cleanup_complete') == 'complete'

"""Pure shutdown state machine that forbids dismantling a live-driver guard."""


TRANSITIONS = {
    ('running', 'producers_stopped'): 'producers_stopped',
    ('producers_stopped', 'zero_proven'): 'zero_proven',
    ('producers_stopped', 'driver_absent'): 'driver_gone',
    ('producers_stopped', 'driver_gone_unproven'): 'driver_gone',
    ('producers_stopped', 'driver_failed'): 'retain_safety',
    ('zero_proven', 'driver_gone'): 'driver_gone',
    ('zero_proven', 'driver_failed'): 'retain_safety',
    ('driver_gone', 'stop_safety'): 'safety_stopped',
    ('safety_stopped', 'cleanup_complete'): 'complete',
}


def next_cleanup_state(state, event):
    """Advance only through the fail-closed producer/zero/driver/safety order."""
    try:
        return TRANSITIONS[(state, event)]
    except KeyError as error:
        raise RuntimeError(
            'unsafe cleanup transition: {} + {}'.format(state, event)) from error

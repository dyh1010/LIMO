"""Strict JSON parsing helpers for safety-critical bridge messages."""

import json


def _reject_duplicate_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key: {}'.format(key))
        result[key] = value
    return result


def _reject_nonfinite_constant(value):
    raise ValueError('non-finite JSON constant: {}'.format(value))


def loads_strict(payload, description):
    """Parse JSON while rejecting duplicate keys and non-JSON constants."""
    try:
        return json.loads(
            payload,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_nonfinite_constant,
        )
    except (TypeError, ValueError, RecursionError) as error:
        raise ValueError('{} must be valid strict JSON'.format(
            description)) from error

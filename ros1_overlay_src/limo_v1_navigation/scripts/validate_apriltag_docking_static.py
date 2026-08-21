#!/usr/bin/env python3
"""Offline validator for the AprilTag docking inventory and static observations."""

from __future__ import print_function

import argparse
import json
import sys
from pathlib import Path


PACKAGE_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / 'src'))

from limo_v1_navigation.apriltag_docking_contract import (  # noqa: E402
    ContractError,
    validate_calibration,
    validate_inventory,
    validate_observation,
)


def _reject_constant(value):
    raise ValueError('nonfinite_json:' + value)


def _reject_duplicate(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate_json_key:' + key)
        result[key] = value
    return result


def load_json(path):
    raw = Path(path).read_text(encoding='utf-8')
    decoder = json.JSONDecoder(
        parse_constant=_reject_constant, object_pairs_hook=_reject_duplicate)
    value, end = decoder.raw_decode(raw)
    if raw[end:].strip():
        raise ValueError('trailing_json_data')
    return value


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--inventory', required=True)
    parser.add_argument('--observations', required=True)
    parser.add_argument('--calibration', required=True)
    parser.add_argument('--host-now-ns', type=int, required=True,
                        help='trusted consumer host time; never detector supplied')
    parser.add_argument('--max-observation-age-ns', type=int, required=True)
    args = parser.parse_args(argv)
    try:
        inventory = load_json(args.inventory)
        observations = load_json(args.observations)
        calibration = load_json(args.calibration)
        if set(inventory) != {
                'schema_version', 'fixed_field_tags',
                'movable_object_tags', 'contract'}:
            raise ContractError('inventory_fields_invalid')
        if inventory.get('schema_version') != (
                'limo_apriltag_docking_inventory/v1'):
            raise ContractError('inventory_schema_invalid')
        if set(observations) != {'schema_version', 'observations'}:
            raise ContractError('observations_fields_invalid')
        if observations.get('schema_version') != (
                'limo_apriltag_docking_static_observations/v1'):
            raise ContractError('observations_schema_invalid')
        if (not isinstance(observations.get('observations'), list)
                or not observations['observations']):
            raise ContractError('observations_missing')
        if (not isinstance(args.host_now_ns, int)
                or isinstance(args.host_now_ns, bool)
                or args.host_now_ns <= 0):
            raise ContractError('host_now_ns_missing')
        if (not isinstance(args.max_observation_age_ns, int)
                or isinstance(args.max_observation_age_ns, bool)
                or args.max_observation_age_ns <= 0):
            raise ContractError('max_observation_age_invalid')
        counts = validate_inventory(
            inventory['fixed_field_tags'] + inventory['movable_object_tags'])
        calibration_result = validate_calibration(calibration)
        accepted = 0
        aborted = []
        for record in observations['observations']:
            try:
                validate_observation(
                    record, host_now_ns=args.host_now_ns,
                    max_age_ns=args.max_observation_age_ns)
                accepted += 1
            except ContractError as error:
                aborted.append(str(error))
        result = {
            'schema_version': 'limo_apriltag_docking_static_validation/v1',
            'decision': 'ACCEPT' if accepted and not aborted else 'ABORT',
            'inventory': counts,
            'calibration': calibration_result,
            'freshness_owner': 'host_now_ns',
            'host_now_ns': args.host_now_ns,
            'max_observation_age_ns': args.max_observation_age_ns,
            'accepted_observations': accepted,
            'aborted_observation_reasons': aborted,
            'motion_authorized': False,
        }
    except (KeyError, TypeError, ValueError, ContractError) as error:
        result = {
            'schema_version': 'limo_apriltag_docking_static_validation/v1',
            'decision': 'ABORT',
            'failure_reason': str(error),
            'motion_authorized': False,
        }
    print(json.dumps(result, sort_keys=True, separators=(',', ':'),
                     allow_nan=False))
    return 0 if result['decision'] == 'ACCEPT' else 3


if __name__ == '__main__':
    sys.exit(main())

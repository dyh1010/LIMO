"""Host-owned bridge from visual camera observations to V1 map-tag inputs.

The adapter is deliberately pure software.  It accepts no caller-supplied
``tag_pose_map``; a map pose is derived only after one record binds the visual
observation, trusted TF snapshot, calibration bytes, mapping authority, and
requested target.
"""

from __future__ import absolute_import

from .apriltag_docking_contract import (
    CAMERA_FRAME, ContractError, OBJECT_FAMILY, SIDES)
from .tag_docking_adapter import (
    SOURCE_BUNDLE_SCHEMA,
    AdapterError, adapt_observation_to_map_pose, canonical_calibration_payload,
    calibration_identity_from_calibration, canonical_observation_sha256)


HOST_RECORD_SCHEMA = 'limo_apriltag_host_observation_record/v1'


class AdapterContractError(ValueError):
    pass


def _require(condition, reason):
    if not condition:
        raise AdapterContractError(reason)


def _exact(value, keys, reason):
    _require(isinstance(value, dict) and set(value) == set(keys), reason)
    return value


def calibration_identity(calibration):
    """Use the sealed adapter's canonical base-to-camera geometry identity."""
    try:
        return calibration_identity_from_calibration(calibration)
    except (AdapterError, ContractError) as error:
        raise AdapterContractError(str(error))


def validate_mapping_authority(inventory, v1_config):
    """Bind V1 object tags to visual inventory, returning the only ID map."""
    _exact(inventory, ('schema_version', 'fixed_field_tags',
                       'movable_object_tags', 'contract'),
           'mapping_authority_fields_invalid')
    _require(inventory['schema_version'] == 'limo_apriltag_docking_inventory/v1',
             'mapping_authority_schema_invalid')
    visual = {}
    for expected_tag_id, tag in enumerate(inventory['movable_object_tags']):
        _exact(tag, ('family', 'id', 'object_index', 'side'),
               'mapping_authority_tag_invalid')
        _require(tag['family'] == OBJECT_FAMILY and type(tag['id']) is int and
                 tag['id'] == expected_tag_id and
                 type(tag['object_index']) is int and tag['id'] not in visual,
                 'mapping_authority_tag_invalid')
        _require(tag['object_index'] == tag['id'] // 4 and
                 tag['side'] == SIDES[tag['id'] % 4],
                 'mapping_authority_mapping_invalid')
        visual[tag['id']] = {'object_index': tag['object_index'],
                             'side': tag['side']}
    _require(set(visual) == set(range(12)), 'mapping_authority_coverage_invalid')
    _require(isinstance(v1_config, dict) and isinstance(v1_config.get('objects'), list),
             'v1_objects_missing')
    v1 = {}
    for expected_object_id, obj in enumerate(v1_config['objects']):
        _require(isinstance(obj, dict) and type(obj.get('object_id')) is int
                 and obj['object_id'] == expected_object_id
                 and isinstance(obj.get('tags'), list)
                 and len(obj['tags']) == 4, 'v1_object_invalid')
        for expected_side_index, tag in enumerate(obj['tags']):
            _exact(tag, ('family', 'id', 'side_index', 'side_label'),
                   'v1_tag_invalid')
            _require(tag['family'] == OBJECT_FAMILY and type(tag['id']) is int and
                     tag['id'] == expected_object_id * 4 + expected_side_index and
                     type(tag['side_index']) is int and
                     tag['side_index'] == expected_side_index and
                     tag['id'] not in v1,
                     'v1_tag_invalid')
            _require(tag['side_index'] in range(4) and
                     tag['side_label'] == SIDES[tag['side_index']],
                     'v1_side_vocabulary_invalid')
            v1[tag['id']] = {'object_index': obj['object_id'],
                              'side': tag['side_label']}
    _require(v1 == visual, 'cross_contract_mapping_mismatch')
    return visual


def derive_bound_tag_pose(host_record, inventory, v1_config, host_now_ns,
                          max_age_ns=250000000):
    """Return V1's opaque adapter output; raw map poses are not an API.

    The record ID and canonical observation hash bind the expected tag to the
    exact TF snapshot.  The sealed V1 adapter then validates source bytes,
    transform frames, calibration identity and freshness before deriving a
    map-frame pose which only V1 policy may consume.
    """
    _exact(host_record, ('schema_version', 'record_id', 'expected_target',
                         'observation', 'tf_snapshot', 'calibration',
                         'calibration_identity'), 'host_record_fields_invalid')
    _require(host_record['schema_version'] == HOST_RECORD_SCHEMA,
             'host_record_schema_invalid')
    record_id = host_record['record_id']
    _require(isinstance(record_id, str) and record_id.strip(), 'record_id_invalid')
    expected = host_record['expected_target']
    _exact(expected, ('family', 'id'), 'expected_target_invalid')
    mapping = validate_mapping_authority(inventory, v1_config)
    _require(expected['family'] == OBJECT_FAMILY and type(expected['id']) is int and
             expected['id'] in mapping,
             'expected_target_invalid')
    expected_identity = calibration_identity(host_record['calibration'])
    _require(host_record['calibration_identity'] == expected_identity,
             'calibration_identity_mismatch')

    _require(isinstance(host_record['observation'], dict), 'observation_invalid')
    digest = canonical_observation_sha256(host_record['observation'])
    tf = host_record['tf_snapshot']
    _exact(tf, ('record_id', 'observation_sha256', 'timestamp_ns',
                'map_to_base_link', 'base_link_to_camera'),
           'tf_snapshot_fields_invalid')
    _require(tf['record_id'] == record_id, 'tf_record_id_mismatch')
    _require(tf['observation_sha256'] == digest, 'tf_observation_source_swap')
    _require(tf['timestamp_ns'] == host_record['observation'].get('timestamp_ns'),
             'tf_timestamp_mismatch')
    source_bundle = {
        'schema_version': SOURCE_BUNDLE_SCHEMA,
        'observation_sha256': digest,
        'observation': host_record['observation'],
        'tf_geometry': {
            'observation_sha256': digest,
            'timestamp_ns': tf['timestamp_ns'],
            'map_to_base_link': tf['map_to_base_link'],
            'base_link_to_camera': tf['base_link_to_camera'],
        },
        'calibration_payload': canonical_calibration_payload(
            host_record['calibration']),
        'calibration_identity': expected_identity,
    }
    try:
        result = adapt_observation_to_map_pose(
            source_bundle, host_now_ns=host_now_ns, max_age_ns=max_age_ns,
            expected_calibration_identity=expected_identity)
    except (AdapterError, ContractError) as error:
        raise AdapterContractError(str(error))
    _require(result.target_family == expected['family'] and
             result.target_id == expected['id'], 'source_target_mismatch')
    _require(result.object_id == mapping[expected['id']]['object_index'] and
             result.side_label == mapping[expected['id']]['side'],
             'cross_contract_mapping_mismatch')
    return result

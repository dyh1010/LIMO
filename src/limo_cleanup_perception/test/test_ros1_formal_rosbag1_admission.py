"""Host-side, ROS-independent tests for formal rosbag1 consumer admission."""

import copy
import hashlib
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


WORKSPACE = Path(__file__).resolve().parents[3]
OVERLAY = WORKSPACE / 'ros1_overlay_src' / 'limo_cleanup_ros1_perception'
OVERLAY_SOURCE = OVERLAY / 'src'
_IMPORT_PATH_BEFORE = list(sys.path)
try:
    if str(OVERLAY_SOURCE) not in sys.path:
        sys.path.insert(0, str(OVERLAY_SOURCE))
    from limo_cleanup_ros1_perception import (  # noqa: E402
        rosbag1_rgbd_indexer as INDEXER)
    from limo_cleanup_ros1_perception import (  # noqa: E402
        typed_raw_binding as BINDING)
finally:
    sys.path[:] = _IMPORT_PATH_BEFORE


FORMAL_MANIFEST = (
    OVERLAY / 'config' / 'dabai_ros1_formal_four_scene_six_topics_v1.json')
BASE_STAMP_NS = 1_700_000_000_000_000_000
FRAME_PERIOD_NS = 33_000_000
FRAME_COUNT = 30
ROLES = (
    'rgb', 'raw_depth', 'rgb_camera_info', 'depth_camera_info',
    'tf', 'tf_static')
STREAM_ROLES = ROLES[:4]
ROSBAG1_V2_MAGIC = b'#ROSBAG V2.0\n'


def _rosbag1_v2_fixture(payload=b'fixture'):
    field = b'op=\x03'
    header = len(field).to_bytes(4, 'little') + field
    return b''.join((
        ROSBAG1_V2_MAGIC,
        len(header).to_bytes(4, 'little'), header,
        len(payload).to_bytes(4, 'little'), payload))


def _canonical_sha256(value):
    encoded = json.dumps(
        value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
        allow_nan=False).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def _header(stamp_ns, frame_id):
    return {'stamp_ns': stamp_ns, 'frame_id': frame_id}


def _image(stamp_ns, encoding):
    bytes_per_pixel = 3 if encoding == 'bgr8' else 2
    width = 640
    height = 480
    step = width * bytes_per_pixel
    return {
        'header': _header(stamp_ns, 'camera_color_optical_frame'),
        'height': height,
        'width': width,
        'encoding': encoding,
        'is_bigendian': 0,
        'step': step,
        'data_length': step * height,
    }


def _camera_info(stamp_ns, frame_id='camera_color_optical_frame'):
    width = 640
    height = 480
    fx = 500.0
    fy = 501.0
    cx = width / 2.0
    cy = height / 2.0
    return {
        'header': _header(stamp_ns, frame_id),
        'height': height,
        'width': width,
        'distortion_model': 'plumb_bob',
        'D': [0.01, -0.02, 0.0, 0.0, 0.0],
        'K': [fx, 0.0, cx, 0.0, fy, cy, 0.0, 0.0, 1.0],
        'R': [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0],
        'P': [fx, 0.0, cx, 0.0, 0.0, fy, cy, 0.0,
              0.0, 0.0, 1.0, 0.0],
        'binning_x': 0,
        'binning_y': 0,
        'roi': {
            'x_offset': 0,
            'y_offset': 0,
            'height': 0,
            'width': 0,
            'do_rectify': False,
        },
    }


def _transform(stamp_ns, parent, child):
    return {
        'header': _header(stamp_ns, parent),
        'child_frame_id': child,
        'translation_m': [0.0, 0.0, 0.0],
        'rotation_xyzw': [0.0, 0.0, 0.0, 1.0],
    }


def _connection_header(topic):
    return {
        'topic': topic['topic'],
        'type': topic['type'],
        'md5sum': topic['md5sum'],
        'callerid': topic['callerid'],
        'latching': '1' if topic['latching'] else '0',
    }


def _raw_message(connection_id, record_stamp, payload, decoded):
    return {
        'connection_id': connection_id,
        'record_timestamp_ns': record_stamp,
        'serialized_payload': payload,
        'decoded': decoded,
    }


def _attach_headers(connections, messages):
    by_id = {}
    for connection in connections:
        header = _connection_header(connection)
        connection['connection_header'] = header
        connection['connection_header_sha256'] = _canonical_sha256(header)
        connection['connection_header_violations'] = []
        by_id[connection['connection_id']] = connection
    for message in messages:
        connection = by_id[message['connection_id']]
        message['connection_header'] = copy.deepcopy(
            connection['connection_header'])
        message['connection_header_sha256'] = connection[
            'connection_header_sha256']
        message['connection_header_violations'] = []
        message['decode_error'] = None


def _records(frame_count=FRAME_COUNT):
    manifest = INDEXER.load_formal_manifest(FORMAL_MANIFEST)
    connections = []
    ids = {}
    for connection_id, role in enumerate(ROLES, 1):
        topic = manifest['topics_by_role'][role]
        ids[role] = connection_id
        connections.append({
            'connection_id': connection_id,
            'topic': topic['name'],
            'type': topic['type'],
            'md5sum': topic['md5sum'],
            'callerid': topic['callerid'],
            'latching': topic['latching'],
        })
    messages = [
        _raw_message(
            ids['tf_static'], BASE_STAMP_NS + 1_000_000,
            b'camera-static-tree', {
                'transforms': [_transform(
                    0, 'camera_link', 'camera_color_optical_frame')]}),
        _raw_message(
            ids['tf'], BASE_STAMP_NS + 5_000_000,
            b'camera-dynamic-tree', {
                'transforms': [_transform(
                    BASE_STAMP_NS, 'camera_root', 'camera_link')]}),
        _raw_message(
            ids['depth_camera_info'], BASE_STAMP_NS + 2_000_000,
            b'old-latched-depth-info',
            _camera_info(BASE_STAMP_NS - 300_000_000_000, '')),
    ]
    for index in range(frame_count):
        stamp = BASE_STAMP_NS + index * FRAME_PERIOD_NS
        messages.extend([
            _raw_message(
                ids['rgb'], stamp + 10_000_000,
                ('rgb-{}'.format(index)).encode('ascii'),
                _image(stamp, 'bgr8')),
            _raw_message(
                ids['raw_depth'], stamp + 11_000_000,
                ('depth-{}'.format(index)).encode('ascii'),
                _image(stamp, '16UC1')),
            _raw_message(
                ids['rgb_camera_info'], stamp + 12_000_000,
                ('rgb-info-{}'.format(index)).encode('ascii'),
                _camera_info(stamp)),
            _raw_message(
                ids['depth_camera_info'], stamp + 13_000_000,
                ('depth-info-{}'.format(index)).encode('ascii'),
                _camera_info(stamp)),
        ])
    _attach_headers(connections, messages)
    return connections, messages


class _FakeReader:
    def __init__(self, connections, messages):
        self._connections = connections
        self._messages = messages

    def read(self):
        return copy.deepcopy(self._connections), copy.deepcopy(self._messages)


def _case(root, frame_count=FRAME_COUNT):
    root = Path(root)
    bag = root / 'formal-camera-only.bag'
    bag.write_bytes(_rosbag1_v2_fixture(b'formal-rosbag1-fixture-v1'))
    connections, messages = _records(frame_count)
    source_capture = {
        'path': str(bag.resolve()),
        'size_bytes': bag.stat().st_size,
        'sha256': INDEXER.sha256_file(bag),
    }
    report = INDEXER.inspect_records(
        connections, messages, 'formal-capture-background', 'background',
        INDEXER.load_formal_manifest(FORMAL_MANIFEST),
        source_capture=source_capture,
        mode=INDEXER.FORMAL_CAMERA_ONLY_MODE)
    assert report['formal_acceptance'] is True, report.get('failures')
    index_path = root / 'formal-index.json'
    index_path.write_text(
        json.dumps(report, sort_keys=True), encoding='utf-8')
    frames_path = root / 'frames.jsonl'
    frames_path.write_text('{}\n', encoding='utf-8')
    collector_path = root / 'collector.json'
    collector_path.write_text('{}\n', encoding='utf-8')
    return {
        'bag': bag,
        'connections': connections,
        'messages': messages,
        'report': report,
        'context': {
            'index_path': index_path,
            'raw_bag_path': bag,
            'frames_path': frames_path,
            'collector_path': collector_path,
            'topic_manifest_path': FORMAL_MANIFEST,
        },
    }


def _validate(case, report=None, rewrite=True, reader_error=None):
    value = copy.deepcopy(case['report'] if report is None else report)
    if rewrite:
        Path(case['context']['index_path']).write_text(
            json.dumps(value, sort_keys=True), encoding='utf-8')
    failures = []
    production_inspect_bag = INDEXER.inspect_bag
    def algorithm_redecode(
            path, capture_id, scene, manifest_path=None,
            reader_factory=None, mode=INDEXER.FORMAL_MODE,
            test_only=False):
        assert reader_factory is None
        assert test_only is False
        if reader_error is not None:
            return production_inspect_bag(
                path, capture_id, scene, manifest_path,
                mode=mode)
        source_path = Path(path).resolve(strict=True)
        return INDEXER.inspect_records(
            case['connections'], case['messages'], capture_id, scene,
            INDEXER.load_formal_manifest(manifest_path),
            source_capture={
                'path': str(source_path),
                'size_bytes': source_path.stat().st_size,
                'sha256': INDEXER.sha256_file(source_path),
            }, mode=mode)

    with patch.object(INDEXER, 'inspect_bag', algorithm_redecode):
        bundles, identities, manifest = BINDING._validate_index(
            value, case['context'], failures)
    return bundles, identities, manifest, sorted(set(failures))


def test_exact_formal_index_is_redecoded_and_independently_recomputed():
    with TemporaryDirectory() as directory:
        case = _case(directory)
        bundles, identities, manifest, failures = _validate(case)
    assert failures == []
    assert len(bundles) == FRAME_COUNT
    assert identities['raw_bag_path']['sha256'] == case[
        'report']['source_capture']['sha256']
    assert manifest['manifest_id'].endswith('six-topics-v1')
    assert case['report']['message_accounting']['closure_valid'] is True
    assert case['report']['isolated_old_latched_camera_info_count'] == 1
    assert case['report']['aligned_stream_contract'] == {
        'required': True,
        'frame_id': 'camera_color_optical_frame',
        'width': 640,
        'height': 480,
        'validated_bundle_count': FRAME_COUNT,
    }


def test_formal_bag_reader_injection_and_test_only_never_enter_denominator():
    with TemporaryDirectory() as directory:
        root = Path(directory)
        bag = root / '51-byte-formal-shell.bag'
        bag.write_bytes(_rosbag1_v2_fixture(b'x' * 22))
        assert bag.stat().st_size == 51
        calls = []

        def factory(_path):
            calls.append(str(_path))
            raise AssertionError('formal injected reader must not execute')

        injected = INDEXER.inspect_bag(
            bag, 'formal-injected', 'background', FORMAL_MANIFEST,
            reader_factory=factory, mode=INDEXER.FORMAL_CAMERA_ONLY_MODE)
        test_only = INDEXER.inspect_bag(
            bag, 'formal-test-only', 'background', FORMAL_MANIFEST,
            reader_factory=factory, mode=INDEXER.FORMAL_CAMERA_ONLY_MODE,
            test_only=True)
    assert injected['failures'] == [
        INDEXER.FORMAL_READER_FACTORY_FORBIDDEN]
    assert test_only['failures'] == [
        INDEXER.FORMAL_TEST_ONLY_READER_FORBIDDEN]
    for report in (injected, test_only):
        assert report['inspection_passed'] is False
        assert report['formal_acceptance'] is False
        assert report['not_in_four_scene_denominator'] is True
        assert report['delivery_ready'] is False
    assert calls == []


def test_production_binding_redecode_requires_unimplemented_fresh_reader_gate():
    with TemporaryDirectory() as directory:
        case = _case(directory)
        failures = []
        bundles, _identities, _manifest = BINDING._validate_index(
            case['report'], case['context'], failures)
    assert bundles
    assert 'raw_index_formal_redecode_failed' in failures
    assert 'raw_index_redecode_mismatch' in failures


def test_stored_field_tamper_is_caught_by_exact_bag_redecode():
    with TemporaryDirectory() as directory:
        case = _case(directory)
        report = copy.deepcopy(case['report'])
        report['capture_window']['header_end_ns'] += 1
        _bundles, _identities, _manifest, failures = _validate(case, report)
    assert 'raw_index_redecode_mismatch' in failures
    assert 'raw_index_capture_window_invalid' in failures


def test_missing_rosbag_api_fails_closed_without_accepting_stored_counts():
    with TemporaryDirectory() as directory:
        case = _case(directory)
        _bundles, _identities, _manifest, failures = _validate(
            case, reader_error=ImportError('rosbag unavailable'))
    assert 'raw_index_formal_redecode_failed' in failures
    assert 'raw_index_redecode_mismatch' in failures


def test_json_sqlite_and_truncated_magic_renames_fail_before_reader():
    payloads = {
        'json': b'{"schema_version":1}\n',
        'sqlite': b'SQLite format 3\x00not-a-rosbag',
        'truncated': ROSBAG1_V2_MAGIC,
    }
    with TemporaryDirectory() as directory:
        root = Path(directory)
        for name, payload in payloads.items():
            bag = root / (name + '.bag')
            bag.write_bytes(payload)
            reader_calls = []

            def reader_factory(_path):
                reader_calls.append(str(_path))
                raise AssertionError('reader must not run before envelope gate')

            report = INDEXER.inspect_bag(
                bag, 'formal-capture-' + name, 'background',
                FORMAL_MANIFEST, reader_factory=reader_factory,
                mode=INDEXER.FORMAL_CAMERA_ONLY_MODE)
            assert report['inspection_passed'] is False
            assert report['formal_acceptance'] is False
            assert report['delivery_ready'] is False
            assert report['not_in_four_scene_denominator'] is True
            expected = (
                'rosbag1_v2_envelope_invalid'
                if name == 'truncated' else 'rosbag1_v2_magic_invalid')
            assert expected in report['failures'], (name, report)
            assert reader_calls == []


def test_source_admitted_isolated_role_accounting_must_close_exactly():
    with TemporaryDirectory() as directory:
        case = _case(directory)
        report = copy.deepcopy(case['report'])
        report['message_accounting']['admitted_message_count'] += 1
        _bundles, _identities, _manifest, failures = _validate(case, report)
    assert 'raw_index_message_accounting_invalid' in failures


def test_old_latched_ledger_is_recomputed_from_the_isolated_message():
    with TemporaryDirectory() as directory:
        case = _case(directory)
        report = copy.deepcopy(case['report'])
        report['isolated_old_latched_camera_info'][0][
            'serialized_sha256'] = '0' * 64
        _bundles, _identities, _manifest, failures = _validate(case, report)
    assert 'raw_index_isolation_ledger_invalid' in failures


def test_isolated_camera_info_cannot_be_in_a_fresh_bundle():
    with TemporaryDirectory() as directory:
        case = _case(directory)
        report = copy.deepcopy(case['report'])
        isolated_id = report['isolated_old_latched_camera_info'][0][
            'message_id']
        report['accepted_bundles'][0]['depth_camera_info'] = isolated_id
        _bundles, _identities, _manifest, failures = _validate(case, report)
    assert 'raw_index_isolated_message_in_bundle' in failures
    assert 'raw_index_bundle_invalid' in failures


def test_all_four_streams_must_share_one_frame_and_grid():
    with TemporaryDirectory() as directory:
        case = _case(directory)
        report = copy.deepcopy(case['report'])
        for message in report['messages']:
            if (message['role'] == 'raw_depth'
                    and message['isolated'] is False):
                message['decoded']['header'][
                    'frame_id'] = 'camera_depth_frame'
        report['streams']['raw_depth']['frame_id'] = 'camera_depth_frame'
        _bundles, _identities, _manifest, failures = _validate(case, report)
    assert 'raw_index_stream_alignment_invalid' in failures
    assert 'raw_index_connection_or_message_invalid' in failures


def test_twenty_nine_bundles_cannot_enter_the_scene_denominator():
    with TemporaryDirectory() as directory:
        case = _case(directory)
        report = copy.deepcopy(case['report'])
        report['accepted_bundles'].pop()
        report['accepted_bundle_count'] = 29
        report['rejected_rgb_count'] = 1
        report['rejection_reasons'] = {
            'missing_stream': 1, 'over_sync_span': 0}
        report['unmatched_message_count_by_stream'] = {
            role: 1 for role in STREAM_ROLES}
        report['total_unpaired_message_count'] = 4
        report['total_unpaired_rate'] = 4 / 120
        report['unique_header_pair_count'] = 29
        report['formal_contract_valid_pair_count'] = 29
        report['aligned_stream_contract']['validated_bundle_count'] = 29
        _bundles, _identities, _manifest, failures = _validate(case, report)
    assert 'raw_index_bundle_invalid' in failures
    assert 'raw_index_bundle_freshness_invalid' in failures


def test_duplicate_bundle_or_zero_denominator_fails_closed():
    with TemporaryDirectory() as directory:
        root = Path(directory)
        for name in ('duplicate', 'zero'):
            case_root = root / name
            case_root.mkdir()
            case = _case(case_root)
            report = copy.deepcopy(case['report'])
            if name == 'duplicate':
                report['accepted_bundles'][1] = copy.deepcopy(
                    report['accepted_bundles'][0])
            else:
                report['accepted_bundles'] = []
                report['accepted_bundle_count'] = 0
                report['unique_header_pair_count'] = 0
                report['formal_contract_valid_pair_count'] = 0
                report['aligned_stream_contract'][
                    'validated_bundle_count'] = 0
            _bundles, _identities, _manifest, failures = _validate(
                case, report)
            assert 'raw_index_bundle_invalid' in failures, (name, failures)
            assert 'raw_index_bundle_freshness_invalid' in failures, (
                name, failures)


def test_diagnostic_short_shared_mixed_and_nonformal_flags_are_rejected():
    mutations = (
        ('mode', 'sensor_only_short_sample'),
        ('report_kind', 'ros1_shared_graph_diagnostic_manifest'),
        ('inspection_scope', 'diagnostic_shared_graph'),
        ('formal_acceptance', False),
        ('shared_graph', True),
        ('mixed_tf', True),
        ('not_in_four_scene_denominator', True),
    )
    with TemporaryDirectory() as directory:
        root = Path(directory)
        for field, value in mutations:
            case_root = root / field
            case_root.mkdir()
            case = _case(case_root)
            report = copy.deepcopy(case['report'])
            report[field] = value
            _bundles, _identities, _manifest, failures = _validate(
                case, report)
            assert ('raw_index_not_formal' in failures
                    or 'raw_index_shared_or_mixed' in failures), (
                        field, failures)


def test_legacy_or_extra_synthetic_schema_never_becomes_formal():
    with TemporaryDirectory() as directory:
        root = Path(directory)
        for name in ('legacy', 'synthetic'):
            case_root = root / name
            case_root.mkdir()
            case = _case(case_root)
            report = copy.deepcopy(case['report'])
            if name == 'legacy':
                report['mode'] = 'sensor_only_short_sample'
                report['report_kind'] = 'ros1_sensor_only_short_sample_index'
                report['inspection_scope'] = 'sensor_only_short_sample'
                report['formal_acceptance'] = False
                report['not_in_four_scene_denominator'] = True
                for key in (
                        'capture_window', 'message_accounting',
                        'isolated_old_latched_camera_info_count',
                        'isolated_old_latched_camera_info',
                        'aligned_stream_contract', 'failure_details'):
                    report.pop(key)
            else:
                report['synthetic_test_only'] = True
            _bundles, _identities, _manifest, failures = _validate(
                case, report)
            if name == 'legacy':
                assert 'raw_index_formal_schema_required' in failures
            else:
                assert 'raw_index_schema_invalid' in failures


def test_raw_bag_identity_drift_is_rejected_before_delivery():
    with TemporaryDirectory() as directory:
        case = _case(directory)
        case['bag'].write_bytes(b'changed-after-index')
        _bundles, _identities, _manifest, failures = _validate(case)
    assert 'raw_index_source_capture_mismatch' in failures
    assert 'raw_index_redecode_mismatch' in failures


def test_in_memory_index_must_equal_the_exclusive_stored_index():
    with TemporaryDirectory() as directory:
        case = _case(directory)
        report = copy.deepcopy(case['report'])
        report['capture_id'] = 'foreign-capture'
        _bundles, _identities, _manifest, failures = _validate(
            case, report, rewrite=False)
    assert 'raw_index_stored_content_mismatch' in failures


def test_test_only_path_can_never_authorize_formal_or_delivery():
    with TemporaryDirectory() as directory:
        case = _case(directory)
        replacement = lambda _path, diagnostic=False: _FakeReader(  # noqa: E731
            case['connections'], case['messages'])
        with patch.object(INDEXER, 'Rosbag1Reader', replacement):
            result = BINDING.create_binding(
                case['report'], [], {}, test_only=True,
                artifact_context=case['context'])
    assert result['validated_pass'] is False
    assert result['formal_acceptance'] is False
    assert result['not_in_four_scene_denominator'] is True
    assert result['delivery_ready'] is False
    assert 'synthetic_test_only_forbidden' in result['failures']


def test_consumer_source_has_no_ros_graph_or_control_publisher():
    source = Path(BINDING.__file__).read_text(encoding='utf-8')
    for token in (
            'import rospy', 'rospy.init_node', 'rospy.Publisher',
            'rospy.Subscriber', 'rospy.Service', 'create_publisher(',
            '.publish(', 'Twist(', 'MoveBaseAction', '/cmd_vel'):
        assert token not in source

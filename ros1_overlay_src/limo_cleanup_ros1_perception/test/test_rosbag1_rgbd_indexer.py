"""ROS-independent fail-closed tests for the ROS1 rosbag1 indexer."""

import copy
import hashlib
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / 'src'))

from limo_cleanup_ros1_perception.rosbag1_rgbd_indexer import (  # noqa: E402
    DIAGNOSTIC_MODE,
    EXPECTED_MANIFEST_SHA256,
    FORMAL_CAMERA_ONLY_MODE,
    FORMAL_READER_ADMISSION_UNAVAILABLE,
    FORMAL_READER_FACTORY_FORBIDDEN,
    FORMAL_TEST_ONLY_READER_FORBIDDEN,
    InspectionError,
    Rosbag1Reader,
    inspect_bag,
    load_manifest,
    main,
    sha256_file,
    inspect_records,
)
from limo_cleanup_ros1_perception import rosbag1_rgbd_indexer as INDEXER  # noqa: E402


MANIFEST_PATH = (
    PACKAGE_ROOT / 'config' / 'dabai_ros1_raw_rgbd_six_topics_v1.json')
FORMAL_MANIFEST_PATH = (
    PACKAGE_ROOT / 'config'
    / 'dabai_ros1_formal_four_scene_six_topics_v1.json')
FRAME_COUNT = 30
BASE_STAMP_NS = 1_700_000_000_000_000_000
FRAME_PERIOD_NS = 33_000_000
ROSBAG1_V2_MAGIC = b'#ROSBAG V2.0\n'


def _rosbag1_v2_fixture(payload=b'fixture', op=b'\x03'):
    field = b'op=' + op
    header = len(field).to_bytes(4, 'little') + field
    return b''.join((
        ROSBAG1_V2_MAGIC,
        len(header).to_bytes(4, 'little'), header,
        len(payload).to_bytes(4, 'little'), payload))


def _header(stamp_ns, frame_id):
    return {'stamp_ns': stamp_ns, 'frame_id': frame_id}


def _image(stamp_ns, frame_id, width, height, encoding):
    bytes_per_pixel = {
        'bgr8': 3, 'rgb8': 3, '16UC1': 2, '32FC1': 4}[encoding]
    step = width * bytes_per_pixel
    return {
        'header': _header(stamp_ns, frame_id),
        'height': height,
        'width': width,
        'encoding': encoding,
        'is_bigendian': 0,
        'step': step,
        'data_length': step * height,
    }


def _camera_info(stamp_ns, frame_id, width, height):
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
        'P': [fx, 0.0, cx, 0.0, 0.0, fy, cy, 0.0, 0.0, 0.0, 1.0, 0.0],
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


def _transform(stamp_ns, parent, child, translation=(0.0, 0.0, 0.0)):
    return {
        'header': _header(stamp_ns, parent),
        'child_frame_id': child,
        'translation_m': list(translation),
        'rotation_xyzw': [0.0, 0.0, 0.0, 1.0],
    }


def _message(connection_id, record_stamp, payload, decoded):
    return {
        'connection_id': connection_id,
        'record_timestamp_ns': record_stamp,
        'serialized_payload': payload,
        'decoded': decoded,
    }


def _fixture(frame_count=FRAME_COUNT):
    manifest = load_manifest(MANIFEST_PATH)
    connections = []
    connection_ids = {}
    for connection_id, role in enumerate(
            ('rgb', 'raw_depth', 'rgb_camera_info', 'depth_camera_info',
             'tf', 'tf_static'), start=1):
        topic = manifest['topics_by_role'][role]
        connection_ids[role] = connection_id
        connections.append({
            'connection_id': connection_id,
            'topic': topic['name'],
            'type': topic['type'],
            'md5sum': topic['md5sum'],
            'callerid': topic['callerid'],
            'latching': topic['latching'],
        })
    messages = [
        _message(
            connection_ids['tf_static'], BASE_STAMP_NS + 1_000_000,
            b'tf-static-camera-tree', {
                'transforms': [
                    _transform(
                        0, 'camera_link', 'camera_depth_frame',
                        (0.0, 0.0, 0.01)),
                    _transform(
                        0, 'camera_depth_frame',
                        'camera_depth_optical_frame'),
                    _transform(
                        0, 'camera_link', 'camera_color_frame',
                        (0.02, 0.0, 0.0)),
                    _transform(
                        0, 'camera_color_frame',
                        'camera_color_optical_frame'),
                ]})]
    for index in range(frame_count):
        stamp = BASE_STAMP_NS + index * FRAME_PERIOD_NS
        if index % 3 == 0:
            messages.append(_message(
                connection_ids['tf'], stamp + 5_000_000,
                ('tf-{}'.format(index)).encode('ascii'), {
                    'transforms': [
                        _transform(
                            stamp, 'camera_root', 'camera_link',
                            (0.0, 0.0, 0.0))]}))
        rgb_stamp = stamp
        depth_stamp = stamp + 1_000_000
        messages.extend([
            _message(
                connection_ids['rgb'], rgb_stamp + 10_000_000,
                ('rgb-{}'.format(index)).encode('ascii'),
                _image(
                    rgb_stamp, 'camera_color_optical_frame',
                    640, 480, 'bgr8')),
            _message(
                connection_ids['raw_depth'], depth_stamp + 10_000_000,
                ('depth-{}'.format(index)).encode('ascii'),
                _image(
                    depth_stamp, 'camera_depth_optical_frame',
                    640, 400, '16UC1')),
            _message(
                connection_ids['rgb_camera_info'], rgb_stamp + 12_000_000,
                ('rgb-info-{}'.format(index)).encode('ascii'),
                _camera_info(
                    rgb_stamp, 'camera_color_optical_frame', 640, 480)),
            _message(
                connection_ids['depth_camera_info'],
                depth_stamp + 12_000_000,
                ('depth-info-{}'.format(index)).encode('ascii'),
                _camera_info(
                    depth_stamp, 'camera_depth_optical_frame', 640, 400)),
        ])
    return manifest, connections, messages, connection_ids


def _report(connections, messages, manifest):
    return inspect_records(
        connections, messages, 'capture-001', 'diagnostic', manifest)


def _messages_for(messages, connection_id):
    return [
        message for message in messages
        if message['connection_id'] == connection_id]


def _header_sha256(header):
    encoded = json.dumps(
        header, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
        allow_nan=False).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def _attach_connection_header_evidence(connections, messages):
    by_id = {}
    for connection in connections:
        header = {
            'topic': connection['topic'],
            'type': connection['type'],
            'md5sum': connection['md5sum'],
            'callerid': connection['callerid'],
            'latching': '1' if connection['latching'] else '0',
        }
        connection['connection_header'] = header
        connection['connection_header_sha256'] = _header_sha256(header)
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


def _shared_graph_diagnostic_fixture():
    manifest, connections, messages, ids = _fixture()
    tf_static_id = ids['tf_static']
    connections = [
        item for item in connections
        if item['connection_id'] != tf_static_id]
    messages = [
        item for item in messages
        if item['connection_id'] != tf_static_id]
    for role in ('rgb_camera_info', 'depth_camera_info'):
        connection = next(
            item for item in connections
            if item['connection_id'] == ids[role])
        connection['latching'] = True
    for message in _messages_for(messages, ids['depth_camera_info']):
        message['decoded']['header']['frame_id'] = ''
    old_stamp = BASE_STAMP_NS - 300_000_000_000
    old_latched = _message(
        ids['depth_camera_info'], BASE_STAMP_NS + 500_000,
        b'depth-info-old-latched',
        _camera_info(old_stamp, '', 640, 400))
    messages.insert(0, old_latched)
    tf_topic = manifest['topics_by_role']['tf']
    mixed_connection_id = 99
    connections.append({
        'connection_id': mixed_connection_id,
        'topic': tf_topic['name'],
        'type': tf_topic['type'],
        'md5sum': tf_topic['md5sum'],
        'callerid': '/base_link_to_laser_link',
        'latching': False,
    })
    messages.append(_message(
        mixed_connection_id, BASE_STAMP_NS + 2_000_000,
        b'base-link-to-laser-link', {
            'transforms': [_transform(
                BASE_STAMP_NS + 1_000_000,
                'base_link', 'laser_link')]}))
    _attach_connection_header_evidence(connections, messages)
    return manifest, connections, messages, ids


class FakeReader:
    def __init__(self, _path, connections, messages):
        self.connections = connections
        self.messages = messages

    def read(self):
        return copy.deepcopy(self.connections), copy.deepcopy(self.messages)


class _FakeStamp:
    def __init__(self, value):
        self.value = value

    def to_nsec(self):
        return self.value


class _Namespace:
    def __init__(self, **values):
        self.__dict__.update(values)


def _ros_header(value):
    return _Namespace(
        stamp=_FakeStamp(value['stamp_ns']), frame_id=value['frame_id'])


class _FakeWireMessage:
    registry = {}

    def deserialize(self, payload):
        datatype, decoded = self.registry[payload]
        self._payload = payload
        if datatype == 'sensor_msgs/Image':
            self.header = _ros_header(decoded['header'])
            for key in ('height', 'width', 'encoding', 'is_bigendian', 'step'):
                setattr(self, key, decoded[key])
            self.data = bytes(decoded['data_length'])
        elif datatype == 'sensor_msgs/CameraInfo':
            self.header = _ros_header(decoded['header'])
            for key in (
                    'height', 'width', 'distortion_model', 'D', 'K', 'R', 'P',
                    'binning_x', 'binning_y'):
                setattr(self, key, copy.deepcopy(decoded[key]))
            self.roi = _Namespace(**decoded['roi'])
        else:
            self.transforms = []
            for transform in decoded['transforms']:
                translation = _Namespace(
                    x=transform['translation_m'][0],
                    y=transform['translation_m'][1],
                    z=transform['translation_m'][2])
                rotation = _Namespace(
                    x=transform['rotation_xyzw'][0],
                    y=transform['rotation_xyzw'][1],
                    z=transform['rotation_xyzw'][2],
                    w=transform['rotation_xyzw'][3])
                self.transforms.append(_Namespace(
                    header=_ros_header(transform['header']),
                    child_frame_id=transform['child_frame_id'],
                    transform=_Namespace(
                        translation=translation, rotation=rotation)))

    def serialize(self, stream):
        stream.write(self._payload)


def _fake_rosbag_module(
        connections, messages, version=200, header_mutation=None):
    by_id = {item['connection_id']: item for item in connections}
    infos = []
    headers = {}
    for item in connections:
        header = {
            'topic': item['topic'], 'type': item['type'],
            'md5sum': item['md5sum'], 'callerid': item['callerid'],
            'latching': '1' if item['latching'] else '0'}
        if header_mutation:
            header_mutation(item['topic'], header)
        headers[item['connection_id']] = header
        infos.append(_Namespace(
            id=item['connection_id'], topic=item['topic'],
            datatype=item['type'], md5sum=item['md5sum'], header=header))
    wire_items = []
    _FakeWireMessage.registry = {}
    for index, item in enumerate(messages):
        connection = by_id[item['connection_id']]
        payload = item['serialized_payload']
        _FakeWireMessage.registry[payload] = (
            connection['type'], copy.deepcopy(item['decoded']))
        raw = (
            connection['type'], payload, connection['md5sum'],
            (1234, index), _FakeWireMessage)
        wire_items.append((
            connection['topic'], raw,
            _FakeStamp(item['record_timestamp_ns']),
            headers[item['connection_id']]))

    class Bag:
        def __init__(self, *_args, **_kwargs):
            self.version = version

        def _get_connections(self):
            return list(infos)

        def read_messages(self, raw=False, return_connection_header=False):
            if raw is not True or return_connection_header is not True:
                raise AssertionError('reader flags are not strict')
            return iter(wire_items)

        def close(self):
            return None

    return types.SimpleNamespace(Bag=Bag)


class Rosbag1RgbdIndexerTest(unittest.TestCase):

    def assertIndexerSource(self, report):
        source_path = (
            PACKAGE_ROOT / 'src' / 'limo_cleanup_ros1_perception' /
            'rosbag1_rgbd_indexer.py').resolve()
        identity = report['indexer_source']
        self.assertEqual(str(source_path), identity['path'])
        self.assertEqual(source_path.stat().st_size, identity['size_bytes'])
        self.assertEqual(sha256_file(source_path), identity['sha256'])

    def assertFailure(self, report, code):
        self.assertFalse(report['inspection_passed'])
        self.assertFalse(report['delivery_ready'])
        self.assertEqual([code], report['failures'])
        self.assertIndexerSource(report)

    def test_frozen_manifest_exact_identity_and_native_ros1_contract(self):
        manifest = load_manifest(MANIFEST_PATH)
        self.assertEqual(EXPECTED_MANIFEST_SHA256, sha256_file(MANIFEST_PATH))
        self.assertEqual('noetic', manifest['ros_distro'])
        self.assertEqual('rosbag1-v2', manifest['bag_format'])
        self.assertEqual('sensor_only_short_sample', manifest['inspection_scope'])
        self.assertEqual(set(manifest['topics_by_role']), {
            'rgb', 'raw_depth', 'rgb_camera_info', 'depth_camera_info',
            'tf', 'tf_static'})
        self.assertEqual(
            'sensor_msgs/Image', manifest['topics_by_role']['raw_depth']['type'])
        self.assertTrue(manifest['topics_by_role']['tf_static']['latching'])

    def test_rosbag1_v2_magic_and_first_record_envelope_are_host_checked(self):
        cases = {
            'json': (b'{"schema_version":1}\n',
                     'rosbag1_v2_magic_invalid'),
            'sqlite': (b'SQLite format 3\x00not-a-rosbag',
                       'rosbag1_v2_magic_invalid'),
            'truncated': (ROSBAG1_V2_MAGIC,
                          'rosbag1_v2_envelope_invalid'),
            'wrong_first_op': (_rosbag1_v2_fixture(op=b'\x04'),
                               'rosbag1_v2_envelope_invalid'),
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, (payload, expected) in cases.items():
                with self.subTest(name=name):
                    bag = root / (name + '.bag')
                    bag.write_bytes(payload)
                    reader_calls = []

                    def factory(_path):
                        reader_calls.append(str(_path))
                        raise AssertionError(
                            'reader must not run before envelope gate')

                    report = inspect_bag(
                        bag, 'capture-' + name, 'background',
                        MANIFEST_PATH, reader_factory=factory)
                    self.assertFailure(report, expected)
                    self.assertEqual([], reader_calls)

    def test_formal_51_byte_shell_and_reader_injection_never_become_formal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bag = root / '51-byte-shell.bag'
            bag.write_bytes(_rosbag1_v2_fixture(b'x' * 22))
            self.assertEqual(51, bag.stat().st_size)
            reader_calls = []

            def factory(_path):
                reader_calls.append(str(_path))
                raise AssertionError('formal injected reader must not execute')

            injected = inspect_bag(
                bag, 'formal-shell-injected', 'background',
                FORMAL_MANIFEST_PATH, reader_factory=factory,
                mode=FORMAL_CAMERA_ONLY_MODE)
            self.assertFailure(injected, FORMAL_READER_FACTORY_FORBIDDEN)
            self.assertFalse(injected['formal_acceptance'])
            self.assertTrue(injected['not_in_four_scene_denominator'])

            explicit_test_only = inspect_bag(
                bag, 'formal-shell-test-only', 'background',
                FORMAL_MANIFEST_PATH, reader_factory=factory,
                mode=FORMAL_CAMERA_ONLY_MODE, test_only=True)
            self.assertFailure(
                explicit_test_only, FORMAL_TEST_ONLY_READER_FORBIDDEN)
            self.assertFalse(explicit_test_only['formal_acceptance'])
            self.assertTrue(
                explicit_test_only['not_in_four_scene_denominator'])
            self.assertEqual([], reader_calls)

    def test_formal_reader_admission_ignores_all_ambient_python_injection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bag = root / 'ambient-reader-shell.bag'
            bag.write_bytes(_rosbag1_v2_fixture(b'x' * 22))
            fake_calls = []

            class AmbientBag:
                def __init__(self, *_args, **_kwargs):
                    fake_calls.append('ambient-rosbag-module')
                    raise AssertionError('ambient rosbag must not execute')

            fake_rosbag = types.ModuleType('rosbag')
            fake_rosbag.Bag = AmbientBag
            fake_rosbag.__file__ = str(root / 'linked' / 'rosbag.py')
            fake_rosbag.__spec__ = types.SimpleNamespace(
                origin='memory://fake-rosbag', loader=object())

            class PatchedReader:
                def __init__(self, *_args, **_kwargs):
                    fake_calls.append('patched-reader-class')
                    raise AssertionError('patched reader must not execute')

            environment = {
                'PYTHONPATH': str(root / 'ambient-shadow'),
                'ROS1_FORMAL_READER_RESULT_MARKER': json.dumps({
                    'validated_pass': True,
                    'module_origin': 'memory://fake-rosbag',
                }),
            }
            with patch.dict(sys.modules, {'rosbag': fake_rosbag}), patch.dict(
                    os.environ, environment, clear=False), patch.object(
                        INDEXER, 'Rosbag1Reader', PatchedReader):
                report = inspect_bag(
                    bag, 'formal-shell-ambient', 'background',
                    FORMAL_MANIFEST_PATH, mode=FORMAL_CAMERA_ONLY_MODE)

            self.assertFailure(report, FORMAL_READER_ADMISSION_UNAVAILABLE)
            self.assertFalse(report['formal_acceptance'])
            self.assertTrue(report['not_in_four_scene_denominator'])
            self.assertEqual([], fake_calls)

    def test_every_report_kind_binds_exact_indexer_source(self):
        manifest, connections, messages, _ids = _fixture()
        formal_success = _report(connections, messages, manifest)

        manifest_29, connections_29, messages_29, _ids_29 = _fixture(29)
        formal_failure = _report(
            connections_29, messages_29, manifest_29)

        diagnostic_manifest, diagnostic_connections, diagnostic_messages, _ = (
            _shared_graph_diagnostic_fixture())
        diagnostic_success = inspect_records(
            diagnostic_connections, diagnostic_messages,
            'shared-diagnostic-source-binding',
            'diagnostic_shared_graph', diagnostic_manifest,
            mode=DIAGNOSTIC_MODE)

        invalid_mode_failure = inspect_records(
            connections, messages, 'invalid-mode-source-binding',
            'diagnostic', manifest, mode='unsupported_mode')

        for name, report in (
                ('formal_success', formal_success),
                ('formal_failure', formal_failure),
                ('diagnostic_success', diagnostic_success),
                ('invalid_mode_failure', invalid_mode_failure)):
            with self.subTest(report_kind=name):
                self.assertIndexerSource(report)

    def test_valid_short_sample_passes_inspection_but_never_delivery(self):
        manifest, connections, messages, _ids = _fixture()
        report = _report(connections, messages, manifest)
        self.assertTrue(report['inspection_passed'])
        self.assertFalse(report['delivery_ready'])
        self.assertIndexerSource(report)
        self.assertEqual([], report['failures'])
        self.assertEqual(FRAME_COUNT, report['accepted_bundle_count'])
        self.assertEqual(FRAME_COUNT, report['unique_header_pair_count'])
        self.assertEqual(
            FRAME_COUNT, report['formal_contract_valid_pair_count'])
        self.assertNotEqual(
            report['streams']['rgb']['frame_id'],
            report['streams']['raw_depth']['frame_id'])
        self.assertNotEqual(
            report['streams']['rgb']['height'],
            report['streams']['raw_depth']['height'])
        self.assertFalse(report['tf_graph']['base_chain_required'])
        self.assertTrue(all(
            isinstance(item['connection_id'], int)
            for item in report['tf_graph']['transforms']))
        self.assertIn(
            'sensor_only_short_sample_not_formal_delivery',
            report['limitations'])

    def test_minimum_bundle_boundary_is_29_fail_30_pass(self):
        for frame_count, expected in ((29, False), (30, True)):
            with self.subTest(frame_count=frame_count):
                manifest, connections, messages, _ids = _fixture(frame_count)
                report = _report(connections, messages, manifest)
                self.assertEqual(expected, report['inspection_passed'])
                if not expected:
                    self.assertEqual(
                        ['accepted_bundle_count_below_minimum'],
                        report['failures'])

    def test_connection_callerid_type_md5_and_latching_are_exact(self):
        mutations = (
            ('callerid', '/rogue_camera', 'connection_callerid_mismatch'),
            ('type', 'sensor_msgs/CompressedImage',
             'connection_type_mismatch'),
            ('md5sum', '0' * 32, 'connection_md5_mismatch'),
            ('latching', True, 'connection_latching_mismatch'),
        )
        for field, value, code in mutations:
            with self.subTest(field=field):
                manifest, connections, messages, ids = _fixture()
                connection = next(
                    item for item in connections
                    if item['connection_id'] == ids['rgb'])
                connection[field] = value
                self.assertFailure(_report(connections, messages, manifest), code)
        manifest, connections, messages, ids = _fixture()
        static_connection = next(
            item for item in connections
            if item['connection_id'] == ids['tf_static'])
        static_connection['latching'] = False
        self.assertFailure(
            _report(connections, messages, manifest),
            'connection_latching_mismatch')

    def test_old_latched_non_static_connection_is_rejected(self):
        manifest, connections, messages, ids = _fixture()
        connection = next(
            item for item in connections
            if item['connection_id'] == ids['rgb_camera_info'])
        connection['latching'] = True
        for message in _messages_for(messages, ids['rgb_camera_info']):
            message['decoded']['header']['stamp_ns'] -= 60_000_000_000
        self.assertFailure(
            _report(connections, messages, manifest),
            'connection_latching_mismatch')

    def test_duplicate_or_cross_connection_is_rejected(self):
        manifest, connections, messages, ids = _fixture()
        duplicate = copy.deepcopy(next(
            item for item in connections
            if item['connection_id'] == ids['tf']))
        duplicate['connection_id'] = 99
        connections.append(duplicate)
        self.assertFailure(
            _report(connections, messages, manifest), 'duplicate_connection')

    def test_unexpected_topic_and_missing_topic_connection_fail(self):
        manifest, connections, messages, ids = _fixture()
        connections.append({
            'connection_id': 99,
            'topic': '/cmd_vel',
            'type': 'geometry_msgs/Twist',
            'md5sum': '9f195f881246fdfa2798d1d3eebca84a',
            'callerid': '/rogue',
            'latching': False,
        })
        self.assertFailure(
            _report(connections, messages, manifest), 'unexpected_topic')

        manifest, connections, messages, ids = _fixture()
        missing_id = ids['depth_camera_info']
        connections = [
            item for item in connections
            if item['connection_id'] != missing_id]
        messages = [
            item for item in messages
            if item['connection_id'] != missing_id]
        self.assertFailure(
            _report(connections, messages, manifest),
            'missing_topic_connection')

    def test_connection_without_messages_fails(self):
        manifest, connections, messages, ids = _fixture()
        messages = [
            item for item in messages
            if item['connection_id'] != ids['tf_static']]
        self.assertFailure(
            _report(connections, messages, manifest),
            'connection_has_no_messages')

    def test_record_timestamp_rollback_and_header_skew_fail(self):
        manifest, connections, messages, ids = _fixture()
        rgb = _messages_for(messages, ids['rgb'])
        rgb[1]['record_timestamp_ns'] = rgb[0]['record_timestamp_ns']
        self.assertFailure(
            _report(connections, messages, manifest),
            'record_timestamp_not_increasing')

        manifest, connections, messages, ids = _fixture()
        rgb = _messages_for(messages, ids['rgb'])
        rgb[0]['record_timestamp_ns'] = (
            rgb[0]['decoded']['header']['stamp_ns'] + 800_000_000)
        self.assertFailure(
            _report(connections, messages, manifest),
            'record_header_skew_invalid')

    def test_stream_header_duplicate_or_backward_fails(self):
        for delta in (0, -1):
            with self.subTest(delta=delta):
                manifest, connections, messages, ids = _fixture()
                rgb = _messages_for(messages, ids['rgb'])
                rgb[1]['decoded']['header']['stamp_ns'] = (
                    rgb[0]['decoded']['header']['stamp_ns'] + delta)
                self.assertFailure(
                    _report(connections, messages, manifest),
                    'stream_header_not_increasing')

    def test_pairing_over_sync_window_fails_closed(self):
        manifest, connections, messages, ids = _fixture()
        for role in ('raw_depth', 'depth_camera_info'):
            for message in _messages_for(messages, ids[role]):
                message['decoded']['header']['stamp_ns'] += 500_000_000
                message['record_timestamp_ns'] += 500_000_000
        self.assertFailure(
            _report(connections, messages, manifest),
            'pairing_over_sync_window')

    def test_ambiguous_nearest_pairing_fails_closed(self):
        manifest, connections, messages, ids = _fixture()
        depth = _messages_for(messages, ids['raw_depth'])
        first = depth[0]
        anchor_stamp = _messages_for(messages, ids['rgb'])[0][
            'decoded']['header']['stamp_ns']
        first['decoded']['header']['stamp_ns'] = anchor_stamp - 1_000_000
        first['record_timestamp_ns'] = anchor_stamp + 8_000_000
        duplicate = copy.deepcopy(first)
        duplicate['decoded']['header']['stamp_ns'] = anchor_stamp + 1_000_000
        duplicate['record_timestamp_ns'] = anchor_stamp + 9_000_000
        duplicate['serialized_payload'] = b'depth-extra-ambiguous'
        insert_at = messages.index(first) + 1
        messages.insert(insert_at, duplicate)
        self.assertFailure(
            _report(connections, messages, manifest),
            'ambiguous_stream_pairing')

    def test_image_camera_info_frame_and_grid_mismatch_fail(self):
        manifest, connections, messages, ids = _fixture()
        for message in _messages_for(messages, ids['rgb_camera_info']):
            message['decoded']['header']['frame_id'] = (
                'camera_wrong_optical_frame')
        self.assertFailure(
            _report(connections, messages, manifest),
            'image_camera_info_frame_mismatch')

        manifest, connections, messages, ids = _fixture()
        for message in _messages_for(messages, ids['depth_camera_info']):
            message['decoded']['height'] = 399
            message['decoded']['K'][5] = 199.0
            message['decoded']['P'][6] = 199.0
        self.assertFailure(
            _report(connections, messages, manifest),
            'image_camera_info_resolution_mismatch')

    def test_camera_info_K_D_R_P_changes_are_all_rejected(self):
        mutations = {
            'K': lambda value: value.__setitem__(0, value[0] + 1.0),
            'D': lambda value: value.__setitem__(0, value[0] + 0.001),
            'R': lambda value: value.__setitem__(0, value[0] - 0.001),
            'P': lambda value: value.__setitem__(0, value[0] + 1.0),
        }
        for field, mutate in mutations.items():
            with self.subTest(field=field):
                manifest, connections, messages, ids = _fixture()
                info = _messages_for(messages, ids['rgb_camera_info'])[1]
                mutate(info['decoded'][field])
                self.assertFailure(
                    _report(connections, messages, manifest),
                    'camera_info_changed')

    def test_camera_info_array_lengths_and_nonfinite_values_fail(self):
        cases = (
            ('K', [1.0] * 8, 'camera_info_K_invalid'),
            ('R', [1.0] * 8, 'camera_info_R_invalid'),
            ('P', [1.0] * 11, 'camera_info_P_invalid'),
            ('D', [float('nan')], 'camera_info_D_invalid'),
        )
        for field, value, code in cases:
            with self.subTest(field=field):
                manifest, connections, messages, ids = _fixture()
                info = _messages_for(messages, ids['rgb_camera_info'])[0]
                info['decoded'][field] = value
                self.assertFailure(_report(connections, messages, manifest), code)

    def test_image_payload_shape_and_encoding_fail(self):
        for field, value in (
                ('data_length', 1), ('encoding', 'jpeg')):
            with self.subTest(field=field):
                manifest, connections, messages, ids = _fixture()
                image = _messages_for(messages, ids['rgb'])[0]
                image['decoded'][field] = value
                self.assertFailure(
                    _report(connections, messages, manifest),
                    'image_payload_invalid')

    def test_non_camera_or_mixed_tf_fails_closed(self):
        manifest, connections, messages, ids = _fixture()
        static_message = _messages_for(messages, ids['tf_static'])[0]
        static_message['decoded']['transforms'][0]['header']['frame_id'] = (
            'base_link')
        self.assertFailure(
            _report(connections, messages, manifest), 'non_camera_tf_frame')

        manifest, connections, messages, ids = _fixture()
        static_message = _messages_for(messages, ids['tf_static'])[0]
        static_message['decoded']['transforms'].append(
            _transform(0, 'camera_root', 'camera_link'))
        self.assertFailure(
            _report(connections, messages, manifest),
            'tf_child_static_dynamic_overlap')

    def test_tf_child_parent_dynamic_stamp_and_value_are_stable(self):
        manifest, connections, messages, ids = _fixture()
        dynamic = _messages_for(messages, ids['tf'])
        dynamic[1]['decoded']['transforms'][0]['header']['frame_id'] = (
            'camera_other_root')
        self.assertFailure(
            _report(connections, messages, manifest),
            'tf_child_multiple_parents')

        manifest, connections, messages, ids = _fixture()
        dynamic = _messages_for(messages, ids['tf'])
        dynamic[1]['decoded']['transforms'][0]['header']['stamp_ns'] = (
            dynamic[0]['decoded']['transforms'][0]['header']['stamp_ns'])
        self.assertFailure(
            _report(connections, messages, manifest),
            'dynamic_tf_stamp_not_increasing')

        manifest, connections, messages, ids = _fixture()
        dynamic = _messages_for(messages, ids['tf'])
        dynamic[1]['decoded']['transforms'][0]['translation_m'][0] = 0.001
        self.assertFailure(
            _report(connections, messages, manifest),
            'dynamic_camera_tf_changed')

    def test_duplicate_static_tf_and_missing_stream_frame_tf_fail(self):
        manifest, connections, messages, ids = _fixture()
        static_message = _messages_for(messages, ids['tf_static'])[0]
        static_message['decoded']['transforms'].append(copy.deepcopy(
            static_message['decoded']['transforms'][0]))
        self.assertFailure(
            _report(connections, messages, manifest), 'duplicate_static_tf')

        manifest, connections, messages, ids = _fixture()
        static_message = _messages_for(messages, ids['tf_static'])[0]
        static_message['decoded']['transforms'] = [
            transform for transform in static_message['decoded']['transforms']
            if transform['child_frame_id'] != 'camera_color_optical_frame']
        self.assertFailure(
            _report(connections, messages, manifest),
            'stream_frame_missing_from_tf')

    def test_rosbag_reader_requires_explicit_latching_and_preserves_headers(self):
        _manifest, connections, messages, _ids = _fixture()
        module = _fake_rosbag_module(connections, messages)
        with patch.dict(sys.modules, {'rosbag': module}):
            read_connections, read_messages = Rosbag1Reader(
                Path('wire-sample.bag')).read()
        self.assertTrue(read_connections)
        self.assertTrue(read_messages)
        for connection in read_connections:
            self.assertIn(
                connection['connection_header']['latching'], ('0', '1'))
            self.assertEqual(
                64, len(connection['connection_header_sha256']))
            self.assertEqual(
                _header_sha256(connection['connection_header']),
                connection['connection_header_sha256'])
        self.assertEqual(
            read_connections[0]['connection_header_sha256'],
            next(
                item for item in read_messages
                if item['connection_id']
                == read_connections[0]['connection_id'])[
                    'connection_header_sha256'])

        for value, expected_code in (
                (None, 'rosbag_latching_header_missing'),
                ('2', 'rosbag_latching_header_invalid')):
            with self.subTest(value=value):
                def mutate(topic, header):
                    if topic == '/camera/color/image_raw':
                        if value is None:
                            header.pop('latching')
                        else:
                            header['latching'] = value

                module = _fake_rosbag_module(
                    connections, messages, header_mutation=mutate)
                with patch.dict(sys.modules, {'rosbag': module}):
                    with self.assertRaises(InspectionError) as raised:
                        Rosbag1Reader(Path('bad-header.bag')).read()
                self.assertEqual(expected_code, raised.exception.code)

                module = _fake_rosbag_module(
                    connections, messages, header_mutation=mutate)
                with patch.dict(sys.modules, {'rosbag': module}):
                    diagnostic_connections, _diagnostic_messages = (
                        Rosbag1Reader(
                            Path('bad-header.bag'), diagnostic=True).read())
                rgb_connection = next(
                    item for item in diagnostic_connections
                    if item['topic'] == '/camera/color/image_raw')
                self.assertIn(
                    expected_code,
                    [item['code'] for item in rgb_connection[
                        'connection_header_violations']])

    def test_diagnostic_shared_graph_aggregates_without_formal_acceptance(self):
        manifest, connections, messages, _ids = (
            _shared_graph_diagnostic_fixture())
        report = inspect_records(
            connections, messages, 'shared-diagnostic-001',
            'diagnostic_shared_graph', manifest,
            mode=DIAGNOSTIC_MODE)
        self.assertEqual(
            'ros1_shared_graph_diagnostic_manifest', report['report_kind'])
        self.assertTrue(report['diagnostic_completed'])
        self.assertIndexerSource(report)
        self.assertFalse(report['inspection_passed'])
        self.assertFalse(report['formal_acceptance'])
        self.assertTrue(report['shared_graph'])
        self.assertTrue(report['mixed_tf'])
        self.assertTrue(report['not_in_four_scene_denominator'])
        self.assertFalse(report['delivery_ready'])
        self.assertEqual(
            1, report['isolated_old_latched_camera_info_count'])
        self.assertEqual(
            'old_latched_camera_info_before_capture_window',
            report['isolated_old_latched_camera_info'][0]['reason'])
        self.assertEqual(FRAME_COUNT, report['unique_header_pair_count'])
        self.assertEqual(0, report['formal_contract_valid_pair_count'])
        self.assertTrue(all(
            not pair['formal_valid']
            for pair in report['unique_header_pairs']))
        self.assertIn('missing_topic_connection', report['failures'])
        self.assertIn('cross_connection_topic', report['failures'])
        self.assertIn('connection_latching_mismatch', report['failures'])
        self.assertIn('frame_id_invalid', report['failures'])
        self.assertIn('non_camera_tf_frame', report['failures'])
        self.assertEqual(0, report['tf_graph']['topic_message_counts'][
            '/tf_static'])
        laser_edges = [
            item for item in report['tf_graph']['transforms']
            if (item['parent_frame_id'], item['child_frame_id'])
            == ('base_link', 'laser_link')]
        self.assertEqual(1, len(laser_edges))
        self.assertEqual(
            '/base_link_to_laser_link', laser_edges[0]['callerid'])
        self.assertEqual('/tf', laser_edges[0]['topic'])
        self.assertEqual(99, laser_edges[0]['connection_id'])
        self.assertTrue(all(
            item['connection_header'] is not None
            and len(item['connection_header_sha256']) == 64
            for item in report['topics']))

    def test_diagnostic_cli_is_exclusive_and_returns_decode_success(self):
        _manifest, connections, messages, _ids = (
            _shared_graph_diagnostic_fixture())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bag = root / 'shared-graph.bag'
            bag.write_bytes(_rosbag1_v2_fixture(
                b'fake-shared-graph-bag-v2'))
            output = root / 'diagnostic.json'

            def factory(path):
                return FakeReader(path, connections, messages)

            args = [
                '--bag', str(bag), '--capture-id', 'shared-diagnostic-001',
                '--scene', 'diagnostic_shared_graph',
                '--mode', DIAGNOSTIC_MODE,
                '--manifest', str(MANIFEST_PATH),
                '--output', str(output)]
            self.assertEqual(0, main(args, reader_factory=factory))
            report = json.loads(output.read_text(encoding='utf-8'))
            self.assertTrue(report['diagnostic_completed'])
            self.assertIndexerSource(report)
            self.assertFalse(report['formal_acceptance'])
            self.assertTrue(report['not_in_four_scene_denominator'])
            with self.assertRaisesRegex(SystemExit, 'must not already exist'):
                main(args, reader_factory=factory)

    def test_manifest_tampering_fails_before_bag_read(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / MANIFEST_PATH.name
            payload = json.loads(MANIFEST_PATH.read_text(encoding='utf-8'))
            payload['max_sync_span_sec'] = 0.2
            path.write_text(json.dumps(payload), encoding='utf-8')
            with self.assertRaises(InspectionError) as raised:
                load_manifest(path)
            self.assertEqual('manifest_hash_mismatch', raised.exception.code)

    def test_cli_uses_injected_reader_writes_exclusively_and_returns_zero(self):
        manifest, connections, messages, _ids = _fixture()
        del manifest
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bag = root / 'sample.bag'
            bag.write_bytes(_rosbag1_v2_fixture(b'fake-bag-v2'))
            output = root / 'inspection.json'

            def factory(path):
                return FakeReader(path, connections, messages)

            args = [
                '--bag', str(bag), '--capture-id', 'capture-001',
                '--scene', 'diagnostic', '--manifest', str(MANIFEST_PATH),
                '--output', str(output)]
            self.assertEqual(0, main(args, reader_factory=factory))
            report = json.loads(output.read_text(encoding='utf-8'))
            self.assertTrue(report['inspection_passed'])
            self.assertFalse(report['delivery_ready'])
            with self.assertRaisesRegex(SystemExit, 'must not already exist'):
                main(args, reader_factory=factory)

    def test_source_is_offline_and_has_no_graph_or_control_api(self):
        source_path = (
            PACKAGE_ROOT / 'src' / 'limo_cleanup_ros1_perception' /
            'rosbag1_rgbd_indexer.py')
        source = source_path.read_text(encoding='utf-8')
        for token in (
                'import rospy', 'rospy.init_node', 'rospy.Publisher',
                'rospy.Subscriber', 'rospy.Service', 'rosgraph',
                'socket.', 'subprocess.', 'create_publisher(', '.publish(',
                'cmd_vel', 'move_base', 'JointTrajectory', 'GripperCommand'):
            self.assertNotIn(token, source)
        self.assertIn("rosbag.Bag(str(self.path), mode='r'", source)
        self.assertIn('allow_unindexed=False', source)
        self.assertNotIn('reindex(', source)


if __name__ == '__main__':
    unittest.main()

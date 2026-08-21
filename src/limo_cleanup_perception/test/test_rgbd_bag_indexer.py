"""ROS-independent tests for the decoded, read-only rosbag indexer."""

import hashlib
import json
import sqlite3
import struct
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from limo_cleanup_perception.rgbd_bag_indexer import (
    MAX_SYNC_SPAN_SEC,
    _CdrReader,
    decode_cdr_payload,
    default_topic_manifest_path,
    inspect_sqlite_bag,
    is_control_topic,
    main,
)


STREAM_TOPICS = {
    'rgb': '/camera/color/image_raw',
    'aligned_depth': '/camera/depth/image_raw',
    'rgb_camera_info': '/camera/color/camera_info',
    'depth_camera_info': '/camera/depth/camera_info',
}
QOS_SENSOR = (
    '- history: 1\n  depth: 5\n  reliability: 2\n'
    '  durability: 2\n  deadline:\n    sec: 0\n    nsec: 0\n'
    '  lifespan:\n    sec: 0\n    nsec: 0\n'
    '  liveliness: 1\n  liveliness_lease_duration:\n'
    '    sec: 0\n    nsec: 0\n'
    '  avoid_ros_namespace_conventions: false\n')
QOS_TF = (
    '- history: 1\n  depth: 100\n  reliability: 1\n'
    '  durability: 2\n  deadline:\n    sec: 0\n    nsec: 0\n'
    '  lifespan:\n    sec: 0\n    nsec: 0\n'
    '  liveliness: 1\n  liveliness_lease_duration:\n'
    '    sec: 0\n    nsec: 0\n'
    '  avoid_ros_namespace_conventions: false\n')
QOS_TF_STATIC = (
    '- history: 1\n  depth: 1\n  reliability: 1\n'
    '  durability: 1\n  deadline:\n    sec: 0\n    nsec: 0\n'
    '  lifespan:\n    sec: 0\n    nsec: 0\n'
    '  liveliness: 1\n  liveliness_lease_duration:\n'
    '    sec: 0\n    nsec: 0\n'
    '  avoid_ros_namespace_conventions: false\n')


class _CdrWriter:
    def __init__(self):
        self.data = bytearray(b'\x00\x01\x00\x00')
        self.origin = 4

    def align(self, alignment):
        self.data.extend(b'\x00' * (
            (-(len(self.data) - self.origin)) % alignment))

    def pack(self, code, alignment, value):
        self.align(alignment)
        self.data.extend(struct.pack('<' + code, value))

    def uint8(self, value):
        self.pack('B', 1, value)

    def uint32(self, value):
        self.pack('I', 4, value)

    def int32(self, value):
        self.pack('i', 4, value)

    def float64(self, value):
        self.pack('d', 8, value)

    def string(self, value):
        encoded = value.encode('utf-8') + b'\x00'
        self.uint32(len(encoded))
        self.data.extend(encoded)

    def bytes(self, value):
        self.data.extend(value)


def _header(writer, stamp_ns, frame_id):
    writer.int32(stamp_ns // 1_000_000_000)
    writer.uint32(stamp_ns % 1_000_000_000)
    writer.string(frame_id)


def _image(stamp_ns, frame_id, encoding='bgr8', width=4, height=3):
    bytes_per_pixel = 2 if encoding in ('16UC1', 'mono16') else 3
    step = width * bytes_per_pixel
    writer = _CdrWriter()
    _header(writer, stamp_ns, frame_id)
    writer.uint32(height)
    writer.uint32(width)
    writer.string(encoding)
    writer.uint8(0)
    writer.uint32(step)
    writer.uint32(step * height)
    if encoding in ('16UC1', 'mono16'):
        writer.bytes(struct.pack('<H', 1000) * (width * height))
    elif encoding == '32FC1':
        writer.bytes(struct.pack('<f', 1.0) * (width * height))
    else:
        writer.bytes(b'\x01' * (step * height))
    return bytes(writer.data)


def _image_with_step(stamp_ns, frame_id, encoding, step, width=4, height=3):
    writer = _CdrWriter()
    _header(writer, stamp_ns, frame_id)
    writer.uint32(height)
    writer.uint32(width)
    writer.string(encoding)
    writer.uint8(0)
    writer.uint32(step)
    writer.uint32(step * height)
    writer.bytes(b'\x01' * (step * height))
    return bytes(writer.data)


def _camera_info(stamp_ns, frame_id, width=4, height=3):
    writer = _CdrWriter()
    _header(writer, stamp_ns, frame_id)
    writer.uint32(height)
    writer.uint32(width)
    writer.string('plumb_bob')
    writer.uint32(5)
    for value in (0.0,) * 5:
        writer.float64(value)
    for value in (500.0, 0.0, 2.0, 0.0, 500.0, 1.5, 0.0, 0.0, 1.0):
        writer.float64(value)
    for value in (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0):
        writer.float64(value)
    for value in (500.0, 0.0, 2.0, 0.0, 0.0, 500.0,
                  1.5, 0.0, 0.0, 0.0, 1.0, 0.0):
        writer.float64(value)
    for value in (0, 0, 0, 0, 0, 0):
        writer.uint32(value)
    writer.uint8(0)
    return bytes(writer.data)


def _camera_info_with_calibration(
        stamp_ns, frame_id, cx, cy, binning_x=0, binning_y=0,
        width=4, height=3):
    writer = _CdrWriter()
    _header(writer, stamp_ns, frame_id)
    writer.uint32(height)
    writer.uint32(width)
    writer.string('plumb_bob')
    writer.uint32(5)
    for value in (0.0,) * 5:
        writer.float64(value)
    for value in (500.0, 0.0, cx, 0.0, 500.0, cy, 0.0, 0.0, 1.0):
        writer.float64(value)
    for value in (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0):
        writer.float64(value)
    for value in (
            500.0, 0.0, cx, 0.0, 0.0, 500.0,
            cy, 0.0, 0.0, 0.0, 1.0, 0.0):
        writer.float64(value)
    writer.uint32(binning_x)
    writer.uint32(binning_y)
    for value in (0, 0, 0, 0):
        writer.uint32(value)
    writer.uint8(0)
    return bytes(writer.data)


def _tf(stamp_ns, parent, child, translation=(0.0, 0.0, 0.0)):
    writer = _CdrWriter()
    writer.uint32(1)
    _header(writer, stamp_ns, parent)
    writer.string(child)
    for value in translation:
        writer.float64(value)
    for value in (0.0, 0.0, 0.0, 1.0):
        writer.float64(value)
    return bytes(writer.data)


def topic_rows(extra_topics=(), omit_topics=(), qos_overrides=None):
    qos_overrides = qos_overrides or {}
    rows = [
        (1, STREAM_TOPICS['rgb'], 'sensor_msgs/msg/Image', 'cdr', QOS_SENSOR),
        (2, STREAM_TOPICS['aligned_depth'], 'sensor_msgs/msg/Image', 'cdr', QOS_SENSOR),
        (3, STREAM_TOPICS['rgb_camera_info'], 'sensor_msgs/msg/CameraInfo', 'cdr', QOS_SENSOR),
        (4, STREAM_TOPICS['depth_camera_info'], 'sensor_msgs/msg/CameraInfo', 'cdr', QOS_SENSOR),
        (5, '/tf', 'tf2_msgs/msg/TFMessage', 'cdr', QOS_TF),
        (6, '/tf_static', 'tf2_msgs/msg/TFMessage', 'cdr', QOS_TF_STATIC),
    ]
    rows = [row for row in rows if row[1] not in set(omit_topics)]
    rows.extend(extra_topics)
    return [
        (row[0], row[1], row[2], row[3],
         qos_overrides.get(row[1], row[4]))
        for row in rows]


def _create_schema(connection, valid=True):
    connection.execute(
        'CREATE TABLE topics('
        'id INTEGER PRIMARY KEY, name TEXT, type TEXT, '
        'serialization_format TEXT, offered_qos_profiles TEXT)')
    if valid:
        connection.execute(
            'CREATE TABLE messages('
            'id INTEGER PRIMARY KEY, topic_id INTEGER, '
            'timestamp INTEGER, data BLOB)')
    else:
        connection.execute(
            'CREATE TABLE messages('
            'id INTEGER PRIMARY KEY, topic_id INTEGER, timestamp INTEGER)')


def create_bag(
        path: Path, frame_count=2, accepted_count=None, topic_rows=None,
        payload_mutator=None, header_offsets_ns=None,
        base_time_ns=1_000_000_000,
        frame_period_ns=100_000_000, link_tf=True,
        dynamic_tf_translations=None, dynamic_tf_every_frame=True):
    if accepted_count is None:
        accepted_count = frame_count
    if topic_rows is None:
        topic_rows = globals()['topic_rows']()
    header_offsets_ns = header_offsets_ns or {
        'rgb': 0, 'aligned_depth': 20_000_000,
        'rgb_camera_info': 10_000_000,
        'depth_camera_info': 10_000_000,
    }
    topic_ids = {row[1]: row[0] for row in topic_rows}
    messages = []
    message_id = 1
    frame_id = 'camera_color_optical_frame'
    for index in range(frame_count):
        base = base_time_ns + index * frame_period_ns
        for name in STREAM_TOPICS:
            if index >= accepted_count and name != 'rgb':
                continue
            stamp = base + header_offsets_ns[name]
            if name == 'rgb':
                payload = _image(stamp, frame_id)
            elif name == 'aligned_depth':
                payload = _image(stamp, frame_id, '16UC1')
            else:
                payload = _camera_info(stamp, frame_id)
            if payload_mutator is not None:
                payload = payload_mutator(name, index, payload)
            record_stamp = stamp + 50_000_000
            messages.append((
                message_id, topic_ids[STREAM_TOPICS[name]], record_stamp,
                payload))
            message_id += 1
    tf_stamp = base_time_ns
    if '/tf_static' in topic_ids:
        messages.append((
            message_id, topic_ids['/tf_static'], tf_stamp + 50_000_000,
            _tf(
                tf_stamp, 'base_link', 'camera_mount',
                (0.1, 0.0, 0.2))))
        message_id += 1
    if '/tf' in topic_ids:
        dynamic_tf_translations = dynamic_tf_translations or [
            (0.0, 0.0, 0.0)] * frame_count
        dynamic_count = frame_count if dynamic_tf_every_frame else 1
        for index in range(dynamic_count):
            stamp = base_time_ns + index * frame_period_ns
            translation = dynamic_tf_translations[min(
                index, len(dynamic_tf_translations) - 1)]
            messages.append((
                message_id, topic_ids['/tf'], stamp + 50_000_000,
                (_tf(stamp, 'camera_mount', frame_id, translation)
                 if link_tf else
                 _tf(stamp, 'other_parent', 'other_child', translation))))
            message_id += 1
    connection = sqlite3.connect(str(path))
    try:
        _create_schema(connection)
        connection.executemany(
            'INSERT INTO topics VALUES (?, ?, ?, ?, ?)', topic_rows)
        connection.executemany(
            'INSERT INTO messages VALUES (?, ?, ?, ?)', messages)
        connection.commit()
    finally:
        connection.close()


class RgbdBagIndexerTest(unittest.TestCase):
    """Verify CDR semantics, exact topic/QoS gates, pairing and safety."""

    def test_complete_decoded_six_topic_bag_passes_read_only(self):
        with TemporaryDirectory() as directory:
            bag = Path(directory) / 'capture.db3'
            create_bag(bag)
            before = bag.read_bytes()
            report = inspect_sqlite_bag(
                bag, 'capture-001', 'bottle_outside', STREAM_TOPICS)
            self.assertEqual(3, report['schema_version'])
            self.assertTrue(report['read_only'])
            self.assertFalse(report['authorizes_motion'])
            self.assertFalse(report['publishes_ros_messages'])
            self.assertEqual(
                'formal_rgbd_raw_capture_index', report['report_kind'])
            self.assertEqual(
                'formal_scene_raw_capture', report['inspection_scope'])
            self.assertTrue(report['formal_acceptance'])
            self.assertFalse(report['shared_graph'])
            self.assertFalse(report['mixed_tf'])
            self.assertFalse(report['not_in_four_scene_denominator'])
            self.assertEqual(before, bag.read_bytes())
            self.assertEqual(
                hashlib.sha256(before).hexdigest(),
                report['source_capture']['sha256'])
            self.assertEqual(6, len(report['topics']))
            self.assertEqual(2, report['rgb_candidate_count'])
            self.assertEqual(2, report['accepted_bundle_count'])
            self.assertEqual(0, report['rejected_rgb_count'])
            self.assertEqual(0.0, report['rejection_rate'])
            self.assertEqual(
                ['base_link', 'camera_mount',
                 'camera_color_optical_frame'],
                report['tf_graph']['chain_base_to_camera'])
            self.assertEqual(
                [0.1, 0.0, 0.2], report['tf_graph'][
                    'base_to_camera_transform']['translation_m'])
            self.assertEqual(
                2, report['tf_graph']['bundle_tf_coverage_count'])
            self.assertEqual(
                'limo-dabai-rgbd-six-topics-v1',
                report['expected_topic_manifest']['manifest_id'])
            self.assertEqual([], report['control_topics'])
            self.assertTrue(all(
                item['payload_decode_ok'] for item in report['messages']))
            self.assertTrue(all(
                item['stamp_span_sec'] <= MAX_SYNC_SPAN_SEC
                for item in report['accepted_bundles']))

    def test_exact_six_topic_manifest_rejects_missing_extra_and_zero(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            cases = [
                ('missing', topic_rows(omit_topics=('/tf_static',))),
                ('extra', topic_rows(extra_topics=((
                    7, '/diagnostics', 'diagnostic_msgs/msg/DiagnosticArray',
                    'cdr', QOS_TF),))),
                ('alias', [
                    (row[0], STREAM_TOPICS['rgb'] if row[1] == '/tf' else row[1],
                     row[2], row[3], row[4])
                    for row in topic_rows()]),
            ]
            for name, topics in cases:
                with self.subTest(name=name):
                    bag = root / (name + '.db3')
                    connection = sqlite3.connect(str(bag))
                    try:
                        _create_schema(connection)
                        connection.executemany(
                            'INSERT INTO topics VALUES (?, ?, ?, ?, ?)', topics)
                        connection.commit()
                    finally:
                        connection.close()
                    with self.assertRaisesRegex(ValueError, 'topic'):
                        inspect_sqlite_bag(
                            bag, name, 'background', STREAM_TOPICS)
            zero = root / 'zero.db3'
            connection = sqlite3.connect(str(zero))
            try:
                _create_schema(connection)
                connection.executemany(
                    'INSERT INTO topics VALUES (?, ?, ?, ?, ?)',
                    topic_rows())
                connection.commit()
            finally:
                connection.close()
            with self.assertRaisesRegex(ValueError, 'at least one message'):
                inspect_sqlite_bag(
                    zero, 'zero', 'background', STREAM_TOPICS)

    def test_qos_missing_unknown_contradictory_and_static_volatile_fail(self):
        invalid = {
            'empty': '',
            'unknown': 'history: keep_last',
            'out_of_range': 'reliability: 10\ndurability: 20',
            'substring': 'xreliability1x: 1\nxdurability2x: 2',
            'junk_value': (
                'reliability: best_effortbar\ndurability: volatilequux'),
            'duplicate': (
                'reliability: 1\nreliability: 2\ndurability: 2'),
            'unknown_key': (
                'history: 1\ndepth: 5\nfoo: ignored\n'
                'reliability: 2\ndurability: 2'),
            'bad_history': (
                'history: garbage\ndepth: 5\n'
                'reliability: 2\ndurability: 2'),
            'negative_depth': (
                'history: 1\ndepth: -1\n'
                'reliability: 2\ndurability: 2'),
        }
        with TemporaryDirectory() as directory:
            for name, qos in invalid.items():
                with self.subTest(name=name):
                    bag = Path(directory) / (name + '.db3')
                    create_bag(
                        bag, topic_rows=topic_rows(
                            qos_overrides={STREAM_TOPICS['rgb']: qos}))
                    with self.assertRaisesRegex(ValueError, 'QoS'):
                        inspect_sqlite_bag(
                            bag, name, 'background', STREAM_TOPICS)
            bag = Path(directory) / 'static-volatile.db3'
            create_bag(
                bag, topic_rows=topic_rows(
                    qos_overrides={'/tf_static': QOS_TF}))
            with self.assertRaisesRegex(ValueError, 'transient-local'):
                inspect_sqlite_bag(
                    bag, 'static-volatile', 'background', STREAM_TOPICS)

    def test_realistic_full_qos_profile_and_nested_failures(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            good = root / 'full-qos.db3'
            create_bag(good)
            report = inspect_sqlite_bag(
                good, 'full-qos', 'background', STREAM_TOPICS)
            self.assertEqual(6, len(report['topics']))

            invalid = {
                'bad_duration': QOS_SENSOR.replace('nsec: 0', 'nsec: -1', 1),
                'bad_liveliness': QOS_SENSOR.replace(
                    'liveliness: 1', 'liveliness: 999'),
                'bad_bool': QOS_SENSOR.replace(
                    'avoid_ros_namespace_conventions: false',
                    'avoid_ros_namespace_conventions: perhaps'),
                'namespace_bypass': QOS_SENSOR.replace(
                    'avoid_ros_namespace_conventions: false',
                    'avoid_ros_namespace_conventions: true'),
                'root_mapping': QOS_SENSOR.replace('- history:', 'history:', 1),
                'tab_indent': QOS_SENSOR.replace('  depth:', '\tdepth:', 1),
                'two_profiles_conflict': QOS_SENSOR + QOS_SENSOR.replace(
                    'depth: 5', 'depth: 6'),
                'two_profiles_deadline_conflict': (
                    QOS_SENSOR + QOS_SENSOR.replace(
                        'deadline:\n    sec: 0\n    nsec: 0',
                        'deadline:\n    sec: 0\n    nsec: 1')),
                'missing_nested': QOS_SENSOR.replace(
                    '  deadline:\n    sec: 0\n    nsec: 0\n', '', 1),
            }
            for name, qos in invalid.items():
                with self.subTest(name=name):
                    bag = root / (name + '.db3')
                    create_bag(
                        bag, topic_rows=topic_rows(qos_overrides={
                            STREAM_TOPICS['rgb']: qos}))
                    with self.assertRaisesRegex(ValueError, 'QoS'):
                        inspect_sqlite_bag(
                            bag, name, 'background', STREAM_TOPICS)
            multi = root / 'two-identical-profiles.db3'
            create_bag(
                multi, topic_rows=topic_rows(qos_overrides={
                    STREAM_TOPICS['rgb']: QOS_SENSOR + QOS_SENSOR}))
            report = inspect_sqlite_bag(
                multi, 'two-identical', 'background', STREAM_TOPICS)
            rgb_topic = next(item for item in report['topics'] if item[
                'name'] == STREAM_TOPICS['rgb'])
            self.assertEqual(2, rgb_topic['qos']['profile_count'])

            keep_all = root / 'keep-all-depth-is-ignored.db3'
            keep_all_zero = (QOS_SENSOR
                             .replace('history: 1', 'history: 2')
                             .replace('depth: 5', 'depth: 0'))
            keep_all_nonzero = (QOS_SENSOR
                                .replace('history: 1', 'history: keep_all')
                                .replace('depth: 5', 'depth: 17'))
            create_bag(
                keep_all, topic_rows=topic_rows(qos_overrides={
                    STREAM_TOPICS['rgb']:
                    keep_all_zero + keep_all_nonzero}))
            report = inspect_sqlite_bag(
                keep_all, 'keep-all-depth', 'background', STREAM_TOPICS)
            rgb_topic = next(item for item in report['topics'] if item[
                'name'] == STREAM_TOPICS['rgb'])
            self.assertEqual(2, rgb_topic['qos']['profile_count'])

            semantic = root / 'two-semantic-profiles.db3'
            symbolic = (QOS_SENSOR
                        .replace('history: 1', 'history: keep_last')
                        .replace('reliability: 2',
                                 'reliability: best_effort')
                        .replace('durability: 2', 'durability: volatile')
                        .replace('liveliness: 1',
                                 'liveliness: automatic'))
            create_bag(
                semantic, topic_rows=topic_rows(qos_overrides={
                    STREAM_TOPICS['rgb']: QOS_SENSOR + symbolic}))
            report = inspect_sqlite_bag(
                semantic, 'two-semantic', 'background', STREAM_TOPICS)
            rgb_topic = next(item for item in report['topics'] if item[
                'name'] == STREAM_TOPICS['rgb'])
            self.assertEqual(2, rgb_topic['qos']['profile_count'])

            for name, qos in {
                    'duration_uint64_overflow': QOS_SENSOR.replace(
                        'deadline:\n    sec: 0',
                        'deadline:\n    sec: 18446744073709551616', 1),
                    'depth_uint64_overflow': QOS_SENSOR.replace(
                        'depth: 5', 'depth: 18446744073709551616', 1),
                    }.items():
                with self.subTest(name=name):
                    bag = root / (name + '.db3')
                    create_bag(
                        bag, topic_rows=topic_rows(qos_overrides={
                            STREAM_TOPICS['rgb']: qos}))
                    with self.assertRaisesRegex(ValueError, 'QoS'):
                        inspect_sqlite_bag(
                            bag, name, 'background', STREAM_TOPICS)

            # Liveliness is a frozen per-stream compatibility policy, not
            # merely a parseable field.
            manual = root / 'manual-liveliness.db3'
            create_bag(
                manual, topic_rows=topic_rows(qos_overrides={
                    STREAM_TOPICS['rgb']: QOS_SENSOR.replace(
                        'liveliness: 1', 'liveliness: 3')}))
            with self.assertRaisesRegex(ValueError, 'incompatible'):
                inspect_sqlite_bag(
                    manual, 'manual-liveliness', 'background', STREAM_TOPICS)

    def test_cdr_invalid_truncated_type_mismatch_and_non_monotonic_fail(self):
        with TemporaryDirectory() as directory:
            mutations = {
                'ascii': lambda name, index, payload: b'not-cdr',
                'truncated': lambda name, index, payload: payload[:-1],
                'wrong_type': lambda name, index, payload: (
                    _camera_info((index + 1) * 1_000_000_000,
                                 'camera_color_optical_frame')
                    if name == 'rgb' else payload),
            }
            for name, mutator in mutations.items():
                with self.subTest(name=name):
                    bag = Path(directory) / (name + '.db3')
                    create_bag(bag, payload_mutator=mutator)
                    with self.assertRaisesRegex(ValueError, 'CDR payload'):
                        inspect_sqlite_bag(
                            bag, name, 'background', STREAM_TOPICS)
            bag = Path(directory) / 'non-monotonic.db3'
            def non_monotonic(name, index, payload):
                if name == 'rgb' and index == 1:
                    return _image(
                        1_000_000_000, 'camera_color_optical_frame')
                return payload
            create_bag(bag, payload_mutator=non_monotonic)
            with self.assertRaisesRegex(ValueError, 'strictly increasing'):
                inspect_sqlite_bag(
                    bag, 'non-monotonic', 'background', STREAM_TOPICS)

            bag = Path(directory) / 'header-order-regression.db3'
            create_bag(bag)
            connection = sqlite3.connect(str(bag))
            try:
                topic_id = connection.execute(
                    'SELECT id FROM topics WHERE name=?', (
                        STREAM_TOPICS['rgb'],)).fetchone()[0]
                rows = connection.execute(
                    'SELECT id FROM messages WHERE topic_id=? ORDER BY id', (
                        topic_id,)).fetchall()
                connection.execute(
                    'UPDATE messages SET data=? WHERE id=?', (
                        _image(900_000_000,
                               'camera_color_optical_frame'), rows[1][0]))
                connection.commit()
            finally:
                connection.close()
            with self.assertRaisesRegex(ValueError, 'strictly increasing'):
                inspect_sqlite_bag(
                    bag, 'header-order-regression', 'background',
                    STREAM_TOPICS)

    def test_camera_info_projection_intrinsics_and_binning_fail_closed(self):
        cases = (
            ('cx_large', 1e12, 1.5, 0, 0),
            ('cy_negative', 2.0, -1e12, 0, 0),
            ('binning_x_large', 2.0, 1.5, 2 ** 32 - 1, 0),
            ('binning_y_large', 2.0, 1.5, 0, 2 ** 32 - 1),
        )
        for name, cx, cy, binning_x, binning_y in cases:
            with self.subTest(name=name):
                payload = _camera_info_with_calibration(
                    1, 'camera_color_optical_frame', cx, cy,
                    binning_x, binning_y)
                with self.assertRaisesRegex(ValueError, 'CameraInfo'):
                    decode_cdr_payload(
                        'sensor_msgs/msg/CameraInfo', payload)

    def test_record_timestamps_must_be_ordered_and_bound_to_headers(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            same = root / 'same.db3'
            create_bag(same)
            connection = sqlite3.connect(str(same))
            try:
                rgb_id = connection.execute(
                    'SELECT id FROM topics WHERE name=?', (
                        STREAM_TOPICS['rgb'],)).fetchone()[0]
                rgb_rows = connection.execute(
                    'SELECT id, timestamp FROM messages WHERE topic_id=? '
                    'ORDER BY id', (rgb_id,)).fetchall()
                connection.execute(
                    'UPDATE messages SET timestamp=? WHERE id=?',
                    (rgb_rows[0][1], rgb_rows[1][0]))
                connection.commit()
            finally:
                connection.close()
            with self.assertRaisesRegex(ValueError, 'strictly increasing'):
                inspect_sqlite_bag(
                    same, 'same', 'background', STREAM_TOPICS)

            skew = root / 'skew.db3'
            create_bag(skew)
            connection = sqlite3.connect(str(skew))
            try:
                connection.execute(
                    'UPDATE messages SET timestamp=timestamp+2000000000')
                connection.commit()
            finally:
                connection.close()
            with self.assertRaisesRegex(ValueError, 'timestamp skew'):
                inspect_sqlite_bag(
                    skew, 'skew', 'background', STREAM_TOPICS)

            static_future = root / 'static-future.db3'
            create_bag(static_future)
            connection = sqlite3.connect(str(static_future))
            try:
                static_id = connection.execute(
                    "SELECT id FROM topics WHERE name='/tf_static'"
                ).fetchone()[0]
                message_id, record_stamp = connection.execute(
                    'SELECT id, timestamp FROM messages WHERE topic_id=?',
                    (static_id,)).fetchone()
                connection.execute(
                    'UPDATE messages SET data=? WHERE id=?', (
                        _tf(record_stamp + 1_000_000_000,
                            'base_link', 'camera_mount'), message_id))
                connection.commit()
            finally:
                connection.close()
            with self.assertRaisesRegex(ValueError, 'record/Header'):
                inspect_sqlite_bag(
                    static_future, 'static-future', 'background',
                    STREAM_TOPICS)

            static_latched = root / 'static-latched.db3'
            create_bag(static_latched)
            connection = sqlite3.connect(str(static_latched))
            try:
                connection.execute(
                    "UPDATE messages SET timestamp=timestamp+2000000000 "
                    "WHERE topic_id=(SELECT id FROM topics "
                    "WHERE name='/tf_static')")
                connection.commit()
            finally:
                connection.close()
            report = inspect_sqlite_bag(
                static_latched, 'static-latched', 'background',
                STREAM_TOPICS)
            static_message = next(
                item for item in report['messages']
                if item['topic'] == '/tf_static')
            self.assertGreater(
                static_message['record_header_skew_sec'],
                0.75)

    def test_cross_stream_header_span_is_rejected_not_record_time(self):
        with TemporaryDirectory() as directory:
            bag = Path(directory) / 'span.db3'
            offsets = {
                'rgb': 0, 'aligned_depth': 200_000_000,
                'rgb_camera_info': 0, 'depth_camera_info': 0,
            }
            create_bag(bag, header_offsets_ns=offsets)
            report = inspect_sqlite_bag(
                bag, 'span', 'background', STREAM_TOPICS)
            self.assertEqual(2, report['rgb_candidate_count'])
            self.assertEqual(1, report['accepted_bundle_count'])
            self.assertEqual(1, report['rejected_rgb_count'])
            self.assertEqual(0.5, report['rejection_rate'])
            self.assertEqual(
                1, report['rejection_reasons']['over_sync_span'])

    def test_selected_bundle_stream_headers_remain_monotonic(self):
        with TemporaryDirectory() as directory:
            bag = Path(directory) / 'monotonic-pairing.db3'
            offsets = {
                'rgb': 0, 'aligned_depth': 10_000_000,
                'rgb_camera_info': 0, 'depth_camera_info': 0,
            }
            create_bag(
                bag, frame_count=2, header_offsets_ns=offsets,
                frame_period_ns=50_000_000)
            connection = sqlite3.connect(str(bag))
            try:
                depth_topic = connection.execute(
                    'SELECT id FROM topics WHERE name=?', (
                        STREAM_TOPICS['aligned_depth'],)).fetchone()[0]
                rows = connection.execute(
                    'SELECT id FROM messages WHERE topic_id=? ORDER BY id', (
                        depth_topic,)).fetchall()
                connection.execute(
                    'UPDATE messages SET data=? WHERE id=?', (
                        _image(910_000_000,
                               'camera_color_optical_frame', '16UC1'),
                        rows[0][0]))
                connection.execute(
                    'UPDATE messages SET data=? WHERE id=?', (
                        _image(1_010_000_000,
                               'camera_color_optical_frame', '16UC1'),
                        rows[1][0]))
                rgb_topic = connection.execute(
                    'SELECT id FROM topics WHERE name=?', (
                        STREAM_TOPICS['rgb'],)).fetchone()[0]
                rgb_rows = connection.execute(
                    'SELECT id FROM messages WHERE topic_id=? ORDER BY id', (
                        rgb_topic,)).fetchall()
                connection.execute(
                    'UPDATE messages SET data=? WHERE id=?', (
                        _image(1_000_000_000,
                               'camera_color_optical_frame'),
                        rgb_rows[0][0]))
                connection.execute(
                    'UPDATE messages SET data=? WHERE id=?', (
                        _image(1_050_000_000,
                               'camera_color_optical_frame'),
                        rgb_rows[1][0]))
                connection.commit()
            finally:
                connection.close()
            report = inspect_sqlite_bag(
                bag, 'monotonic', 'background', STREAM_TOPICS)
            selected = [
                item['header_stamps_ns']['aligned_depth']
                for item in report['accepted_bundles']]
            self.assertEqual(sorted(selected), selected)
            self.assertEqual(len(selected), len(set(selected)))

    def test_rejection_rate_denominator_and_seventy_percent_unmatched(self):
        with TemporaryDirectory() as directory:
            bag = Path(directory) / 'rejection.db3'
            create_bag(bag, frame_count=10, accepted_count=3)
            report = inspect_sqlite_bag(
                bag, 'rejection', 'background', STREAM_TOPICS)
            self.assertEqual(10, report['rgb_candidate_count'])
            self.assertEqual(3, report['accepted_bundle_count'])
            self.assertEqual(7, report['rejected_rgb_count'])
            self.assertAlmostEqual(0.7, report['rejection_rate'])
            self.assertEqual(7, report['total_unpaired_message_count'])
            self.assertEqual(
                7, report['unmatched_message_count_by_stream']['rgb'])
            self.assertGreater(report['total_unpaired_rate'], 0.0)

            boundary = Path(directory) / 'boundary-five-percent.db3'
            create_bag(boundary, frame_count=20, accepted_count=19)
            report = inspect_sqlite_bag(
                boundary, 'boundary-five-percent', 'background',
                STREAM_TOPICS)
            self.assertEqual(0.05, report['rejection_rate'])
            self.assertEqual(
                1, report['unmatched_message_count_by_stream']['rgb'])

            extra = Path(directory) / 'extra-depth.db3'
            create_bag(extra, frame_count=2)
            connection = sqlite3.connect(str(extra))
            try:
                topic_id = connection.execute(
                    'SELECT id FROM topics WHERE name=?', (
                        STREAM_TOPICS['aligned_depth'],)).fetchone()[0]
                next_id = connection.execute(
                    'SELECT MAX(id)+1 FROM messages').fetchone()[0]
                connection.execute(
                    'INSERT INTO messages VALUES (?, ?, ?, ?)', (
                        next_id, topic_id, 1_350_000_000,
                        _image(1_300_000_000,
                               'camera_color_optical_frame', '16UC1')))
                connection.commit()
            finally:
                connection.close()
            report = inspect_sqlite_bag(
                extra, 'extra-depth', 'background', STREAM_TOPICS)
            self.assertEqual(
                1, report['unmatched_message_count_by_stream'][
                    'aligned_depth'])
            self.assertGreater(report['total_unpaired_rate'], 0.0)

            empty = Path(directory) / 'empty-rgb.db3'
            rows = topic_rows()
            connection = sqlite3.connect(str(empty))
            try:
                _create_schema(connection)
                connection.executemany(
                    'INSERT INTO topics VALUES (?, ?, ?, ?, ?)', rows)
                topic_ids = {row[1]: row[0] for row in rows}
                messages = [
                    (1, topic_ids['/tf_static'], 1,
                     _tf(1, 'base_link', 'camera_mount')),
                    (2, topic_ids['/tf'], 1,
                     _tf(1, 'camera_mount', 'camera_color_optical_frame')),
                ]
                for index, name in enumerate(
                        ('aligned_depth', 'rgb_camera_info',
                         'depth_camera_info'), 3):
                    payload = (
                        _image(1, 'camera_color_optical_frame', '16UC1')
                        if name == 'aligned_depth' else
                        _camera_info(1, 'camera_color_optical_frame'))
                    messages.append((
                        index, topic_ids[STREAM_TOPICS[name]], 1, payload))
                connection.executemany(
                    'INSERT INTO messages VALUES (?, ?, ?, ?)', messages)
                connection.commit()
            finally:
                connection.close()
            with self.assertRaisesRegex(ValueError, 'at least one message'):
                inspect_sqlite_bag(
                    empty, 'empty-rgb', 'background', STREAM_TOPICS)

    def test_tf_payload_must_build_camera_to_base_chain(self):
        with TemporaryDirectory() as directory:
            bag = Path(directory) / 'bad-tf.db3'
            create_bag(bag, link_tf=False)
            with self.assertRaisesRegex(ValueError, 'base-to-camera'):
                inspect_sqlite_bag(
                    bag, 'bad-tf', 'background', STREAM_TOPICS)

            static_only = Path(directory) / 'static-only-chain.db3'
            create_bag(static_only)
            connection = sqlite3.connect(str(static_only))
            try:
                tf_id = connection.execute(
                    "SELECT id FROM topics WHERE name='/tf'").fetchone()[0]
                static_id = connection.execute(
                    "SELECT id FROM topics WHERE name='/tf_static'").fetchone()[0]
                dynamic_rows = connection.execute(
                    'SELECT id FROM messages WHERE topic_id=?', (tf_id,)
                ).fetchall()
                for index, row in enumerate(dynamic_rows):
                    connection.execute(
                        'UPDATE messages SET data=? WHERE id=?', (
                            _tf(1_000_000_000 + index * 100_000_000,
                                'other', 'unrelated'), row[0]))
                static_row = connection.execute(
                    'SELECT id FROM messages WHERE topic_id=?', (static_id,)
                ).fetchone()[0]
                connection.execute(
                    'UPDATE messages SET data=? WHERE id=?', (
                        _tf(1_000_000_000, 'base_link',
                            'camera_color_optical_frame', (0.1, 0.0, 0.2)),
                        static_row))
                connection.commit()
            finally:
                connection.close()
            with self.assertRaisesRegex(ValueError, 'both /tf'):
                inspect_sqlite_bag(
                    static_only, 'static-only', 'background', STREAM_TOPICS)

    def test_stream_role_encoding_is_fail_closed(self):
        with TemporaryDirectory() as directory:
            bad_rgb = Path(directory) / 'bad-rgb-encoding.db3'
            create_bag(
                bad_rgb, payload_mutator=lambda name, index, payload: (
                    _image(1_000_000_000 + index * 100_000_000,
                           'camera_color_optical_frame', '16UC1')
                    if name == 'rgb' else payload))
            with self.assertRaisesRegex(ValueError, 'RGB Image encoding'):
                inspect_sqlite_bag(
                    bad_rgb, 'bad-rgb', 'background', STREAM_TOPICS)
            unknown = Path(directory) / 'unknown-rgb-encoding.db3'
            create_bag(
                unknown, payload_mutator=lambda name, index, payload: (
                    _image(1_000_000_000 + index * 100_000_000,
                           'camera_color_optical_frame', 'xyz')
                    if name == 'rgb' else payload))
            with self.assertRaisesRegex(ValueError, 'RGB Image encoding'):
                inspect_sqlite_bag(
                    unknown, 'unknown-rgb', 'background', STREAM_TOPICS)

            odd_depth_step = Path(directory) / 'odd-depth-step.db3'
            create_bag(
                odd_depth_step,
                payload_mutator=lambda name, index, payload: (
                    _image_with_step(
                        1_020_000_000 + index * 100_000_000,
                        'camera_color_optical_frame', '16UC1', 9)
                    if name == 'aligned_depth' else payload))
            with self.assertRaisesRegex(ValueError, 'depth Image encoding'):
                inspect_sqlite_bag(
                    odd_depth_step, 'odd-depth-step', 'background',
                    STREAM_TOPICS)

    def test_header_and_tf_frame_ids_are_fail_closed(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            invalid_frames = (
                ' ', '/camera_color_optical_frame', 'camera color',
                'camera\nframe', 'camera//frame', 'camera/../frame')
            for index, frame_id in enumerate(invalid_frames):
                with self.subTest(frame_id=repr(frame_id)):
                    bag = root / ('invalid-frame-{}.db3'.format(index))
                    create_bag(
                        bag, payload_mutator=lambda name, frame_index, payload,
                        bad=frame_id: (
                            _image(
                                1_000_000_000 + frame_index * 100_000_000,
                                bad)
                            if name == 'rgb' else payload))
                    with self.assertRaisesRegex(ValueError, 'CDR payload'):
                        inspect_sqlite_bag(
                            bag, 'invalid-frame', 'background', STREAM_TOPICS)

            bad_child = root / 'invalid-tf-child.db3'
            create_bag(bad_child)
            connection = sqlite3.connect(str(bad_child))
            try:
                tf_id = connection.execute(
                    "SELECT id FROM topics WHERE name='/tf'").fetchone()[0]
                row_id = connection.execute(
                    'SELECT id FROM messages WHERE topic_id=? ORDER BY id '
                    'LIMIT 1', (tf_id,)).fetchone()[0]
                connection.execute(
                    'UPDATE messages SET data=? WHERE id=?', (
                        _tf(1_000_000_000, 'camera_mount', '/bad_child'),
                        row_id))
                connection.commit()
            finally:
                connection.close()
            with self.assertRaisesRegex(ValueError, 'CDR payload'):
                inspect_sqlite_bag(
                    bad_child, 'invalid-tf-child', 'background', STREAM_TOPICS)

    def test_dynamic_tf_is_bound_to_every_bundle_and_must_be_stable(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            stale = root / 'stale.db3'
            create_bag(
                stale, frame_count=3, frame_period_ns=100_000_000,
                dynamic_tf_every_frame=False)
            with self.assertRaisesRegex(ValueError, 'one unambiguous'):
                inspect_sqlite_bag(
                    stale, 'stale', 'background', STREAM_TOPICS,
                    max_dynamic_tf_age_sec=0.05)

            changing = root / 'changing.db3'
            create_bag(
                changing, frame_count=3,
                dynamic_tf_translations=[
                    (9.0, 8.0, 7.0), (9.0, 8.0, 7.0),
                    (0.0, 0.0, 0.0)])
            with self.assertRaisesRegex(ValueError, 'not stable'):
                inspect_sqlite_bag(
                    changing, 'changing', 'background', STREAM_TOPICS)

            non_monotonic = root / 'tf-header-regression.db3'
            create_bag(non_monotonic, frame_count=3)
            connection = sqlite3.connect(str(non_monotonic))
            try:
                tf_id = connection.execute(
                    "SELECT id FROM topics WHERE name='/tf'").fetchone()[0]
                rows = connection.execute(
                    'SELECT id FROM messages WHERE topic_id=? ORDER BY id', (
                        tf_id,)).fetchall()
                connection.execute(
                    'UPDATE messages SET data=? WHERE id=?', (
                        _tf(1_140_000_000, 'camera_mount',
                            'camera_color_optical_frame'), rows[1][0]))
                connection.execute(
                    'UPDATE messages SET data=? WHERE id=?', (
                        _tf(1_130_000_000, 'camera_mount',
                            'camera_color_optical_frame'), rows[2][0]))
                connection.commit()
            finally:
                connection.close()
            with self.assertRaisesRegex(ValueError, 'strictly increasing'):
                inspect_sqlite_bag(
                    non_monotonic, 'tf-regression', 'background',
                    STREAM_TOPICS)

    def test_frozen_manifest_rejects_topic_aliases_and_tampering(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            bag = root / 'capture.db3'
            create_bag(bag)
            aliases = {
                role: '/unrelated/' + role for role in STREAM_TOPICS}
            with self.assertRaisesRegex(ValueError, 'frozen'):
                inspect_sqlite_bag(
                    bag, 'alias', 'background', aliases)
            manifest = root / 'manifest.json'
            manifest.write_text(json.dumps({
                'schema_version': 1, 'manifest_id': 'forged',
                'read_only': True, 'authorizes_motion': False,
                'publishes_ros_messages': False, 'topics': [],
            }), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'manifest'):
                inspect_sqlite_bag(
                    bag, 'forged', 'background', STREAM_TOPICS, manifest)

            policy = json.loads(default_topic_manifest_path().read_text(
                encoding='utf-8'))
            for item in policy['topics']:
                item['qos']['liveliness'] = ['MANUAL_BY_NODE']
            same_id = root / 'same-id-altered-policy.json'
            same_id.write_text(
                json.dumps(policy, sort_keys=True) + '\n', encoding='utf-8')
            manual_qos = {
                topic: qos.replace('liveliness: 1', 'liveliness: 2')
                for topic, qos in (
                    (STREAM_TOPICS['rgb'], QOS_SENSOR),
                    (STREAM_TOPICS['aligned_depth'], QOS_SENSOR),
                    (STREAM_TOPICS['rgb_camera_info'], QOS_SENSOR),
                    (STREAM_TOPICS['depth_camera_info'], QOS_SENSOR),
                    ('/tf', QOS_TF),
                    ('/tf_static', QOS_TF_STATIC),
                )
            }
            matching_bag = root / 'same-id-matching-qos.db3'
            create_bag(
                matching_bag,
                topic_rows=topic_rows(qos_overrides=manual_qos))
            with self.assertRaisesRegex(ValueError, 'frozen artifact'):
                inspect_sqlite_bag(
                    matching_bag, 'same-id-altered-policy', 'background',
                    STREAM_TOPICS, same_id)

    def test_control_type_and_name_variants_fail_closed(self):
        self.assertTrue(is_control_topic(
            '/other/cmd_vel', 'geometry_msgs/msg/Twist'))
        self.assertTrue(is_control_topic(
            '/move_base_simple/goal', 'geometry_msgs/msg/PoseStamped'))
        self.assertTrue(is_control_topic(
            '/cleanup/gripper/goal', 'custom_msgs/msg/Request'))
        self.assertFalse(is_control_topic(
            '/camera/color/image_raw', 'sensor_msgs/msg/Image'))

    def test_decoder_directly_rejects_bad_encapsulation_and_trailing_bytes(self):
        with self.assertRaisesRegex(ValueError, 'encapsulation'):
            _CdrReader(b'BAD!')
        payload = _image(1, 'camera') + b'\x00'
        with self.assertRaisesRegex(ValueError, 'trailing'):
            decode_cdr_payload('sensor_msgs/msg/Image', payload)

    def test_stream_mapping_must_be_exact_unique_and_not_tf_alias(self):
        with TemporaryDirectory() as directory:
            bag = Path(directory) / 'capture.db3'
            create_bag(bag)
            duplicate = dict(STREAM_TOPICS)
            duplicate['aligned_depth'] = duplicate['rgb']
            with self.assertRaisesRegex(ValueError, 'unique'):
                inspect_sqlite_bag(
                    bag, 'duplicate', 'background', duplicate)
            missing = dict(STREAM_TOPICS)
            missing.pop('depth_camera_info')
            with self.assertRaisesRegex(ValueError, 'exactly'):
                inspect_sqlite_bag(
                    bag, 'missing', 'background', missing)
            alias = dict(STREAM_TOPICS)
            alias['rgb'] = '/tf'
            with self.assertRaisesRegex(ValueError, 'alias'):
                inspect_sqlite_bag(
                    bag, 'alias', 'background', alias)

    def test_non_db3_bad_schema_duplicate_message_and_cli_contract(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            wrong = root / 'capture.sqlite'
            wrong.write_bytes(b'')
            with self.assertRaisesRegex(ValueError, '.db3'):
                inspect_sqlite_bag(
                    wrong, 'wrong', 'background', STREAM_TOPICS)
            bad = root / 'bad.db3'
            connection = sqlite3.connect(str(bad))
            try:
                _create_schema(connection, valid=False)
                connection.commit()
            finally:
                connection.close()
            with self.assertRaisesRegex(ValueError, 'columns missing'):
                inspect_sqlite_bag(
                    bad, 'bad', 'background', STREAM_TOPICS)

            bag = root / 'good.db3'
            create_bag(bag)
            output = root / 'index.json'
            args = [
                '--bag', str(bag), '--capture-id', 'cli',
                '--scene', 'background',
                '--rgb-topic', STREAM_TOPICS['rgb'],
                '--aligned-depth-topic', STREAM_TOPICS['aligned_depth'],
                '--rgb-camera-info-topic', STREAM_TOPICS['rgb_camera_info'],
                '--depth-camera-info-topic',
                STREAM_TOPICS['depth_camera_info'],
                '--output', str(output),
            ]
            self.assertEqual(0, main(args))
            self.assertEqual(3, json.loads(
                output.read_text(encoding='utf-8'))['schema_version'])
            with self.assertRaisesRegex(SystemExit, 'must not already exist'):
                main(args)

    def test_source_has_no_ros_network_or_control_api(self):
        source = Path(inspect_sqlite_bag.__code__.co_filename).read_text(
            encoding='utf-8')
        for token in (
                'import rclpy', 'import rospy', 'socket.', 'requests.',
                'create_publisher(', '.publish(', 'create_subscription(',
                'ActionClient', 'ActionServer', 'Twist('):
            self.assertNotIn(token, source)
        self.assertIn('mode=ro&immutable=1', source)
        self.assertIn('PRAGMA query_only = ON', source)


if __name__ == '__main__':
    unittest.main()

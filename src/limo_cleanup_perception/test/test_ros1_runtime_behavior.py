"""ROS-independent behavior tests for the ROS1 Noetic perception runtime.

The tests use only in-memory images and fake ROS modules.  They never start a
ROS graph, open a camera, publish control messages, or authorize motion.
"""

import copy
import json
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np


WORKSPACE = Path(__file__).resolve().parents[3]
OVERLAY = Path(os.environ.get(
    'LIMO_ROS1_RUNTIME_OVERLAY',
    str(WORKSPACE / 'ros1_overlay_src' /
        'limo_cleanup_ros1_perception'))).resolve()
OVERLAY_PYTHON = OVERLAY / 'src'
HOST_PYTHON = WORKSPACE / 'src' / 'limo_cleanup_perception'
for candidate in (str(OVERLAY_PYTHON), str(HOST_PYTHON), str(WORKSPACE)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from limo_cleanup_perception import perception_readiness as host_readiness
from limo_cleanup_ros1_perception import ros1_adapter
from limo_cleanup_ros1_perception.perception_core import Detection2D
from limo_cleanup_ros1_perception.rgbd_contract import StreamMetadata


CAMERA_FRAME = 'camera_color_optical_frame'
MODEL_SET_SHA256 = 'a' * 64
CAMERA_MATRIX = (100.0, 0.0, 50.0,
                 0.0, 100.0, 50.0,
                 0.0, 0.0, 1.0)
OUTPUT_TOPICS = {
    '/cleanup/perception/frames',
    '/cleanup/detection/raw',
    '/cleanup/perception_status',
}
CONTROL_TOPIC_TOKENS = (
    'cmd_vel', 'move_base', 'navigation', 'goal', 'cancel',
    'arm', 'gripper', 'trajectory', 'controller/command',
)


class _Detector:
    def __init__(self, bottles=(), bins=()):
        self.bottles = tuple(bottles)
        self.bins = tuple(bins)
        self.model_set_sha256 = MODEL_SET_SHA256
        self.calls = 0
        self.images = []

    def infer(self, image):
        self.calls += 1
        self.images.append(image.copy())
        return self.bottles, self.bins


def _metadata(stamps=None, frames=None, depth_encoding='16UC1'):
    stamps = stamps or (10.0, 10.01, 10.02, 10.03)
    frames = frames or (CAMERA_FRAME,) * 4
    return (
        StreamMetadata(
            'rgb', stamps[0], frames[0], 100, 100, 'bgr8'),
        StreamMetadata(
            'depth', stamps[1], frames[1], 100, 100, depth_encoding),
        StreamMetadata(
            'rgb_info', stamps[2], frames[2], 100, 100, ''),
        StreamMetadata(
            'depth_info', stamps[3], frames[3], 100, 100, ''),
    )


def _images(depth_mm=1000):
    return (
        np.zeros((100, 100, 3), dtype=np.uint8),
        np.full((100, 100), depth_mm, dtype=np.uint16),
    )


def _target(result, object_class, status):
    matches = [
        item for item in result['targets']
        if item['object_class'] == object_class and item['status'] == status]
    if len(matches) != 1:
        raise AssertionError(
            'expected one {} target with status {}, got {}'.format(
                object_class, status, len(matches)))
    return matches[0]


class PerceptionPipelineBehaviorTests(unittest.TestCase):
    def test_dual_class_projection_bin_filter_and_legacy_output(self):
        bottle_in_bin = Detection2D(
            'plastic_bottle', 0.82, 40.0, 10.0, 50.0, 35.0,
            'bottle-model.pt')
        bottle_outside = Detection2D(
            'plastic_bottle', 0.91, 5.0, 60.0, 15.0, 90.0,
            'bottle-model.pt')
        trash_bin = Detection2D(
            'trash_bin', 0.94, 20.0, 5.0, 80.0, 95.0,
            'bin-model.pt')
        detector = _Detector((bottle_in_bin, bottle_outside), (trash_bin,))
        pipeline = ros1_adapter.PerceptionPipeline(
            detector, capture_id='behavior-test')
        rgb, depth = _images()

        result = pipeline.process(
            rgb, depth, CAMERA_MATRIX, _metadata(), task_id='task-17')

        self.assertEqual(detector.calls, 1)
        self.assertTrue(np.array_equal(detector.images[0], rgb))
        self.assertTrue(result['valid'])
        self.assertEqual(result['status'], 'targets_ready')
        self.assertEqual(result['frame_id'], CAMERA_FRAME)
        self.assertEqual(result['task_id'], 'task-17')
        self.assertEqual(result['capture_id'], 'behavior-test')
        self.assertEqual(result['model_binding_sha256'], MODEL_SET_SHA256)
        self.assertEqual(len(result['bundle_id']), 64)
        self.assertEqual(len(result['targets']), 3)

        active = _target(result, 'plastic_bottle', 'active')
        disposed = _target(result, 'plastic_bottle', 'already_in_bin')
        bin_target = _target(result, 'trash_bin', 'observed')
        self.assertTrue(active['valid'])
        self.assertTrue(active['actionable'])
        self.assertFalse(disposed['actionable'])
        self.assertFalse(bin_target['actionable'])
        self.assertAlmostEqual(active['depth_m'], 1.0)
        self.assertAlmostEqual(active['position'][0], -0.4)
        self.assertAlmostEqual(active['position'][1], 0.25)
        self.assertAlmostEqual(active['position'][2], 1.0)
        self.assertAlmostEqual(bin_target['position'][0], 0.0)
        self.assertAlmostEqual(bin_target['position'][1], 0.0)
        self.assertAlmostEqual(bin_target['position'][2], 1.0)
        self.assertEqual(
            active['position_semantics'],
            'camera_frame_aligned_depth_roi_median_at_clipped_bbox_center')
        self.assertEqual(
            result['legacy_bottle']['observation_id'],
            active['observation_id'])

    def test_depth_mismatch_keeps_overlapping_bottle_actionable(self):
        bottle = Detection2D(
            'plastic_bottle', 0.88, 40.0, 10.0, 50.0, 35.0,
            'bottle-model.pt')
        trash_bin = Detection2D(
            'trash_bin', 0.93, 20.0, 5.0, 80.0, 95.0,
            'bin-model.pt')
        detector = _Detector((bottle,), (trash_bin,))
        pipeline = ros1_adapter.PerceptionPipeline(detector)
        rgb, depth = _images()
        depth[17:28, 43:47] = 1500

        result = pipeline.process(rgb, depth, CAMERA_MATRIX, _metadata())

        active = _target(result, 'plastic_bottle', 'active')
        self.assertNotIn(
            'already_in_bin', [item['status'] for item in result['targets']])
        self.assertAlmostEqual(active['depth_m'], 1.5)
        self.assertTrue(active['actionable'])
        self.assertIsNotNone(result['legacy_bottle'])

    def test_four_stream_contract_rejects_before_inference(self):
        detector = _Detector((Detection2D(
            'plastic_bottle', 0.9, 5.0, 5.0, 25.0, 40.0),), ())
        pipeline = ros1_adapter.PerceptionPipeline(
            detector, max_sync_delta_sec=0.05)
        rgb, depth = _images()

        result = pipeline.process(
            rgb, depth, CAMERA_MATRIX,
            _metadata(stamps=(10.0, 10.01, 10.02, 10.30)))

        self.assertEqual(detector.calls, 0)
        self.assertFalse(result['valid'])
        self.assertEqual(result['status'], 'rgbd_contract_rejected')
        self.assertIn('timestamp_span_exceeded', result['error_code'])
        self.assertEqual(result['targets'], [])
        self.assertIsNone(result['legacy_bottle'])

    def test_frame_mismatch_and_non_four_stream_input_fail_closed(self):
        detector = _Detector()
        pipeline = ros1_adapter.PerceptionPipeline(detector)
        rgb, depth = _images()
        frames = (CAMERA_FRAME, CAMERA_FRAME, 'wrong_frame', CAMERA_FRAME)

        result = pipeline.process(
            rgb, depth, CAMERA_MATRIX, _metadata(frames=frames))
        self.assertFalse(result['valid'])
        self.assertIn('frame_mismatch', result['error_code'])
        self.assertEqual(detector.calls, 0)
        with self.assertRaisesRegex(ValueError, 'exactly four'):
            pipeline.process(rgb, depth, CAMERA_MATRIX, _metadata()[:3])

    def test_invalid_depth_rejects_all_targets_and_legacy_output(self):
        detector = _Detector(
            (Detection2D(
                'plastic_bottle', 0.9, 5.0, 60.0, 15.0, 90.0,
                'bottle-model.pt'),),
            (Detection2D(
                'trash_bin', 0.9, 20.0, 5.0, 80.0, 95.0,
                'bin-model.pt'),))
        pipeline = ros1_adapter.PerceptionPipeline(detector)
        rgb, depth = _images(depth_mm=0)

        result = pipeline.process(rgb, depth, CAMERA_MATRIX, _metadata())

        self.assertFalse(result['valid'])
        self.assertEqual(result['status'], 'targets_invalid')
        self.assertEqual(result['error_code'], 'all_target_projections_invalid')
        self.assertTrue(result['targets'])
        self.assertTrue(all(not item['valid'] for item in result['targets']))
        self.assertIsNone(result['legacy_bottle'])

    def test_empty_dual_model_result_is_valid_no_targets(self):
        detector = _Detector()
        pipeline = ros1_adapter.PerceptionPipeline(detector)
        rgb, depth = _images()

        result = pipeline.process(rgb, depth, CAMERA_MATRIX, _metadata())

        self.assertTrue(result['valid'])
        self.assertEqual(result['status'], 'no_targets')
        self.assertEqual(result['targets'], [])
        self.assertIsNone(result['legacy_bottle'])


class _Stamp:
    def __init__(self, value):
        self.value = float(value)

    def to_sec(self):
        return self.value


class _Header:
    def __init__(self, stamp=20.0, frame_id=CAMERA_FRAME):
        self.stamp = _Stamp(stamp)
        self.frame_id = frame_id


class _Point:
    def __init__(self):
        self.x = 0.0
        self.y = 0.0
        self.z = 0.0


class _PerceptionTarget:
    def __init__(self):
        self.position = _Point()
        self.size = _Point()


class _PerceptionFrame:
    pass


class _ObjectDetection:
    def __init__(self):
        self.position = _Point()
        self.size = _Point()


class _String:
    def __init__(self, data=''):
        self.data = data


class _Image:
    pass


class _CameraInfo:
    pass


class _Publisher:
    def __init__(self, runtime, topic, message_type, queue_size, latch):
        self.runtime = runtime
        self.topic = topic
        self.message_type = message_type
        self.queue_size = queue_size
        self.latch = latch
        self.messages = []

    def publish(self, message):
        self.messages.append(message)


class _Subscriber:
    def __init__(self, runtime, topic, message_type):
        self.runtime = runtime
        self.topic = topic
        self.message_type = message_type


class _Synchronizer:
    def __init__(self, runtime, subscribers, queue_size, slop,
                 allow_headerless):
        self.runtime = runtime
        self.subscribers = list(subscribers)
        self.queue_size = queue_size
        self.slop = slop
        self.allow_headerless = allow_headerless
        self.callback = None

    def registerCallback(self, callback):
        self.callback = callback


class _TfBuffer:
    def __init__(self, runtime, cache_time=None):
        self.runtime = runtime
        self.cache_time = cache_time
        self.lookup_calls = []
        self.lookup_error = None

    def lookup_transform(self, target, source, stamp, timeout):
        self.lookup_calls.append((target, source, stamp, timeout))
        if self.lookup_error is not None:
            raise self.lookup_error
        return object()


class _FakeRosRuntime:
    def __init__(self):
        self.params = {}
        self.publishers = []
        self.subscribers = []
        self.synchronizers = []
        self.buffers = []
        self.listeners = []
        self.service_calls = []
        self.action_calls = []

    def modules(self):
        runtime = self
        rospy = types.ModuleType('rospy')

        class Duration:
            def __init__(self, seconds):
                self.seconds = float(seconds)

        def get_param(name, default=None):
            return runtime.params.get(name, default)

        def publisher(topic, message_type, queue_size=10, latch=False):
            if any(token in topic.lower() for token in CONTROL_TOPIC_TOKENS):
                raise AssertionError('control publisher forbidden: ' + topic)
            item = _Publisher(
                runtime, topic, message_type, queue_size, latch)
            runtime.publishers.append(item)
            return item

        def service(*args, **kwargs):
            runtime.service_calls.append((args, kwargs))
            raise AssertionError('service creation is forbidden')

        def service_proxy(*args, **kwargs):
            runtime.service_calls.append((args, kwargs))
            raise AssertionError('service proxy creation is forbidden')

        rospy.Duration = Duration
        rospy.get_param = get_param
        rospy.Publisher = publisher
        rospy.Service = service
        rospy.ServiceProxy = service_proxy

        message_filters = types.ModuleType('message_filters')

        def subscriber(topic, message_type):
            item = _Subscriber(runtime, topic, message_type)
            runtime.subscribers.append(item)
            return item

        def synchronizer(subscribers, queue_size, slop, allow_headerless):
            item = _Synchronizer(
                runtime, subscribers, queue_size, slop, allow_headerless)
            runtime.synchronizers.append(item)
            return item

        message_filters.Subscriber = subscriber
        message_filters.ApproximateTimeSynchronizer = synchronizer

        tf2_ros = types.ModuleType('tf2_ros')

        def buffer(cache_time=None):
            item = _TfBuffer(runtime, cache_time=cache_time)
            runtime.buffers.append(item)
            return item

        def listener(tf_buffer):
            runtime.listeners.append(tf_buffer)
            return object()

        tf2_ros.Buffer = buffer
        tf2_ros.TransformListener = listener

        generated = types.ModuleType('limo_cleanup_ros1_perception.msg')
        generated.PerceptionTarget = _PerceptionTarget
        generated.PerceptionFrame = _PerceptionFrame
        generated.ObjectDetection = _ObjectDetection

        sensor_msgs = types.ModuleType('sensor_msgs')
        sensor_msgs.__path__ = []
        sensor_msgs_msg = types.ModuleType('sensor_msgs.msg')
        sensor_msgs_msg.Image = _Image
        sensor_msgs_msg.CameraInfo = _CameraInfo
        sensor_msgs.msg = sensor_msgs_msg

        std_msgs = types.ModuleType('std_msgs')
        std_msgs.__path__ = []
        std_msgs_msg = types.ModuleType('std_msgs.msg')
        std_msgs_msg.String = _String
        std_msgs.msg = std_msgs_msg

        actionlib = types.ModuleType('actionlib')

        def action_client(*args, **kwargs):
            runtime.action_calls.append((args, kwargs))
            raise AssertionError('action client creation is forbidden')

        actionlib.SimpleActionClient = action_client
        actionlib.SimpleActionServer = action_client
        return {
            'rospy': rospy,
            'message_filters': message_filters,
            'tf2_ros': tf2_ros,
            'limo_cleanup_ros1_perception.msg': generated,
            'sensor_msgs': sensor_msgs,
            'sensor_msgs.msg': sensor_msgs_msg,
            'std_msgs': std_msgs,
            'std_msgs.msg': std_msgs_msg,
            'actionlib': actionlib,
        }


def _image_message(array, encoding, stamp=20.0, frame_id=CAMERA_FRAME):
    message = _Image()
    message.header = _Header(stamp, frame_id)
    message.height = int(array.shape[0])
    message.width = int(array.shape[1])
    message.encoding = encoding
    message.is_bigendian = False
    message.step = int(array.strides[0])
    message.data = array.tobytes()
    return message


def _camera_info(stamp=20.0, frame_id=CAMERA_FRAME):
    message = _CameraInfo()
    message.header = _Header(stamp, frame_id)
    message.height = 100
    message.width = 100
    message.K = list(CAMERA_MATRIX)
    return message


class Ros1AdapterBehaviorTests(unittest.TestCase):
    def _make_adapter(self, params=None):
        bottle = Detection2D(
            'plastic_bottle', 0.91, 5.0, 60.0, 15.0, 90.0,
            'bottle-model.pt')
        trash_bin = Detection2D(
            'trash_bin', 0.94, 20.0, 5.0, 80.0, 95.0,
            'bin-model.pt')
        detector = _Detector((bottle,), (trash_bin,))
        runtime = _FakeRosRuntime()
        runtime.params.update(params or {})
        modules = runtime.modules()
        module_patch = patch.dict(sys.modules, modules)
        detector_patch = patch.object(
            ros1_adapter, 'DualModelInference', return_value=detector)
        module_patch.start()
        detector_patch.start()
        self.addCleanup(detector_patch.stop)
        self.addCleanup(module_patch.stop)
        return runtime, detector, ros1_adapter.Ros1PerceptionAdapter()

    def _assert_formal_identity_rejected(self, params, expected_error):
        runtime = _FakeRosRuntime()
        runtime.params.update(params)
        detector = _Detector()
        with patch.dict(sys.modules, runtime.modules()), patch.object(
                ros1_adapter, 'DualModelInference',
                return_value=detector) as detector_factory:
            with self.assertRaisesRegex(
                    RuntimeError, '^{}$'.format(expected_error)):
                ros1_adapter.Ros1PerceptionAdapter()
        detector_factory.assert_not_called()
        self.assertEqual([], runtime.publishers)
        self.assertEqual([], runtime.subscribers)
        self.assertEqual([], runtime.synchronizers)
        self.assertEqual([], runtime.buffers)
        self.assertEqual([], runtime.listeners)

    def test_formal_capture_rejects_empty_task_before_detector_or_ros_io(self):
        self._assert_formal_identity_rejected({
            '~formal_capture_mode': True,
            '~task_id': '',
            '~capture_id': 'capture-17',
        }, 'formal_capture_task_id_invalid')

    def test_formal_capture_rejects_empty_capture_before_detector_or_ros_io(self):
        self._assert_formal_identity_rejected({
            '~formal_capture_mode': True,
            '~task_id': 'task-17',
            '~capture_id': '',
        }, 'formal_capture_capture_id_invalid')

    def test_formal_capture_rejects_whitespace_only_identities_before_ros_io(self):
        cases = (
            ('task', ' \t', 'capture-17',
             'formal_capture_task_id_invalid'),
            ('capture', 'task-17', ' \r\n',
             'formal_capture_capture_id_invalid'),
        )
        for name, task_id, capture_id, error in cases:
            with self.subTest(identity=name):
                self._assert_formal_identity_rejected({
                    '~formal_capture_mode': True,
                    '~task_id': task_id,
                    '~capture_id': capture_id,
                }, error)

    def test_formal_capture_accepts_and_strips_nonempty_identities(self):
        runtime, detector, adapter = self._make_adapter({
            '~formal_capture_mode': True,
            '~task_id': ' task-17 ',
            '~capture_id': ' capture-17 ',
        })

        self.assertTrue(adapter.formal_capture_mode)
        self.assertEqual('task-17', adapter.task_id)
        self.assertEqual('capture-17', adapter.pipeline.capture_id)
        self.assertIs(adapter.pipeline.detector, detector)
        self.assertEqual(3, len(runtime.publishers))
        self.assertEqual(4, len(runtime.subscribers))

    def test_generic_readonly_defaults_remain_compatible(self):
        runtime, detector, adapter = self._make_adapter()

        self.assertFalse(adapter.formal_capture_mode)
        self.assertEqual('', adapter.task_id)
        self.assertEqual('runtime-readonly', adapter.pipeline.capture_id)
        self.assertIs(adapter.pipeline.detector, detector)
        self.assertEqual(3, len(runtime.publishers))
        self.assertEqual(4, len(runtime.subscribers))

    def test_initialization_has_four_sensor_subscriptions_and_three_outputs(self):
        runtime, detector, adapter = self._make_adapter()

        self.assertIs(adapter.pipeline.detector, detector)
        self.assertIs(adapter.PerceptionFrame, _PerceptionFrame)
        self.assertIs(adapter.PerceptionTarget, _PerceptionTarget)
        self.assertIs(adapter.ObjectDetection, _ObjectDetection)
        self.assertEqual(
            {item.topic for item in runtime.subscribers},
            {
                '/camera/color/image_raw',
                '/camera/depth/image_raw',
                '/camera/color/camera_info',
                '/camera/depth/camera_info',
            })
        self.assertEqual(len(runtime.subscribers), 4)
        self.assertEqual({item.topic for item in runtime.publishers}, OUTPUT_TOPICS)
        self.assertEqual(len(runtime.publishers), 3)
        self.assertTrue(all(item.queue_size == 10 for item in runtime.publishers))
        self.assertTrue(all(item.latch is False for item in runtime.publishers))
        self.assertEqual(len(runtime.synchronizers), 1)
        synchronizer = runtime.synchronizers[0]
        self.assertEqual(synchronizer.subscribers, runtime.subscribers)
        self.assertEqual(synchronizer.queue_size, 10)
        self.assertAlmostEqual(synchronizer.slop, 0.15)
        self.assertFalse(synchronizer.allow_headerless)
        self.assertEqual(synchronizer.callback, adapter._callback)
        self.assertEqual(runtime.service_calls, [])
        self.assertEqual(runtime.action_calls, [])
        self.assertFalse(any(
            token in item.topic.lower()
            for item in runtime.publishers for token in CONTROL_TOPIC_TOKENS))

    def test_callback_publishes_camera_frame_when_tf_lookup_is_not_applied(self):
        runtime, detector, adapter = self._make_adapter()
        rgb = np.zeros((100, 100, 3), dtype=np.uint8)
        depth = np.full((100, 100), 1000, dtype=np.uint16)
        callback = runtime.synchronizers[0].callback

        callback(
            _image_message(rgb, 'bgr8'),
            _image_message(depth, '16UC1', stamp=20.01),
            _camera_info(stamp=20.02),
            _camera_info(stamp=20.03),
        )

        publishers = {item.topic: item for item in runtime.publishers}
        self.assertEqual(detector.calls, 1)
        self.assertEqual(len(runtime.buffers[0].lookup_calls), 1)
        lookup = runtime.buffers[0].lookup_calls[0]
        self.assertEqual(lookup[0], 'base_link')
        self.assertEqual(lookup[1], CAMERA_FRAME)
        self.assertEqual(len(publishers['/cleanup/perception/frames'].messages), 1)
        frame = publishers['/cleanup/perception/frames'].messages[0]
        self.assertAlmostEqual(frame.stamp.to_sec(), 20.0)
        self.assertEqual(frame.frame_id, CAMERA_FRAME)
        self.assertTrue(frame.valid)
        self.assertEqual(frame.tf_target_frame, 'base_link')
        self.assertFalse(frame.tf_valid)
        self.assertFalse(frame.tf_transform_applied)
        self.assertEqual(
            frame.tf_status,
            'tf_chain_available_not_applied_camera_frame_output')
        self.assertEqual(frame.tf_error_code, 'transform_not_applied')
        self.assertEqual(len(frame.targets), 2)
        self.assertTrue(all(item.valid for item in frame.targets))
        self.assertTrue(all(item.depth_m == 1.0 for item in frame.targets))
        self.assertTrue(all(item.depth_valid_pixels > 0 for item in frame.targets))
        self.assertTrue(all(
            0.0 < item.depth_valid_ratio <= 1.0 for item in frame.targets))
        self.assertTrue(all(
            item.position_semantics.startswith('camera_frame_')
            for item in frame.targets))

        legacy_messages = publishers['/cleanup/detection/raw'].messages
        self.assertEqual(len(legacy_messages), 1)
        self.assertAlmostEqual(legacy_messages[0].stamp.to_sec(), 20.0)
        self.assertEqual(legacy_messages[0].frame_id, CAMERA_FRAME)
        status_payload = json.loads(
            publishers['/cleanup/perception_status'].messages[-1].data)
        self.assertTrue(status_payload['read_only'])
        self.assertEqual(status_payload['state'], 'targets_ready')
        self.assertEqual(runtime.service_calls, [])
        self.assertEqual(runtime.action_calls, [])

    def test_tf_lookup_failure_and_callback_error_remain_read_only(self):
        runtime, detector, adapter = self._make_adapter()
        runtime.buffers[0].lookup_error = RuntimeError('no transform')
        status = adapter._tf_status(CAMERA_FRAME, _Stamp(20.0))
        self.assertEqual(status['target_frame'], 'base_link')
        self.assertFalse(status['valid'])
        self.assertFalse(status['transform_applied'])
        self.assertEqual(
            status['status'], 'tf_unavailable_camera_frame_retained')
        self.assertEqual(status['error_code'], 'RuntimeError')

        bad_rgb = np.zeros((100, 100, 3), dtype=np.uint8)
        callback = runtime.synchronizers[0].callback
        callback(
            _image_message(bad_rgb, 'unsupported-color'),
            _image_message(
                np.full((100, 100), 1000, dtype=np.uint16), '16UC1'),
            _camera_info(), _camera_info())

        publishers = {item.topic: item for item in runtime.publishers}
        self.assertEqual(
            publishers['/cleanup/perception/frames'].messages, [])
        self.assertEqual(publishers['/cleanup/detection/raw'].messages, [])
        status_payload = json.loads(
            publishers['/cleanup/perception_status'].messages[-1].data)
        self.assertEqual(status_payload['state'], 'processing_error')
        self.assertEqual(status_payload['error_code'], 'ValueError')
        self.assertTrue(status_payload['read_only'])
        self.assertEqual(detector.calls, 0)
        self.assertEqual(runtime.service_calls, [])
        self.assertEqual(runtime.action_calls, [])


class HostRuntimeAdmissionBehaviorTests(unittest.TestCase):
    def test_capability_self_reports_cannot_make_source_audit_pass(self):
        capability_path = (
            OVERLAY / 'config' / 'capability_matrix.json').resolve()
        adapter_path = (
            OVERLAY / 'src' / 'limo_cleanup_ros1_perception' /
            'ros1_adapter.py').resolve()
        baseline = json.loads(capability_path.read_text(encoding='utf-8'))
        names = sorted(baseline['capabilities'])
        all_true = {name: True for name in names}
        variants = [
            ('implementation_only', dict(baseline['capabilities'])),
            ('all_true', dict(all_true)),
        ] + [
            ('single_false:' + name, dict(
                all_true, **{name: False})) for name in names]
        original_read_text = Path.read_text
        original_read_bytes = Path.read_bytes

        for label, capabilities in variants:
            payload = copy.deepcopy(baseline)
            payload['implementation_validated'] = True
            payload['capabilities'] = capabilities
            encoded = json.dumps(payload, sort_keys=True)

            def controlled_read_text(path, *args, **kwargs):
                if Path(path).resolve() == capability_path:
                    return encoded
                return original_read_text(path, *args, **kwargs)

            def controlled_read_bytes(path, *args, **kwargs):
                raw = original_read_bytes(path, *args, **kwargs)
                if Path(path).resolve() == adapter_path:
                    return raw.replace(
                        b'validate_rgbd_contract(',
                        b'validate_rgbd_contract_DISABLED(')
                return raw

            with self.subTest(variant=label), patch.object(
                    Path, 'read_text', new=controlled_read_text), patch.object(
                        Path, 'read_bytes', new=controlled_read_bytes), patch.object(
                        host_readiness, '_validate_ros1_source_core_binding',
                        return_value={
                            'validated_pass': True, 'failures': []}), patch.object(
                        host_readiness, '_validate_ros1_model_loader',
                        return_value={
                            'validated_pass': True, 'failures': []}), patch.object(
                        host_readiness,
                        '_audit_ros1_formal_rosbag1_admission_source',
                        return_value={
                            'validated_pass': True, 'failures': []}):
                audit = host_readiness.audit_ros1_noetic_field_source_contract(
                    workspace=WORKSPACE)
                self.assertFalse(audit['pass'])
                self.assertFalse(audit['complete_runtime'])
                self.assertIn(
                    host_readiness.ROS1_RUNTIME_IMPLEMENTATION_VALIDATION_BLOCKER,
                    audit['failures'])
                runtime_gate = audit['runtime_implementation_admission']
                self.assertEqual(
                    runtime_gate['gate_id'],
                    host_readiness.ROS1_RUNTIME_IMPLEMENTATION_ADMISSION_GATE_ID)
                self.assertFalse(runtime_gate['validated_pass'])
                self.assertFalse(
                    runtime_gate['capability_declarations_consulted'])
                self.assertFalse(
                    runtime_gate['capability_declarations_can_override'])
                self.assertFalse(audit['capability_matrix_diagnostic'][
                    'authoritative_for_complete_runtime'])


if __name__ == '__main__':
    unittest.main()

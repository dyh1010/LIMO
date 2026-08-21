"""Static contract for the observed ROS1 Noetic DaBai camera runtime."""

import collections
import hashlib
import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parents[1]
CONTRACT = json.loads((
    ROOT / 'fixtures' / 'ros1_dabai_runtime_contract.json'
).read_text(encoding='utf-8'))
START_SCRIPT = WORKSPACE / 'scripts' / 'start_dabai_camera.sh'
DOCS = WORKSPACE / 'docs'
ROS1_RUNBOOK = DOCS / 'PERCEPTION_V2_ROS1_NOETIC_FIELD_RUNBOOK.md'
LEGACY_RUNBOOK = DOCS / 'PERCEPTION_V2_FIELD_READINESS_RUNBOOK.md'
ROS2_SENSOR_README = (
    WORKSPACE / 'src' / 'limo_cleanup_dabai_sensor' / 'README.md')
INDEXER_SOURCE = (
    WORKSPACE / 'ros1_overlay_src' / 'limo_cleanup_ros1_perception' /
    'src' / 'limo_cleanup_ros1_perception' / 'rosbag1_rgbd_indexer.py')
EXPECTED_TOPIC_MANIFEST = (
    WORKSPACE / 'ros1_overlay_src' / 'limo_cleanup_ros1_perception' /
    'config' / 'dabai_ros1_raw_rgbd_six_topics_v1.json')


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _artifact(entry):
    path = WORKSPACE / entry['path']
    assert path.is_file()
    assert path.stat().st_size == entry['size_bytes']
    assert _sha256(path) == entry['sha256']
    return path


def _mapping_sha256(value):
    encoded = json.dumps(
        value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
        allow_nan=False).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def _calibration_sha256(decoded):
    keys = (
        'height', 'width', 'distortion_model', 'D', 'K', 'R', 'P',
        'binning_x', 'binning_y', 'roi')
    encoded = json.dumps(
        {key: decoded[key] for key in keys}, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def test_runtime_is_ros1_noetic_and_motion_is_never_authorized():
    assert CONTRACT['schema_version'] == 2
    assert CONTRACT['contract_id'] == (
        'limo-v2-ros1-noetic-dabai-runtime-v2')
    assert CONTRACT['runtime'] == {
        'ros_major': 1,
        'ros_distro': 'noetic',
        'on_robot_middleware': 'roscpp_tcpros',
        'ros2_field_runtime_allowed': False,
    }
    authorization = CONTRACT['authorization']
    assert authorization['camera_only_active'] is True
    assert authorization['read_only'] is True
    assert authorization['authorizes_motion'] is False
    assert authorization['publishes_control_messages'] is False
    assert authorization['may_stop_non_camera_nodes'] is False


def test_launch_and_four_stream_surface_are_exact():
    startup = CONTRACT['startup']
    assert startup['launch_sha256'] == (
        '75f9ada995ac961d0b4dddb7d86d591f57dc5392165663f4a905709a24231b2e')
    assert startup['node'] == '/camera/camera'
    assert startup['package'] == 'astra_camera'
    assert startup['executable'] == 'astra_camera_node'
    assert startup['includes'] == []
    expected = {
        ('rgb', '/camera/color/image_raw', 'sensor_msgs/Image'),
        ('raw_depth', '/camera/depth/image_raw', 'sensor_msgs/Image'),
        ('rgb_camera_info', '/camera/color/camera_info',
         'sensor_msgs/CameraInfo'),
        ('depth_camera_info', '/camera/depth/camera_info',
         'sensor_msgs/CameraInfo'),
    }
    streams = CONTRACT['streams']
    assert {(item['role'], item['topic'], item['type'])
            for item in streams} == expected
    assert {item['publisher'] for item in streams} == {'/camera/camera'}
    by_role = {item['role']: item for item in streams}
    assert by_role['depth_camera_info']['live_probe_frame_id'] == (
        'camera_depth_optical_frame')
    assert by_role['depth_camera_info']['diagnostic_bag_frame_ids'] == ['']
    assert by_role['rgb_camera_info']['diagnostic_bag_frame_ids'] == [
        'camera_color_optical_frame']
    assert len(CONTRACT['evidence_sources']) == 4
    for item in CONTRACT['evidence_sources']:
        _artifact(item)


def test_shared_tf_and_diagnostic_bag_can_never_be_formal_evidence():
    tf_runtime = CONTRACT['tf_runtime']
    assert tf_runtime['mixed_tf'] is True
    assert tf_runtime['camera_only_tf_pass'] is False
    live_publishers = set(tf_runtime['live_owner_probe']['tf_publishers'])
    assert '/limo_base_node' in live_publishers

    bag = CONTRACT['diagnostic_bag']
    bag_path = _artifact({
        'path': bag['local_path'],
        'size_bytes': bag['size_bytes'],
        'sha256': bag['sha256'],
    })
    assert bag_path.suffix == '.bag'
    manifest_path = _artifact(bag['manifest'])
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    formal_gate_path = _artifact(bag['formal_gate_history'])
    formal_gate = json.loads(formal_gate_path.read_text(encoding='utf-8'))

    assert manifest['schema_version'] == bag['manifest']['schema_version']
    for key in ('report_kind', 'inspection_scope', 'mode'):
        assert manifest[key] == bag['manifest'][key]
    expected_policy = {
        'formal_acceptance': False,
        'shared_graph': True,
        'mixed_tf': True,
        'not_in_four_scene_denominator': True,
        'delivery_ready': False,
        'diagnostic_completed': True,
        'inspection_passed': False,
        'read_only': True,
        'authorizes_motion': False,
        'publishes_ros_messages': False,
        'starts_ros_graph': False,
    }
    for key, expected_value in expected_policy.items():
        assert manifest[key] is expected_value
    assert manifest['capture_id'] == bag['capture_id']
    assert manifest['capture_window'] == bag['capture_window']
    assert manifest['scene'] == bag['scene']
    assert manifest['storage_identifier'] == bag['storage_identifier']
    assert manifest['source_capture'] == {
        'path': bag['remote_path'],
        'size_bytes': bag['size_bytes'],
        'sha256': bag['sha256'],
    }

    source_identity = manifest['indexer_source']
    expected_source = bag['indexer_source']
    assert Path(source_identity['path']).name == expected_source['path_suffix']
    assert source_identity['size_bytes'] == expected_source['size_bytes']
    assert source_identity['sha256'] == expected_source['sha256']
    # This diagnostic manifest remains immutably bound to the historical
    # indexer that decoded it.  A newer formal-capable indexer must not be
    # substituted into that provenance or promote the shared-TF artifact.
    assert (
        INDEXER_SOURCE.stat().st_size,
        _sha256(INDEXER_SOURCE),
    ) != (
        expected_source['size_bytes'],
        expected_source['sha256'],
    )
    manifest_identity = manifest['expected_topic_manifest']
    expected_identity = bag['expected_topic_manifest']
    for key in ('manifest_id', 'schema_version', 'size_bytes', 'sha256'):
        assert manifest_identity[key] == expected_identity[key]
    assert EXPECTED_TOPIC_MANIFEST.stat().st_size == expected_identity[
        'size_bytes']
    assert _sha256(EXPECTED_TOPIC_MANIFEST) == expected_identity['sha256']

    topics = manifest['topics']
    messages = manifest['messages']
    assert len(topics) == bag['connection_count'] == 8
    assert len(messages) == bag['message_count'] == 1248
    observed_topics = sorted({item['topic'] for item in topics})
    assert observed_topics == bag['observed_unique_topics']
    assert bag['missing_expected_topics'] == ['/tf_static']
    counts = collections.Counter(item['topic'] for item in messages)
    for topic, expected_count in bag['topic_message_counts'].items():
        assert counts[topic] == expected_count
    assert sum(bag['topic_message_counts'].values()) == bag['message_count']
    assert sum(item['topic'] == '/tf' for item in topics) == (
        bag['tf_connection_count'])
    assert all(
        item['connection_header_sha256'] == _mapping_sha256(
            item['connection_header'])
        for item in topics)
    assert all(
        item['connection_header_sha256'] == _mapping_sha256(
            item['connection_header'])
        for item in messages)

    metrics = bag['pairing_metrics']
    for source_key, contract_key in (
            ('rgb_candidate_count', 'rgb_candidate_count'),
            ('unique_header_pair_count', 'unique_header_pair_count'),
            ('formal_contract_valid_pair_count',
             'formal_contract_valid_pair_count'),
            ('accepted_bundle_count', 'diagnostic_accepted_bundle_count'),
            ('rejected_rgb_count', 'rejected_rgb_count'),
            ('total_stream_message_count', 'total_stream_message_count'),
            ('total_unpaired_message_count',
             'total_unpaired_message_count')):
        assert manifest[source_key] == metrics[contract_key]
    assert math.isclose(
        manifest['total_unpaired_rate'], metrics['total_unpaired_rate'],
        rel_tol=0.0, abs_tol=1e-15)
    assert manifest['unmatched_message_count_by_stream'] == metrics[
        'unmatched_message_count_by_stream']
    assert metrics['total_unpaired_message_count'] == sum(
        metrics['unmatched_message_count_by_stream'].values())
    assert math.isclose(
        metrics['total_unpaired_rate'],
        metrics['total_unpaired_message_count'] /
        metrics['total_stream_message_count'], rel_tol=0.0, abs_tol=1e-15)
    pairs = manifest['unique_header_pairs']
    assert len(pairs) == metrics['unique_header_pair_count']
    assert len({item['pair_sha256'] for item in pairs}) == len(pairs)
    assert sum(item['formal_valid'] is True for item in pairs) == 0
    assert all(set(item['formal_invalid_reasons']) == {
        'frame_id_invalid', 'image_camera_info_frame_mismatch',
        'stream_message_not_formal_valid'} for item in pairs)

    camera_info = bag['camera_info_evidence']
    connection_by_role = {item['role']: item for item in topics}
    for role in ('rgb_camera_info', 'depth_camera_info'):
        expected_info = camera_info[role]
        fresh = [
            item for item in messages
            if item['role'] == role and item['isolated'] is False]
        assert len(fresh) == expected_info['fresh_message_count']
        assert connection_by_role[role]['latching'] is (
            expected_info['connection_latching'])
        assert sorted({
            item['decoded']['header']['frame_id'] for item in fresh
        }) == expected_info['header_frame_ids']
        assert {item['decoded']['width'] for item in fresh} == {
            expected_info['width']}
        assert {item['decoded']['height'] for item in fresh} == {
            expected_info['height']}
        assert {item['decoded']['distortion_model'] for item in fresh} == {
            expected_info['distortion_model']}
        assert {_calibration_sha256(item['decoded']) for item in fresh} == {
            expected_info['calibration_sha256']}
        assert all(len(item['decoded']['K']) == 9 for item in fresh)
        assert all(len(item['decoded']['D']) == 5 for item in fresh)
        assert all(len(item['decoded']['R']) == 9 for item in fresh)
        assert all(len(item['decoded']['P']) == 12 for item in fresh)
    isolated = manifest['isolated_old_latched_camera_info']
    expected_old = camera_info['depth_camera_info'][
        'isolated_old_latched_count']
    assert manifest['isolated_old_latched_camera_info_count'] == expected_old
    assert len(isolated) == expected_old == 1
    assert isolated[0]['topic'] == '/camera/depth/camera_info'
    assert isolated[0]['reason'] == (
        'old_latched_camera_info_before_capture_window')
    old_message_ids = {item['message_id'] for item in isolated}
    paired_message_ids = {
        pair[role] for pair in pairs for role in (
            'rgb', 'raw_depth', 'rgb_camera_info', 'depth_camera_info')}
    assert not old_message_ids.intersection(paired_message_ids)

    tf_graph = manifest['tf_graph']
    expected_tf = bag['tf_evidence']
    assert tf_graph['camera_only'] is expected_tf['camera_only']
    assert tf_graph['mixed_tf'] is expected_tf['mixed_tf']
    assert tf_graph['base_chain_required'] is expected_tf[
        'base_chain_required']
    assert tf_graph['transform_count'] == expected_tf['transform_count']
    assert len(tf_graph['transforms']) == expected_tf['transform_count']
    assert len(tf_graph['edge_summary']) == expected_tf[
        'edge_summary_count']
    assert sum(item['transform_count'] for item in tf_graph['edge_summary']) == (
        expected_tf['transform_count'])
    def edge_key(item):
        return (
            item['connection_id'], item['topic'], item['callerid'],
            item['parent_frame_id'], item['child_frame_id'],
            item['transform_count'])
    assert {edge_key(item) for item in tf_graph['edge_summary']} == {
        edge_key(item) for item in expected_tf['edge_summary']}
    assert sorted({item['callerid'] for item in topics
                   if item['topic'] == '/tf'}) == expected_tf[
                       'bag_tf_callers']
    assert '/limo_base_node' not in expected_tf['bag_tf_callers']
    assert any(
        item['topic'] == '/tf'
        and item['callerid'] == '/base_link_to_laser_link'
        and item['parent_frame_id'] == '/base_link'
        and item['child_frame_id'] == '/laser_link'
        for item in tf_graph['transforms'])
    required_transform_fields = {
        'topic', 'connection_id', 'callerid', 'parent_frame_id',
        'child_frame_id', 'stamp_ns', 'serialized_sha256'}
    assert all(required_transform_fields.issubset(item)
               for item in tf_graph['transforms'])

    assert formal_gate['diagnostic_completed'] is False
    assert formal_gate['inspection_passed'] is False
    assert formal_gate['formal_acceptance'] is False
    assert formal_gate['delivery_ready'] is False
    assert formal_gate['failures'] == ['connection_latching_mismatch']
    assert formal_gate['source_capture'] == manifest['source_capture']
    assert formal_gate['indexer_source'] == manifest['indexer_source']
    assert bag['formal_gate_history']['not_full_field_evidence'] is True
    assert bag['formal_gate_history']['not_in_four_scene_denominator'] is True
    assert formal_gate['not_in_four_scene_denominator'] is False
    assert bag['formal_acceptance'] is False
    assert bag['shared_graph'] is True
    assert bag['mixed_tf'] is True
    assert bag['exact_six_topics_present'] is False
    assert bag['not_in_four_scene_denominator'] is True
    assert bag['delivery_ready'] is False
    assert bag['formal_tf_pass'] is False
    assert bag['formal_3d_pass'] is False
    assert bag['formal_scene_frame_contribution'] == {
        'background': 0,
        'bin_only': 0,
        'bottle_in_bin': 0,
        'bottle_outside': 0,
    }


def test_legacy_start_script_is_permanently_fail_closed():
    source = START_SCRIPT.read_text(encoding='utf-8')
    for required in (
            'is retired and never starts ROS',
            'PERCEPTION_V2_ROS1_NOETIC_FIELD_RUNBOOK.md',
            'ros1_camera_only_atomic_launcher.py',
            'EXECUTE_AUDITED_CAMERA_ONLY',
            '--actual-vendor-launch',
            'exit 64'):
        assert required in source
    for forbidden in (
            'source "$ros_setup"', 'source "$agilex_setup"',
            'exec roslaunch', 'roslaunch astra_camera', 'sha256sum',
            'move_base', 'cmd_vel', 'arm_controller', 'gripper_controller',
            '$@'):
        assert forbidden not in source


def test_docs_route_field_work_to_ros1_and_demote_ros2_assets():
    runbook = ROS1_RUNBOOK.read_text(encoding='utf-8')
    for required in (
            'authoritative on-robot V2 camera procedure',
            '# HISTORICAL/NON_AUTHORITATIVE/DO NOT RUN: '
            'roslaunch astra_camera dabai_u3.launch',
            'The only production camera-start entry is the host-owned atomic launcher',
            'python3 -I -S -B audit_tools/ros1_camera_only_atomic_launcher.py',
            '--mode EXECUTE_AUDITED_CAMERA_ONLY',
            'diagnostic-manifest-v3.json',
            '4683b682b908a2325232aa604a3b7e6367dd0404a84baf0013d159ab8da7e08f',
            '4b541369995076cbb588ec53854a8f22edec99d71a0a96629b5252f896046037',
            '86 unique Header-bound diagnostic pairs',
            'zero formal-contract-valid pairs',
            'one old latched depth CameraInfo',
            '5 of 349',
            '1.4327%',
            '1,043 transforms across nine edge summaries',
            'empty Header.frame_id',
            'formal_acceptance=false',
            'not_in_four_scene_denominator=true',
            'delivery_ready=false',
            'four-scene denominator remains zero'):
        assert required in runbook
    operational_direct = [
        line for line in runbook.splitlines()
        if (line.startswith('    ') or line.startswith('\t'))
        if 'roslaunch astra_camera dabai_u3.launch' in line
        and not line.strip().startswith(
            '# HISTORICAL/NON_AUTHORITATIVE/DO NOT RUN:')
    ]
    assert operational_direct == []
    legacy_prefix = LEGACY_RUNBOOK.read_text(encoding='utf-8')[:1200]
    assert 'robot field runtime is ROS1 Noetic' in legacy_prefix
    assert 'offline' in legacy_prefix
    assert 'migration/build archaeology' in legacy_prefix
    migration = ROS2_SENSOR_README.read_text(encoding='utf-8')[:700]
    assert 'ROS2 migration-only' in migration
    assert 'not an on-robot camera entry' in migration


if __name__ == '__main__':
    import inspect

    checks = [value for name, value in sorted(globals().items())
              if name.startswith('test_') and inspect.isfunction(value)]
    for check in checks:
        check()
    print('{} ROS1 DaBai runtime checks passed'.format(len(checks)))

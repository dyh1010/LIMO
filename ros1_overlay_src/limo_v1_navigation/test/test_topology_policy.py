from dataclasses import replace
from pathlib import Path
import sys
import unittest

PACKAGE_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / 'src'))

import limo_v1_navigation.topology_policy as TOPOLOGY  # noqa: E402
from limo_v1_navigation.topology_policy import (  # noqa: E402
    ExpectedTopology,
    TF_DYNAMIC,
    TF_STATIC_LATCHED,
    TF_STATIC_PERIODIC,
    TfEdgeObservation,
    TfEdgeRule,
    TfEdgeValidationError,
    validate_tf_edge_evidence,
    validate_topology,
)


class TopologyPolicyTest(unittest.TestCase):

    def _vendor_contract(self, rule):
        return TOPOLOGY._VerifiedVendorTfRules(
            rules=(rule,),
            evidence_json='{}',
            seal=TOPOLOGY._VENDOR_RULES_SEAL)

    def _laser_rule(self, behavior=TF_STATIC_LATCHED):
        if behavior == TF_STATIC_LATCHED:
            topic = '/tf_static'
        elif behavior == TF_STATIC_PERIODIC:
            topic = '/tf'
        else:
            raise AssertionError('unsupported test laser behavior')
        return TfEdgeRule(
            parent_frame='base_link',
            child_frame='laser_link',
            authority='/base_link_to_laser_link',
            topic=topic,
            behavior=behavior,
            provenance_verified=True,
        )

    def _tf_observation(
            self, message_id, parent, child, authority, topic,
            stamp, receipt, translation=(0.0, 0.0, 0.0),
            rotation=(0.0, 0.0, 0.0, 1.0), latching=False):
        return TfEdgeObservation(
            message_id=message_id,
            parent_frame=parent,
            child_frame=child,
            authority=authority,
            topic=topic,
            source_stamp=stamp,
            receipt_monotonic=receipt,
            translation=translation,
            rotation=rotation,
            latching=latching,
        )

    def _valid_tf_evidence(self, laser_rule=None):
        laser_rule = laser_rule or self._laser_rule()
        observations = [
            self._tf_observation(
                1, 'odom', 'base_link', '/limo_base_node',
                '/tf', 10.0, 20.0),
            self._tf_observation(
                2, 'odom', 'base_link', '/limo_base_node',
                '/tf', 11.0, 21.0),
            self._tf_observation(
                3, 'map', 'odom', '/amcl', '/tf', 10.1, 20.1),
            self._tf_observation(
                4, 'map', 'odom', '/amcl', '/tf', 11.1, 21.1),
        ]
        if laser_rule.behavior == TF_STATIC_LATCHED:
            observations.append(self._tf_observation(
                5, 'base_link', 'laser_link', laser_rule.authority,
                '/tf_static', 0.0, 20.2,
                translation=(0.105, 0.0, 0.08), latching=True))
        else:
            observations.extend((
                self._tf_observation(
                    5, 'base_link', 'laser_link', laser_rule.authority,
                    '/tf', 10.2, 20.2,
                    translation=(0.105, 0.0, 0.08)),
                self._tf_observation(
                    6, 'base_link', 'laser_link', laser_rule.authority,
                    '/tf', 11.2, 21.2,
                    translation=(0.105, 0.0, 0.08)),
            ))
        observations.extend((
            self._tf_observation(
                7, 'base_link', 'camera_link',
                '/base_link_to_camera_link', '/tf', 10.3, 20.3),
            self._tf_observation(
                8, 'base_link', 'imu_link',
                '/base_link_to_imu_link', '/tf', 10.4, 20.4),
        ))
        graph = {
            '/tf': {
                '/limo_base_node', '/amcl',
                '/base_link_to_camera_link', '/base_link_to_imu_link',
            },
            '/tf_static': set(),
        }
        if laser_rule.topic == '/tf':
            graph['/tf'].add(laser_rule.authority)
        else:
            graph['/tf_static'].add(laser_rule.authority)
        return observations, graph

    def _valid(self, mode='native'):
        expected = ExpectedTopology()
        publishers = {
            expected.scan_topic: [expected.scan_node],
            expected.odom_topic: [expected.odom_node],
        }
        subscribers = {}
        active_nodes = {
            expected.scan_node, expected.odom_node,
            expected.map_server_node, expected.amcl_node,
            expected.move_base_node}
        if mode == 'native':
            action_prefix = expected.private_action_prefix
            simple_goal_topic = expected.private_goal_topic
            action_client = expected.gateway_node
            status_consumers = [
                expected.gateway_node,
                expected.localization_manager_node,
            ]
            publishers.update({
                expected.nav_cmd_topic: [expected.move_base_node],
                expected.driver_cmd_topic: [expected.guard_node],
            })
            subscribers.update({
                expected.nav_cmd_topic: [expected.guard_node],
                expected.driver_cmd_topic: [expected.odom_node],
                expected.private_goal_topic: [expected.move_base_node],
            })
            active_nodes.update({
                expected.guard_node,
                expected.gateway_node,
                expected.localization_manager_node,
            })
        else:
            action_prefix = expected.public_action_prefix
            simple_goal_topic = expected.public_goal_topic
            action_client = expected.navigation_adapter_node
            status_consumers = [expected.navigation_adapter_node]
            publishers.update({
                expected.integrated_request_topic: [expected.move_base_node],
                expected.integrated_safe_topic: [expected.bridge_node],
                expected.integrated_driver_topic: [
                    expected.bridge_watchdog_node],
            })
            subscribers.update({
                expected.integrated_request_topic: [expected.bridge_node],
                expected.integrated_safe_topic: [
                    expected.bridge_watchdog_node],
                expected.integrated_driver_topic: [
                    expected.odom_node, expected.bridge_verifier_node],
                simple_goal_topic: [expected.move_base_node],
            })
            active_nodes.update({
                expected.bridge_node,
                expected.bridge_watchdog_node,
                expected.bridge_verifier_node,
                expected.navigation_adapter_node,
            })
        publishers.update({
            '{}/goal'.format(action_prefix): [action_client],
            '{}/cancel'.format(action_prefix): [action_client],
            '{}/status'.format(action_prefix): [
                expected.move_base_node],
            '{}/feedback'.format(action_prefix): [
                expected.move_base_node],
            '{}/result'.format(action_prefix): [
                expected.move_base_node],
        })
        subscribers.update({
            simple_goal_topic: [expected.move_base_node],
            '{}/goal'.format(action_prefix): [
                expected.move_base_node],
            '{}/cancel'.format(action_prefix): [
                expected.move_base_node],
            '{}/status'.format(action_prefix): status_consumers,
            '{}/feedback'.format(action_prefix): [action_client],
            '{}/result'.format(action_prefix): [action_client],
        })
        tf_publishers = {
            expected.odom_node,
            '/base_link_to_laser_link',
            '/base_link_to_imu_link',
        }
        return expected, publishers, subscribers, tf_publishers, active_nodes

    def test_exact_native_and_integrated_topologies_pass(self):
        for mode in ('native', 'integrated'):
            with self.subTest(mode=mode):
                _, publishers, subscribers, tf_publishers, nodes = self._valid(
                    mode)
                validate_topology(
                    publishers, subscribers, tf_publishers,
                    navigation=True, mode=mode, active_nodes=nodes)
        for behavior in (TF_STATIC_LATCHED, TF_STATIC_PERIODIC):
            with self.subTest(laser_behavior=behavior):
                vendor_rule = self._laser_rule(behavior)
                observations, graph = self._valid_tf_evidence(vendor_rule)
                result = validate_tf_edge_evidence(
                    observations,
                    stage='navigation',
                    vendor_rules=self._vendor_contract(vendor_rule),
                    current_tf_publishers_by_topic=graph,
                    now_monotonic=21.3,
                    dynamic_timeout_s=1.0,
                    now_source_time=11.3,
                    source_timeout_s=1.0,
                    source_future_tolerance_s=0.1,
                )
                self.assertEqual(result['status'], 'TF_EDGE_TOPOLOGY_PASS')
                self.assertEqual(result['stage'], 'navigation')
                self.assertEqual(
                    {item['child_frame'] for item in result['edges']},
                    {'base_link', 'odom', 'laser_link'})
                self.assertTrue(result['observed_edges'])
                observed = result['observed_edges'][0]
                for field in (
                        'authorities', 'topics', 'first_source_stamp',
                        'last_source_stamp', 'source_stamp_behavior',
                        'first_receipt_monotonic',
                        'last_receipt_monotonic', 'reference_translation',
                        'reference_rotation', 'geometry_stable',
                        'latching_values'):
                    self.assertIn(field, observed)
        vendor_rule = self._laser_rule()
        navigation_observations, navigation_graph = (
            self._valid_tf_evidence(vendor_rule))
        no_map_observations = [
            item for item in navigation_observations
            if (item.parent_frame, item.child_frame) != ('map', 'odom')]
        no_map_graph = {
            topic: set(owners) for topic, owners in navigation_graph.items()}
        no_map_graph['/tf'].remove('/amcl')
        mapping_observations = [
            replace(item, authority='/slam_gmapping')
            if (item.parent_frame, item.child_frame) == ('map', 'odom')
            else item
            for item in navigation_observations]
        mapping_graph = {
            topic: set(owners) for topic, owners in navigation_graph.items()}
        mapping_graph['/tf'].remove('/amcl')
        mapping_graph['/tf'].add('/slam_gmapping')
        for stage, evidence, graph_state in (
                ('scan', no_map_observations, no_map_graph),
                ('navigation_precore', no_map_observations, no_map_graph),
                ('mapping', mapping_observations, mapping_graph),
                ('localization', navigation_observations, navigation_graph)):
            with self.subTest(tf_stage=stage):
                result = validate_tf_edge_evidence(
                    evidence,
                    stage=stage,
                    vendor_rules=self._vendor_contract(vendor_rule),
                    current_tf_publishers_by_topic=graph_state,
                )
                self.assertEqual(result['stage'], stage)

    def test_rogue_or_missing_owner_blocks(self):
        expected, publishers, subscribers, tf_publishers, nodes = self._valid()
        mutations = (
            lambda p, s, t: p[expected.scan_topic].append('/scan_relay'),
            lambda p, s, t: p.pop(expected.odom_topic),
            lambda p, s, t: t.remove(expected.odom_node),
            lambda p, s, t: t.add(expected.forbidden_tf_node),
            lambda p, s, t: p.__setitem__(
                expected.public_cmd_topic, ['/teleop']),
            lambda p, s, t: s.__setitem__(
                expected.public_cmd_topic, ['/limo_base_node']),
            lambda p, s, t: p[expected.nav_cmd_topic].append('/teleop'),
            lambda p, s, t: s[expected.driver_cmd_topic].append(
                '/second_driver'),
            lambda p, s, t: p.__setitem__(
                expected.integrated_request_topic, [expected.move_base_node]),
            lambda p, s, t: p.__setitem__(
                expected.public_goal_topic, ['/rviz']),
            lambda p, s, t: p.__setitem__(
                '{}/goal'.format(expected.public_action_prefix), ['/rogue']),
            lambda p, s, t: p[
                '{}/goal'.format(expected.private_action_prefix)].append(
                    '/rogue_goal_client'),
            lambda p, s, t: s[
                '{}/cancel'.format(expected.private_action_prefix)].append(
                    '/rogue_action_server'),
            lambda p, s, t: p[
                '{}/status'.format(expected.private_action_prefix)].append(
                    '/rogue_action_server'),
            lambda p, s, t: s[
                '{}/status'.format(expected.private_action_prefix)].remove(
                    expected.localization_manager_node),
            lambda p, s, t: s[
                '{}/status'.format(expected.private_action_prefix)].append(
                    '/rogue_status_monitor'),
            lambda p, s, t: s[
                '{}/feedback'.format(expected.private_action_prefix)].append(
                    '/rogue_action_client'),
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                p = {key: list(value) for key, value in publishers.items()}
                s = {key: list(value) for key, value in subscribers.items()}
                t = set(tf_publishers)
                mutation(p, s, t)
                with self.assertRaises(RuntimeError):
                    validate_topology(
                        p, s, t, navigation=True, mode='native',
                        active_nodes=nodes)
        for missing in (expected.map_server_node, expected.amcl_node):
            with self.subTest(missing=missing):
                with self.assertRaises(RuntimeError):
                    validate_topology(
                        publishers, subscribers, tf_publishers,
                        navigation=True, mode='native',
                        active_nodes=nodes - {missing})
        for forbidden in (
                expected.gmapping_node, expected.cartographer_node,
                expected.forbidden_tf_node, '/amcl_legacy',
                '/map_server_legacy'):
            with self.subTest(forbidden=forbidden):
                with self.assertRaises(RuntimeError):
                    validate_topology(
                        publishers, subscribers, tf_publishers,
                        navigation=True, mode='native',
                        active_nodes=nodes | {forbidden})

        vendor_rule = self._laser_rule()
        observations, graph = self._valid_tf_evidence(vendor_rule)

        def replaced(indexes, **changes):
            candidate = list(observations)
            for index in indexes:
                candidate[index] = replace(candidate[index], **changes)
            return candidate

        multi_owner = list(observations)
        multi_owner.append(self._tf_observation(
            100, 'odom', 'base_link', '/robot_pose_ekf',
            '/tf', 11.2, 21.2))
        multi_parent = list(observations)
        multi_parent.append(self._tf_observation(
            103, 'map', 'base_link', '/limo_base_node',
            '/tf', 11.3, 21.3))
        cross_topic = list(observations)
        cross_topic.append(replace(
            observations[4], message_id=101, topic='/tf',
            source_stamp=11.2, receipt_monotonic=21.2,
            latching=False))
        conflicting_authority = list(observations)
        conflicting_authority.append(self._tf_observation(
            102, 'base_link', 'camera_link', '/limo_base_node',
            '/tf', 11.3, 21.3))
        missing_graph_capture = {
            topic: set(owners) for topic, owners in graph.items()}
        missing_graph_capture['/tf'].add('/silent_tf_owner')
        vendor_contract = self._vendor_contract(vendor_rule)

        edge_cases = (
            ('same_child_multiple_owners', multi_owner, vendor_contract, graph,
             'TF_CHILD_MULTIPLE_OWNERS'),
            ('same_child_multiple_parents', multi_parent, vendor_contract, graph,
             'TF_CHILD_MULTIPLE_PARENTS'),
            ('same_edge_cross_topics', cross_topic, vendor_contract, graph,
             'TF_EDGE_MULTIPLE_TOPICS'),
            ('wrong_parent', replaced((0, 1), parent_frame='map'),
             vendor_contract, graph, 'TF_AUTHORITY_CONFLICTING_EDGE'),
            ('wrong_child', replaced((4,), child_frame='laser_alias'),
             vendor_contract, graph, 'TF_AUTHORITY_CONFLICTING_EDGE'),
            ('alias_same_edge', replaced(
                (0, 1), authority='/limo_base_node_alias'),
             vendor_contract, graph, 'TF_EDGE_OWNER_MISMATCH'),
            ('same_node_conflicting_edge', conflicting_authority,
             vendor_contract, graph, 'TF_AUTHORITY_CONFLICTING_EDGE'),
            ('dynamic_on_static_channel', replaced(
                (0, 1), topic='/tf_static', latching=True),
             vendor_contract, graph, 'TF_EDGE_TOPIC_MISMATCH'),
            ('static_on_dynamic_channel', replaced(
                (4,), topic='/tf', latching=False),
             vendor_contract, graph, 'TF_EDGE_TOPIC_MISMATCH'),
            ('vendor_rules_missing', observations, None, graph,
             'TF_VENDOR_CONTRACT_UNVERIFIED'),
            ('vendor_rule_self_reported_true', observations, [vendor_rule],
             graph, 'TF_VENDOR_CONTRACT_UNVERIFIED'),
            ('vendor_rule_unverified', observations, [replace(
                vendor_rule, provenance_verified=False)], graph,
             'TF_VENDOR_CONTRACT_UNVERIFIED'),
            ('vendor_owner_unknown', replaced((4,), authority=''),
             vendor_contract, graph, 'TF_AUTHORITY_UNKNOWN'),
            ('graph_owner_not_attributed', observations, vendor_contract,
             missing_graph_capture, 'TF_GRAPH_CAPTURE_MISMATCH'),
            ('dynamic_not_repeated', [
                item for index, item in enumerate(observations)
                if index != 1], vendor_contract, graph,
             'TF_EDGE_BEHAVIOR_MISMATCH'),
            ('latched_flag_missing', replaced((4,), latching=False),
             vendor_contract, graph, 'TF_EDGE_BEHAVIOR_MISMATCH'),
        )
        for name, evidence, vendor, graph_state, code in edge_cases:
            with self.subTest(tf_edge_case=name):
                with self.assertRaises(TfEdgeValidationError) as raised:
                    validate_tf_edge_evidence(
                        evidence,
                        stage='navigation',
                        vendor_rules=vendor,
                        current_tf_publishers_by_topic=graph_state,
                    )
                self.assertEqual(raised.exception.code, code)

        periodic_rule = self._laser_rule(TF_STATIC_PERIODIC)
        periodic, periodic_graph = self._valid_tf_evidence(periodic_rule)
        periodic[5] = replace(
            periodic[5], translation=(0.205, 0.0, 0.08))
        with self.subTest(tf_edge_case='legacy_static_geometry_changes'):
            with self.assertRaises(TfEdgeValidationError) as raised:
                validate_tf_edge_evidence(
                    periodic,
                    stage='navigation',
                    vendor_rules=self._vendor_contract(periodic_rule),
                    current_tf_publishers_by_topic=periodic_graph,
                )
            self.assertEqual(
                raised.exception.code, 'TF_EDGE_BEHAVIOR_MISMATCH')

        source_time_cases = (
            ('stale_source', 12.1, 1.0, 0.1),
            ('future_source', 10.8, 1.0, 0.1),
        )
        for name, source_now, source_timeout, future_tolerance in (
                source_time_cases):
            with self.subTest(tf_edge_case=name):
                with self.assertRaises(TfEdgeValidationError) as raised:
                    validate_tf_edge_evidence(
                        observations,
                        stage='navigation',
                        vendor_rules=vendor_contract,
                        current_tf_publishers_by_topic=graph,
                        now_source_time=source_now,
                        source_timeout_s=source_timeout,
                        source_future_tolerance_s=future_tolerance,
                    )
                self.assertEqual(
                    raised.exception.code, 'TF_EDGE_SOURCE_TIME_INVALID')

        regressing = replaced((1,), source_stamp=9.0)
        with self.subTest(tf_edge_case='regressing_source_stamp'):
            with self.assertRaises(TfEdgeValidationError) as raised:
                validate_tf_edge_evidence(
                    regressing,
                    stage='navigation',
                    vendor_rules=vendor_contract,
                    current_tf_publishers_by_topic=graph,
                )
            self.assertEqual(
                raised.exception.code, 'TF_EDGE_BEHAVIOR_MISMATCH')

        nonfinite = replaced((1,), source_stamp=float('nan'))
        with self.subTest(tf_edge_case='nonfinite_source_stamp'):
            with self.assertRaises(TfEdgeValidationError) as raised:
                validate_tf_edge_evidence(
                    nonfinite,
                    stage='navigation',
                    vendor_rules=vendor_contract,
                    current_tf_publishers_by_topic=graph,
                )
            self.assertEqual(raised.exception.code, 'TF_OBSERVATION_INVALID')

    def test_native_action_owner_is_only_v1_gateway(self):
        expected, publishers, subscribers, tf_publishers, nodes = self._valid(
            'native')
        action_prefix = expected.private_action_prefix
        cases = []

        for owner in (
                expected.navigation_adapter_node,
                '/rogue_action_client'):
            p = {key: list(value) for key, value in publishers.items()}
            p['{}/goal'.format(action_prefix)] = [owner]
            cases.append((p, subscribers, nodes))

        p = {key: list(value) for key, value in publishers.items()}
        p['{}/goal'.format(action_prefix)].append(
            expected.navigation_adapter_node)
        cases.append((p, subscribers, nodes | {
            expected.navigation_adapter_node}))

        p = {key: list(value) for key, value in publishers.items()}
        p.pop('{}/goal'.format(action_prefix))
        cases.append((p, subscribers, nodes))

        p = {key: list(value) for key, value in publishers.items()}
        s = {key: list(value) for key, value in subscribers.items()}
        p['{}/goal'.format(expected.public_action_prefix)] = [
            expected.navigation_adapter_node]
        s['{}/goal'.format(expected.public_action_prefix)] = [
            expected.move_base_node]
        cases.append((p, s, nodes | {expected.navigation_adapter_node}))

        cases.append((publishers, subscribers, nodes | {
            expected.navigation_adapter_node}))

        for publishers_case, subscribers_case, nodes_case in cases:
            with self.subTest(
                    publishers=publishers_case, nodes=nodes_case):
                with self.assertRaises(RuntimeError):
                    validate_topology(
                        publishers_case, subscribers_case, tf_publishers,
                        navigation=True, mode='native',
                        active_nodes=nodes_case)

    def test_integrated_action_owner_is_only_bridge_adapter(self):
        expected, publishers, subscribers, tf_publishers, nodes = self._valid(
            'integrated')
        action_prefix = expected.public_action_prefix
        cases = []

        for owner in (expected.gateway_node, '/rogue_action_client'):
            p = {key: list(value) for key, value in publishers.items()}
            p['{}/goal'.format(action_prefix)] = [owner]
            cases.append((p, subscribers, nodes))

        p = {key: list(value) for key, value in publishers.items()}
        p['{}/goal'.format(action_prefix)].append(expected.gateway_node)
        cases.append((p, subscribers, nodes | {expected.gateway_node}))

        p = {key: list(value) for key, value in publishers.items()}
        p.pop('{}/goal'.format(action_prefix))
        cases.append((p, subscribers, nodes))

        p = {key: list(value) for key, value in publishers.items()}
        s = {key: list(value) for key, value in subscribers.items()}
        p['{}/goal'.format(expected.private_action_prefix)] = [
            expected.gateway_node]
        s['{}/goal'.format(expected.private_action_prefix)] = [
            expected.move_base_node]
        cases.append((p, s, nodes | {expected.gateway_node}))

        cases.append((publishers, subscribers, nodes | {
            expected.gateway_node}))

        for publishers_case, subscribers_case, nodes_case in cases:
            with self.subTest(
                    publishers=publishers_case, nodes=nodes_case):
                with self.assertRaises(RuntimeError):
                    validate_topology(
                        publishers_case, subscribers_case, tf_publishers,
                        navigation=True, mode='integrated',
                        active_nodes=nodes_case)

    def test_mode_specific_stop_ready_and_guard_nodes_remain_mandatory(self):
        expected = ExpectedTopology()
        for mode, required in (
                ('native', (
                    expected.guard_node,
                    expected.gateway_node,
                    expected.localization_manager_node,
                )),
                ('integrated', (
                    expected.bridge_node,
                    expected.bridge_watchdog_node,
                    expected.bridge_verifier_node,
                    expected.navigation_adapter_node,
                ))):
            _, publishers, subscribers, tf_publishers, nodes = self._valid(
                mode)
            for missing in required:
                with self.subTest(mode=mode, missing=missing):
                    with self.assertRaises(RuntimeError):
                        validate_topology(
                            publishers, subscribers, tf_publishers,
                            navigation=True, mode=mode,
                            active_nodes=nodes - {missing})

    def test_every_action_endpoint_has_exact_mode_specific_ownership(self):
        expected = ExpectedTopology()
        for mode in ('native', 'integrated'):
            _, publishers, subscribers, tf_publishers, nodes = self._valid(
                mode)
            if mode == 'native':
                prefix = expected.private_action_prefix
                simple_goal = expected.private_goal_topic
                client = expected.gateway_node
                status_consumers = [
                    expected.gateway_node,
                    expected.localization_manager_node,
                ]
            else:
                prefix = expected.public_action_prefix
                simple_goal = expected.public_goal_topic
                client = expected.navigation_adapter_node
                status_consumers = [expected.navigation_adapter_node]
            owners = {
                'goal': ([client], [expected.move_base_node]),
                'cancel': ([client], [expected.move_base_node]),
                'status': ([expected.move_base_node], status_consumers),
                'feedback': ([expected.move_base_node], [client]),
                'result': ([expected.move_base_node], [client]),
            }
            for suffix, (expected_publishers, expected_subscribers) in (
                    owners.items()):
                topic = '{}/{}'.format(prefix, suffix)
                for mapping_name, accepted in (
                        ('publishers', expected_publishers),
                        ('subscribers', expected_subscribers)):
                    for mutation_name, replacement in (
                            ('missing', []),
                            ('wrong', ['/wrong_action_owner']),
                            ('double', accepted + ['/wrong_action_owner'])):
                        with self.subTest(
                                mode=mode, topic=topic,
                                mapping=mapping_name,
                                mutation=mutation_name):
                            p = {
                                key: list(value)
                                for key, value in publishers.items()}
                            s = {
                                key: list(value)
                                for key, value in subscribers.items()}
                            target = p if mapping_name == 'publishers' else s
                            target[topic] = replacement
                            with self.assertRaises(RuntimeError):
                                validate_topology(
                                    p, s, tf_publishers,
                                    navigation=True, mode=mode,
                                    active_nodes=nodes)

            for mapping_name, replacement in (
                    ('publishers', ['/wrong_simple_goal_owner']),
                    ('subscribers', []),
                    ('subscribers', ['/wrong_simple_goal_owner']),
                    ('subscribers', [
                        expected.move_base_node,
                        '/wrong_simple_goal_owner',
                    ])):
                with self.subTest(
                        mode=mode, topic=simple_goal,
                        mapping=mapping_name,
                        replacement=replacement):
                    p = {
                        key: list(value)
                        for key, value in publishers.items()}
                    s = {
                        key: list(value)
                        for key, value in subscribers.items()}
                    target = p if mapping_name == 'publishers' else s
                    target[simple_goal] = replacement
                    with self.assertRaises(RuntimeError):
                        validate_topology(
                            p, s, tf_publishers,
                            navigation=True, mode=mode,
                            active_nodes=nodes)

    def test_precore_requires_base_sensors_and_forbids_navigation_nodes(self):
        expected, publishers, subscribers, tf_publishers, _nodes = self._valid()
        publishers.pop(expected.nav_cmd_topic)
        publishers.pop(expected.driver_cmd_topic)
        subscribers.pop(expected.nav_cmd_topic)
        subscribers.pop(expected.driver_cmd_topic)
        subscribers.pop(expected.private_goal_topic)
        for suffix in ('goal', 'cancel', 'status', 'feedback', 'result'):
            publishers.pop('{}/{}'.format(
                expected.private_action_prefix, suffix))
            subscribers.pop('{}/{}'.format(
                expected.private_action_prefix, suffix))
        validate_topology(
            publishers, subscribers, tf_publishers,
            navigation=False, mode='integrated', phase='precore')
        for forbidden in (
                expected.map_server_node, expected.amcl_node,
                expected.move_base_node,
                expected.guard_node, '/cleanup_ros1_navigation_adapter'):
            with self.subTest(forbidden=forbidden):
                candidate = {
                    key: list(value) for key, value in publishers.items()}
                candidate['/test_precore_forbidden'] = [forbidden]
                with self.assertRaises(RuntimeError):
                    validate_topology(
                        candidate, subscribers, tf_publishers,
                        navigation=False, mode='integrated', phase='precore')
        vendor_rule = self._laser_rule()
        observations, _graph = self._valid_tf_evidence(vendor_rule)
        with self.subTest(tf_edge_case='precore_map_to_odom_forbidden'):
            with self.assertRaises(TfEdgeValidationError) as raised:
                validate_tf_edge_evidence(
                    observations,
                    stage='navigation_precore',
                    vendor_rules=self._vendor_contract(vendor_rule),
                )
            self.assertEqual(
                raised.exception.code, 'TF_EDGE_FORBIDDEN_PRESENT')

    def test_double_owners_and_speed_loops_block_integrated_mode(self):
        expected, publishers, subscribers, tf_publishers, nodes = self._valid(
            'integrated')

        cases = []
        p = {key: list(value) for key, value in publishers.items()}
        s = {key: list(value) for key, value in subscribers.items()}
        p[expected.integrated_driver_topic].append(expected.guard_node)
        cases.append((p, s, set(nodes)))

        p = {key: list(value) for key, value in publishers.items()}
        s = {key: list(value) for key, value in subscribers.items()}
        p[expected.nav_cmd_topic] = [expected.move_base_node]
        s[expected.nav_cmd_topic] = [expected.guard_node]
        cases.append((p, s, set(nodes) | {expected.guard_node}))

        p = {key: list(value) for key, value in publishers.items()}
        s = {key: list(value) for key, value in subscribers.items()}
        s[expected.integrated_request_topic].append(
            expected.bridge_watchdog_node)
        cases.append((p, s, set(nodes)))

        cases.append((
            {key: list(value) for key, value in publishers.items()},
            {key: list(value) for key, value in subscribers.items()},
            set(nodes) | {'/move_base_2'}))

        for forbidden in (
                '/amcl_2', '/map_server_2', expected.gmapping_node,
                expected.cartographer_node, expected.forbidden_tf_node):
            cases.append((
                {key: list(value) for key, value in publishers.items()},
                {key: list(value) for key, value in subscribers.items()},
                set(nodes) | {forbidden}))

        for publishers_case, subscribers_case, nodes_case in cases:
            with self.subTest(
                    publishers=publishers_case,
                    subscribers=subscribers_case,
                    nodes=nodes_case):
                with self.assertRaises(RuntimeError):
                    validate_topology(
                        publishers_case, subscribers_case, tf_publishers,
                        navigation=True, mode='integrated',
                        active_nodes=nodes_case)


if __name__ == '__main__':
    unittest.main()

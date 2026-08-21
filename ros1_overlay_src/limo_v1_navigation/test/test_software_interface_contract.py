import json
from pathlib import Path
import re
import unittest


PACKAGE_ROOT = Path(__file__).parents[1]
MANIFEST = PACKAGE_ROOT / 'config' / 'v1_software_interface.json'
SCHEMA = PACKAGE_ROOT / 'config' / 'v1_software_interface.schema.json'
FIXTURE = (
    PACKAGE_ROOT / 'docs' / 'examples'
    / 'v1_read_only_status_fixture.json')
TABLE = PACKAGE_ROOT / 'docs' / 'V1_SOFTWARE_INTERFACE_TABLE.md'


def _matches_json_type(value, expected):
    if expected == 'object':
        return isinstance(value, dict)
    if expected == 'array':
        return isinstance(value, list)
    if expected == 'string':
        return isinstance(value, str)
    if expected == 'boolean':
        return isinstance(value, bool)
    if expected == 'number':
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == 'null':
        return value is None
    raise AssertionError('unsupported JSON Schema type: {}'.format(expected))


def _resolve_local_ref(root_schema, reference):
    if not reference.startswith('#/'):
        raise AssertionError('only local JSON Schema refs are supported')
    value = root_schema
    for token in reference[2:].split('/'):
        token = token.replace('~1', '/').replace('~0', '~')
        value = value[token]
    return value


def _validate_schema(instance, schema, root_schema, path='$'):
    if '$ref' in schema:
        _validate_schema(
            instance, _resolve_local_ref(root_schema, schema['$ref']),
            root_schema, path)
    if 'const' in schema and instance != schema['const']:
        raise AssertionError('{} does not match const'.format(path))
    if 'enum' in schema and instance not in schema['enum']:
        raise AssertionError('{} is not in enum'.format(path))
    if 'anyOf' in schema:
        matches = 0
        for choice in schema['anyOf']:
            try:
                _validate_schema(instance, choice, root_schema, path)
            except AssertionError:
                continue
            matches += 1
        if matches == 0:
            raise AssertionError('{} does not match anyOf'.format(path))
    expected_type = schema.get('type')
    if expected_type is not None and not _matches_json_type(
            instance, expected_type):
        raise AssertionError(
            '{} is not JSON type {}'.format(path, expected_type))
    if isinstance(instance, dict):
        required = set(schema.get('required', ()))
        missing = required - set(instance)
        if missing:
            raise AssertionError(
                '{} is missing {}'.format(path, sorted(missing)))
        properties = schema.get('properties', {})
        if schema.get('additionalProperties') is False:
            extra = set(instance) - set(properties)
            if extra:
                raise AssertionError(
                    '{} has additional properties {}'.format(
                        path, sorted(extra)))
        for key, value in instance.items():
            if key in properties:
                _validate_schema(
                    value, properties[key], root_schema,
                    '{}.{}'.format(path, key))
    if isinstance(instance, list):
        if len(instance) < schema.get('minItems', 0):
            raise AssertionError('{} has too few items'.format(path))
        if schema.get('uniqueItems'):
            canonical = [
                json.dumps(value, sort_keys=True, separators=(',', ':'))
                for value in instance]
            if len(canonical) != len(set(canonical)):
                raise AssertionError('{} has duplicate items'.format(path))
        item_schema = schema.get('items')
        if item_schema is not None:
            for index, value in enumerate(instance):
                _validate_schema(
                    value, item_schema, root_schema,
                    '{}[{}]'.format(path, index))
    if isinstance(instance, str):
        if len(instance) < schema.get('minLength', 0):
            raise AssertionError('{} is too short'.format(path))
        if 'pattern' in schema and re.search(
                schema['pattern'], instance) is None:
            raise AssertionError('{} does not match pattern'.format(path))
    if (
            isinstance(instance, (int, float))
            and not isinstance(instance, bool)
            and 'exclusiveMinimum' in schema
            and instance <= schema['exclusiveMinimum']):
        raise AssertionError('{} is below exclusiveMinimum'.format(path))


class SoftwareInterfaceContractTest(unittest.TestCase):

    def setUp(self):
        self.manifest = json.loads(MANIFEST.read_text(encoding='utf-8'))
        self.schema = json.loads(SCHEMA.read_text(encoding='utf-8'))
        self.fixture = json.loads(FIXTURE.read_text(encoding='utf-8'))
        self.read_interfaces = {
            item['id']: item
            for item in self.manifest['read_only_interfaces']}

    def test_manifest_is_frozen_additive_only_and_defaults_fail_closed(self):
        self.assertEqual(
            self.manifest['schema'], 'limo_v1_software_interface/v1')
        self.assertTrue(self.manifest['frozen'])
        self.assertEqual(self.manifest['compatibility'], 'additive_only')
        self.assertTrue(self.manifest['modes']['mutually_exclusive'])
        self.assertEqual(self.manifest['defaults'], {
            'integrated': {
                'adapter_enabled': False,
                'navigation_ready': False,
            },
            'native': {
                'forwarding_allowed': False,
                'gateway_enabled': False,
                'navigation_enabled': False,
                'nonzero_output_allowed': False,
                'stop_latched': True,
            },
        })

    def test_machine_readable_schema_locks_version_and_fail_closed_fields(self):
        self.assertEqual(
            self.schema['$schema'],
            'https://json-schema.org/draft/2020-12/schema')
        self.assertEqual(
            self.schema['properties']['schema']['const'],
            'limo_v1_software_interface/v1')
        self.assertEqual(
            self.schema['properties']['frozen']['const'], True)
        self.assertEqual(
            self.schema['properties']['compatibility']['const'],
            'additive_only')
        required = set(self.schema['required'])
        self.assertEqual(required, {
            'schema', 'frozen', 'compatibility', 'modes', 'defaults',
            'freshness_policy', 'read_only_interfaces',
            'controlled_interfaces', 'mock_fixture',
        })
        self.assertEqual(self.manifest['freshness_policy'], {
            'basis': 'consumer_monotonic_receipt',
            'error_records_are_not_health_heartbeats': True,
            'fresh_if': '0 <= receipt_age_s < freshness_timeout_s',
            'latched_heartbeat_requires_followup_sample': True,
            'missing_heartbeat_fail_closed': True,
            'stale_at_or_above_timeout': True,
        })
        controlled = self.schema['$defs']['controlledInterface']
        self.assertFalse(
            controlled['properties']['default_authorized']['const'])
        read_only = self.schema['$defs']['readOnlyInterface']
        self.assertEqual(
            read_only['properties']['access']['const'], 'subscribe_only')
        self.assertFalse(
            read_only['properties']['motion_capable']['const'])

    def test_manifest_validates_against_machine_readable_schema(self):
        _validate_schema(self.manifest, self.schema, self.schema)

    def test_read_only_interface_names_types_owners_and_payloads_are_exact(self):
        expected = {
            'localization_ready': (
                '/v1/localization/ready', 'std_msgs/Bool',
                '/v1_localization_manager', True, 'boolean'),
            'localization_status': (
                '/v1/localization/status', 'std_msgs/String',
                '/v1_localization_manager', True,
                'limo_v1_localization_status/v1'),
            'localization_diagnostics': (
                '/v1/localization/diagnostics', 'std_msgs/String',
                '/v1_localization_manager', True,
                'limo_v1_localization_status/v1'),
            'navigation_status': (
                '/v1/navigation/status', 'std_msgs/String',
                '/v1_navigation_gateway', True,
                'limo_v1_navigation_status/v1'),
            'navigation_error': (
                '/v1/navigation/error', 'std_msgs/String',
                '/v1_navigation_gateway', True,
                'limo_v1_navigation_error/v1'),
            'native_stop_latched': (
                '/v1/cmd_guard/stop_latched', 'std_msgs/Bool',
                '/v1_cmd_guard', True, 'boolean'),
            'integrated_navigation_status': (
                '/cleanup/navigation/bridge_status', 'std_msgs/String',
                '/cleanup_ros1_navigation_adapter', False,
                'cleanup_navigation_bridge/v3'),
        }
        self.assertEqual(set(self.read_interfaces), set(expected))
        for interface_id, values in expected.items():
            with self.subTest(interface_id=interface_id):
                item = self.read_interfaces[interface_id]
                self.assertEqual(
                    (item['name'], item['ros_type'], item['publisher_owner'],
                     item['latched'], item['payload_contract']), values)
                self.assertEqual(item['access'], 'subscribe_only')
                self.assertFalse(item['motion_capable'])

    def test_read_only_freshness_contract_matches_runtime_heartbeats(self):
        expected = {
            'localization_ready': (0.1, 0.5, 'heartbeat', False),
            'localization_status': (0.1, 0.5, 'heartbeat', False),
            'localization_diagnostics': (0.1, 0.5, 'heartbeat', False),
            'navigation_status': (0.1, 0.5, 'heartbeat', False),
            'navigation_error': (
                None, None, 'latched_event_record', False),
            'native_stop_latched': (0.1, 0.5, 'heartbeat', False),
            'integrated_navigation_status': (
                0.05, 0.25, 'heartbeat', True),
        }
        for interface_id, contract in expected.items():
            with self.subTest(interface_id=interface_id):
                item = self.read_interfaces[interface_id]
                self.assertEqual((
                    item['nominal_publish_period_s'],
                    item['freshness_timeout_s'],
                    item['freshness_semantics'],
                    item['first_sample_establishes_liveness'],
                ), contract)
                if item['latched'] and contract[2] == 'heartbeat':
                    self.assertFalse(
                        item['first_sample_establishes_liveness'])

    def test_command_interfaces_have_no_default_authority(self):
        commands = self.manifest['controlled_interfaces']
        self.assertTrue(commands)
        self.assertTrue(all(item['default_authorized'] is False
                            for item in commands))
        self.assertEqual({item['id'] for item in commands}, {
            'native_navigation_request',
            'native_navigation_cancel_topic',
            'native_gateway_arm',
            'native_gateway_cancel_service',
            'integrated_navigation_command',
            'initial_pose_authorization',
            'initial_pose_input',
        })
        integrated = next(
            item for item in commands
            if item['id'] == 'integrated_navigation_command')
        self.assertTrue(integrated['internal_only'])
        self.assertFalse(integrated['public_consumer'])

    def test_private_action_owners_are_mode_exact_and_mutually_exclusive(self):
        modes = self.manifest['modes']
        native = modes['native']
        integrated = modes['integrated']
        self.assertEqual(native['action_prefix'], '/v1/private_move_base')
        self.assertEqual(
            native['action_client_owner'], '/v1_navigation_gateway')
        self.assertEqual(
            native['forbidden_action_client_owner'],
            integrated['action_client_owner'])
        self.assertEqual(integrated['action_prefix'], '/move_base')
        self.assertEqual(
            integrated['action_client_owner'],
            '/cleanup_ros1_navigation_adapter')
        self.assertEqual(
            integrated['forbidden_action_client_owner'],
            native['action_client_owner'])
        self.assertEqual(
            integrated['visibility'], 'runner_private_internal')

    def test_fixture_covers_read_only_native_and_integrated_state_matrix(self):
        self.assertEqual(
            self.fixture['interface_schema'], self.manifest['schema'])
        self.assertTrue(self.fixture['mock_only'])
        self.assertFalse(self.fixture['real_machine_evidence'])
        self.assertFalse(self.fixture['motion_commanded'])
        scenarios = {
            item['name']: item for item in self.fixture['scenarios']}
        self.assertEqual(set(scenarios), {
            'native_ready_true',
            'native_ready_false',
            'native_ready_stale',
            'native_stop_latched',
            'native_request_accepted_status',
            'native_request_rejected_error',
            'native_cancel_observed',
            'integrated_ready',
            'integrated_unavailable',
            'integrated_request_accepted_status',
            'integrated_request_rejected_status',
            'integrated_cancel_observed',
        })
        self.assertEqual(
            scenarios['native_ready_true']['observations'][0]['data'], True)
        self.assertEqual(
            scenarios['native_ready_false']['observations'][0]['data'], False)
        self.assertEqual(
            scenarios['native_ready_stale']['observations'][0]['json'][
                'reason'], 'localization_ready_stale')
        stale = scenarios['native_ready_stale']['observations'][0]['json']
        self.assertTrue(stale['localization_ready'])
        self.assertTrue(stale['gateway_enabled'])
        self.assertTrue(stale['allow_goal_forwarding'])
        self.assertEqual(stale['state'], 'BLOCKED')
        self.assertTrue(stale['cancel_required'])
        self.assertEqual(
            scenarios['native_stop_latched']['observations'][0]['data'], True)
        self.assertEqual(
            scenarios['native_request_accepted_status']['observations'][0][
                'json']['state'], 'ACTIVE')
        self.assertEqual(
            scenarios['native_request_rejected_error']['observations'][0][
                'interface_id'], 'navigation_error')
        rejected = scenarios['native_request_rejected_error'][
            'observations'][1]['json']
        self.assertEqual(rejected['state'], 'BLOCKED')
        self.assertEqual(rejected['reason'], 'startup_latched')
        self.assertEqual(rejected['event'], 'goal_rejected')
        self.assertFalse(rejected['gateway_enabled'])
        self.assertFalse(rejected['allow_goal_forwarding'])
        self.assertEqual(
            scenarios['native_cancel_observed']['observations'][0]['json'][
                'state'], 'CANCELED')
        canceled = scenarios['native_cancel_observed'][
            'observations'][0]['json']
        self.assertTrue(canceled['gateway_enabled'])
        self.assertTrue(canceled['allow_goal_forwarding'])
        self.assertTrue(canceled['cancel_required'])
        self.assertEqual(
            scenarios['integrated_request_accepted_status'][
                'observations'][0]['json']['state'], 'active')
        self.assertEqual(
            scenarios['integrated_request_rejected_status'][
                'observations'][0]['json']['state'], 'rejected')
        self.assertEqual(
            scenarios['integrated_cancel_observed']['observations'][0][
                'json']['state'], 'stopped')

    def test_every_fixture_observation_is_schema_valid_read_only_projection(self):
        command_ids = {
            item['id'] for item in self.manifest['controlled_interfaces']}
        for scenario in self.fixture['scenarios']:
            self.assertIn(scenario['mode'], ('native', 'integrated'))
            for observation in scenario['observations']:
                with self.subTest(
                        scenario=scenario['name'],
                        interface=observation['interface_id']):
                    interface_id = observation['interface_id']
                    self.assertNotIn(interface_id, command_ids)
                    interface = self.read_interfaces[interface_id]
                    self.assertIn(scenario['mode'], interface['modes'])
                    self.assertEqual(
                        observation['ros_type'], interface['ros_type'])
                    if interface['payload_contract'] == 'boolean':
                        self.assertIs(type(observation['data']), bool)
                        self.assertNotIn('json', observation)
                    else:
                        payload = observation['json']
                        self.assertTrue(
                            set(interface['required_payload_fields'])
                            <= set(payload))
                        discriminator = payload.get(
                            'schema', payload.get('protocol'))
                        self.assertEqual(
                            discriminator, interface['payload_contract'])

    def test_fixture_contains_no_motion_command_transport(self):
        text = FIXTURE.read_text(encoding='utf-8').lower()
        for forbidden in (
                'cmd_vel', 'twist', 'posestamped', 'service_call',
                'action_client', 'send_goal', 'target_pose'):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, text)
        for scenario in self.fixture['scenarios']:
            for observation in scenario['observations']:
                self.assertNotIn('name', observation)
                self.assertNotIn('operation', observation)

    def test_native_fixture_states_and_cross_fields_are_runtime_reachable(self):
        scenarios = {
            item['name']: item for item in self.fixture['scenarios']}
        allowed_states = {
            'BLOCKED', 'IDLE', 'ACTIVE', 'SUCCEEDED', 'CANCELED', 'FAILED'}
        for scenario in self.fixture['scenarios']:
            if scenario['mode'] != 'native':
                continue
            for observation in scenario['observations']:
                if observation['interface_id'] != 'navigation_status':
                    continue
                status = observation['json']
                self.assertIn(status['state'], allowed_states)
                if status['state'] == 'ACTIVE':
                    self.assertTrue(status['armed'])
                    self.assertFalse(status['cancel_required'])
                    self.assertTrue(status['gateway_enabled'])
                    self.assertTrue(status['allow_goal_forwarding'])
                if status['state'] == 'CANCELED':
                    self.assertFalse(status['armed'])
                    self.assertTrue(status['cancel_required'])
                    self.assertTrue(status['gateway_enabled'])
                    self.assertTrue(status['allow_goal_forwarding'])
        stale = scenarios['native_ready_stale']['observations'][0]['json']
        self.assertTrue(stale['localization_ready'])
        self.assertEqual(stale['reason'], 'localization_ready_stale')
        rejected = scenarios['native_request_rejected_error'][
            'observations'][1]['json']
        self.assertEqual(rejected['event'], 'goal_rejected')
        self.assertEqual(rejected['state'], 'BLOCKED')

    def test_table_warns_about_accuracy_motion_and_integrated_privacy(self):
        source = TABLE.read_text(encoding='utf-8')
        self.assertIn('not proof of absolute localization accuracy', source)
        self.assertIn('not a physical emergency stop', source)
        self.assertIn('It is not a public consumer entry', source)
        self.assertIn('wrong, double,\nor missing ownership is fail-closed', source)
        self.assertIn('cannot establish', source)
        self.assertIn('consumer\'s monotonic receipt time', source)
        self.assertIn('equality is stale', source)
        self.assertIn('only a snapshot', source)
        self.assertIn('not a heartbeat', source)


if __name__ == '__main__':
    unittest.main()

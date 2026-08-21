import importlib.util
import json
from pathlib import Path
import sys
import types

import pytest


PACKAGE_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / 'src'))
SCRIPT = PACKAGE_ROOT / 'scripts' / 'verify_v1_map_binding_runtime.py'


def _load_module():
    rospy = types.ModuleType('rospy')
    sys.modules.setdefault('rospy', rospy)
    spec = importlib.util.spec_from_file_location('runtime_monitor', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MONITOR = _load_module()


def test_snapshot_manifest_accepts_ros_dict_and_strict_json_string():
    payload = {'map_yaml': {'path': '/proc/1/fd/3', 'sha256': '1' * 64}}
    assert MONITOR._parse_snapshot_manifest(payload) == payload
    assert MONITOR._parse_snapshot_manifest(
        json.dumps(payload, sort_keys=True)) == payload


@pytest.mark.parametrize('payload', [[], 1, True, None])
def test_snapshot_manifest_rejects_non_mapping_parameter_types(payload):
    with pytest.raises(RuntimeError):
        MONITOR._parse_snapshot_manifest(payload)


def test_snapshot_manifest_rejects_duplicate_keys_and_deep_recursion():
    with pytest.raises(RuntimeError):
        MONITOR._parse_snapshot_manifest('{"a":1,"a":2}')
    with pytest.raises(RuntimeError):
        MONITOR._parse_snapshot_manifest('[' * 2000 + '0' + ']' * 2000)

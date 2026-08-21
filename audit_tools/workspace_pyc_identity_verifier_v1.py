"""Host-owned verifier for the isolated workspace-PYC identity broker.

This module is loaded from its exact source bytes by the v2 supervisor runners.
It never runs in the audited test child and never receives an open broker file
descriptor.  It validates only identities and transcripts; broker capability
material (raw bytes, file descriptors and the session nonce) is forbidden from
all emitted records.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import PurePosixPath
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple


SCHEMA_VERSION = "workspace_pyc_identity_verifier_result/v1"
BROKER_SCHEMA_VERSION = "workspace_pyc_identity_broker_result/v1"
BROKER_READY_MARKER = "OFFLINE_WORKSPACE_PYC_BROKER_READY "
BROKER_CHECKPOINT_MARKER = "OFFLINE_WORKSPACE_PYC_BROKER_CHECKPOINT "
BROKER_FINAL_MARKER = "OFFLINE_WORKSPACE_PYC_BROKER_FINAL "
BROKER_ERROR_MARKER = "OFFLINE_WORKSPACE_PYC_BROKER_ERROR "
EXECUTION_COMPONENT_BOOTSTRAP_SCHEMA = (
    "host_owned_execution_component_bootstrap/v1"
)
EXECUTION_COMPONENT_BOOTSTRAP_SHA256 = (
    "511f43a8b14f5428588c359739bec177c8db4687112be933eff2f2330a75bb1c"
)
BROKER_RELATIVE_PATH = "audit_tools/workspace_pyc_identity_broker_v1.py"
CHECKPOINT_PHASES = (
    "AFTER_PRODUCTION_WRAPPER",
    "AFTER_TEST_CHILD",
)


PYC_INVENTORY: Tuple[Mapping[str, Any], ...] = (
    {"path": "src/limo_cleanup_perception/limo_cleanup_perception/__pycache__/__init__.cpython-312.pyc", "size_bytes": 214, "sha256": "78f96e22cf96d017139da3aece774f635ee006f22390c1a78a3ec097e8315e3b"},
    {"path": "src/limo_cleanup_perception/limo_cleanup_perception/__pycache__/__init__.cpython-314.pyc", "size_bytes": 220, "sha256": "b200787a3c4754dde0c7ead4e3e98f8ed8dcd378c89ac60a4b540169e66598ac"},
    {"path": "src/limo_cleanup_perception/limo_cleanup_perception/__pycache__/evidence_binding.cpython-312.pyc", "size_bytes": 5833, "sha256": "1b88a431d58896bfc04fe460f2b851fc4d0aedd1824fe1babdebfe870897fbb5"},
    {"path": "src/limo_cleanup_perception/limo_cleanup_perception/__pycache__/evidence_binding.cpython-314.pyc", "size_bytes": 7079, "sha256": "9efef1d5045fa4e9a5f58991b9b654eaa0f6fbcd47c4cc5b056c7e6d7414c499"},
    {"path": "src/limo_cleanup_perception/limo_cleanup_perception/__pycache__/perception_core.cpython-312.pyc", "size_bytes": 13991, "sha256": "e53cfcbb8df8336b6e11df1671f9e08ab8e548333c93e987112d528712d85401"},
    {"path": "src/limo_cleanup_perception/limo_cleanup_perception/__pycache__/perception_evaluator.cpython-312.pyc", "size_bytes": 57985, "sha256": "798aff14d11ab2378163177f60668a904ee866ab2b697b02215a54461b6fa1b1"},
    {"path": "src/limo_cleanup_perception/limo_cleanup_perception/__pycache__/perception_evaluator.cpython-314.pyc", "size_bytes": 68091, "sha256": "2daeb486ba30a8cb001c63178a7a39d3576e68fc3bd6699a9a3109ef1d3988ee"},
    {"path": "src/limo_cleanup_perception/limo_cleanup_perception/__pycache__/perception_readiness.cpython-312.pyc", "size_bytes": 295010, "sha256": "fe053afa9250ed126ef374e5ceff72c24b90568d75660e3bdfcc9eae99ead0b0"},
    {"path": "src/limo_cleanup_perception/limo_cleanup_perception/__pycache__/perception_readiness.cpython-314.pyc", "size_bytes": 440146, "sha256": "56af58364e9ecc94acfd718b6c55004f3030e1a768a06d04f078b290b34253ab"},
    {"path": "src/limo_cleanup_perception/limo_cleanup_perception/__pycache__/rgbd_bag_indexer.cpython-312.pyc", "size_bytes": 67692, "sha256": "bd21494d7ae5c4ca6d1b14a5c4f3dabcceed3c823f4308d6582d0ca444459d1c"},
    {"path": "src/limo_cleanup_perception/limo_cleanup_perception/__pycache__/rgbd_bag_indexer.cpython-314.pyc", "size_bytes": 80227, "sha256": "063fe97ffadcc9b49ac3054f8ec25ca03ff17afaf3828a83b1cef102034e41df"},
    {"path": "src/limo_cleanup_perception/limo_cleanup_perception/__pycache__/ros1_source_core_admission.cpython-312.pyc", "size_bytes": 22310, "sha256": "7a33bf43c59292a322187872e8e098529b0894d8b8309836a025922bb81e2e1b"},
    {"path": "src/limo_cleanup_perception/limo_cleanup_perception/__pycache__/stdlib_attestation.cpython-312.pyc", "size_bytes": 26427, "sha256": "8054f6e38e9533cedd1865dd7cf4e4202adda4bb6fa4f7e98fb781eff062c1ed"},
    {"path": "src/limo_cleanup_perception/limo_cleanup_perception/__pycache__/stdlib_attestation.cpython-314.pyc", "size_bytes": 28768, "sha256": "2ae546ab8415f515d47236877ea2203b38cd0d94a6a08abdf7ef319f1455dca8"},
    {"path": "src/limo_cleanup_perception/limo_cleanup_perception/__pycache__/target_contract.cpython-312.pyc", "size_bytes": 12598, "sha256": "67fd007b379e660932d45e55a5a6b6c3aee143f58f1f83010abd245b3f90d615"},
    {"path": "src/limo_cleanup_perception/limo_cleanup_perception/__pycache__/target_contract.cpython-314.pyc", "size_bytes": 15324, "sha256": "55ac0fcd5a0114e771c33778470850f9c6c44f388a49293dac61aa3816159217"},
    {"path": "src/limo_cleanup_perception/limo_cleanup_perception/__pycache__/typed_raw_binding.cpython-312.pyc", "size_bytes": 24265, "sha256": "0ac9615815621d32c73c8b727c944a9ec90ed0568872bee50fa7f7cab9a91838"},
    {"path": "src/limo_cleanup_perception/limo_cleanup_perception/__pycache__/typed_raw_binding.cpython-314.pyc", "size_bytes": 27296, "sha256": "32ab295c896215d9436dbf8b0a5e58af818450f75daead004fe5a2a8ac052d53"},
)


def _strict_pairs(pairs: Iterable[Tuple[str, Any]]) -> Dict[str, Any]:
    value: Dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("strict_json_duplicate_key:" + key)
        value[key] = item
    return value


def _reject_constant(value: str) -> None:
    raise ValueError("strict_json_nonfinite:" + value)


def strict_json_loads(raw: bytes | str) -> Any:
    if isinstance(raw, bytes):
        text = raw.decode("utf-8")
    elif isinstance(raw, str):
        text = raw
    else:
        raise TypeError("strict_json_input_invalid")
    return json.loads(
        text, object_pairs_hook=_strict_pairs, parse_constant=_reject_constant,
    )


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def inventory() -> List[Dict[str, Any]]:
    return [dict(item) for item in PYC_INVENTORY]


def inventory_sha256() -> str:
    return canonical_sha256(inventory())


def _valid_sha256(value: Any) -> bool:
    return (
        isinstance(value, str) and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def broker_execution_binding_failures(
    value: Any, expected: Mapping[str, Any],
) -> List[str]:
    required = {
        "schema_version", "component_kind", "path", "size_bytes",
        "sha256", "bootstrap_sha256",
    }
    if not isinstance(value, dict) or set(value) != required:
        return ["pyc_verifier_broker_execution_binding_schema_invalid"]
    failures: List[str] = []
    if (
        value.get("schema_version") != EXECUTION_COMPONENT_BOOTSTRAP_SCHEMA
        or value.get("component_kind") != "broker"
        or value.get("path") != BROKER_RELATIVE_PATH
        or value.get("bootstrap_sha256")
        != EXECUTION_COMPONENT_BOOTSTRAP_SHA256
        or type(value.get("size_bytes")) is not int
        or value["size_bytes"] <= 0
        or not _valid_sha256(value.get("sha256"))
    ):
        failures.append("pyc_verifier_broker_execution_binding_invalid")
    if value != expected:
        failures.append("pyc_verifier_broker_execution_binding_mismatch")
    return failures


def _safe_relative(value: Any) -> bool:
    if not isinstance(value, str) or not value or "\\" in value:
        return False
    path = PurePosixPath(value)
    return not path.is_absolute() and all(
        part not in ("", ".", "..") for part in path.parts
    )


def inventory_failures(value: Any) -> List[str]:
    if not isinstance(value, list):
        return ["pyc_verifier_inventory_set_invalid"]
    expected = inventory()
    failures: List[str] = []
    if len(value) != len(expected):
        failures.append("pyc_verifier_inventory_set_invalid")
    paths: List[str] = []
    for item in value:
        if not isinstance(item, dict) or set(item) != {
            "path", "size_bytes", "sha256",
        }:
            failures.append("pyc_verifier_schema_invalid")
            continue
        path = item.get("path")
        if (
            not _safe_relative(path)
            or not str(path).casefold().endswith(".pyc")
            or type(item.get("size_bytes")) is not int
            or item["size_bytes"] < 0
            or not _valid_sha256(item.get("sha256"))
        ):
            failures.append("pyc_verifier_schema_invalid")
            continue
        paths.append(path)
    if paths != sorted(set(paths)):
        failures.append("pyc_verifier_inventory_set_invalid")
    if value != expected:
        failures.append("pyc_verifier_inventory_set_invalid")
    return list(dict.fromkeys(failures))


def _identity_failures(value: Any, expected: Mapping[str, Any]) -> List[str]:
    if not isinstance(value, dict) or set(value) != {
        "path", "size_bytes", "sha256", "regular_file", "non_linklike",
        "nlink", "fd_inheritable",
    }:
        return ["pyc_verifier_schema_invalid"]
    failures: List[str] = []
    for key in ("path", "size_bytes", "sha256"):
        if value.get(key) != expected.get(key):
            failures.append("pyc_verifier_checkpoint_drift")
    if (
        value.get("regular_file") is not True
        or value.get("non_linklike") is not True
        or value.get("nlink") != 1
        or value.get("fd_inheritable") is not False
    ):
        failures.append("pyc_verifier_checkpoint_drift")
    return failures


def broker_event_failures(
    event: Any, *, record_id: str, event_kind: str, checkpoint_index: int,
    expected_phase: str, nonce_key: bytes,
    broker_execution_binding: Mapping[str, Any],
) -> List[str]:
    required = {
        "schema_version", "event", "record_id", "checkpoint_index", "phase",
        "inventory_sha256", "nonce_sha256", "identities", "raw_bytes_exported",
        "file_descriptors_exported", "hmac_sha256", "descriptor_count",
        "descriptors_closed", "nonce_invalidated", "broker_execution_binding",
    }
    if not isinstance(event, dict) or set(event) != required:
        return ["pyc_verifier_schema_invalid"]
    failures: List[str] = []
    failures.extend(broker_execution_binding_failures(
        event.get("broker_execution_binding"), broker_execution_binding,
    ))
    nonce_sha256 = hashlib.sha256(nonce_key).hexdigest()
    if (
        event.get("schema_version") != BROKER_SCHEMA_VERSION
        or event.get("event") != event_kind
        or event.get("record_id") != record_id
        or event.get("checkpoint_index") != checkpoint_index
        or event.get("phase") != expected_phase
        or event.get("inventory_sha256") != inventory_sha256()
        or event.get("nonce_sha256") != nonce_sha256
    ):
        failures.append("pyc_verifier_nonce_digest_mismatch")
    supplied_hmac = event.get("hmac_sha256")
    unsigned = dict(event)
    unsigned.pop("hmac_sha256", None)
    expected_hmac = hmac.new(
        nonce_key, canonical_json(unsigned), hashlib.sha256,
    ).hexdigest()
    if (
        not _valid_sha256(supplied_hmac)
        or not hmac.compare_digest(supplied_hmac, expected_hmac)
    ):
        failures.append("pyc_verifier_nonce_digest_mismatch")
    if event.get("raw_bytes_exported") is not False:
        failures.append("pyc_verifier_schema_invalid")
    if event.get("file_descriptors_exported") is not False:
        failures.append("pyc_verifier_schema_invalid")
    if event_kind == "FINAL":
        if (
            event.get("descriptor_count") != 0
            or event.get("descriptors_closed") is not True
            or event.get("nonce_invalidated") is not True
        ):
            failures.append("pyc_verifier_checkpoint_drift")
    elif (
        event.get("descriptor_count") != len(PYC_INVENTORY)
        or event.get("descriptors_closed") is not False
        or event.get("nonce_invalidated") is not False
    ):
        failures.append("pyc_verifier_checkpoint_drift")
    identities = event.get("identities")
    if not isinstance(identities, list) or len(identities) != len(PYC_INVENTORY):
        failures.append("pyc_verifier_inventory_set_invalid")
    else:
        for actual, expected in zip(identities, PYC_INVENTORY):
            failures.extend(_identity_failures(actual, expected))
    return list(dict.fromkeys(failures))


def capability_surface_failures(value: Any) -> List[str]:
    expected = {
        "broker_argv_fields": [],
        "broker_channels": [],
        "broker_environment_fields": [],
        "broker_fds": [],
        "broker_modules_in_sys_modules": [],
        "broker_secrets": [],
        "broker_tokens": [],
    }
    if not isinstance(value, dict) or set(value) != set(expected):
        return ["pyc_test_child_capability_surface_nonempty"]
    failures = []
    for key, empty in expected.items():
        if value.get(key) != empty:
            failures.append("pyc_test_child_capability_surface_nonempty")
    return list(dict.fromkeys(failures))


def verify_transcript(
    *, record_id: str, nonce: str, ready: Mapping[str, Any],
    checkpoints: Sequence[Mapping[str, Any]], final: Mapping[str, Any],
    child_capability_surface: Mapping[str, Any],
    broker_execution_binding: Mapping[str, Any],
) -> Dict[str, Any]:
    failures: List[str] = []
    if (
        not isinstance(record_id, str) or not record_id
        or any(
            character not in "abcdefghijklmnopqrstuvwxyz0123456789_"
            for character in record_id
        )
    ):
        failures.append("pyc_verifier_schema_invalid")
    if not isinstance(nonce, str) or len(nonce) != 64 or any(
        character not in "0123456789abcdef" for character in nonce
    ):
        failures.append("pyc_verifier_nonce_digest_mismatch")
        nonce_key = b""
    else:
        nonce_key = bytes.fromhex(nonce)
    failures.extend(broker_event_failures(
        ready, record_id=record_id, event_kind="READY", checkpoint_index=0,
        expected_phase="READY", nonce_key=nonce_key,
        broker_execution_binding=broker_execution_binding,
    ))
    if not isinstance(checkpoints, (list, tuple)):
        failures.append("pyc_verifier_schema_invalid")
        checkpoint_values: Sequence[Mapping[str, Any]] = ()
    else:
        checkpoint_values = checkpoints
    if len(checkpoint_values) != len(CHECKPOINT_PHASES):
        failures.append("pyc_verifier_checkpoint_drift")
    for index, event in enumerate(checkpoint_values, 1):
        expected_phase = (
            CHECKPOINT_PHASES[index - 1]
            if index <= len(CHECKPOINT_PHASES) else "INVALID"
        )
        failures.extend(broker_event_failures(
            event, record_id=record_id, event_kind="CHECKPOINT",
            checkpoint_index=index, expected_phase=expected_phase,
            nonce_key=nonce_key,
            broker_execution_binding=broker_execution_binding,
        ))
    failures.extend(broker_event_failures(
        final, record_id=record_id, event_kind="FINAL",
        checkpoint_index=len(CHECKPOINT_PHASES) + 1, expected_phase="FINAL",
        nonce_key=nonce_key,
        broker_execution_binding=broker_execution_binding,
    ))
    failures.extend(capability_surface_failures(child_capability_surface))
    projections = [ready, *checkpoint_values, final]
    identities = [
        item.get("identities") if isinstance(item, dict) else None
        for item in projections
    ]
    if identities and any(item != identities[0] for item in identities[1:]):
        failures.append("pyc_verifier_checkpoint_drift")
    failures = list(dict.fromkeys(failures))
    return {
        "schema_version": SCHEMA_VERSION,
        "validated_pass": not failures,
        "record_id": record_id,
        "inventory_count": len(PYC_INVENTORY),
        "inventory_sha256": inventory_sha256(),
        "checkpoint_count": len(checkpoint_values),
        "raw_bytes_exposed": False,
        "file_descriptors_exposed": False,
        "broker_execution_binding": dict(broker_execution_binding),
        "failures": failures,
    }


__all__ = [
    "BROKER_RELATIVE_PATH",
    "BROKER_CHECKPOINT_MARKER", "BROKER_ERROR_MARKER", "BROKER_FINAL_MARKER",
    "BROKER_READY_MARKER", "BROKER_SCHEMA_VERSION", "CHECKPOINT_PHASES",
    "PYC_INVENTORY",
    "EXECUTION_COMPONENT_BOOTSTRAP_SCHEMA",
    "EXECUTION_COMPONENT_BOOTSTRAP_SHA256", "SCHEMA_VERSION",
    "broker_event_failures", "broker_execution_binding_failures", "canonical_json",
    "canonical_sha256", "capability_surface_failures", "inventory",
    "inventory_failures", "inventory_sha256", "strict_json_loads",
    "verify_transcript",
]

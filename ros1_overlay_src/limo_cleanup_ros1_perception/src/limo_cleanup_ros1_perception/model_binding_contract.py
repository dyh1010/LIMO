"""Immutable ROS1 dual-model binding contract with a stdlib-only closure."""

import hashlib
import json
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional, Tuple


MODEL_CLASSES = ('plastic_bottle', 'trash_bin')
EXPECTED_MODEL_SHA256 = {
    'plastic_bottle': (
        'abe7eaf409e3d24d255a627823f4b107'
        'a8884008ab659901c6c50479b2153512'),
    'trash_bin': (
        '24beb4a7941ba5d783f1937128b5f0f4307b03513'
        '7889c78be1993cad76b8bc5'),
}


@dataclass(frozen=True)
class ModelBinding:
    """One immutable single-class detector binding."""

    class_name: str
    filename: str
    deployment_path: str
    size_bytes: int
    sha256: str
    backend: str


def sha256_file(path: Path) -> str:
    """Hash one regular file without loading it into memory."""
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _reject_duplicate_pairs(pairs):
    payload = {}
    for key, value in pairs:
        if key in payload:
            raise ValueError('duplicate JSON key: ' + key)
        payload[key] = value
    return payload


def _reject_non_finite(value):
    raise ValueError('non-finite JSON constant: ' + value)


def _lower_sha256(value) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and value == value.lower()
        and all(character in '0123456789abcdef' for character in value)
    )


def _path_is_linklike(path: Path) -> bool:
    try:
        candidate = Path(path)
        info = candidate.lstat()
        if candidate.is_symlink() or stat.S_ISLNK(info.st_mode):
            return True
        attributes = getattr(info, 'st_file_attributes', 0)
        reparse = getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0)
        return bool(reparse and attributes & reparse)
    except (OSError, RuntimeError):
        return True


def load_model_bindings(path: Path) -> Tuple[Mapping[str, ModelBinding], str]:
    """Load the exact two-model manifest and return its artifact hash."""
    candidate = Path(path).resolve(strict=True)
    if not candidate.is_file() or _path_is_linklike(candidate):
        raise ValueError('model binding manifest must be a regular file')
    payload = json.loads(
        candidate.read_text(encoding='utf-8'),
        object_pairs_hook=_reject_duplicate_pairs,
        parse_constant=_reject_non_finite,
    )
    expected_keys = {
        'schema_version', 'manifest_id', 'runtime_family', 'ros_distro',
        'read_only', 'authorizes_motion', 'delivery_ready', 'runtime',
        'load_policy', 'models'}
    if (
            not isinstance(payload, Mapping)
            or set(payload) != expected_keys
            or payload.get('schema_version') != 1
            or payload.get('manifest_id')
            != 'limo-ros1-dual-model-bindings-v1'
            or payload.get('runtime_family') != 'ROS1'
            or payload.get('ros_distro') != 'noetic'
            or payload.get('read_only') is not True
            or payload.get('authorizes_motion') is not False
            or payload.get('delivery_ready') is not False
            or payload.get('runtime') != 'ultralytics-8.3.21'):
        raise ValueError('model binding manifest policy is invalid')
    if payload.get('load_policy') != {
            'regular_file_required': True,
            'sha256_required': True,
            'single_exact_class_required': True,
            'missing_model_is_fatal': True,
            'hash_mismatch_is_fatal': True,
            'silent_fallback_or_relabel_forbidden': True,
            'automatic_download_forbidden': True}:
        raise ValueError('model loading policy is invalid')
    raw_models = payload.get('models')
    if not isinstance(raw_models, Mapping) or set(raw_models) != set(
            MODEL_CLASSES):
        raise ValueError('model binding classes are incomplete')
    bindings = {}
    entry_keys = {
        'class_name', 'filename', 'deployment_path', 'size_bytes',
        'sha256', 'backend'}
    expected_filenames = {
        'plastic_bottle': 'nongfu_yolov8n_best.pt',
        'trash_bin': 'trash_bin_yolov8n_best.pt',
    }
    expected_paths = {
        class_name: '/home/agilex/limo_cleanup_ws/models/' + filename
        for class_name, filename in expected_filenames.items()}
    expected_sizes = {
        'plastic_bottle': 6244778,
        'trash_bin': 6231338,
    }
    for class_name in MODEL_CLASSES:
        item = raw_models[class_name]
        if (
                not isinstance(item, Mapping)
                or set(item) != entry_keys
                or item.get('class_name') != class_name
                or item.get('filename') != expected_filenames[class_name]
                or item.get('deployment_path') != expected_paths[class_name]
                or not isinstance(item.get('size_bytes'), int)
                or isinstance(item.get('size_bytes'), bool)
                or item.get('size_bytes') != expected_sizes[class_name]
                or item.get('sha256') != EXPECTED_MODEL_SHA256[class_name]
                or not _lower_sha256(item.get('sha256'))
                or item.get('backend') != 'ultralytics-yolo-pt'):
            raise ValueError('invalid model binding: ' + class_name)
        bindings[class_name] = ModelBinding(**dict(item))
    return bindings, sha256_file(candidate)


def resolve_model_artifacts(
        bindings: Mapping[str, ModelBinding],
        model_root: Optional[Path] = None) -> Mapping[str, Path]:
    """Resolve and verify both weight files before any model is loaded."""
    resolved = {}
    for class_name in MODEL_CLASSES:
        binding = bindings[class_name]
        candidate = (
            Path(binding.deployment_path)
            if model_root is None
            else Path(model_root) / binding.filename)
        try:
            path = candidate.resolve(strict=True)
        except (OSError, RuntimeError) as error:
            raise ValueError(
                'model artifact missing: ' + class_name) from error
        if not path.is_file() or _path_is_linklike(path):
            raise ValueError(
                'model artifact is not a regular file: ' + class_name)
        if path.stat().st_size != binding.size_bytes:
            raise ValueError('model artifact size mismatch: ' + class_name)
        if sha256_file(path) != binding.sha256:
            raise ValueError('model artifact hash mismatch: ' + class_name)
        resolved[class_name] = path
    return resolved


def model_set_sha256(bindings: Mapping[str, ModelBinding]) -> str:
    """Return a deterministic identity for the ordered class/hash set."""
    value = [
        {'class_name': name, 'sha256': bindings[name].sha256}
        for name in MODEL_CLASSES]
    encoded = json.dumps(
        value, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()

"""Canonical hashes and provenance checks for read-only V2 evidence."""

import hashlib
import json
import math
from pathlib import Path
from typing import Mapping, Sequence


def sha256_file(path: Path) -> str:
    """Hash one artifact without importing ROS or changing the file."""
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def artifact_identity(path: Path) -> Mapping:
    """Return the canonical path/size/hash identity of a regular file."""
    resolved = Path(path).resolve(strict=True)
    if not resolved.is_file():
        raise ValueError('evidence artifact must be a regular file')
    return {
        'path': str(resolved),
        'size_bytes': resolved.stat().st_size,
        'sha256': sha256_file(resolved),
    }


def canonical_file_manifest(
        entries: Sequence[Mapping], base_path: Path = None) -> Mapping:
    """Validate exact file identities and hash a deterministic manifest."""
    if not isinstance(entries, list) or not entries:
        raise ValueError('source manifest entries are missing')
    normalized = []
    names = set()
    paths = set()
    for entry in entries:
        if not isinstance(entry, Mapping) or set(entry) != {
                'name', 'path', 'size_bytes', 'sha256'}:
            raise ValueError('source manifest entry is invalid')
        name = entry.get('name')
        if (not isinstance(name, str) or not name or name in names
                or not isinstance(entry.get('path'), str)
                or not entry.get('path')):
            raise ValueError('source manifest identity is invalid')
        entry_path = Path(entry['path'])
        if not entry_path.is_absolute():
            if base_path is None:
                raise ValueError('relative source manifest path needs base_path')
            entry_path = Path(base_path) / entry_path
        identity = artifact_identity(entry_path)
        if identity['path'] in paths:
            raise ValueError('source manifest path is duplicated')
        if (entry.get('size_bytes') != identity['size_bytes']
                or entry.get('sha256') != identity['sha256']):
            raise ValueError('source manifest file identity mismatch')
        names.add(name)
        paths.add(identity['path'])
        normalized.append({
            'name': name,
            'path': entry['path'].replace('\\', '/'),
            'size_bytes': identity['size_bytes'],
            'sha256': identity['sha256'],
        })
    normalized.sort(key=lambda item: item['name'])
    source_set = [{
        key: item[key] for key in ('name', 'size_bytes', 'sha256')}
        for item in normalized]
    canonical = json.dumps(
        source_set, ensure_ascii=False, sort_keys=True,
        separators=(',', ':')).encode('utf-8')
    return {
        'entries': normalized,
        'sha256': hashlib.sha256(canonical).hexdigest(),
        'file_count': len(normalized),
    }


def valid_release_id(value) -> bool:
    """Return whether a release identifier is explicit and machine-safe."""
    return (isinstance(value, str) and 8 <= len(value) <= 128
            and all(character.isalnum() or character in '._-'
                    for character in value))


def finite_timestamp(value) -> bool:
    """Return whether a value is a non-negative finite Unix timestamp."""
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and value >= 0.0)

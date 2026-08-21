"""Interpreter-rooted stdlib provenance checks for the model-loader gate.

This module deliberately does not import any of the six modules that it
attests.  Expected specs are resolved from the interpreter's own stdlib root
through CPython's frozen import finders, rather than learned from the objects
already present in ``sys.modules``.
"""

import _frozen_importlib as _bootstrap
import _frozen_importlib_external as _bootstrap_external
import os
import sys


WATCHED_STDLIB_MODULES = (
    'json', 'hashlib', 'stat', 'dataclasses', 'pathlib', 'typing')

_REGULAR_FILE_TYPE = 0o100000
_FILE_TYPE_MASK = 0o170000
_MODULE_TYPE = type(sys)
_BUILTIN_FUNCTION_TYPE = type(len)
_CODE_TYPE = type((lambda: None).__code__)
_SHA256_INITIAL = (
    0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
    0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19)
_SHA256_ROUND = (
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5,
    0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3,
    0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc,
    0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7,
    0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
    0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3,
    0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5,
    0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
    0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2)


def _module_dict(module):
    """Read a module namespace without invoking module-level ``__getattr__``."""
    try:
        namespace = object.__getattribute__(module, '__dict__')
    except (AttributeError, TypeError):
        return {}
    return namespace if isinstance(namespace, dict) else {}


def _loader_label(loader):
    if loader is None:
        return None
    loader_type = loader if isinstance(loader, type) else type(loader)
    return '{}.{}'.format(
        getattr(loader_type, '__module__', ''),
        getattr(loader_type, '__qualname__',
                getattr(loader_type, '__name__', '')))


def _stdlib_root():
    base = os.path.realpath(sys.base_prefix)
    if sys.platform == 'win32':
        return os.path.realpath(os.path.join(base, 'Lib'))
    directory = getattr(sys, 'platlibdir', 'lib')
    version = 'python{}.{}'.format(
        sys.version_info[0], sys.version_info[1])
    return os.path.realpath(os.path.join(base, directory, version))


def _source_sha256(path):
    with open(path, 'rb') as stream:
        payload = stream.read()
    return _sha256_payload(payload)


def _sha256_payload(value):
    payload = bytearray(value)
    bit_length = len(payload) * 8
    payload.append(0x80)
    while len(payload) % 64 != 56:
        payload.append(0)
    payload.extend(bit_length.to_bytes(8, 'big'))
    state = list(_SHA256_INITIAL)
    mask = 0xffffffff
    for offset in range(0, len(payload), 64):
        block = payload[offset:offset + 64]
        words = [
            int.from_bytes(block[index:index + 4], 'big')
            for index in range(0, 64, 4)]
        for index in range(16, 64):
            value_15 = words[index - 15]
            value_2 = words[index - 2]
            sigma_0 = (
                ((value_15 >> 7) | (value_15 << 25))
                ^ ((value_15 >> 18) | (value_15 << 14))
                ^ (value_15 >> 3)) & mask
            sigma_1 = (
                ((value_2 >> 17) | (value_2 << 15))
                ^ ((value_2 >> 19) | (value_2 << 13))
                ^ (value_2 >> 10)) & mask
            words.append((
                words[index - 16] + sigma_0 + words[index - 7] + sigma_1
            ) & mask)
        a, b, c, d, e, f, g, h = state
        for index, constant in enumerate(_SHA256_ROUND):
            sum_1 = (
                ((e >> 6) | (e << 26))
                ^ ((e >> 11) | (e << 21))
                ^ ((e >> 25) | (e << 7))) & mask
            choose = (e & f) ^ ((~e) & g)
            temporary_1 = (
                h + sum_1 + choose + constant + words[index]) & mask
            sum_0 = (
                ((a >> 2) | (a << 30))
                ^ ((a >> 13) | (a << 19))
                ^ ((a >> 22) | (a << 10))) & mask
            majority = (a & b) ^ (a & c) ^ (b & c)
            temporary_2 = (sum_0 + majority) & mask
            h, g, f, e, d, c, b, a = (
                g, f, e, (d + temporary_1) & mask,
                c, b, a, (temporary_1 + temporary_2) & mask)
        state = [
            (left + right) & mask
            for left, right in zip(state, (a, b, c, d, e, f, g, h))]
    return ''.join('{:08x}'.format(value) for value in state)


def _regular_non_link(path):
    try:
        info = os.lstat(path)
    except (OSError, ValueError, TypeError):
        return False
    return (info.st_mode & _FILE_TYPE_MASK) == _REGULAR_FILE_TYPE


def _inside_root(path, root):
    try:
        return os.path.commonpath((
            os.path.normcase(os.path.realpath(path)),
            os.path.normcase(os.path.realpath(root)),
        )) == os.path.normcase(os.path.realpath(root))
    except (OSError, ValueError, TypeError):
        return False


def _expected_spec(name, root):
    spec = _bootstrap.BuiltinImporter.find_spec(name)
    if spec is None:
        spec = _bootstrap.FrozenImporter.find_spec(name)
    if spec is None:
        spec = _bootstrap_external.PathFinder.find_spec(name, [root])
    return spec


class _CanonicalWatchedFinder:
    """Resolve watched names from the attested root before ambient finders."""

    def __init__(self, root):
        self.root = root

    def find_spec(self, fullname, path=None, target=None):
        del path, target
        if fullname in WATCHED_STDLIB_MODULES:
            return _expected_spec(fullname, self.root)
        if fullname.startswith('json.'):
            package_root = os.path.join(self.root, 'json')
            return _bootstrap_external.PathFinder.find_spec(
                fullname, [package_root])
        return None


def begin_canonical_watched_imports():
    """Install a temporary first finder for missing watched modules."""
    before = tuple(sys.meta_path)
    finder = _CanonicalWatchedFinder(_stdlib_root())
    sys.meta_path.insert(0, finder)
    return finder, before


def end_canonical_watched_imports(token):
    """Remove exactly the temporary finder and report exact restoration."""
    finder, before = token
    if sys.meta_path and sys.meta_path[0] is finder:
        del sys.meta_path[0]
    else:
        for index, candidate in enumerate(tuple(sys.meta_path)):
            if candidate is finder:
                del sys.meta_path[index]
                break
    return tuple(sys.meta_path) == before


def _safe_attr(value, name, default=None):
    try:
        return object.__getattribute__(value, name)
    except (AttributeError, TypeError):
        return default


def _code_origin(value):
    namespace = _safe_attr(value, '__dict__')
    code = namespace.get('__code__') if isinstance(namespace, dict) else None
    if code is None:
        try:
            code = object.__getattribute__(value, '__code__')
        except (AttributeError, TypeError):
            return None
    return getattr(code, 'co_filename', None)


def _nested_namespace_value(namespace, dotted_name):
    parts = dotted_name.split('.')
    value = namespace.get(parts[0])
    for part in parts[1:]:
        mro = _safe_attr(value, '__mro__')
        owners = mro if isinstance(mro, tuple) else (value,)
        found = False
        for owner in owners:
            child_namespace = _safe_attr(owner, '__dict__')
            if child_namespace is None:
                continue
            try:
                value = child_namespace[part]
            except (KeyError, TypeError):
                continue
            found = True
            break
        if not found:
            return None
    return value


def _critical_attributes(name):
    return {
        'json': ('loads', 'dumps'),
        'hashlib': ('sha256',),
        'stat': ('S_ISREG', 'S_ISLNK'),
        'dataclasses': ('dataclass',),
        'pathlib': ('Path.exists',),
        'typing': ('get_origin',),
    }[name]


def _critical_code_origins(name, namespace):
    return tuple(
        (attribute, _code_origin(
            _nested_namespace_value(namespace, attribute)))
        for attribute in _critical_attributes(name))


def _code_material(code):
    constants = []
    for value in code.co_consts:
        if isinstance(value, _CODE_TYPE):
            constants.append(('code', _code_material(value)))
        elif isinstance(value, (str, bytes, int, float, complex, type(None))):
            constants.append((type(value).__name__, repr(value)))
        elif isinstance(value, tuple):
            constants.append(('tuple', tuple(
                (type(item).__name__, repr(item))
                for item in value)))
        else:
            constants.append((type(value).__name__, repr(value)))
    return (
        code.co_name,
        getattr(code, 'co_qualname', code.co_name),
        code.co_argcount,
        getattr(code, 'co_posonlyargcount', 0),
        code.co_kwonlyargcount,
        code.co_nlocals,
        code.co_stacksize,
        code.co_flags,
        code.co_code.hex(),
        tuple(code.co_names),
        tuple(code.co_varnames),
        tuple(code.co_freevars),
        tuple(code.co_cellvars),
        tuple(constants),
    )


def _code_sha256(code):
    if not isinstance(code, _CODE_TYPE):
        return None
    return _sha256_payload(repr(_code_material(code)).encode('utf-8'))


def _find_named_code(code, name):
    matches = []
    for value in code.co_consts:
        if not isinstance(value, _CODE_TYPE):
            continue
        if value.co_name == name:
            matches.append(value)
        matches.extend(_find_named_code(value, name))
    return matches


def _expected_code_hashes(name, expected_origin):
    if not isinstance(expected_origin, str) or expected_origin == 'frozen':
        return {}
    with open(expected_origin, 'rb') as stream:
        source = stream.read()
    module_code = compile(source, expected_origin, 'exec', dont_inherit=True)
    attributes = {
        'json': ('loads', 'dumps'),
        'stat': ('S_ISREG', 'S_ISLNK'),
        'dataclasses': ('dataclass',),
        'pathlib': ('exists',),
        'typing': ('get_origin',),
    }.get(name, ())
    result = {}
    for attribute in attributes:
        matches = _find_named_code(module_code, attribute)
        result[attribute] = tuple(sorted(
            _code_sha256(code) for code in matches))
    return result


def _loader_matches_expected(ambient, expected):
    if ambient is None or expected is None:
        return False
    if isinstance(expected, type):
        return ambient is expected
    return type(ambient) is type(expected)


def _trusted_builtin(value, modules, names):
    if type(value) is not _BUILTIN_FUNCTION_TYPE:
        return False
    if _safe_attr(value, '__code__') is not None:
        return False
    if _safe_attr(value, '__module__') not in modules:
        return False
    if _safe_attr(value, '__name__') not in names:
        return False
    owner = _safe_attr(value, '__self__')
    if owner is None:
        return True
    owner_namespace = _module_dict(owner)
    return owner_namespace.get('__name__') in modules


def _resolved_file(value):
    return (os.path.realpath(value) if isinstance(value, str) else None)


def audit_ambient_stdlib(allow_missing=False):
    """Return provenance records and stable mismatch codes for six modules."""
    root = _stdlib_root()
    provenance = []
    failures = []
    missing = object()
    for name in WATCHED_STDLIB_MODULES:
        current = sys.modules.get(name, missing)
        expected = _expected_spec(name, root)
        expected_origin = _safe_attr(expected, 'origin')
        expected_loader = _safe_attr(expected, 'loader')
        expected_is_frozen = expected_origin == 'frozen'
        expected_resolved_origin = (
            'frozen' if expected_is_frozen or not isinstance(
                expected_origin, str)
            else os.path.realpath(expected_origin))
        expected_regular = (
            expected_is_frozen
            or (
                isinstance(expected_origin, str)
                and _inside_root(expected_origin, root)
                and _regular_non_link(expected_origin)))
        expected_sha256 = (
            _source_sha256(expected_resolved_origin)
            if expected_regular and not expected_is_frozen else None)

        if current is missing:
            valid = bool(allow_missing and expected is not None
                         and expected_regular)
            provenance.append({
                'module': name,
                'attestor_source_sha256': ATTESTOR_SOURCE_SHA256,
                'present': False,
                'bound_trusted_object': False,
                'expected_origin': expected_origin,
                'trusted_origin': expected_resolved_origin,
                'ambient_origin': None,
                'ambient_file': None,
                'ambient_file_matches': False,
                'expected_loader': _loader_label(expected_loader),
                'trusted_loader': _loader_label(expected_loader),
                'ambient_loader': None,
                'expected_regular_non_link': expected_regular,
                'expected_source_sha256': expected_sha256,
                'module_type_valid': False,
                'origin_matches': False,
                'loader_type_matches': False,
                'loader_path_matches': False,
                'module_loader_matches_spec': False,
                'critical_code_origins': [],
                'critical_code_origin_valid': False,
                'provenance_valid': valid,
            })
            if not valid:
                failures.append(
                    'ros1_field_model_loader_ambient_stdlib_identity_mismatch:'
                    + name)
            continue

        namespace = _module_dict(current)
        spec = namespace.get('__spec__')
        ambient_origin = _safe_attr(spec, 'origin')
        ambient_loader = _safe_attr(spec, 'loader')
        module_loader = namespace.get('__loader__')
        ambient_file = namespace.get('__file__')
        ambient_is_frozen = ambient_origin == 'frozen'
        ambient_resolved_origin = (
            'frozen' if ambient_is_frozen or not isinstance(
                ambient_origin, str)
            else os.path.realpath(ambient_origin))
        origin_matches = (
            expected is not None
            and ambient_resolved_origin == expected_resolved_origin)
        loader_type_matches = _loader_matches_expected(
            ambient_loader, expected_loader)
        ambient_loader_path = _safe_attr(ambient_loader, 'path')
        expected_loader_path = _safe_attr(expected_loader, 'path')
        loader_path_matches = (
            expected_is_frozen
            or (
                _resolved_file(ambient_loader_path)
                == _resolved_file(expected_loader_path)
                == expected_resolved_origin))
        frozen_source = os.path.join(root, name + '.py')
        ambient_file_matches = (
            (
                ambient_file is None
                or (
                    _resolved_file(ambient_file)
                    == _resolved_file(frozen_source)
                    and _regular_non_link(ambient_file)))
            if expected_is_frozen else
            _resolved_file(ambient_file) == expected_resolved_origin)
        module_loader_matches_spec = module_loader is ambient_loader
        module_type_valid = type(current) is _MODULE_TYPE
        code_origins = _critical_code_origins(name, namespace)
        critical_values = tuple(
            (attribute, _nested_namespace_value(namespace, attribute))
            for attribute in _critical_attributes(name))
        expected_code_hashes = _expected_code_hashes(
            name, expected_origin)
        critical_code_hashes = tuple(
            (attribute, _code_sha256(
                _safe_attr(value, '__code__')))
            for attribute, value in critical_values)
        if name == 'hashlib':
            sha256_callable = namespace.get('sha256')
            critical_code_origin_valid = (
                all(origin is None for _, origin in code_origins)
                and _trusted_builtin(
                    sha256_callable,
                    ('_hashlib', '_sha256'),
                    ('openssl_sha256', 'sha256')))
        elif name == 'stat' and expected_is_frozen:
            critical_code_origin_valid = all(
                (origin is None and _trusted_builtin(
                    namespace.get(attribute),
                    ('stat', '_stat'),
                    (attribute,)))
                or origin == '<frozen stat>'
                for attribute, origin in code_origins)
        elif expected_is_frozen:
            critical_code_origin_valid = all(
                origin == '<frozen {}>'.format(name)
                for _, origin in code_origins)
        else:
            critical_code_origin_valid = all(
                _resolved_file(origin) == expected_resolved_origin
                and _regular_non_link(origin)
                for _, origin in code_origins)
            critical_code_origin_valid = (
                critical_code_origin_valid
                and all(
                    code_hash is not None
                    and code_hash in expected_code_hashes.get(
                        attribute.rsplit('.', 1)[-1], ())
                    and _safe_attr(value, '__globals__') is namespace
                    for (attribute, value), (_, code_hash)
                    in zip(critical_values, critical_code_hashes)))
        ambient_regular = (
            ambient_is_frozen
            or (
                isinstance(ambient_origin, str)
                and _inside_root(ambient_origin, root)
                and _regular_non_link(ambient_origin)))
        bound_trusted_object = all((
            module_type_valid,
            namespace.get('__name__') == name,
            critical_code_origin_valid,
        ))
        captured_provenance_valid = all((
            expected is not None,
            expected_regular,
            bool(expected_sha256) if not expected_is_frozen else True,
        ))
        spec_object_matches = (
            spec is not None and module_loader_matches_spec)
        valid = all((
            captured_provenance_valid,
            bound_trusted_object,
            module_type_valid,
            spec_object_matches,
            origin_matches,
            loader_type_matches,
            loader_path_matches,
            module_loader_matches_spec,
            ambient_file_matches,
            ambient_regular,
            critical_code_origin_valid,
        ))
        provenance.append({
            'module': name,
            'attestor_source_sha256': ATTESTOR_SOURCE_SHA256,
            'present': True,
            'bound_trusted_object': bound_trusted_object,
            'captured_provenance_valid': captured_provenance_valid,
            'spec_object_matches': spec_object_matches,
            'expected_origin': expected_origin,
            'trusted_origin': expected_resolved_origin,
            'ambient_origin': ambient_origin,
            'ambient_file': ambient_file,
            'ambient_file_matches': ambient_file_matches,
            'expected_loader': _loader_label(expected_loader),
            'trusted_loader': _loader_label(expected_loader),
            'ambient_loader': _loader_label(ambient_loader),
            'expected_regular_non_link': expected_regular,
            'ambient_regular_non_link': ambient_regular,
            'expected_source_sha256': expected_sha256,
            'module_type_valid': module_type_valid,
            'origin_matches': origin_matches,
            'loader_type_matches': loader_type_matches,
            'loader_object_matches': loader_type_matches,
            'loader_path_matches': loader_path_matches,
            'module_loader_matches_spec': module_loader_matches_spec,
            'module_loader_object_matches': module_loader_matches_spec,
            'critical_code_origins': list(code_origins),
            'critical_code_sha256': list(critical_code_hashes),
            'expected_critical_code_sha256': expected_code_hashes,
            'critical_code_origin_valid': critical_code_origin_valid,
            'provenance_valid': valid,
        })
        if not valid:
            failures.append(
                'ros1_field_model_loader_ambient_stdlib_identity_mismatch:'
                + name)
    return tuple(provenance), tuple(failures)


def bootstrap_ambient_stdlib():
    """Attest pre-existing bindings before the host imports watched modules."""
    return audit_ambient_stdlib(allow_missing=True)


ATTESTOR_SOURCE_SHA256 = _source_sha256(__file__)

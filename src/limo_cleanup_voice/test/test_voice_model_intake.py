# Copyright 2026 DYH
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Independent tests for the explicit, read-only Vosk intake gate."""

import hashlib
import json
from pathlib import Path

import pytest
from jsonschema import Draft7Validator

import limo_cleanup_voice.voice_model_intake as intake
from limo_cleanup_voice.voice_grammar import DEFAULT_GRAMMAR


def _write_plausible_model(model):
    (model / 'am').mkdir(parents=True)
    (model / 'conf').mkdir()
    (model / 'graph' / 'phones').mkdir(parents=True)
    model_header = b'\x00B<TransitionModel> '
    (model / 'am' / 'final.mdl').write_bytes(
        model_header + b'\x00' * (1024 * 1024 - len(model_header)))
    graph_header = b'\xd6\xfd\xb2\x7e'
    (model / 'graph' / 'HCLr.fst').write_bytes(
        graph_header + b'\x00' * (1024 - len(graph_header)))
    (model / 'graph' / 'Gr.fst').write_bytes(
        graph_header + b'\x00' * (32 - len(graph_header)))
    (model / 'conf' / 'mfcc.conf').write_text(
        '--sample-frequency=16000\n--num-mel-bins=40\n',
        encoding='utf-8')
    (model / 'conf' / 'model.conf').write_text(
        '--endpoint.silence-phones=1:2:3\n', encoding='utf-8')
    words = ['<eps> 0'] + [
        'word{} {}'.format(index, index) for index in range(1, 10)
    ]
    (model / 'graph' / 'words.txt').write_text(
        '\n'.join(words) + '\n', encoding='utf-8')
    (model / 'graph' / 'phones' / 'word_boundary.int').write_text(
        '1 0\n2 1\n', encoding='utf-8')
    (model / 'graph' / 'disambig_tid.int').write_text(
        '1\n2\n3\n', encoding='utf-8')


@pytest.mark.parametrize('provided', [
    '',
    'relative/model',
    'file:///tmp/model',
    'https://example.invalid/model',
    r'\\server\share\model',
])
def test_intake_rejects_non_explicit_or_nonlocal_paths_without_validation(
        provided, monkeypatch):
    calls = []
    monkeypatch.setattr(
        intake, 'validate_vosk_model',
        lambda *args, **kwargs: calls.append((args, kwargs)))

    report = intake.validate_local_vosk_model(provided)

    assert report['status'] == 'BLOCKED'
    assert report['delivery_ready'] is False
    assert report['input']['automatic_search_performed'] is False
    assert report['input']['network_access_performed'] is False
    assert calls == []


def test_intake_missing_explicit_directory_is_blocked(tmp_path):
    missing = tmp_path / 'missing-model'

    report = intake.validate_local_vosk_model(missing)

    assert report['delivery_ready'] is False
    assert report['model']['inventory']['files'] == []
    assert report['grammar_probe']['attempted'] is False
    assert 'Vosk model directory is missing' in report['blocking_issues']


def test_intake_reports_deterministic_inventory_and_complete_grammar(
        tmp_path):
    model = tmp_path / 'model'
    _write_plausible_model(model)
    captured = {}

    def recognizer_loader(unused_model, sample_rate, grammar_json):
        captured['sample_rate'] = sample_rate
        captured['grammar'] = json.loads(grammar_json)
        return object()

    first = intake.validate_local_vosk_model(
        model,
        model_loader=lambda unused_path: object(),
        recognizer_loader=recognizer_loader,
    )
    second = intake.validate_local_vosk_model(
        model,
        model_loader=lambda unused_path: object(),
        recognizer_loader=recognizer_loader,
    )

    assert first['status'] == 'PASS'
    assert first['delivery_ready'] is True
    assert first['blocking_issues'] == []
    assert first['model']['inventory'] == second['model']['inventory']
    assert first['model']['inventory']['file_count'] == 8
    assert first['model']['inventory']['total_bytes'] > 1024 * 1024
    assert len(first['model']['inventory']['directory_sha256']) == 64
    assert all(not Path(item['path']).is_absolute()
               for item in first['model']['inventory']['files'])
    assert all(len(item['sha256']) == 64
               for item in first['model']['inventory']['files'])
    assert captured['sample_rate'] == 16000.0
    assert captured['grammar'] == DEFAULT_GRAMMAR
    grammar_payload = json.dumps(
        DEFAULT_GRAMMAR, ensure_ascii=False, sort_keys=True,
        separators=(',', ':')).encode('utf-8')
    assert first['grammar_probe']['phrases_sha256'] == (
        hashlib.sha256(grammar_payload).hexdigest())


def test_intake_runtime_probe_failure_is_blocked(tmp_path):
    model = tmp_path / 'model'
    _write_plausible_model(model)

    def reject_recognizer(unused_model, unused_rate, unused_grammar):
        raise RuntimeError('grammar construction failed')

    report = intake.validate_local_vosk_model(
        model,
        model_loader=lambda unused_path: object(),
        recognizer_loader=reject_recognizer,
    )

    assert report['delivery_ready'] is False
    assert report['grammar_probe']['attempted'] is True
    assert report['grammar_probe']['passed'] is False
    assert any('grammar construction failed' in issue
               for issue in report['blocking_issues'])


def test_intake_rejects_symlink_without_hashing_target(tmp_path):
    model = tmp_path / 'model'
    _write_plausible_model(model)
    outside = tmp_path / 'outside-secret.bin'
    outside.write_bytes(b'outside')
    link = model / 'outside-link.bin'
    try:
        link.symlink_to(outside)
    except OSError as error:
        pytest.skip('test environment cannot create symlink: {}'.format(
            error))

    report = intake.validate_local_vosk_model(
        model,
        model_loader=lambda unused_path: object(),
        recognizer_loader=lambda *unused: object(),
    )

    assert report['delivery_ready'] is False
    assert any('contains a symlink' in issue
               for issue in report['blocking_issues'])
    assert link.name not in {
        item['path'] for item in report['model']['inventory']['files']}


def test_cli_exclusively_creates_json_and_refuses_overwrite(
        tmp_path, capsys):
    model = tmp_path / 'model'
    _write_plausible_model(model)
    output = tmp_path / 'intake.json'
    loaders = {
        'model_loader': lambda unused_path: object(),
        'recognizer_loader': lambda *unused: object(),
    }

    first_code = intake.main([
        '--model-path', str(model), '--json-output', str(output),
    ], **loaders)
    first_payload = output.read_bytes()
    second_code = intake.main([
        '--model-path', str(model), '--json-output', str(output),
    ], **loaders)

    assert first_code == 0
    assert json.loads(first_payload)['delivery_ready'] is True
    assert second_code == 2
    assert output.read_bytes() == first_payload
    assert 'FileExistsError' in capsys.readouterr().err


def test_machine_schema_matches_report_identity(tmp_path):
    schema = json.loads(intake._schema_path().read_text(encoding='utf-8'))
    report = intake.validate_local_vosk_model(tmp_path / 'missing')
    compatibility_schema = dict(schema)
    compatibility_schema.pop('$schema')
    compatibility_schema.pop('$id')
    compatibility_schema['definitions'] = compatibility_schema.pop('$defs')

    def rewrite_local_references(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key == '$ref':
                    value[key] = item.replace(
                        '#/$defs/', '#/definitions/')
                else:
                    rewrite_local_references(item)
        elif isinstance(value, list):
            for item in value:
                rewrite_local_references(item)

    rewrite_local_references(compatibility_schema)

    Draft7Validator.check_schema(compatibility_schema)
    Draft7Validator(compatibility_schema).validate(report)
    assert schema['$id'] == report['schema_id']
    assert set(schema['required']) == set(report)
    assert schema['properties']['mode']['const'] == report['mode']
    assert report['validator']['artifacts']


def test_official_small_model_layout_accepts_text_boundaries_without_words(
        tmp_path):
    model = tmp_path / 'official-small-model'
    _write_plausible_model(model)
    (model / 'graph' / 'words.txt').unlink()
    (model / 'graph' / 'phones' / 'word_boundary.int').write_text(
        '1 nonword\n2 begin\n3 end\n4 internal\n5 singleton\n',
        encoding='utf-8',
    )

    report = intake.validate_local_vosk_model(
        model,
        model_loader=lambda unused_path: object(),
        recognizer_loader=lambda unused_model, unused_rate, unused_grammar: (
            object()),
    )

    validation = report['model']['validation']
    assert report['status'] == 'PASS'
    assert report['delivery_ready'] is True
    assert validation['static_ready'] is True
    assert validation['words_txt_present'] is False
    assert validation['word_boundary_present'] is True
    assert validation['issues'] == []


def test_official_small_model_layout_rejects_unknown_boundary_label(tmp_path):
    model = tmp_path / 'bad-boundary-model'
    _write_plausible_model(model)
    (model / 'graph' / 'words.txt').unlink()
    (model / 'graph' / 'phones' / 'word_boundary.int').write_text(
        '1 begin\n2 executable\n', encoding='utf-8')

    report = intake.validate_local_vosk_model(
        model,
        model_loader=lambda unused_path: object(),
        recognizer_loader=lambda unused_model, unused_rate, unused_grammar: (
            object()),
    )

    assert report['status'] == 'BLOCKED'
    assert report['delivery_ready'] is False
    assert 'Vosk graph/phones/word_boundary.int is invalid' in (
        report['blocking_issues'])

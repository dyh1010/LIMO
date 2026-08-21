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

"""ROS-free, endpoint-only ingress for the isolated STOP recognizer."""

from dataclasses import dataclass
import threading

from .semantic_agent import normalize_non_stop_semantics
from .voice_contract import validate_identifier


ENDPOINT_SOURCE = 'vosk_complete_endpoint'
REJECTED_PARTIAL_SOURCE = 'vosk_partial'


@dataclass(frozen=True)
class StopIngressDecision:
    """One inert ingress decision with no ROS or device side effects."""

    state: str
    reason: str
    stream_id: str
    segment_index: int
    stop_event: object = None
    actual_publish_count: int = 0
    production_publish_count: int = 0


class Ros1StopEndpointIngressCore:
    """Admit only explicit STOP from ordered complete ASR endpoints."""

    def __init__(
            self, adapter_core, max_context_segments=8, max_streams=64):
        if adapter_core is None \
                or not callable(getattr(
                    adapter_core, 'process_transcript', None)):
            raise ValueError('adapter_core must expose process_transcript')
        if not isinstance(max_context_segments, int) \
                or isinstance(max_context_segments, bool) \
                or not 1 <= max_context_segments <= 32:
            raise ValueError('max_context_segments must be in [1, 32]')
        if not isinstance(max_streams, int) \
                or isinstance(max_streams, bool) \
                or not 1 <= max_streams <= 1024:
            raise ValueError('max_streams must be in [1, 1024]')
        self._adapter_core = adapter_core
        self._max_context_segments = max_context_segments
        self._max_streams = max_streams
        self._streams = {}
        self._lock = threading.RLock()

    @staticmethod
    def _segment_index(value):
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError('segment_index must be a non-negative integer')
        return value

    @staticmethod
    def _text(value):
        if not isinstance(value, str):
            raise ValueError('endpoint text must be a string')
        text = value.strip()
        if not text or len(text) > 256:
            raise ValueError('endpoint text length is invalid')
        return text

    def _decision(self, state, reason, stream_id, segment_index, **values):
        return StopIngressDecision(
            state=state,
            reason=reason,
            stream_id=stream_id,
            segment_index=segment_index,
            **values
        )

    def reset_stream(self, stream_id):
        """Forget one stream without producing any output."""
        stream_id = validate_identifier(stream_id, 'stream_id')
        with self._lock:
            self._streams.pop(stream_id, None)

    def observe(
            self, stream_id, segment_index, source, text, now_ns=None):
        """Observe one ASR item and admit only a complete explicit STOP."""
        stream_id = validate_identifier(stream_id, 'stream_id')
        segment_index = self._segment_index(segment_index)
        text = self._text(text)
        if source == REJECTED_PARTIAL_SOURCE:
            return self._decision(
                'ignored_partial',
                'partial ASR is never authoritative for STOP',
                stream_id,
                segment_index,
            )
        if source != ENDPOINT_SOURCE:
            return self._decision(
                'ignored_source',
                'unreviewed ASR source is not authoritative for STOP',
                stream_id,
                segment_index,
            )

        with self._lock:
            stream = self._streams.get(stream_id)
            if stream is None:
                if len(self._streams) >= self._max_streams:
                    return self._decision(
                        'rejected_capacity',
                        'stream context capacity is exhausted',
                        stream_id,
                        segment_index,
                    )
                stream = {'next_index': 0, 'segments': []}
                self._streams[stream_id] = stream
            if segment_index != stream['next_index']:
                return self._decision(
                    'rejected_sequence',
                    'endpoint segment index is not the exact next index',
                    stream_id,
                    segment_index,
                )
            stream['next_index'] += 1
            stream['segments'].append(text)
            stream['segments'] = stream['segments'][
                -self._max_context_segments:]
            contextual_text = ' '.join(stream['segments'])
            if normalize_non_stop_semantics(contextual_text) is not None:
                return self._decision(
                    'ignored_non_stop',
                    'complete endpoint context is not an explicit STOP',
                    stream_id,
                    segment_index,
                )
            adapter = self._adapter_core.process_transcript(
                contextual_text, now_ns=now_ns)
            if adapter.state not in {
                    'priority_stop_internal', 'stop_debounced'} \
                    or adapter.intent != 'stop_task' \
                    or adapter.stop_event is None \
                    or adapter.actual_publish_count != 0 \
                    or adapter.production_publish_count != 0:
                raise RuntimeError('adapter violated STOP ingress contract')
            return self._decision(
                adapter.state,
                'complete endpoint admitted as explicit STOP',
                stream_id,
                segment_index,
                stop_event=adapter.stop_event,
            )

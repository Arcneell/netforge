"""Tests for the JSON-Schema cleanup applied before sending tool definitions
to Gemini.

The Gemini v1beta endpoint rejects most non-essential JSON-Schema keywords
(`additionalProperties`, `$schema`, `maxItems`, …) with a 400. The provider
strips them recursively before serialising the tool. These tests pin that
behaviour so a refactor of the keyword whitelist can't silently re-introduce
a 400 in production.
"""

from __future__ import annotations

from app.services.ai.providers.gemini import _clean_schema_for_gemini


def test_strips_unknown_keywords_at_root() -> None:
    schema = {
        "type": "object",
        "additionalProperties": False,
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": "MyThing",
        "properties": {"x": {"type": "integer", "minimum": 1}},
        "required": ["x"],
    }
    cleaned = _clean_schema_for_gemini(schema)
    assert "additionalProperties" not in cleaned
    assert "$schema" not in cleaned
    assert "title" not in cleaned
    # Whitelisted keywords stay.
    assert cleaned["type"] == "object"
    assert cleaned["properties"]["x"] == {"type": "integer", "minimum": 1}
    assert cleaned["required"] == ["x"]


def test_property_names_are_preserved_even_if_they_collide_with_a_keyword() -> None:
    """A field literally named "additionalProperties" must NOT be dropped — it
    is a property *name*, not a schema *keyword*. The cleanup must distinguish
    map values (schemas to clean) from map keys (free-form identifiers)."""
    schema = {
        "type": "object",
        "properties": {
            "additionalProperties": {"type": "boolean"},
            "items": {"type": "string"},
        },
        "required": ["additionalProperties"],
    }
    cleaned = _clean_schema_for_gemini(schema)
    assert "additionalProperties" in cleaned["properties"]
    assert cleaned["properties"]["additionalProperties"] == {"type": "boolean"}
    assert cleaned["properties"]["items"] == {"type": "string"}


def test_strips_maxitems_at_multiple_nesting_levels() -> None:
    """The advisor tool has `maxItems` on the outer array AND on the inner
    `affected_entities` array — that exact shape was the regression that lead
    to the strip-everything-not-whitelisted approach."""
    schema = {
        "type": "object",
        "properties": {
            "insights": {
                "type": "array",
                "maxItems": 20,
                "items": {
                    "type": "object",
                    "properties": {
                        "affected_entities": {
                            "type": "array",
                            "maxItems": 20,
                            "items": {"type": "object"},
                        }
                    },
                },
            }
        },
    }
    cleaned = _clean_schema_for_gemini(schema)
    arr = cleaned["properties"]["insights"]
    assert "maxItems" not in arr
    inner_arr = arr["items"]["properties"]["affected_entities"]
    assert "maxItems" not in inner_arr


def test_recurses_through_items() -> None:
    schema = {
        "type": "array",
        "items": {
            "type": "object",
            "additionalProperties": False,
            "properties": {"id": {"type": "integer"}},
        },
    }
    cleaned = _clean_schema_for_gemini(schema)
    assert "additionalProperties" not in cleaned["items"]
    assert cleaned["items"]["properties"]["id"] == {"type": "integer"}


# --- Streaming -------------------------------------------------------------


import pytest

from app.services.ai.providers.gemini import GeminiProvider
from app.services.ai.types import StreamDelta, StreamDone


class _FakeStream:
    def __init__(self, chunks):
        self._chunks = list(chunks)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._chunks:
            raise StopAsyncIteration
        return self._chunks.pop(0)


@pytest.mark.asyncio
async def test_gemini_stream_yields_one_delta_per_chunk(monkeypatch) -> None:
    """Regression for the 'Gemini pops the whole answer at once' bug: the
    streaming path now iterates `generate_content_stream` chunks and
    forwards each as a `StreamDelta`. With three text chunks from the SDK
    we expect three deltas + one terminating `done`."""
    from types import SimpleNamespace

    chunks = [
        SimpleNamespace(text="Hello", usage_metadata=None, candidates=[]),
        SimpleNamespace(text=" world", usage_metadata=None, candidates=[]),
        SimpleNamespace(
            text="!",
            usage_metadata=SimpleNamespace(prompt_token_count=12, candidates_token_count=3),
            candidates=[],
        ),
    ]

    fake_client = SimpleNamespace()
    fake_client.aio = SimpleNamespace()
    fake_client.aio.models = SimpleNamespace()

    async def fake_stream(**_kwargs):
        return _FakeStream(chunks)

    fake_client.aio.models.generate_content_stream = fake_stream

    fake_gtypes = SimpleNamespace(GenerateContentConfig=lambda **kw: kw)

    provider = GeminiProvider.__new__(GeminiProvider)
    provider._api_key = "k"
    provider.model = "gemini-test"
    provider._client = fake_client
    provider._gtypes = fake_gtypes

    events = []
    async for ev in provider.stream_call(system="sys", prompt="hi"):
        events.append(ev)

    # 3 deltas + 1 done
    assert len(events) == 4
    assert all(isinstance(e, StreamDelta) for e in events[:3])
    assert [e.text for e in events[:3]] == ["Hello", " world", "!"]
    final = events[-1]
    assert isinstance(final, StreamDone)
    assert final.text == "Hello world!"
    assert final.usage.prompt_tokens == 12
    assert final.usage.completion_tokens == 3

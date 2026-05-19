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

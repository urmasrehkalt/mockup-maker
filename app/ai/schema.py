"""Turn a Pydantic response model into a schema for `codex exec --output-schema`.

Structured output in strict mode wants every property listed in `required`,
`additionalProperties: false` on every object, and only a subset of JSON Schema
keywords. Anything dropped here (lengths, patterns, defaults) is still enforced,
because the answer is validated against the Pydantic model on the server.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel

KEPT_KEYWORDS = {
    "type", "properties", "required", "additionalProperties", "items", "enum",
    "anyOf", "$ref", "$defs", "description", "minItems", "maxItems",
}


def strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    return _strict(model.model_json_schema())


def _strict(node: Any) -> Any:
    if isinstance(node, list):
        return [_strict(item) for item in node]
    if not isinstance(node, dict):
        return node
    if "const" in node:
        node = {**node, "enum": [node["const"]]}
    out = {key: _strict(value) for key, value in node.items() if key in KEPT_KEYWORDS}
    if "properties" in node:
        out["properties"] = {name: _strict(sub) for name, sub in node["properties"].items()}
        out["required"] = list(node["properties"])
        out["additionalProperties"] = False
    if "$defs" in node:
        out["$defs"] = {name: _strict(sub) for name, sub in node["$defs"].items()}
    return out

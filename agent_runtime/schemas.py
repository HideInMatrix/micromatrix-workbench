"""Reusable MCP JSON schema helpers and validation.

Tool definitions live under :mod:`agent_runtime.tools`; this module only
owns schema building blocks and validation shared by the framework.
"""

from __future__ import annotations

from typing import Any


def obj(
    properties: dict[str, Any] | None = None,
    required: tuple[str, ...] = (),
    *,
    additional: bool | dict[str, Any] = False,
) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties or {},
        "required": list(required),
        "additionalProperties": additional,
    }


S = {"type": "string"}
I = {"type": "integer"}
B = {"type": "boolean"}
SA = {"type": "array", "items": {"type": "string"}}


def output_schema() -> dict[str, Any]:
    return obj(
        {
            "ok": {"type": "boolean"},
            "error": obj(
                {
                    "code": {"type": "string"},
                    "message": {"type": "string"},
                    "category": {"type": "string"},
                    "retryable": {"type": "boolean"},
                    "details": {"type": "object", "additionalProperties": True},
                },
                ("code", "message", "category", "retryable", "details"),
                additional=True,
            ),
        },
        ("ok",),
        additional=True,
    )


EXEC_COMMON = {
    "max_output_bytes": {**I, "minimum": 1, "maximum": 1_048_576, "default": 65_536},
    "verbosity": {**S, "enum": ["summary", "preview", "full"]},
    "preview_bytes": {**I, "minimum": 1, "maximum": 1_048_576, "default": 4_096},
}


def validate_value(value: Any, schema: dict[str, Any], path: str = "arguments") -> None:
    if "const" in schema and value != schema["const"]:
        raise ValueError(f"{path} must equal {schema['const']!r}")

    one_of = schema.get("oneOf")
    if isinstance(one_of, list):
        matches = 0
        errors: list[str] = []
        for branch in one_of:
            if not isinstance(branch, dict):
                continue
            try:
                validate_value(value, branch, path)
            except ValueError as exc:
                errors.append(str(exc))
            else:
                matches += 1
        if matches != 1:
            if matches == 0 and errors:
                raise ValueError(
                    f"{path} does not match exactly one allowed shape: "
                    + "; ".join(errors[:3])
                )
            raise ValueError(f"{path} must match exactly one allowed shape")
        return

    expected = schema.get("type")
    if expected == "object":
        if not isinstance(value, dict):
            raise ValueError(f"{path} must be an object")
        for key in schema.get("required", []):
            if key not in value:
                raise ValueError(f"{path}.{key} is required")
        props = schema.get("properties", {})
        additional = schema.get("additionalProperties", True)
        for key, item in value.items():
            child = props.get(key)
            if child is None:
                if additional is False:
                    raise ValueError(f"{path}.{key} is not allowed")
                if isinstance(additional, dict):
                    validate_value(item, additional, f"{path}.{key}")
            else:
                validate_value(item, child, f"{path}.{key}")
        return
    if expected == "array":
        if not isinstance(value, list):
            raise ValueError(f"{path} must be an array")
        if "minItems" in schema and len(value) < int(schema["minItems"]):
            raise ValueError(f"{path} has too few items")
        if "maxItems" in schema and len(value) > int(schema["maxItems"]):
            raise ValueError(f"{path} has too many items")
        child = schema.get("items")
        if isinstance(child, dict):
            for index, item in enumerate(value):
                validate_value(item, child, f"{path}[{index}]")
        return
    if expected == "string":
        if not isinstance(value, str):
            raise ValueError(f"{path} must be a string")
        if len(value) < int(schema.get("minLength", 0)):
            raise ValueError(f"{path} is too short")
        if "maxLength" in schema and len(value) > int(schema["maxLength"]):
            raise ValueError(f"{path} is too long")
    elif expected == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{path} must be an integer")
        if "minimum" in schema and value < schema["minimum"]:
            raise ValueError(f"{path} is below the minimum")
        if "maximum" in schema and value > schema["maximum"]:
            raise ValueError(f"{path} is above the maximum")
    elif expected == "boolean" and not isinstance(value, bool):
        raise ValueError(f"{path} must be a boolean")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{path} must be one of {schema['enum']}")

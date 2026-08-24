from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Iterable

from .effective_tools import EffectiveTool
from .skills import SkillDefinition
from .workflows import WorkflowDefinition


CAPABILITY_ID_PATTERN = re.compile(
    r"^(?:system:[a-zA-Z0-9_.-]+|skill:[a-zA-Z0-9_.-]+|workflow:[a-zA-Z0-9_.-]+|mcp:[a-zA-Z0-9_.-]+:[a-zA-Z0-9_.-]+)$"
)


def is_valid_capability_id(value: str) -> bool:
    return bool(CAPABILITY_ID_PATTERN.fullmatch(str(value).strip()))


def capability_catalog_revision(capabilities: Iterable[dict[str, Any]]) -> str:
    payload = json.dumps(
        list(capabilities),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def validate_capability_references(
    references: Iterable[str],
    *,
    available_ids: Iterable[str],
) -> tuple[str, ...]:
    available = set(available_ids)
    invalid: list[str] = []
    for reference in references:
        value = str(reference).strip()
        if not is_valid_capability_id(value) or value not in available:
            invalid.append(value)
    return tuple(invalid)


def build_capability_catalog(
    *,
    tools: Iterable[EffectiveTool],
    skills: Iterable[SkillDefinition],
    workflows: Iterable[WorkflowDefinition],
) -> tuple[dict[str, Any], ...]:
    """Build the AI-facing capability catalog.

    The catalog is descriptive rather than prescriptive: it tells the AI client
    which capabilities exist and how they can be invoked, but it never performs
    intent routing or selects a capability on the client's behalf.
    """

    values: list[dict[str, Any]] = []
    tool_by_key = {tool.key: tool for tool in tools}

    for tool in tools:
        source: dict[str, Any] = {"provider": tool.provider}
        if tool.provider == "mcp":
            source.update(
                {
                    "connection_id": tool.connection_id,
                    "connection_name": tool.connection_name,
                }
            )
        values.append(
            {
                "id": tool.key,
                "type": "mcp_tool" if tool.provider == "mcp" else "builtin_tool",
                "name": tool.tool_name,
                "description": tool.description,
                "input_schema": dict(tool.input_schema),
                "source": source,
                "availability": {
                    "status": (
                        "degraded"
                        if tool.provider == "mcp" and bool(tool.connection_last_error)
                        else "available"
                    ),
                    "reasons": (
                        [{"code": "MCP_CONNECTION_LAST_ERROR", "message": tool.connection_last_error}]
                        if tool.provider == "mcp" and tool.connection_last_error
                        else []
                    ),
                },
                "execution": {
                    "owner": "external_mcp" if tool.provider == "mcp" else "workbench_runtime",
                    "required_capabilities": list(tool.required_capabilities),
                    "required_operation_permissions": list(tool.required_operation_permissions),
                    "annotations": dict(tool.annotations),
                    "permission_boundary": "runtime_permission_profile",
                    "approval_boundary": "permission_broker_when_required",
                },
                "invocation": {
                    "mcp_tool": "mcp_connection_manage" if tool.provider == "mcp" else tool.tool_name,
                    "arguments": (
                        {
                            "action": "call_tool",
                            "connection_id": tool.connection_id,
                            "tool_name": tool.tool_name,
                            "arguments": "<capability input>",
                        }
                        if tool.provider == "mcp"
                        else "<capability input>"
                    ),
                },
            }
        )

    for skill in skills:
        skill_dependencies = [
            {
                "capability_id": capability_id,
                "relation": "recommended",
                "required": False,
            }
            for capability_id in skill.recommended_capabilities
        ]
        values.append(
            {
                "id": f"skill:{skill.id}",
                "type": "skill",
                "name": skill.name,
                "description": skill.description,
                "usage_hint": skill.usage_hint,
                "recommended_capabilities": list(skill.recommended_capabilities),
                "dependencies": skill_dependencies,
                "input_schema": {"type": "object", "additionalProperties": True},
                "source": {"scope": skill.scope.value, "skill_id": skill.id},
                "availability": {"status": "available", "reasons": []},
                "execution": {
                    "owner": "ai_client",
                    "required_capabilities": [],
                    "required_operation_permissions": [],
                    "annotations": {
                        "read_only": True,
                        "destructive": False,
                        "idempotent": True,
                        "open_world": False,
                    },
                    "permission_boundary": "selected_capabilities",
                    "approval_boundary": "inherited_from_selected_capabilities",
                },
                "invocation": {
                    "mcp_tool": "skill_manage",
                    "arguments": {"action": "get", "skill_id": skill.id},
                    "execution_owner": "ai_client",
                },
            }
        )

    for workflow in workflows:
        has_approval = any(node.type == "approval" for node in workflow.nodes)
        workflow_tools: list[EffectiveTool] = []
        for node in workflow.nodes:
            if node.type != "tool":
                continue
            provider = str(node.config.get("provider") or "system")
            tool_name = str(node.config.get("tool_name") or "")
            if provider == "mcp":
                connection_id = str(node.config.get("connection_id") or "")
                key = f"mcp:{connection_id}:{tool_name}"
            else:
                key = f"system:{tool_name}"
            tool = tool_by_key.get(key)
            if tool is not None:
                workflow_tools.append(tool)
        required_capabilities = sorted(
            {
                capability
                for tool in workflow_tools
                for capability in tool.required_capabilities
            }
        )
        dependency_by_id: dict[str, dict[str, Any]] = {}
        for tool in workflow_tools:
            dependency_by_id[tool.key] = {
                "capability_id": tool.key,
                "relation": "workflow_tool",
                "required": True,
            }
        for node in workflow.nodes:
            if node.type != "skill":
                continue
            skill_id = str(node.config.get("skill_id") or "").strip()
            if not skill_id:
                continue
            capability_id = f"skill:{skill_id}"
            dependency_by_id[capability_id] = {
                "capability_id": capability_id,
                "relation": "workflow_skill",
                "required": True,
            }
        required_operation_permissions = sorted(
            {
                permission
                for tool in workflow_tools
                for permission in tool.required_operation_permissions
            }
        )
        has_tool = bool(workflow_tools)
        all_read_only = bool(workflow_tools) and all(
            tool.annotations.get("read_only", False) for tool in workflow_tools
        )
        destructive = any(
            tool.annotations.get("destructive", False) for tool in workflow_tools
        )
        open_world = any(
            tool.annotations.get("open_world", False) for tool in workflow_tools
        )
        values.append(
            {
                "id": f"workflow:{workflow.id}",
                "type": "workflow",
                "name": workflow.name,
                "description": workflow.description,
                "input_schema": dict(workflow.inputs_schema),
                "tags": list(workflow.tags),
                "dependencies": list(dependency_by_id.values()),
                "source": {"scope": workflow.scope.value, "workflow_id": workflow.id},
                "availability": {"status": "available", "reasons": []},
                "execution": {
                    "owner": "workflow_runtime",
                    "required_capabilities": required_capabilities,
                    "required_operation_permissions": required_operation_permissions,
                    "annotations": {
                        "read_only": not has_tool or all_read_only,
                        "destructive": destructive,
                        "idempotent": False,
                        "open_world": open_world,
                    },
                    "permission_boundary": "per_node_runtime_permissions",
                    "approval_boundary": "workflow_approval_nodes" if has_approval else "none_declared",
                },
                "invocation": {
                    "mcp_tool": "workflow_run",
                    "arguments": {
                        "action": "start",
                        "workflow_id": workflow.id,
                        "inputs": "<capability input>",
                    },
                },
            }
        )

    ordered = list(sorted(values, key=lambda item: (str(item["type"]), str(item["id"]))))
    available_ids = {str(item["id"]) for item in ordered}
    by_id = {str(item["id"]): item for item in ordered}
    for item in ordered:
        item.setdefault("dependencies", [])
        item["dependents"] = []
    for item in ordered:
        source_id = str(item["id"])
        for dependency in item.get("dependencies", []):
            target_id = str(dependency.get("capability_id") or "")
            target = by_id.get(target_id)
            if target is None:
                continue
            target["dependents"].append(
                {
                    "capability_id": source_id,
                    "relation": dependency.get("relation", "depends_on"),
                    "required": bool(dependency.get("required", False)),
                }
            )
    for item in ordered:
        if item.get("type") != "skill":
            continue
        recommended = [str(value) for value in item.get("recommended_capabilities", [])]
        unresolved = [value for value in recommended if value not in available_ids]
        item["recommended_capability_status"] = {
            "resolved": [value for value in recommended if value in available_ids],
            "unresolved": unresolved,
            "ok": not unresolved,
        }
        if unresolved:
            item["availability"] = {
                "status": "degraded",
                "reasons": [
                    {
                        "code": "RECOMMENDED_CAPABILITY_UNRESOLVED",
                        "capability_ids": unresolved,
                    }
                ],
            }
    for item in ordered:
        missing_required = [
            str(dependency.get("capability_id") or "")
            for dependency in item.get("dependencies", [])
            if dependency.get("required")
            and str(dependency.get("capability_id") or "") not in available_ids
        ]
        if missing_required:
            item["availability"] = {
                "status": "unavailable",
                "reasons": [
                    {
                        "code": "REQUIRED_CAPABILITY_UNRESOLVED",
                        "capability_ids": missing_required,
                    }
                ],
            }
    return tuple(ordered)


def filter_capability_catalog(
    capabilities: Iterable[dict[str, Any]],
    *,
    types: Iterable[str] = (),
    query: str = "",
) -> tuple[dict[str, Any], ...]:
    allowed_types = {str(item).strip() for item in types if str(item).strip()}
    normalized_query = query.strip().lower()
    values: list[dict[str, Any]] = []
    for capability in capabilities:
        if allowed_types and str(capability.get("type")) not in allowed_types:
            continue
        if normalized_query:
            haystack = " ".join(
                str(capability.get(key) or "")
                for key in ("id", "type", "name", "description", "usage_hint")
            ).lower()
            tags = " ".join(str(item) for item in capability.get("tags", []))
            if normalized_query not in f"{haystack} {tags.lower()}":
                continue
        values.append(capability)
    return tuple(values)

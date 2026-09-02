from __future__ import annotations

from typing import Any


class WorkbenchAPI:
    """Workbench target, capability, MCP connection, Skill and Workflow APIs."""

    def list_workbench_targets(self) -> list[dict[str, object]]:
        return [item.to_dict() for item in self.workbench_manager.targets()]

    def get_workbench_catalog(self, target_id: str) -> dict[str, object]:
        return self.workbench_manager.catalog(str(target_id))

    def get_workbench_capability_catalog(self) -> dict[str, object]:
        return self.workbench_manager.capability_catalog()

    def get_workbench_mcp_connection(self, connection_id: str) -> dict[str, object]:
        return self.workbench_manager.get_mcp_connection(str(connection_id))

    def validate_workbench_mcp_connection(
        self,
        connection: dict[str, Any],
    ) -> dict[str, object]:
        return self.workbench_manager.validate_mcp_connection(connection)

    def save_workbench_mcp_connection(
        self,
        connection: dict[str, Any],
        expected_version: int,
    ) -> dict[str, object]:
        return self.workbench_manager.save_mcp_connection(
            connection,
            expected_version=int(expected_version),
        )

    def delete_workbench_mcp_connection(self, connection_id: str) -> bool:
        return self.workbench_manager.delete_mcp_connection(str(connection_id))

    def test_workbench_mcp_connection(
        self,
        connection_id: str,
        timeout_seconds: int = 8,
    ) -> dict[str, object]:
        return self.workbench_manager.test_mcp_connection(
            str(connection_id),
            timeout_seconds=int(timeout_seconds),
        )

    def discover_workbench_mcp_connection_tools(
        self,
        connection_id: str,
        timeout_seconds: int = 8,
    ) -> dict[str, object]:
        return self.workbench_manager.discover_mcp_connection_tools(
            str(connection_id),
            timeout_seconds=int(timeout_seconds),
        )

    def get_workbench_skill(self, skill_id: str) -> dict[str, object]:
        return self.workbench_manager.get_skill(str(skill_id))

    def validate_workbench_skill(
        self,
        skill: dict[str, Any],
    ) -> dict[str, object]:
        return self.workbench_manager.validate_skill(skill)

    def save_workbench_skill(
        self,
        skill: dict[str, Any],
        expected_version: int,
    ) -> dict[str, object]:
        return self.workbench_manager.save_skill(
            skill,
            expected_version=int(expected_version),
        )

    def delete_workbench_skill(self, skill_id: str) -> bool:
        return self.workbench_manager.delete_skill(str(skill_id))

    def get_workbench_workflow(
        self,
        target_id: str,
        workflow_id: str,
    ) -> dict[str, object]:
        return self.workbench_manager.get_workflow(
            str(target_id),
            str(workflow_id),
        )

    def validate_workbench_workflow(
        self,
        target_id: str,
        workflow: dict[str, Any],
    ) -> dict[str, object]:
        return self.workbench_manager.validate_workflow(str(target_id), workflow)

    def save_workbench_workflow(
        self,
        target_id: str,
        workflow: dict[str, Any],
        expected_version: int,
    ) -> dict[str, object]:
        return self.workbench_manager.save_workflow(
            str(target_id),
            workflow,
            expected_version=int(expected_version),
        )

    def delete_workbench_workflow(self, target_id: str, workflow_id: str) -> bool:
        return self.workbench_manager.delete_workflow(
            str(target_id),
            str(workflow_id),
        )

    def list_workbench_runs(self, target_id: str) -> list[dict[str, object]]:
        return self.workbench_manager.runs(str(target_id))


__all__ = ["WorkbenchAPI"]

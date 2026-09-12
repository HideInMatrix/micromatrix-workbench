from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from threading import RLock

from agent_runtime.toolchains.registration import fingerprint, register_toolchain

_REGISTRATION_LOCK = RLock()


class ApprovalAPI:
    """Permission Broker and workflow approval bridge methods."""

    def list_permission_requests(self) -> list[dict[str, object]]:
        requests = self.permission_broker.pending()
        names = {profile.server_id: profile.name for profile in self.store.list()}
        payload = [
            {
                **item,
                "server_name": names.get(
                    str(item.get("server_id") or ""),
                    "MCP Server",
                ),
            }
            for item in requests
        ]
        request_id = str(payload[0].get("request_id") or "") if payload else ""
        if request_id and request_id != self._permission_attention_id:
            self._permission_attention_id = request_id
            window = self._window
            if window is not None:
                try:
                    window.show()
                    window.restore()
                except Exception:
                    pass
        elif not request_id:
            self._permission_attention_id = ""
        return payload

    def respond_permission_request(
        self,
        request_id: str,
        decision: str | bool,
    ) -> bool:
        if decision != "remember":
            return self.permission_broker.respond(str(request_id), decision)
        # A separate, explicit persistent decision: session-all never grants registration.
        with _REGISTRATION_LOCK:
            item = next((r for r in self.permission_broker.pending()
                         if r["request_id"] == request_id), None)
            if not item or item["permission"] != "toolchain_registration":
                return False
            proposal = item["arguments"]
            server_id = item["server_id"]
            profile = self.store.get(server_id)
            if profile is None:
                raise ValueError("发起请求的 Work 已删除或未参与运行。")
            if str(profile.workspace.resolve()) != proposal.get("workspace"):
                raise ValueError("运行目录与保存的 Work 不一致，请先保存 Work 配置。")
            displayed_fingerprint = str(proposal.get("proposal_fingerprint") or "")
            if not displayed_fingerprint or fingerprint(
                str(proposal["executable"]),
                list(proposal["read_roots"]),
            ) != displayed_fingerprint:
                raise ValueError("工具在授权确认前已发生变化，请重新发起工具请求。")
            record = register_toolchain(
                proposal["program"],
                proposal["executable"],
                proposal["read_roots"],
                confirmed_roots=proposal["read_roots"],
                project_context=(
                    proposal.get("project_context")
                    if isinstance(proposal.get("project_context"), dict)
                    else None
                ),
            )
            # Reload after fingerprinting so a concurrent profile edit cannot be overwritten.
            current = self.store.get(server_id)
            if current is None or current.workspace != profile.workspace:
                raise ValueError("Work 已变化，请重新发起工具请求。")
            records = tuple(r for r in current.toolchains if r["program"] != record["program"]) + (record,)
            updated = replace(current, toolchains=records)
            self.store.save(updated)
            return self.permission_broker.respond(request_id, "remember", registration=record)

    def list_resource_authorizations(self) -> list[dict[str, object]]:
        rules = self.permission_broker.resource_authorizations.list()
        names = {profile.server_id: profile.name for profile in self.store.list()}
        return [
            {
                **item,
                "server_name": names.get(str(item.get("server_id") or ""), "MCP Server"),
            }
            for item in rules
        ]

    def revoke_resource_authorization(self, rule_id: str) -> bool:
        return self.permission_broker.resource_authorizations.revoke(str(rule_id))

    def stop_all_desktop_input(self) -> dict[str, object]:
        server_ids = {profile.server_id for profile in self.store.list()}
        results = {
            server_id: bool(self.permission_broker.stop_desktop_input(server_id))
            for server_id in sorted(server_ids)
        }
        return {
            "requested": len(results),
            "stopped": sum(1 for value in results.values() if value),
            "results": results,
        }

    def list_workflow_approvals(self) -> list[dict[str, object]]:
        requests = self.permission_broker.pending_workflow_approvals()
        names = {profile.server_id: profile.name for profile in self.store.list()}
        payload = [
            {
                **item,
                "server_name": names.get(
                    str(item.get("server_id") or ""),
                    "MCP Server",
                ),
            }
            for item in requests
        ]
        request_id = str(payload[0].get("request_id") or "") if payload else ""
        if request_id and request_id != self._workflow_approval_attention_id:
            self._workflow_approval_attention_id = request_id
            window = self._window
            if window is not None:
                try:
                    window.show()
                    window.restore()
                except Exception:
                    pass
        elif not request_id:
            self._workflow_approval_attention_id = ""
        return payload

    def respond_workflow_approval(self, request_id: str, approved: bool) -> bool:
        return self.permission_broker.respond_workflow_approval(
            str(request_id),
            bool(approved),
        )


__all__ = ["ApprovalAPI"]

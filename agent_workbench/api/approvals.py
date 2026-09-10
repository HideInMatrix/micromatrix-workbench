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
        for gateway in self.gateway_store.list():
            names.update(
                {member.server_id: member.name for member in gateway.members}
            )
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
            gateway = None
            if profile is None:
                gateway = next((g for g in self.gateway_store.list()
                                if any(m.server_id == server_id for m in g.runtime_members)), None)
                if gateway is not None:
                    profile = next(m for m in gateway.runtime_members if m.server_id == server_id)
            if profile is None:
                raise ValueError("发起请求的 Profile 已删除或未参与运行。")
            if str(profile.workspace.resolve()) != proposal.get("workspace"):
                raise ValueError("运行 Workspace 与保存的 Profile 不一致，请先保存服务配置。")
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
            if gateway is None:
                current = self.store.get(server_id)
            else:
                gateway = self.gateway_store.get(gateway.gateway_id)
                current = next((m for m in gateway.runtime_members if m.server_id == server_id), None) if gateway else None
            if current is None or current.workspace != profile.workspace:
                raise ValueError("Profile 已变化，请重新发起工具请求。")
            records = tuple(r for r in current.toolchains if r["program"] != record["program"]) + (record,)
            updated = replace(current, toolchains=records)
            if gateway is None:
                self.store.save(updated)
            else:
                self.gateway_store.save(replace(gateway, members=tuple(
                    updated if m.server_id == server_id else m for m in gateway.members)))
            return self.permission_broker.respond(request_id, "remember", registration=record)

    def list_workflow_approvals(self) -> list[dict[str, object]]:
        requests = self.permission_broker.pending_workflow_approvals()
        names = {profile.server_id: profile.name for profile in self.store.list()}
        for gateway in self.gateway_store.list():
            names.update(
                {member.server_id: member.name for member in gateway.members}
            )
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

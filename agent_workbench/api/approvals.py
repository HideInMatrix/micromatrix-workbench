from __future__ import annotations


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
        return self.permission_broker.respond(str(request_id), decision)

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

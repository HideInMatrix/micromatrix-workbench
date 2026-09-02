from __future__ import annotations


class OAuthAPI:
    """Server and Gateway OAuth client query/revocation bridge methods."""

    def list_oauth_clients(self, server_id: str) -> list[dict[str, object]]:
        return [
            {
                "client_id": client.client_id,
                "client_name": client.client_name or "未命名客户端",
                "redirect_uris": list(client.redirect_uris),
                "token_endpoint_auth_method": client.token_endpoint_auth_method,
                "issued_at": client.issued_at,
                "client_type": client.client_type,
                "revocable": client.revocable,
            }
            for client in self.manager.oauth_clients(server_id)
        ]

    def list_gateway_oauth_clients(
        self,
        gateway_id: str,
        server_id: str,
    ) -> list[dict[str, object]]:
        return [
            {
                "client_id": client.client_id,
                "client_name": client.client_name or "未命名客户端",
                "redirect_uris": list(client.redirect_uris),
                "token_endpoint_auth_method": client.token_endpoint_auth_method,
                "issued_at": client.issued_at,
                "client_type": client.client_type,
                "revocable": client.revocable,
            }
            for client in self.gateway_manager.oauth_clients(gateway_id, server_id)
        ]

    def revoke_oauth_client(self, server_id: str, client_id: str) -> bool:
        return self.manager.remove_oauth_client(server_id, client_id)

    def revoke_all_oauth_clients(self, server_id: str) -> int:
        return self.manager.clear_oauth_clients(server_id)

    def revoke_gateway_oauth_client(
        self,
        gateway_id: str,
        server_id: str,
        client_id: str,
    ) -> bool:
        return self.gateway_manager.remove_oauth_client(
            gateway_id,
            server_id,
            client_id,
        )

    def revoke_all_gateway_oauth_clients(
        self,
        gateway_id: str,
        server_id: str,
    ) -> int:
        return self.gateway_manager.clear_oauth_clients(gateway_id, server_id)


__all__ = ["OAuthAPI"]

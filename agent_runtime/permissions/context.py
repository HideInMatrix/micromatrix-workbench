from __future__ import annotations

import contextvars


ACTIVE_PERMISSIONS: contextvars.ContextVar[frozenset[str]] = contextvars.ContextVar(
    "agent_runtime_active_permissions",
    default=frozenset(),
)

# A resource-session approval may authorize creation of a resource whose final
# ID does not exist until the Host action succeeds (for example browser_open).
# The handler must return a matching private ``_authorization_session`` marker
# before Runtime materializes the grant; failures never create a grant.
ACTIVE_RESOURCE_SESSION_CREATION: contextvars.ContextVar[tuple[str, str] | None] = (
    contextvars.ContextVar(
        "agent_runtime_resource_session_creation",
        default=None,
    )
)


__all__ = ["ACTIVE_PERMISSIONS", "ACTIVE_RESOURCE_SESSION_CREATION"]

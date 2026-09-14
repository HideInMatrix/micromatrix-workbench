from __future__ import annotations

import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

_LOG = Path('/Users/micromatrix/Documents/Project/micromatrix-workbench/.build-meta/host-validation-runtime.log')

def _write(message: str) -> None:
    try:
        _LOG.parent.mkdir(parents=True, exist_ok=True)
        with _LOG.open("a", encoding="utf-8") as stream:
            stream.write(f"{datetime.now(timezone.utc).isoformat()} {message}\n")
    except OSError:
        pass

_write(f"boot argv={sys.argv!r} frozen={bool(getattr(sys, 'frozen', False))} meipass={getattr(sys, '_MEIPASS', '')!s}")

_original_excepthook = sys.excepthook
def _excepthook(exc_type, exc, tb):
    _write("uncaught " + "".join(traceback.format_exception(exc_type, exc, tb)).replace("\n", " | "))
    _original_excepthook(exc_type, exc, tb)
sys.excepthook = _excepthook

try:
    from agent_workbench.runtime import supervisor as _supervisor
    _original_ensure_running = _supervisor.RuntimeSupervisorClient._ensure_running
    _original_shutdown_incompatible = _supervisor.RuntimeSupervisorClient._shutdown_incompatible

    def _shutdown_incompatible(self, health):
        _write(f"shutdown_incompatible current_owner={health.get('owner')} client_owner={self.owner} generation={health.get('generation')}")
        try:
            return _original_shutdown_incompatible(self, health)
        except Exception as exc:
            _write(f"shutdown_incompatible failed {type(exc).__name__}: {exc}")
            raise
        finally:
            _write("shutdown_incompatible finished")

    def _ensure_running(self):
        raw = self._read_health(require_owner=False)
        _write(f"ensure_running before current_owner={raw.get('owner') if raw else None} client_owner={self.owner} generation={raw.get('generation') if raw else None}")
        try:
            result = _original_ensure_running(self)
        except Exception as exc:
            _write(f"ensure_running failed {type(exc).__name__}: {exc}")
            raise
        _write(f"ensure_running after owner={result.get('owner')} generation={result.get('generation')}")
        return result

    _supervisor.RuntimeSupervisorClient._shutdown_incompatible = _shutdown_incompatible
    _supervisor.RuntimeSupervisorClient._ensure_running = _ensure_running
    _write("supervisor diagnostics installed")
except Exception as exc:
    _write(f"diagnostic install failed {type(exc).__name__}: {exc}")

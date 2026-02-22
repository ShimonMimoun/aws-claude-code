"""
Login web : flow Entra (device code) côté serveur pour la page /login.
Sessions en mémoire : session_id -> { status, token?, message? }.
"""
import uuid
from typing import Any

try:
    import msal
except ImportError:
    msal = None  # type: ignore

from config import settings

_login_sessions: dict[str, dict[str, Any]] = {}


def _run_entra_device_flow(session_id: str, flow: dict[str, Any]) -> None:
    if not msal:
        _login_sessions[session_id] = {"status": "error", "error": "msal non installé"}
        return
    tenant = settings.entra_tenant_id
    client_id = settings.entra_client_id
    if not tenant or not client_id:
        _login_sessions[session_id] = {"status": "error", "error": "Entra non configuré"}
        return
    authority = f"https://login.microsoftonline.com/{tenant}"
    app = msal.PublicClientApplication(client_id=client_id, authority=authority)
    result = app.acquire_token_by_device_flow(flow)
    if result.get("id_token"):
        _login_sessions[session_id] = {"status": "done", "token": result["id_token"]}
    else:
        _login_sessions[session_id] = {
            "status": "error",
            "error": result.get("error_description") or str(result),
        }


def start_entra_login() -> dict[str, Any]:
    """Lance le device flow Entra, retourne session_id + message pour l'utilisateur."""
    if not msal:
        return {"error": "msal non installé"}
    tenant = settings.entra_tenant_id
    client_id = settings.entra_client_id
    if not tenant or not client_id:
        return {"error": "entra_tenant_id et entra_client_id requis dans .env"}
    authority = f"https://login.microsoftonline.com/{tenant}"
    app = msal.PublicClientApplication(client_id=client_id, authority=authority)
    flow = app.initiate_device_flow(scopes=["openid", "profile", "email"])
    if "user_code" not in flow:
        return {"error": flow.get("error_description", "Impossible de démarrer le device flow")}
    session_id = str(uuid.uuid4())
    _login_sessions[session_id] = {"status": "pending", "message": flow.get("message", "")}
    import threading
    thread = threading.Thread(target=_run_entra_device_flow, args=(session_id, flow))
    thread.daemon = True
    thread.start()
    return {
        "session_id": session_id,
        "message": flow.get("message", ""),
        "verification_uri": flow.get("verification_uri", "https://microsoft.com/devicelogin"),
        "user_code": flow.get("user_code", ""),
    }


def poll_entra_login(session_id: str) -> dict[str, Any]:
    """État du login : pending | done | error."""
    data = _login_sessions.get(session_id)
    if not data:
        return {"status": "error", "error": "Session inconnue ou expirée"}
    return {"status": data["status"], **{k: v for k, v in data.items() if k != "status"}}

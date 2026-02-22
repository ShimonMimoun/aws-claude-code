"""
Exécution d'appels AWS via le profil forgé (session).
Toutes les requêtes passent par ce module → tout transite par notre proxy.
"""
import base64
from typing import Any, Optional
from .credentials import get_cached_aws_session
from config import settings


# Services dont le nom boto3 diffère (ex: bedrock-runtime)
SERVICE_ALIASES = {
    "bedrock": "bedrock-runtime",  # souvent utilisé pour InvokeModel
}


def execute_aws_api(
    service: str,
    action: str,
    params: Optional[dict[str, Any]] = None,
    region: Optional[str] = None,
) -> dict[str, Any]:
    """
    Exécute une action AWS (méthode boto3 en snake_case) avec le profil forgé.
    Ex: service="s3", action="list_buckets", params={}
    Ex: service="bedrock-runtime", action="invoke_model", params={"modelId": "...", "body": b"..."}
    """
    session = get_cached_aws_session()
    region_name = region or settings.aws_region
    params = dict(params or {})

    # Pour invoke_model, body peut arriver en base64 (client JSON)
    if service in ("bedrock-runtime", "bedrock") and action == "invoke_model":
        body = params.get("body")
        if isinstance(body, str):
            try:
                params["body"] = base64.standard_b64decode(body)
            except Exception:
                params["body"] = body.encode("utf-8")

    svc = SERVICE_ALIASES.get(service, service)
    client = session.client(svc, region_name=region_name)

    if not hasattr(client, action):
        raise ValueError(f"Action inconnue pour {svc}: {action}")

    method = getattr(client, action)
    response = method(**params)

    # Sérialiser pour JSON (datetime, bytes, etc.)
    return _serialize_response(response)


def _serialize_response(obj: Any) -> Any:
    """Convertit la réponse boto3 en structure JSON-serializable."""
    if obj is None:
        return None
    if hasattr(obj, "get"):
        return {k: _serialize_response(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_serialize_response(x) for x in obj]
    if isinstance(obj, bytes):
        return {"__bytes_base64": True, "data": __import__("base64").standard_b64encode(obj).decode()}
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    if isinstance(obj, (str, int, float, bool)):
        return obj
    return str(obj)

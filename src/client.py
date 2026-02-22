"""
Client + CLI pour utiliser automatiquement le proxy AWS/Bedrock.

- Côté code : client Python pour appeler le proxy (Claude Code, scripts, etc.).
- Côté utilisateur : commande CLI `python -m src.client login-entra` qui ouvre un
  flow SSO Azure Entra ID (device code) et écrit la config automatiquement.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Any, Optional

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore

try:
    import msal
except ImportError:  # pragma: no cover
    msal = None  # type: ignore

from config import settings


def get_proxy_url() -> str:
    url = os.environ.get("BEDROCK_PROXY_URL") or os.environ.get("AWS_PROXY_URL", "")
    return url.rstrip("/")


def get_proxy_token() -> str:
    return os.environ.get("BEDROCK_PROXY_TOKEN") or os.environ.get("AWS_PROXY_TOKEN", "")


def _default_config_path() -> str:
    return os.path.join(os.path.dirname(os.path.dirname(__file__)), "bedrock-proxy.config.json")


def load_config_from_file(path: Optional[str] = None) -> tuple[str, str]:
    """Charge url et token depuis un fichier JSON. Par défaut : bedrock-proxy.config.json à la racine."""
    if path is None:
        path = _default_config_path()
    if not os.path.isfile(path):
        return get_proxy_url(), get_proxy_token()
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    url = (data.get("url") or data.get("base_url") or get_proxy_url()).rstrip("/")
    token = data.get("token") or data.get("bearer_token") or get_proxy_token()
    return url, token


def save_config(url: str, token: str, path: Optional[str] = None) -> None:
    """Écrit bedrock-proxy.config.json avec url + token."""
    if path is None:
        path = _default_config_path()
    data = {"url": url.rstrip("/"), "token": token}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def execute(
    service: str,
    action: str,
    params: Optional[dict[str, Any]] = None,
    region: Optional[str] = None,
    *,
    base_url: Optional[str] = None,
    token: Optional[str] = None,
    config_path: Optional[str] = None,
) -> dict[str, Any]:
    """
    Appelle le proxy : POST /api/aws/execute.
    Si base_url ou token ne sont pas passés, utilise config_path puis les env BEDROCK_PROXY_* / AWS_PROXY_*.
    """
    if httpx is None:
        raise RuntimeError("httpx est requis pour le client proxy : pip install httpx")
    url_base = base_url
    auth_token = token
    if url_base is None or auth_token is None:
        loaded_url, loaded_token = load_config_from_file(config_path)
        if url_base is None:
            url_base = loaded_url
        if auth_token is None:
            auth_token = loaded_token
    if not url_base:
        raise ValueError("URL du proxy manquante : définir BEDROCK_PROXY_URL ou AWS_PROXY_URL (ou fichier config)")
    if not auth_token:
        raise ValueError("Token du proxy manquant : définir BEDROCK_PROXY_TOKEN ou AWS_PROXY_TOKEN (ou fichier config)")

    payload = {
        "service": service,
        "action": action,
        "params": params or {},
    }
    if region is not None:
        payload["region"] = region

    with httpx.Client(timeout=60.0) as client:
        r = client.post(
            f"{url_base}/api/aws/execute",
            json=payload,
            headers={"Authorization": f"Bearer {auth_token}", "Content-Type": "application/json"},
        )
        r.raise_for_status()
        data = r.json()
    if not data.get("success"):
        raise RuntimeError(data.get("detail", "Erreur inconnue du proxy"))
    return data.get("result", {})


class BedrockProxyClient:
    """
    Client orienté Bedrock : expose invoke_model et invoke_model_with_response_stream
    en passant par le proxy. Utilise fichier de config ou variables d'environnement.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        token: Optional[str] = None,
        region: Optional[str] = None,
        config_path: Optional[str] = None,
    ):
        if base_url is None or token is None:
            loaded_url, loaded_token = load_config_from_file(config_path)
            base_url = base_url or loaded_url
            token = token or loaded_token
        self._base_url = base_url.rstrip("/") if base_url else ""
        self._token = token or ""
        self._region = region

    def invoke_model(
        self,
        modelId: str,
        body: str | bytes | dict,
        contentType: str = "application/json",
        accept: str = "application/json",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Appel invoke_model Bedrock via le proxy. body : dict, JSON string ou bytes."""
        if isinstance(body, dict):
            body = json.dumps(body)
        if isinstance(body, str):
            body = body.encode("utf-8")
        body_b64 = base64.standard_b64encode(body).decode("ascii")
        params = {
            "modelId": modelId,
            "contentType": contentType,
            "accept": accept,
            "body": body_b64,
            **kwargs,
        }
        result = execute(
            "bedrock-runtime",
            "invoke_model",
            params=params,
            region=self._region,
            base_url=self._base_url,
            token=self._token,
        )
        return result

    def invoke_model_with_response_stream(
        self,
        modelId: str,
        body: str | bytes,
        contentType: str = "application/json",
        accept: str = "application/json",
        **kwargs: Any,
    ) -> Any:
        """
        Stream non géré par défaut via le proxy (le proxy renvoie la réponse sérialisée).
        Pour le streaming, prévoir un endpoint dédié ou utiliser invoke_model et traiter le body.
        """
        return self.invoke_model(
            modelId=modelId,
            body=body,
            contentType=contentType,
            accept=accept,
            **kwargs,
        )


def get_proxy_client(
    base_url: Optional[str] = None,
    token: Optional[str] = None,
    region: Optional[str] = None,
    config_path: Optional[str] = None,
) -> BedrockProxyClient:
    """Retourne un client Bedrock qui passe par le proxy (config env ou fichier)."""
    return BedrockProxyClient(
        base_url=base_url,
        token=token,
        region=region,
        config_path=config_path,
    )


def login_entra(proxy_url: Optional[str] = None, config_path: Optional[str] = None) -> int:
    """
    Login SSO Azure Entra ID (device code) pour obtenir automatiquement un JWT
    et écrire bedrock-proxy.config.json. Usage :

        python -m src.client login-entra --proxy-url http://localhost:8000
    """
    if msal is None:
        print("msal n'est pas installé. Ajoutez-le avec: pip install msal")
        return 1

    tenant = settings.entra_tenant_id
    client_id = settings.entra_client_id
    if not tenant or not client_id:
        print("entra_tenant_id et entra_client_id doivent être configurés dans .env pour login Entra.")
        return 1

    authority = f"https://login.microsoftonline.com/{tenant}"
    app = msal.PublicClientApplication(client_id=client_id, authority=authority)

    scopes = ["openid", "profile", "email"]
    flow = app.initiate_device_flow(scopes=scopes)
    if "user_code" not in flow:
        print("Impossible d'initialiser le device code flow :", flow)
        return 1

    print(flow["message"])
    print("En attendant la validation dans le navigateur...")
    result = app.acquire_token_by_device_flow(flow)
    if "id_token" not in result:
        print("Échec de l'authentification :", result.get("error_description") or result)
        return 1

    token = result["id_token"]
    final_proxy_url = (
        proxy_url
        or os.environ.get("BEDROCK_PROXY_URL")
        or os.environ.get("AWS_PROXY_URL")
        or "http://localhost:8000"
    ).rstrip("/")
    save_config(final_proxy_url, token, path=config_path)
    print(f"✅ Login Entra réussi. Config écrite dans {config_path or _default_config_path()}")
    return 0


def login_cognito(
    proxy_url: Optional[str] = None,
    config_path: Optional[str] = None,
    callback_port: int = 8765,
) -> int:
    """
    Login Cognito via Hosted UI : ouvre le navigateur, récupère le token
    sur le redirect localhost, écrit la config.
    """
    region = settings.cognito_region
    client_id = settings.cognito_app_client_id
    prefix = settings.cognito_domain_prefix
    if not all([region, client_id, prefix]):
        print("cognito_region, cognito_app_client_id et cognito_domain_prefix doivent être configurés dans .env")
        return 1

    base = f"https://{prefix}.auth.{region}.amazoncognito.com"
    redirect_uri = f"http://localhost:{callback_port}/callback"
    auth_url = (
        f"{base}/oauth2/authorize?client_id={client_id}&response_type=token"
        f"&scope=openid+profile&redirect_uri={redirect_uri}"
    )

    token_received: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            pass

        def do_GET(self) -> None:
            if self.path.startswith("/callback"):
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                # Page qui lit le hash (#id_token=...) et envoie au serveur
                self.wfile.write(
                    b"""<!DOCTYPE html><html><head><meta charset="utf-8"></head><body>
<p>Connexion en cours...</p>
<script>
var hash = window.location.hash.slice(1);
var params = new URLSearchParams(hash);
var id = params.get('id_token');
if (id) {
  fetch('/callback/done', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({token: id}) })
    .then(function() { document.body.innerHTML = '<p style="color:green">Connexion reussie. Vous pouvez fermer cette fenetre.</p>'; });
} else {
  document.body.innerHTML = '<p style="color:red">Token non reçu. Fermez et réessayez.</p>';
}
</script></body></html>"""
                )
                return
            self.send_response(404)
            self.end_headers()

        def do_POST(self) -> None:
            if self.path == "/callback/done":
                content_len = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_len)
                try:
                    data = json.loads(body)
                    tok = data.get("token")
                    if tok:
                        token_received.append(tok)
                except Exception:
                    pass
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(
                    b"<!DOCTYPE html><html><body><p>Connexion reussie. Vous pouvez fermer cette fenetre.</p></body></html>"
                )
                return
            self.send_response(404)
            self.end_headers()

    server = HTTPServer(("localhost", callback_port), Handler)
    print(f"Ouverture du navigateur pour Cognito. Si rien ne s'ouvre, allez sur : {auth_url}")
    webbrowser.open(auth_url)
    while not token_received:
        server.handle_request()
    server.server_close()

    if not token_received:
        print("Aucun token reçu (timeout ou annulation).")
        return 1

    final_proxy_url = (
        proxy_url
        or os.environ.get("BEDROCK_PROXY_URL")
        or os.environ.get("AWS_PROXY_URL")
        or "http://localhost:8000"
    ).rstrip("/")
    save_config(final_proxy_url, token_received[0], path=config_path)
    print(f"✅ Login Cognito réussi. Config écrite dans {config_path or _default_config_path()}")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="CLI pour le proxy AWS/Bedrock (login SSO + client).")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_login_entra = subparsers.add_parser(
        "login-entra",
        help="Login SSO Azure Entra ID (device code) et écriture de la config proxy.",
    )
    p_login_entra.add_argument(
        "--proxy-url",
        dest="proxy_url",
        help="URL du proxy (défaut: BEDROCK_PROXY_URL/AWS_PROXY_URL ou http://localhost:8000)",
    )
    p_login_entra.add_argument(
        "--config-path",
        dest="config_path",
        help="Chemin du fichier de config (défaut: bedrock-proxy.config.json à la racine).",
    )

    p_login_cognito = subparsers.add_parser(
        "login-cognito",
        help="Login Cognito (Hosted UI) : ouvre le navigateur et écrit la config proxy.",
    )
    p_login_cognito.add_argument("--proxy-url", dest="proxy_url", help="URL du proxy")
    p_login_cognito.add_argument("--config-path", dest="config_path", help="Fichier de config")
    p_login_cognito.add_argument("--port", type=int, default=8765, help="Port du callback local (défaut: 8765)")

    args = parser.parse_args(argv)
    if args.command == "login-entra":
        return login_entra(proxy_url=args.proxy_url, config_path=args.config_path)
    if args.command == "login-cognito":
        return login_cognito(
            proxy_url=args.proxy_url,
            config_path=args.config_path,
            callback_port=getattr(args, "port", 8765),
        )
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

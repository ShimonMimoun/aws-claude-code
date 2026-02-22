"""
Serveur proxy AWS : authentification (Azure Entra ID ou Cognito) puis
toutes les requêtes AWS passent par ce serveur avec un profil forgé (AssumeRole).
Page /login pour auth web automatique (device code Entra) + cookie.
"""
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import BaseModel, Field
from typing import Any, Optional

from config import settings
from src.auth.dependencies import COOKIE_TOKEN_NAME, get_current_user
from src.auth.models import TokenPayload
from src.aws.proxy import execute_aws_api
from src.login_web import poll_entra_login, start_entra_login
from src.usage.store import usage_store

app = FastAPI(
    title="AWS Proxy",
    description="Proxy AWS avec auth SSO (Entra ID / Cognito), profil forgé et passage de toutes les requêtes par le serveur.",
    version="0.1.0",
)


class AwsExecuteRequest(BaseModel):
    service: str = Field(..., description="Service AWS (ex: s3, bedrock-runtime, sts)")
    action: str = Field(..., description="Action boto3 en snake_case (ex: list_buckets, invoke_model)")
    params: Optional[dict[str, Any]] = Field(default_factory=dict, description="Paramètres de l'appel")
    region: Optional[str] = Field(default=None, description="Région AWS (défaut: config)")


@app.get("/health")
def health():
    """Sans auth : vérification que le serveur répond."""
    return {"status": "ok", "auth_provider": settings.auth_provider}


# ---------- Login web : page + API Entra device code + cookie ----------

LOGIN_HTML = """<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Connexion – AWS Proxy</title>
  <style>
    body { font-family: system-ui, sans-serif; max-width: 480px; margin: 2rem auto; padding: 0 1rem; }
    h1 { font-size: 1.25rem; }
    .step { background: #f5f5f5; padding: 1rem; border-radius: 8px; margin: 1rem 0; white-space: pre-wrap; }
    .success { background: #e8f5e9; color: #1b5e20; }
    .error { background: #ffebee; color: #b71c1c; }
    a { color: #1565c0; }
    code { background: #eee; padding: 2px 6px; border-radius: 4px; }
  </style>
</head>
<body>
  <h1>Connexion au proxy AWS</h1>
  <div id="root">Chargement...</div>
  <script>
    var root = document.getElementById('root');
    function show(msg, cls) {
      root.innerHTML = '<div class="step ' + (cls || '') + '">' + msg + '</div>';
    }
    function onSuccess() {
      show('Vous êtes connecté. Vous pouvez fermer cette page ou utiliser le proxy (cookie enregistré).', 'success');
    }
    if (window.location.search.indexOf('success=1') !== -1) {
      onSuccess();
      return;
    }
    fetch('/api/login/entra/start', { method: 'POST' })
      .then(function(r) { return r.json(); })
      .then(function(data) {
        if (data.error) {
          show('Erreur: ' + data.error, 'error');
          return;
        }
        show('1. Allez sur : <a href="' + data.verification_uri + '" target="_blank">' + data.verification_uri + '</a>\\n2. Entrez le code : <code>' + data.user_code + '</code>\\n\\nEn attente de votre connexion...');
        var sessionId = data.session_id;
        var interval = setInterval(function() {
          fetch('/api/login/entra/poll?session_id=' + sessionId)
            .then(function(r) { return r.json(); })
            .then(function(poll) {
              if (poll.status === 'done') {
                clearInterval(interval);
                fetch('/api/login/set-cookie', {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ token: poll.token }),
                  credentials: 'include'
                }).then(function() {
                  window.location = '/login?success=1';
                });
              } else if (poll.status === 'error') {
                clearInterval(interval);
                show('Erreur: ' + (poll.error || 'inconnue'), 'error');
              }
            });
        }, 2000);
      })
      .catch(function(e) {
        show('Erreur: ' + e.message, 'error');
      });
  </script>
</body>
</html>
"""


@app.get("/login", response_class=HTMLResponse)
def login_page():
    """Page de connexion : device code Entra, puis cookie enregistré automatiquement."""
    return LOGIN_HTML


@app.post("/api/login/entra/start")
def api_login_entra_start():
    """Démarre le flow device code Entra (pour la page /login)."""
    return start_entra_login()


@app.get("/api/login/entra/poll")
def api_login_entra_poll(session_id: str):
    """Poll l’état du login Entra (pending | done | error)."""
    return poll_entra_login(session_id)


class SetCookieBody(BaseModel):
    token: str


@app.post("/api/login/set-cookie")
def api_login_set_cookie(body: SetCookieBody, response: Response):
    """Enregistre le token en cookie (HttpOnly) après login réussi."""
    response.set_cookie(
        key=COOKIE_TOKEN_NAME,
        value=body.token,
        path="/",
        max_age=86400 * 7,
        httponly=True,
        samesite="lax",
    )
    return Response(status_code=204)


@app.get("/me")
def me(user: TokenPayload = Depends(get_current_user)):
    """Retourne les infos du token (pour debug)."""
    return {
        "sub": user.sub,
        "email": user.email,
        "name": user.name,
        "roles": user.roles,
    }


@app.post("/api/aws/execute")
def api_aws_execute(
    body: AwsExecuteRequest,
    user: TokenPayload = Depends(get_current_user),
):
    """
    Exécute un appel AWS via le proxy avec le profil forgé.
    Toute la requête passe par ce serveur ; le client n'appelle jamais AWS directement.
    Chaque appel est enregistré pour le suivi d'utilisation (qui, combien).
    """
    try:
        result = execute_aws_api(
            service=body.service,
            action=body.action,
            params=body.params,
            region=body.region,
        )
        usage_store.record(
            user_id=user.sub,
            user_email=user.email,
            user_name=user.name,
            service=body.service,
            action=body.action,
            region=body.region,
        )
        return {"success": True, "result": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Erreur AWS: {e!s}")


@app.get("/api/usage/me")
def api_usage_me(user: TokenPayload = Depends(get_current_user)):
    """
    Mon utilisation : combien d'appels j'ai faits, par service et par action.
    """
    summaries = usage_store.get_summary_by_user(user_id=user.sub)
    if not summaries:
        return {
            "user_id": user.sub,
            "user_email": user.email,
            "user_name": user.name,
            "total_calls": 0,
            "by_service": {},
            "by_action": {},
            "first_call": None,
            "last_call": None,
        }
    s = summaries[0]
    return s.model_dump(mode="json")


@app.get("/api/usage")
def api_usage_all(user: TokenPayload = Depends(get_current_user)):
    """
    Utilisation de tout le monde : qui a utilisé le proxy et combien (par utilisateur).
    """
    summaries = usage_store.get_summary_by_user()
    return [s.model_dump(mode="json") for s in summaries]


@app.get("/api/usage/events")
def api_usage_events(
    user_id: Optional[str] = None,
    limit: int = 100,
    user: TokenPayload = Depends(get_current_user),
):
    """
    Derniers événements (optionnellement filtrés par user_id).
    """
    events = usage_store.get_events(user_id=user_id, limit=limit)
    return [e.model_dump(mode="json") for e in events]


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )

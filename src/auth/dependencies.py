"""
Dépendance FastAPI : extraction du Bearer token (ou cookie) et validation (Entra ou Cognito).
"""
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from config import settings
from .models import TokenPayload
from . import entra, cognito

security = HTTPBearer(auto_error=False)

COOKIE_TOKEN_NAME = "proxy_token"


def _get_token_from_request(request: Request) -> str | None:
    """Token depuis Authorization Bearer ou cookie proxy_token."""
    auth = request.headers.get("Authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.cookies.get(COOKIE_TOKEN_NAME)


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> TokenPayload:
    token = None
    if credentials and credentials.scheme.lower() == "bearer":
        token = credentials.credentials
    if not token:
        token = request.cookies.get(COOKIE_TOKEN_NAME)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentification requise (Bearer token ou cookie)",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        if settings.auth_provider == "cognito":
            return cognito.validate_cognito_token(token)
        return entra.validate_entra_token(token)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token invalide ou expiré: {e!s}",
            headers={"WWW-Authenticate": "Bearer"},
        )

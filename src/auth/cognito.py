"""
Validation des tokens Cognito (JWT).
Utilise le JWKS du User Pool pour vérifier les access ou id tokens.
"""
import httpx
from jose import jwt, JWTError
from typing import Optional
from .models import TokenPayload
from config import settings


_jwks_cache: Optional[dict] = None


def _fetch_cognito_jwks() -> dict:
    url = settings.get_cognito_jwks_url()
    if not url:
        raise ValueError("Cognito non configuré (cognito_user_pool_id + cognito_region ou cognito_jwks_url)")
    with httpx.Client(timeout=10.0) as client:
        r = client.get(url)
        r.raise_for_status()
        return r.json()


def _get_jwks() -> dict:
    global _jwks_cache
    if _jwks_cache is None:
        _jwks_cache = _fetch_cognito_jwks()
    return _jwks_cache


def _get_signing_key(jwks: dict, kid: Optional[str]) -> Optional[dict]:
    for key in jwks.get("keys", []):
        if kid is None or key.get("kid") == kid:
            return key
    return None


def validate_cognito_token(token: str) -> TokenPayload:
    jwks = _get_jwks()
    unverified = jwt.get_unverified_header(token)
    kid = unverified.get("kid")
    key_data = _get_signing_key(jwks, kid)
    if not key_data:
        raise ValueError("Signing key not found in Cognito JWKS")

    payload = jwt.decode(
        token,
        key_data,
        algorithms=["RS256"],
        audience=settings.cognito_app_client_id,
        options={"verify_aud": True},
    )

    return TokenPayload(
        sub=payload.get("sub", ""),
        email=payload.get("email"),
        name=payload.get("name") or payload.get("cognito:username"),
        roles=payload.get("cognito:groups", []) if isinstance(payload.get("cognito:groups"), list) else [],
        raw_claims=payload,
    )

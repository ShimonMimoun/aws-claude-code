"""
Validation des tokens Azure Entra ID (OIDC).
Récupération des clés JWKS depuis l'issuer et vérification du JWT.
"""
import httpx
from jose import jwt, JWTError
from jose.backends.rsa_backend import RSAKey
from typing import Optional
from .models import TokenPayload
from config import settings


def _get_jwks_uri(issuer: str) -> str:
    return f"{issuer.rstrip('/')}/.well-known/openid-configuration"


def _fetch_jwks(issuer: str) -> dict:
    config_url = _get_jwks_uri(issuer)
    with httpx.Client(timeout=10.0) as client:
        r = client.get(config_url)
        r.raise_for_status()
        doc = r.json()
    jwks_url = doc.get("jwks_uri")
    if not jwks_url:
        raise ValueError("jwks_uri not found in OIDC discovery")
    with httpx.Client(timeout=10.0) as client:
        r = client.get(jwks_url)
        r.raise_for_status()
        return r.json()


def _get_signing_key(jwks: dict, kid: Optional[str]) -> Optional[dict]:
    for key in jwks.get("keys", []):
        if kid is None or key.get("kid") == kid:
            return key
    return None


# Cache simple en mémoire (en prod préférer TTL + invalidation)
_jwks_cache: dict[str, dict] = {}


def validate_entra_token(token: str) -> TokenPayload:
    issuer = settings.get_entra_issuer()
    if not issuer:
        raise ValueError("Entra ID non configuré (entra_tenant_id ou entra_issuer)")
    audience = settings.entra_audience or settings.entra_client_id
    if not audience:
        raise ValueError("entra_audience ou entra_client_id requis")

    if issuer not in _jwks_cache:
        _jwks_cache[issuer] = _fetch_jwks(issuer)
    jwks = _jwks_cache[issuer]

    unverified = jwt.get_unverified_header(token)
    kid = unverified.get("kid")
    key_data = _get_signing_key(jwks, kid)
    if not key_data:
        raise ValueError("Signing key not found in JWKS")

    payload = jwt.decode(
        token,
        key_data,
        algorithms=["RS256"],
        audience=audience,
        issuer=issuer,
        options={"verify_aud": True, "verify_iss": True},
    )

    # Mapper les claims Entra vers notre modèle
    return TokenPayload(
        sub=payload.get("oid") or payload.get("sub", ""),
        email=payload.get("email") or payload.get("preferred_username"),
        name=payload.get("name"),
        roles=payload.get("roles", []) if isinstance(payload.get("roles"), list) else [],
        raw_claims=payload,
    )

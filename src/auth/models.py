from pydantic import BaseModel
from typing import Optional, Any


class TokenPayload(BaseModel):
    """Payload décodé du JWT après validation (Entra ID ou Cognito)."""
    sub: str
    email: Optional[str] = None
    name: Optional[str] = None
    roles: list[str] = []
    raw_claims: dict[str, Any] = {}

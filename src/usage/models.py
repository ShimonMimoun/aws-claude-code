from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class UsageEvent(BaseModel):
    """Un appel proxy enregistré."""
    user_id: str
    user_email: Optional[str] = None
    user_name: Optional[str] = None
    at: datetime
    service: str
    action: str
    region: Optional[str] = None


class UserUsageSummary(BaseModel):
    """Résumé d'utilisation par utilisateur."""
    user_id: str
    user_email: Optional[str] = None
    user_name: Optional[str] = None
    total_calls: int
    by_service: dict[str, int]
    by_action: dict[str, int]
    first_call: Optional[datetime] = None
    last_call: Optional[datetime] = None

"""
Stockage des appels proxy par utilisateur : qui a utilisé quoi et combien.
Persistance optionnelle en JSON pour survivre aux redémarrages.
"""
from datetime import datetime
from typing import Optional
from collections import defaultdict
import json
import os

from .models import UsageEvent, UserUsageSummary


class UsageStore:
    def __init__(self, persist_path: Optional[str] = None):
        self._events: list[UsageEvent] = []
        self._persist_path = persist_path
        if persist_path and os.path.isfile(persist_path):
            self._load()

    def record(
        self,
        user_id: str,
        service: str,
        action: str,
        region: Optional[str] = None,
        user_email: Optional[str] = None,
        user_name: Optional[str] = None,
    ) -> None:
        event = UsageEvent(
            user_id=user_id,
            user_email=user_email,
            user_name=user_name,
            at=datetime.utcnow(),
            service=service,
            action=action,
            region=region,
        )
        self._events.append(event)
        if self._persist_path:
            self._append_to_file(event)

    def _append_to_file(self, event: UsageEvent) -> None:
        try:
            line = event.model_dump(mode="json")
            with open(self._persist_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(line, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def _load(self) -> None:
        try:
            with open(self._persist_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    data = json.loads(line)
                    if "at" in data and isinstance(data["at"], str):
                        data["at"] = datetime.fromisoformat(data["at"].replace("Z", "+00:00"))
                    self._events.append(UsageEvent(**data))
        except Exception:
            self._events = []

    def get_events(self, user_id: Optional[str] = None, limit: int = 1000) -> list[UsageEvent]:
        """Derniers événements, optionnellement filtrés par user_id."""
        events = self._events
        if user_id is not None:
            events = [e for e in events if e.user_id == user_id]
        return list(reversed(events[-limit:]))

    def get_summary_by_user(self, user_id: Optional[str] = None) -> list[UserUsageSummary]:
        """Résumé par utilisateur (qui a utilisé, combien). Si user_id est fourni, un seul user."""
        events = self._events
        if user_id is not None:
            events = [e for e in events if e.user_id == user_id]

        by_user: dict[str, list[UsageEvent]] = defaultdict(list)
        for e in events:
            by_user[e.user_id].append(e)

        result = []
        for uid, user_events in by_user.items():
            by_service: dict[str, int] = defaultdict(int)
            by_action: dict[str, int] = defaultdict(int)
            first_call: Optional[datetime] = None
            last_call: Optional[datetime] = None
            email, name = None, None
            for e in user_events:
                by_service[e.service] += 1
                by_action[e.action] += 1
                if first_call is None or e.at < first_call:
                    first_call = e.at
                if last_call is None or e.at > last_call:
                    last_call = e.at
                if e.user_email:
                    email = e.user_email
                if e.user_name:
                    name = e.user_name
            result.append(
                UserUsageSummary(
                    user_id=uid,
                    user_email=email,
                    user_name=name,
                    total_calls=len(user_events),
                    by_service=dict(by_service),
                    by_action=dict(by_action),
                    first_call=first_call,
                    last_call=last_call,
                )
            )
        result.sort(key=lambda s: s.total_calls, reverse=True)
        return result


# Instance globale (optionnel: chemin depuis config)
def _get_persist_path() -> Optional[str]:
    try:
        from config import settings
        return getattr(settings, "usage_log_path", None)
    except Exception:
        return None


usage_store = UsageStore(persist_path=_get_persist_path())

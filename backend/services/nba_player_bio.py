"""
Životopis hráče pro stránku zajímavostí.

Zdroj: NBA CommonPlayerInfo (datum narození, roky v lize, klub, pozice).
Odpovědi se ukládají do souboru, aby se každý hráč stahoval jen jednou.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "player_bio.json"
)
_LOCK = threading.Lock()
_CACHE: Dict[str, Dict[str, Any]] = {}


def _load() -> Dict[str, Dict[str, Any]]:
    global _CACHE
    if _CACHE:
        return _CACHE
    try:
        if os.path.exists(_FILE):
            with open(_FILE, encoding="utf-8") as fh:
                _CACHE = json.load(fh)
    except Exception as exc:  # pragma: no cover
        logger.warning("Životopisy hráčů nešly načíst: %s", exc)
    return _CACHE


def _save() -> None:
    try:
        tmp = _FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(_CACHE, fh, ensure_ascii=False)
        os.replace(tmp, _FILE)
    except Exception as exc:  # pragma: no cover
        logger.warning("Životopisy hráčů nešly uložit: %s", exc)


def bio(player_id: int) -> Optional[Dict[str, Any]]:
    """Základní údaje hráče (název, narození, roky v NBA, klub, pozice)."""
    key = str(int(player_id))
    data = _load()
    with _LOCK:
        if key in data:
            return data[key]

    try:
        from nba_api.stats.endpoints import commonplayerinfo

        df = commonplayerinfo.CommonPlayerInfo(player_id=int(player_id), timeout=20).get_data_frames()[0]
        r = df.iloc[0]
        info = {
            "player_id": int(player_id),
            "name": str(r["DISPLAY_FIRST_LAST"]),
            "birthdate": str(r["BIRTHDATE"])[:10],
            "from_year": int(float(r["FROM_YEAR"] or 0)),
            "to_year": int(float(r["TO_YEAR"] or 0)),
            "team": str(r["TEAM_NAME"]),
            "position": str(r["POSITION"]),
            "height": str(r["HEIGHT"]),
            "weight": str(r["WEIGHT"]),
        }
    except Exception as exc:
        logger.warning("Životopis hráče %s se nepodařilo načíst: %s", player_id, exc)
        return None

    with _LOCK:
        data[key] = info
    _save()
    return info

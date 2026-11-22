"""
Historická data pro All-Time žebříčky – přímo z NBA.

Proč ne ruční stahování kariér: NBA má dva hotové zdroje, které pokrývají
celou historii ligy (od 1946-47) a jsou hotové za zlomek sekundy:

  1) AllTimeLeadersGrids – oficiální all-time žebříček NBA (top 10 pro
     každou statistiku). Používá se pro pořadí, počet zápasů i jména,
     takže čísla jsou přesně ta, která uvádí NBA.
  2) CommonAllPlayers – seznam všech hráčů, kteří kdy v NBA nastoupili
     (id, roky od–do).

Oba zdroje jsou hotové do ~1 s, takže žádné dlouhé stahování tisíců
kariér. Kdo v oficiální top 10 není, dopočítá se z týmových žebříčků
franšíz (ty vycházejí z kariérních dat jednotlivých hráčů týmu).
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

POOL_VERSION = 1

_POOL_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "alltime_official.json.gz"
)
_POOL_FILE_PLAIN = _POOL_FILE.replace(".json.gz", ".json")

_POOL: Optional[Dict[str, Any]] = None
_LOCK = threading.Lock()

# NBA klíč statistiky → náš klíč (v AllTimeLeadersGrids)
_GRID_KEYS = {
    "PTS": "PTS",
    "REB": "REB",
    "AST": "AST",
    "STL": "STL",
    "BLK": "BLK",
    "FG3M": "FG3M",
    "GP": "GP",
    "FGM": "FGM",
    "FGA": "FGA",
    "FG_PCT": "FG_PCT",
    "FG3A": "FG3A",
    "FG3_PCT": "FG3_PCT",
    "FTM": "FTM",
    "FTA": "FTA",
    "FT_PCT": "FT_PCT",
    "TOV": "TOV",
    "PF": "PF",
    "OREB": "OREB",
    "DREB": "DREB",
}


def _safe_float(value: Any) -> float:
    try:
        if value is None:
            return 0.0
        f = float(value)
        return 0.0 if f != f else f
    except (TypeError, ValueError):
        return 0.0


def _safe_int(value: Any) -> int:
    return int(_safe_float(value))


def _read_pool() -> Optional[Dict[str, Any]]:
    """Načte pool – nově komprimovaný, starší nekomprimovaný se převede."""
    import gzip

    try:
        if os.path.exists(_POOL_FILE):
            with gzip.open(_POOL_FILE, "rt", encoding="utf-8") as fh:
                return json.load(fh)
        if os.path.exists(_POOL_FILE_PLAIN):
            with open(_POOL_FILE_PLAIN, encoding="utf-8") as fh:
                data = json.load(fh)
            _save_pool(data)
            return data
    except Exception as exc:  # pragma: no cover
        logger.warning("All-time pool nešel načíst: %s", exc)
    return None


def _needed_people(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Zúží seznam všech hráčů na ty, které aplikace opravdu použije:
    ty ze žebříčků + ty se známým počtem zápasů. Ze 5 200 lidí zůstane ~100,
    takže soubor je 25× menší a načítá se okamžitě.
    """
    leaders = data.get("leaders") or {}
    ids = set()
    for rows in leaders.values():
        for row in rows or []:
            pid = row.get("player_id") if isinstance(row, dict) else None
            if pid:
                ids.add(str(pid))
    people = data.get("people") or {}
    keep = ids | {k for k, v in people.items() if (v or {}).get("gp_known")}
    data["people"] = {k: people[k] for k in keep if k in people}
    return data


def _save_pool(data: Dict[str, Any]) -> None:
    """Uloží pool komprimovaně (gzip) – na disku i v paměti je několikrát menší."""
    import gzip

    data = _needed_people(data)
    try:
        tmp = _POOL_FILE + ".tmp"
        with gzip.open(tmp, "wt", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, _POOL_FILE)
        plain = _POOL_FILE.replace(".json.gz", ".json")
        if plain != _POOL_FILE and os.path.exists(plain):
            try:
                os.remove(plain)
            except OSError:
                pass
    except Exception as exc:  # pragma: no cover
        logger.warning("All-time pool nešel uložit: %s", exc)


def build_official_pool(force: bool = False) -> Dict[str, Any]:
    """
    Stáhne oficiální all-time žebříčky + seznam všech hráčů.
    Dohromady dva requesty, trvá to kolem sekundy.
    """
    if not force:
        data = _read_pool()
        if data and data.get("version") == POOL_VERSION and data.get("leaders"):
            return data
    if False:
        try:
            pass
        except Exception as exc:  # pragma: no cover
            logger.warning("All-time pool (oficiální) nešel načíst: %s", exc)

    from nba_api.stats.endpoints import alltimeleadersgrids, commonallplayers

    started = time.time()
    leaders: Dict[str, Any] = {}

    dfs = alltimeleadersgrids.AllTimeLeadersGrids(
        per_mode_simple="Totals",
        season_type="Regular Season",
        timeout=40,
    ).get_data_frames()

    for df in dfs:
        cols = list(df.columns)
        if not cols or "PLAYER_ID" not in cols:
            continue
        stat_key = None
        for c in cols:
            if c.endswith("_RANK"):
                stat_key = c[: -len("_RANK")]
                break
        if not stat_key or stat_key not in _GRID_KEYS:
            continue
        rows: List[Dict[str, Any]] = []
        for _, r in df.iterrows():
            value = _safe_float(r.get(stat_key))
            rows.append(
                {
                    "player_id": _safe_int(r.get("PLAYER_ID")),
                    "name": str(r.get("PLAYER_NAME") or ""),
                    "value": value,
                    "gp": _safe_int(r.get("GP")) if "GP" in cols else 0,
                    "rank": _safe_int(r.get(f"{stat_key}_RANK")),
                    "active": str(r.get("IS_ACTIVE_FLAG") or "").upper() == "Y",
                }
            )
        rows.sort(key=lambda x: x["rank"] or 999)
        leaders[stat_key] = rows

    # Přehled všech hráčů, kteří kdy v NBA nastoupili
    people_df = commonallplayers.CommonAllPlayers(
        is_only_current_season=0, league_id="00", timeout=40
    ).get_data_frames()[0]

    people: Dict[str, Dict[str, Any]] = {}
    for _, r in people_df.iterrows():
        pid = _safe_int(r.get("PERSON_ID"))
        if not pid:
            continue
        people[str(pid)] = {
            "name": str(r.get("DISPLAY_FIRST_LAST") or ""),
            "from_year": _safe_int(r.get("FROM_YEAR")),
            "to_year": _safe_int(r.get("TO_YEAR")),
            "active": str(r.get("ROSTERSTATUS") or "") == "1",
            "team": str(r.get("TEAM_ABBREVIATION") or ""),
        }

    # Kdo hraje právě teď (kvůli průměrům na zápas a značce "aktivní")
    try:
        from nba_api.stats.endpoints import playerindex

        idx_df = playerindex.PlayerIndex(league_id="00", timeout=40).get_data_frames()[0]
        for _, r in idx_df.iterrows():
            pid = _safe_int(r.get("PERSON_ID"))
            if not pid:
                continue
            name = f"{str(r.get('PLAYER_FIRST_NAME') or '')} {str(r.get('PLAYER_LAST_NAME') or '')}".strip()
            entry = people.setdefault(
                str(pid),
                {"name": name, "from_year": 0, "to_year": 0, "active": False, "team": ""},
            )
            entry["active"] = True
            entry["team"] = str(r.get("TEAM_ABBREVIATION") or entry.get("team") or "")
            if not entry.get("name"):
                entry["name"] = name
    except Exception as exc:  # pragma: no cover
        logger.warning("Seznam aktivních hráčů se nepodařilo načíst: %s", exc)

    # Zápasy (GP) pro každého hráče z oficiálních gridů – každý grid má sloupec GP
    gp_all: Dict[str, int] = {}
    for stat_key, stat_rows in leaders.items():
        for row in stat_rows:
            if not row.get("gp"):
                # AllTimeLeadersGrids má u PTS/REB/… sloupec GP jen u gridu zápasů;
                # ostatní gridy GP neposílají – vezmeme ho z gridu "GP"
                gp_row = next(
                    (x for x in (leaders.get("GP") or []) if x["player_id"] == row["player_id"]),
                    None,
                )
                if gp_row:
                    row["gp"] = gp_row["gp"] or gp_row.get("value") or 0
            if row.get("gp"):
                gp_all[str(row["player_id"])] = max(gp_all.get(str(row["player_id"]), 0), row["gp"])
    for pid, info in people.items():
        info["gp_known"] = gp_all.get(pid, 0)

    data = {
        "version": POOL_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "NBA – AllTimeLeadersGrids + CommonAllPlayers (celá historie ligy)",
        "leaders": leaders,
        "people": people,
        "build_seconds": round(time.time() - started, 2),
    }
    try:
        _save_pool(data)
    except Exception as exc:  # pragma: no cover
        logger.warning("All-time pool (oficiální) nešel uložit: %s", exc)

    logger.info(
        "All-time pool (oficiální) hotov: %s statistik, %s hráčů, %.1f s",
        len(leaders),
        len(people),
        time.time() - started,
    )
    return data


def official_pool() -> Dict[str, Any]:
    global _POOL
    with _LOCK:
        if _POOL is not None:
            return _POOL
        _POOL = build_official_pool()
        return _POOL


def people_index() -> Dict[str, Dict[str, Any]]:
    return official_pool().get("people") or {}


def leaders_for(stat: str) -> List[Dict[str, Any]]:
    """Oficiální all-time žebříček pro danou statistiku (nebo prázdný seznam)."""
    return (official_pool().get("leaders") or {}).get(stat) or []


def _fetch_gp(player_id: int) -> int:
    """Počet odehraných zápasů v základní části z kariérní tabulky hráče."""
    from nba_api.stats.endpoints import playercareerstats

    dfs = playercareerstats.PlayerCareerStats(
        player_id=player_id, per_mode36="Totals", timeout=25
    ).get_data_frames()
    if not dfs or dfs[0].empty:
        return 0
    df = dfs[0]
    total = 0
    for _, r in df.iterrows():
        team = str(r.get("TEAM_ABBREVIATION") or "").strip().upper()
        if team in ("", "TOT", "N/A", "NONE"):
            continue
        gp = _safe_int(r.get("GP"))
        if gp > 0:
            total += gp
    return total


def fill_missing_gp(pool: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Doplní zápasy (GP) u hráčů, u kterých je NBA v žebříčku neuvádí.
    Stačí to jednou – pak se uloží do souboru.
    """
    global _POOL
    data = pool or official_pool()
    cache: Dict[str, int] = {}
    changed = 0
    for stat_key, rows in (data.get("leaders") or {}).items():
        for row in rows:
            if row.get("gp"):
                continue
            pid = str(row["player_id"])
            if pid not in cache:
                for attempt in range(3):
                    try:
                        cache[pid] = _fetch_gp(row["player_id"])
                        break
                    except Exception:
                        time.sleep(0.6 + attempt)
                time.sleep(0.25)
            row["gp"] = cache.get(pid, 0)
            if row["gp"]:
                changed += 1
    if changed:
        try:
            _save_pool(data)
        except Exception as exc:  # pragma: no cover
            logger.warning("Doplnění zápasů nešlo uložit: %s", exc)
    _POOL = data
    return {"filled": changed, "checked": len(cache)}


def leaderboard_people(stat: str) -> List[Dict[str, Any]]:
    """Všichni hráči, kteří mají v dané statistice oficiální hodnotu."""
    pool = official_pool()
    rows = (pool.get("leaders") or {}).get(stat) or []
    people = pool.get("people") or {}
    out: List[Dict[str, Any]] = []
    for row in rows:
        info = people.get(str(row["player_id"])) or {}
        out.append({**row, "person": info})
    return out


def status() -> Dict[str, Any]:
    data = _read_pool()
    if not data:
        return {"ready": False}
    try:
        return {
            "ready": True,
            "generated_at": data.get("generated_at"),
            "source": data.get("source"),
            "stats": len(data.get("leaders") or {}),
            "players": len(data.get("people") or {}),
        }
    except Exception:
        return {"ready": False}

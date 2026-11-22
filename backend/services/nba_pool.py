"""
Externí fond hráčů pro porovnávání („nejbližší hráč").

Proč to existuje:
    Dřív se porovnávalo jen mezi hráči, kteří byli ručně nahraní do SQLite
    (54 jmen). Proto u Raye Allena chyběl Klay Thompson a u Dirka Lauri
    Markkanen. Tenhle modul bere kariérní průměry přímo z NBA API
    (LeagueDashPlayerStats, ALL_STAR / regular season) a výsledek drží
    v malé gzip cache, aby se nestahovalo pořád dokola.

Data, která se používají (vše za zápas):
    GP, PTS, REB, AST, STL, BLK, TOV, FGM/FGA, FG3M/FG3A, FTM/FTA, MIN
"""

from __future__ import annotations

import gzip
import json
import logging
import os
import re
import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

CACHE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "comparison_pool.json.gz")
CACHE_VERSION = 3
# Kdy se má fond obnovit (7 dní). Hráči se mění jen pomalu.
MAX_AGE_SECONDS = 7 * 24 * 3600
# Sezóny, které se stahují pro kariérní průměry (od začátku NBA API dat)
FIRST_SEASON = 1996

_LOCK = threading.Lock()
_MEMORY: Optional[Dict[str, Any]] = None

# Sloupce, které z NBA API potřebujeme
_COLUMNS = (
    "PLAYER_ID,PLAYER_NAME,GP,PTS,REB,AST,STL,BLK,TOV,"
    "FGM,FGA,FG3M,FG3A,FTM,FTA,MIN"
)


def normalize_name(name: str) -> str:
    """Jméno bez diakritiky a malými písmeny – Dončić == Doncic."""
    import unicodedata

    text = unicodedata.normalize("NFKD", name or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = re.sub(r"\b(jr|sr|ii|iii|iv)\b", " ", text)
    return " ".join(text.split())


def _seasons() -> List[str]:
    """Seznam sezón '1996-97' … '2025-26'."""
    current_year = 2025
    try:
        now = time.gmtime()
        # sezóna začíná v říjnu, takže od července se počítá další rok
        current_year = now.tm_year if now.tm_mon >= 7 else now.tm_year - 1
    except Exception:
        pass
    out = []
    for year in range(FIRST_SEASON, current_year + 1):
        out.append(f"{year}-{str(year + 1)[-2:]}")
    return out


def _fetch_season(season: str) -> List[Dict[str, Any]]:
    """Jedna sezóna základní části – všichni hráči s průměry za zápas."""
    from nba_api.stats.endpoints import leaguedashplayerstats

    endpoint = leaguedashplayerstats.LeagueDashPlayerStats(
        season=season,
        season_type_all_star="Regular Season",
        per_mode_detailed="PerGame",
        timeout=25,
    )
    frame = endpoint.league_dash_player_stats.get_data_frame()
    if frame is None or frame.empty:
        return []
    return frame.to_dict("records")


def _build(progress=None) -> Dict[str, Any]:
    """
    Stáhne všechny sezóny a udělá z nich kariérní průměry.
    Kariérní průměr = vážený průměr sezón podle odehraných zápasů,
    stejně jako to počítá NBA.
    """
    totals: Dict[int, Dict[str, Any]] = {}
    seasons = _seasons()
    failed: List[str] = []

    empty_streak = 0
    for idx, season in enumerate(seasons):
        if empty_streak >= 3:
            # NBA API vrací prázdno pro sezóny, které nevede – dál to nemá cenu
            break
        try:
            rows = _fetch_season(season)
        except Exception as exc:  # pragma: no cover
            logger.warning("Sezóna %s se nestáhla: %s", season, exc)
            failed.append(season)
            continue

        empty_streak = empty_streak + 1 if not rows else 0

        for row in rows:
            pid = int(row.get("PLAYER_ID") or 0)
            if not pid:
                continue
            gp = float(row.get("GP") or 0)
            if gp <= 0:
                continue
            entry = totals.setdefault(
                pid,
                {
                    "id": pid,
                    "name": row.get("PLAYER_NAME") or "",
                    "gp": 0.0,
                    "pts": 0.0,
                    "reb": 0.0,
                    "ast": 0.0,
                    "stl": 0.0,
                    "blk": 0.0,
                    "tov": 0.0,
                    "fgm": 0.0,
                    "fga": 0.0,
                    "fg3m": 0.0,
                    "fg3a": 0.0,
                    "ftm": 0.0,
                    "fta": 0.0,
                    "min": 0.0,
                    "first_season": season,
                },
            )
            entry["gp"] += gp
            for key, col in (
                ("pts", "PTS"), ("reb", "REB"), ("ast", "AST"), ("stl", "STL"),
                ("blk", "BLK"), ("tov", "TOV"), ("fgm", "FGM"), ("fga", "FGA"),
                ("fg3m", "FG3M"), ("fg3a", "FG3A"), ("ftm", "FTM"),
                ("fta", "FTA"), ("min", "MIN"),
            ):
                entry[key] += float(row.get(col) or 0) * gp
            entry["last_season"] = season

        if progress and (idx % 5 == 0 or idx == len(seasons) - 1):
            progress(f"{season} ({idx + 1}/{len(seasons)})")
        time.sleep(0.25)  # slušnost k NBA API

    players: List[Dict[str, Any]] = []
    for entry in totals.values():
        gp = entry["gp"]
        if gp < 1:
            continue
        item = {"id": entry["id"], "name": entry["name"], "gp": round(gp, 1)}
        for key in (
            "pts", "reb", "ast", "stl", "blk", "tov", "fgm", "fga",
            "fg3m", "fg3a", "ftm", "fta", "min",
        ):
            item[key] = round(entry[key] / gp, 3)
        item["fg_pct"] = round(item["fgm"] / item["fga"], 4) if item["fga"] else 0.0
        item["fg3_pct"] = round(item["fg3m"] / item["fg3a"], 4) if item["fg3a"] else 0.0
        item["ft_pct"] = round(item["ftm"] / item["fta"], 4) if item["fta"] else 0.0
        item["first_season"] = entry.get("first_season")
        item["last_season"] = entry.get("last_season")
        item["name_key"] = normalize_name(item["name"])
        players.append(item)

    players.sort(key=lambda x: -x["gp"])
    return {
        "version": CACHE_VERSION,
        "updated_at": int(time.time()),
        "seasons": len(seasons) - len(failed),
        "failed_seasons": failed,
        "players": players,
    }


def _write(payload: Dict[str, Any]) -> None:
    try:
        with gzip.open(CACHE_PATH, "wt", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)
    except Exception as exc:  # pragma: no cover
        logger.warning("Fond hráčů se nepodařilo uložit: %s", exc)


def _read() -> Optional[Dict[str, Any]]:
    if not os.path.exists(CACHE_PATH):
        return None
    try:
        with gzip.open(CACHE_PATH, "rt", encoding="utf-8") as fh:
            payload = json.load(fh)
        if payload.get("version") != CACHE_VERSION:
            return None
        return payload
    except Exception as exc:  # pragma: no cover
        logger.warning("Fond hráčů se nepodařilo načíst: %s", exc)
        return None


def load(force: bool = False, progress=None) -> Dict[str, Any]:
    """
    Vrátí fond hráčů. Když cache chybí nebo je stará, stáhne se z NBA API.
    Síťová chyba nesmí shodit endpoint – v tom případě se vrátí, co je.
    """
    global _MEMORY

    with _LOCK:
        if _MEMORY is not None and not force:
            return _MEMORY

        cached = None if force else _read()
        if cached and (time.time() - cached.get("updated_at", 0)) < MAX_AGE_SECONDS:
            _MEMORY = cached
            return cached

        try:
            payload = _build(progress=progress)
        except Exception as exc:  # pragma: no cover
            logger.error("Fond hráčů se nepodařilo stáhnout: %s", exc)
            if cached:
                _MEMORY = cached
                return cached
            return {"version": CACHE_VERSION, "updated_at": 0, "players": []}

        if payload.get("players"):
            _write(payload)
            _MEMORY = payload
            return payload

        if cached:
            _MEMORY = cached
            return cached
        return payload


def stats_for(record: Dict[str, Any]) -> Dict[str, Any]:
    """Převede záznam z fondu do tvaru, který bere build_profile()."""
    return {
        "pts": record.get("pts", 0.0),
        "reb": record.get("reb", 0.0),
        "ast": record.get("ast", 0.0),
        "stl": record.get("stl", 0.0),
        "blk": record.get("blk", 0.0),
        "tov": record.get("tov", 0.0),
        "fga": record.get("fga", 0.0),
        "fg3a": record.get("fg3a", 0.0),
        "fg3m": record.get("fg3m", 0.0),
        "fta": record.get("fta", 0.0),
        "fg_pct": record.get("fg_pct", 0.0),
        "fg3_pct": record.get("fg3_pct", 0.0),
        "ft_pct": record.get("ft_pct", 0.0),
        "min_per_game": record.get("min", 32.0),
    }


def info() -> Dict[str, Any]:
    """Stav fondu pro UI (kolik hráčů, kdy se stáhl)."""
    payload = _read() or {}
    players = payload.get("players") or []
    return {
        "players": len(players),
        "updated_at": payload.get("updated_at", 0),
        "seasons": payload.get("seasons", 0),
        "failed_seasons": payload.get("failed_seasons", []),
        "source": "NBA API – LeagueDashPlayerStats (Regular Season, 1996–)",
    }

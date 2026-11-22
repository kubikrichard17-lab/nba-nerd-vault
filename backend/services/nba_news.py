"""
Novinky a lídři statistik pro NBA Nerd Vault.

Modul obstarává tři okruhy dat (vše z nba_api, s krátkou paměťovou cache):
  * výsledky zápasů z předchozího dne (tým vs tým + skóre),
  * detailní boxscore zápasu (statistiky všech hráčů obou týmů),
  * žebříčky lídrů (All-Time / Sezóna / Tým) pro vybranou statistiku.

Každá veřejná funkce je navržená tak, aby při výpadku nba_api vrátila
srozumitelnou chybu (NewsDataError) a backend mohl odpovědět 503.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class NewsDataError(Exception):
    """Datová vrstva nba_api neodpovídá nebo data nejsou k dispozici."""


# --------------------------------------------------------------------------- #
# Cache
# --------------------------------------------------------------------------- #

_CACHE: Dict[str, Tuple[float, Any]] = {}
_CACHE_LOCK = threading.Lock()

GAMES_TTL = 300          # 5 minut – výsledky se mění jen během zápasů
BOXSCORE_TTL = 3600 * 6  # 6 hodin – odehraný zápas se už nemění
LEADERS_TTL = 3600 * 3   # 3 hodiny – sezónní žebříčky


def _retry(call, attempts: int = 3, what: str = "data"):
    """NBA API občas zahodí spojení – zkusíme to víckrát."""
    last: Optional[Exception] = None
    for attempt in range(attempts):
        try:
            return call()
        except Exception as exc:  # pragma: no cover
            last = exc
            logger.warning("Načítání %s – pokus %s selhal: %s", what, attempt + 1, exc)
            time.sleep(1.5 + attempt * 2.5)
    raise last  # type: ignore[misc]


def _cache_get(key: str, ttl: int) -> Any:
    with _CACHE_LOCK:
        item = _CACHE.get(key)
        if not item:
            return None
        ts, value = item
        if (datetime.now(timezone.utc).timestamp() - ts) > ttl:
            return None
        return value


def _cache_set(key: str, value: Any) -> Any:
    with _CACHE_LOCK:
        _CACHE[key] = (datetime.now(timezone.utc).timestamp(), value)
    return value


# --------------------------------------------------------------------------- #
# Základní slovníky
# --------------------------------------------------------------------------- #

TEAM_CZ: Dict[str, str] = {
    "ATL": "Atlanta Hawks",
    "BOS": "Boston Celtics",
    "BKN": "Brooklyn Nets",
    "CHA": "Charlotte Hornets",
    "CHI": "Chicago Bulls",
    "CLE": "Cleveland Cavaliers",
    "DAL": "Dallas Mavericks",
    "DEN": "Denver Nuggets",
    "DET": "Detroit Pistons",
    "GSW": "Golden State Warriors",
    "HOU": "Houston Rockets",
    "IND": "Indiana Pacers",
    "LAC": "Los Angeles Clippers",
    "LAL": "Los Angeles Lakers",
    "MEM": "Memphis Grizzlies",
    "MIA": "Miami Heat",
    "MIL": "Milwaukee Bucks",
    "MIN": "Minnesota Timberwolves",
    "NOP": "New Orleans Pelicans",
    "NYK": "New York Knicks",
    "OKC": "Oklahoma City Thunder",
    "ORL": "Orlando Magic",
    "PHI": "Philadelphia 76ers",
    "PHX": "Phoenix Suns",
    "POR": "Portland Trail Blazers",
    "SAC": "Sacramento Kings",
    "SAS": "San Antonio Spurs",
    "TOR": "Toronto Raptors",
    "UTA": "Utah Jazz",
    "WAS": "Washington Wizards",
    # Historické zkratky (lídři All-Time / starší sezóny)
    "NJN": "New Jersey Nets",
    "NOH": "New Orleans Hornets",
    "NOK": "New Orleans/Oklahoma City Hornets",
    "NOH/CHA": "New Orleans Hornets",
    "CHA/CHO": "Charlotte Hornets",
    "CHH": "Charlotte Hornets",
    "CHO": "Charlotte Hornets",
    "SEA": "Seattle SuperSonics",
    "VAN": "Vancouver Grizzlies",
    "WSB": "Washington Bullets",
    "WSH": "Washington Wizards",
    "KCK": "Kansas City Kings",
    "SDC": "San Diego Clippers",
    "BUF": "Buffalo Braves",
    "SFW": "San Francisco Warriors",
    "PHL": "Philadelphia Warriors",
    "STL": "St. Louis Hawks",
    "CIN": "Cincinnati Royals",
    "ROC": "Rochester Royals",
    "FTW": "Fort Wayne Pistons",
    "SYR": "Syracuse Nationals",
    "MNL": "Minneapolis Lakers",
    "PHW": "Philadelphia Warriors",
    "TRI": "Tri-Cities Blackhawks",
    "MILH": "Milwaukee Hawks",
    "CAP": "Capital Bullets",
    "BAL": "Baltimore Bullets",
}

# Zkratky, které se slévají pod jednu franšízu (pro filtr "tým" u All-Time lídrů)
TEAM_ALIASES: Dict[str, List[str]] = {
    "ATL": ["ATL", "STL", "MLH"],
    "BOS": ["BOS"],
    "BKN": ["BKN", "NJN", "NYN"],
    "CHA": ["CHA", "CHH", "CHO"],
    "CHI": ["CHI"],
    "CLE": ["CLE"],
    "DAL": ["DAL"],
    "DEN": ["DEN"],
    "DET": ["DET", "FTW"],
    "GSW": ["GSW", "SFW", "PHW", "PHL"],
    "HOU": ["HOU", "SDR"],
    "IND": ["IND"],
    "LAC": ["LAC", "SDC", "BUF"],
    "LAL": ["LAL", "MNL"],
    "MEM": ["MEM", "VAN"],
    "MIA": ["MIA"],
    "MIL": ["MIL"],
    "MIN": ["MIN"],
    "NOP": ["NOP", "NOH", "NOK", "NOJ"],
    "NYK": ["NYK"],
    "OKC": ["OKC", "SEA"],
    "ORL": ["ORL"],
    "PHI": ["PHI", "SYR"],
    "PHX": ["PHX"],
    "POR": ["POR"],
    "SAC": ["SAC", "KCK", "KCO", "CIN", "ROC"],
    "SAS": ["SAS"],
    "TOR": ["TOR"],
    "UTA": ["UTA"],
    "WAS": ["WAS", "WSB", "CAP", "BAL"],
}

# Historická zkratka → aktuální franšíza
_FRANCHISE_OF: Dict[str, str] = {}
for _current, _aliases in TEAM_ALIASES.items():
    for _alias in _aliases:
        _FRANCHISE_OF.setdefault(_alias, _current)

# Rok, od kterého klub hraje (kvůli filtru historie u týmových žebříčků)
_FRANCHISE_ERA: Dict[str, Tuple[int, int]] = {
    "ATL": (1949, 2026), "BOS": (1946, 2026), "BKN": (1976, 2026), "CHA": (1988, 2026),
    "CHI": (1966, 2026), "CLE": (1970, 2026), "DAL": (1980, 2026), "DEN": (1976, 2026),
    "DET": (1948, 2026), "GSW": (1946, 2026), "HOU": (1967, 2026), "IND": (1976, 2026),
    "LAC": (1970, 2026), "LAL": (1948, 2026), "MEM": (1995, 2026), "MIA": (1988, 2026),
    "MIL": (1968, 2026), "MIN": (1989, 2026), "NOP": (2002, 2026), "NYK": (1946, 2026),
    "OKC": (1967, 2026), "ORL": (1989, 2026), "PHI": (1949, 2026), "PHX": (1968, 2026),
    "POR": (1970, 2026), "SAC": (1948, 2026), "SAS": (1976, 2026), "TOR": (1995, 2026),
    "UTA": (1974, 2026), "WAS": (1961, 2026),
}

# Statistiky, které umíme žebříčkovat
#   key: název statistiky (shodný s parametry nba_api / klíči v datech)
#   per_game_available: jde spočítat i průměr na zápas?
STAT_DEFS: Dict[str, Dict[str, Any]] = {
    "PTS": {"label": "Body", "short": "PTS", "per_game_available": True},
    "REB": {"label": "Doskoky", "short": "REB", "per_game_available": True},
    "AST": {"label": "Asistence", "short": "AST", "per_game_available": True},
    "STL": {"label": "Zisky", "short": "STL", "per_game_available": True},
    "BLK": {"label": "Bloky", "short": "BLK", "per_game_available": True},
    "FG3M": {"label": "Trojky", "short": "3PM", "per_game_available": True},
    "MIN": {"label": "Odehrané minuty", "short": "MIN", "per_game_available": True},
    "FG_PCT": {"label": "Úspěšnost střelby", "short": "FG%", "per_game_available": False},
    "FG3_PCT": {"label": "Úspěšnost trojek", "short": "3P%", "per_game_available": False},
    "FT_PCT": {"label": "Úspěšnost šestek", "short": "FT%", "per_game_available": False},
}

# nba_api názvy pro per-game variantu
PER_GAME_KEY = {
    "PTS": "PTS",
    "REB": "REB",
    "AST": "AST",
    "STL": "STL",
    "BLK": "BLK",
    "FG3M": "FG3M",
    "MIN": "MIN",
}

MIN_GAMES_SEASON = 10  # aby se v sezónním žebříčku neobjevili hráči s 1 zápasem


# --------------------------------------------------------------------------- #
# Pomocné funkce
# --------------------------------------------------------------------------- #

def _nba_season_from_date(d: datetime) -> str:
    """Vrátí sezónu nba_api (např. 2026-27) pro dané datum."""
    year = d.year
    # Sezóna začíná v říjnu; leden–červenec patří k sezóně začínající předchozí rok
    start = year if d.month >= 9 else year - 1
    return f"{start}-{str(start + 1)[-2:]}"


def current_season() -> str:
    """Aktuální sezóna nba_api (např. '2026-27')."""
    return _nba_season_from_date(datetime.now(timezone.utc))


def _season_label(season: str) -> str:
    return season


def _to_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except Exception:
        return default


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def _pct(value: Any) -> float:
    """nba_api vrací procenta jako 0.0–1.0 (u V3 boxscore) – sjednotíme na 0–1."""
    v = _to_float(value)
    if v > 1.5:  # některé endpointy vrací 45.3 místo 0.453
        v = v / 100.0
    return round(v, 3)


def _minutes_to_str(value: Any) -> str:
    if value is None:
        return "0:00"
    if isinstance(value, str):
        return value
    total = _to_int(value)
    return f"{total // 60}:{total % 60:02d}"


def _split_team_codes(raw: str) -> List[str]:
    """'TOT' nebo 'PHX/LAL' → [] nebo ['PHX', 'LAL'] (hráč v sezóně vystřídal týmy)."""
    raw = (raw or "").strip().upper()
    if not raw or raw in ("TOT", "N/A"):
        return []
    return [code for code in raw.replace("-", "/").split("/") if len(code) == 3]


def _team_name(abbr: str) -> str:
    return TEAM_CZ.get(abbr, abbr)


# --------------------------------------------------------------------------- #
# 1) Výsledky zápasů
# --------------------------------------------------------------------------- #

def _fetch_team_game_log(season: str) -> List[Dict[str, Any]]:
    key = f"team_gamelog:{season}"
    cached = _cache_get(key, GAMES_TTL)
    if cached is not None:
        return cached

    try:
        from nba_api.stats.endpoints import leaguegamelog

        endpoint = leaguegamelog.LeagueGameLog(
            season=season,
            season_type_all_star="Regular Season",
            player_or_team_abbreviation="T",
            timeout=25,
        )
        df = endpoint.get_data_frames()[0]
    except Exception as exc:  # pragma: no cover – síťová chyba
        logger.error("Nelze načíst LeagueGameLog pro sezónu %s: %s", season, exc)
        raise NewsDataError(f"Výsledky zápasů sezóny {season} se nepodařilo načíst z NBA API.") from exc

    if df is None or df.empty:
        return _cache_set(key, [])

    rows: List[Dict[str, Any]] = []
    for _, r in df.iterrows():
        rows.append(
            {
                "game_id": str(r.get("GAME_ID") or ""),
                "game_date": str(r.get("GAME_DATE") or ""),
                "season_id": str(r.get("SEASON_ID") or ""),
                "team": str(r.get("TEAM_ABBREVIATION") or ""),
                "team_name": str(r.get("TEAM_NAME") or ""),
                "matchup": str(r.get("MATCHUP") or ""),
                "wl": str(r.get("WL") or ""),
                "pts": _to_int(r.get("PTS")),
                "reb": _to_int(r.get("REB")),
                "ast": _to_int(r.get("AST")),
                "fgm": _to_int(r.get("FGM")),
                "fga": _to_int(r.get("FGA")),
                "fg3m": _to_int(r.get("FG3M")),
                "fg3a": _to_int(r.get("FG3A")),
                "ftm": _to_int(r.get("FTM")),
                "fta": _to_int(r.get("FTA")),
                "tov": _to_int(r.get("TOV")),
                "stl": _to_int(r.get("STL")),
                "blk": _to_int(r.get("BLK")),
                "plus_minus": _to_float(r.get("PLUS_MINUS")),
            }
        )
    return _cache_set(key, rows)


def _available_seasons() -> List[str]:
    """Sezóny, které NBA API skutečně vydává (od 1996-97 dál)."""
    current = _nba_season_from_date(datetime.now(timezone.utc))
    start_year = int(current.split("-")[0])
    seasons = []
    for y in range(start_year, 1995, -1):
        seasons.append(f"{y}-{str(y + 1)[-2:]}")
    return seasons


def get_recent_games(days_back: int = 1) -> Dict[str, Any]:
    """
    Vrátí poslední odehraný hrací den (a případně předchozí dny).

    days_back = 1 znamená "poslední hrací den" (což je prakticky vždy
    "výsledky z předchozího dne" – pokud se právě hraje, přidá i dnešek).
    """
    days_back = max(1, min(int(days_back or 1), 7))

    rows: List[Dict[str, Any]] = []
    season_used = None
    # Zkusíme aktuální sezónu, případně tu předchozí (mezisezóna / prázdniny)
    for season in _available_seasons()[:2]:
        try:
            rows = _fetch_team_game_log(season)
        except NewsDataError:
            rows = []
        if rows:
            season_used = season
            break

    if not rows:
        raise NewsDataError("Výsledky zápasů nejsou momentálně dostupné z NBA API.")

    dates = sorted({r["game_date"] for r in rows}, reverse=True)
    selected_dates = dates[:days_back]

    # Seskupení dvojic týmů do jednoho zápasu
    games: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        if r["game_date"] not in selected_dates:
            continue
        gid = r["game_id"]
        game = games.setdefault(
            gid,
            {
                "game_id": gid,
                "game_date": r["game_date"],
                "teams": [],
            },
        )
        game["teams"].append(r)

    result: List[Dict[str, Any]] = []
    for gid, game in games.items():
        if len(game["teams"]) < 2:
            continue
        home = None
        away = None
        for t in game["teams"]:
            if "vs." in t["matchup"]:
                home = t
            else:
                away = t
        if home is None or away is None:
            home, away = game["teams"][0], game["teams"][1]

        result.append(
            {
                "game_id": gid,
                "game_date": game["game_date"],
                "home": {
                    "abbr": home["team"],
                    "name": _team_name(home["team"]),
                    "pts": home["pts"],
                    "wl": home["wl"],
                    "stats": {k: home[k] for k in ("reb", "ast", "fgm", "fga", "fg3m", "fg3a", "ftm", "fta", "tov", "stl", "blk")},
                },
                "away": {
                    "abbr": away["team"],
                    "name": _team_name(away["team"]),
                    "pts": away["pts"],
                    "wl": away["wl"],
                    "stats": {k: away[k] for k in ("reb", "ast", "fgm", "fga", "fg3m", "fg3a", "ftm", "fta", "tov", "stl", "blk")},
                },
                "winner": home["team"] if home["pts"] >= away["pts"] else away["team"],
                "margin": abs(home["pts"] - away["pts"]),
            }
        )

    result.sort(key=lambda g: (g["game_date"], g["game_id"]), reverse=True)

    return {
        "season": season_used,
        "dates": selected_dates,
        "last_game_date": selected_dates[0] if selected_dates else None,
        "games": result,
        "source": "NBA API – LeagueGameLog",
    }


# --------------------------------------------------------------------------- #
# 1b) Dnešní rozpis (co se hraje dnes a v noci)
# --------------------------------------------------------------------------- #

SCHEDULE_TTL = 180  # 3 minuty – stavy zápasů se mění


def get_schedule(day_offset: int = 0) -> Dict[str, Any]:
    """
    Rozpis zápasů na zvolený den (0 = dnes, 1 = zítra, -1 = včera).

    Časy se vracejí v UTC a UI si je převede do lokálního pásma.
    """
    day_offset = max(-1, min(int(day_offset or 0), 7))
    target = (datetime.now(timezone.utc) + timedelta(days=day_offset)).date()
    date_str = target.isoformat()

    key = f"schedule:{date_str}"
    cached = _cache_get(key, SCHEDULE_TTL)
    if cached is not None:
        return cached

    try:
        from nba_api.stats.endpoints import scoreboardv3

        endpoint = _retry(
            lambda: scoreboardv3.ScoreboardV3(game_date=date_str, league_id="00", timeout=30),
            what=f"rozpis {date_str}",
        )
        frames = endpoint.get_data_frames()
    except Exception as exc:  # pragma: no cover
        logger.error("Rozpis na %s se nepodařilo načíst: %s", date_str, exc)
        raise NewsDataError("Rozpis zápasů se nepodařilo načíst z NBA API (zkus to za chvíli znovu).")

    games_df = frames[1] if len(frames) > 1 else None
    teams_df = frames[2] if len(frames) > 2 else None
    if games_df is None or games_df.empty:
        payload = {"date": date_str, "day_offset": day_offset, "games": [], "source": "NBA API – ScoreboardV3"}
        return _cache_set(key, payload)

    by_game: Dict[str, List[Dict[str, Any]]] = {}
    if teams_df is not None and not teams_df.empty:
        for _, r in teams_df.iterrows():
            by_game.setdefault(str(r.get("gameId")), []).append(
                {
                    "abbr": str(r.get("teamTricode") or ""),
                    "name": f"{str(r.get('teamCity') or '')} {str(r.get('teamName') or '')}".strip(),
                    "wins": _to_int(r.get("wins")),
                    "losses": _to_int(r.get("losses")),
                    "score": _to_int(r.get("score")),
                }
            )

    games: List[Dict[str, Any]] = []
    for _, g in games_df.iterrows():
        gid = str(g.get("gameId") or "")
        sides = by_game.get(gid, [])
        # NBA Scoreboard uvádí jako první domácí tým
        home = sides[0] if sides else None
        away = sides[1] if len(sides) > 1 else None
        if not home or not away:
            continue
        status = _to_int(g.get("gameStatus"))  # 1 = plánováno, 2 = hraje se, 3 = dohráno
        games.append(
            {
                "game_id": gid,
                "status": status,
                "status_text": str(g.get("gameStatusText") or "").strip(),
                "tipoff_utc": str(g.get("gameTimeUTC") or ""),
                "label": str(g.get("gameLabel") or ""),
                "sublabel": str(g.get("gameSubLabel") or ""),
                "home": home,
                "away": away,
            }
        )

    games.sort(key=lambda x: x["tipoff_utc"])
    payload = {
        "date": date_str,
        "day_offset": day_offset,
        "games": games,
        "source": "NBA API – ScoreboardV3",
    }
    return _cache_set(key, payload)


# --------------------------------------------------------------------------- #
# 2) Boxscore zápasu
# --------------------------------------------------------------------------- #

def _minutes_total(value: Any) -> float:
    """'32:37' → 32.62 (minuty jako desetinné číslo)."""
    if value is None:
        return 0.0
    if isinstance(value, str):
        if ":" in value:
            m, _, sec = value.partition(":")
            return _to_float(m) + _to_float(sec) / 60.0
        return _to_float(value)
    return _to_float(value)


def _player_row_v3(r: Any) -> Dict[str, Any]:
    first = str(r.get("firstName") or "").strip()
    last = str(r.get("familyName") or "").strip()
    name = f"{first} {last}".strip() or str(r.get("nameI") or "")
    minutes = r.get("minutes")
    position = str(r.get("position") or "")
    return {
        "player_id": _to_int(r.get("personId")),
        "name": name,
        "team": str(r.get("teamTricode") or ""),
        "position": position,
        "starter": position != "",
        "minutes": _minutes_to_str(minutes),
        "pts": _to_int(r.get("points")),
        "reb": _to_int(r.get("reboundsTotal")),
        "oreb": _to_int(r.get("reboundsOffensive")),
        "dreb": _to_int(r.get("reboundsDefensive")),
        "ast": _to_int(r.get("assists")),
        "stl": _to_int(r.get("steals")),
        "blk": _to_int(r.get("blocks")),
        "tov": _to_int(r.get("turnovers")),
        "pf": _to_int(r.get("foulsPersonal")),
        "fgm": _to_int(r.get("fieldGoalsMade")),
        "fga": _to_int(r.get("fieldGoalsAttempted")),
        "fg_pct": _pct(r.get("fieldGoalsPercentage")),
        "fg3m": _to_int(r.get("threePointersMade")),
        "fg3a": _to_int(r.get("threePointersAttempted")),
        "fg3_pct": _pct(r.get("threePointersPercentage")),
        "ftm": _to_int(r.get("freeThrowsMade")),
        "fta": _to_int(r.get("freeThrowsAttempted")),
        "ft_pct": _pct(r.get("freeThrowsPercentage")),
        "plus_minus": _to_float(r.get("plusMinusPoints")),
        "comment": str(r.get("comment") or ""),
    }


def _team_row_v3(r: Any) -> Dict[str, Any]:
    return {
        "team": str(r.get("teamTricode") or ""),
        "name": _team_name(str(r.get("teamTricode") or "")),
        "minutes": _minutes_to_str(r.get("minutes")),
        "pts": _to_int(r.get("points")),
        "reb": _to_int(r.get("reboundsTotal")),
        "ast": _to_int(r.get("assists")),
        "stl": _to_int(r.get("steals")),
        "blk": _to_int(r.get("blocks")),
        "tov": _to_int(r.get("turnovers")),
        "pf": _to_int(r.get("foulsPersonal")),
        "fgm": _to_int(r.get("fieldGoalsMade")),
        "fga": _to_int(r.get("fieldGoalsAttempted")),
        "fg_pct": _pct(r.get("fieldGoalsPercentage")),
        "fg3m": _to_int(r.get("threePointersMade")),
        "fg3a": _to_int(r.get("threePointersAttempted")),
        "fg3_pct": _pct(r.get("threePointersPercentage")),
        "ftm": _to_int(r.get("freeThrowsMade")),
        "fta": _to_int(r.get("freeThrowsAttempted")),
        "ft_pct": _pct(r.get("freeThrowsPercentage")),
    }


def _aggregate_team_stats(players: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Součty týmu ze statistik jednotlivých hráčů (FG, 3P, FT, doskoky…)."""
    buckets: Dict[str, Dict[str, Any]] = {}
    for p in players:
        abbr = p["team"]
        if not abbr:
            continue
        b = buckets.setdefault(
            abbr,
            {
                "team": abbr,
                "name": _team_name(abbr),
                "minutes_total": 0.0,
                "pts": 0,
                "reb": 0,
                "ast": 0,
                "stl": 0,
                "blk": 0,
                "tov": 0,
                "pf": 0,
                "fgm": 0,
                "fga": 0,
                "fg3m": 0,
                "fg3a": 0,
                "ftm": 0,
                "fta": 0,
            },
        )
        b["minutes_total"] += _minutes_total(p["minutes"])
        for f in ("pts", "reb", "ast", "stl", "blk", "tov", "pf", "fgm", "fga", "fg3m", "fg3a", "ftm", "fta"):
            b[f] += p[f]

    out: List[Dict[str, Any]] = []
    for b in buckets.values():
        out.append(
            {
                "team": b["team"],
                "name": b["name"],
                "minutes": _minutes_to_str(round(b["minutes_total"] * 60)),
                "pts": b["pts"],
                "reb": b["reb"],
                "ast": b["ast"],
                "stl": b["stl"],
                "blk": b["blk"],
                "tov": b["tov"],
                "pf": b["pf"],
                "fgm": b["fgm"],
                "fga": b["fga"],
                "fg_pct": round(b["fgm"] / b["fga"], 3) if b["fga"] else 0.0,
                "fg3m": b["fg3m"],
                "fg3a": b["fg3a"],
                "fg3_pct": round(b["fg3m"] / b["fg3a"], 3) if b["fg3a"] else 0.0,
                "ftm": b["ftm"],
                "fta": b["fta"],
                "ft_pct": round(b["ftm"] / b["fta"], 3) if b["fta"] else 0.0,
            }
        )
    out.sort(key=lambda t: -t["pts"])
    return out


def get_game_boxscore(game_id: str) -> Dict[str, Any]:
    """Boxscore zápasu – statistiky všech hráčů rozdělené po týmech."""
    game_id = str(game_id or "").strip()
    if not game_id.isdigit() or len(game_id) < 8:
        raise NewsDataError("Neplatné ID zápasu.")

    key = f"boxscore:{game_id}"
    cached = _cache_get(key, BOXSCORE_TTL)
    if cached is not None:
        return cached

    from nba_api.stats.endpoints import boxscoretraditionalv3

    frames = None
    last_error: Optional[Exception] = None
    for attempt in range(3):
        try:
            endpoint = boxscoretraditionalv3.BoxScoreTraditionalV3(game_id=game_id, timeout=30)
            frames = endpoint.get_data_frames()
            break
        except Exception as exc:  # pragma: no cover – NBA API občas zahodí spojení
            last_error = exc
            logger.warning("Boxscore %s – pokus %s selhal: %s", game_id, attempt + 1, exc)
            time.sleep(2 + attempt * 3)

    if frames is None:
        logger.error("Boxscore zápasu %s selhalo: %s", game_id, last_error)
        raise NewsDataError("Boxscore tohoto zápasu se nepodařilo načíst z NBA API.")

    if not frames or frames[0] is None or frames[0].empty:
        raise NewsDataError("Pro tento zápas nejsou statistiky k dispozici.")

    players = [_player_row_v3(r) for _, r in frames[0].iterrows()]
    # Pozor: řádek 1 v této verzi NBA API obsahuje součty po čtvrtinách, ne týmové
    # součty (ty jsou až ve třetím dataframe). Týmové součty proto počítáme sami
    # ze hráčských statistik – jsou přesné a odpovídají skóre zápasu.
    team_stats = _aggregate_team_stats(players)

    # Rozdělení po týmech
    teams: Dict[str, Dict[str, Any]] = {}
    for p in players:
        abbr = p["team"]
        if not abbr:
            continue
        t = teams.setdefault(abbr, {"abbr": abbr, "name": _team_name(abbr), "players": []})
        t["players"].append(p)

    for abbr, t in teams.items():
        # Seřadit: základní pětka první, pak podle bodů
        t["players"].sort(key=lambda x: (0 if x["starter"] else 1, -x["pts"]))
        summary = next((s for s in team_stats if s["team"] == abbr), None)
        t["totals"] = summary
        t["pts"] = summary["pts"] if summary else sum(p["pts"] for p in t["players"])

    ordered = sorted(teams.values(), key=lambda t: -t["pts"])

    payload = {
        "game_id": game_id,
        "teams": ordered,
        "team_totals": team_stats,
        "source": "NBA API – BoxScoreTraditionalV3",
        "cache": "fresh",
    }
    return _cache_set(key, payload)


# --------------------------------------------------------------------------- #
# 3) Lídři statistik
# --------------------------------------------------------------------------- #

def _leaderboard_from_df(
    df: Any,
    stat: str,
    value_key: str,
    per_game: bool,
    limit: int,
    min_gp: int = 0,
    team_filter: Optional[List[str]] = None,
    season: Optional[str] = None,
) -> List[Dict[str, Any]]:
    if df is None or df.empty:
        return []

    rows: List[Dict[str, Any]] = []
    for _, r in df.iterrows():
        gp = _to_int(r.get("GP"))
        if gp < min_gp:
            continue
        team = str(r.get("TEAM_ABBREVIATION") or r.get("TEAM") or "")
        if team_filter and team not in team_filter:
            continue
        value = _to_float(r.get(value_key))
        if stat.endswith("_PCT") and per_game is False:
            # procenta necháváme v 0-1
            value = _pct(r.get(value_key))
        rows.append(
            {
                "player_id": _to_int(r.get("PLAYER_ID")),
                "name": str(r.get("PLAYER_NAME") or r.get("PLAYER") or ""),
                "team": team,
                "team_name": _team_name(team),
                "gp": gp,
                "season": season,
                "season_span": season,
                "value": round(value, 3 if stat.endswith("_PCT") else 1),
                "per_game": per_game,
                "total": round(_to_float(r.get(value_key)) * gp, 1) if per_game else round(value, 1),
            }
        )

    rows.sort(key=lambda x: x["value"], reverse=True)
    rows = rows[:limit]
    for idx, row in enumerate(rows, start=1):
        row["rank"] = idx
    return rows


def _all_time_rows(
    stat: str,
    per_game: bool,
    limit: int,
    team_filter: Optional[List[str]] = None,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    All-Time žebříček z kariérních tabulek celé NBA (1946-47 → dnes).

    Zdroj: Basketball-Reference Career Leaders (celá historie ligy).
    Pro průměr na zápas se použije žebříček "na zápas" (počítá se
    z kariérních zápasů, ne jen od roku 1997).
    """
    from services import nba_alltime, nba_career_leaders

    stat = stat.upper()
    key = f"{stat}:pg" if per_game and stat in nba_career_leaders.SOURCES_PER_GAME else stat
    src_rows = nba_career_leaders.leaders(key)
    gp_by_name = {
        r["name"].strip().lower(): int(float(r["value"]))
        for r in nba_career_leaders.leaders("GP")
    }
    people = nba_alltime.people_index()
    by_name = {}
    for pid, info in people.items():
        nm = (info.get("name") or "").strip().lower()
        if nm and nm not in by_name:
            by_name[nm] = (pid, info)

    rows: List[Dict[str, Any]] = []
    for src in src_rows:
        pid, info = by_name.get(src["name"].strip().lower(), (0, {}))
        career_gp = gp_by_name.get(src["name"].strip().lower(), 0)
        first = int(info.get("from_year") or 0)
        last = int(info.get("to_year") or 0)
        rows.append(
            {
                "player_id": pid,
                "name": src["name"],
                "team": info.get("team") or "",
                "team_name": _team_name(info.get("team") or ""),
                "gp": career_gp,
                "career_gp": career_gp,
                "seasons": max(0, last - first + 1),
                "season_span": (
                    f"{first}–{last}" if first and last and last > first else str(first or "")
                ),
                "value": round(float(src["value"]), 3 if per_game else 1),
                "total": round(float(src["value"]), 1),
                "hall_of_fame": bool(src.get("hall_of_fame")),
                "official_rank": src.get("rank"),
                "per_game": per_game,
                "season": None,
            }
        )

    rows = rows[:limit]
    for idx, row in enumerate(rows, start=1):
        row["rank"] = idx
        row["official_rank"] = src_rows[idx - 1]["rank"] if idx - 1 < len(src_rows) else idx
    return rows, []


def _franchise_rows(
    stat: str,
    per_game: bool,
    limit: int,
    team_abbr: str,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    Lídři franšízy z celé historie klubu (od založení ligy).

    NBA vydává týmové tabulky jen od 1996-97, proto se bere hotový klubový
    kariérní žebříček z Basketball-Reference – jeden request na klub,
    uložený na disku, takže načtení je pak okamžité.
    Průměr na zápas se dopočítá z klubových součtů a klubových zápasů.
    """
    from services import nba_alltime, nba_career_leaders

    abbr = team_abbr.upper()
    stat = stat.upper()
    src = nba_career_leaders.franchise_rows(abbr, stat)
    if not src:
        raise NewsDataError(
            f"Žebříček klubu {abbr} se nepodařilo načíst (zkus to za chvíli znovu)."
        )

    gp_by_name = {
        r["name"].strip().lower(): float(r["value"])
        for r in nba_career_leaders.franchise_rows(abbr, "GP")
    }
    people = nba_alltime.people_index()
    by_name = {}
    for pid, info in people.items():
        nm = (info.get("name") or "").strip().lower()
        if nm and nm not in by_name:
            by_name[nm] = (pid, info)

    rows: List[Dict[str, Any]] = []
    for r in src:
        name = r["name"]
        games = gp_by_name.get(name.strip().lower(), 0.0)
        value = float(r["value"])
        if per_game:
            if not games:
                continue
            value = value / games
        pid, info = by_name.get(name.strip().lower(), (0, {}))
        first = int(info.get("from_year") or 0)
        last = int(info.get("to_year") or 0)
        rows.append(
            {
                "player_id": pid,
                "name": name,
                "team": abbr,
                "team_name": _team_name(abbr),
                "gp": int(games),
                "career_gp": int(games),
                "seasons": 0,
                "season_span": "",
                "value": round(value, 3 if per_game else 1),
                "total": round(float(r["value"]), 1),
                "hall_of_fame": bool(r.get("hall_of_fame")),
                "official_rank": r.get("rank"),
                "per_game": per_game,
                "season": None,
            }
        )

    rows = rows[:limit]
    for idx, row in enumerate(rows, start=1):
        row["rank"] = idx
    return rows, []


def _franchise_roster_ids(team_id: int, abbr: str) -> set:
    """
    ID hráčů, kteří za klub nastoupili od 1996-97 (rychlé, ze sezónních tabulek),
    plus jedničky klubových rekordů (FranchiseLeaders) pro jistotu.
    """
    from nba_api.stats.endpoints import leaguedashplayerstats
    from nba_api.stats.static import players as static_players

    ids: set = set()
    seasons = _available_seasons()
    name_to_id = {p["full_name"].strip().lower(): int(p["id"]) for p in static_players.get_players()}

    codes = set(TEAM_ALIASES.get(abbr, [abbr]))
    for season in seasons:
        try:
            df = leaguedashplayerstats.LeagueDashPlayerStats(
                season=season,
                per_mode_detailed="Totals",
                season_type_all_star="Regular Season",
                timeout=25,
            ).get_data_frames()[0]
        except Exception:
            continue
        if df.empty:
            continue
        for _, r in df.iterrows():
            code = str(r.get("TEAM_ABBREVIATION") or "").upper()
            franchise = _FRANCHISE_OF.get(code, code)
            if franchise in codes or code in codes:
                pid = int(r.get("PLAYER_ID") or 0)
                if pid:
                    ids.add(pid)

    return ids


_FRANCHISE_POOL_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "franchise_pool.json"
)
_FRANCHISE_POOL_LOCK = threading.Lock()


def _franchise_pool_get(abbr: str) -> Optional[List[Dict[str, Any]]]:
    """Předpočítaní hráči klubu (včetně statistik za franšízu) ze souboru."""
    try:
        with _FRANCHISE_POOL_LOCK:
            if not os.path.exists(_FRANCHISE_POOL_FILE):
                return None
            with open(_FRANCHISE_POOL_FILE, encoding="utf-8") as fh:
                data = json.load(fh)
        block = (data or {}).get(abbr.upper()) or {}
        players = block.get("players_list")
        return players or None
    except Exception as exc:  # pragma: no cover
        logger.warning("Týmový pool nešel načíst: %s", exc)
        return None


def _TEAM_ID_BY_ABBR() -> Dict[str, int]:
    from nba_api.stats.static import teams

    out: Dict[str, int] = {}
    for t in teams.get_teams():
        out[t["abbreviation"].upper()] = int(t["id"])
    return out


def get_leaders(
    mode: str = "season",
    stat: str = "PTS",
    per_game: bool = True,
    team: Optional[str] = None,
    season: Optional[str] = None,
    limit: int = 15,
) -> Dict[str, Any]:
    """
    Žebříčky lídrů.

    mode:
      * "alltime" – historické žebříčky (poskládané ze všech sezón 1996-97 → dnes)
      * "season"  – lídři aktuální (nebo zvolené) sezóny
      * "team"    – lídři vybraného týmu / franšízy
    stat: klíč ze STAT_DEFS
    per_game: True = průměr na zápas, False = celkový součet
    """
    stat = (stat or "PTS").upper()
    if stat not in STAT_DEFS:
        stat = "PTS"
    mode = (mode or "season").lower()
    if mode not in ("alltime", "season", "team"):
        mode = "season"
    limit = max(1, min(int(limit or 15), 50))

    def_info = STAT_DEFS[stat]
    if not def_info["per_game_available"]:
        per_game = False

    season = season or _nba_season_from_date(datetime.now(timezone.utc))

    team_abbr = (team or "").upper() if team else None
    if mode == "team" and not team_abbr:
        raise NewsDataError("Pro režim 'tým' je potřeba vybrat tým.")

    key = f"leaders:{mode}:{stat}:{per_game}:{team_abbr}:{season}:{limit}"
    cached = _cache_get(key, LEADERS_TTL)
    if cached is not None:
        return cached

    rows: List[Dict[str, Any]] = []
    note = ""

    # ---------- All-Time ----------
    if mode == "alltime":
        rows, missing = _all_time_rows(stat=stat, per_game=per_game, limit=limit)
        note = (
            "Počítá se celá historie NBA od 1946-47 – včetně hráčů před rokem 1997 "
            "(Jordan, Kareem, Wilt, Russell…). Zdrojem jsou kariérní žebříčky "
            "Basketball-Reference; u průměru na zápas se počítá z kariérních zápasů. "
            "Zisky a bloky se evidují od 1973-74, trojky od 1979-80."
        )
        if missing:
            note += f" Pozor: {len(missing)} sezón se nepodařilo stáhnout, zkus to prosím znovu."
        title = f"All-Time lídři – {def_info['label']}"

    # ---------- Sezóna ----------
    elif mode == "season":
        from nba_api.stats.endpoints import leaguedashplayerstats

        season_key = f"season_df:{season}:{per_game}"
        df = _cache_get(season_key, LEADERS_TTL)
        if df is None:
            per_mode = "PerGame" if per_game else "Totals"
            try:
                df = _retry(
                    lambda: leaguedashplayerstats.LeagueDashPlayerStats(
                        season=season,
                        per_mode_detailed=per_mode,
                        season_type_all_star="Regular Season",
                        timeout=30,
                    ).get_data_frames()[0],
                    what=f"sezóna {season}",
                )
            except Exception as exc:  # pragma: no cover
                logger.error("Sezónní lídři (%s, %s) selhali: %s", season, stat, exc)
                raise NewsDataError(
                    f"Sezónní žebříčky {season} se nepodařilo načíst z NBA API (zkus to za chvíli znovu)."
                ) from exc
            _cache_set(season_key, df)

        rows = _leaderboard_from_df(
            df,
            stat=stat,
            value_key=stat,
            per_game=per_game,
            limit=limit,
            min_gp=MIN_GAMES_SEASON,
            season=season,
        )
        title = f"Lídři sezóny {season} – {def_info['label']}"

    # ---------- Tým / franšíza ----------
    else:
        rows, missing = _franchise_rows(
            stat=stat, per_game=per_game, limit=limit, team_abbr=team_abbr
        )
        note = (
            f"Žebříček franšízy {_team_name(team_abbr)} pochází z týmových tabulek NBA a "
            "pokrývá celou historii klubu (u Lakers i Minneapolis, u Warriors i Philadelphii). "
            "Počítají se jen zápasy a statistiky odehrané za tuto franšízu."
        )
        if missing:
            note += f" Pozor: {len(missing)} sezón se nepodařilo stáhnout, zkus to prosím znovu."
        title = f"Lídři franšízy {_team_name(team_abbr)} – {def_info['label']}"

    payload = {
        "mode": mode,
        "stat": stat,
        "stat_label": def_info["label"],
        "per_game": per_game,
        "season": season,
        "team": team_abbr,
        "team_name": _team_name(team_abbr) if team_abbr else None,
        "title": title,
        "note": note,
        "rows": rows,
        "source": {
            "alltime": "Basketball-Reference – Career Leaders (celá historie NBA od 1946-47)",
            "team": "NBA – FranchiseLeaders (týmové žebříčky, celá historie klubu)",
            "season": f"NBA – LeagueDashPlayerStats (sezóna {season})",
        }[mode],
    }
    return _cache_set(key, payload)


def get_standings(season: Optional[str] = None) -> Dict[str, Any]:
    """
    Tabulka sezóny – obě konference, seřazené podle nasazení do play-off.

    Vrací i rekordy (doma/venku, posledních 10, série) a body na zápas,
    protože v NBA jsou to základní ukazatele formy.
    """
    from nba_api.stats.endpoints import leaguestandingsv3

    season = season or current_season()
    key = f"standings:{season}"
    cached = _cache_get(key, 300)
    if cached is not None:
        return cached

    try:
        df = _retry(
            lambda: leaguestandingsv3.LeagueStandingsV3(
                season=season,
                season_type="Regular Season",
                league_id="00",
                timeout=30,
            ).get_data_frames()[0],
            what=f"tabulka {season}",
        )
    except Exception as exc:  # pragma: no cover
        logger.error("Tabulka %s se nepodařila načíst: %s", season, exc)
        raise NewsDataError(
            f"Tabulku sezóny {season} se nepodařilo načíst z NBA API (zkus to za chvíli znovu)."
        ) from exc

    from nba_api.stats.static import teams as static_teams

    abbr_by_id = {int(t["id"]): t["abbreviation"] for t in static_teams.get_teams()}

    # forma: posledních 5 zápasů každého týmu (nejnovější první)
    form: Dict[str, List[Dict[str, Any]]] = {}
    try:
        log = _fetch_team_game_log(season)
        by_team: Dict[str, List[Dict[str, Any]]] = {}
        for r in log:
            by_team.setdefault(r["team"], []).append(r)
        for abbr, games in by_team.items():
            games.sort(key=lambda g: (g["game_date"], g["game_id"]), reverse=True)
            entries = []
            for g in games[:5]:
                plus_minus = g.get("plus_minus")
                opp_pts = (
                    int(round(g["pts"] - plus_minus)) if plus_minus is not None else None
                )
                entries.append(
                    {
                        "game_id": g["game_id"],
                        "date": g["game_date"],
                        "wl": g["wl"],
                        "pts": g["pts"],
                        "opp_pts": opp_pts,
                        "matchup": g["matchup"],
                        "opponent": (g["matchup"].split()[-1] if g["matchup"] else ""),
                        "home": "vs." in g["matchup"],
                    }
                )
            form[abbr] = entries
    except Exception as exc:  # forma není kritická, tabulka musí fungovat i bez ní
        logger.warning("Formu posledních zápasů se nepodařilo načíst: %s", exc)

    def _fmt_pct(value: Any) -> float:
        return round(_to_float(value), 3)

    rows: List[Dict[str, Any]] = []
    for _, r in df.iterrows():
        team_id = _to_int(r.get("TeamID"))
        abbr = abbr_by_id.get(team_id, "")
        rows.append(
            {
                "team_id": team_id,
                "abbr": abbr,
                "name": _team_name(abbr) if abbr else f"{r.get('TeamCity')} {r.get('TeamName')}",
                "conference": "East" if str(r.get("Conference")) == "East" else "West",
                "division": str(r.get("Division") or ""),
                "rank": _to_int(r.get("PlayoffRank")),
                "wins": _to_int(r.get("WINS")),
                "losses": _to_int(r.get("LOSSES")),
                "win_pct": _fmt_pct(r.get("WinPCT")),
                "games_back": _to_float(r.get("ConferenceGamesBack")),
                "conf_record": str(r.get("ConferenceRecord") or ""),
                "home": str(r.get("HOME") or ""),
                "road": str(r.get("ROAD") or ""),
                "l10": str(r.get("L10") or ""),
                "streak": str(r.get("strCurrentStreak") or ""),
                "ppg": round(_to_float(r.get("PointsPG")), 1),
                "opp_ppg": round(_to_float(r.get("OppPointsPG")), 1),
                "diff": round(_to_float(r.get("DiffPointsPG")), 1),
                "form": form.get(abbr, []),
            }
        )

    east = sorted([x for x in rows if x["conference"] == "East"], key=lambda x: (x["rank"] or 99))
    west = sorted([x for x in rows if x["conference"] == "West"], key=lambda x: (x["rank"] or 99))

    for group in (east, west):
        for idx, row in enumerate(group, start=1):
            row["seed"] = idx

    payload = {
        "season": season,
        "east": east,
        "west": west,
        "updated": datetime.now(timezone.utc).isoformat(),
        "source": "NBA – LeagueStandingsV3 (základní část)",
    }
    return _cache_set(key, payload)


def get_teams() -> List[Dict[str, Any]]:
    """Seznam týmů pro přepínač v UI."""
    current = [{"abbr": abbr, "name": _team_name(abbr)} for abbr in TEAM_ALIASES.keys()]
    current.sort(key=lambda t: t["name"])
    return current


def get_stats_definitions() -> List[Dict[str, Any]]:
    return [
        {
            "key": k,
            "label": v["label"],
            "short": v["short"],
            "per_game_available": v["per_game_available"],
        }
        for k, v in STAT_DEFS.items()
    ]

"""
Záložní zdroj dat: ESPN.

Proč to existuje
----------------
`stats.nba.com` (přes nba_api) blokuje požadavky z datových center. Doma na
počítači všechno funguje, ale na serveru (Render) se tabulka, žebříčky ani
rozpis zápasů nenačtou – NBA na ně z cloudu neodpovídá.

ESPN má veřejné API, které z cloudu funguje, a nabízí totéž:
  * tabulku sezóny (`standings`)
  * žebříčky hráčů (`leaders`)
  * rozpis a výsledky zápasů na den (`scoreboard`)

Tenhle modul vrací data ve **stejném tvaru**, jaký skládá `nba_news.py`
z nba_api. Volající kód se tak nemění – jen se nejdřív zkusí NBA a když
neodpovídá, sáhne sem.

Co je jinak než u NBA
---------------------
* ESPN nemá české názvy týmů – bere se `TEAM_CZ` z `nba_news.py`.
* Forma posledních zápasů u tabulky je jen jako série „10-5", ne seznam
  zápasů s protivníky. Když NBA neodpovídá, `form` zůstane prázdné.
* Žebříčky jsou jen sezónní (All-Time a franšízy jsou z Basketball-Reference
  v `.json.gz`, ty fungují vždycky).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

ESPN_STANDINGS = "https://site.api.espn.com/apis/v2/sports/basketball/nba/standings"
ESPN_LEADERS = (
    "https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba"
    "/seasons/{year}/types/2/leaders"
)
ESPN_ATHLETE = (
    "https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba"
    "/seasons/{year}/athletes/{athlete_id}"
)
ESPN_TEAM = (
    "https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba"
    "/seasons/{year}/teams/{team_id}"
)
ESPN_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"

TIMEOUT = 15
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; NBA-Nerd-Vault/1.0)"}

# kategorie v ESPN → náš klíč ze STAT_DEFS
ESPN_STAT_CATEGORY = {
    "PTS": "pointsPerGame",
    "REB": "reboundsPerGame",
    "AST": "assistsPerGame",
    "STL": "stealsPerGame",
    "BLK": "blocksPerGame",
    "FG3M": "3PointsMadePerGame",
    "MIN": "minutesPerGame",
    "FG_PCT": "fieldGoalPercentage",
    "FG3_PCT": "3PointPct",
    "FT_PCT": "FreeThrowPct",
}

# ESPN má i celkové součty (`points`), pro per_game=False
ESPN_STAT_TOTAL = {
    "PTS": "points",
}

_CONF_BY_GROUP = {"5": "East", "6": "West"}

# ESPN vrací u žebříčků jen odkazy na hráče a týmy. Stahovat 50 detailů při
# každém požadavku by trvalo 20 s, proto se jména pamatují. Sportovci se
# nemění, týmová zkratka u hráče se může (výměna) – proto kratší platnost.
_ATHLETE_CACHE: Dict[int, str] = {}
_TEAM_CACHE: Dict[tuple[int, int], tuple[float, str]] = {}
TEAM_CACHE_TTL = 3600 * 12

# Paralelní stahování: 25 jmen sériově = 20 s, paralelně pod 2 s.
from concurrent.futures import ThreadPoolExecutor


def _get_json(url: str) -> Optional[Dict[str, Any]]:
    """Stáhne JSON; při chybě vrátí None (volající zkusí jiný zdroj)."""
    try:
        res = requests.get(url, timeout=TIMEOUT, headers=HEADERS)
        if res.status_code != 200:
            logger.warning("ESPN %s → HTTP %s", url, res.status_code)
            return None
        return res.json()
    except Exception as exc:  # pragma: no cover – síťová chyba
        logger.warning("ESPN %s selhalo: %s", url, exc)
        return None


def season_year(season: str) -> int:
    """'2026-27' → 2027 (ESPN značí sezónu rokem, kdy končí)."""
    try:
        start = int(season.split("-")[0])
        return start + 1
    except Exception:
        return datetime.now(timezone.utc).year


def season_from_year(year: int) -> str:
    """2027 → '2026-27'."""
    return f"{year - 1}-{str(year)[-2:]}"


def _stat(stats: List[Dict[str, Any]], *names: str) -> Any:
    """Najde hodnotu ve seznamu statistik podle `name` nebo `type`."""
    for item in stats:
        if item.get("name") in names or item.get("type") in names:
            return item.get("displayValue")
    return None


def _split_record(value: Any) -> tuple[int, int]:
    """'12-5' → (12, 5)."""
    if not value or "-" not in str(value):
        return 0, 0
    left, _, right = str(value).partition("-")
    try:
        return int(left), int(right)
    except ValueError:
        return 0, 0


def standings(season: str, team_cz: Dict[str, str]) -> Optional[Dict[str, Any]]:
    """
    Tabulka sezóny ve stejném tvaru jako `nba_news.get_standings()`.

    Vrací None, když ESPN nic nevrátí.
    """
    data = _get_json(ESPN_STANDINGS)
    if not data or not data.get("children"):
        return None

    rows: List[Dict[str, Any]] = []
    for group in data["children"]:
        conference = "East" if "East" in str(group.get("name", "")) else "West"
        entries = (group.get("standings") or {}).get("entries") or []
        for entry in entries:
            team = entry.get("team") or {}
            stats = entry.get("stats") or []
            abbr = str(team.get("abbreviation") or "").upper()
            wins, losses = _split_record(_stat(stats, "overall"))
            ppg = _stat(stats, "avgPointsFor")
            opp = _stat(stats, "avgPointsAgainst")
            diff = _stat(stats, "differential")
            rows.append(
                {
                    "team_id": int(team.get("id") or 0),
                    "abbr": abbr,
                    "name": team_cz.get(abbr, team.get("displayName") or abbr),
                    "conference": conference,
                    "division": "",
                    "rank": int(float(_stat(stats, "playoffSeed") or 0)),
                    "wins": wins,
                    "losses": losses,
                    "win_pct": round(wins / (wins + losses), 3) if wins + losses else 0.0,
                    "games_back": _num(_stat(stats, "gamesBehind")),
                    "conf_record": str(_stat(stats, "vs. Conf.") or ""),
                    "home": str(_stat(stats, "Home") or ""),
                    "road": str(_stat(stats, "Road") or ""),
                    "l10": str(_stat(stats, "Last Ten Games") or ""),
                    "streak": str(_stat(stats, "streak") or ""),
                    "ppg": round(_num(ppg), 1),
                    "opp_ppg": round(_num(opp), 1),
                    "diff": round(_num(diff), 1),
                    "form": [],
                }
            )

    if not rows:
        return None

    east = sorted([r for r in rows if r["conference"] == "East"], key=lambda r: r["rank"] or 99)
    west = sorted([r for r in rows if r["conference"] == "West"], key=lambda r: r["rank"] or 99)
    for group in (east, west):
        for idx, row in enumerate(group, start=1):
            row["seed"] = idx

    return {
        "season": season,
        "east": east,
        "west": west,
        "updated": datetime.now(timezone.utc).isoformat(),
        "source": "ESPN (záložní zdroj – NBA API z tohoto serveru neodpovídá)",
    }


def _num(value: Any) -> float:
    try:
        return float(str(value).replace("+", ""))
    except (TypeError, ValueError):
        return 0.0


def _athlete_name(athlete_id: int, year: int) -> str:
    if athlete_id in _ATHLETE_CACHE:
        return _ATHLETE_CACHE[athlete_id]
    data = _get_json(ESPN_ATHLETE.format(year=year, athlete_id=athlete_id))
    name = str((data or {}).get("displayName") or (data or {}).get("fullName") or "")
    if name:
        _ATHLETE_CACHE[athlete_id] = name
    return name


def _team_abbr(team_id: int, year: int) -> str:
    key = (team_id, year)
    hit = _TEAM_CACHE.get(key)
    if hit and (datetime.now(timezone.utc).timestamp() - hit[0]) < TEAM_CACHE_TTL:
        return hit[1]
    data = _get_json(ESPN_TEAM.format(year=year, team_id=team_id))
    abbr = str((data or {}).get("abbreviation") or "").upper()
    if abbr:
        _TEAM_CACHE[key] = (datetime.now(timezone.utc).timestamp(), abbr)
    return abbr


_GP_CACHE: Dict[str, int] = {}


def _athlete_gp(athlete_id: Optional[int], year: int) -> int:
    """
    Počet odehraných zápasů hráče v sezóně.

    Bez toho se v žebříčku ukazovalo 0 zápasů u všech hráčů – a protože se
    průměr počítá jen od určitého počtu zápasů, vypadalo to jako chyba.
    """
    if not athlete_id:
        return 0
    key = f"{athlete_id}:{year}"
    if key in _GP_CACHE:
        return _GP_CACHE[key]
    data = _get_json(
        "https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba"
        f"/seasons/{year}/types/2/athletes/{athlete_id}/statistics/0"
    )
    gp = 0
    if data:
        for cat in ((data.get("splits") or {}).get("categories")) or []:
            for stat in cat.get("stats") or []:
                if stat.get("name") == "gamesPlayed":
                    gp = int(_num(stat.get("value")))
                    break
    _GP_CACHE[key] = gp
    return gp


def leaders(
    season: str,
    stat: str,
    per_game: bool,
    limit: int,
    team_cz: Dict[str, str],
) -> Optional[List[Dict[str, Any]]]:
    """
    Sezónní žebříček ve tvaru `_leaderboard_from_df()`.

    ESPN vrací jen odkazy (`$ref`) na hráče a týmy, takže se jména dotahují
    zvlášť. Aby to nebylo 50 požadavků, kešuje se jméno i tým v paměti.
    """
    year = season_year(season)
    category = ESPN_STAT_CATEGORY.get(stat)
    if not category:
        return None
    if not per_game and stat in ESPN_STAT_TOTAL:
        category = ESPN_STAT_TOTAL[stat]

    data = _get_json(ESPN_LEADERS.format(year=year))
    if not data:
        return None

    block = None
    for item in data.get("categories") or []:
        if item.get("name") == category:
            block = item
            break
    if not block:
        return None

    entries = (block.get("leaders") or [])[: max(limit, 15)]
    athlete_ids = [_id_from_ref((e.get("athlete") or {}).get("$ref") or "") for e in entries]
    team_ids = [_id_from_ref((e.get("team") or {}).get("$ref") or "") for e in entries]

    # jména, týmy a počet zápasů paralelně – sériově to trvalo 20 s
    with ThreadPoolExecutor(max_workers=12) as pool:
        names = list(pool.map(lambda i: _athlete_name(i, year) if i else "", athlete_ids))
        abbrs = list(pool.map(lambda i: _team_abbr(i, year) if i else "", team_ids))
        games = list(pool.map(lambda i: _athlete_gp(i, year) if i else 0, athlete_ids))

    rows: List[Dict[str, Any]] = []
    for entry, athlete_id, team_id, name, abbr, gp in zip(
        entries, athlete_ids, team_ids, names, abbrs, games
    ):
        value = entry.get("value")
        if value is None:
            value = _num(entry.get("displayValue"))
        value = float(value)
        # ESPN dává procenta jako 66.434, my je držíme v 0-1 (0.664)
        if stat.endswith("_PCT") and value > 1.5:
            value = value / 100.0
        rows.append(
            {
                "player_id": athlete_id,
                "name": name,
                "team": abbr,
                "team_name": team_cz.get(abbr, abbr),
                "gp": gp,
                "season": season,
                "season_span": season,
                "value": round(value, 3 if stat.endswith("_PCT") else 1),
                "per_game": per_game,
                "total": round(value * 100, 1) if stat.endswith("_PCT") else round(value, 1),
            }
        )

    rows = [r for r in rows if r["name"]]
    # u procent i u součtů platí: vyšší = lepší
    rows.sort(key=lambda r: r["value"], reverse=True)
    rows = rows[:limit]
    for idx, row in enumerate(rows, start=1):
        row["rank"] = idx
    return rows or None


def _id_from_ref(ref: str) -> int:
    """'…/athletes/3945274?lang=en' → 3945274"""
    try:
        tail = ref.split("/athletes/")[-1].split("/teams/")[-1]
        return int(tail.split("?")[0])
    except Exception:
        return 0


def scoreboard(date_str: str, day_offset: int, team_cz: Dict[str, str]) -> Optional[Dict[str, Any]]:
    """
    Rozpis a výsledky na den – stejný tvar jako `nba_news.get_schedule()`.

    ESPN bere datum jako `YYYYMMDD`.
    """
    compact = date_str.replace("-", "")
    data = _get_json(f"{ESPN_SCOREBOARD}?dates={compact}")
    if not data:
        return None

    games: List[Dict[str, Any]] = []
    for event in data.get("events") or []:
        competitions = event.get("competitions") or []
        if not competitions:
            continue
        comp = competitions[0]
        sides = {"home": None, "away": None}
        for competitor in comp.get("competitors") or []:
            team = competitor.get("team") or {}
            abbr = str(team.get("abbreviation") or "").upper()
            scores = competitor.get("score")
            side = "home" if competitor.get("homeAway") == "home" else "away"
            record = ""
            for rec in competitor.get("records") or []:
                if rec.get("type") in ("total", "overall"):
                    record = str(rec.get("summary") or "")
                    break
            wins, losses = _split_record(record)
            sides[side] = {
                "abbr": abbr,
                "name": team_cz.get(abbr, team.get("displayName") or abbr),
                "wins": wins,
                "losses": losses,
                "score": int(_num(scores)) if scores is not None else None,
            }
        if not sides["home"] or not sides["away"]:
            continue

        status = comp.get("status") or {}
        status_type = status.get("type") or {}
        state = str(status_type.get("state") or "pre")
        status_code = {"pre": 1, "in": 2, "post": 3}.get(state, 1)
        games.append(
            {
                "game_id": str(event.get("id") or ""),
                "status": status_code,
                "status_text": str(status_type.get("shortDetail") or status_type.get("detail") or ""),
                "tipoff_utc": str(event.get("date") or ""),
                "label": str(event.get("season", {}).get("slug") or ""),
                "sublabel": "",
                "home": sides["home"],
                "away": sides["away"],
            }
        )

    games.sort(key=lambda g: g["tipoff_utc"])
    return {
        "date": date_str,
        "day_offset": day_offset,
        "games": games,
        "source": "ESPN (záložní zdroj – NBA API z tohoto serveru neodpovídá)",
    }

"""
Zdroj sezónních dat: ESPN.

Proč to existuje
----------------
`stats.nba.com` blokuje požadavky z datových center (Render, cloud). Doma
všechno funguje, na serveru se profil hráče načítal 45 s a „poslední zápas"
nešel vůbec. ESPN má veřejné API, které z cloudu funguje.

Tenhle modul dodává **sezónní statistiky hráče** ve stejném tvaru, jaký
skládá `nba_fetcher` z nba_api – jen jinam napsaný:

    {"season_id": "2026-27", "gp": 14, "pts": 27.4, "reb": 6.1, ...}

ESPN ale vrací jen odkazy (`$ref`), takže se musí dotahovat zvlášť:
`statisticslog` → odkazy na sezóny → detail statistik. Proto je tu keš;
bez ní by jeden profil znamenal 20 požadavků.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

ESPN_BASE = "https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba"

TIMEOUT = 12
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; NBA-Nerd-Vault/1.0)"}

# ESPN klíč statistiky → náš klíč. Bereme průměry (avg…), protože zbytek
# aplikace pracuje s průměrem na zápas.
STAT_MAP = {
    "avgPoints": "pts",
    "avgRebounds": "reb",
    "avgOffensiveRebounds": "oreb",
    "avgAssists": "ast",
    "avgSteals": "stl",
    "avgBlocks": "blk",
    "avgTurnovers": "tov",
    "avgFieldGoalsMade": "fgm",
    "avgFieldGoalsAttempted": "fga",
    "avgThreePointFieldGoalsMade": "fg3m",
    "avgThreePointFieldGoalsAttempted": "fg3a",
    "avgFreeThrowsMade": "ftm",
    "avgFreeThrowsAttempted": "fta",
    "avgMinutes": "min_per_game",
    "avgFouls": "pf",
    "gamesPlayed": "gp",
    "gamesStarted": "gs",
}

# keš: hráč → seznam sezón (mění se jen jednou za zápas, TTL v aplikaci)
_CACHE: Dict[str, Any] = {}
_CACHE_TTL = 3600  # 1 hodina


def _cached(key: str, fn):
    hit = _CACHE.get(key)
    if hit and (datetime.now(timezone.utc).timestamp() - hit[0]) < _CACHE_TTL:
        return hit[1]
    value = fn()
    if value is not None:
        _CACHE[key] = (datetime.now(timezone.utc).timestamp(), value)
    return value


def _get_json(url: str) -> Optional[Dict[str, Any]]:
    try:
        res = requests.get(url, timeout=TIMEOUT, headers=HEADERS)
        if res.status_code != 200:
            return None
        return res.json()
    except Exception as exc:  # pragma: no cover – síťová chyba
        logger.warning("ESPN %s selhalo: %s", url, exc)
        return None


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _season_from_year(year: Any) -> str:
    """2027 → '2026-27'."""
    try:
        number = int(year)
    except (TypeError, ValueError):
        return ""
    return f"{number - 1}-{str(number)[-2:]}"


def _year_from_season(season: str) -> int:
    """'2026-27' → 2027."""
    try:
        return int(season.split("-")[0]) + 1
    except Exception:
        return datetime.now(timezone.utc).year


def _split_stats(url: str) -> Dict[str, Any]:
    """Z detailu statistik vytáhne všechna `name` → `value`."""
    data = _get_json(url)
    if not data:
        return {}
    values: Dict[str, Any] = {}
    categories = ((data.get("splits") or {}).get("categories")) or []
    for cat in categories:
        for stat in cat.get("stats") or []:
            name = stat.get("name")
            if name:
                values[str(name)] = stat.get("value")
    return values


def _to_row(season_id: str, values: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Převede hodnoty z ESPN na náš řádek sezóny."""
    gp = int(_num(values.get("gamesPlayed")))
    if gp <= 0:
        return None

    def avg(key: str) -> Optional[float]:
        source = None
        for espn_key, our_key in STAT_MAP.items():
            if our_key == key:
                source = values.get(espn_key)
                break
        if source is None:
            return None
        return round(_num(source), 3)

    fgm, fga = avg("fgm"), avg("fga")
    fg3m, fg3a = avg("fg3m"), avg("fg3a")
    ftm, fta = avg("ftm"), avg("fta")
    return {
        "season_id": season_id,
        "gp": gp,
        "gs": int(_num(values.get("gamesStarted"))),
        "pts": avg("pts"),
        "reb": avg("reb"),
        "ast": avg("ast"),
        "stl": avg("stl"),
        "blk": avg("blk"),
        "tov": avg("tov"),
        "pf": avg("pf"),
        "min_per_game": avg("min_per_game"),
        "fgm": fgm,
        "fga": fga,
        "fg3m": fg3m,
        "fg3a": fg3a,
        "ftm": ftm,
        "fta": fta,
        "fg_pct": round(fgm / fga, 3) if fgm and fga else None,
        "fg3_pct": round(fg3m / fg3a, 3) if fg3m and fg3a else None,
        "ft_pct": round(ftm / fta, 3) if ftm and fta else None,
        "poss100_pts": None,
        "poss100_reb": None,
        "poss100_ast": None,
        "poss100_stl": None,
        "poss100_blk": None,
        "poss100_tov": None,
    }


def _plain(text: Any) -> str:
    """Jméno bez diakritiky, mezer a interpunkce (Dončić → doncic)."""
    t = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z]", "", t.lower())


def _is_espn_id(value: int) -> bool:
    """Pozná číslo, které už je ESPN ID (profil v ESPN existuje)."""
    payload = _get_json(f"{ESPN_BASE}/athletes/{int(value)}") or {}
    return bool(payload.get("fullName"))


# Čísla, o kterých aplikace ví, že jsou už ESPN ID (legendy v seznamu
# kandidátů). Ta se nepřekládají – jinak by se ESPN 1035 (Jordan) bralo
# jako NBA číslo a přeložilo na jiného hráče.
KNOWN_ESPN_IDS: set = set()


def mark_espn_ids(ids) -> None:
    """Zapamatuje si čísla, která pocházejí přímo z ESPN."""
    for value in ids or []:
        try:
            KNOWN_ESPN_IDS.add(int(value))
        except (TypeError, ValueError):
            continue


def resolve_id(nba_id: int, name: str = "") -> Optional[int]:
    """
    Přeloží NBA ID hráče na ID v ESPN (jsou jiná: LeBron 2544 → 1966).

    Jméno se vezme z registru NBA a dohledá přes vyhledávání ESPN;
    bere se jen přesná shoda jména v NBA. Když se nenajde, vrátí původní ID.
    """
    if name:
        return search_athlete(name)

    def _do() -> int:
        name = None
        try:
            from nba_api.stats.static import players

            for pl in players.get_players():
                if int(pl["id"]) == int(nba_id):
                    name = pl["full_name"]
                    break
        except Exception:
            name = None
        if not name:
            # Registr NBA je v cloudu nedostupný – jméno se vezme z paměti
            # aplikace (profily hráčů, kariérní mezipaměť), jinak by se
            # ID nepřeložilo a statistiky by se hledaly pod špatným číslem.
            try:
                from services import nba_external

                name = nba_external._name_for(int(nba_id))
            except Exception:
                name = None
        if not name or str(name).isdigit():
            return int(nba_id) if _is_espn_id(nba_id) else None

        # Stejné číslo může v ESPN patřit jinému sportovci (NBA 893 Jordan =
        # ESPN 893 Jameel Watkins). ESPN ID se bere jen při shodě jména.
        payload = _get_json(f"{ESPN_BASE}/athletes/{int(nba_id)}") or {}
        if payload.get("fullName") and _plain(payload["fullName"]) == _plain(name):
            return int(nba_id)

        found = search_athlete(str(name))
        if found:
            return int(found)
        from urllib.parse import quote

        data = _get_json(
            "https://site.web.api.espn.com/apis/search/v2?limit=10&type=player&query=" + quote(name)
        )
        want = _plain(name)
        for res in (data or {}).get("results") or []:
            for item in res.get("contents") or []:
                if item.get("type") != "player" or str(item.get("description")) != "NBA":
                    continue
                if _plain(item.get("displayName", "")) != want:
                    continue
                m = re.search(r"a:(\d+)", str(item.get("uid", "")))
                if m:
                    return int(m.group(1))
        return None

    return _cached(f"resolve:{nba_id}", _do)


def search_athlete(name: str) -> Optional[int]:
    """
    Najde hráče podle jména přímo v ESPN (bez registru NBA).

    Na serveru je registr NBA nedostupný, takže bez tohohle by se legendy
    jako Kobe, Wade nebo Pippen vůbec nedohledaly a AI by navrhovala
    náhodné současné hráče.
    """
    wanted = _plain(name)
    if not wanted:
        return None

    def _do() -> Optional[int]:
        from urllib.parse import quote

        data = _get_json(
            "https://site.web.api.espn.com/apis/search/v2?limit=20&type=player&query="
            + quote(name)
        )
        # Ve výsledcích je víc sportovců stejného jména (Michael Jordan
        # z NCAAF, MMA…). Bere se první NBA, u kterého profil potvrdí
        # odehranou kariéru – jinak se hráč plete s jiným sportem.
        for res in (data or {}).get("results") or []:
            for item in res.get("contents") or []:
                if item.get("type") != "player" or str(item.get("description")) != "NBA":
                    continue
                if _plain(item.get("displayName", "")) != wanted:
                    continue
                m = re.search(r"a:(\d+)", str(item.get("uid", "")))
                if not m:
                    continue
                espn_id = int(m.group(1))
                payload = _get_json(f"{ESPN_BASE}/athletes/{espn_id}") or {}
                if _plain(payload.get("fullName") or payload.get("displayName") or "") != wanted:
                    continue
                if not (payload.get("statisticslog") or payload.get("statistics")):
                    continue
                return espn_id
        return None

    return _cached(f"search:{wanted}", _do)


_AVERAGE_FIELDS = {**STAT_MAP, "fieldGoalPct": "fg_pct",
                   "threePointFieldGoalPct": "fg3_pct", "freeThrowPct": "ft_pct"}


def _compact_seasons(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    averages = next((c for c in data.get("categories", []) if c.get("name") == "averages"), {})
    teams = data.get("teams") or {}
    grouped: Dict[str, list] = {}
    for entry in averages.get("statistics", []):
        season = _season_from_year((entry.get("season") or {}).get("year"))
        if not season:
            continue
        row: Dict[str, Any] = {"season_id": season, "team_abbreviation":
                              (teams.get(entry.get("teamSlug")) or {}).get("abbreviation") or ""}
        for key, raw in zip(averages.get("names", []), entry.get("stats", [])):
            parts = key.split("-")
            if len(parts) == 2 and all(p in _AVERAGE_FIELDS for p in parts):
                pair = str(raw).split("-", 1)
                if len(pair) == 2:
                    for part, value in zip(parts, pair):
                        row[_AVERAGE_FIELDS[part]] = _num(value, None)
            elif key in _AVERAGE_FIELDS:
                field = _AVERAGE_FIELDS[key]
                value = _num(raw, None)
                row[field] = value / 100 if value is not None and field.endswith("_pct") else value
        if row.get("gp") and row.get("pts") is not None:
            grouped.setdefault(season, []).append(row)
    rows = []
    for season, entries in sorted(grouped.items()):
        combined = next((r for r in entries if r["team_abbreviation"] in {"", "TOT"}), None)
        if len(entries) == 1 or combined:
            rows.append(combined or entries[0])
            continue
        row = {"season_id": season, "team_abbreviation": "TOT", "gp": sum(r["gp"] for r in entries)}
        for field in set().union(*(r.keys() for r in entries)) - set(row):
            values = [(r[field], r["gp"]) for r in entries if r.get(field) is not None]
            if values:
                row[field] = sum(v for v, _ in values) if field == "gs" else sum(v * n for v, n in values) / sum(n for _, n in values)
        for pct, made, attempts in (("fg_pct", "fgm", "fga"), ("fg3_pct", "fg3m", "fg3a"), ("ft_pct", "ftm", "fta")):
            if row.get(attempts) and row.get(made) is not None:
                row[pct] = row[made] / row[attempts]
        rows.append(row)
    return rows


def player_season_stats(player_id: int, *, name: str = "", espn_id: Optional[int] = None,
                        allow_legacy: bool = True) -> Optional[List[Dict[str, Any]]]:
    """
    Všechny sezóny hráče podle ESPN, ve tvaru jako z nba_api.

    Vrací None, když ESPN hráče nezná. Pořadí je od nejstarší sezóny.
    """
    player_id = espn_id if espn_id is not None else resolve_id(player_id, name)
    if not player_id:
        return None
    from services import nba_external

    key = f"espn-summary:v1:{player_id}"
    cached = nba_external._cache_get(key, 6 * 3600)
    if cached:
        return cached
    summary = _get_json(
        "https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba/"
        f"athletes/{player_id}/stats?seasontype=2"
    )
    rows = _compact_seasons(summary or {})
    if rows:
        nba_external._cache_set(key, rows)
        return rows
    stale = nba_external._cache_get(key, nba_external.TTL_PROFILE)
    if stale or not allow_legacy:
        return stale

    def load() -> Optional[List[Dict[str, Any]]]:
        log = _get_json(f"{ESPN_BASE}/athletes/{player_id}/statisticslog")
        if not log:
            return None

        # 1) z logu vytáhneme odkazy na statistiky sezón
        refs: List[tuple[str, str]] = []
        for entry in log.get("entries") or []:
            season_ref = ((entry.get("season") or {}).get("$ref")) or ""
            season_id = ""
            if "/seasons/" in season_ref:
                season_id = _season_from_year(season_ref.split("/seasons/")[-1].split("?")[0])
            if not season_id:
                continue
            for block in entry.get("statistics") or []:
                if block.get("type") != "total":
                    continue
                stat_ref = ((block.get("statistics") or {}).get("$ref")) or ""
                # types/2 = základní část, types/3 = play-off. Play-off řádky
                # (3–20 zápasů) by zkreslily tabulku i kariérní průměr.
                if stat_ref:
                    # ESPN uvádí v logu často jen play-off odkaz → vždy se
                    # sáhne na základní část (types/2) téže sezóny.
                    stat_ref = re.sub(r"/types/\d+/", "/types/2/", stat_ref)
                    if all(r[0] != season_id for r in refs):
                        refs.append((season_id, stat_ref))

        if not refs:
            return None

        # 2) detaily paralelně – sériově by to trvalo půl minuty
        with ThreadPoolExecutor(max_workers=8) as pool:
            details = list(pool.map(lambda item: _split_stats(item[1]), refs))

        rows: List[Dict[str, Any]] = []
        for (season_id, _), values in zip(refs, details):
            row = _to_row(season_id, values)
            if row:
                rows.append(row)

        if not rows:
            return None
        rows.sort(key=lambda r: r["season_id"])
        return rows

    return _cached(f"seasons:{player_id}", load)


def career_stats(player_id: int, name: str = "", *, espn_id: Optional[int] = None,
                 metadata_only: bool = False) -> Optional[Dict[str, Any]]:
    """
    Kariérní průměry hráče podle ESPN (jeden dotaz).

    Používá se jako náhrada, když NBA API neodpovídá a Basketball-Reference
    nestačí. Vrací i pozici a míry, protože je má ve stejném dokumentu.
    `name` slouží k ověření, že profil v ESPN opravdu patří tomuhle hráči.
    """
    player_id = espn_id if espn_id is not None else resolve_id(player_id, name)
    if not player_id:
        return None
    wanted = _plain(name) if name else ""

    def load() -> Optional[Dict[str, Any]]:
        data = _get_json(f"{ESPN_BASE}/athletes/{player_id}")
        if not data:
            return None
        # Číslo NBA ID se v ESPN trefí i do jiného sportovce (Jordan 893 =
        # Jameel Watkins). Bez jména by se hráči ukázala cizí čísla.
        full = _plain(data.get("fullName") or data.get("displayName") or "")
        if wanted and full != wanted:
            logger.info(
                "ESPN profil %s patří jinému hráči (%s) – přeskakuje se",
                player_id,
                full or "?",
            )
            return None

        # kariérní statistiky jsou odkaz v `statistics`
        values: Dict[str, Any] = {}
        stat_ref = ((data.get("statistics") or {}).get("$ref")) or ""
        if stat_ref and not metadata_only:
            values = _split_stats(stat_ref)

        row = _to_row("career", values) if values else None
        if not row:
            # bez statistik aspoň jméno a míry
            row = {"gp": 0}
        row["name"] = data.get("displayName") or data.get("fullName") or ""
        position = ((data.get("position") or {}).get("abbreviation")) or ""
        row["position"] = str(position).strip()
        height_in = _num(data.get("height"), 0.0)  # ESPN uvádí palce
        if height_in > 0:
            row["height_cm"] = round(height_in * 2.54, 1)
        weight_lb = _num(data.get("weight"), 0.0)  # libry
        if weight_lb > 0:
            row["weight_kg"] = round(weight_lb * 0.45359237, 1)
        return row if row.get("gp") or row.get("name") else None

    return _cached(f"career:{player_id}:{wanted}:{metadata_only}", load)


GAMELOG_URL = (
    "https://site.api.espn.com/apis/common/v3/sports/basketball/nba/athletes/{id}/gamelog"
)


def last_game(player_id: int) -> Optional[Dict[str, Any]]:
    """
    Poslední odehraný zápas hráče.

    Pozor: `sports.core.api…/athletes/{id}/gamelog` vrací 404. Seznam zápasů
    je jen na `site.api.espn.com/apis/common/v3/…/athletes/{id}/gamelog`,
    a to v jiném tvaru – `labels` + `stats` jako seznam hodnot.

    Vrací stejný tvar jako `/api/players/{id}/last-game`.
    """
    player_id = resolve_id(player_id)

    def load() -> Optional[Dict[str, Any]]:
        data = _get_json(GAMELOG_URL.format(id=player_id))
        if not data:
            return None

        labels: List[str] = [str(x).upper() for x in (data.get("labels") or [])]
        if not labels:
            return None

        # poslední blok sezóny = aktuální, v něm kategorie s odehranými zápasy
        events: List[Dict[str, Any]] = []
        for block in data.get("seasonTypes") or []:
            for cat in block.get("categories") or []:
                for event in cat.get("events") or []:
                    events.append(event)
        if not events:
            return None

        # ESPN řadí zápasy po měsících a typech sezóny (příprava je na konci),
        # takže poslední v seznamu není nejnovější – bere se nejvyšší datum.
        meta_all = data.get("events") or {}
        played = max(
            events,
            key=lambda ev: str((meta_all.get(str(ev.get("eventId"))) or {}).get("gameDate") or ""),
        )
        event_id = str(played.get("eventId") or "")
        stats = played.get("stats") or []
        values = {}
        for idx, label in enumerate(labels):
            if idx < len(stats):
                values[label] = stats[idx]

        meta = (data.get("events") or {}).get(event_id) or {}

        def pair(label: str) -> tuple[float, float]:
            """'8-13' → (8, 13)"""
            raw = str(values.get(label) or "0-0")
            left, _, right = raw.partition("-")
            return _num(left), _num(right)

        fgm, fga = pair("FG")
        fg3m, fg3a = pair("3PT")
        ftm, fta = pair("FT")
        pts = int(_num(values.get("PTS")))
        reb = _num(values.get("REB"))
        ast = _num(values.get("AST"))
        stl = _num(values.get("STL"))
        blk = _num(values.get("BLK"))
        tov = _num(values.get("TO"))
        minutes = str(int(_num(values.get("MIN"))))

        my_team = str(((meta.get("team") or {}).get("abbreviation")) or "").upper()
        opp_team = str((meta.get("opponent") or {}).get("abbreviation") or "").upper()
        at_vs = str(meta.get("atVs") or "")
        is_home = at_vs == "vs"
        wl = str(meta.get("gameResult") or "")
        if not wl:
            mine = _num(meta.get("homeTeamScore") if is_home else meta.get("awayTeamScore"))
            theirs = _num(meta.get("awayTeamScore") if is_home else meta.get("homeTeamScore"))
            if mine and theirs:
                wl = "W" if mine > theirs else "L"

        return {
            "game_date": str(meta.get("gameDate") or "")[:10],
            "matchup": f"{my_team} {'vs.' if is_home else '@'} {opp_team}".strip(),
            "my_team": my_team,
            "opp_team": opp_team,
            "is_home": is_home,
            "wl": wl,
            "minutes": minutes,
            "pts": pts,
            "reb": reb,
            "ast": ast,
            "stl": stl,
            "blk": blk,
            "tov": tov,
            "fgm": fgm,
            "fga": fga,
            "fg_pct": round(fgm / fga, 3) if fga else 0.0,
            "fg3m": fg3m,
            "fg3a": fg3a,
            "fg3_pct": round(fg3m / fg3a, 3) if fg3a else 0.0,
            "ftm": ftm,
            "fta": fta,
            "ft_pct": round(ftm / fta, 3) if fta else 0.0,
            "plus_minus": 0,
            "source": "ESPN (záložní zdroj)",
        }

    return _cached(f"lastgame:{player_id}", load)


def _team_id(player_id: int) -> Optional[int]:
    """ID klubu hráče – pozná se z detailu hráče."""
    data = _get_json(f"{ESPN_BASE}/athletes/{player_id}")
    if not data:
        return None
    ref = ((data.get("team") or {}).get("$ref")) or ""
    try:
        return int(ref.split("/teams/")[-1].split("?")[0])
    except Exception:
        return None

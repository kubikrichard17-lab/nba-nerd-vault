"""
Externí zdroje pro porovnávání hráčů („nejbližší hráč").

Žádná vlastní databáze hráčů: kariérní čísla se berou z internetu.

Zdroje:
    1. NBA API (stats.nba.com, přes balíček nba_api) – oficiální sezónní data.
    2. Basketball-Reference (HTML tabulky) – kariérní součty, funguje i tam,
       kde NBA API nemá data.

Cache:
    Malý gzip soubor `external_pool.json.gz` NENÍ databáze hráčů. Je to
    jen dočasná paměť odpovědí, aby se stejný hráč nestahoval při každém
    kliknutí. Záznamy samy vyprší (TTL), takže se obsah obnovuje z internetu.
"""

from __future__ import annotations

import gzip
import json
import logging
import os
import re
import threading
import time
import unicodedata
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

CACHE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "external_pool.json.gz")
CACHE_VERSION = 1

# Jak dlouho zůstává odpověď v paměti (sekundy)
TTL_STATS = 3 * 24 * 3600      # sezónní průměry
TTL_PROFILE = 14 * 24 * 3600   # kariérní profil (výška, váha, pozice)
TTL_SLUG = 30 * 24 * 3600      # převod jména na adresu Basketball-Reference

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
BBREF_SEARCH = "https://www.basketball-reference.com/search/search.fcgi?search="

_LOCK = threading.Lock()
_MEMORY: Optional[Dict[str, Any]] = None


# --------------------------------------------------------------------------- #
# 1. Malá paměť s časem vypršení
# --------------------------------------------------------------------------- #

def _now() -> int:
    return int(time.time())


def _load_memory() -> Dict[str, Any]:
    global _MEMORY
    if _MEMORY is not None:
        return _MEMORY
    if os.path.exists(CACHE_PATH):
        try:
            with gzip.open(CACHE_PATH, "rt", encoding="utf-8") as fh:
                payload = json.load(fh)
            if payload.get("version") == CACHE_VERSION:
                _MEMORY = payload
                return payload
        except Exception as exc:  # pragma: no cover
            logger.warning("Paměť externích dat se nepodařilo načíst: %s", exc)
    _MEMORY = {"version": CACHE_VERSION, "entries": {}}
    return _MEMORY


def _save_memory(payload: Dict[str, Any]) -> None:
    try:
        with gzip.open(CACHE_PATH, "wt", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)
    except Exception as exc:  # pragma: no cover
        logger.warning("Paměť externích dat se nepodařilo uložit: %s", exc)


def _cache_get(key: str, ttl: int) -> Optional[Any]:
    payload = _load_memory()
    entry = payload["entries"].get(key)
    if not entry:
        return None
    if _now() - entry.get("t", 0) > ttl:
        return None
    return entry.get("v")


_DIRTY = {"count": 0}


def _cache_set(key: str, value: Any) -> None:
    """
    Zapíše odpověď do paměti. Na disk se ukládá jen občas – jinak by
    každé uložení zdržovalo požadavek.
    """
    payload = _load_memory()
    payload["entries"][key] = {"t": _now(), "v": value}
    _DIRTY["count"] += 1
    if len(payload["entries"]) > 6000:
        cutoff = _now() - TTL_PROFILE
        payload["entries"] = {
            k: v for k, v in payload["entries"].items() if v.get("t", 0) >= cutoff
        }
    if _DIRTY["count"] % 40 == 0:
        with _LOCK:
            _save_memory(payload)


def flush() -> None:
    """Uloží paměť na disk (volá se při ukončení aplikace)."""
    with _LOCK:
        _save_memory(_load_memory())


# --------------------------------------------------------------------------- #
# 2. Pomocné funkce
# --------------------------------------------------------------------------- #

def normalize_name(name: str) -> str:
    """Jméno bez diakritiky a malými písmeny – Dončić == Doncic."""
    text = unicodedata.normalize("NFKD", name or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = re.sub(r"\b(jr|sr|ii|iii|iv)\b", " ", text)
    return " ".join(text.split())


def _num(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(str(value).replace(",", "").replace("%", ""))
    except (TypeError, ValueError):
        return default


def _http_get(url: str, timeout: int = 25) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "ignore")


def _clean(cell: str) -> str:
    return re.sub(r"<[^>]+>", "", cell or "").strip()


# --------------------------------------------------------------------------- #
# 3. Basketball-Reference – kariérní součty a profil hráče
# --------------------------------------------------------------------------- #

def bbref_slug(name: str) -> Optional[str]:
    """
    Najde adresu hráče na Basketball-Reference (např. thompkl01).
    Hledá se přes jejich vyhledávání, výsledek se pamatuje.
    """
    key = f"slug:{normalize_name(name)}"
    cached = _cache_get(key, TTL_SLUG)
    if cached:
        return cached or None

    try:
        html = _http_get(BBREF_SEARCH + urllib.parse.quote(name), timeout=20)
    except Exception as exc:  # pragma: no cover
        logger.warning("Basketball-Reference hledání selhalo pro %s: %s", name, exc)
        # Známá jména mají adresu uloženou – vyhledávání bývá zablokované
        known = _SLUG_FALLBACK.get(normalize_name(name), "")
        if known:
            _cache_set(key, known)
        return known or None

    # Odkazy na hráče v odpovědi. Vyhledávání může vrátit i víc hráčů,
    # a brát naslepo první odkaz vede na cizí stránku (Bill Walton →
    # sharmbi01). Proto se vybírá ten, jehož jméno opravdu sedí.
    links = re.findall(r'/players/([a-z])/([a-z0-9]+)\.html[^>]*>([^<]*)<', html)
    if not links:
        links = [(m[0], m[1], "") for m in re.findall(r'/players/([a-z])/([a-z0-9]+)\.html', html)]

    wanted = normalize_name(name)
    slug = ""
    for letter, candidate, label in links:
        text = normalize_name(label or candidate)
        if not text:
            continue
        if text == wanted or text.startswith(wanted) or wanted.startswith(text):
            slug = candidate
            break

    if not slug and links:
        # Když jméno v odpovědi není, radši nic – špatný hráč je horší
        # než žádná data.
        logger.warning("Basketball-Reference: jméno %s v odpovědi nenalezeno", name)
        return _SLUG_FALLBACK.get(normalize_name(name), "") or None

    _cache_set(key, slug)
    return slug or None


def bbref_career(name: str) -> Optional[Dict[str, Any]]:
    """
    Kariérní součty a průměry z Basketball-Reference.
    Bere se souhrnný řádek „14 Yrs" z tabulky totals.
    """
    slug = bbref_slug(name)
    if not slug:
        return None

    key = f"bbref:{slug}"
    cached = _cache_get(key, TTL_STATS)
    if cached:
        return cached or None
    import sys

    letter = slug[0]
    url = f"https://www.basketball-reference.com/players/{letter}/{slug}.html"
    try:
        html = _http_get(url, timeout=30)
    except Exception as exc:  # pragma: no cover
        logger.warning("Basketball-Reference stránka selhala pro %s: %s", name, exc)
        return None

    table = re.search(r'<table[^>]*id="totals_stats"[^>]*>.*?</table>', html, re.S)
    if not table:
        _cache_set(key, {})
        return None

    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", table.group(0), re.S)
    header: List[str] = []
    if rows:
        header = [_clean(c) for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", rows[0], re.S)]
        # hlavička má u eFG% dlouhou poznámku, zkrať ji na název sloupce
        header = [re.sub(r"^(eFG%).*$", r"\1", h) for h in header]

    career_row: Optional[List[str]] = None
    for row in rows:
        cells = [_clean(c) for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", row, re.S)]
        if cells and re.match(r"^\d+\s*Yrs$", cells[0]):
            career_row = cells
            break
    import sys
    if not career_row:
        _cache_set(key, {})
        return None

    # Pozice a míry ze záhlaví stránky – funguje i pro hráče z 60. let
    position = ""
    pos_match = re.search(
        r"Position:\s*</strong>\s*([A-Za-z and\-]+?)\s*(?:&#9642;|<strong>)", html
    )
    if pos_match:
        position = " ".join(pos_match.group(1).split())

    height_cm = weight_kg = 0.0
    size_match = re.search(r"<span>(\d)-(\d+)</span>.*?<span>(\d+)lb</span>", html, re.S)
    if size_match:
        feet, inches, pounds = (float(x) for x in size_match.groups())
        height_cm = round((feet * 12 + inches) * 2.54, 1)
        weight_kg = round(pounds * 0.45359237, 1)

    # Některé buňky (prázdná pozice, poznámky) vypadnou, takže se čte
    # z konce tabulky, kde pořadí sloupců vždy sedí.
    # Součtový řádek má méně buněk než hlavička (chybí prázdná pozice),
    # takže se doplní zleva a čte se podle hlavičky.
    if len(career_row) < len(header):
        career_row = career_row[:2] + [""] * (len(header) - len(career_row)) + career_row[2:]

    def col(*names: str) -> float:
        for candidate in names:
            if candidate in header:
                idx = header.index(candidate)
                if idx < len(career_row):
                    return _num(career_row[idx])
        return 0.0

    gp = col("G")
    if gp <= 0:
        _cache_set(key, {})
        return None

    result = {
        "source": "Basketball-Reference",
        "url": url,
        "gp": gp,
        "pts": col("PTS") / gp,
        "reb": col("TRB") / gp,
        "ast": col("AST") / gp,
        "stl": col("STL") / gp,
        "blk": col("BLK") / gp,
        "tov": col("TOV") / gp,
        "fgm": col("FG") / gp,
        "fga": col("FGA") / gp,
        "fg3m": col("3P") / gp,
        "fg3a": col("3PA") / gp,
        "ftm": col("FT") / gp,
        "fta": col("FTA") / gp,
        "min_per_game": col("MP") / gp,
        "fg_pct": col("FG%") / 100.0 if col("FG%") > 1 else col("FG%"),
        "fg3_pct": col("3P%") / 100.0 if col("3P%") > 1 else col("3P%"),
        "ft_pct": col("FT%") / 100.0 if col("FT%") > 1 else col("FT%"),
        "position": position,
        "height_cm": height_cm,
        "weight_kg": weight_kg,
    }
    _cache_set(key, result)
    return result


# --------------------------------------------------------------------------- #
# 4. NBA API – sezónní průměry hráče
# --------------------------------------------------------------------------- #

def nba_info(player_id: int) -> Optional[Dict[str, Any]]:
    """
    Pozice, výška, váha a roky kariéry přímo z NBA API
    (CommonPlayerInfo). Jeden dotaz, kešovaný 14 dní.
    """
    key = f"nbainfo:{player_id}"
    cached = _cache_get(key, TTL_PROFILE)
    if cached is not None:
        return cached or None

    try:
        from nba_api.stats.endpoints import commonplayerinfo

        endpoint = commonplayerinfo.CommonPlayerInfo(player_id=player_id, timeout=20)
        frame = endpoint.common_player_info.get_data_frame()
    except Exception as exc:  # pragma: no cover
        logger.warning("NBA API profil %s selhal: %s", player_id, exc)
        return None

    if frame is None or frame.empty:
        _cache_set(key, {})
        return None

    row = frame.to_dict("records")[0]
    height_cm = weight_kg = 0.0
    height_match = re.match(r"(\d+)-(\d+)", str(row.get("HEIGHT") or ""))
    if height_match:
        height_cm = round(
            (int(height_match.group(1)) * 12 + int(height_match.group(2))) * 2.54, 1
        )
    weight = _num(row.get("WEIGHT"))
    if weight:
        weight_kg = round(weight * 0.45359237, 1)

    result = {
        "position": (row.get("POSITION") or "").strip(),
        "height_cm": height_cm,
        "weight_kg": weight_kg,
        "from_year": int(_num(row.get("FROM_YEAR"))),
        "to_year": int(_num(row.get("TO_YEAR"))),
    }
    _cache_set(key, result)
    return result


def _nba_id(name: str) -> Optional[int]:
    """ID hráče v NBA API podle jména (statický seznam, nestahuje se)."""
    try:
        from nba_api.stats.static import players as nba_players
    except Exception:  # pragma: no cover
        return None
    key = normalize_name(name)
    exact = [p for p in nba_players.get_players() if normalize_name(p["full_name"]) == key]
    if not exact:
        exact = [p for p in nba_players.get_players() if key and key in normalize_name(p["full_name"])]
    return exact[0]["id"] if exact else None


def nba_stats(player_id: int, player_name: str) -> Optional[Dict[str, Any]]:
    """
    Kariérní průměry z NBA API – jeden dotaz na celou kariéru hráče
    (PlayerCareerStats). Funguje i pro hráče z 60.–80. let, na rozdíl od
    sezónních týmových tabulek.
    """
    key = f"nba:{player_id}"
    cached = _cache_get(key, TTL_STATS)
    if cached:
        return cached or None

    try:
        from nba_api.stats.endpoints import playercareerstats
    except Exception:  # pragma: no cover
        return None

    try:
        endpoint = playercareerstats.PlayerCareerStats(
            player_id=player_id, per_mode36="PerGame", timeout=25
        )
        frame = endpoint.season_totals_regular_season.get_data_frame()
    except Exception as exc:  # pragma: no cover
        logger.warning("NBA API kariéra %s selhala: %s", player_name, exc)
        return None

    if frame is None or frame.empty:
        _cache_set(key, {})
        return None

    totals: Dict[str, float] = {"gp": 0.0}
    for row in frame.to_dict("records"):
        gp = _num(row.get("GP"))
        if gp <= 0:
            continue
        totals["gp"] += gp
        for stat_key, column in (
            ("pts", "PTS"), ("reb", "REB"), ("ast", "AST"), ("stl", "STL"),
            ("blk", "BLK"), ("tov", "TOV"), ("fgm", "FGM"), ("fga", "FGA"),
            ("fg3m", "FG3M"), ("fg3a", "FG3A"), ("ftm", "FTM"),
            ("fta", "FTA"), ("min_per_game", "MIN"),
        ):
            # NBA API u starých sezón někdy nemá hodnotu (NaN) – počítá se jako 0
            value = _num(row.get(column))
            if value != value:  # NaN
                value = 0.0
            totals[stat_key] = totals.get(stat_key, 0.0) + value * gp

    gp = totals.get("gp", 0.0)
    if gp <= 0:
        _cache_set(key, {})
        return None

    result: Dict[str, Any] = {"source": "NBA API", "gp": gp, "name": player_name}
    for stat_key, value in totals.items():
        if stat_key == "gp":
            continue
        result[stat_key] = value / gp
    result["fg_pct"] = (result.get("fgm", 0.0) / result["fga"]) if result.get("fga") else 0.0
    result["fg3_pct"] = (result.get("fg3m", 0.0) / result["fg3a"]) if result.get("fg3a") else 0.0
    result["ft_pct"] = (result.get("ftm", 0.0) / result["fta"]) if result.get("fta") else 0.0
    _cache_set(key, result)
    return result


# Názvy klubů pro zobrazení (zkratka -> celý název)
TEAM_NAMES = {
    "ATL": "Atlanta Hawks", "BOS": "Boston Celtics", "BKN": "Brooklyn Nets",
    "NJN": "New Jersey Nets", "CHA": "Charlotte Hornets", "CHH": "Charlotte Hornets",
    "CHO": "Charlotte Hornets", "CHI": "Chicago Bulls", "CLE": "Cleveland Cavaliers",
    "DAL": "Dallas Mavericks", "DEN": "Denver Nuggets", "DET": "Detroit Pistons",
    "GSW": "Golden State Warriors", "SFW": "San Francisco Warriors",
    "PHW": "Philadelphia Warriors", "HOU": "Houston Rockets", "SDR": "San Diego Rockets",
    "IND": "Indiana Pacers", "LAC": "Los Angeles Clippers", "SDC": "San Diego Clippers",
    "BUF": "Buffalo Braves", "LAL": "Los Angeles Lakers", "MIN": "Minnesota Timberwolves",
    "MEM": "Memphis Grizzlies", "VAN": "Vancouver Grizzlies", "MIA": "Miami Heat",
    "MIL": "Milwaukee Bucks", "NOP": "New Orleans Pelicans", "NOH": "New Orleans Hornets",
    "NOK": "New Orleans/Oklahoma City Hornets", "NYK": "New York Knicks",
    "SEA": "Seattle SuperSonics", "OKC": "Oklahoma City Thunder",
    "ORL": "Orlando Magic", "PHI": "Philadelphia 76ers", "SYR": "Syracuse Nationals",
    "PHX": "Phoenix Suns", "POR": "Portland Trail Blazers", "SAC": "Sacramento Kings",
    "KCK": "Kansas City Kings", "KCO": "Kansas City-Omaha Kings",
    "CIN": "Cincinnati Royals", "ROC": "Rochester Royals", "SAS": "San Antonio Spurs",
    "TOR": "Toronto Raptors", "UTA": "Utah Jazz", "NOJ": "New Orleans Jazz",
    "WAS": "Washington Wizards", "WSB": "Washington Bullets", "BAL": "Baltimore Bullets",
    "CHP": "Chicago Packers", "CHZ": "Chicago Zephyrs", "CAP": "Capital Bullets",
    "FTW": "Fort Wayne Pistons", "TRI": "Tri-Cities Blackhawks", "MLH": "Milwaukee Hawks",
    "STL": "St. Louis Hawks", "DNV": "Denver Nuggets", "SDS": "San Diego Sails",
    "TOT": "Více klubů",
}


def _team_name(abbr: str) -> str:
    return TEAM_NAMES.get(abbr, abbr)


def _merge_club_runs(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Ze sezón udělá pobyty v klubech: klub + od–do + zápasy a průměry.
    Když se hráč do klubu vrátil, jsou to dva samostatné pobyty.
    """
    runs: List[Dict[str, Any]] = []
    for row in sorted(rows, key=lambda r: r["season_id"]):
        abbr = row["team_abbreviation"]
        last = runs[-1] if runs else None
        if last and last["team_abbreviation"] == abbr:
            last["to_season"] = row["season_id"]
            last["gp"] += row["gp"]
            last["_weighted"].append(row)
        else:
            runs.append(
                {
                    "team_abbreviation": abbr,
                    "team_name": _team_name(abbr),
                    "from_season": row["season_id"],
                    "to_season": row["season_id"],
                    "gp": row["gp"],
                    "_weighted": [row],
                }
            )

    for run in runs:
        total_gp = run["gp"] or 1
        for key in ("pts", "reb", "ast", "stl", "blk", "fg3m"):
            # Starší sezóny zisky a bloky nemají (None) a NBA data mohou
            # obsahovat i NaN – takové sezóny se do průměru nepočítají,
            # jinak klidně vznikne NaN a celý profil hráče přestane jít načíst.
            pairs = [
                (r.get(key), r["gp"])
                for r in run["_weighted"]
                if r.get(key) is not None and r.get(key) == r.get(key)
            ]
            games = sum(g for _, g in pairs)
            run[key] = round(sum(v * g for v, g in pairs) / games, 1) if games else None
        del run["_weighted"]
    return runs


def career_clubs(player_id: Optional[int], name: str) -> Dict[str, Any]:
    """
    Kariéra po klubech. Bere se z NBA API (jednotlivé sezóny včetně týmů);
    když API neodpovídá, zkusí se Basketball-Reference.
    """
    if player_id:
        key = f"clubs:{player_id}"
        cached = _cache_get(key, TTL_STATS)
        if cached is not None:
            return cached or {}

        try:
            from nba_api.stats.endpoints import playercareerstats
        except Exception:  # pragma: no cover
            return {}

        try:
            endpoint = playercareerstats.PlayerCareerStats(
                player_id=player_id, per_mode36="PerGame", timeout=25
            )
            frame = endpoint.season_totals_regular_season.get_data_frame()
        except Exception as exc:  # pragma: no cover
            logger.warning("NBA API kluby %s selhaly: %s", name, exc)
            frame = None

        if frame is not None and not frame.empty:
            rows: List[Dict[str, Any]] = []
            for row in frame.to_dict("records"):
                gp = _num(row.get("GP"))
                abbr = str(row.get("TEAM_ABBREVIATION") or "").strip()
                if gp <= 0 or not abbr:
                    continue
                rows.append(
                    {
                        "season_id": str(row.get("SEASON_ID"))[:7],
                        "team_abbreviation": abbr,
                        "gp": int(gp),
                        "pts": _num(row.get("PTS")),
                        "reb": _num(row.get("REB")),
                        "ast": _num(row.get("AST")),
                        "stl": _num(row.get("STL")),
                        "blk": _num(row.get("BLK")),
                        "fg3m": _num(row.get("FG3M")),
                    }
                )
            # Sezóna, ve které hráč střídal kluby, má i souhrnný řádek (TOT).
            # Do pobytů v klubech nepatří – jinak by se kluby počítaly dvakrát.
            rows = [r for r in rows if r["team_abbreviation"] != "TOT"]
            if rows:
                result = {
                    "source": "NBA API",
                    "clubs": _merge_club_runs(rows),
                }
                _cache_set(key, result)
                return result

    # Záložní cesta: Basketball-Reference má v tabulce totals sloupec "Tm"
    fallback = bbref_clubs(name)
    if fallback:
        if player_id:
            _cache_set(f"clubs:{player_id}", fallback)
        return fallback
    if player_id:
        _cache_set(f"clubs:{player_id}", {})
    return {}


def bbref_season_rows(player_id: int) -> List[Dict[str, Any]]:
    """
    Kompletní sezónní řádky hráče z Basketball-Reference ve stejných
    sloupcích, jaké dává NBA API. Používá se jako záloha, když NBA API
    nevrátí kariéru (starší hráči jako Bill Walton).

    Bere se řádek součtu za sezónu (Tm = TOT), jinak řádek týmu.
    """
    name = _name_for(player_id)
    if not name:
        return []
    slug = bbref_slug(name)
    if not slug:
        return []

    key = f"bbrefseasons:{slug}"
    cached = _cache_get(key, TTL_STATS)
    if cached is not None:
        return cached or []

    url = f"https://www.basketball-reference.com/players/{slug[0]}/{slug}.html"
    try:
        html = _http_get(url, timeout=30)
    except Exception as exc:  # pragma: no cover
        logger.warning("Basketball-Reference sezóny selhaly pro %s: %s", name, exc)
        return []

    table = re.search(r'<table[^>]*id="per_game_stats"[^>]*>.*?</table>', html, re.S)
    if not table:
        _cache_set(key, [])
        return []

    header: List[str] = []
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", table.group(0), re.S)
    if rows:
        header = [_clean(c) for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", rows[0], re.S)]
    if "Season" not in header or "G" not in header:
        _cache_set(key, [])
        return []

    index = {name_: i for i, name_ in enumerate(header)}

    def cell(cells: List[str], key_: str) -> Optional[str]:
        position = index.get(key_)
        if position is None or position >= len(cells):
            return None
        return cells[position]

    by_season: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        cells = [_clean(c) for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", row, re.S)]
        if len(cells) < len(header):
            continue
        season = cell(cells, "Season") or ""
        if not re.match(r"^\d{4}-\d{2}$", season):
            continue
        team = cell(cells, "Tm") or ""
        gp = _num(cell(cells, "G") or "")
        if gp <= 0:
            continue

        def per_game(key_: str) -> Optional[float]:
            raw = cell(cells, key_)
            if raw in (None, ""):
                return None
            value = _num(raw)
            return value if value == value else None

        item = {
            "SEASON_ID": season,
            "TEAM_ABBREVIATION": team if team != "TOT" else "",
            "TEAM_ID": 0 if team == "TOT" else 1,
            "PLAYER_AGE": per_game("Age") or 0,
            "GP": int(gp),
            "GS": int(_num(cell(cells, "GS") or "") or 0),
            "MIN": per_game("MP") or 0.0,
            "PTS": per_game("PTS") or 0.0,
            "REB": per_game("TRB") or 0.0,
            "AST": per_game("AST") or 0.0,
            "STL": per_game("STL"),
            "BLK": per_game("BLK"),
            "TOV": per_game("TOV"),
            "PF": per_game("PF"),
            "FGM": per_game("FG") or 0.0,
            "FGA": per_game("FGA") or 0.0,
            "FG_PCT": per_game("FG%"),
            "FG3M": per_game("3P") or 0.0,
            "FG3A": per_game("3PA") or 0.0,
            "FG3_PCT": per_game("3P%"),
            "FTM": per_game("FT") or 0.0,
            "FTA": per_game("FTA") or 0.0,
            "FT_PCT": per_game("FT%"),
        }
        previous = by_season.get(season)
        if previous is None or item["TEAM_ID"] == 0 or item["GP"] > previous["GP"]:
            by_season[season] = item

    out = [by_season[k] for k in sorted(by_season)]
    _cache_set(key, out)
    return out


def bbref_clubs(name: str) -> Optional[Dict[str, Any]]:
    """Kariéra po klubech z Basketball-Reference (tabulka totals)."""
    slug = bbref_slug(name)
    if not slug:
        return None
    key = f"bbrefclubs:{slug}"
    cached = _cache_get(key, TTL_STATS)
    if cached is not None:
        return cached or None

    letter = slug[0]
    url = f"https://www.basketball-reference.com/players/{letter}/{slug}.html"
    try:
        html = _http_get(url, timeout=30)
    except Exception as exc:  # pragma: no cover
        logger.warning("Basketball-Reference kluby selhaly pro %s: %s", name, exc)
        return None

    table = re.search(r'<table[^>]*id="totals_stats"[^>]*>.*?</table>', html, re.S)
    if not table:
        _cache_set(key, {})
        return None

    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", table.group(0), re.S)
    header: List[str] = []
    if rows:
        header = [_clean(c) for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", rows[0], re.S)]
    if "Tm" not in header or "G" not in header:
        _cache_set(key, {})
        return None

    index = {name_: i for i, name_ in enumerate(header)}
    parsed: List[Dict[str, Any]] = []
    for row in rows:
        cells = [_clean(c) for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", row, re.S)]
        if len(cells) < len(header):
            continue
        season = cells[index.get("Season", 1)]
        if not re.match(r"^\d{4}-\d{2}$", season):
            continue
        abbr = cells[index["Tm"]]
        if abbr in ("TOT", ""):
            continue
        gp = _num(cells[index["G"]])
        if gp <= 0:
            continue
        parsed.append(
            {
                "season_id": season,
                "team_abbreviation": abbr,
                "gp": int(gp),
                "pts": _num(cells[index.get("PTS", 0)]) / gp,
                "reb": _num(cells[index.get("TRB", 0)]) / gp,
                "ast": _num(cells[index.get("AST", 0)]) / gp,
                "stl": _num(cells[index.get("STL", 0)]) / gp,
                "blk": _num(cells[index.get("BLK", 0)]) / gp,
                "fg3m": _num(cells[index.get("3P", 0)]) / gp,
            }
        )
    if not parsed:
        _cache_set(key, {})
        return None
    result = {"source": "Basketball-Reference", "clubs": _merge_club_runs(parsed)}
    _cache_set(key, result)
    return result


def league_season_for_profile(profile: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Kandidáti na porovnání: sezónní tabulka celé ligy (LeagueDashPlayerStats),
    jeden dotaz. Když se profil nenačte, zkusí se o sezónu dřív.
    """
    seasons: List[str] = []
    for key in ("season", "last_season"):
        value = profile.get(key)
        if isinstance(value, str) and value:
            seasons.append(value)
    seasons.extend(["2025-26", "2024-25"])

    seen_seasons = set()
    for season in seasons:
        if season in seen_seasons:
            continue
        seen_seasons.add(season)
        rows = _league_season(season)
        if rows:
            return rows

    # Záloha: hráči, jejichž kariérní profil už aplikace zná (bez sítě)
    return _cached_players()


def _cached_players() -> List[Dict[str, Any]]:
    """Hráči z paměti, když se sezónní tabulka nenačte (výpadek NBA API)."""
    out: List[Dict[str, Any]] = []
    for key, entry in _load_memory()["entries"].items():
        if not key.startswith("nba:"):
            continue
        value = entry.get("v") or {}
        if not value.get("gp"):
            continue
        player_id = int(key.split(":", 1)[1])
        size = _cache_get(f"size:{player_id}", TTL_PROFILE) or {}
        out.append(
            {
                "id": player_id,
                "name": value.get("name") or _name_for(player_id),
                "gp": value.get("gp", 0.0),
                "pts": value.get("pts", 0.0),
                "reb": value.get("reb", 0.0),
                "ast": value.get("ast", 0.0),
                "stl": value.get("stl", 0.0),
                "blk": value.get("blk", 0.0),
                "tov": value.get("tov", 0.0),
                "fgm": value.get("fgm", 0.0),
                "fga": value.get("fga", 0.0),
                "fg3m": value.get("fg3m", 0.0),
                "fg3a": value.get("fg3a", 0.0),
                "ftm": value.get("ftm", 0.0),
                "fta": value.get("fta", 0.0),
                "fg_pct": value.get("fg_pct", 0.0),
                "fg3_pct": value.get("fg3_pct", 0.0),
                "ft_pct": value.get("ft_pct", 0.0),
                "min_per_game": value.get("min_per_game", 0.0),
                "position": size.get("position", ""),
                "height_cm": size.get("height_cm", 0.0),
                "weight_kg": size.get("weight_kg", 0.0),
            }
        )
    return out


def _name_for(player_id: int) -> str:
    try:
        from nba_api.stats.static import players as nba_players

        for info in nba_players.get_players():
            if info["id"] == player_id:
                return info["full_name"]
    except Exception:
        pass
    return str(player_id)


def _position_cache() -> Dict[int, Dict[str, Any]]:
    """Pozice a míry hráčů, které už aplikace jednou načetla (bez sítě)."""
    out: Dict[int, Dict[str, Any]] = {}
    for key, entry in _load_memory()["entries"].items():
        if not key.startswith("size:"):
            continue
        value = entry.get("v") or {}
        if value.get("height_cm"):
            out[int(key.split(":", 1)[1])] = value
    return out


def remember_position(player_id: int, position: str, height_cm: float, weight_kg: float) -> None:
    """Zapamatuje si pozici a míry hráče, aby se nedohledávaly znovu."""
    if not height_cm and not position:
        return
    _cache_set(
        f"size:{player_id}",
        {"position": position or "", "height_cm": height_cm or 0.0, "weight_kg": weight_kg or 0.0},
    )


def known_position(player_id: int) -> Optional[Dict[str, Any]]:
    """
    Pozice a míry hráče z paměti – bez čekání na síť.
    NBA API je pomalé, takže se během požadavku nedohledává.
    """
    return _cache_get(f"size:{player_id}", TTL_PROFILE) or None


def position_and_size(player_id: int, name: str = "") -> Optional[Dict[str, Any]]:
    """
    Pozice a míry hráče. Nejdřív NBA API, při výpadku Basketball-Reference.
    Výsledek se pamatuje, takže se každý hráč dotahuje jen jednou.
    """
    value = _nba_position_size(player_id)
    if value and value.get("height_cm"):
        return value

    size_key = f"size:{player_id}"
    stale = _load_memory()["entries"].pop(size_key, None)
    if stale:
        _DIRTY["count"] += 1

    if not name:
        name = _name_for(player_id)
    fallback = bbref_profile(name) if name and not name.isdigit() else None
    if fallback and fallback.get("height_cm"):
        remember_position(
            player_id,
            fallback.get("position", ""),
            fallback.get("height_cm", 0.0),
            fallback.get("weight_kg", 0.0),
        )
        return fallback
    return value


_SLUG_FALLBACK = {
    "klay thompson": "thompkl01",
    "lebron james": "jamesle01",
    "chris paul": "paulch01",
    "giannis antetokounmpo": "antetgi01",
    "kevin durant": "duranke01",
    "lauri markkanen": "markkla01",
    "stephen curry": "curryst01",
    "michael jordan": "jordami01",
    "kobe bryant": "bryanko01",
}


def _nba_position_size(player_id: int) -> Optional[Dict[str, Any]]:
    """Pozice a míry hráče z NBA API, s vlastní (delší) pamětí."""
    key = f"size:{player_id}"
    cached = _cache_get(key, TTL_PROFILE)
    if cached and cached.get("height_cm"):
        return cached
    details = nba_info(player_id) or {}
    if not details.get("height_cm"):
        # prázdná odpověď se neukládá – zkusí se to znovu jindy
        return None
    value = {
        "position": details.get("position", ""),
        "height_cm": details.get("height_cm", 0.0),
        "weight_kg": details.get("weight_kg", 0.0),
    }
    _cache_set(key, value)
    return value


def _league_season(season: str) -> List[Dict[str, Any]]:
    """Sezónní průměry všech hráčů ligy, kešované na 3 dny."""
    key = f"league:{season}"
    cached = _cache_get(key, TTL_STATS)
    if cached is not None:
        return cached or []

    try:
        from nba_api.stats.endpoints import leaguedashplayerstats

        endpoint = leaguedashplayerstats.LeagueDashPlayerStats(
            season=season,
            season_type_all_star="Regular Season",
            per_mode_detailed="PerGame",
            timeout=30,
        )
        frame = endpoint.league_dash_player_stats.get_data_frame()
    except Exception as exc:  # pragma: no cover
        logger.warning("Sezóna %s z NBA API se nenačetla: %s", season, exc)
        return []

    if frame is None or frame.empty:
        _cache_set(key, [])
        return []

    records = [r for r in frame.to_dict("records") if int(_num(r.get("PLAYER_ID")))]

    # Pozice a míry: NBA API je v sezónní tabulce neposílá a dohledávat
    # je pro každého hráče zvlášť by znamenalo stovky dotazů. Bere se proto
    # jen to, co už aplikace zná (profily hráčů); zbytek se doplní podle
    # výšky z pozdějšího profilu.
    sizes: Dict[int, Dict[str, Any]] = _position_cache()

    rows: List[Dict[str, Any]] = []
    for row in records:
        pid = int(_num(row.get("PLAYER_ID")))
        if not pid:
            continue
        rows.append(
            {
                "id": pid,
                "name": row.get("PLAYER_NAME") or "",
                "gp": _num(row.get("GP")),
                "pts": _num(row.get("PTS")),
                "reb": _num(row.get("REB")),
                "ast": _num(row.get("AST")),
                "stl": _num(row.get("STL")),
                "blk": _num(row.get("BLK")),
                "tov": _num(row.get("TOV")),
                "fgm": _num(row.get("FGM")),
                "fga": _num(row.get("FGA")),
                "fg3m": _num(row.get("FG3M")),
                "fg3a": _num(row.get("FG3A")),
                "ftm": _num(row.get("FTM")),
                "fta": _num(row.get("FTA")),
                "fg_pct": _num(row.get("FG_PCT")),
                "fg3_pct": _num(row.get("FG3_PCT")),
                "ft_pct": _num(row.get("FT_PCT")),
                "min_per_game": _num(row.get("MIN")),
                "season": season,
                # Pozice a míry: NBA API je neposílá, bere se profil hráče
                **(sizes.get(pid) or {"position": "", "height_cm": 0.0, "weight_kg": 0.0}),
            }
        )
    _cache_set(key, rows)
    return rows


def bbref_profile(name: str) -> Optional[Dict[str, Any]]:
    """
    Pozice a míry z Basketball-Reference (výška, váha, pozice).
    Načte se stránka hráče a přečte se jen záhlaví – levné a kešované.
    """
    slug = bbref_slug(name)
    if not slug:
        return None

    key = f"bbref-profile:{slug}"
    cached = _cache_get(key, TTL_PROFILE)
    if cached is not None:
        return cached or None

    url = f"https://www.basketball-reference.com/players/{slug[0]}/{slug}.html"
    try:
        html = _http_get(url, timeout=30)
    except Exception as exc:  # pragma: no cover
        logger.warning("Basketball-Reference profil selhal pro %s: %s", name, exc)
        return None

    position = ""
    pos_match = re.search(
        r"Position:\s*</strong>\s*([A-Za-z and\-]+?)\s*(?:&#9642;|<strong>)", html
    )
    if pos_match:
        position = " ".join(pos_match.group(1).split())

    height_cm = weight_kg = 0.0
    size_match = re.search(r"<span>(\d)-(\d+)</span>.*?<span>(\d+)lb</span>", html, re.S)
    if size_match:
        feet, inches, pounds = (float(x) for x in size_match.groups())
        height_cm = round((feet * 12 + inches) * 2.54, 1)
        weight_kg = round(pounds * 0.45359237, 1)

    result = {"position": position, "height_cm": height_cm, "weight_kg": weight_kg}
    _cache_set(key, result)
    return result


def career_profile(player_id: Optional[int], name: str) -> Optional[Dict[str, Any]]:
    """
    Kariérní profil hráče z externích zdrojů.

    Pořadí: NBA API (přesnější, zná pozice) → Basketball-Reference.
    Když obojí selže, vrací None a volající použije, co má.
    """
    stats: Optional[Dict[str, Any]] = None
    if player_id:
        stats = nba_stats(player_id, name)
        # Málo zápasů = NBA API nezná celou kariéru, vezme se Basketball-Reference
        if stats and stats.get("gp", 0) < 250:
            stats = None
    if not stats:
        stats = bbref_career(name)
    if not stats:
        return None

    # Pozice a míry: primárně z NBA API (CommonPlayerInfo),
    # Basketball-Reference se použije jen jako záloha.
    if not stats.get("position") or not stats.get("height_cm"):
        details = nba_info(player_id) if player_id else {}
        for field in ("position", "height_cm", "weight_kg"):
            if not stats.get(field):
                stats[field] = (details or {}).get(field, "")
    if not stats.get("position") or not stats.get("height_cm"):
        ref = bbref_profile(name) or {}
        for field in ("position", "height_cm", "weight_kg"):
            if not stats.get(field):
                stats[field] = ref.get(field, "")

    stats["name"] = name
    stats["id"] = player_id
    remember_position(
        player_id or 0,
        stats.get("position", ""),
        stats.get("height_cm", 0.0),
        stats.get("weight_kg", 0.0),
    )
    return stats


def info() -> Dict[str, Any]:
    """Stav externí paměti pro UI."""
    payload = _load_memory()
    entries = payload.get("entries", {})
    newest = max((e.get("t", 0) for e in entries.values()), default=0)
    return {
        "entries": len(entries),
        "last_fetch": newest,
        "ttl_hours": TTL_STATS // 3600,
        "sources": ["NBA API (stats.nba.com)", "Basketball-Reference"],
        "note": "Žádná vlastní databáze – jen dočasná paměť odpovědí z internetu.",
    }

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

from services import source_switch

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
            # Kandidáti ze sezónní tabulky + hráči, jejichž kariéru už
            # aplikace zná (legendy mimo sezónní tabulku). Bez toho by
            # Jordan dostal jen dnešní hráče a Karla Malona z ESPN.
            known = {r["id"] for r in rows}
            return rows + [r for r in _cached_players() if r["id"] not in known]

    # Záloha: hráči, jejichž kariérní profil už aplikace zná (bez sítě)
    return _cached_players()


_ESPN_STAT_KEYS = {
    "gamesPlayed": "gp",
    "minutes": "min_per_game",
    "points": "pts",
    "totalRebounds": "reb",
    "assists": "ast",
    "steals": "stl",
    "blocks": "blk",
    "turnovers": "tov",
    "fieldGoalsMade": "fgm",
    "fieldGoalsAttempted": "fga",
    "threePointFieldGoalsMade": "fg3m",
    "threePointFieldGoalsAttempted": "fg3a",
    "freeThrowsMade": "ftm",
    "freeThrowsAttempted": "fta",
    "fieldGoalPct": "fg_pct",
    "threePointFieldGoalPct": "fg3_pct",
    "freeThrowPct": "ft_pct",
}

# Kolik hráčů ligy se z ESPN bere jako kandidáti (podle bodů na zápas).
ESPN_LEAGUE_LIMIT = 200


def _espn_season_start(season: str) -> int:
    """'2025-26' → 2026 (rok, kterým sezóna končí – tak čísluje ESPN)."""
    try:
        return int(str(season)[:4]) + 1
    except (TypeError, ValueError):
        return 0


def _espn_league_rows(season: str) -> List[Dict[str, Any]]:
    """
    Sezónní průměry hráčů ligy z ESPN – jeden dotaz na kategorii plus jeden
    dotaz na hráče. Používá se, když NBA API není dostupné (cloud).
    """
    from concurrent.futures import ThreadPoolExecutor

    from services import espn_seasons

    year = _espn_season_start(season)
    if not year:
        return []
    base = (
        "https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba/"
        f"seasons/{year}/types/2/leaders"
    )
    data = espn_seasons._get_json(f"{base}?limit={ESPN_LEAGUE_LIMIT}")
    if not data:
        return []

    refs: Dict[int, str] = {}
    for category in data.get("categories") or []:
        if category.get("name") != "pointsPerGame":
            continue
        for leader in category.get("leaders") or []:
            athlete = str((leader.get("athlete") or {}).get("$ref") or "")
            stats_ref = str((leader.get("statistics") or {}).get("$ref") or "")
            digits = "".join(ch for ch in athlete.split("/athletes/")[-1] if ch.isdigit())
            if digits and stats_ref:
                refs[int(digits)] = stats_ref.replace("http://", "https://")

    def fetch(item):
        espn_id, ref = item
        payload = espn_seasons._get_json(ref)
        if not payload:
            return None
        athlete_ref = str((payload.get("athlete") or {}).get("$ref") or "")
        athlete = espn_seasons._get_json(athlete_ref.replace("http://", "https://")) or {}
        values: Dict[str, Any] = {}
        for category in (payload.get("splits") or {}).get("categories") or []:
            for stat in category.get("stats") or []:
                key = _ESPN_STAT_KEYS.get(stat.get("name"))
                if key:
                    values[key] = _num(stat.get("value"))
        games = values.get("gp") or 0.0
        if not games:
            return None
        # Pozor: ESPN číslo hráče není NBA ID. Do `id` patří přeložené NBA
        # ID, jinak vzniknou nesmyslná čísla (61 644,91) a aplikace nepozná
        # hráče, kterého má v databázi.
        row: Dict[str, Any] = {
            "id": int(espn_id),
            "espn_id": int(espn_id),
            "name": athlete.get("displayName") or athlete.get("fullName") or "",
        }
        row.update(values)
        row["season"] = season
        size = _cache_get(f"size:{espn_id}", TTL_STATS) or {}
        row["position"] = size.get("position") or ""
        row["height_cm"] = size.get("height_cm") or 0.0
        row["weight_kg"] = size.get("weight_kg") or 0.0
        if not row["height_cm"]:
            # Míry a pozice z profilu v ESPN (jeden dotaz na kandidáta)
            height = _num(athlete.get("height"))
            weight = _num(athlete.get("weight"))
            pos = athlete.get("position") or {}
            if isinstance(pos, dict):
                row["position"] = pos.get("abbreviation") or pos.get("displayName") or ""
            # ESPN posílá míry v palcích i ve stopách; 80 znamená 6-8 (203 cm),
            # ne 80 palců. Hodnoty nad 7 jsou palce, menší stopy.
            height_cm = height * 2.54 if height and height > 7 else height * 30.48
            row["height_cm"] = round(height_cm, 1) if height_cm else 0.0
            row["weight_kg"] = round(weight * 0.45359237, 1) if weight else 0.0
            if row["height_cm"]:
                remember_position(
                    int(espn_id), row["position"], row["height_cm"], row["weight_kg"]
                )
        return row

    with ThreadPoolExecutor(max_workers=8) as executor:
        rows = [r for r in executor.map(fetch, refs.items()) if r]
    if not rows:
        return []

    # ESPN posílá sezónní SOUČTY, aplikace počítá s průměry na zápas.
    pct_keys = {"fg_pct", "fg3_pct", "ft_pct"}
    keep_keys = {"gp", "name", "position", "height_cm", "weight_kg", "id", "espn_id", "season"}
    for row in rows:
        games = row.pop("gp", 0.0) or 0.0
        row["gp"] = games
        if games > 0:
            for key in list(row.keys()):
                if key in pct_keys or key in keep_keys:
                    continue
                value = row.get(key)
                if isinstance(value, (int, float)):
                    row[key] = round(value / games, 2)
        for key in pct_keys:
            if isinstance(row.get(key), (int, float)):
                row[key] = row[key] / 100.0
    rows.sort(key=lambda r: -(r.get("pts") or 0.0))
    _link_nba_ids(rows)
    return rows


def _link_nba_ids(rows: List[Dict[str, Any]]) -> None:
    """
    Přeloží ESPN ID na NBA ID tam, kde hráče zná databáze nebo registr NBA.
    Neznámý hráč si nechá ESPN číslo (jen dočasně, nic se neukládá).
    """
    try:
        import models
        from database import SessionLocal

        session = SessionLocal()
        try:
            known = {p.full_name: p.id for p in session.query(models.Player).all()}
        finally:
            session.close()
    except Exception:
        known = {}
    from services.espn_seasons import _plain

    by_plain = {_plain(name): pid for name, pid in known.items()}
    for row in rows:
        nba_id = by_plain.get(_plain(row.get("name") or ""))
        if nba_id:
            row["id"] = int(nba_id)


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
    """
    Jméno hráče podle ID: registr NBA, jinak paměť aplikace.

    V cloudu registr NBA nefunguje, takže se jméno bere z kariérních
    profilů, které si aplikace už uložila – bez jména by se nedalo
    přeložit ESPN ID a hráč by „zmizel".
    """
    try:
        from nba_api.stats.static import players as nba_players

        for info in nba_players.get_players():
            if info["id"] == player_id:
                return info["full_name"]
    except Exception:
        pass

    entry = _load_memory()["entries"].get(f"nba:{player_id}") or {}
    value = entry.get("v") or {}
    if value.get("name"):
        return str(value["name"])

    size = _cache_get(f"size:{player_id}", TTL_PROFILE) or {}
    if size.get("name"):
        return str(size["name"])
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


def remember_career(player_id: int, name: str, stat: Dict[str, Any]) -> None:
    """Zapamatuje si kariérní profil hráče (dočasně, s vypršením)."""
    if not stat or not stat.get("gp"):
        return
    value = dict(stat)
    value["name"] = name or value.get("name") or ""
    _cache_set(f"nba:{player_id}", value)


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

    if source_switch.espn_first() and not (value and value.get("height_cm")):
        # NBA API je v cloudu zablokované – pozice a míry z ESPN.
        from services import espn_seasons

        espn_id = espn_seasons.resolve_id(player_id)
        payload = espn_seasons._get_json(
            "https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba/"
            f"athletes/{espn_id}"
        )
        if payload:
            height = _num(payload.get("height"))
            weight = _num(payload.get("weight"))
            position = ""
            pos = payload.get("position") or {}
            if isinstance(pos, dict):
                position = pos.get("abbreviation") or pos.get("displayName") or ""
            if height or weight:
                remember_position(
                    player_id,
                    position,
                    round(height * 2.54, 1) if height else 0.0,
                    round(weight * 0.45359237, 1) if weight else 0.0,
                )
                return {
                    "position": position,
                    "height_cm": round(height * 2.54, 1) if height else 0.0,
                    "weight_kg": round(weight * 0.45359237, 1) if weight else 0.0,
                }

    size_key = f"size:{player_id}"
    stale = _load_memory()["entries"].pop(size_key, None)
    if stale:
        _DIRTY["count"] += 1

    if not name:
        name = _name_for(player_id)
    if not name or name.isdigit():
        # Bez jména se Basketball-Reference nedá použít – zkusí se ESPN
        # (na serveru je to jediný zdroj, který odpovídá).
        try:
            from services import espn_seasons

            espn_id = espn_seasons.resolve_id(player_id)
            payload = espn_seasons._get_json(
                "https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba/"
                f"athletes/{espn_id}"
            ) or {}
            height = _num(payload.get("height"))
            weight = _num(payload.get("weight"))
            pos = payload.get("position") or {}
            position = pos.get("abbreviation") or "" if isinstance(pos, dict) else ""
            height_cm = height * 2.54 if height and height > 7 else height * 30.48
            if height_cm:
                remember_position(
                    player_id, position, round(height_cm, 1),
                    round(weight * 0.45359237, 1) if weight else 0.0,
                )
                return {
                    "position": position,
                    "height_cm": round(height_cm, 1),
                    "weight_kg": round(weight * 0.45359237, 1) if weight else 0.0,
                }
        except Exception as exc:  # pragma: no cover
            logger.warning("Míry %s z ESPN selhaly: %s", player_id, exc)
        return value

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


_ALL_PLAYERS_TTL = 7 * 24 * 3600
_LEGEND_TTL = 30 * 24 * 3600


def _espn_legends() -> List[Dict[str, Any]]:
    """
    Legendy, které v sezónní tabulce nejsou (Kobe, Pippen, Wade, Jordan).

    ESPN je má ve svém seznamu hráčů NBA podle abecedy, jen ne v sezónní
    tabulce. Načtou se jednou za 30 dní – jsou to stovky dotazů, ale jen
    jednou, a pak se drží v paměti.
    """
    key = "legends"
    cached = _cache_get(key, _LEGEND_TTL)
    if cached is not None:
        return cached or []

    from concurrent.futures import ThreadPoolExecutor

    from services import espn_seasons

    # seznam všech hráčů NBA v ESPN (bez sezóny) – odkazy po 25
    refs: List[int] = []
    page = 1
    while True:
        url = (
            "https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba"
            f"/athletes?limit=100&page={page}"
        )
        try:
            data = json.loads(_http_get(url, timeout=40) or "{}")
        except Exception as exc:  # pragma: no cover
            logger.warning("Seznam hráčů ESPN (strana %d) selhal: %s", page, exc)
            break
        items = (data or {}).get("items") or []
        if not items:
            break
        for item in items:
            ref = ((item.get("$ref")) or "").split("?")[0]
            parts = ref.rsplit("/athletes/", 1)
            if len(parts) == 2 and parts[1].isdigit():
                refs.append(int(parts[1]))
        pages = int(_num((data or {}).get("pageCount"), 1))
        if page >= pages or page >= 80:
            break
        page += 1

    if not refs:
        return []

    # Do seznamu legend patří i hráči, kteří v ESPN nejsou vedení jako
    # neaktivní (Jordan, Pippen). Bere se proto každý, kdo má v ESPN
    # kariérní statistiky a není to aktuální hráč ze sezónní tabulky.
    active_ids = set()
    try:
        for row in _espn_all_players("2025-26"):
            active_ids.add(int(row["id"]))
    except Exception:  # pragma: no cover
        pass

    def fetch(espn_id: int) -> Optional[Dict[str, Any]]:
        if espn_id in active_ids:
            return None
        payload = espn_seasons._get_json(
            "https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba"
            f"/athletes/{espn_id}"
        ) or {}
        name = (payload.get("fullName") or payload.get("displayName") or "").strip()
        if not name:
            return None
        # jen hráči s odehranou kariérou (seznam obsahuje i lidi bez zápasů)
        if not (payload.get("statistics") or {}).get("$ref"):
            return None
        height = _num(payload.get("height"))
        weight = _num(payload.get("weight"))
        pos = payload.get("position") or {}
        return {
            "id": espn_id,
            "espn_id": espn_id,
            "name": name,
            "position": (pos.get("abbreviation") or "") if isinstance(pos, dict) else "",
            "height_cm": round(height * 2.54, 1) if height else 0.0,
            "weight_kg": round(weight * 0.45359237, 1) if weight else 0.0,
            "legend": True,
        }

    with ThreadPoolExecutor(max_workers=12) as pool:
        rows = [r for r in pool.map(fetch, refs) if r]

    # Seznam odkazů nemusí obsahovat všechny hráče – doplní se jmenovitě
    # ti, které AI nejčastěji navrhuje jako obdobu současných hvězd.
    # Dohledají se přes vyhledávání ESPN (jedno jméno = jeden dotaz).
    have = {r["name"].lower() for r in rows}
    extra_names = [
        "Michael Jordan", "Kobe Bryant", "Scottie Pippen", "Dwyane Wade",
        "Hakeem Olajuwon", "Patrick Ewing", "Reggie Miller", "Ray Allen",
        "Paul Pierce", "Tracy McGrady", "Allen Iverson", "Vince Carter",
        "Kevin Garnett", "Tim Duncan", "Dirk Nowitzki", "Steve Nash",
        "Jason Kidd", "Gary Payton", "Shaquille O'Neal", "David Robinson",
        "Karl Malone", "John Stockton", "Charles Barkley", "Scottie Barnes",
        "Penny Hardaway", "Grant Hill", "Chris Webber", "Detlef Schrempf",
        "Peja Stojakovic", "Rashard Lewis", "Manu Ginobili", "Tony Parker",
        "Chauncey Billups", "Ben Wallace", "Ron Artest", "Shane Battier",
        "Andre Iguodala", "Klay Thompson", "Draymond Green", "Blake Griffin",
        "Kevin Love", "LaMarcus Aldridge", "Pau Gasol", "Marc Gasol",
    ]

    def fetch_named(name: str) -> Optional[Dict[str, Any]]:
        if name.lower() in have:
            return None
        espn_id = espn_seasons.search_athlete(name)
        if not espn_id or espn_id in active_ids:
            return None
        return fetch(espn_id)

    with ThreadPoolExecutor(max_workers=8) as pool:
        for row in pool.map(fetch_named, extra_names):
            if row:
                rows.append(row)

    if rows:
        _cache_set(key, rows)
    logger.info("ESPN legendy: %d hráčů", len(rows))
    return rows


def _espn_all_players(season: str) -> List[Dict[str, Any]]:
    """
    Všichni hráči ligy ze sezónní tabulky ESPN (jeden dotaz).

    Kdřív se bralo jen 200 nejlepších podle bodů, takže legenda mimo
    tento seznam (Kobe, Pippen, Wade) v nabídce vůbec nebyla. ESPN posílá
    celou tabulku v jednom dokumentu – načte se jednou a drží se 7 dní.
    """
    from services import espn_seasons

    year = _espn_season_start(season)
    if not year:
        return []
    key = f"allplayers:{year}"
    cached = _cache_get(key, _ALL_PLAYERS_TTL)
    if cached is not None:
        return cached or []

    url = (
        "https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba"
        f"/seasons/{year}/athletes?limit=1200"
    )
    # ESPN posílá jen odkazy (25 na stránku), jméno je až v detailu hráče.
    # Stáhne se všech ~770 odkazů a jména paralelně – jednou za 7 dní.
    from concurrent.futures import ThreadPoolExecutor

    refs: List[int] = []
    page = 1
    while True:
        page_url = url + f"&page={page}"
        try:
            data = json.loads(_http_get(page_url, timeout=40) or "{}")
        except Exception as exc:  # pragma: no cover
            logger.warning("Seznam hráčů ESPN (strana %d) selhal: %s", page, exc)
            break
        items = (data or {}).get("items") or []
        if not items:
            break
        for item in items:
            ref = ((item.get("$ref")) or "").split("?")[0]
            parts = ref.rsplit("/athletes/", 1)
            if len(parts) == 2 and parts[1].isdigit():
                refs.append(int(parts[1]))
        pages = int(_num((data or {}).get("pageCount"), 1))
        if page >= pages or page >= 40:
            break
        page += 1

    if not refs:
        logger.warning("ESPN nevrátil seznam hráčů pro %s", season)
        return []

    def fetch(espn_id: int) -> Optional[Dict[str, Any]]:
        payload = espn_seasons._get_json(
            "https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba"
            f"/athletes/{espn_id}"
        ) or {}
        name = (payload.get("fullName") or payload.get("displayName") or "").strip()
        if not name:
            return None
        height = _num(payload.get("height"))
        weight = _num(payload.get("weight"))
        pos = payload.get("position") or {}
        return {
            "id": espn_id,
            "espn_id": espn_id,
            "name": name,
            "position": (pos.get("abbreviation") or "") if isinstance(pos, dict) else "",
            "height_cm": round(height * 2.54, 1) if height else 0.0,
            "weight_kg": round(weight * 0.45359237, 1) if weight else 0.0,
        }

    with ThreadPoolExecutor(max_workers=10) as pool:
        rows = [r for r in pool.map(fetch, refs) if r]

    if rows:
        _cache_set(key, rows)
    logger.info("ESPN seznam hráčů %s: %d jmen", season, len(rows))
    return rows


def _all_player_pool() -> List[Dict[str, Any]]:
    """
    Nabídka kandidátů pro „nejbližšího hráče" = všichni hráči z ESPN
    (jméno + ID) a k tomu profily, které už aplikace zná.

    Statistiky se u kandidátů dotahují až podle podobnosti (viz
    closest_service), takže se nemusí stahovat celá liga.
    """
    key = "allpool"
    cached = _cache_get(key, TTL_STATS)
    if cached is not None:
        return cached or []

    by_id: Dict[int, Dict[str, Any]] = {}
    for row in _cached_players():
        if row.get("id"):
            by_id[int(row["id"])] = dict(row)

    # Stačí aktuální sezóna – v té jsou všichni hráči ligy. Starší sezóny
    # se přidají, jen když ta aktuální nic nevrátí.
    seasons = ["2025-26"]
    try:
        from services import nba_news

        current = nba_news.current_season()
        if current:
            seasons = [current]
    except Exception:  # pragma: no cover
        pass

    # Základ nabídky: sezónní tabulka s čísly (200 nejlepších podle bodů).
    # Odsud se dá počítat hned, bez dalších dotazů. Data se pamatují i
    # kariérně – hráč tak zůstane v nabídce i v příští sezóně.
    for season in seasons:
        for row in _espn_league_rows(season):
            pid = int(row["id"])
            if pid and pid not in by_id:
                by_id[pid] = dict(row)
                remember_career(pid, row.get("name") or "", row)

    # K tomu všichni hráči ligy a legendy – zatím jen jméno a míry,
    # statistiky se jim dotahují až podle podobnosti (a drží se v paměti).
    for season in seasons:
        for row in _espn_all_players(season):
            pid = int(row["id"])
            if pid in by_id:
                by_id[pid].setdefault("name", row["name"])
                continue
            by_id[pid] = {
                "id": pid,
                "espn_id": pid,
                "name": row["name"],
                "gp": 0,
                "pts": 0.0,
                "position": row.get("position") or "",
                "height_cm": row.get("height_cm") or 0.0,
                "weight_kg": row.get("weight_kg") or 0.0,
            }

    # Legendy mimo sezónní tabulku – jinak by Kobe, Pippen nebo Wade
    # v nabídce vůbec nebyli.
    for row in _espn_legends():
        pid = int(row["id"])
        if pid in by_id:
            continue
        by_id[pid] = dict(row)

    pool = _link_nba_ids(list(by_id.values()))
    if pool:
        _cache_set(key, pool)
    logger.info("Nabídka hráčů pro nejbližšího hráče: %d", len(pool))
    return pool


def _link_nba_ids(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Převede ESPN ID na NBA ID tam, kde hráče zná paměť aplikace.

    ESPN a NBA mají jiná čísla (LeBron 1966 vs 2544). Bez převodu vzniknou
    v nabídce dvě verze stejného hráče – jedna s čísly, druhá bez nich.
    """
    try:
        from services.espn_seasons import _plain
    except Exception:  # pragma: no cover
        return rows

    by_name: Dict[str, int] = {}
    for key, entry in _load_memory()["entries"].items():
        if not key.startswith("nba:"):
            continue
        value = entry.get("v") or {}
        name = _plain(value.get("name") or "")
        if name:
            by_name.setdefault(name, int(key.split(":", 1)[1]))

    for row in rows:
        name = _plain(row.get("name") or "")
        nba_id = by_name.get(name)
        if nba_id and int(row.get("id") or 0) != nba_id:
            row["espn_id"] = int(row.get("id") or 0)
            row["id"] = nba_id
    return rows


def _season_rows(player_id: int, season: str) -> Optional[Dict[str, Any]]:
    """Statistiky hráče v jedné sezóně z ESPN (per-game), kešované."""
    key = f"srow:{player_id}:{season}"
    cached = _cache_get(key, TTL_STATS)
    if cached is not None:
        return cached or None

    from services import espn_seasons

    espn_id = espn_seasons.resolve_id(player_id)
    year = _espn_season_start(season)
    if not year:
        return None
    values = espn_seasons._split_stats(
        "https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba"
        f"/seasons/{year}/types/2/athletes/{espn_id}/statistics/0"
    )
    row = espn_seasons._to_row(season, values) if values else None
    if row:
        _cache_set(key, row)
    return row


def fill_candidate_stats(
    rows: List[Dict[str, Any]], seasons: Optional[List[str]] = None
) -> List[Dict[str, Any]]:
    """
    Doplní statistiky kandidátům, kteří přišli jen se jménem.

    Sezónní tabulka ESPN má jen 200 nejlepších podle bodů, legenda nebo
    hráč mimo ni přišel bez čísel. Tady se dohledá jeho nejlepší sezóna
    (jednou, s pamětí), aby měl z čeho počítat podobnost.
    """
    from concurrent.futures import ThreadPoolExecutor

    seasons = seasons or ["2025-26", "2024-25", "2023-24"]
    need = [r for r in rows if not _num(r.get("gp"))]
    if not need:
        return rows

    def lookup(row: Dict[str, Any]) -> Dict[str, Any]:
        # Legenda nemá v aktuální sezóně nic – bere se její nejsilnější
        # sezóna z kariérního logu (jedno volání, pak z paměti).
        try:
            from services import espn_seasons

            history = espn_seasons.player_season_stats(int(row["id"])) or []
            if history:
                best = max(
                    history,
                    key=lambda r: _num(r.get("pts")) * min(_num(r.get("gp")), 70.0),
                )
                merged = dict(row)
                merged.update({k: v for k, v in best.items() if v is not None})
                merged["id"] = row["id"]
                merged["name"] = row.get("name") or best.get("name") or ""
                merged["season"] = best.get("season_id")
                return merged
        except Exception:  # pragma: no cover
            pass

        for season in seasons:
            stat = _season_rows(int(row["id"]), season)
            if stat and _num(stat.get("gp")) >= 20:
                merged = dict(row)
                merged.update({k: v for k, v in stat.items() if v is not None})
                merged["id"] = row["id"]
                merged["name"] = row.get("name") or stat.get("name") or ""
                merged["season"] = season
                return merged
        return row

    with ThreadPoolExecutor(max_workers=8) as pool:
        filled = list(pool.map(lookup, need))

    by_id = {int(r["id"]): r for r in filled}
    out: List[Dict[str, Any]] = []
    for row in rows:
        out.append(by_id.get(int(row["id"]), row))
    return out


def _league_season(season: str) -> List[Dict[str, Any]]:
    """Sezónní průměry všech hráčů ligy, kešované na 3 dny."""
    key = f"league:{season}"
    cached = _cache_get(key, TTL_STATS)
    if cached is not None:
        return cached or []

    if source_switch.espn_first():
        rows = _espn_league_rows(season)
        if rows:
            _cache_set(key, rows)
            return rows
        # Když ESPN nic nevrátí, pokračuje se na záložní seznam hráčů –
        # prázdný výsledek by se jinak uložil do paměti jako „nikdo".
        return _cached_players()

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

    # Když hráč není v sezónní tabulce ESPN (ukončil kariéru nebo je mimo
    # prvních 200), použije se kariérní seznam z ESPN. Ten dává průměry
    # na zápas, takže se hodí pro profil i pro dočasný seznam kandidátů.
    if not stats and player_id and source_switch.espn_first():
        try:
            from . import espn_seasons

            espn = espn_seasons.career_stats(player_id, name)
            if espn and espn.get("gp", 0) >= 50:
                stats = dict(espn)
        except Exception as exc:  # pragma: no cover
            logger.warning("ESPN kariéra %s selhala: %s", player_id, exc)

    # Na serveru NBA API neodpovídá – ESPN je pak nejrychlejší a nejspolehlivější
    if not stats and player_id:
        try:
            from . import espn_seasons

            espn = espn_seasons.career_stats(player_id, name)
            if espn and espn.get("gp", 0) >= 50:
                stats = dict(espn)
        except Exception as exc:  # pragma: no cover
            logger.warning("ESPN kariéra %s selhala: %s", player_id, exc)

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

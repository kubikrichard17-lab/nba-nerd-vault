"""
Kariérní žebříčky celé NBA (od 1946-47) z Basketball-Reference.

NBA API vydává jen sezónní tabulky od 1996-97, takže All-Time žebříčky
byly omezené. Basketball-Reference má hotové kariérní žebříčky celé ligy
pro každou statistiku – jeden request na statistiku, žádné stahování
tisíců hráčů.

Pozor na značky: jména s hvězdičkou = člen basketbalové Síně slávy.
Pořadí zůstává 1:1 podle zdroje.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

POOL_VERSION = 1

_POOL_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "career_leaders.json.gz"
)
_POOL_FILE_PLAIN = _POOL_FILE.replace(".json.gz", ".json")

_CACHE: Optional[Dict[str, Any]] = None
_LOCK = threading.Lock()

_BASE = "https://www.basketball-reference.com/leaders/{path}.html"
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

# náš klíč statistiky → (url cesta, sloupec v tabulce)
SOURCES: Dict[str, Dict[str, str]] = {
    "PTS": {"path": "pts_career", "col": "PTS"},
    "REB": {"path": "trb_career", "col": "TRB"},
    "AST": {"path": "ast_career", "col": "AST"},
    "STL": {"path": "stl_career", "col": "STL"},
    "BLK": {"path": "blk_career", "col": "BLK"},
    "FG3M": {"path": "fg3_career", "col": "3P"},
    "GP": {"path": "g_career", "col": "G"},
    "FGM": {"path": "fg_career", "col": "FG"},
    "FGA": {"path": "fga_career", "col": "FGA"},
    "FTM": {"path": "ft_career", "col": "FT"},
    "FTA": {"path": "fta_career", "col": "FTA"},
    "FG3A": {"path": "fg3a_career", "col": "3PA"},
    "TOV": {"path": "tov_career", "col": "TOV"},
}

# stejné statistiky jako průměr na zápas (jiná stránka zdroje)
SOURCES_PER_GAME: Dict[str, Dict[str, str]] = {
    "PTS": {"path": "pts_per_g_career", "col": "PTS"},
    "REB": {"path": "trb_per_g_career", "col": "TRB"},
    "AST": {"path": "ast_per_g_career", "col": "AST"},
    "STL": {"path": "stl_per_g_career", "col": "STL"},
    "BLK": {"path": "blk_per_g_career", "col": "BLK"},
    "FG3M": {"path": "fg3_per_g_career", "col": "3P"},
}


def _cells(row_html: str) -> List[str]:
    raw = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row_html, re.S)
    return [re.sub(r"<[^>]+>", "", c).strip() for c in raw]


def _download(path: str) -> str:
    import urllib.request

    url = _BASE.format(path=path)
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=45) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _parse_table(html: str) -> List[Dict[str, Any]]:
    match = re.search(r'<table[^>]*id="nba".*?</table>', html, re.S)
    if not match:
        return []
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", match.group(0), re.S)
    out: List[Dict[str, Any]] = []
    for row in rows[1:]:
        cells = _cells(row)
        if len(cells) < 3:
            continue
        rank_raw, player_raw, value_raw = cells[0], cells[1], cells[2]
        if not re.match(r"^\d+\.?$", rank_raw or ""):
            continue
        hall_of_fame = player_raw.endswith("*")
        name = player_raw.rstrip("*").strip()
        try:
            value = float(value_raw.replace(",", ""))
        except ValueError:
            continue
        out.append(
            {
                "rank": int(rank_raw.rstrip(".")),
                "name": name,
                "value": value,
                "hall_of_fame": hall_of_fame,
            }
        )
    return out


def _read_pool() -> Optional[Dict[str, Any]]:
    import gzip

    try:
        if os.path.exists(_POOL_FILE):
            with gzip.open(_POOL_FILE, "rt", encoding="utf-8") as fh:
                return json.load(fh)
        if os.path.exists(_POOL_FILE_PLAIN):
            with open(_POOL_FILE_PLAIN, encoding="utf-8") as fh:
                data = json.load(fh)
            _write_pool(data)
            return data
    except Exception as exc:  # pragma: no cover
        logger.warning("Kariérní žebříčky nešly načíst: %s", exc)
    return None


def _write_pool(data: Dict[str, Any]) -> None:
    import gzip

    try:
        tmp = _POOL_FILE + ".tmp"
        with gzip.open(tmp, "wt", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, _POOL_FILE)
        if os.path.exists(_POOL_FILE_PLAIN):
            try:
                os.remove(_POOL_FILE_PLAIN)
            except OSError:
                pass
    except Exception as exc:  # pragma: no cover
        logger.warning("Kariérní žebříčky nešly uložit: %s", exc)


def build_pool(force: bool = False) -> Dict[str, Any]:
    """Stáhne kariérní žebříčky všech statistik (14 requestů, ~1 min)."""
    if not force:
        data = _read_pool()
        if data and data.get("version") == POOL_VERSION and data.get("leaders"):
            return data

    started = time.time()
    leaders: Dict[str, List[Dict[str, Any]]] = {}
    failed: List[str] = []

    jobs = [(k, v, False) for k, v in SOURCES.items()] + [
        (k, v, True) for k, v in SOURCES_PER_GAME.items()
    ]
    for stat, src, per_game in jobs:
        rows: List[Dict[str, Any]] = []
        for attempt in range(3):
            try:
                html = _download(src["path"])
                rows = _parse_table(html)
                if rows:
                    break
            except Exception as exc:
                logger.warning("Kariérní žebříček %s (pokus %s): %s", stat, attempt + 1, exc)
            time.sleep(2 + attempt * 2)
        key = f"{stat}:pg" if per_game else stat
        if rows:
            leaders[key] = rows
        else:
            failed.append(key)
        time.sleep(3.5)  # ohleduplnost ke zdroji

    data = {
        "version": POOL_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "Basketball-Reference – Career Leaders (celá historie NBA od 1946-47)",
        "leaders": leaders,
        "failed": failed,
        "build_seconds": round(time.time() - started, 1),
    }
    _write_pool(data)

    logger.info(
        "Kariérní žebříčky hotovy: %s statistik, chybí %s, %.0f s",
        len(leaders),
        failed or "nic",
        time.time() - started,
    )
    return data


# --- klubové kariérní žebříčky (jedna stránka na klub, celá historie) ---
_FRANCHISE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "franchise_leaders"
)
_FRANCHISE_URL = "https://www.basketball-reference.com/teams/{abbr}/leaders_career.html"

# zdroj používá u některých klubů jinou zkratku než NBA
_FRANCHISE_SLUG = {
    "BKN": "NJN",   # Brooklyn Nets (zdroj je vede jako New Jersey)
    "NOP": "NOH",   # New Orleans Pelicans (dřív Hornets)
    "PHX": "PHO",   # Phoenix Suns
}

# náš klíč statistiky → klíč skupiny na stránce klubu
FRANCHISE_KEYS: Dict[str, str] = {
    "PTS": "pts",
    "REB": "trb",
    "AST": "ast",
    "STL": "stl",
    "BLK": "blk",
    "FG3M": "fg3",
    "GP": "g",
    "MIN": "mp",
    "FGM": "fg",
    "FGA": "fga",
    "FTM": "ft",
    "FTA": "fta",
    "FG3A": "fg3a",
    "TOV": "tov",
}


def _parse_franchise_page(html: str) -> Dict[str, List[Dict[str, Any]]]:
    """Vytáhne všechny klubové žebříčky ze stránky klubu (skupiny id="leaders_xxx")."""
    blocks = re.split(r'<div id="leaders_([a-z0-9]+)"', html)
    out: Dict[str, List[Dict[str, Any]]] = {}
    for i in range(1, len(blocks), 2):
        key, body = blocks[i], blocks[i + 1]
        entries = re.findall(
            r'<span class="rank">(\d+)\.</span>\s*<span class="who">(.*?)</span>'
            r'\s*<span class="value">\s*([\d.]+)</span>',
            body,
            re.S,
        )
        if not entries:
            continue
        rows = []
        for rank, who, value in entries:
            name = re.sub(r"<[^>]+>", "", who)
            hall_of_fame = name.rstrip().endswith("*")
            rows.append(
                {
                    "rank": int(rank),
                    "name": name.rstrip("*").strip(),
                    "value": float(value),
                    "hall_of_fame": hall_of_fame,
                }
            )
        out[key] = rows
    return out


def _gz_path(abbr: str) -> str:
    return os.path.join(_FRANCHISE_DIR, f"{abbr}.json.gz")


def _read_franchise(abbr: str) -> Optional[Dict[str, List[Dict[str, Any]]]]:
    """Načte klubový žebříček – nejdřív komprimovaný, pak starý nekomprimovaný."""
    plain = os.path.join(_FRANCHISE_DIR, f"{abbr}.json")
    gz = _gz_path(abbr)
    try:
        if os.path.exists(gz):
            import gzip

            with gzip.open(gz, "rt", encoding="utf-8") as fh:
                data = json.load(fh)
            return data.get("leaders") or None
        if os.path.exists(plain):
            with open(plain, encoding="utf-8") as fh:
                data = json.load(fh)
            leaders = data.get("leaders")
            if leaders:
                _write_franchise(abbr, leaders)  # převést na komprimovanou podobu
                try:
                    os.remove(plain)
                except OSError:
                    pass
                return leaders
    except Exception as exc:  # pragma: no cover
        logger.warning("Klubový žebříček %s nešel načíst: %s", abbr, exc)
    return None


def _write_franchise(abbr: str, leaders: Dict[str, List[Dict[str, Any]]]) -> None:
    """Uloží klubový žebříček komprimovaně (gzip) – na disku zabírá ~5× méně."""
    try:
        import gzip

        os.makedirs(_FRANCHISE_DIR, exist_ok=True)
        payload = {
            "abbr": abbr,
            "source": "Basketball-Reference – Club Career Leaders",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "leaders": leaders,
        }
        tmp = _gz_path(abbr) + ".tmp"
        with gzip.open(tmp, "wt", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, _gz_path(abbr))
    except Exception as exc:  # pragma: no cover
        logger.warning("Klubový žebříček %s nešel uložit: %s", abbr, exc)


def franchise_leaders(abbr: str, force: bool = False) -> Dict[str, List[Dict[str, Any]]]:
    """
    Klubové kariérní žebříčky z celé historie klubu (jeden request na klub).

    Ukládá se do backend/franchise_leaders/<ABBR>.json, takže další načtení
    je okamžité. Když soubor chybí, stáhne se (a při chybě se vrátí prázdno,
    aby aplikace nespadla).
    """
    abbr = abbr.upper()
    if not force:
        cached = _read_franchise(abbr)
        if cached:
            return cached

    html = ""
    for attempt in range(3):
        try:
            import urllib.request

            req = urllib.request.Request(
                _FRANCHISE_URL.format(abbr=_FRANCHISE_SLUG.get(abbr, abbr)),
                headers={"User-Agent": _UA},
            )
            with urllib.request.urlopen(req, timeout=45) as resp:
                html = resp.read().decode("utf-8", errors="replace")
            # zdroj někdy vrátí přesměrovací stránku – jdeme na správnou adresu
            redirect = re.search(r'URL=/(teams/[A-Za-z0-9]+/leaders_career\.html)', html)
            if redirect and "leaders_" not in html:
                req2 = urllib.request.Request(
                    "https://www.basketball-reference.com/" + redirect.group(1),
                    headers={"User-Agent": _UA},
                )
                with urllib.request.urlopen(req2, timeout=45) as resp2:
                    html = resp2.read().decode("utf-8", errors="replace")
            break
        except Exception as exc:
            logger.warning("Klub %s (pokus %s): %s", abbr, attempt + 1, exc)
            time.sleep(2 + attempt * 2)

    leaders = _parse_franchise_page(html) if html else {}
    if leaders:
        _write_franchise(abbr, leaders)
    return leaders


def franchise_rows(abbr: str, stat: str) -> List[Dict[str, Any]]:
    """Žebříček klubu pro jednu statistiku (celá historie), nebo []."""
    key = FRANCHISE_KEYS.get(stat.upper())
    if not key:
        return []
    return franchise_leaders(abbr).get(key) or []


def franchise_status() -> Dict[str, Any]:
    if not os.path.isdir(_FRANCHISE_DIR):
        return {"ready": 0, "teams": []}
    ready = sorted(
        {
            f.split(".")[0].upper()
            for f in os.listdir(_FRANCHISE_DIR)
            if f.endswith(".json") or f.endswith(".json.gz")
        }
    )
    return {"ready": len(ready), "teams": ready}


def pool() -> Dict[str, Any]:
    global _CACHE
    with _LOCK:
        if _CACHE is None:
            _CACHE = build_pool()
        return _CACHE


def leaders(stat: str) -> List[Dict[str, Any]]:
    """stat = 'PTS' nebo 'PTS:pg' (velikost písmen nerozhoduje)."""
    raw = str(stat or "").strip()
    base = raw.split(":")[0].upper()
    key = f"{base}:pg" if raw.lower().endswith(":pg") else base
    data = pool().get("leaders") or {}
    return data.get(key) or []


def status() -> Dict[str, Any]:
    data = _read_pool()
    if not data:
        return {"ready": False}
    try:
        return {
            "ready": True,
            "generated_at": data.get("generated_at"),
            "source": data.get("source"),
            "stats": list((data.get("leaders") or {}).keys()),
            "failed": data.get("failed") or [],
        }
    except Exception:
        return {"ready": False}

"""
enrich_vault_stats.py – v2: Správné API parametry, multiindex handling pro ShotLocations.

Stahuje:
  - LeagueDashPlayerStats (Advanced): ts_pct, usg_pct, ast_pct, trb_pct/orb/drb/stl/blk_pct,
    def_rating, off_rating
  - LeagueDashPlayerShotLocations: pct_fga_0_3 (Restricted Area), pct_fga_mid, pct_fga_3p

Spusť: python backend/scripts/enrich_vault_stats.py
"""

import os
import sys
import time
import logging
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger("enrich")

DB_PATH = ROOT / "nba_vault.db"

NEW_COLS = [
    ("dbpm",        "REAL"),
    ("obpm",        "REAL"),
    ("bpm",         "REAL"),
    ("dws",         "REAL"),
    ("ows",         "REAL"),
    ("ws",          "REAL"),
    ("per",         "REAL"),
    ("ts_pct",      "REAL"),
    ("usg_pct",     "REAL"),
    ("ast_pct",     "REAL"),
    ("trb_pct",     "REAL"),
    ("orb_pct",     "REAL"),
    ("drb_pct",     "REAL"),
    ("stl_pct",     "REAL"),
    ("blk_pct",     "REAL"),
    ("pct_fga_0_3", "REAL"),
    ("pct_fga_mid", "REAL"),
    ("pct_fga_3p",  "REAL"),
    ("pct_astd_fg", "REAL"),
    ("def_rating",  "REAL"),
    ("off_rating",  "REAL"),
]


def migrate_schema(con):
    cur = con.execute("PRAGMA table_info(player_season_stats)")
    existing = {row[1] for row in cur.fetchall()}
    added = []
    for col, dtype in NEW_COLS:
        if col not in existing:
            con.execute(f"ALTER TABLE player_season_stats ADD COLUMN {col} {dtype}")
            added.append(col)
    con.commit()
    log.info("Schéma: přidáno %d sloupců: %s", len(added), added or "žádné")


def _f(val):
    try:
        v = float(val)
        return None if v != v else v
    except (TypeError, ValueError):
        return None


def season_start_year(season_id):
    try:
        return int(str(season_id)[:4])
    except (TypeError, ValueError):
        return None


def nba_season_str(year):
    return f"{year}-{str(year + 1)[-2:]}"


def fetch_advanced_season(season):
    from nba_api.stats.endpoints import leaguedashplayerstats
    log.info("  Advanced: %s …", season)
    time.sleep(1.2)
    try:
        ep = leaguedashplayerstats.LeagueDashPlayerStats(
            season=season,
            measure_type_detailed_defense="Advanced",
            per_mode_detailed="PerGame",
            timeout=25,
        )
        df = ep.get_data_frames()[0]
    except Exception as exc:
        log.warning("    Chyba Advanced %s: %s", season, exc)
        return {}

    result = {}
    for _, row in df.iterrows():
        pid = int(row.get("PLAYER_ID", 0) or 0)
        if not pid:
            continue
        def _pct100(val):
            v = _f(val)
            return round(v * 100.0, 2) if v is not None and v <= 1.0 else v

        result[pid] = {
            "ts_pct":     _f(row.get("TS_PCT")),
            "usg_pct":    _pct100(row.get("USG_PCT")),
            "ast_pct":    _pct100(row.get("AST_PCT")),
            "trb_pct":    _pct100(row.get("REB_PCT")),
            "orb_pct":    _pct100(row.get("OREB_PCT")),
            "drb_pct":    _pct100(row.get("DREB_PCT")),
            "stl_pct":    _pct100(row.get("STL_PCT")),
            "blk_pct":    _pct100(row.get("BLK_PCT")),
            "def_rating": _f(row.get("DEF_RATING")),
            "off_rating": _f(row.get("OFF_RATING")),
            # PIE ≈ proxy pro celkový dopad
            "per":        _f(row.get("PIE")),
        }
    log.info("    → %d hráčů", len(result))
    return result


def fetch_shot_locations_season(season):
    """
    Multi-level columns: ('Restricted Area', 'FGA'), ('In The Paint (Non-RA)', 'FGA') …
    Flatten: ra_fga, paint_fga, mid_fga, lc3_fga, rc3_fga, atb3_fga
    """
    from nba_api.stats.endpoints import leaguedashplayershotlocations
    log.info("  ShotLocations: %s …", season)
    time.sleep(1.2)
    try:
        ep = leaguedashplayershotlocations.LeagueDashPlayerShotLocations(
            season=season,
            per_mode_detailed="PerGame",
            timeout=25,
        )
        df = ep.get_data_frames()[0]
    except Exception as exc:
        log.warning("    Chyba ShotLocations %s: %s", season, exc)
        return {}

    # Flatten multi-level columns → "Zone_Stat" (e.g. "Restricted Area_FGA")
    if hasattr(df.columns, 'levels'):
        df.columns = [
            f"{z}_{s}".strip("_") if z.strip() else s
            for z, s in df.columns
        ]

    def gcol(df, zone_key, stat):
        """Flexibilně najde sloupec podle části názvu."""
        for col in df.columns:
            if zone_key.lower() in col.lower() and stat.upper() in col.upper():
                return col
        return None

    result = {}
    for _, row in df.iterrows():
        # Zjisti player_id – může být v (, 'PLAYER_ID') nebo 'PLAYER_ID'
        pid = None
        for c in df.columns:
            if "PLAYER_ID" in str(c).upper():
                try:
                    pid = int(row[c] or 0)
                except (TypeError, ValueError):
                    pass
                break
        if not pid:
            continue

        def gv(zone_key, stat):
            col = gcol(df, zone_key, stat)
            return _f(row[col]) if col else 0.0

        ra_fga    = gv("Restricted Area", "FGA") or 0.0
        paint_fga = gv("In The Paint (Non-RA)", "FGA") or gv("Paint", "FGA") or 0.0
        mid_fga   = gv("Mid-Range", "FGA") or 0.0
        lc3_fga   = gv("Left Corner 3", "FGA") or 0.0
        rc3_fga   = gv("Right Corner 3", "FGA") or 0.0
        atb3_fga  = gv("Above the Break 3", "FGA") or 0.0

        total = ra_fga + paint_fga + mid_fga + lc3_fga + rc3_fga + atb3_fga
        if total < 0.1:
            continue

        result[pid] = {
            "pct_fga_0_3": round(ra_fga / total, 4),
            "pct_fga_mid": round((paint_fga + mid_fga) / total, 4),
            "pct_fga_3p":  round((lc3_fga + rc3_fga + atb3_fga) / total, 4),
        }

    log.info("    → %d hráčů", len(result))
    return result


def load_bref_data():
    """Načte BPM/DWS z lokálních .json.gz souborů."""
    import json, gzip
    result = {}
    for gz_path in list(ROOT.glob("*.json.gz")) + list(ROOT.glob("**/*.json.gz")):
        try:
            with gzip.open(gz_path, "rt", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        entries = data if isinstance(data, list) else data.get("players", [])
        for entry in (entries if isinstance(entries, list) else []):
            if not isinstance(entry, dict):
                continue
            nba_id = entry.get("nba_id") or entry.get("id")
            season = entry.get("season_id") or entry.get("season")
            if not nba_id or not season:
                continue
            patch = {k: _f(entry.get(k)) for k in
                     ("dbpm", "obpm", "bpm", "dws", "ows", "ws") if _f(entry.get(k)) is not None}
            if patch:
                result[(int(nba_id), str(season))] = patch
    if result:
        log.info("BRef fallback: %d záznamů", len(result))
    return result


def enrich(con):
    cur = con.cursor()
    cur.execute("""
        SELECT DISTINCT pss.player_id, pss.season_id, p.full_name
        FROM player_season_stats pss
        JOIN players p ON p.id = pss.player_id
        ORDER BY pss.season_id
    """)
    rows = cur.fetchall()
    if not rows:
        log.warning("Žádné sezóny v DB")
        return

    seasons = sorted(set(r[1] for r in rows))
    log.info("Sezóny v DB: %d (%s … %s)", len(seasons), seasons[0], seasons[-1])

    bref = load_bref_data()

    # Ke každé sezóně stáhneme Advanced (od 1996 i ShotLocations)
    adv_by_season: dict = {}
    shot_by_season: dict = {}
    SHOT_FIRST = 1996

    for s in seasons:
        yr = season_start_year(s)
        if yr is None:
            continue
        nba_s = nba_season_str(yr)
        if nba_s not in adv_by_season:
            adv_by_season[nba_s] = fetch_advanced_season(nba_s)
        if yr >= SHOT_FIRST and nba_s not in shot_by_season:
            shot_by_season[nba_s] = fetch_shot_locations_season(nba_s)

    updated = 0
    for player_id, season_id, name in rows:
        yr = season_start_year(season_id)
        nba_s = nba_season_str(yr) if yr else None

        patch = {}
        # 1. Advanced stats
        adv = adv_by_season.get(nba_s, {}).get(player_id, {}) if nba_s else {}
        for k, v in adv.items():
            if v is not None:
                patch[k] = v

        # 2. Shot locations
        shot = shot_by_season.get(nba_s, {}).get(player_id, {}) if nba_s else {}
        for k, v in shot.items():
            if v is not None:
                patch[k] = v

        # 3. BRef data
        for k, v in bref.get((player_id, season_id), {}).items():
            if v is not None:
                patch.setdefault(k, v)   # BRef nesmí přepsat NBA API hodnoty

        if not patch:
            continue

        set_clause = ", ".join(f"{k} = ?" for k in patch)
        vals = list(patch.values()) + [player_id, season_id]
        cur.execute(
            f"UPDATE player_season_stats SET {set_clause} "
            f"WHERE player_id = ? AND season_id = ?",
            vals,
        )
        updated += 1

    con.commit()
    log.info("Aktualizováno %d / %d řádků", updated, len(rows))


def report(con):
    cur = con.cursor()
    cur.execute("""
        SELECT
            COUNT(*) total,
            SUM(CASE WHEN ts_pct IS NOT NULL THEN 1 ELSE 0 END) has_ts,
            SUM(CASE WHEN pct_fga_0_3 IS NOT NULL THEN 1 ELSE 0 END) has_zones,
            SUM(CASE WHEN usg_pct IS NOT NULL THEN 1 ELSE 0 END) has_usg,
            SUM(CASE WHEN def_rating IS NOT NULL THEN 1 ELSE 0 END) has_dr
        FROM player_season_stats
    """)
    r = cur.fetchone()
    log.info("Stav DB: %d sezón total | ts_pct=%d | zones=%d | usg=%d | def_rating=%d",
             r[0], r[1], r[2], r[3], r[4])


if __name__ == "__main__":
    log.info("DB: %s", DB_PATH)
    con = sqlite3.connect(str(DB_PATH))
    con.execute("PRAGMA journal_mode=WAL")
    migrate_schema(con)
    enrich(con)
    report(con)
    con.close()
    log.info("HOTOVO.")

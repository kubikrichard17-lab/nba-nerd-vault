"""Doplnění sezónních metrik z cache. Síť se používá jen v ručním importu."""
from services import nba_external

KEY = "advanced-nba:v1:"
BBR_KEY = "advanced-bbr:v1:"
ADVANCED = ("ast_pct", "usg_pct", "orb_pct", "stl_pct", "blk_pct", "dbpm", "def_rating", "oreb", "trb_pct", "drb_pct", "dws")


def revision():
    from hashlib import blake2s

    entries = nba_external._load_memory()["entries"]
    relevant = sorted((k, v.get("t")) for k, v in entries.items()
                      if k.startswith(("advanced-", "espn-identity:", "espn-summary:", "nbainfo:", "bbrefseasons:")))
    return blake2s(repr(relevant).encode(), digest_size=6).hexdigest()


def cached_espn_id(player_id, name):
    link = nba_external._cache_get(f"espn-identity:v1:{player_id}", nba_external.TTL_PROFILE) or {}
    if name and nba_external.normalize_name(link.get("name")) == nba_external.normalize_name(name):
        return link.get("espn_id")
    return None


def consistent_career(player):
    # Pouze když zdroj skutečně pokrývá celou kariéru. Chrání proti starým
    # záznamům, kde správnému jménu patřily sezóny úplně jiného hráče.
    name = nba_external.normalize_name(player.full_name)
    tables = [nba_external._cache_get(BBR_KEY + str(s.season_id), nba_external.TTL_PROFILE)
              for s in player.stats if s.gp and s.gp >= 20]
    return not tables or not all(tables) or any(name in t for t in tables)


def nba_id_for_espn(espn_id):
    """Pouze dříve ověřené odkazy; žádné porovnávání stejných čísel napříč zdroji."""
    matches = set()
    for key in nba_external._load_memory()["entries"]:
        if not key.startswith("espn-identity:v1:"):
            continue
        link = nba_external._cache_get(key, nba_external.TTL_PROFILE) or {}
        if str(link.get("espn_id")) == str(espn_id) and link.get("name"):
            nba_id = int(key.rsplit(":", 1)[-1])
            if nba_id != espn_id:
                matches.add((nba_id, link["name"]))
    return next(iter(matches)) if len(matches) == 1 else (None, None)


def derive_boxscore(row, include_rates=True):
    from services.defense import optional_number, per100

    result = dict(row)
    num = lambda k: optional_number(row.get(k))
    fga, fta, pts, three = map(num, ("fga", "fta", "pts", "fg3a"))
    if fga is not None and fga > 0:
        for key, value in (("ts", pts / (2 * (fga + .44 * fta)) if pts is not None and fta is not None and fta >= 0 else None),
                           ("ftr", fta / fga if fta is not None else None),
                           ("3par", three / fga if three is not None else None)):
            if num(key) is None and value is not None:
                result[key] = value
    minutes = num("min_per_game")
    if include_rates and minutes and minutes > 0:
        for key in ("pts", "reb", "ast", "blk", "stl", "oreb"):
            value = num(key)
            if value is not None:
                result.setdefault(key + "36", value * 36 / minutes)
                result.setdefault(key + "100", per100(value, minutes, row.get("season_id")))
    return result


def enrich(player_id, name, rows, espn_id=None):
    from services.defense import optional_number

    norm = nba_external.normalize_name
    payload = nba_external._cache_get(KEY + str(player_id), nba_external.TTL_PROFILE) or {}
    nba = payload.get("seasons", {}) if norm(payload.get("name")) == norm(name) else {}
    slug = nba_external._cache_get("slug:" + norm(name), nba_external.TTL_SLUG)
    bb = nba_external._cache_get("bbrefseasons:" + slug, nba_external.TTL_PROFILE) if isinstance(slug, str) else []
    bb = {r.get("SEASON_ID"): r for r in bb or []}
    espn = nba_external._cache_get(f"espn-summary:v1:{espn_id}", nba_external.TTL_PROFILE) if espn_id else []
    espn = {r.get("season_id"): r for r in espn or []}
    result = []
    for row in rows:
        season = row.get("season_id")
        row = dict(row)
        # Metriky připojujeme pouze ke stejné identitě, sezóně a počtu zápasů.
        basketball_ref = bb.get(season, {})
        if basketball_ref.get("GP") == row.get("gp"):
            for k in (*ADVANCED, "ast", "stl", "blk", "fga", "fta", "fg3a"):
                if row.get(k) is None:
                    row[k] = optional_number(basketball_ref.get(k.upper()))
        bbr = nba_external._cache_get(BBR_KEY + str(season), nba_external.TTL_PROFILE) or {}
        matching = bbr.get(norm(name), [])
        reference = matching[0] if len(matching) == 1 else {}
        for source in (reference, nba.get(season, {}), espn.get(season, {})):
            if source.get("gp") == row.get("gp"):
                for k in (*ADVANCED, "ast", "stl", "blk", "fga", "fta", "fg3a"):
                    if row.get(k) is None and source.get(k) is not None:
                        row[k] = optional_number(source[k])
        from services.shot_context import season_year
        year = season_year(season)
        if year is not None and year < 1973:
            for key in ("stl", "blk", "oreb", "stl_pct", "blk_pct", "orb_pct"):
                row[key] = None
        result.append(derive_boxscore(row))
    return result


def import_nba_season(season, timeout=15):
    """Explicitní import oficiálních NBA statistik, ne součást HTTP požadavku."""
    from nba_api.stats.endpoints import leaguedashplayerstats
    from services.defense import optional_number

    frame = leaguedashplayerstats.LeagueDashPlayerStats(
        season=season, season_type_all_star="Regular Season", measure_type_detailed_defense="Advanced",
        timeout=timeout,
    ).get_data_frames()[0]
    count = 0
    for row in frame.to_dict("records"):
        pid, name = int(row["PLAYER_ID"]), row["PLAYER_NAME"]
        stats = {key: optional_number(row.get(col)) for key, col in (
            ("ast_pct", "AST_PCT"), ("orb_pct", "OREB_PCT"), ("usg_pct", "USG_PCT"),
            ("trb_pct", "REB_PCT"),
            ("def_rating", "DEF_RATING"), ("gp", "GP"),
        )}
        for key in ("ast_pct", "orb_pct", "usg_pct"):
            if stats[key] is not None:
                stats[key] *= 100  # NBA endpoint uses fractions; model uses percentage points.
        key = KEY + str(pid)
        known = nba_external._cache_get(key, nba_external.TTL_PROFILE) or {}
        seasons = dict(known.get("seasons", {}))
        seasons[season] = stats
        nba_external._cache_set(key, {"name": name, "seasons": seasons})
        count += 1
    nba_external._save_memory(nba_external._load_memory())
    return count


def import_bbr_season(season, timeout=15):
    """Ligová tabulka regulérní sezóny; při HTTP chybě nic neukládat."""
    from collections import defaultdict
    from html import unescape
    import re
    from services.defense import optional_number

    year = int(season[:4]) + 1
    page = nba_external._http_get(f"https://www.basketball-reference.com/leagues/NBA_{year}_advanced.html", timeout=timeout)
    table = re.search(r'<table[^>]*id="advanced"[^>]*>(.*?)</table>', page, re.S)
    if not table:
        raise ValueError("Tabulka advanced chybí")
    players = {}
    for row in re.findall(r'<tr[^>]*>(.*?)</tr>', table[1], re.S):
        cells = dict(re.findall(r'<td[^>]*data-stat="([^"]+)"[^>]*>(.*?)</td>', row, re.S))
        link = re.search(r'/players/[^/]+/([a-z0-9]+)\.html', cells.get("name_display", ""))
        if not link:
            continue
        text = lambda key: unescape(re.sub(r'<[^>]+>', '', cells.get(key, ""))).strip()
        gp = optional_number(text("games"))
        if not gp:
            continue
        # Celosezónní řádek má více zápasů než kterýkoliv dílčí tým.
        athlete = link[1]
        if athlete not in players or gp > players[athlete][1]["gp"]:
            players[athlete] = (nba_external.normalize_name(text("name_display")),
                                {"gp": gp, **{k: optional_number(text(k)) for k in ADVANCED}})
    if not players:
        raise ValueError("Tabulka neobsahuje žádné použitelné řádky")
    by_name = defaultdict(list)
    for name, stats in players.values():
        by_name[name].append(stats)
    nba_external._cache_set(BBR_KEY + season, dict(by_name))
    nba_external._save_memory(nba_external._load_memory())
    return len(players)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("season", nargs="+", help="Sezóna ve formátu 2024-25")
    parser.add_argument("--source", choices=("nba", "bbr"), default="nba")
    args = parser.parse_args()
    importer = import_nba_season if args.source == "nba" else import_bbr_season
    for season in args.season:
        print(f"{season}: zapsáno do cache {importer(season)} hráčů", flush=True)

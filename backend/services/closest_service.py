"""
Prime a fáze kariéry – integrace do API.

`/api/players/{id}/closest` volá `closest_player.resolve()` jednou pro
vrcholnou verzi hráče a (u hráčů, kteří se během kariéry proměnili) jednou
pro ranou a jednou pro pozdní fázi. Každé volání má stejnou strukturu jako
dřív, takže UI se nemusí učit nic nového – jen se přepíná mezi výsledky.

Cache: klíč obsahuje verzi výpočtu. Stará cache se při prvním požadavku
smaže, aby se nezobrazovaly výsledky z dřívějšího (kariérního) modelu.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from services import advanced_cache, closest_player, nba_external
from services.career_phases import career_phases

logger = logging.getLogger(__name__)


def season_rows(player, espn_id=None) -> List[Dict[str, Any]]:
    """
    Sezóny hráče ve tvaru, který bere career_phases.
    Chybějící statistiky (starší éra) zůstávají None – model si je přeskočí.
    """
    rows: List[Dict[str, Any]] = []
    for row in sorted(player.stats or [], key=lambda s: s.season_id or ""):
        rows.append(
            {
                "season_id": row.season_id,
                "gp": row.gp,
                "pts": row.pts,
                "reb": row.reb,
                "ast": row.ast,
                "stl": row.stl,
                "blk": row.blk,
                "tov": row.tov,
                "fgm": row.fgm,
                "fga": row.fga,
                "fg3m": row.fg3m,
                "fg3a": row.fg3a,
                "ftm": row.ftm,
                "fta": row.fta,
                "min_per_game": row.min_per_game,
                "dbpm": row.dbpm,
                "obpm": row.obpm,
                "bpm": row.bpm,
                "dws": row.dws,
                "ows": row.ows,
                "ws": row.ws,
                "per": row.per,
                "ts_pct": row.ts_pct,
                "usg_pct": row.usg_pct,
                "ast_pct": row.ast_pct,
                "trb_pct": row.trb_pct,
                "orb_pct": row.orb_pct,
                "drb_pct": row.drb_pct,
                "stl_pct": row.stl_pct,
                "blk_pct": row.blk_pct,
                "pct_fga_0_3": row.pct_fga_0_3,
                "pct_fga_mid": row.pct_fga_mid,
                "pct_fga_3p": row.pct_fga_3p,
                "pct_astd_fg": row.pct_astd_fg,
                "def_rating": row.def_rating,
                "off_rating": row.off_rating,
            }
        )
    # Nezapočítej týmové dílčí řádky dvakrát; nejvíc zápasů má sezónní součet.
    by_season = {}
    for row in rows:
        season = row["season_id"]
        if season and (row["gp"] or 0) > (by_season.get(season, {}).get("gp") or 0):
            by_season[season] = row
    return advanced_cache.enrich(player.id, player.full_name, list(by_season.values()), espn_id)


def _decorate(result: Dict[str, Any], match, db) -> Dict[str, Any]:
    """Doplní data, která UI zobrazuje (fotka, tým, tagy, shrnutí)."""
    if not result or not result.get("closest"):
        return result
    closest = result["closest"]
    if match:
        closest["headshot_url"] = match.headshot_url
        closest["is_active"] = bool(match.is_active)
        try:
            import json

            closest["playstyle_tags"] = (
                json.loads(match.playstyle_tags) if match.playstyle_tags else []
            )
        except Exception:
            closest["playstyle_tags"] = []
        closest["summary_source"] = "local"
    else:
        closest["headshot_url"] = (
            "https://cdn.nba.com/headshots/nba/latest/1040x760/"
            f"{closest['id']}.png"
        )
        closest["is_active"] = False
        closest["playstyle_tags"] = []
    closest["summary_cs"] = result.get("style_comparison") or result.get("reasoning")
    closest["stylistic_pct"] = closest.get("style_pct")
    closest["statistical_pct"] = closest.get("stats_pct")
    return result


def comparison_dimensions(player_id, position, height, weight):
    known = nba_external._cache_get(f"nbainfo:{player_id}", nba_external.TTL_PROFILE) or {}
    return (known.get("position") or position, known.get("height_cm") or height,
            known.get("weight_kg") or weight)


def canonical_player(player, db):
    """Preferuj externě ověřené NBA ID, pokud jsou jeho sezóny již uložené."""
    from models import Player

    name = nba_external.normalize_name(player.full_name)
    matches = _nba_ids().get(name, ())
    if len(matches) == 1 and matches[0] != player.id:
        alternate = db.get(Player, matches[0])
        if alternate and alternate.stats and nba_external.normalize_name(alternate.full_name) == name:
            return alternate
    return player


from functools import lru_cache


@lru_cache(maxsize=1)
def _nba_ids():
    from nba_api.stats.static import players

    by_name = {}
    for entry in players.get_players():
        by_name.setdefault(nba_external.normalize_name(entry["full_name"]), []).append(entry["id"])
    return by_name


def phase_metadata(player, rows=None):
    from services.career_phases import _blend

    espn_id = advanced_cache.cached_espn_id(player.id, player.full_name)
    rows = season_rows(player, espn_id) if rows is None else rows
    pos, height, weight = comparison_dimensions(player.id, player.position, player.height_cm, player.weight_kg)
    def build(stat):
        return closest_player.build_profile(player.id, player.full_name, pos, height, weight,
                                            {**stat, "espn_id": espn_id})
    base = build(_blend(rows))
    metadata = career_phases(rows, base, closest_player.build_profile)
    for phase in [metadata.get("prime"), *metadata.get("phases", [])]:
        if phase:
            phase["profile"] = build(phase["stat"])
    return rows, base, metadata


def phase_for_player(player, key="prime", prepared=None):
    rows, base, phases = prepared if prepared is not None else phase_metadata(player)
    if key == "career":
        return base if rows else None
    if key == "prime":
        return (phases.get("prime") or {}).get("profile")
    if key in ("early", "late"):
        return next((p["profile"] for p in phases["phases"] if p["key"] == key), None)
    row = next((row for row in rows if row["season_id"] == key), None)
    if row is None:
        return None
    return closest_player.build_profile(player.id, player.full_name, base["position"], base["height_cm"],
                                        base["weight_kg"], row)


def prime_for_player(player):
    return phase_for_player(player)


def build_closest_payload(player, db, raw_pool):
    from models import Player
    from sqlalchemy.orm import selectinload

    prepared = phase_metadata(player)
    _, base, phases = prepared
    if not phases.get("prime"):
        return None
    # Sezónní souhrny udržované existujícími importy; bez žádostí o data při výběru.
    # Vrchol sezóny je předvýběr, nikdy zdroj finálního procenta.
    players = db.query(Player).options(selectinload(Player.stats)).filter(Player.stats.any()).all()
    by_id = {int(row["id"]): row for row in raw_pool if row.get("id")}
    by_name = {nba_external.normalize_name(row.get("name")): row for row in raw_pool if row.get("name")}
    roster = []
    all_ids = {p.id for p in players}
    for other in players:
        canonical = _nba_ids().get(nba_external.normalize_name(other.full_name), ())
        if len(canonical) == 1 and canonical[0] != other.id and canonical[0] in all_ids:
            if canonical_player(other, db).id != other.id:
                continue
        extra = by_id.get(other.id) or by_name.get(nba_external.normalize_name(other.full_name)) or {}
        espn_id = extra.get("espn_id") if nba_external.normalize_name(extra.get("name")) == nba_external.normalize_name(other.full_name) else None
        identity = {"id": other.id, "name": other.full_name, "espn_id": espn_id}
        if closest_player.same_player(base, identity) or not advanced_cache.consistent_career(other):
            continue
        metadata = phase_metadata(other)
        credible = [r for r in metadata[0] if r.get("gp", 0) >= 45] or metadata[0]
        peak = max((r.get("pts") or 0 for r in credible), default=0.)
        roster.append((other, metadata, peak))

    def resolve(target, phase_key):
        profiles = []
        for other, metadata, peak in roster:
            career = metadata[1]
            if not closest_player.compatible_dimensions(career, target):
                continue
            if peak < target["pts"] * .40:
                continue
            profile = phase_for_player(other, phase_key, prepared=metadata)
            if profile:
                profiles.append(profile)
        result = closest_player.resolve_cached(target, profiles)
        if result:
            result["basis"] = phase_key
        return result

    prime = phases["prime"]
    result = resolve(prime["profile"], "prime")
    if not result:
        return None
    result["prime"] = {"label": "Vrchol kariéry", "season": prime["season"], "seasons": prime["seasons"]}
    result["career_profile"] = {k: base.get(k) for k in ("pts", "reb", "ast")}
    result["has_major_evolution"] = bool(phases["has_major_evolution"])
    result["evolution_note"] = phases["evolution_note"]
    result["career_phases"] = []
    for phase in phases["phases"]:
        resolved = resolve(phase["profile"], phase["key"])
        if resolved:
            resolved["phase"] = {k: phase[k] for k in ("key", "label", "season", "seasons", "gp")}
            resolved["phase"]["range"] = phase["label_range"]
            result["career_phases"].append(resolved)
    return result

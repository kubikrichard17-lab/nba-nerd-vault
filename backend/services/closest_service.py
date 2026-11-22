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
from typing import Any, Dict, List, Optional

from services import closest_player, nba_external
from services.career_phases import career_phases

logger = logging.getLogger(__name__)


def season_rows(player) -> List[Dict[str, Any]]:
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
            }
        )
    return rows


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


def _resolve_for(profile: Dict[str, Any], pool: List[Dict[str, Any]], label: str) -> Optional[Dict[str, Any]]:
    """Jedno volání modelu pro danou verzi hráče."""
    result = closest_player.resolve(profile, pool)
    if result:
        result["basis"] = label
    return result


def build_closest_payload(
    player,
    db,
    pool: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """
    Sestaví odpověď pro `/api/players/{id}/closest`:

      closest / style_comparison / …   – vrcholná verze (Prime)
      prime                            – z jakých sezón se Prime počítá
      has_major_evolution              – změnil hráč zásadně styl?
      career_phases                    – [{key, label, closest, …}, …]
      evolution_note                   – co se konkrétně změnilo
    """
    external = nba_external.career_profile(player.id, player.full_name) or {}
    position = external.get("position") or player.position
    height_cm = external.get("height_cm") or player.height_cm
    weight_kg = external.get("weight_kg") or player.weight_kg
    awards = len(player.awards or [])

    career_stat = dict(external) if external else {}
    base = closest_player.build_profile(
        player_id=player.id,
        name=player.full_name,
        position=position,
        height_cm=height_cm,
        weight_kg=weight_kg,
        stat=career_stat,
        awards_count=awards,
    )

    phases = career_phases(season_rows(player), base, closest_player.build_profile)
    prime = phases.get("prime") or {}
    prime_profile = prime.get("profile") or base

    # 1) Prime – výchozí srovnání
    result = _resolve_for(prime_profile, pool, "prime")
    if not result:
        return None

    result["prime"] = {
        "label": "Vrchol kariéry",
        "season": prime.get("season", ""),
        "seasons": prime.get("seasons", []),
    }
    result["basis"] = "prime"
    result["career_profile"] = {
        "pts": base.get("pts"),
        "reb": base.get("reb"),
        "ast": base.get("ast"),
    }
    result["has_major_evolution"] = bool(phases.get("has_major_evolution"))
    result["evolution_note"] = phases.get("evolution_note", "")

    # 2) Fáze kariéry – jen když se hráč opravdu proměnil
    phase_results: List[Dict[str, Any]] = []
    if result["has_major_evolution"]:
        for phase in phases.get("phases") or []:
            phase_profile = phase.get("profile")
            if not phase_profile:
                continue
            resolved = _resolve_for(phase_profile, pool, phase["key"])
            if not resolved:
                continue
            resolved["phase"] = {
                "key": phase["key"],
                "label": phase["label"],
                "season": phase.get("season", ""),
                "seasons": phase.get("seasons", []),
                "range": phase.get("label_range", ""),
                "gp": phase.get("gp", 0),
            }
            phase_results.append(resolved)
    result["career_phases"] = phase_results
    return result

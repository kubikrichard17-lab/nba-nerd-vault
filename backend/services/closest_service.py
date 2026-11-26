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
from typing import Any, Dict, List, Optional, Tuple

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


def _find_player(name: str) -> Tuple[Optional[int], str]:
    """
    Najde hráče podle jména: nejdřív databáze aplikace, pak registr NBA.
    V cloudu (ESPN) je registr NBA nedostupný, takže bez databáze by
    navržení kandidáti neměli odkud vzít sezóny.
    """
    try:
        import models
        from database import SessionLocal
        from services.espn_seasons import _plain

        session = SessionLocal()
        try:
            rows = session.query(models.Player).all()
        finally:
            session.close()
        wanted = _plain(name)
        for row in rows:
            if _plain(row.full_name) == wanted:
                return int(row.id), row.full_name
        for row in rows:
            if wanted and wanted in _plain(row.full_name):
                return int(row.id), row.full_name
    except Exception as exc:  # pragma: no cover
        logger.warning("Hráče %s nešlo najít v databázi: %s", name, exc)

    # Registr NBA (lokálně) – v cloudu je nedostupný, proto se zkouší dál.
    try:
        from nba_api.stats.static import players as nba_players

        found = nba_players.find_players_by_full_name(name)
        exact = [p for p in found if p["full_name"].lower() == name.lower()] or found
        if exact:
            return int(exact[0]["id"]), exact[0]["full_name"]
    except Exception:
        pass

    # ESPN podle jména – jediná cesta, jak na serveru najít legendu.
    try:
        from services import espn_seasons

        espn_id = espn_seasons.search_athlete(name)
        if espn_id:
            return int(espn_id), name
    except Exception as exc:  # pragma: no cover
        logger.warning("Hráče %s nešlo najít v ESPN: %s", name, exc)
    return None, name


def _season_rows_for(player_id: int) -> List[Dict[str, Any]]:
    """
    Sezóny hráče pro výpočet vrcholu. V cloudu (ESPN) se berou z ESPN,
    lokálně z NBA API; když jeden zdroj nic nevrátí, zkusí se druhý.
    """
    rows: List[Dict[str, Any]] = []

    try:
        from services import source_switch

        espn_first = source_switch.espn_first()
    except Exception:  # pragma: no cover
        espn_first = False

    if espn_first:
        try:
            from services import espn_seasons

            for r in espn_seasons.player_season_stats(player_id) or []:
                if (r.get("gp") or 0) > 0:
                    rows.append(dict(r))
        except Exception as exc:  # pragma: no cover
            logger.warning("Sezóny %s z ESPN selhaly: %s", player_id, exc)

    if not rows:
        try:
            from services import nba_fetcher

            frame = nba_fetcher._career_frame(player_id)
            for r in nba_fetcher._career_rows(frame) if frame is not None else []:
                gp = int(r.get("GP") or 0)
                if gp <= 0:
                    continue
                rows.append({
                    "season_id": str(r.get("SEASON_ID")), "gp": gp,
                    "pts": r.get("PTS"), "reb": r.get("REB"), "ast": r.get("AST"),
                    "stl": r.get("STL"), "blk": r.get("BLK"), "tov": r.get("TOV"),
                    "fgm": r.get("FGM"), "fga": r.get("FGA"), "fg3m": r.get("FG3M"),
                    "fg3a": r.get("FG3A"), "ftm": r.get("FTM"), "fta": r.get("FTA"),
                    "min_per_game": r.get("MIN"),
                })
        except Exception as exc:  # pragma: no cover
            logger.warning("Sezóny %s z NBA API selhaly: %s", player_id, exc)
    return rows


def _profile_by_name(name: str) -> Optional[Dict[str, Any]]:
    """
    Prime profil hráče stažený za běhu (jen pro navržené kandidáty).
    Nic se neukládá do databáze; sezóny i ocenění jdou přes dočasnou paměť.
    """
    try:
        pid, full = _find_player(name)
        if not pid:
            return None

        rows = _season_rows_for(pid)
        if not rows:
            return None
        size = nba_external.position_and_size(pid, full) or {}
        from services.career_phases import prime_window, _blend

        stat = _blend(prime_window(rows))
        stat["fg_pct"] = (stat.get("fgm") or 0) / stat["fga"] if stat.get("fga") else 0.0
        stat["fg3_pct"] = (stat.get("fg3m") or 0) / stat["fg3a"] if stat.get("fg3a") else 0.0
        stat["ft_pct"] = (stat.get("ftm") or 0) / stat["fta"] if stat.get("fta") else 0.0
        return closest_player.build_profile(
            player_id=pid, name=full,
            position=size.get("position"), height_cm=size.get("height_cm"),
            weight_kg=size.get("weight_kg"), stat=stat,
        )
    except Exception as exc:  # pragma: no cover
        logger.warning("Kandidát %s se nenačetl: %s", name, exc)
        return None


def _suggested(profile: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Fáze 1: AI navrhne jména, fáze 2: stáhnou se jen jejich data."""
    names = closest_player.ai_suggest(profile)
    if not names:
        return []
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=5) as ex:
        found = list(ex.map(_profile_by_name, names))
    return [p for p in found if p]


def comparison_dimensions(player_id, position, height, weight):
    known = nba_external._cache_get(f"nbainfo:{player_id}", nba_external.TTL_PROFILE) or {}
    return (known.get("position") or position, known.get("height_cm") or height,
            known.get("weight_kg") or weight)


def prime_for_player(player):
    from services.career_phases import _blend, prime_window

    rows = season_rows(player)
    pos, height, weight = comparison_dimensions(player.id, player.position, player.height_cm, player.weight_kg)
    return closest_player.build_profile(player.id, player.full_name, pos, height, weight, _blend(prime_window(rows)))


def _refine_candidates(target, pool):
    """Na vyžádání ověří vrchol krátkého výběru, paralelně a jednou pro všechny fáze."""
    from concurrent.futures import ThreadPoolExecutor
    from services import espn_seasons
    from services.career_phases import _blend, prime_window

    shortlist = closest_player.preselect(target, pool, limit=6)
    # Kariérní průměr může skrýt vrchol (zejména u dlouhých kariér).
    # Část výběru proto rezervujeme hráčům ze stejné role a s podobnou postavou.
    names = {nba_external.normalize_name(c["name"]) for c in [target, *shortlist]}
    same_role = sorted(
        (c for c in pool if c["role_group"] == target["role_group"]
         and c["pts"] >= max(2, target["pts"] * 0.62)
         and abs(c["height_cm"] - target["height_cm"]) <= 10
         and nba_external.normalize_name(c["name"]) not in names),
        key=lambda c: (c["archetype"] != target["archetype"],
                       abs(c["height_cm"] - target["height_cm"]) * 0.25 + abs(c["pts"] - target["pts"]),
                       c["id"]),
    )
    shortlist.extend(same_role[:4])
    names.update(nba_external.normalize_name(c["name"]) for c in shortlist)
    # Doplň i historické profily, kde v souhrnu může chybět přesná pozice.
    established = sorted(
        (c for c in pool if nba_external.normalize_name(c["name"]) not in names
         and c["pts"] >= target["pts"] * 0.58
         and abs(c["height_cm"] - target["height_cm"]) <= 8),
        key=lambda c: (abs(c["pts"] - target["pts"]) + abs(c["height_cm"] - target["height_cm"]) * 0.35,
                       c["id"]),
    )
    shortlist.extend(established[:4])
    def refine(candidate):
        rows = espn_seasons.player_season_stats(candidate["id"], name=candidate["name"],
                                                espn_id=candidate.get("espn_id"), allow_legacy=False)
        if not rows:
            return candidate
        stat = _blend(prime_window(rows))
        pos, height, weight = comparison_dimensions(candidate["id"], candidate["position"],
                                                     candidate["height_cm"], candidate["weight_kg"])
        profile = closest_player.build_profile(candidate["id"], candidate["name"], pos, height, weight, stat)
        return profile

    with ThreadPoolExecutor(max_workers=14) as executor:
        refined = list(executor.map(refine, shortlist))
    resolved = [c for original, c in zip(shortlist, refined) if c is not original]
    return resolved


def _resolve_for(profile: Dict[str, Any], pool: List[Dict[str, Any]], label: str) -> Optional[Dict[str, Any]]:
    """Jedno volání modelu pro danou verzi hráče."""
    if nba_external.source_switch.espn_first():
        result = closest_player.resolve_cached(profile, pool)
        if result:
            result["basis"] = label
        return result
    suggested = _suggested(profile)
    # Diagnostika pro log serveru – z kolika návrhů se opravdu počítalo.
    logger.info(
        "Nejbližší hráč (%s): AI navrhla %s",
        label,
        [c.get("name") for c in suggested] or "nic",
    )
    result = None
    if len(suggested) >= 2:
        result = closest_player.resolve(
            profile, pool, suggested=suggested, allow_below_pool=True
        )
        # AI smí navrhnout jen hráče, kteří mají co porovnávat. Když z pěti
        # návrhů zbyl jediný (ostatní se nedohledali nebo byli vyloučeni
        # tvrdým filtrem obrany), srovnává se raději podle předvýběru –
        # jinak by Jordan skončil u jediného kandidáta s 40 % shody.
        if result and len(result.get("top_3_candidates") or []) < 2:
            logger.info("Nejbližší hráč (%s): z návrhů zbyl jediný kandidát, bere se předvýběr", label)
            result = None
    if not result:
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
    rows = season_rows(player)
    if nba_external.source_switch.espn_first() and not rows:
        return None
    external = ({} if rows else nba_external.career_profile(player.id, player.full_name) or {})
    position, height_cm, weight_kg = comparison_dimensions(
        player.id, external.get("position") or player.position,
        external.get("height_cm") or player.height_cm, external.get("weight_kg") or player.weight_kg
    )
    awards = 0 if nba_external.source_switch.espn_first() else len(player.awards or [])

    from services.career_phases import _blend

    career_stat = _blend(rows) if rows else dict(external)
    if external:
        # Kariéra se pamatuje (dočasně) – slouží i jako kandidát pro
        # ostatní hráče, takže legenda mimo sezónní tabulku nezmizí.
        nba_external.remember_career(player.id, player.full_name, external)
    award_detail = (closest_player.defense.empty_awards() if nba_external.source_switch.espn_first()
                    else closest_player.defense.award_profile(player.id))
    base = closest_player.build_profile(
        player_id=player.id,
        name=player.full_name,
        position=position,
        height_cm=height_cm,
        weight_kg=weight_kg,
        stat=career_stat,
        awards_count=awards,
        award_detail=award_detail,
    )

    phases = career_phases(rows, base, closest_player.build_profile)
    prime = phases.get("prime") or {}
    prime_profile = prime.get("profile") or base
    if nba_external.source_switch.espn_first():
        prime_profile = prime_for_player(player)
        pool = _refine_candidates(prime_profile, pool)
    else:
        closest_player.apply_awards(prime_profile, award_detail)

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
            closest_player.apply_awards(phase_profile, award_detail)
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

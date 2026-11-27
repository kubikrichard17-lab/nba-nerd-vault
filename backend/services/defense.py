"""
Obrana, ocenění, tempo éry, postava a střelecký profil – podklady pro
„Nejbližšího hráče".

Nic se nepředvyplňuje do databáze. Ocenění hráče se za běhu stáhnou z ESPN
a drží se jen v dočasné paměti `external_pool.json.gz` s vypršením (TTL).

Obranná úroveň (defense_tier):
  elite    – DPOY, opakovaně All-Defensive, nebo výrazně nadprůměrné
             zisky + bloky na 100 držení
  average  – zbytek, i hráči, o kterých nevíme dost (starší éra bez STL/BLK)
  weak     – statistiky známe, jsou podprůměrné a hráč nemá obranná ocenění
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

TTL_AWARDS = 14 * 24 * 3600

# Číselník ocenění ESPN (pevná taxonomie ocenění, ne seznam hráčů).
_AWARD_KIND = {
    "33": "mvp",
    "39": "dpoy",
    "44": "all_nba",
    "45": "all_nba",
    "46": "all_nba",
    "49": "all_def",
    "50": "all_def",
}

# Tempo ligy (držení na 48 minut) podle období – pro přepočet na 100 držení.
_PACE = (
    (1950, 120.0),
    (1960, 125.0),
    (1970, 106.0),
    (1980, 101.5),
    (1990, 96.0),
    (2000, 91.5),
    (2010, 93.5),
    (2015, 97.0),
    (2020, 99.5),
)


def era_pace(season_id: Optional[str]) -> float:
    """Tempo ligy v dané sezóně (např. '1987-88' → 101.5)."""
    try:
        year = int(str(season_id)[:4])
    except (TypeError, ValueError):
        return 98.0
    pace = _PACE[0][1]
    for start, value in _PACE:
        if year >= start:
            pace = value
    return pace


def per100(value: Any, minutes: Any, season_id: Optional[str]) -> Optional[float]:
    """Hodnota na zápas → na 100 držení míče (podle minut a tempa éry)."""
    v = _num(value)
    m = _num(minutes)
    if v is None or not m or m <= 0:
        return None
    return round(v * (48.0 / max(m, 1.0)) * (100.0 / era_pace(season_id)), 2)


def optional_number(value):
    import math

    v = _num(value)
    return v if v is not None and math.isfinite(v) else None


def defensive_rates(stat, season):
    from services.shot_context import season_year

    result = {"dbpm": optional_number(stat.get("dbpm")), "def_rating": optional_number(stat.get("def_rating"))}
    year = season_year(season)
    for k in ("stl", "blk"):
        pct = optional_number(stat.get(k + "_pct"))
        per = per100(stat.get(k), stat.get("min_per_game"), season)
        result[k] = pct if pct is not None else per if year is None or year >= 1973 else None
        result[k + "_is_pct"] = pct is not None
        result[k + "100"] = per if year is None or year >= 1973 else None
    return result


DEFENSIVE_STYLE_LABEL = {
    "switchable_wing": "mobilní obousměrný obránce",
    "mobile_big": "mobilní podkošový obránce",
    "paint_anchor": "podkošová kotva",
}


def defensive_style(stat, season, height, weight, position, rates):
    """Typ obrany, nikoli měřená mobilita. Chybějící signál není nula."""
    from services.shot_context import season_year

    height, weight = optional_number(height), optional_number(weight)
    if not height or not weight:
        return None
    stl, blk = rates.get("stl"), rates.get("blk")
    drb, orb = optional_number(stat.get("drb_pct")), optional_number(stat.get("orb_pct"))
    mins, reb = optional_number(stat.get("min_per_game")), optional_number(stat.get("reb"))
    reb36 = reb * 36 / mins if reb is not None and mins and mins > 0 else None
    year = season_year(season)
    big = position == "C" or height >= 207
    dws = optional_number(stat.get("dws"))
    if year is not None and year < 1973 and big and (
        (reb36 is not None and reb36 >= 14) or (dws is not None and dws >= 6 and (reb36 or 0) >= 10)
    ):
        return "paint_anchor"
    boards = (drb or 0) >= 21 or (orb or 0) >= 8 or (reb36 or 0) >= 9.5
    if big and weight >= 120 and boards:
        return "paint_anchor"
    if stl is None or blk is None:
        return None
    if big and weight >= 115 and boards and (blk >= (4 if rates.get("blk_is_pct") else 2.2)) and stl < 1.5:
        return "paint_anchor"
    if big and 103 <= weight < 120 and (blk >= (2.3 if rates.get("blk_is_pct") else 1.2) or ((reb36 or 0) >= 9 and stl >= 1)):
        return "mobile_big"
    if height >= 190 and weight < 112 and stl >= 2 and blk >= (0.9 if rates.get("blk_is_pct") else .48):
        return "switchable_wing"
    return None


def defense_similarity(a, b):
    """Podobnost společně dostupných metrik; vrací i pokrytí obrany."""
    scores = []
    for k, weight, scale in (("stl", .43, 2.0), ("blk", .37, 2.0),
                             ("dbpm", .14, 5.0), ("def_rating", .06, 12.0)):
        x, y = a.get(k), b.get(k)
        if k in ("stl", "blk") and a.get(k + "_is_pct") != b.get(k + "_is_pct"):
            x, y = a.get(k + "100"), b.get(k + "100")
        if x is not None and y is not None:
            scores.append((weight, max(0., 100. * (1 - abs(x - y) / scale))))
    coverage = sum(w for w, _ in scores)
    return (sum(w * s for w, s in scores) / coverage if coverage else None), coverage


def empty_awards() -> Dict[str, int]:
    return {"mvp": 0, "dpoy": 0, "all_nba": 0, "all_def": 0}


def _store():
    from services import nba_external

    return nba_external


def award_profile(nba_id: int) -> Dict[str, int]:
    """
    MVP / DPOY / All-NBA / All-Defensive hráče. Poprvé se stáhne z ESPN,
    pak je v dočasné paměti. Když ESPN neodpoví, vrací nuly (a nezapamatuje).
    """
    try:
        hit = _store()._cache_get(f"awards:{int(nba_id)}", TTL_AWARDS)
    except Exception:
        hit = None
    if hit is not None:
        return hit

    result = empty_awards()
    try:
        from services import espn_seasons

        espn_id = espn_seasons.resolve_id(int(nba_id))
        base = (
            "https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba/"
            f"athletes/{espn_id}/awards"
        )
        page, pages, ok = 1, 1, False
        while page <= pages and page <= 4:
            data = espn_seasons._get_json(f"{base}?page={page}")
            if not data:
                break
            ok = True
            pages = int(data.get("pageCount") or 1)
            for item in data.get("items") or []:
                m = re.search(r"/awards/(\d+)", str(item.get("$ref") or ""))
                kind = _AWARD_KIND.get(m.group(1)) if m else None
                if kind:
                    result[kind] += 1
            page += 1
        if ok:
            _store()._cache_set(f"awards:{int(nba_id)}", result)
    except Exception as exc:  # pragma: no cover
        logger.warning("Ocenění hráče %s se nenačetla: %s", nba_id, exc)
    return result


def _num(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if number != number else number


# --------------------------------------------------------------------------- #
# Obrana
# --------------------------------------------------------------------------- #

def defense_tier(
    stl: Optional[float],
    blk: Optional[float],
    role_group: str,
    awards: Optional[Dict[str, int]],
    minutes: Optional[float] = None,
    season: Optional[str] = None,
) -> str:
    """
    Elitní / průměrný / slabý obránce. Ocenění mají přednost před čísly.

    `stl` a `blk` jsou na zápas; když je zadané `minutes`, přepočítají se
    na 100 držení podle tempa éry.
    """
    aw = awards or {}
    # Ocenění se počítají, jen když nějaké opravdu jsou. Když se seznam
    # ocenění nepodařilo načíst (nebo hráč žádné nemá), rozhodují čísla –
    # jinak by každý vyšel jako „průměrný obránce".
    has_awards = any(aw.values())
    if has_awards and (aw.get("dpoy", 0) >= 1 or aw.get("all_def", 0) >= 3):
        return "elite"
    has_def_award = has_awards and aw.get("all_def", 0) >= 1

    stl100 = per100(stl, minutes, season) if minutes else _num(stl)
    blk100 = per100(blk, minutes, season) if minutes else _num(blk)
    if stl is None and blk is None:
        # starší éra bez STL/BLK – rozhodují jen ocenění
        if has_awards and aw.get("all_def", 0) >= 2:
            return "elite"
        return "average"

    stocks = (stl or 0.0) + (blk or 0.0)
    big = role_group == "big"
    elite_cut = 6.4 if big else 4.6
    weak_cut = 3.6 if big else 2.7

    if stocks >= elite_cut or (has_def_award and stocks >= elite_cut - 1.2):
        return "elite"
    if stocks < weak_cut and not has_def_award:
        return "weak"
    return "average"


DEFENSE_LABEL = {
    "elite": "elitní obránce",
    "average": "průměrný obránce",
    "weak": "slabší obránce",
}


def defense_penalty(a_tier: str, b_tier: str) -> float:
    """Srážka ze stylu podle rozdílu v obraně (body procent)."""
    pair = {a_tier, b_tier}
    if pair == {"elite", "weak"}:
        return 45.0  # tvrdá hranice: elitní obránce nikdy nedostane slabého
    if pair == {"elite", "average"}:
        return 10.0
    if pair == {"average", "weak"}:
        return 4.0
    return 0.0


# --------------------------------------------------------------------------- #
# Postava a atletičnost
# --------------------------------------------------------------------------- #

BUILD_LABEL = {
    "explosive": "explozivní atlet",
    "long_lean": "dlouhý hubený střelec",
    "technical": "technický neexplozivní hráč",
    "powerful": "silový hráč",
}


def build_type(
    height_cm: float,
    weight_kg: float,
    ft_rate: float,
    two_rate: float,
    stocks100: Optional[float],
    role_group: str,
    three_rate: float,
) -> str:
    """
    Typ postavy a atletičnosti z reálných údajů: poměr váhy a výšky,
    kolik hráč dojíždí na čáru, jak moc žije pod košem a kolik má
    zisků + bloků. Je to odhad ze statistik, ne měření.
    """
    bmi = weight_kg / max(height_cm, 1.0)          # kg na cm výšky
    athletic = (
        0.45 * min(ft_rate / 0.45, 1.0)
        + 0.30 * min(two_rate / 0.80, 1.0)
        + 0.25 * (min((stocks100 or 2.5) / 5.0, 1.0))
    )
    if bmi >= 0.585 and role_group == "big":
        return "powerful"
    if athletic >= 0.66:
        return "explosive"
    if bmi <= 0.545 and height_cm >= 201 and three_rate >= 0.22:
        return "long_lean"
    if athletic <= 0.52:
        return "technical"
    return "explosive" if athletic >= 0.60 else "technical"


def athleticism_score(
    ft_rate: float, two_rate: float, stocks100: Optional[float]
) -> float:
    return round(
        0.45 * min(ft_rate / 0.45, 1.0)
        + 0.30 * min(two_rate / 0.80, 1.0)
        + 0.25 * min((stocks100 or 2.5) / 5.0, 1.0),
        3,
    )


# --------------------------------------------------------------------------- #
# Střelecký profil (gravity)
# --------------------------------------------------------------------------- #

GRAVITY_LABEL = {
    3: "elitní trojkař",
    2: "spolehlivý střelec zdálky",
    1: "střední střelba",
    0: "bez spolehlivé trojky",
}


def shooting_gravity(fg3m: float, fg3a: float, fg3_pct: float) -> int:
    """
    3 = elitní, 2 = spolehlivý, 1 = střední, 0 = bez spolehlivé trojky.

    Rozhoduje objem střelby, ne procento: 0,9 trojky na zápas znamená, že
    trojka není hráčova zbraň (Jordan, DeRozan), i když ji občas trefí.
    """
    # Jordan v roce 1987 házel 0,8 trojky na zápas – trojka není jeho
    # zbraň. Hráč, který hází aspoň jednu a půl trojky na zápas, ale
    # nějakou má (Kobe 1996-97: 1,9 pokusu) – ten se nesmí počítat jako
    # hráč bez trojky.
    if fg3a < 0.8 or fg3_pct < 0.27:
        return 0
    if fg3m >= 2.3 and fg3_pct >= 0.375:
        return 3
    if fg3m >= 1.3 and fg3_pct >= 0.34:
        return 2
    return 1

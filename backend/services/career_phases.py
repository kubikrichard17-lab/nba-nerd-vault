"""
Prime / fáze kariéry – srovnání podle vrcholné verze hráče.

Proč to je:

Průměr celé kariéry zkresluje. Michael Jordan byl v roce 1988 atlet,
který žil z nájezdů, a v roce 1996 technický střelec ze střední vzdálenosti.
Brook Lopez střílel v New Jersey z postu a v Milwaukee stojí za trojkou.
Kariérní průměr z toho udělá hráče, který neexistoval.

Tenhle modul z reálných sezón spočítá:

1. **Prime** – jedna až tři souvislé sezóny s nejvyšším výkonem (body, objem,
   minuty). Z nich se udělá průměr – to je „verze hráče na vrcholu".
2. **Fáze kariéry** – kariéra se rozdělí na první a druhou polovinu podle
   odehraných zápasů. U každé se zjistí, jestli se změnil způsob hraní
   (odkud skóruje, kolik tvoří hry, kde brání).
3. **Proměna** – `has_major_evolution` je true, jen když je rozdíl opravdu
   velký a obě fáze mají dost zápasů. Malé výkyvy se ignorují.

Všechno se počítá z dat, která aplikace už má (NBA API / Basketball-Reference),
nic se nestahuje navíc.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

# Minimální počet zápasů ve fázi, aby se o ní dalo mluvit
MIN_PHASE_GP = 60
# Od kolika zápasů má smysl kariéru dělit na fáze
MIN_CAREER_GP = 300
# Jak velký rozdíl ve stylu už je „proměna hráče"
EVOLUTION_THRESHOLD = 0.30

STAT_KEYS = (
    "pts",
    "reb",
    "ast",
    "stl",
    "blk",
    "tov",
    "fgm",
    "fga",
    "fg3m",
    "fg3a",
    "ftm",
    "fta",
    "min_per_game", "oreb", "orb_pct", "stl_pct", "blk_pct", "dbpm", "def_rating",
    "ast_pct", "usg_pct", "trb_pct", "drb_pct", "dws",
    "obpm", "bpm", "ows", "ws", "per", "ts_pct", "off_rating",
    "pct_fga_0_3", "pct_fga_mid", "pct_fga_3p", "pct_astd_fg",
)


def _num(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number:  # NaN
        return default
    return number


def _season(row: Dict[str, Any]) -> str:
    return str(row.get("season_id") or row.get("SEASON_ID") or "")


def _games(row: Dict[str, Any]) -> int:
    return int(_num(row.get("gp", row.get("GP")), 0))


def _weighted(rows: Sequence[Dict[str, Any]], key: str) -> Optional[float]:
    """Vážený průměr podle odehraných zápasů. Chybějící hodnota = přeskočeno."""
    total_gp = 0
    total = 0.0
    for row in rows:
        gp = _games(row)
        if gp <= 0:
            continue
        value = row.get(key)
        if value is None:
            continue
        number = _num(value, float("nan"))
        if number != number:
            continue
        total += number * gp
        total_gp += gp
    if total_gp == 0:
        return None
    return total / total_gp


def _row_style(row: Dict[str, Any]) -> Dict[str, float]:
    """Z jedné sezóny vytáhne míry, podle kterých se pozná styl."""
    fga = max(_num(row.get("fga", row.get("FGA")), 0.0), 1.0)
    fg3a = _num(row.get("fg3a", row.get("FG3A")), 0.0)
    fg3m = _num(row.get("fg3m", row.get("FG3M")), 0.0)
    fgm = _num(row.get("fgm", row.get("FGM")), 0.0)
    ftm = _num(row.get("ftm", row.get("FTM")), 0.0)
    pts = max(_num(row.get("pts", row.get("PTS")), 0.0), 1.0)
    ast = _num(row.get("ast", row.get("AST")), 0.0)
    reb = _num(row.get("reb", row.get("REB")), 0.0)
    return {
        "three_rate": fg3a / fga,
        "three_pts_share": min((3.0 * fg3m) / pts, 0.8),
        "ft_pts_share": min(ftm / pts, 0.5),
        "two_rate": max(fga - fg3a, 0.0) / fga,
        "paint_share": max(fgm - fg3m, 0.0) / fga,
        "ast": ast,
        "reb": reb,
        "pts": _num(row.get("pts", row.get("PTS")), 0.0),
    }


def _phase_style(rows: Sequence[Dict[str, Any]]) -> Dict[str, float]:
    """Styl fáze jako vážený průměr jejích sezón."""
    total_gp = sum(_games(r) for r in rows) or 1
    acc: Dict[str, float] = {}
    for row in rows:
        gp = _games(row)
        for key, value in _row_style(row).items():
            acc[key] = acc.get(key, 0.0) + value * gp
    return {key: value / total_gp for key, value in acc.items()}


def _style_gap(a: Dict[str, float], b: Dict[str, float]) -> float:
    """
    Jak moc se změnil styl mezi dvěma fázemi (0 = stejný, 1 = jiný hráč).
    Nejdůležitější je, odkud hráč skóruje – to se mění nejvíc a je to
    vidět na první pohled (Lopez z postu za trojku).
    """
    gap = 0.0
    gap += abs(a.get("three_pts_share", 0) - b.get("three_pts_share", 0)) * 1.6
    gap += abs(a.get("ft_pts_share", 0) - b.get("ft_pts_share", 0)) * 1.2
    gap += abs(a.get("two_rate", 0) - b.get("two_rate", 0)) * 0.8
    gap += abs(a.get("paint_share", 0) - b.get("paint_share", 0)) * 1.0
    gap += min(abs(a.get("ast", 0) - b.get("ast", 0)) / 4.0, 1.0) * 0.5
    gap += min(abs(a.get("reb", 0) - b.get("reb", 0)) / 6.0, 1.0) * 0.4
    gap += min(abs(a.get("pts", 0) - b.get("pts", 0)) / 12.0, 1.0) * 0.5
    return round(min(gap, 1.0), 3)


def _blend(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Průměrná sezóna z několika sezón – vstup pro build_profile().

    Průměr se počítá ze zápasů, ve kterých se statistika opravdu měřila.
    Kdyby se chybějící hodnota brala jako nula, hráč z éry bez trojek by
    měl „0 % bodů z trojek" a model by ho zařadil mezi podkošové hráče –
    Jordan by skončil jako big_creator. Proto se každá statistika váží
    jen svými vlastními zápasy.
    """
    result: Dict[str, Any] = {}
    for key in STAT_KEYS:
        result[key] = _weighted(rows, key)
    from services.shot_context import era_3par

    league = [(era_3par(_season(r)), _games(r) * _num(r.get("fga"))) for r in rows
              if r.get("fg3a") is not None]
    league = [(x, w) for x, w in league if x is not None and w > 0]
    result["era_avg_3par"] = sum(x * w for x, w in league) / sum(w for _, w in league) if league else None
    result["gp"] = sum(_games(r) for r in rows)
    result["seasons"] = [_season(r) for r in rows if _season(r)]
    from services.advanced_cache import derive_boxscore
    return derive_boxscore(result, include_rates=False)


def _score(row: Dict[str, Any]) -> float:
    """Jak moc je sezóna „vrcholná" – body, objem střelby a minuty."""
    pts = _num(row.get("pts", row.get("PTS")))
    fga = _num(row.get("fga", row.get("FGA")))
    minutes = _num(row.get("min_per_game", row.get("MIN")))
    gp = _games(row)
    # Krátká sezóna (zranění) nesmí vyhrát jen proto, že měla vysoký průměr
    availability = min(gp / 70.0, 1.0)
    return (pts * 0.6 + fga * 0.25 + minutes * 0.15) * availability


def prime_window(seasons: Sequence[Dict[str, Any]], window: int = 3) -> List[Dict[str, Any]]:
    """Preferuj stabilní vrchol; kratší okno musí vyhrát přesvědčivě."""
    from services.shot_context import season_year

    rows = sorted((r for r in seasons if _games(r) > 0), key=_season)
    qualified = [r for r in rows if _games(r) >= 45 and season_year(_season(r)) is not None]
    if not qualified:
        return [max(rows, key=_score)] if rows else []
    windows = []
    for length in range(1, min(3, window, len(qualified)) + 1):
        for i in range(len(qualified) - length + 1):
            chunk = qualified[i:i + length]
            years = [season_year(_season(r)) for r in chunk]
            if years[-1] - years[0] != length - 1 or len(set(years)) != length:
                continue
            raw = sum(_score(r) for r in chunk) / length
            # Delší kariéra dává větší jistotu, že krátké okno je výkyv.
            reliability = {1: .81, 2: .88, 3: 1.} if len(qualified) >= 9 else {1: .87, 2: .94, 3: 1.}
            adjusted = raw * reliability[length]
            windows.append((adjusted, length, -years[0], chunk))
    return list(max(windows, key=lambda item: item[:3])[3])


def _split_phases(seasons: Sequence[Dict[str, Any]]) -> Optional[List[Dict[str, Any]]]:
    """
    Rozdělí kariéru na dvě poloviny podle odehraných zápasů (ne podle
    počtu sezón – hráč mohl půl kariéry prosedět na marodce).
    """
    rows = [r for r in seasons if _games(r) > 0]
    total = sum(_games(r) for r in rows)
    if total < MIN_CAREER_GP or len(rows) < 4:
        return None

    half = total / 2.0
    running = 0
    split_at = 1
    for index, row in enumerate(rows):
        running += _games(row)
        if running >= half:
            split_at = index + 1
            break
    split_at = max(1, min(split_at, len(rows) - 1))

    early = rows[:split_at]
    late = rows[split_at:]
    if sum(_games(r) for r in early) < MIN_PHASE_GP:
        return None
    if sum(_games(r) for r in late) < MIN_PHASE_GP:
        return None
    return [early, late]


def _label(rows: Sequence[Dict[str, Any]]) -> str:
    seasons = [_season(r) for r in rows if _season(r)]
    if not seasons:
        return ""
    first = seasons[0][:4]
    last = seasons[-1][:4]
    return f"{first}–{last}"


def career_phases(
    seasons: Sequence[Dict[str, Any]],
    base_profile: Dict[str, Any],
    profile_builder,
) -> Dict[str, Any]:
    """
    Vrátí vše, co UI potřebuje:

        prime:   {season, seasons, stat, profile}      – vrcholná verze
        phases:  [{key, label, season, stat, profile, style_gap}]  – raná/pozdní
        has_major_evolution: bool
        evolution_note: české vysvětlení, co se změnilo

    `profile_builder` je funkce closest_player.build_profile – profil se
    staví stejnou cestou jako jinde v aplikaci, aby čísla seděla.
    """
    rows = [r for r in seasons if _games(r) > 0]
    result: Dict[str, Any] = {
        "has_major_evolution": False,
        "evolution_note": "",
        "prime": None,
        "phases": [],
    }
    if not rows:
        return result

    # 1) Prime – vrcholná verze hráče
    prime_rows = prime_window(rows)
    prime_stat = _blend(prime_rows)
    prime_seasons = prime_stat.get("seasons") or []
    prime_profile = profile_builder(
        player_id=base_profile["id"],
        name=base_profile["name"],
        position=base_profile.get("position") or "",
        height_cm=base_profile.get("height_cm"),
        weight_kg=base_profile.get("weight_kg"),
        stat=prime_stat,
        awards_count=base_profile.get("awards", 0),
        award_detail=base_profile.get("award_detail"),
    )
    result["prime"] = {
        "season": prime_seasons[0] if prime_seasons else "",
        "seasons": prime_seasons,
        "label": "Vrchol kariéry",
        "stat": prime_stat,
        "profile": prime_profile,
    }

    # 2) Fáze kariéry – jen když je kariéra dost dlouhá
    split = _split_phases(rows)
    if not split:
        return result

    early, late = split
    early_style = _phase_style(early)
    late_style = _phase_style(late)
    gap = _style_gap(early_style, late_style)

    phases = []
    for key, label, phase_rows in (
        ("early", "Raná kariéra", early),
        ("late", "Pozdní kariéra", late),
    ):
        stat = _blend(phase_rows)
        profile = profile_builder(
            player_id=base_profile["id"],
            name=base_profile["name"],
            position=base_profile.get("position") or "",
            height_cm=base_profile.get("height_cm"),
            weight_kg=base_profile.get("weight_kg"),
            stat=stat,
            awards_count=base_profile.get("awards", 0),
            award_detail=base_profile.get("award_detail"),
        )
        phases.append(
            {
                "key": key,
                "label": label,
                "season": (stat.get("seasons") or [""])[0],
                "seasons": stat.get("seasons") or [],
                "label_range": _label(phase_rows),
                "gp": sum(_games(r) for r in phase_rows),
                "stat": stat,
                "profile": profile,
            }
        )

    result["phases"] = phases
    result["has_major_evolution"] = gap >= EVOLUTION_THRESHOLD
    result["style_gap"] = gap
    result["evolution_note"] = _evolution_note(phases, gap)
    return result


def _phase_style_rows(stat: Dict[str, Any]) -> Dict[str, float]:
    """Styl fáze z její průměrné sezóny (stejný přepočet jako u sezóny)."""
    return _row_style(stat)


def _evolution_note(phases: List[Dict[str, Any]], gap: float) -> str:
    """Jedna věta o tom, co se změnilo – čísly, ne dojmem."""
    if len(phases) < 2:
        return ""
    early = phases[0]["profile"]
    late = phases[1]["profile"]
    early_style = _phase_style_rows(phases[0].get("stat") or {})
    late_style = _phase_style_rows(phases[1].get("stat") or {})
    changes: List[str] = []

    three_diff = late_style["three_pts_share"] - early_style["three_pts_share"]
    if abs(three_diff) >= 0.05:
        smer = "stoupl" if three_diff > 0 else "klesl"
        changes.append(
            f"podíl bodů z trojek {smer} z "
            f"{round(early_style['three_pts_share'] * 100)} % na "
            f"{round(late_style['three_pts_share'] * 100)} %"
        )

    paint_diff = late_style["paint_share"] - early_style["paint_share"]
    if abs(paint_diff) >= 0.08:
        smer = "stoupl" if paint_diff > 0 else "klesl"
        changes.append(
            f"podíl střel z blízkosti koše {smer} z "
            f"{round(early_style['paint_share'] * 100)} % na "
            f"{round(late_style['paint_share'] * 100)} %"
        )

    ast_diff = late.get("ast", 0) - early.get("ast", 0)
    if abs(ast_diff) >= 1.0:
        smer = "stoupl" if ast_diff > 0 else "klesl"
        changes.append(
            f"počet asistencí {smer} z {round(early.get('ast', 0), 1)} "
            f"na {round(late.get('ast', 0), 1)}"
        )

    pts_diff = late.get("pts", 0) - early.get("pts", 0)
    if abs(pts_diff) >= 1.0:
        smer = "stoupl" if pts_diff > 0 else "klesl"
        changes.append(
            f"průměr bodů {smer} z {round(early.get('pts', 0), 1)} "
            f"na {round(late.get('pts', 0), 1)}"
        )

    reb_diff = late.get("reb", 0) - early.get("reb", 0)
    if abs(reb_diff) >= 1.0:
        # „doskoky" je množné číslo – „stouply / klesly", ne „stoupl / klesl"
        smer = "stouply" if reb_diff > 0 else "klesly"
        changes.append(
            f"doskoky {smer} z {round(early.get('reb', 0), 1)} "
            f"na {round(late.get('reb', 0), 1)}"
        )

    if not changes:
        return "Způsob hraní se mezi fázemi kariéry výrazně nezměnil."
    return "Během kariéry se změnilo: " + ", ".join(changes) + "."

import numpy as np
from typing import Dict, List, Any, Optional, Tuple
from sklearn.metrics.pairwise import cosine_similarity


def compute_physical_match(p1: Dict[str, Any], p2: Dict[str, Any]) -> float:
    """Calculate physical similarity (height & weight) 0-100%."""
    h1 = p1.get("height_cm") or 198.0
    h2 = p2.get("height_cm") or 198.0
    w1 = p1.get("weight_kg") or 98.0
    w2 = p2.get("weight_kg") or 98.0

    # Max difference thresholds: 25 cm, 30 kg
    h_diff = abs(h1 - h2)
    h_score = max(0.0, 100.0 - (h_diff / 25.0) * 100.0)

    w_diff = abs(w1 - w2)
    w_score = max(0.0, 100.0 - (w_diff / 30.0) * 100.0)

    return round(0.55 * h_score + 0.45 * w_score, 1)


def compute_position_score(pos1: str, pos2: str) -> float:
    """Calculate position similarity 0-100%."""
    p1 = (pos1 or "").upper().replace(" ", "")
    p2 = (pos2 or "").upper().replace(" ", "")

    if not p1 or not p2:
        return 70.0
    if p1 == p2:
        return 100.0

    # Common combinations
    guards = {"G", "PG", "SG"}
    forwards = {"F", "SF", "PF"}
    centers = {"C"}

    set1 = set(p1.split("-"))
    set2 = set(p2.split("-"))

    if set1.intersection(set2):
        return 85.0
    
    # Check category overlaps
    is_g1 = bool(set1.intersection(guards))
    is_g2 = bool(set2.intersection(guards))
    is_f1 = bool(set1.intersection(forwards))
    is_f2 = bool(set2.intersection(forwards))
    is_c1 = bool(set1.intersection(centers))
    is_c2 = bool(set2.intersection(centers))

    if (is_g1 and is_g2) or (is_f1 and is_f2) or (is_c1 and is_c2):
        return 90.0
    if (is_g1 and is_f2) or (is_f1 and is_g2) or (is_f1 and is_c2) or (is_c1 and is_f2):
        return 55.0
    return 25.0


def compute_tag_similarity(tags1: List[str], tags2: List[str]) -> float:
    """Calculate stylistic tag overlap (Jaccard similarity)."""
    if not tags1 or not tags2:
        return 60.0

    s1 = set(tags1)
    s2 = set(tags2)
    intersect = len(s1.intersection(s2))
    union = len(s1.union(s2))
    if union == 0:
        return 50.0

    jaccard = intersect / union
    # Base score of 40% + 60% based on matches
    return round(min(100.0, 40.0 + jaccard * 100.0), 1)


def extract_stat_vector(stat: Dict[str, Any]) -> np.ndarray:
    """
    Extract normalized statistical vector for scikit-learn cosine similarity.
    Normalized across NBA league historical ranges.
    """
    pts100 = float(stat.get("poss100_pts") or (float(stat.get("pts", 0)) * 2.5))
    reb100 = float(stat.get("poss100_reb") or (float(stat.get("reb", 0)) / pace * 100.0))
    ast100 = float(stat.get("poss100_ast") or (float(stat.get("ast", 0)) / pace * 100.0))
    stl100 = float(stat.get("poss100_stl") or (float(stat.get("stl", 0)) / pace * 100.0))
    blk100 = float(stat.get("poss100_blk") or (float(stat.get("blk", 0)) / pace * 100.0))
    tov100 = float(stat.get("poss100_tov") or (float(stat.get("tov", 0)) * 2.5))

    fg_pct = float(stat.get("fg_pct") or 0.45)
    fg3_pct = float(stat.get("fg3_pct") or 0.33)
    ft_pct = float(stat.get("ft_pct") or 0.75)

    fga = max(float(stat.get("fga") or 1.0), 1.0)
    fg3a = float(stat.get("fg3a") or 0.0)
    fta = float(stat.get("fta") or 0.0)

    three_point_rate = min(1.0, fg3a / fga)
    free_throw_rate = min(1.0, fta / fga)

    # Feature scaling into roughly ~[0, 1] domain
    v = np.array([
        pts100 / 45.0,
        reb100 / 22.0,
        ast100 / 18.0,
        stl100 / 3.5,
        blk100 / 4.5,
        tov100 / 5.5,
        fg_pct / 0.65,
        fg3_pct / 0.45,
        ft_pct / 0.95,
        three_point_rate * 1.5,
        free_throw_rate * 1.2
    ], dtype=np.float64)

    return v


def compute_statistical_match(s1: Dict[str, Any], s2: Dict[str, Any]) -> float:
    """Use scikit-learn cosine similarity and distance to calculate stats match %."""
    v1 = extract_stat_vector(s1)
    v2 = extract_stat_vector(s2)

    # Scikit-learn Cosine Similarity
    cos_sim = float(cosine_similarity(v1.reshape(1, -1), v2.reshape(1, -1))[0][0])
    # Bound between 0 and 1
    cos_sim = max(0.0, min(1.0, cos_sim))

    # Normalized Euclidean distance penalty
    dist = float(np.linalg.norm(v1 - v2))
    norm_dist = max(0.0, min(1.0, dist / 2.5))

    # Combine cosine orientation (70%) with magnitude proximity (30%)
    score = (0.75 * cos_sim + 0.25 * (1.0 - norm_dist)) * 100.0
    return round(max(10.0, min(99.5, score)), 1)


def calculate_radar_dimensions(stat: Dict[str, Any], height_cm: float, weight_kg: float) -> Dict[str, Optional[float]]:
    """Calculate 7 standardized dimensions (0-100) for CompareRadar overlay chart."""
    # Odhad držení míče na zápas, když zdroj neposílá metriky na 100 držení
    minutes = float(stat.get("min_per_game") or 32.0) or 32.0
    pace = (minutes / 48.0) * 100.0
    pace = max(pace, 30.0)

    from services.defense import optional_number

    def rate(key):
        measured = optional_number(stat.get("poss100_" + key))
        raw = optional_number(stat.get(key))
        return measured if measured is not None else raw / pace * 100 if raw is not None else None

    pts100, reb100, ast100 = (rate(key) or 0. for key in ("pts", "reb", "ast"))
    stl100, blk100 = rate("stl"), rate("blk")

    fg_pct = float(stat.get("fg_pct") or 0.45)
    fg3_pct = float(stat.get("fg3_pct") or 0.0)
    ft_pct = float(stat.get("ft_pct") or 0.75)
    fg3a = float(stat.get("fg3a") or 0.0)

    # 1. Skórování (0-100) - based on 40 pts/100 as elite 95+
    scoring = min(100.0, (pts100 / 42.0) * 100.0)

    # 2. 3B Střelba (0-100) - volume & %
    three_volume = min(1.0, fg3a / 8.0)
    three_acc = min(1.0, fg3_pct / 0.42)
    shooting_3p = min(100.0, (0.6 * three_acc + 0.4 * three_volume) * 100.0)

    # 3. Tvorba hry (0-100) - based on 15 ast/100
    playmaking = min(100.0, (ast100 / 14.0) * 100.0)

    # 4. Doskakování (0-100) - based on 20 reb/100
    rebounding = min(100.0, (reb100 / 18.0) * 100.0)

    # 5. Obrana (0-100) - stocks (steals + blocks per 100)
    stocks = sum(v * w for v, w in ((stl100, 1.2), (blk100, 1.3)) if v is not None)
    defense = min(100., stocks / 6. * 100) if stl100 is not None or blk100 is not None else None

    # 6. Efektivita střelby (0-100) - True shooting estimate
    ts_est = fg_pct * 0.5 + ft_pct * 0.3 + fg3_pct * 0.2
    efficiency = min(100.0, (ts_est / 0.62) * 100.0)

    # 7. Fyzická dominance (0-100) - based on height & weight
    bmi_score = min(100.0, (height_cm / 215.0) * 55.0 + (weight_kg / 125.0) * 45.0)

    return {
        "Skórování": round(scoring, 1),
        "3B Střelba": round(shooting_3p, 1),
        "Tvorba hry": round(playmaking, 1),
        "Doskakování": round(rebounding, 1),
        "Obrana": round(defense, 1) if defense is not None else None,
        "Efektivita": round(efficiency, 1),
        "Fyzická dominance": round(bmi_score, 1),
    }


def shot_and_creation_features(stat, season, usage, three_efficiency=None):
    from services import defense
    from services.shot_context import era_3par, season_year

    def unit(value):
        return max(0., min(1., value))

    num = defense.optional_number
    fga, ast, ast_pct, usg_pct, fta, fg3a = (num(stat.get(k)) for k in
        ("fga", "ast", "ast_pct", "usg_pct", "fta", "fg3a"))
    ast100 = defense.per100(ast, stat.get("min_per_game"), season)
    creation = unit(ast_pct / 50) if ast_pct is not None else unit(ast100 / 15) if ast100 is not None else None
    usage_source = usg_pct / 100 if usg_pct is not None else usage if fga is not None and num(stat.get("min_per_game")) else None
    load = None if creation is None or usage_source is None else .65 * creation + .35 * unit((usage_source - .10) / .30)
    ftr = fta / fga if fga and fta is not None else None
    year = season_year(season)
    three = fg3a / fga if fga and fg3a is not None else 0. if year is not None and year < 1979 else None
    baseline = num(stat.get("era_avg_3par"))
    if baseline is None:
        baseline = era_3par(season)
    orb = num(stat.get("orb_pct"))
    orb100 = defense.per100(stat.get("oreb"), stat.get("min_per_game"), season)
    board = unit(orb / 14) if orb is not None else unit(orb100 / 6.4) if orb100 is not None else None
    rates = defense.defensive_rates(stat, season)
    relative_three = three - baseline if three is not None and baseline is not None else None
    ft_weight = .72 * (1 - min(.32, max(relative_three or 0., 0.) * 1.6))
    signals = [(unit(ftr / .55), ft_weight)] if ftr is not None else []
    if board is not None:
        signals.append((board, .20))
    if rates["blk"] is not None:
        signals.append((unit(rates["blk"] / (5 if rates["blk_is_pct"] else 3)), .08))
    rim = sum(v * w for v, w in signals) / sum(w for _, w in signals) if signals else None
    # Dvoubodový profil, ne měřená vzdálenost střely.
    mid = None if three is None or ftr is None else (1 - unit(three)) * (
        .80 * (1 - unit(ftr / .60)) + .20 * (1 - board) if board is not None else 1 - unit(ftr / .60))
    # Boxscore proxy, nikoli měření výskoku. Použij pouze společně dostupné signály.
    vertical = {"orb": board, "blk": unit(rates["blk"] / (5 if rates["blk_is_pct"] else 3)) if rates["blk"] is not None else None,
                "stl": unit(rates["stl"] / 4) if rates["stl"] is not None else None}
    weights = {"orb": .40, "blk": .45, "stl": .15}
    observed = [(v, weights[k]) for k, v in vertical.items() if v is not None]
    vertical_index = sum(v * w for v, w in observed) / sum(w for _, w in observed) if len(observed) >= 2 else None
    primary = (ast_pct >= 35 and usg_pct >= 30) if ast_pct is not None and usg_pct is not None else (
        load is not None and load >= .76 and ast is not None and fga and ast/fga >= .35)
    pct_0_3 = num(stat.get("pct_fga_0_3"))
    pct_mid = num(stat.get("pct_fga_mid"))
    pct_3p = num(stat.get("pct_fga_3p"))
    if pct_0_3 is not None:
        rim = 0.65 * unit(pct_0_3 / 0.65) + 0.35 * rim if rim is not None else unit(pct_0_3 / 0.65)
    if pct_mid is not None:
        mid = 0.65 * unit(pct_mid / 0.55) + 0.35 * mid if mid is not None else unit(pct_mid / 0.55)
    return {"primary_playmaker": bool(primary), "vertical_athleticism": vertical_index,
            "orb_signal": board, "trb_pct": num(stat.get("trb_pct")), "ftr": ftr,
            "on_ball_load": load, "pass_to_score": ast / fga if ast is not None and fga else None,
            "rim_pressure_index": rim, "mid_range_index": mid,
            "pct_fga_0_3": pct_0_3, "pct_fga_mid": pct_mid, "pct_fga_3p": pct_3p,
            "rel_3par": relative_three,
            "three_efficiency": three_efficiency if fg3a and fg3a >= 1 and (stat.get("fg3m") is not None or stat.get("fg3_pct") is not None) else None,
            "defensive_rates": rates, "defense_missing": any(rates[k] is None for k in ("dbpm", "def_rating"))}


def compare_players(
    p1_info: Dict[str, Any],
    p1_stat: Dict[str, Any],
    p2_info: Dict[str, Any],
    p2_stat: Dict[str, Any],
    unified: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Main Comparison Engine:
    Computes total match % and sub-matches (physical, statistical, stylistic),
    generates radar chart dimensions and comparison table.
    """
    # Když je k dispozici sjednocený model (stejný jako „nejbližší hráč"
    # na hlavní stránce), berou se jeho čísla – jinak by stejná dvojice
    # ukazovala na dvou místech aplikace dvě různé shody.
    if unified:
        physical_pct = unified["physical_pct"]
        style_pct = unified["style_pct"]
        stat_pct = unified["stats_pct"]
        total_match_pct = unified["match_pct"]
    else:
        physical_pct = compute_physical_match(p1_info, p2_info)
        stat_pct = compute_statistical_match(p1_stat, p2_stat)

        pos_score = compute_position_score(p1_info.get("position", ""), p2_info.get("position", ""))
        tag_score = compute_tag_similarity(p1_info.get("tags", []), p2_info.get("tags", []))
        style_pct = round(0.5 * pos_score + 0.5 * tag_score, 1)

        total_match_pct = round(
            0.20 * physical_pct + 0.55 * stat_pct + 0.25 * style_pct, 1
        )

    # Radar dimensions – z kariérních dat, která jsou vždy k dispozici
    radar1 = calculate_radar_dimensions(
        p1_stat,
        p1_info.get("height_cm") or 198.0,
        p1_info.get("weight_kg") or 98.0
    )
    radar2 = calculate_radar_dimensions(
        p2_stat,
        p2_info.get("height_cm") or 198.0,
        p2_info.get("weight_kg") or 98.0
    )

    def stat_row(label, key, percent=False):
        x, y = (p.get(key) for p in (p1_stat, p2_stat))
        def display(value):
            if value is None:
                return "—"
            return f"{100 * value:.1f} %" if percent else round(value, 1)
        delta = x - y if x is not None and y is not None else None
        diff = f"{100 * delta:+.1f} p. b." if percent and delta is not None else display(delta)
        return {"metric": label, "p1": display(x), "p2": display(y), "diff": diff}

    comp_table = [
        {"metric": label, "p1": p1_info.get(key), "p2": p2_info.get(key),
         "diff": round(p1_info[key] - p2_info[key], 1) if all(p.get(key) is not None for p in (p1_info, p2_info)) else "—"}
        for label, key in (("Výška (cm)", "height_cm"), ("Váha (kg)", "weight_kg"))
    ] + [stat_row(label, key, percent) for label, key, percent in (
        ("Body / zápas (PPG)", "pts", False), ("Doskoky / zápas (RPG)", "reb", False),
        ("Asistence / zápas (APG)", "ast", False), ("Zisky / zápas (SPG)", "stl", False),
        ("Bloky / zápas (BPG)", "blk", False), ("Úspěšnost střelby z pole (FG %)", "fg_pct", True),
        ("Úspěšnost trojek (3P %)", "fg3_pct", True), ("Trestné hody (FT %)", "ft_pct", True),
        ("Podíl bodů z trojek", "three_pts_share", True), ("Podíl bodů ze šestek", "ft_pts_share", True),
        ("Body na 100 držení míče", "poss100_pts", False), ("Doskoky na 100 držení míče", "poss100_reb", False),
        ("Asistence na 100 držení míče", "poss100_ast", False),
    )]

    return {
        "match_pct": total_match_pct,
        "physical_pct": physical_pct,
        "statistical_pct": stat_pct,
        "stylistic_pct": style_pct,
        "radar": {
            "p1": radar1,
            "p2": radar2,
            "labels": list(radar1.keys())
        },
        "table": comp_table
    }

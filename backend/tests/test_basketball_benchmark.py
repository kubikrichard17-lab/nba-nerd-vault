"""
Benchmark kalibrační test pro NBA Nerd Vault Similarity Engine (režim Prime + Early pro LeBrona).
Ověřuje 20 pozitivních kotev (Top 3), 10 negativních kotev (NESMÍ být v Top 5),
a 100% shodu procent na desetinu mezi closest a compare_pair.

Spuštění:
    python backend/tests/test_basketball_benchmark.py
"""

from __future__ import annotations

import os
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("NBA_DATA_SOURCE", "espn")

from database import SessionLocal
from models import Player
from services import advanced_cache, closest_player, closest_service, nba_external
from sqlalchemy.orm import selectinload


def norm(name: str) -> str:
    s = unicodedata.normalize("NFKD", name or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.lower().replace(".", "").split())


# 20 pozitivních kotev: (target, phase, allowed_any_in_top3, extra_checks)
POSITIVE_ANCHORS = [
    ("Shaquille O'Neal", "prime", ["Dwight Howard", "Wilt Chamberlain", "Moses Malone"], {}),
    ("Chet Holmgren", "prime", ["Kristaps Porzingis", "Myles Turner", "Jaren Jackson Jr"], {"before": ("Karl-Anthony Towns",)}),
    ("Dennis Rodman", "prime", ["Ben Wallace", "Charles Oakley", "Reggie Evans"], {}),
    ("Ben Wallace", "prime", ["Dikembe Mutombo", "Rudy Gobert", "Dwight Howard"], {}),
    ("Scottie Pippen", "prime", ["Scottie Barnes", "Kawhi Leonard", "Grant Hill"], {}),
    ("Dwyane Wade", "prime", ["Michael Jordan", "Kobe Bryant", "Donovan Mitchell"], {"before": ("Shai Gilgeous-Alexander",)}),
    ("Luka Doncic", "prime", ["James Harden"], {}),
    ("James Harden", "prime", ["Luka Doncic"], {}),
    ("Nikola Jokic", "prime", ["Domantas Sabonis", "Alperen Sengun", "Arvydas Sabonis"], {}),
    ("Jayson Tatum", "prime", ["Paul George"], {}),
    ("Kevin Garnett", "prime", ["Anthony Davis", "Chris Bosh", "Tim Duncan"], {}),
    ("Giannis Antetokounmpo", "prime", ["Anthony Davis", "Kevin Garnett", "Blake Griffin"], {}),
    ("Michael Jordan", "prime", ["Kobe Bryant", "Dwyane Wade", "Kawhi Leonard"], {}),
    ("Stephen Curry", "prime", ["Damian Lillard"], {}),
    ("Kawhi Leonard", "prime", ["Paul George", "Jimmy Butler", "Jimmy Butler III", "Scottie Pippen"], {}),
    ("Kevin Durant", "prime", ["Dirk Nowitzki"], {}),
    ("Dirk Nowitzki", "prime", ["Kevin Durant"], {}),
    ("Allen Iverson", "prime", ["Ja Morant", "Derrick Rose", "Russell Westbrook"], {}),
    ("Klay Thompson", "prime", ["Reggie Miller", "Ray Allen", "Dale Ellis"], {}),
    ("LeBron James", "early", ["Grant Hill", "Blake Griffin", "Giannis Antetokounmpo", "Tracy McGrady"], {}),
    ("Bill Russell", "prime", ["Wilt Chamberlain", "Ben Wallace", "Rudy Gobert"], {}),
    ("Bob McAdoo", "prime", None, {}),  # speciální kontrola načtení + podkošoví střelci
]

# 10 negativních kotev: (target, phase, forbidden_in_top5)
NEGATIVE_ANCHORS = [
    ("Shaquille O'Neal", "prime", ["Nikola Jokic"]),
    ("Draymond Green", "prime", ["Muggsy Bogues", "Lonzo Ball"]),
    ("Dennis Rodman", "prime", ["David Wood"]),
    ("Ben Wallace", "prime", ["Anthony Bonner"]),
    ("Jayson Tatum", "prime", ["Anthony Edwards"]),
    ("Giannis Antetokounmpo", "prime", ["Joel Embiid"]),
    ("Kevin Garnett", "prime", ["Nikola Jokic", "Alperen Sengun"]),
    ("Bill Russell", "prime", ["Ken Norman"]),
    ("LeBron James", "early", ["Luka Doncic"]),
    ("Kawhi Leonard", "prime", ["Manu Ginobili"]),
]


def load_roster(db):
    raw_pool = nba_external.cached_comparison_rows()
    players = db.query(Player).options(selectinload(Player.stats)).filter(Player.stats.any()).all()
    by_id = {int(row["id"]): row for row in raw_pool if row.get("id")}
    by_name = {nba_external.normalize_name(row.get("name")): row for row in raw_pool if row.get("name")}
    all_ids = {p.id for p in players}

    roster = []
    by_player_name = {}
    for p in players:
        canonical = closest_service._nba_ids().get(nba_external.normalize_name(p.full_name), ())
        if len(canonical) == 1 and canonical[0] != p.id and canonical[0] in all_ids:
            if closest_service.canonical_player(p, db).id != p.id:
                continue
        if not advanced_cache.consistent_career(p):
            continue
        meta = closest_service.phase_metadata(p)
        credible = [r for r in meta[0] if r.get("gp", 0) >= 45] or meta[0]
        peak = max((r.get("pts") or 0 for r in credible), default=0.0)
        roster.append((p, meta, peak))
        by_player_name[norm(p.full_name)] = (p, meta, peak)
    return roster, by_player_name


def rank_candidates(target_profile, roster, phase_key):
    profiles = []
    for other, metadata, peak in roster:
        career = metadata[1]
        if closest_player.same_player(career, target_profile):
            continue
        if not closest_player.compatible_dimensions(career, target_profile):
            continue
        if peak < target_profile["pts"] * 0.40:
            continue
        prof = closest_service.phase_for_player(other, phase_key, prepared=metadata)
        if prof:
            profiles.append(prof)

    cands = [c for c in profiles if closest_player.is_eligible_candidate(target_profile, c)]
    ranked = sorted(cands, key=lambda c: (-closest_player._similarity(target_profile, c)["match_pct"], c["id"]))
    unique = []
    for c in ranked:
        if not any(closest_player.same_player(c, u) for u in unique):
            unique.append(c)
    return unique


def find_player_entry(by_player_name, name):
    key = norm(name)
    if key in by_player_name:
        return by_player_name[key]
    for k, v in by_player_name.items():
        if key in k or k in key:
            return v
    return None


def main():
    db = SessionLocal()
    try:
        roster, by_player_name = load_roster(db)
        print(f"Načteno {len(roster)} hráčů do benchmark poolu (ENGINE_VERSION={closest_player.ENGINE_VERSION}).\n")

        pos_pass = 0
        pos_total = len(POSITIVE_ANCHORS)
        neg_pass = 0
        neg_total = len(NEGATIVE_ANCHORS)

        print("=== POZITIVNÍ KOTVY (Top 3) ===")
        for target_name, phase, expected, extra in POSITIVE_ANCHORS:
            entry = find_player_entry(by_player_name, target_name)
            if not entry:
                print(f"[FAIL] {target_name} ({phase}): Hráč nenalezen v DB!")
                continue
            p, meta, _ = entry
            target_prof = closest_service.phase_for_player(p, phase, prepared=meta)
            if not target_prof:
                print(f"[FAIL] {target_name} ({phase}): Profil fáze {phase} nenalezen!")
                continue
            ranked = rank_candidates(target_prof, roster, phase)
            top5_names = [c["name"] for c in ranked[:5]]
            top3_names = top5_names[:3]
            top3_norm = [norm(x) for x in top3_names]

            # Ověření 100% shody procent na desetinu mezi closest a compare_pair
            pct_ok = True
            if ranked:
                sim_direct = closest_player._similarity(target_prof, ranked[0])["match_pct"]
                sim_compare = closest_player.compare_pair(target_prof, ranked[0])["match_pct"]
                if sim_direct != sim_compare:
                    pct_ok = False

            if expected is None:
                # Bob McAdoo: bezchybné načtení profilu + smysluplní podkošoví střelci v Top 3
                big_count = sum(1 for c in ranked[:3] if c.get("role_group") == "big" or c.get("position_type") in ("PF", "C"))
                ok = len(ranked) >= 3 and big_count >= 2 and pct_ok
            else:
                exp_norm = [norm(x) for x in expected]
                ok = any(any(e in t or t in e for e in exp_norm) for t in top3_norm) and pct_ok

            if ok and "before" in extra:
                all_norms = [norm(c["name"]) for c in ranked]
                exp_norm = [norm(x) for x in expected]
                best_exp_idx = min((i for i, n in enumerate(all_norms) if any(e in n or n in e for e in exp_norm)), default=999)
                for forbidden_ahead in extra["before"]:
                    fn = norm(forbidden_ahead)
                    for_idx = next((i for i, n in enumerate(all_norms) if fn in n or n in fn), 999)
                    if for_idx <= best_exp_idx:
                        ok = False

            if ok:
                pos_pass += 1
            status = "PASS" if ok else "FAIL"
            top3_str = ", ".join(f"{c['name']} ({closest_player._similarity(target_prof, c)['match_pct']}%)" for c in ranked[:3])
            print(f"[{status}] {target_name} ({phase}) -> {top3_str}")
            if not ok and expected:
                # Ukaž pozice očekávaných hráčů
                all_norms = [norm(c["name"]) for c in ranked]
                pos_info = []
                for e in expected:
                    en = norm(e)
                    idx = next((i + 1 for i, n in enumerate(all_norms) if en in n or n in en), None)
                    pos_info.append(f"{e}: #{idx}" if idx else f"{e}: N/A")
                print(f"       Očekáváno v Top 3: {', '.join(pos_info)}")

        print(f"\n=== NEGATIVNÍ KOTVY (NESMÍ být v Top 5) ===")
        for target_name, phase, forbidden in NEGATIVE_ANCHORS:
            entry = find_player_entry(by_player_name, target_name)
            if not entry:
                print(f"[FAIL] {target_name} ({phase}): Hráč nenalezen v DB!")
                continue
            p, meta, _ = entry
            target_prof = closest_service.phase_for_player(p, phase, prepared=meta)
            ranked = rank_candidates(target_prof, roster, phase)
            top5_norm = [norm(c["name"]) for c in ranked[:5]]
            forb_norm = [norm(x) for x in forbidden]
            hits = [f for f, fn in zip(forbidden, forb_norm) if any(fn in t or t in fn for t in top5_norm)]
            ok = len(hits) == 0
            if ok:
                neg_pass += 1
            status = "PASS" if ok else "FAIL"
            top5_str = ", ".join(f"{c['name']} ({closest_player._similarity(target_prof, c)['match_pct']}%)" for c in ranked[:5])
            print(f"[{status}] {target_name} ({phase}) != {forbidden} | Top 5: {top5_str}")

        print(f"\nSOUHRN: Pozitivní {pos_pass}/{pos_total} | Negativní {neg_pass}/{neg_total} | Celkem {pos_pass + neg_pass}/{pos_total + neg_total}")
        return 0 if (pos_pass == pos_total and neg_pass == neg_total) else 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())

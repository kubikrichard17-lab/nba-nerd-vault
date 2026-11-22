"""
Test odolnosti profilů hráčů.

Projde všechny hráče, které aplikace zná (databáze, registr NBA a datové
soubory) a zavolá na ně profil. Cílem je najít hráče, kteří se nenačtou
kvůli chybějícím statistikám (zisky a bloky se v NBA měří až od 70. let).

Spuštění:
    python check_profiles.py            # prvních 60 hráčů bez dat v DB
    python check_profiles.py --all      # všichni (může trvat dlouho)
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import sys
from typing import List, Set

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

BASE = os.path.dirname(os.path.abspath(__file__))


def known_ids() -> Set[int]:
    """Všechna ID, která aplikace používá."""
    ids: Set[int] = set()
    try:
        from nba_api.stats.static import players as nba_players

        ids.update(p["id"] for p in nba_players.get_players())
    except Exception:
        pass

    for filename in ("alltime_official.json.gz", "career_leaders.json.gz"):
        path = os.path.join(BASE, filename)
        if not os.path.exists(path):
            continue
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            data = json.load(fh)
        for rows in (data.get("leaders") or {}).values():
            for row in rows:
                if isinstance(row, dict) and row.get("player_id"):
                    ids.add(int(row["player_id"]))

    try:
        from database import SessionLocal
        from models import Player

        db = SessionLocal()
        try:
            ids.update(p.id for p in db.query(Player).all())
        finally:
            db.close()
    except Exception:
        pass
    return ids


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true", help="projít všechny hráče")
    parser.add_argument("--limit", type=int, default=60)
    args = parser.parse_args()

    import main as app_module
    from fastapi.testclient import TestClient

    client = TestClient(app_module.app, raise_server_exceptions=False)

    ids = sorted(known_ids())
    # nejdřív hráči, kteří ještě nejsou v databázi – tam chyby vznikají
    if not args.all:
        ids = ids[: args.limit]

    problems: List[str] = []
    ok = 0
    for pid in ids:
        response = client.get(f"/api/players/{pid}")
        if response.status_code == 200:
            ok += 1
            continue
        problems.append(f"{pid}: HTTP {response.status_code} {response.text[:80]}")

    print(f"Profilů v pořádku: {ok}/{len(ids)}")
    for line in problems:
        print("  CHYBA", line)


if __name__ == "__main__":
    main()

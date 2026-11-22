"""
Stáhne klubové kariérní žebříčky z celé historie pro všech 30 klubů.

Jeden request na klub (~0,3 s), výsledek se ukládá do
backend/franchise_leaders/<ABBR>.json – aplikace ho pak čte okamžitě.

Spouští se z POST /api/leaders/rebuild-franchises (na pozadí),
nebo ručně:  python build_franchises.py [--teams BOS,LAL] [--force]
"""

import argparse
import os
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

from services import nba_career_leaders  # noqa: E402
from services import nba_news  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--teams", default="", help="jen vybrané kluby, čárkou oddělené")
    ap.add_argument("--force", action="store_true", help="stáhnout znovu i hotové kluby")
    args = ap.parse_args()

    wanted = [t.strip().upper() for t in args.teams.split(",") if t.strip()]
    teams = wanted or sorted(nba_news.TEAM_ALIASES.keys())

    started = time.time()
    ok = 0
    for i, abbr in enumerate(teams, start=1):
        try:
            leaders = nba_career_leaders.franchise_leaders(abbr, force=args.force)
        except Exception as exc:
            print(f"[{i}/{len(teams)}] {abbr}: CHYBA {exc}", flush=True)
            continue
        if leaders:
            ok += 1
            print(
                f"[{i}/{len(teams)}] {abbr}: {len(leaders)} žebříčků, "
                f"body: {leaders.get('pts', [{}])[0].get('name', '?')}",
                flush=True,
            )
        else:
            print(f"[{i}/{len(teams)}] {abbr}: prázdné", flush=True)
        time.sleep(2.5)  # ohleduplnost ke zdroji

    print(f"HOTOVO: {ok}/{len(teams)} klubů za {(time.time()-started)/60:.1f} min", flush=True)


if __name__ == "__main__":
    main()

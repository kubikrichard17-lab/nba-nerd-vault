"""
Zajímavosti generované algoritmem z dat, která aplikace už má.

Nic se nedostahuje a nevolá se AI – texty vznikají deterministicky
z `career_leaders.json.gz`, `alltime_official.json.gz` a klubových lídrů.
Výsledek se jednou spočítá a uloží do `data/facts_generated.json.gz`,
takže za běhu stránky je to jen čtení souboru.

Spuštění:  python build_facts.py
"""
from __future__ import annotations

import gzip
import json
import os
from typing import Any, Dict, Iterable, List, Optional

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, 'data', 'facts_generated.json.gz')

CAREER_FILE = os.path.join(BASE, 'career_leaders.json.gz')
ALLTIME_FILE = os.path.join(BASE, 'alltime_official.json.gz')
FRANCHISE_DIR = os.path.join(BASE, 'franchise_leaders')

# kolik zajímavostí z jednoho typu nejvíc vzít, aby se neopakovaly same
MAX_PER_KIND = 14

# ---------------------------------------------------------------- pomocné

# (4. pád jednotného čísla, 2. pád do spojení „v …", tvar po čísle)
STAT_LABEL = {
    'PTS': ('kariérní body', 'bodech', 'bodů'),
    'REB': ('kariérní doskoky', 'doskocích', 'doskoků'),
    'AST': ('kariérní asistence', 'asistencích', 'asistencí'),
    'STL': ('kariérní zisky', 'ziscích', 'zisků'),
    'BLK': ('kariérní bloky', 'blocích', 'bloků'),
    'FG3M': ('kariérní trojky', 'trojkových koších', 'trojkových košů'),
    'GP': ('kariérní zápasy', 'odehraných zápasech', 'odehraných zápasů'),
    'FGM': ('kariérní koše', 'proměněných střelách', 'proměněných střel'),
    'FGA': ('kariérní střelecké pokusy', 'střeleckých pokusech', 'střeleckých pokusů'),
    'FTM': ('kariérní šestky', 'proměněných šestkách', 'proměněných šestek'),
    'FTA': ('kariérní pokusy o šestku', 'pokusech o šestku', 'pokusů o šestku'),
    'FG3A': ('kariérní pokusy o trojku', 'pokusech o trojku', 'pokusů o trojku'),
    'TOV': ('kariérní ztráty', 'ztrátách', 'ztrát'),
}

PER_GAME_LABEL = {
    'PTS:pg': 'bodů na zápas',
    'REB:pg': 'doskoků na zápas',
    'AST:pg': 'asistencí na zápas',
    'STL:pg': 'zisků na zápas',
    'BLK:pg': 'bloků na zápas',
    'FG3M:pg': 'trojkových košů na zápas',
}

# jméno hráče → id v NBA (jen pro ty, které má aplikace v datech)
NAME_TO_ID: Dict[str, int] = {}


VOKALY = 'aeiouyáéěíóúůäöü'


def v_in(phrase: str) -> str:
    """Předložka „v" nebo „ve" podle prvního písmene (v bodech, ve střelách)."""
    first = phrase.strip()[:1].lower()
    return f've {phrase}' if first in 'fsšzž' else f'v {phrase}'


def fmt(value: float, decimals: int = 0) -> str:
    """Číslo s mezerou jako oddělovačem tisíců, česky."""
    if value is None:
        return '–'
    if decimals:
        return f'{value:,.{decimals}f}'.replace(',', ' ').replace('.', ',')
    return f'{int(round(value)):,}'.replace(',', ' ')


def fact(
    fact_id: str,
    player: str,
    category: str,
    text: str,
    player_id: Optional[int] = None,
    source: str = '',
) -> Dict[str, Any]:
    return {
        'id': fact_id,
        'player_id': player_id or player_id_for(player),
        'player': player,
        'category': category,
        'text': text,
        'source': source,
        'generated': True,
    }


def _load_gz(path: str) -> Optional[Dict[str, Any]]:
    if not os.path.exists(path):
        return None
    with gzip.open(path, 'rt', encoding='utf-8') as fh:
        return json.load(fh)


# ---------------------------------------------------------------- generátory


def from_career_leaders(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Sestavy ze žebříčků kariérních součtů a průměrů."""
    out: List[Dict[str, Any]] = []
    leaders: Dict[str, List[Dict[str, Any]]] = data.get('leaders', {})
    src = 'NBA – kariérní žebříčky'

    for key, (label, label_in, _) in STAT_LABEL.items():
        rows = [r for r in leaders.get(key, []) if r.get('value')]
        if len(rows) < 3:
            continue
        top = rows[0]
        second = rows[1]
        third = rows[2]
        gap = top['value'] - second['value']
        out.append(
            fact(
                f'gen-{key.lower()}-lead',
                top['name'],
                'Rekord',
                f'{top["name"]} vede historii NBA {v_in(label_in)} – má {fmt(top["value"])}. '
                f'Druhý {second["name"]} zaostává o {fmt(gap)}.',
                source=src,
            )
        )
        if len(rows) >= 5:
            fifth = rows[4]
            out.append(
                fact(
                    f'gen-{key.lower()}-top5',
                    top['name'],
                    'Rekord',
                    f'Pětice nejlepších {v_in(label_in)} v historii NBA: '
                    f'{top["name"]}, {second["name"]}, {third["name"]}, {rows[3]["name"]} a {fifth["name"]}. '
                    f'Na prvním místě je {top["name"]} s {fmt(top["value"])}.',
                    source=src,
                )
            )

    for key, label in PER_GAME_LABEL.items():
        rows = [r for r in leaders.get(key, []) if r.get('value')]
        if len(rows) < 3:
            continue
        top = rows[0]
        second = rows[1]
        out.append(
            fact(
                f'gen-{key.split(":")[0].lower()}-pg',
                top['name'],
                'Rekord',
                f'{top["name"]} má nejvyšší kariérní průměr v NBA: '
                f'{fmt(top["value"], 2)} {label}. Druhý {second["name"]} '
                f'({fmt(second["value"], 2)}) zaostává o '
                f'{fmt(top["value"] - second["value"], 2)}.',
                source=src,
            )
        )
    return out


def from_alltime(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Vzácná kombinace – hráč je vysoko ve více kategoriích naráz."""
    out: List[Dict[str, Any]] = []
    leaders: Dict[str, List[Dict[str, Any]]] = data.get('leaders', {})
    src = 'NBA – AllTimeLeadersGrids'

    ranks: Dict[str, Dict[str, int]] = {}
    for key, rows in leaders.items():
        if key.endswith(':pg'):
            continue
        for row in rows:
            name = row.get('name')
            rank = row.get('rank')
            if name and rank:
                ranks.setdefault(name, {})[key] = int(rank)

    # hráči, kteří jsou v top 10 alespoň ve čtyřech kategoriích
    multi = [
        (name, table)
        for name, table in ranks.items()
        if sum(1 for r in table.values() if r <= 10) >= 4
    ]
    multi.sort(key=lambda item: -sum(1 for r in item[1].values() if r <= 10))
    for name, table in multi[:MAX_PER_KIND]:
        tops = sorted(
            ((k, r) for k, r in table.items() if r <= 10),
            key=lambda kr: kr[1],
        )
        listed = ', '.join(
            f'{STAT_LABEL.get(k, (k, k, k))[0]} ({r}.)' for k, r in tops[:4]
        )
        out.append(
            fact(
                f'gen-multi-{abs(hash(name)) % 100000}',
                name,
                'Rekord',
                f'{name} je v historických tabulkách NBA v top 10 hned v {len(tops)} '
                f'kategoriích: {listed}. Takových hráčů je v celé historii jen {len(multi)}.',
                source=src,
            )
        )

    # jedničky v jedné kategorii a přitom slabší jinde – kontrast
    for key, rows in leaders.items():
        if key.endswith(':pg') or not rows:
            continue
        top = rows[0]
        name = top.get('name')
        table = ranks.get(name, {})
        if not table or not top.get('value'):
            continue
        worst_key, worst_rank = max(table.items(), key=lambda kr: kr[1])
        if worst_rank >= 40:
            out.append(
                fact(
                    f'gen-contrast-{key.lower()}-{abs(hash(name)) % 100000}',
                    name,
                    'Příběh',
                    f'{name} je v {STAT_LABEL.get(key, (key, key, key))[1]} na 1. místě historie NBA '
                    f'({fmt(top["value"])}), ale v {STAT_LABEL.get(worst_key, (worst_key, worst_key, worst_key))[1]} '
                    f'mu tolik nešlo – patří mu až {worst_rank}. místo.',
                    source=src,
                )
            )
            break
    return out


def from_franchises() -> List[Dict[str, Any]]:
    """Kluboví rekordmani a hráči, kteří vládnou více klubům."""
    if not os.path.isdir(FRANCHISE_DIR):
        return []

    out: List[Dict[str, Any]] = []
    per_club: Dict[str, Dict[str, Any]] = {}
    owner: Dict[str, List[str]] = {}

    for filename in sorted(os.listdir(FRANCHISE_DIR)):
        if not filename.endswith('.json.gz'):
            continue
        data = _load_gz(os.path.join(FRANCHISE_DIR, filename))
        if not data:
            continue
        abbr = data.get('abbr', filename.split('.')[0])
        leaders = data.get('leaders', {})
        rows = [r for r in leaders.get('pts', []) if r.get('value')]
        if not rows:
            continue
        top = rows[0]
        per_club[abbr] = top
        owner.setdefault(top['name'], []).append(abbr)

        # jen výjimečné klubové rekordy – všechny by se opakovaly
        if top['value'] >= 25000:
            out.append(
                fact(
                    f'gen-club-{abbr.lower()}-pts',
                    top['name'],
                    'Trofeje',
                    f'{top["name"]} je nejlepším střelcem historie klubu {abbr}: '
                    f'{fmt(top["value"])} bodů.',
                    source='Basketball-Reference – kluboví lídři',
                )
            )

    if per_club:
        names = sorted(per_club.values(), key=lambda r: -r['value'])
        best = names[0]
        best_club = next(
            (abbr for abbr, row in per_club.items() if row is best), ''
        )
        out.append(
            fact(
                'gen-club-best-all',
                best['name'],
                'Trofeje',
                f'Nejvíc bodů v historii jednoho klubu má {best["name"]} – '
                f'{fmt(best["value"])} za {best_club}. '
                f'Klubové rekordmany má aplikace u všech {len(per_club)} klubů.',
                source='Basketball-Reference – kluboví lídři',
            )
        )

    for name, clubs in sorted(owner.items(), key=lambda kv: -len(kv[1])):
        if len(clubs) < 2:
            continue
        out.append(
            fact(
                f'gen-club-multi-{abs(hash(name)) % 100000}',
                name,
                'Trofeje',
                f'{name} vede klubové tabulky střelců hned u {len(clubs)} klubů: '
                f'{", ".join(clubs)}. V žádném jiném klubu v historii nebyl nejlepší střelec.',
                source='Basketball-Reference – kluboví lídři',
            )
        )

    # kluby, kde je rozdíl mezi prvním a druhým nejmenší – tým bez jedné hvězdy
    closest: List[tuple] = []
    all_ratios: List[float] = []
    for filename in sorted(os.listdir(FRANCHISE_DIR)):
        if not filename.endswith('.json.gz'):
            continue
        data = _load_gz(os.path.join(FRANCHISE_DIR, filename))
        if not data:
            continue
        rows = [r for r in data.get('leaders', {}).get('pts', []) if r.get('value')]
        if len(rows) < 2:
            continue
        # poměr druhého k prvnímu – čím blíž 1, tím vyrovnanější čelo
        if not rows[0]['value']:
            continue
        ratio = rows[1]['value'] / rows[0]['value']
        all_ratios.append(ratio)
        closest.append((ratio, data.get('abbr'), rows[0], rows[1]))
    closest.sort(key=lambda item: item[0])
    avg_gap = (1 - sum(all_ratios) / len(all_ratios)) * 100 if all_ratios else 0.0
    for ratio, abbr, first, second in closest[:4]:
        own_gap = (1 - ratio) * 100
        if avg_gap and own_gap < avg_gap:
            tail = (
                f'V celé lize je přitom průměrný rozdíl mezi prvním a druhým '
                f'střelcem klubu {fmt(avg_gap, 0)} % – tady jen {fmt(own_gap, 0)} % '
                f'z bodů lídra.'
            )
        else:
            tail = (
                f'I tak jde o nejtěsnější čelo v lize; průměrný rozdíl '
                f'mezi prvním a druhým střelcem klubu je přitom {fmt(avg_gap, 0)} % '
                f'z bodů lídra.'
            )
        out.append(
            fact(
                f'gen-club-tight-{str(abbr).lower()}',
                second['name'],
                'Příběh',
                f'Klub {abbr} má nejvyrovnanější čelo střelců v lize: {first["name"]} '
                f'({fmt(first["value"])} bodů) vede před {second["name"]} '
                f'({fmt(second["value"])}) jen o {fmt(first["value"] - second["value"])} bodů. '
                f'{tail}',
                source='Basketball-Reference – kluboví lídři',
            )
        )
    return out


# ---------------------------------------------------------------- stavba


def load_name_index() -> None:
    """Jména hráčů z databáze → jejich NBA id (pro fotky a proklik)."""
    try:
        import sys
        sys.path.insert(0, BASE)
        from database import SessionLocal
        from models import Player
    except Exception:
        return
    db = SessionLocal()
    try:
        for player in db.query(Player).all():
            name = player.full_name.strip().lower()
            NAME_TO_ID[name] = player.id
            # i bez diakritiky a po příjmení (data mají „Nikola Jokić" vs „Jokic")
            plain = (
                name.replace('ć', 'c').replace('č', 'c').replace('š', 's')
                .replace('ž', 'z').replace('ř', 'r').replace('ě', 'e')
                .replace('á', 'a').replace('í', 'i').replace('é', 'e')
                .replace('ú', 'u').replace('ů', 'u').replace('ý', 'y')
                .replace('ň', 'n').replace('ď', 'd').replace('ť', 't')
                .replace('ó', 'o').replace('ä', 'a').replace('ö', 'o')
                .replace('ü', 'u')
            )
            NAME_TO_ID.setdefault(plain, player.id)
    finally:
        db.close()


def player_id_for(name: str) -> int:
    """Najde hráče v datech aplikace (i s diakritikou nebo bez)."""
    if not name:
        return 0
    key = name.strip().lower()
    if key in NAME_TO_ID:
        return NAME_TO_ID[key]
    plain = (
        key.replace('ć', 'c').replace('č', 'c').replace('š', 's')
        .replace('ž', 'z').replace('ř', 'r').replace('ě', 'e')
        .replace('á', 'a').replace('í', 'i').replace('é', 'e')
        .replace('ú', 'u').replace('ů', 'u').replace('ý', 'y')
        .replace('ň', 'n').replace('ď', 'd').replace('ť', 't')
        .replace('ó', 'o').replace('ä', 'a').replace('ö', 'o')
        .replace('ü', 'u')
    )
    if plain in NAME_TO_ID:
        return NAME_TO_ID[plain]
    # poslední šance: příjmení
    surname = plain.split()[-1] if plain.split() else plain
    for known, pid in NAME_TO_ID.items():
        if known.split() and known.split()[-1] == surname:
            return pid
    return 0


def build() -> List[Dict[str, Any]]:
    load_name_index()
    career = _load_gz(CAREER_FILE)
    alltime = _load_gz(ALLTIME_FILE)

    facts: List[Dict[str, Any]] = []
    if career:
        facts += from_career_leaders(career)
    if alltime:
        facts += from_alltime(alltime)
    facts += from_franchises()

    # bez duplicitních textů
    seen: set = set()
    unique: List[Dict[str, Any]] = []
    for f in facts:
        key = f['text'].strip().lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(f)
    return unique


def main() -> None:
    facts = build()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with gzip.open(OUT, 'wt', encoding='utf-8') as fh:
        json.dump({'count': len(facts), 'facts': facts}, fh, ensure_ascii=False)
    print(f'Uloženo {len(facts)} zajímavostí do {OUT}')
    for f in facts[:8]:
        print(' -', f['category'], '|', f['player'], '|', f['text'][:95])


if __name__ == '__main__':
    main()

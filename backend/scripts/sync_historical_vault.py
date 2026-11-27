"""Offline season import from verified NBA/BBR archives; never start on Render.

JSON(.gz): list of {player:{id,full_name,first_name,last_name,is_active},
 dimensions:{height_cm,weight_kg,position}, rows:[{PLAYER_ID,SEASON_ID,GP,...}]}.
CSV: same keys flattened, with NBA ID and canonical name verified upstream.
BBR exports must be normalized to this schema (regular season, NBA ID, per game).
"""
import argparse
import csv
import gzip
import json
import math
import os
import sqlite3
from pathlib import Path

FIELDS = dict(zip('season_id team_abbreviation player_age gp gs min_per_game pts reb ast stl blk tov pf fgm fga fg_pct fg3m fg3a fg3_pct ftm fta ft_pct'.split(),
                  'SEASON_ID TEAM_ABBREVIATION PLAYER_AGE GP GS MIN PTS REB AST STL BLK TOV PF FGM FGA FG_PCT FG3M FG3A FG3_PCT FTM FTA FT_PCT'.split()))


def read_archive(path):
    if path.suffix == '.csv':
        grouped = {}
        with path.open(encoding='utf-8-sig', newline='') as f:
            for row in csv.DictReader(f):
                pid = int(row['PLAYER_ID'])
                name = row['full_name']
                first, _, last = name.partition(' ')
                record = grouped.setdefault(pid, {'player': dict(id=pid, full_name=name, first_name=first, last_name=last, is_active=False),
                    'dimensions': {k: row[k] for k in ('height_cm','weight_kg','position')}, 'rows': []})
                if record['player']['full_name'] != name:
                    raise ValueError(f'Conflicting names for {pid}')
                record['rows'].append(row)
        return list(grouped.values())
    opener = gzip.open if path.suffix == '.gz' else open
    with opener(path, 'rt', encoding='utf-8') as f:
        return json.load(f)


def number(v):
    x = float(v) if v not in (None, '') else None
    return x if x is not None and math.isfinite(x) else None


def sync(path, db):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from services.nba_external import normalize_name
    from nba_api.stats.static import players
    with sqlite3.connect(db) as c:
        for record in read_archive(path):
            p, m = record['player'], record['dimensions']
            pid, name = int(p['id']), p['full_name']
            reg = players.find_player_by_id(pid)
            if not reg or normalize_name(reg['full_name']) != normalize_name(name):
                raise ValueError(f'Unverified identity: {pid} / {name}')
            rows = {}
            for r in record['rows']:
                season = r['SEASON_ID']; year = int(season[:4]); gp = number(r.get('GP'))
                if int(r['PLAYER_ID']) != pid or season != f'{year:04}-{(year+1)%100:02}':
                    raise ValueError(f'Invalid season or identity {pid}/{season}')
                if gp and gp > 0:
                    if season in rows:
                        raise ValueError(f'Duplicate season {pid}/{season}; use league total')
                    rows[season] = r
            if not rows:
                raise ValueError(f'No seasons for {pid}')
            existing = c.execute('SELECT full_name FROM players WHERE id=?', (pid,)).fetchone()
            if existing and normalize_name(existing[0]) != normalize_name(name):
                raise ValueError(f'Collision with stored ID {pid}')
            c.execute('''INSERT INTO players(id,full_name,first_name,last_name,is_active,height_cm,weight_kg,position,headshot_url,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP) ON CONFLICT(id) DO UPDATE SET
                height_cm=COALESCE(excluded.height_cm,players.height_cm), weight_kg=COALESCE(excluded.weight_kg,players.weight_kg),
                position=COALESCE(excluded.position,players.position), updated_at=CURRENT_TIMESTAMP''',
                (pid,name,p.get('first_name'),p.get('last_name'),p.get('is_active',False),number(m.get('height_cm')),number(m.get('weight_kg')),m.get('position'),f'https://cdn.nba.com/headshots/nba/latest/1040x760/{pid}.png'))
            for season, r in sorted(rows.items()):
                year = int(season[:4]); values=[]
                for k,v in FIELDS.items():
                    values.append(r.get(v) if k in ('season_id','team_abbreviation') else None if year<1973 and k in ('stl','blk') else number(r.get(v)))
                c.execute('DELETE FROM player_season_stats WHERE player_id=? AND season_id=?',(pid,season))
                c.execute(f'INSERT INTO player_season_stats(player_id,{",".join(FIELDS)}) VALUES({",".join("?" for _ in range(len(FIELDS)+1))})',[pid,*values])
            print(pid,name,len(rows))
        assert c.execute('PRAGMA integrity_check').fetchone()==('ok',)


if __name__ == '__main__':
    if os.getenv('RENDER', '').lower() == 'true':
        raise SystemExit('Offline only')
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('archive',type=Path)
    p.add_argument('--db', type=Path, default=Path(__file__).resolve().parents[1]/'nba_vault.db')
    args=p.parse_args()
    if not args.db.is_file():p.error('SQLite database must already exist')
    sync(args.archive,args.db)

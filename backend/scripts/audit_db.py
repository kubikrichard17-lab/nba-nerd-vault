import sqlite3, json, sys

conn = sqlite3.connect(r'C:\Users\42077\.gemini\antigravity\scratch\nba-nerd-vault\backend\nba_vault.db')
cur = conn.cursor()

cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in cur.fetchall()]
print('=== TABULKY ===')
for t in tables:
    cur.execute(f'PRAGMA table_info({t})')
    cols = [r[1] for r in cur.fetchall()]
    print(f'  {t}: {cols}')

cur.execute("SELECT COUNT(*) FROM players")
n = cur.fetchone()[0]
print(f'\n=== HRACU v DB: {n} ===')
cur.execute("SELECT id, full_name, is_active FROM players ORDER BY full_name LIMIT 60")
for r in cur.fetchall():
    print(f'  {r[0]:>8} {"A" if r[1] else " "} {r[2]}')

cur.execute("PRAGMA table_info(player_season_stats)")
cols = [r[1] for r in cur.fetchall()]
wanted = ['dbpm','obpm','bpm','dws','per','ts_pct','usg_pct','ast_pct','trb_pct','orb_pct','drb_pct','stl_pct','blk_pct','pct_fga_0_3','pct_fga_mid','pct_fga_3p','pct_astd_fg']
present = [c for c in cols if c in wanted]
missing = [c for c in wanted if c not in cols]
print(f'\n=== Advanced columns present: {present}')
print(f'=== Advanced columns MISSING: {missing}')

conn.close()

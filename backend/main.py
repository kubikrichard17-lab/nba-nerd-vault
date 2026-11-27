import json
import logging
import os
from datetime import datetime
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session

from services import source_switch

source_switch.install()

from database import engine, get_db, Base
from models import Player, PlayerSeasonStat, PlayerAward, ComparisonCache, ClosestCache
from services.nba_fetcher import (
    search_players_service,
    fetch_and_cache_player,
    ensure_correct_name,
)
from services.similarity_engine import compare_players
from services import advanced_cache, closest_service
from services import nba_news
import settings
from services import (
    closest_player,
    nba_alltime,
    nba_career_leaders,
    nba_external,
    nba_facts,
    nba_player_bio,
)
from services.nba_news import NewsDataError

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nba_nerd_vault")

# Initialize database tables
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="NBA Nerd Vault API",
    description="Backend API pro NBA Nerd Vault – databázová cache, pokročilý similarity engine a AI scouting v češtině.",
    version="1.0.0"
)

# Enable CORS for frontend Next.js
# Doma "*" (localhost / domácí síť); pro nasazení lze omezit přes ALLOWED_ORIGINS.
_ORIGINS = settings.allowed_origins()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_ORIGINS,
    allow_credentials="*" not in _ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health_check():
    return {
        "status": "online",
        "app": "NBA Nerd Vault",
        "phase": 1,
        "similarity_engine": closest_player.ENGINE_VERSION,
        "data_source": "espn" if source_switch.espn_first() else "nba",
        "database": "SQLite (nba_vault.db)"
    }


# --------------------------------------------------------------------------- #
# Novinky, boxscores a lídři statistik
# --------------------------------------------------------------------------- #

@app.get("/api/news/games")
def news_games(days: int = Query(1, ge=1, le=7, description="Kolik posledních hracích dnů vrátit")):
    """Výsledky zápasů z posledního hracího dne (tým vs tým + skóre)."""
    try:
        return nba_news.get_recent_games(days_back=days)
    except NewsDataError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.get("/api/news/schedule")
def news_schedule(day: int = Query(0, ge=-1, le=7, description="0 = dnes, 1 = zítra, -1 = včera")):
    """Rozpis zápasů na den (časy v UTC, frontend si je převede do lokálního pásma)."""
    try:
        return nba_news.get_schedule(day_offset=day)
    except NewsDataError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.get("/api/news/games/{game_id}")
def news_game_detail(game_id: str):
    """Boxscore zápasu – statistiky všech hráčů obou týmů."""
    try:
        return nba_news.get_game_boxscore(game_id)
    except NewsDataError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


def _fact_with_context(fact: Dict[str, Any]) -> Dict[str, Any]:
    """Doplní zajímavost o fotku a životopis hráče (věk, roky v NBA, klub)."""
    pid = int(fact.get("player_id") or 0)
    if not pid:
        # zajímavost může být o hráči, který v datech aplikace není
        return {**fact, "headshot_url": "", "bio": {}}
    info = nba_player_bio.bio(pid) or {}
    age = None
    birth = info.get("birthdate") or ""
    if len(birth) >= 4 and birth[:4].isdigit():
        age = datetime.now().year - int(birth[:4])
    return {
        **fact,
        "headshot_url": f"https://cdn.nba.com/headshots/nba/latest/1040x760/{pid}.png",
        "bio": {
            "birthdate": info.get("birthdate", ""),
            "age": age,
            "from_year": info.get("from_year"),
            "to_year": info.get("to_year"),
            "team": info.get("team", ""),
            "position": info.get("position", ""),
            "height": info.get("height", ""),
        },
    }


@app.get("/api/facts")
def facts(
    limit: Optional[int] = Query(None, description="kolik zajímavostí vrátit"),
    category: Optional[str] = Query(None, description="Rekord / Trofeje / Příběh"),
    player_id: Optional[int] = Query(None, description="jen zajímavosti k hráči"),
    shuffle: bool = Query(True, description="promíchat pořadí"),
):
    """
    Zajímavosti (fun facts) o NBA hráčích.

    Fotka hráče se bere z oficiálního NBA CDN podle ID, takže vždy sedí.
    """
    import random as _random

    items = nba_facts.all_facts()
    if player_id:
        items = [f for f in items if int(f["player_id"]) == int(player_id)]
    if category:
        items = [f for f in items if f["category"].lower() == category.lower()]
    items = list(items)
    if shuffle:
        _random.shuffle(items)
    if limit:
        items = items[: max(1, min(int(limit), 100))]

    out = [_fact_with_context(f) for f in items]
    return {
        "count": len(out),
        "total": len(nba_facts.all_facts()),
        "categories": nba_facts.categories(),
        "facts": out,
    }


@app.get("/api/standings")
def standings(season: Optional[str] = Query(None, description="sezóna, např. 2026-27")):
    """Tabulka sezóny po konferencích (východ / západ) s rekordy týmů."""
    try:
        return nba_news.get_standings(season=season)
    except NewsDataError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.get("/api/leaders/career-status")
def career_status():
    """Stav oficiálních all-time dat (celá historie NBA)."""
    return nba_alltime.status()


@app.post("/api/leaders/rebuild")
def rebuild_career_pool(background: bool = Query(False)):
    """
    Znovu stáhne oficiální all-time žebříčky NBA (trvá ~2 s).
    """
    data = nba_alltime.build_official_pool(force=True)
    return {
        "started": False,
        "stats": len(data.get("leaders") or {}),
        "players": len(data.get("people") or {}),
        "status": nba_alltime.status(),
    }


@app.post("/api/leaders/rebuild-franchises")
def rebuild_franchises(
    teams: Optional[str] = Query(None, description="jen vybrané kluby, čárkou oddělené"),
    force: bool = Query(False),
):
    """
    Stáhne klubové kariérní žebříčky z celé historie (jeden request na klub,
    ~0,3 s). Běží na pozadí; stav je na /api/leaders/franchise-status.
    """
    import subprocess
    import sys as _sys

    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "build_franchises.py")
    cmd = [_sys.executable, "-u", script]
    if teams:
        cmd += ["--teams", teams]
    if force:
        cmd += ["--force"]

    log_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "franchise_leaders.log"
    )
    log = open(log_path, "a", encoding="utf-8")
    log.write(f"\n=== start {datetime.now().isoformat()} ===\n")
    log.flush()
    proc = subprocess.Popen(
        cmd,
        cwd=os.path.dirname(os.path.abspath(__file__)),
        stdout=log,
        stderr=subprocess.STDOUT,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return {"started": True, "pid": proc.pid, "status": nba_career_leaders.franchise_status()}


@app.get("/api/leaders/franchise-status")
def franchise_status():
    """Kolik klubů už má stažené kariérní žebříčky z celé historie."""
    return nba_career_leaders.franchise_status()


@app.get("/api/leaders/career-status")
def career_status():
    """Stav oficiálních all-time dat (celá historie NBA)."""
    return nba_alltime.status()


@app.post("/api/leaders/rebuild")
def rebuild_career_pool(background: bool = Query(False)):
    """
    Znovu stáhne oficiální all-time žebříčky NBA (trvá ~2 s).
    """
    data = nba_alltime.build_official_pool(force=True)
    return {
        "started": False,
        "stats": len(data.get("leaders") or {}),
        "players": len(data.get("people") or {}),
        "status": nba_alltime.status(),
    }


@app.post("/api/leaders/rebuild-franchises")
def rebuild_franchises(
    teams: Optional[str] = Query(None, description="jen vybrané kluby, čárkou oddělené"),
    force: bool = Query(False),
):
    """
    Spustí dopočítání týmových žebříčků z celé historie klubu na pozadí.
    Stav jde sledovat na /api/leaders/franchise-status.
    """
    import subprocess
    import sys as _sys

    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "build_franchises.py")
    cmd = [_sys.executable, "-u", script]
    if teams:
        cmd += ["--teams", teams]
    if force:
        cmd += ["--force"]

    log_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "franchise_pool.log"
    )
    log = open(log_path, "a", encoding="utf-8")
    log.write(f"\n=== start {datetime.now().isoformat()} ===\n")
    log.flush()
    proc = subprocess.Popen(
        cmd,
        cwd=os.path.dirname(os.path.abspath(__file__)),
        stdout=log,
        stderr=subprocess.STDOUT,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return {"started": True, "pid": proc.pid, "status": _franchise_status()}


def _franchise_status() -> Dict[str, Any]:
    import json as _json

    base = os.path.dirname(os.path.abspath(__file__))
    pool_path = os.path.join(base, "franchise_pool.json")
    prog_path = os.path.join(base, "franchise_pool.progress.json")
    ready: List[str] = []
    if os.path.exists(pool_path):
        try:
            with open(pool_path, encoding="utf-8") as fh:
                data = _json.load(fh)
            ready = sorted(k for k, v in data.items() if (v or {}).get("players_list"))
        except Exception:
            ready = []
    progress = {}
    if os.path.exists(prog_path):
        try:
            with open(prog_path, encoding="utf-8") as fh:
                progress = _json.load(fh)
        except Exception:
            progress = {}
    return {
        "teams_ready": len(ready),
        "teams": ready,
        "progress": progress,
    }


@app.get("/api/leaders/franchise-status")
def franchise_status():
    """Kolik klubů už má dopočítané celé historie (týmové žebříčky)."""
    return _franchise_status()


@app.get("/api/leaders/meta")
def leaders_meta():
    """Možnosti pro UI žebříčků (statistiky, týmy, režimy)."""
    return {
        "stats": nba_news.get_stats_definitions(),
        "teams": nba_news.get_teams(),
        "modes": [
            {"key": "alltime", "label": "All-Time"},
            {"key": "season", "label": "Sezóna"},
            {"key": "team", "label": "Tým / franšíza"},
        ],
        "current_season": nba_news.current_season(),
        "seasons": nba_news._available_seasons()[:12],
    }


@app.get("/api/leaders")
def leaders(
    mode: str = Query("season", description="alltime | season | team"),
    stat: str = Query("PTS", description="PTS, REB, AST, STL, BLK, FG3M, MIN, FG_PCT, FG3_PCT, FT_PCT"),
    per_game: bool = Query(True, description="True = průměr na zápas, False = celkový součet"),
    team: Optional[str] = Query(None, description="Zkratka týmu pro režim team"),
    season: Optional[str] = Query(None, description="Sezóna ve formátu 2026-27"),
    limit: int = Query(15, ge=1, le=50),
):
    """Žebříčky lídrů – All-Time / Sezóna / Tým, na zápas nebo celkem."""
    try:
        return nba_news.get_leaders(
            mode=mode, stat=stat, per_game=per_game, team=team, season=season, limit=limit
        )
    except NewsDataError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.get("/api/players/search")
def search_players(
    q: str = Query("", description="Hledané jméno hráče"),
    limit: int = Query(15, description="Limit výsledků"),
    db: Session = Depends(get_db)
):
    """Instant search with autocomplete across SQLite cache and NBA static registry."""
    return search_players_service(query=q, db=db, limit=limit)


@app.get("/api/players/seeded")
def get_seeded_players(db: Session = Depends(get_db)):
    """Return list of players currently stored in SQLite database."""
    players = db.query(Player).order_by(Player.full_name.asc()).all()
    return [
        {
            "id": p.id,
            "full_name": p.full_name,
            "position": p.position,
            "height_cm": p.height_cm,
            "weight_kg": p.weight_kg,
            "is_active": p.is_active,
            "headshot_url": p.headshot_url,
            "tags": json.loads(p.playstyle_tags) if p.playstyle_tags else []
        }
        for p in players
    ]


def _row_get(row: Any, key: str) -> Any:
    """
    Jedno čtení statistiky ze sezóny – ať už je to řádek z databáze
    (atribut) nebo slovník z ESPN.
    """
    if isinstance(row, dict):
        return row.get(key)
    return getattr(row, key, None)


@app.get("/api/players/{player_id}")
def get_player_profile(player_id: int, db: Session = Depends(get_db)):
    """Return full player profile with career stats, awards, Wikipedia bio and AI scout report."""
    player = fetch_and_cache_player(player_id=player_id, db=db)
    if player is not None:
        # ID z NBA musí mít správné jméno – data ze záložního zdroje mohla
        # pod stejné číslo uložit cizí hráče (ESPN má vlastní číselník).
        player = ensure_correct_name(player, db)
    if not player:
        raise HTTPException(status_code=404, detail="Hráč nebyl nalezen v databázi ani v NBA API.")

    # Sezóny: databáze je nemusí mít (v cloudu NBA API neodpovídá, takže
    # se hráč uloží jen se jménem a mírami). Pak se vezmou z ESPN, aby
    # profil nebyl prázdný.
    season_rows = list(player.stats or [])
    if not season_rows and not source_switch.espn_first():
        try:
            from services import espn_seasons

            season_rows = espn_seasons.player_season_stats(player_id, name=player.full_name) or []
        except Exception as exc:  # pragma: no cover
            logger.warning("Sezóny hráče %s z ESPN selhaly: %s", player_id, exc)

    # Format season stats
    season_stats = []
    season_rows.sort(key=lambda x: _row_get(x, "season_id") or "")
    for s in season_rows:
        season_stats.append({
            "season_id": _row_get(s, "season_id"),
            "team_abbreviation": _row_get(s, "team_abbreviation"),
            "player_age": _row_get(s, "player_age"),
            "gp": _row_get(s, "gp"),
            "gs": _row_get(s, "gs"),
            "min_per_game": _row_get(s, "min_per_game"),
            "pts": _row_get(s, "pts"),
            "reb": _row_get(s, "reb"),
            "ast": _row_get(s, "ast"),
            "stl": _row_get(s, "stl"),
            "blk": _row_get(s, "blk"),
            "tov": _row_get(s, "tov"),
            "pf": _row_get(s, "pf"),
            "fgm": _row_get(s, "fgm"),
            "fga": _row_get(s, "fga"),
            "fg_pct": _row_get(s, "fg_pct"),
            "fg3m": _row_get(s, "fg3m"),
            "fg3a": _row_get(s, "fg3a"),
            "fg3_pct": _row_get(s, "fg3_pct"),
            "ftm": _row_get(s, "ftm"),
            "fta": _row_get(s, "fta"),
            "ft_pct": _row_get(s, "ft_pct"),
            "poss100_pts": _row_get(s, "poss100_pts"),
            "poss100_reb": _row_get(s, "poss100_reb"),
            "poss100_ast": _row_get(s, "poss100_ast"),
            "poss100_stl": _row_get(s, "poss100_stl"),
            "poss100_blk": _row_get(s, "poss100_blk"),
            "poss100_tov": _row_get(s, "poss100_tov"),
        })

    # Calculate career averages
    total_gp = sum(int(s["gp"] or 0) for s in season_stats)
    career_summary = {}
    if total_gp > 0:
        def _avg(field: str, decimals: int = 1) -> Optional[float]:
            """
            Vážený průměr podle zápasů. Starší sezóny nemají některé
            statistiky vůbec (Wes Unseld – zisky a bloky se neměřily),
            proto se takové sezóny přeskakují, místo aby shodily celý profil.
            """
            pairs = [
                (s[field], int(s["gp"] or 0))
                for s in season_stats
                if s.get(field) is not None and int(s.get("gp") or 0) > 0
            ]
            games = sum(g for _, g in pairs)
            if not games:
                return None
            return round(sum(v * g for v, g in pairs) / games, decimals)

        career_summary = {
            "gp": total_gp,
            "pts": _avg("pts"),
            "reb": _avg("reb"),
            "ast": _avg("ast"),
            "stl": _avg("stl"),
            "blk": _avg("blk"),
            "tov": _avg("tov"),
            "fg_pct": _avg("fg_pct", 3),
            "fg3_pct": _avg("fg3_pct", 3),
            "ft_pct": _avg("ft_pct", 3),
            "poss100_pts": _avg("poss100_pts"),
            "poss100_reb": _avg("poss100_reb"),
            "poss100_ast": _avg("poss100_ast"),
            "poss100_stl": _avg("poss100_stl"),
            "poss100_blk": _avg("poss100_blk"),
        }

    # Awards list
    awards = [
        {
            "description": a.description,
            "description_cs": a.description_cs or a.description,
            "count": a.count,
            "season": a.season
        }
        for a in player.awards
    ]

    tags = []
    if player.playstyle_tags:
        try:
            tags = json.loads(player.playstyle_tags)
        except Exception:
            tags = []

    return _json_safe({
        "id": player.id,
        "full_name": player.full_name,
        "first_name": player.first_name,
        "last_name": player.last_name,
        "is_active": player.is_active,
        "headshot_url": player.headshot_url,
        "height_cm": player.height_cm,
        "height_ft": player.height_ft,
        "weight_kg": player.weight_kg,
        "weight_lbs": player.weight_lbs,
        "position": player.position,
        "draft_year": player.draft_year,
        "draft_round": player.draft_round,
        "draft_number": player.draft_number,
        "draft_team": player.draft_team,
        "college": player.college,
        "country": player.country,
        "bio_summary": player.bio_summary,
        "scouting_report": player.scouting_report,
        "playstyle_tags": tags,
        "season_stats": season_stats,
        "career_summary": career_summary,
        "clubs": _clubs_safe(player),
        "awards": awards,
        "latest_season": season_stats[-1] if season_stats else None
    })


def _json_safe(value: Any) -> Any:
    """
    Nahradí NaN a nekonečna za None, aby profil šel vždy převést na JSON.
    Jedna taková hodnota (třeba zisky u hráčů z 60. let) jinak shodí
    celou stránku hráče – přesně to se dělo u Wese Unselda.
    """
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return None
    return value


def _clubs_safe(player: Player) -> List[Dict[str, Any]]:
    """Klubová kariéra nesmí shodit celý profil, když zdroj neodpovídá."""
    try:
        return _club_career(player)
    except Exception as exc:  # pragma: no cover
        logger.warning("Klubová kariéra %s selhala: %s", player.full_name, exc)
        return []


def _club_career(player: Player) -> List[Dict[str, Any]]:
    """
    Kariéra po klubech: klub, roky, zápasy a průměry.
    Bere se z NBA API (sezóny včetně týmů), když nejde, z Basketball-Reference,
    a když ani to ne, složí se aspoň z toho, co je v databázi.
    """
    try:
        external = (nba_external._cache_get(f"clubs:{player.id}", nba_external.TTL_PROFILE)
                    if source_switch.espn_first() else nba_external.career_clubs(player.id, player.full_name))
        clubs = external.get("clubs") if isinstance(external, dict) else None
        if clubs:
            return clubs
    except Exception as exc:  # pragma: no cover
        logger.warning("Klubová kariéra %s selhala: %s", player.full_name, exc)

    # Poslední záchrana: co je v databázi
    rows = [
        {
            "season_id": s.season_id,
            "team_abbreviation": s.team_abbreviation or "",
            "gp": s.gp or 0,
            "pts": s.pts or 0.0,
            "reb": s.reb or 0.0,
            "ast": s.ast or 0.0,
            "stl": s.stl or 0.0,
            "blk": s.blk or 0.0,
            "fg3m": s.fg3m or 0.0,
        }
        for s in player.stats
        if s.team_abbreviation and s.team_abbreviation != "TOT"
    ]
    if not rows:
        return []
    return nba_external._merge_club_runs(rows)


def _player_info(player: Player, stat: Dict[str, Any]) -> Dict[str, Any]:
    tags: List[str] = []
    if player.playstyle_tags:
        try:
            tags = json.loads(player.playstyle_tags)
        except Exception:
            tags = []
    return {
        "id": player.id,
        "name": player.full_name,
        "position": player.position,
        "height_cm": player.height_cm,
        "weight_kg": player.weight_kg,
        "headshot_url": player.headshot_url,
        "tags": tags,
        "pts": stat.get("pts", 0),
        "reb": stat.get("reb", 0),
        "ast": stat.get("ast", 0),
    }



# Kolik hráčů se maximálně bere z externího zdroje jako kandidáti
EXTERNAL_POOL_LIMIT = 260


def _external_pool(external: Optional[Dict[str, Any]], target_id: int) -> List[Dict[str, Any]]:
    """
    Kandidáti pro porovnání z externích zdrojů (NBA API, Basketball-Reference).

    Bere se sezónní tabulka celé ligy – jeden dotaz na sezónu, ne dotaz
    pro každého hráče. Kandidáti se vybírají podle podobné role a kategorie
    dopadu, aby se střelec bez míče neporovnával s rozehrávačem.
    """
    if not external:
        return []

    # Profil cílového hráče
    target = closest_player.build_profile(
        player_id=target_id,
        name=external.get("name", ""),
        position=external.get("position"),
        height_cm=external.get("height_cm"),
        weight_kg=external.get("weight_kg"),
        stat=external,
    )

    # Filtr kandidátů: jiný objem bodů znamená jinou roli v týmu.
    # Hráč s 25 body se neporovnává s náhradníkem, který dá 9.
    want_pts = external.get("pts", 0.0)
    if want_pts >= 22:
        min_pts, max_pts = want_pts - 8.0, want_pts + 8.0
    elif want_pts >= 16:
        min_pts, max_pts = want_pts - 6.0, want_pts + 9.0
    else:
        min_pts, max_pts = 0.0, want_pts + 10.0

    rows = nba_external.league_season_for_profile(external)
    if not rows:
        return []

    # Hráči, které už aplikace zná, se přidají vždy – záloha pro výpadky NBA API
    known = {r["id"] for r in rows}
    for extra in nba_external._cached_players():
        if extra["id"] not in known:
            rows.append(extra)
            known.add(extra["id"])

    picked: List[Dict[str, Any]] = []
    for row in rows:
        if row["id"] == target_id:
            continue
        if row.get("gp", 0) < 40:
            continue
        if not (min_pts <= row.get("pts", 0.0) <= max_pts):
            continue
        profile = dict(row)
        # Když chybí pozice nebo výška, dohledá se profil hráče – jen pro
        # kandidáty, kteří projdou filtrem, ne pro celou ligu.
        if not profile.get("height_cm") or not profile.get("position"):
            # V cloudu je NBA API zablokované a sezónní tabulka ESPN míry
            # nemá – dohledá se jen to, co už aplikace zná (paměť), plus
            # u hráčů bez míry profil z ESPN (jen pro kandidáty z filtru).
            details = nba_external.known_position(row["id"])
            if not details or not details.get("height_cm"):
                details = nba_external.position_and_size(row["id"], row["name"]) or details
            if details:
                profile.setdefault("position", "")
                profile["position"] = profile.get("position") or details.get("position", "")
                profile["height_cm"] = profile.get("height_cm") or details.get("height_cm", 0.0)
                profile["weight_kg"] = profile.get("weight_kg") or details.get("weight_kg", 0.0)
        picked.append(
            closest_player.build_profile(
                player_id=row["id"],
                name=row["name"],
                position=profile.get("position"),
                height_cm=profile.get("height_cm"),
                weight_kg=profile.get("weight_kg"),
                stat=profile,
            )
        )

    return picked


def _local_pool(db: Session, player) -> List[Dict[str, Any]]:
    """Záložní seznam kandidátů z hráčů, kteří už jsou v aplikaci."""
    pool: List[Dict[str, Any]] = []
    for other in db.query(Player).filter(Player.id != player.id).all():
        if not other.stats:
            continue
        other_stat = _get_target_stat(other, "career")
        if not other_stat.get("pts") and not other_stat.get("fga"):
            continue
        pool.append(
            closest_player.build_profile(
                player_id=other.id,
                name=other.full_name,
                position=other.position,
                height_cm=other.height_cm,
                weight_kg=other.weight_kg,
                stat=other_stat,
                awards_count=len(other.awards or []),
            )
        )
    return pool


@app.get("/api/players/{player_id}/closest")
def get_closest_player(
    player_id: int,
    refresh: bool = False,
    db: Session = Depends(get_db),
):
    """
    Nejbližší hráč podle basketbalové logiky (stejný archetyp a role,
    podobná kategorie dopadu). AI vybírá z předvybraných kandidátů a vrací
    top_3_candidates + tři porovnání: styl, fyzično, statistiky.

    Výsledek se ukládá do tabulky `closest_cache`, takže stejný hráč vrací
    vždy totéž. Parametr `refresh=true` cache přeskočí.
    """
    # Nejdřív databáze; když v ní hráč není, dotáhne se z NBA API.
    # Když je NBA API zrovna nedostupné a hráč v databázi je, počítá se dál.
    player = db.query(Player).filter(Player.id == player_id).first()
    if not player or not player.stats:
        player = fetch_and_cache_player(player_id=player_id, db=db)
    if player is not None:
        # ID z NBA musí mít správné jméno – data ze záložního zdroje mohla
        # pod stejné číslo uložit cizí hráče (ESPN má vlastní číselník).
        player = ensure_correct_name(player, db)
    if not player:
        raise HTTPException(status_code=404, detail="Hráč nebyl nalezen v databázi ani v NBA API.")

    player = closest_service.canonical_player(player, db)
    cache_key = f"closest:v{closest_player.ENGINE_VERSION}:{closest_service.advanced_cache.revision()}:{player.id}"

    # Stará cache z předchozí verze výpočtu se maže, aby se výsledky
    # přegenerovaly a nezůstaly v ní špatné shody.
    try:
        stale = (
            db.query(ClosestCache)
            .filter(ClosestCache.cache_key != cache_key)
            .filter(ClosestCache.player_id == player.id)
            .all()
        )
        for row in stale or []:
            db.delete(row)
        if stale:
            db.commit()
    except Exception as exc:  # pragma: no cover
        db.rollback()
        logger.warning("Starou cache nejbližšího hráče nešlo smazat: %s", exc)

    if not refresh:
        cached = (
            db.query(ClosestCache)
            .filter(ClosestCache.cache_key == cache_key)
            .first()
        )
        if cached:
            try:
                return json.loads(cached.payload)
            except Exception:
                db.delete(cached)
                db.commit()

    # Srovnává se vrcholná verze hráče (Prime), ne zkreslený kariérní
    # průměr. U hráčů, kteří během kariéry změnili styl, se navíc počítá
    # raná a pozdní fáze – viz services/career_phases.py.
    result = closest_service.build_closest_payload(player, db, nba_external.cached_comparison_rows())
    if not result:
        return {"closest": None, "reasoning": None, "breakdown": None}

    # doplnit data, která frontend zobrazuje (fotka, tým, tagy)
    match = db.query(Player).filter(Player.id == result["closest"]["id"]).first()
    closest_service._decorate(result, match, db)

    # stejná data i pro fáze kariéry
    for phase in result.get("career_phases") or []:
        phase_match = db.query(Player).filter(Player.id == phase["closest"]["id"]).first()
        closest_service._decorate(phase, phase_match, db)

    try:
        existing = (
            db.query(ClosestCache)
            .filter(ClosestCache.cache_key == cache_key)
            .first()
        )
        payload = json.dumps(result, ensure_ascii=False)
        if existing:
            existing.payload = payload
            existing.closest_id = result["closest"]["id"]
        else:
            db.add(
                ClosestCache(
                    cache_key=cache_key,
                    player_id=player.id,
                    closest_id=result["closest"]["id"],
                    payload=payload,
                )
            )
        db.commit()
    except Exception as exc:  # pragma: no cover
        db.rollback()
        logger.warning("Nejbližší hráč se nepodařilo uložit do cache: %s", exc)

    return result


_HEADSHOT_CACHE: Dict[int, tuple] = {}
_HEADSHOT_TTL = 24 * 3600


@app.get("/api/players/{player_id}/headshot")
def get_headshot(player_id: int, db: Session = Depends(get_db)):
    """
    Ověřená fotka hráče. Pořadí: 1) oficiální NBA CDN s přesným player_id,
    2) Basketball-Reference podle jména hráče z registru NBA,
    3) nic (frontend ukáže iniciály). Nikdy se nehledá „podobné" jméno.
    """
    import time
    import urllib.request

    now = time.time()
    hit = _HEADSHOT_CACHE.get(player_id)
    if hit and now - hit[0] < _HEADSHOT_TTL:
        return hit[1]

    def exists(url: str) -> bool:
        try:
            req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=6) as resp:
                ctype = str(resp.headers.get("Content-Type") or "")
                return resp.status == 200 and ctype.startswith("image")
        except Exception:
            return False

    result: Dict[str, Any] = {"url": "", "source": "none"}
    cdn = f"https://cdn.nba.com/headshots/nba/latest/1040x760/{player_id}.png"
    if exists(cdn):
        result = {"url": cdn, "source": "nba"}
    else:
        try:
            from services import nba_external
            from services.nba_fetcher import canonical_name

            name = canonical_name(player_id) or ""
            slug = nba_external.bbref_slug(name) if name else None
            if slug:
                url = f"https://www.basketball-reference.com/req/202106291/images/headshots/{slug}.jpg"
                if exists(url):
                    result = {"url": url, "source": "basketball-reference"}
        except Exception as exc:  # pragma: no cover
            logger.warning("Fotka %s z Basketball-Reference nešla: %s", player_id, exc)

    _HEADSHOT_CACHE[player_id] = (now, result)
    return result


@app.get("/api/players/{player_id}/last-game")
def get_last_game(player_id: int):
    """Return stats from the player's last played game using NBA API PlayerGameLog."""
    from services import source_switch

    if source_switch.espn_first():
        from services import espn_seasons

        fallback = espn_seasons.last_game(player_id)
        if fallback:
            return _json_safe(fallback)
        raise HTTPException(status_code=404, detail="Hráč nemá žádné záznamy o zápasech.")

    try:
        from nba_api.stats.endpoints import playergamelog
        from nba_api.stats.library.parameters import SeasonAll

        # Try current season first, then fall back to all seasons
        gl = playergamelog.PlayerGameLog(player_id=player_id, season=SeasonAll.all, timeout=12)
        df = gl.player_game_log.get_data_frame()

        if df is None or df.empty:
            raise HTTPException(status_code=404, detail="Hráč nemá žádné záznamy o zápasech.")

        # Most recent game is first row
        row = df.iloc[0]

        # Parse matchup "LAL vs. BOS" or "LAL @ BOS"
        matchup = str(row.get("MATCHUP", ""))
        is_home = "vs." in matchup
        teams = matchup.replace("vs.", "@").split("@")
        my_team = teams[0].strip() if teams else ""
        opp_team = teams[1].strip() if len(teams) > 1 else ""

        wl = str(row.get("WL", ""))
        pts = int(row.get("PTS", 0) or 0)
        reb = float(row.get("REB", 0.0) or 0.0)
        ast = float(row.get("AST", 0.0) or 0.0)
        stl = float(row.get("STL", 0.0) or 0.0)
        blk = float(row.get("BLK", 0.0) or 0.0)
        tov = float(row.get("TOV", 0.0) or 0.0)
        fgm = float(row.get("FGM", 0.0) or 0.0)
        fga = float(row.get("FGA", 0.0) or 0.0)
        fg3m = float(row.get("FG3M", 0.0) or 0.0)
        fg3a = float(row.get("FG3A", 0.0) or 0.0)
        ftm = float(row.get("FTM", 0.0) or 0.0)
        fta = float(row.get("FTA", 0.0) or 0.0)
        minutes = str(row.get("MIN", "0"))
        plus_minus = int(row.get("PLUS_MINUS", 0) or 0)
        game_date = str(row.get("GAME_DATE", ""))
        season_id = str(row.get("SEASON_ID", ""))

        fg_pct = round(fgm / fga, 3) if fga > 0 else 0.0
        fg3_pct = round(fg3m / fg3a, 3) if fg3a > 0 else 0.0
        ft_pct = round(ftm / fta, 3) if fta > 0 else 0.0

        return {
            "game_date": game_date,
            "season_id": season_id,
            "matchup": matchup,
            "my_team": my_team,
            "opp_team": opp_team,
            "is_home": is_home,
            "wl": wl,
            "minutes": minutes,
            "pts": pts,
            "reb": reb,
            "ast": ast,
            "stl": stl,
            "blk": blk,
            "tov": tov,
            "fgm": fgm,
            "fga": fga,
            "fg_pct": fg_pct,
            "fg3m": fg3m,
            "fg3a": fg3a,
            "fg3_pct": fg3_pct,
            "ftm": ftm,
            "fta": fta,
            "ft_pct": ft_pct,
            "plus_minus": plus_minus,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"Poslední zápas hráče {player_id} z NBA API nešel: {e} – zkouším ESPN")
        try:
            from services import espn_seasons

            fallback = espn_seasons.last_game(player_id)
            if fallback:
                return _json_safe(fallback)
        except Exception as exc:  # pragma: no cover
            logger.warning("ESPN poslední zápas %s selhal: %s", player_id, exc)
        raise HTTPException(status_code=503, detail="Nelze načíst data posledního zápasu z NBA API.")


class CompareRequest(BaseModel):
    p1_id: int
    p2_id: int
    season1: Optional[str] = "prime"
    season2: Optional[str] = "prime"


def _comparison_player(player_id, db):
    cached = db.get(Player, player_id)
    if cached is not None and cached.stats:
        return closest_service.canonical_player(cached, db)
    nba_id, name = advanced_cache.nba_id_for_espn(player_id)
    if nba_id is not None:
        alternate = db.get(Player, nba_id)
        if alternate is not None and alternate.stats and (
            nba_external.normalize_name(alternate.full_name) == nba_external.normalize_name(name)
        ):
            return alternate
    player = fetch_and_cache_player(player_id, db)
    return closest_service.canonical_player(player, db) if player is not None else None


_PHASE_LABELS = {"prime": "Vrchol kariéry", "early": "Raná kariéra", "late": "Pozdní kariéra"}


def _comparison_options(player):
    rows, _, phases = closest_service.phase_metadata(player)
    return ([{"id": "prime", "label": _PHASE_LABELS["prime"]}]
            + [{"id": p["key"], "label": p["label"]} for p in phases["phases"]]
            + [{"id": "career", "label": "Celá kariéra (průměr)"}]
            + [{"id": row["season_id"], "label": row["season_id"]} for row in rows])


def _get_target_stat(player: Player, season_id: Optional[str]) -> Dict[str, Any]:
    """Helper to get stats for comparison (either career average or specific season)."""
    if season_id in _PHASE_LABELS:
        _, _, phases = closest_service.phase_metadata(player)
        phase = phases["prime"] if season_id == "prime" else next(
            (p for p in phases["phases"] if p["key"] == season_id), None)
        if phase:
            stat = phase["stat"]
            ratio = lambda a, b: stat[a] / stat[b] if stat.get(a) is not None and stat.get(b) else None
            from services.defense import per100
            return {**stat, "season_id": season_id, "fg_pct": ratio("fgm", "fga"),
                    "fg3_pct": ratio("fg3m", "fg3a"), "ft_pct": ratio("ftm", "fta"),
                    **{f"poss100_{key}": per100(stat.get(key), stat.get("min_per_game"), phase["season"])
                       for key in ("pts", "reb", "ast", "stl", "blk", "tov")}}
    if season_id and season_id != "career":
        for s in player.stats:
            if s.season_id == season_id:
                return {
                    "season_id": s.season_id,
                    "pts": s.pts,
                    "reb": s.reb,
                    "ast": s.ast,
                    "stl": s.stl,
                    "blk": s.blk,
                    "tov": s.tov,
                    "fg_pct": s.fg_pct,
                    "fg3_pct": s.fg3_pct,
                    "ft_pct": s.ft_pct,
                    "fga": s.fga,
                    "fg3a": s.fg3a,
                    "fg3m": s.fg3m,
                    "fta": s.fta,
                    "poss100_pts": s.poss100_pts,
                    "poss100_reb": s.poss100_reb,
                    "poss100_ast": s.poss100_ast,
                    "poss100_stl": s.poss100_stl,
                    "poss100_blk": s.poss100_blk,
                    "poss100_tov": s.poss100_tov,
                    "min_per_game": s.min_per_game,
                }

    # Default to career average
    stats = player.stats
    total_gp = sum(s.gp or 0 for s in stats)
    if total_gp == 0:
        return {"season_id": "career", "pts": 0, "reb": 0, "ast": 0, "stl": 0, "blk": 0, "tov": 0, "fg_pct": 0, "fg3_pct": 0, "ft_pct": 0, "fga": 0, "fg3a": 0, "fg3m": 0, "fta": 0, "poss100_pts": 0, "poss100_reb": 0, "poss100_ast": 0, "poss100_stl": 0, "poss100_blk": 0, "poss100_tov": 0}

    fields = ("pts", "reb", "ast", "stl", "blk", "tov", "fg_pct", "fg3_pct", "ft_pct", "fga", "fg3a",
              "fg3m", "fta", "poss100_pts", "poss100_reb", "poss100_ast", "poss100_stl", "poss100_blk",
              "poss100_tov", "min_per_game")
    result = {"season_id": "Kariéra"}
    for field in fields:
        values = [(getattr(s, field), s.gp) for s in stats if s.gp and getattr(s, field) is not None]
        result[field] = round(sum(v * n for v, n in values) / sum(n for _, n in values), 3) if values else 0
    return result


@app.post("/api/compare")
def compare_two_players(req: CompareRequest, db: Session = Depends(get_db)):
    """
    Compare two NBA players using scikit-learn Similarity Engine,
    generating total %, sub-metrics, radar overlay and Czech AI verdict.
    """
    p1 = _comparison_player(req.p1_id, db)
    p2 = _comparison_player(req.p2_id, db)

    if not p1 or not p2:
        raise HTTPException(status_code=404, detail="Jeden nebo oba hráči nebyli nalezeni.")

    s1_key = req.season1 or "prime"
    s2_key = req.season2 or "prime"
    stat1 = _get_target_stat(p1, s1_key)
    stat2 = _get_target_stat(p2, s2_key)

    tags1 = json.loads(p1.playstyle_tags) if p1.playstyle_tags else []
    tags2 = json.loads(p2.playstyle_tags) if p2.playstyle_tags else []

    p1_info = {
        "id": p1.id,
        "name": p1.full_name,
        "position": p1.position,
        "height_cm": p1.height_cm,
        "weight_kg": p1.weight_kg,
        "headshot_url": p1.headshot_url,
        "tags": tags1,
        "pts": stat1.get("pts", 0),
        "reb": stat1.get("reb", 0),
        "ast": stat1.get("ast", 0),
    }

    p2_info = {
        "id": p2.id,
        "name": p2.full_name,
        "position": p2.position,
        "height_cm": p2.height_cm,
        "weight_kg": p2.weight_kg,
        "headshot_url": p2.headshot_url,
        "tags": tags2,
        "pts": stat2.get("pts", 0),
        "reb": stat2.get("reb", 0),
        "ast": stat2.get("ast", 0),
    }

    # Stejný model, jaký používá „nejbližší hráč" na hlavní stránce.
    # Když je vybraná sezóna, počítá se stejnými parametry, ale z čísel
    # té sezóny (viz _seasonal_comparison).
    unified = _unified_comparison(p1, p2, s1_key, s2_key)
    for info, profile in ((p1_info, unified["_p1"]), (p2_info, unified["_p2"])):
        info["height_cm"] = profile["listed_height_cm"]
        info["weight_kg"] = profile["listed_weight_kg"]

    # Tabulka a popisky potřebují podíly bodů z trojek a šestek – ty jsou
    # jen v kariérním profilu z externího zdroje. Bez nich tabulka ukazovala
    # nuly (Jordan „0 % bodů z trojek", což nedávalo smysl).
    if unified and unified.get("_p1") and unified.get("_p2"):
        stat1["three_pts_share"] = unified["_p1"].get("three_pts_share", 0.0)
        stat1["ft_pts_share"] = unified["_p1"].get("ft_pts_share", 0.0)
        stat1["two_rate"] = unified["_p1"].get("two_rate", 0.0)
        stat2["three_pts_share"] = unified["_p2"].get("three_pts_share", 0.0)
        stat2["ft_pts_share"] = unified["_p2"].get("ft_pts_share", 0.0)
        stat2["two_rate"] = unified["_p2"].get("two_rate", 0.0)

    comp_results = compare_players(
        p1_info=p1_info,
        p1_stat=stat1,
        p2_info=p2_info,
        p2_stat=stat2,
        unified=unified,
    )

    ai_verdict = unified.get("style_note") or "Shoda vychází z dostupných statistik a herního stylu."

    return {
        "player1": {
            "id": p1.id,
            "full_name": p1.full_name,
            "position": p1.position,
            "height_cm": p1_info["height_cm"],
            "weight_kg": p1_info["weight_kg"],
            "headshot_url": p1.headshot_url,
            "selected_season": stat1["season_id"],
            "stat": stat1,
            "available_seasons": _comparison_options(p1)
        },
        "player2": {
            "id": p2.id,
            "full_name": p2.full_name,
            "position": p2.position,
            "height_cm": p2_info["height_cm"],
            "weight_kg": p2_info["weight_kg"],
            "headshot_url": p2.headshot_url,
            "selected_season": stat2["season_id"],
            "stat": stat2,
            "available_seasons": _comparison_options(p2)
        },
        "match_pct": comp_results["match_pct"],
        "physical_pct": comp_results["physical_pct"],
        "statistical_pct": comp_results["statistical_pct"],
        "stylistic_pct": comp_results["stylistic_pct"],
        # Stejná čísla, jaká ukazuje hlavní stránka u „nejbližšího hráče"
        "unified_engine_version": closest_player.ENGINE_VERSION,
        "style": _unified_payload(p1, p2, unified),
        "radar": comp_results["radar"],
        "table": comp_results["table"],
        "ai_verdict": ai_verdict
    }


def _unified_payload(
    p1: Player, p2: Player, pair: Optional[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    if not pair:
        return None
    profile1 = pair.get("_p1") or {}
    profile2 = pair.get("_p2") or {}
    return {
        "engine_version": closest_player.ENGINE_VERSION,
        **{k: v for k, v in pair.items() if not k.startswith("_")},
        "player1": {
            "id": p1.id,
            "full_name": p1.full_name,
            "headshot_url": p1.headshot_url,
            "archetype": profile1.get("archetype_label", ""),
            "position": profile1.get("position_label", ""),
        },
        "player2": {
            "id": p2.id,
            "full_name": p2.full_name,
            "headshot_url": p2.headshot_url,
            "archetype": profile2.get("archetype_label", ""),
            "position": profile2.get("position_label", ""),
        },
    }


def _unified_comparison(p1, p2, season1=None, season2=None):
    key1, key2 = season1 or "prime", season2 or "prime"
    a, b = closest_service.phase_for_player(p1, key1), closest_service.phase_for_player(p2, key2)
    if a is None or b is None:
        raise HTTPException(status_code=422, detail="Pro vybranou fázi nebo sezónu nejsou dostupné statistiky.")
    if closest_player.same_player(a, b):
        raise HTTPException(status_code=422, detail="Hráče nelze porovnat se sebou samým.")
    return {**closest_player.compare_pair(a, b), "phase1": key1, "phase2": key2,
            "season_mode": key1 not in (*_PHASE_LABELS, "career") or key2 not in (*_PHASE_LABELS, "career")}


def _season_stat(player: Player, season: str) -> Dict[str, Any]:
    """Čísla jedné sezóny ve stejném tvaru, jaký bere model."""
    row = next((s for s in player.stats if s.season_id == season), None)
    if not row:
        return _get_target_stat(player, "career")
    return {
        "pts": row.pts or 0.0,
        "reb": row.reb or 0.0,
        "ast": row.ast or 0.0,
        "stl": row.stl or 0.0,
        "blk": row.blk or 0.0,
        "tov": row.tov or 0.0,
        "fgm": row.fgm or 0.0,
        "fga": row.fga or 0.0,
        "fg3m": row.fg3m or 0.0,
        "fg3a": row.fg3a or 0.0,
        "ftm": row.ftm or 0.0,
        "fta": row.fta or 0.0,
        "fg_pct": row.fg_pct or 0.0,
        "fg3_pct": row.fg3_pct or 0.0,
        "ft_pct": row.ft_pct or 0.0,
        "min_per_game": row.min_per_game or 32.0,
    }


@app.post("/api/compare/style")
def compare_players_style(req: CompareRequest, db: Session = Depends(get_db)):
    """
    Porovnání dvou hráčů stejnou logikou, jakou používá „nejbližší hráč"
    na hlavní stránce: archetyp, konkrétní pozice, odkud hráč skóruje,
    postava a statistiky. Díky tomu stejná dvojice nikdy neukáže dvě
    různá procenta na dvou místech aplikace.
    """
    p1 = _comparison_player(req.p1_id, db)
    p2 = _comparison_player(req.p2_id, db)
    if not p1 or not p2:
        raise HTTPException(status_code=404, detail="Jeden nebo oba hráči nebyli nalezeni.")

    return _unified_payload(p1, p2, _unified_comparison(p1, p2, req.season1, req.season2))

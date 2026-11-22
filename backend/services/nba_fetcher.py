import json
import logging
import re
import time
import requests
from typing import Dict, List, Any, Optional
from sqlalchemy.orm import Session

from models import Player, PlayerSeasonStat, PlayerAward
from services.ai_scout import generate_scouting_report

logger = logging.getLogger(__name__)

AWARD_TRANSLATIONS = {
    "nba champion": "Šampion NBA",
    "nba most valuable player": "Nejužitečnější hráč ligy (MVP)",
    "nba finals most valuable player": "MVP Finále NBA",
    "nba all-star": "Účast v NBA All-Star",
    "nba defensive player of the year": "Obránce roku (DPOY)",
    "nba rookie of the year": "Nováček roku (ROY)",
    "nba sixth man of the year": "Nejlepší šestý hráč (6MOY)",
    "nba most improved player": "Hráč s největším zlepšením (MIP)",
    "all-nba": "Člen All-NBA týmu",
    "all-defensive": "Člen All-Defensive týmu",
    "all-rookie": "Člen All-Rookie týmu",
    "hall of fame": "Síň slávy (Hall of Fame)",
    "olympic gold medal": "Zlatá olympijská medaile",
    "olympic silver medal": "Stříbrná olympijská medaile",
    "olympic bronze medal": "Bronzová olympijská medaile",
    "nba scoring champion": "Nejlepší střelec sezóny",
    "nba assists leader": "Lídr asistencí sezóny",
    "nba rebounds leader": "Lídr doskoků sezóny",
    "nba blocks leader": "Lídr bloků sezóny",
    "nba steals leader": "Lídr zisků sezóny",
}

def translate_award(description: str) -> str:
    desc_lower = (description or "").lower()
    for eng, cze in AWARD_TRANSLATIONS.items():
        if eng in desc_lower:
            return cze
    return description or "Oficiální ocenění NBA"


def parse_height_to_cm(height_str: Optional[str]) -> Optional[float]:
    if not height_str:
        return None
    # e.g. "6-6" or "6'6\""
    match = re.search(r"(\d+)[\'-](\d+)", height_str)
    if match:
        feet = int(match.group(1))
        inches = int(match.group(2))
        return round(feet * 30.48 + inches * 2.54, 1)
    try:
        return float(height_str)
    except Exception:
        return None


def parse_weight_to_kg(weight_lbs: Optional[float]) -> Optional[float]:
    """
    Váha v librách na kilogramy. NBA API u starších hráčů posílá místo
    čísla mezeru nebo prázdný text – taková hodnota se bere jako neznámá,
    ne jako chyba, která by shodila celý profil.
    """
    if weight_lbs is None:
        return None
    try:
        value = float(str(weight_lbs).strip())
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    return round(value * 0.45359237, 1)


def parse_weight_lbs(weight_raw: Any) -> Optional[float]:
    """Váha v librách jako číslo (nebo None, když ji API neposlalo)."""
    if weight_raw is None:
        return None
    try:
        value = float(str(weight_raw).strip())
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def fetch_wikipedia_summary(player_name: str) -> str:
    """Fetch Wikipedia summary in Czech, fallback to English or default."""
    try:
        headers = {"User-Agent": "NBANerdVault/1.0 (contact@nbanerdvault.local)"}
        # First try Czech Wikipedia
        url_cs = f"https://cs.wikipedia.org/api/rest_v1/page/summary/{requests.utils.quote(player_name)}"
        res_cs = requests.get(url_cs, headers=headers, timeout=4)
        if res_cs.status_code == 200:
            data = res_cs.json()
            extract = data.get("extract")
            if extract and len(extract) > 40:
                return extract
        
        # Fallback to English Wikipedia
        url_en = f"https://en.wikipedia.org/api/rest_v1/page/summary/{requests.utils.quote(player_name)}"
        res_en = requests.get(url_en, headers=headers, timeout=4)
        if res_en.status_code == 200:
            data = res_en.json()
            extract = data.get("extract")
            if extract:
                return extract
    except Exception as e:
        logger.warning(f"Chyba při stahování Wikipedia sumáře pro {player_name}: {e}")
    
    return f"{player_name} je významná osobnost a basketbalista americké soutěže NBA, proslulý svými výkony na hřišti."


def calculate_playstyle_tags(career_stats: List[Dict[str, Any]], position: Optional[str]) -> List[str]:
    """Calculate rule-based playstyle tags in Czech based on career statistics."""
    if not career_stats:
        return ["Všestranný basketbalista", "Týmový hráč"]
    
    # Calculate career totals & weighted averages
    total_gp = sum(s.get("gp", 0) for s in career_stats)
    if total_gp == 0:
        return ["Mladý talent", "Hráč v rotaci"]
    
    def _safe(row: Dict[str, Any], field: str) -> float:
        """
        Hodnota sezóny pro součty. Starší sezóny některé statistiky nemají
        (zisky a bloky až od 70. let) – počítá se s nulou, ne s None,
        jinak by výpočet tagů spadl a hráč by se vůbec nenačetl.
        """
        value = row.get(field)
        if value is None or value != value:  # None nebo NaN
            return 0.0
        return float(value)

    def _total(field: str) -> float:
        return sum(
            _safe(row, field) * int(row.get("gp") or 0) for row in career_stats
        )

    def _weighted(field: str) -> float:
        return _total(field) / total_gp

    avg_pts = _weighted("pts")
    avg_reb = _weighted("reb")
    avg_ast = _weighted("ast")
    avg_stl = _weighted("stl")
    avg_blk = _weighted("blk")

    total_fga = _total("fga")
    total_fgm = _total("fgm")
    fg_pct = (total_fgm / total_fga) if total_fga > 0 else 0.0

    total_fg3a = _total("fg3a")
    total_fg3m = _total("fg3m")
    fg3_pct = (total_fg3m / total_fg3a) if total_fg3a > 0 else 0.0

    total_fta = _total("fta")
    total_ftm = _total("ftm")
    ft_pct = (total_ftm / total_fta) if total_fta > 0 else 0.0

    tags = []

    # Scoring tags
    if avg_pts >= 26.0:
        tags.append("Generální skórer (26+ PPG)")
    elif avg_pts >= 20.0:
        tags.append("Elitní zakončovatel (20+ PPG)")
    elif avg_pts >= 15.0:
        tags.append("Spolehlivý střelec")

    # 3-point tags
    if fg3_pct >= 0.38 and (total_fg3a / total_gp) >= 3.0:
        tags.append("Smrtící sniper za 3B (38%+)")
    elif (total_fg3a / total_gp) >= 5.0:
        tags.append("Objemový trojkař")
    elif total_fg3a / max(total_fga, 1) < 0.05 and avg_pts >= 15:
        tags.append("Mistr střední vzdálenosti & podkošové hry")

    # Playmaking tags
    if avg_ast >= 8.0:
        tags.append("Elitní Floor General (8+ APG)")
    elif avg_ast >= 5.5:
        tags.append("Kreativní tvůrce hry")
    
    # Rebounding tags
    if avg_reb >= 11.0:
        tags.append("Monstrum na doskoku (11+ RPG)")
    elif avg_reb >= 7.5:
        tags.append("Silový doskakovač")

    # Defensive tags
    if avg_blk >= 2.0:
        tags.append("Neprostupný štít pod košem (2+ BPG)")
    elif avg_blk >= 1.2:
        tags.append("Spolehlivý blokař")

    if avg_stl >= 1.8:
        tags.append("Lockdown zloděj míčů (1.8+ SPG)")
    elif avg_stl >= 1.3:
        tags.append("Agresivní obrana na perimetru")

    # Efficiency tags
    if fg_pct >= 0.54:
        tags.append("Mimořádně efektivní zakončení (54%+ FG)")
    if ft_pct >= 0.86:
        tags.append("Chladnokrevný exekutor šestek (86%+ FT)")

    # Versatility tags
    if avg_pts >= 18 and avg_reb >= 6 and avg_ast >= 5:
        tags.append("Komplexní All-Around mašina")

    # Position specific
    pos = (position or "").upper()
    if "C" in pos and avg_blk >= 1.5:
        tags.append("Kotva týmové defenzívy")
    if "F" in pos and avg_ast >= 4.5:
        tags.append("Moderní Point Forward")

    if not tags:
        tags = ["Zkušený veterán NBA", "Všestranný hráč"]

    return tags[:6]


def get_static_players_list() -> List[Dict[str, Any]]:
    """Return static list of all NBA players from nba_api with error fallback."""
    try:
        from nba_api.stats.static import players
        all_players = players.get_players()
        return all_players
    except Exception as e:
        logger.error(f"Nelze načíst static players z nba_api: {e}")
        # Fallback list of top famous players
        return [
            {"id": 893, "full_name": "Michael Jordan", "is_active": False},
            {"id": 2544, "full_name": "LeBron James", "is_active": True},
            {"id": 977, "full_name": "Kobe Bryant", "is_active": False},
            {"id": 406, "full_name": "Shaquille O'Neal", "is_active": False},
            {"id": 201939, "full_name": "Stephen Curry", "is_active": True},
            {"id": 77142, "full_name": "Magic Johnson", "is_active": False},
            {"id": 1449, "full_name": "Larry Bird", "is_active": False},
            {"id": 76003, "full_name": "Kareem Abdul-Jabbar", "is_active": False},
            {"id": 1495, "full_name": "Tim Duncan", "is_active": False},
            {"id": 201142, "full_name": "Kevin Durant", "is_active": True},
            {"id": 203507, "full_name": "Giannis Antetokounmpo", "is_active": True},
            {"id": 203999, "full_name": "Nikola Jokic", "is_active": True},
            {"id": 1629029, "full_name": "Luka Doncic", "is_active": True},
        ]


def search_players_service(query: str, db: Session, limit: int = 15) -> List[Dict[str, Any]]:
    """Search players in SQLite cache first, then in nba_api static registry."""
    clean_query = query.strip().lower()
    if not clean_query:
        # Return popular seeded players
        db_popular = db.query(Player).order_by(Player.full_name).limit(limit).all()
        return [{"id": p.id, "full_name": p.full_name, "is_active": p.is_active, "in_db": True} for p in db_popular]

    results = []
    seen_ids = set()

    # 1. Search in local SQLite database
    db_matches = db.query(Player).filter(Player.full_name.ilike(f"%{clean_query}%")).limit(limit).all()
    for p in db_matches:
        results.append({
            "id": p.id,
            "full_name": p.full_name,
            "is_active": p.is_active,
            "in_db": True,
            "position": p.position,
            "headshot_url": p.headshot_url
        })
        seen_ids.add(p.id)

    # 2. Search static registry
    static_players = get_static_players_list()
    for sp in static_players:
        if clean_query in sp["full_name"].lower():
            if sp["id"] not in seen_ids:
                results.append({
                    "id": sp["id"],
                    "full_name": sp["full_name"],
                    "is_active": sp.get("is_active", False),
                    "in_db": False,
                    "position": "",
                    "headshot_url": f"https://cdn.nba.com/headshots/nba/latest/1040x760/{sp['id']}.png"
                })
                seen_ids.add(sp["id"])
        if len(results) >= limit:
            break

    return results


def _career_frame(player_id: int, attempts: int = 3):
    """
    Sezónní tabulka kariéry z NBA API.

    stats.nba.com občas nevrátí data vůbec (odpověď bez tabulky) – hlavně
    u hráčů, kteří už dávno skončili. Bez opakování pak profil vypadá, že
    hráč neexistuje (Bill Walton). Proto se to zkouší víckrát a nakonec
    se sáhne po Basketball-Reference.
    """
    # Import až tady: kdyby nba_api nebyl nainstalovaný nebo selhal při
    # importu, profil se pořád dotáhne z Basketball-Reference.
    from nba_api.stats.endpoints import playercareerstats

    last_error: Optional[Exception] = None
    for attempt in range(attempts):
        try:
            endpoint = playercareerstats.PlayerCareerStats(
                player_id=player_id, per_mode36="PerGame", timeout=12
            )
            frame = endpoint.season_totals_regular_season.get_data_frame()
            if frame is not None and not frame.empty:
                return frame
        except Exception as exc:  # pragma: no cover
            last_error = exc
            time.sleep(1.2 * (attempt + 1))

    if last_error:
        logger.warning("Kariérní tabulka %s z NBA API nešla: %s", player_id, last_error)
    return _career_frame_bbref(player_id)


def _career_frame_bbref(player_id: int):
    """Záložní zdroj sezón: Basketball-Reference (stejné sloupce jako NBA)."""
    try:
        import pandas as pd

        from . import nba_external

        rows = nba_external.bbref_season_rows(player_id)
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows)
    except Exception as exc:  # pragma: no cover
        logger.warning("Záložní sezóny pro %s selhaly: %s", player_id, exc)
        return pd.DataFrame()


def _career_rows(frame) -> List[Dict[str, Any]]:
    """
    Ze sezónní tabulky udělá jeden řádek na sezónu.
    Když hráč v sezóně střídal týmy, NBA API dává víc řádků – použije se
    ten souhrnný (TEAM_ID 0), jinak by se zápasy počítaly víckrát.
    """
    rows = frame.to_dict("records")
    by_season: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        season = str(row.get("SEASON_ID") or "")
        if not season:
            continue
        team_id = row.get("TEAM_ID")
        previous = by_season.get(season)
        if previous is None:
            by_season[season] = row
        elif team_id == 0 or (previous.get("TEAM_ID") != 0 and (row.get("GP") or 0) > (previous.get("GP") or 0)):
            by_season[season] = row
    return [by_season[k] for k in sorted(by_season)]


def _seasons_from(season_id: str) -> int:
    """Kolik sezón uplynulo od zadané sezóny (2024-25 -> 2 pro 2026-27)."""
    try:
        start = int(str(season_id)[:4])
    except (TypeError, ValueError):
        return 99
    from datetime import date

    today = date.today()
    current = today.year if today.month >= 7 else today.year - 1
    return max(current - start, 0)


def fetch_and_cache_player(player_id: int, db: Session) -> Optional[Player]:
    """Load player from SQLite database. If missing, fetch from NBA API and cache."""
    # Check cache first
    existing = db.query(Player).filter(Player.id == player_id).first()
    if existing and existing.stats:
        # Data se musí obnovit jen tehdy, když v databázi chybí konec
        # kariéry (např. 15 z 22 sezón). Jinak se nic nestahuje.
        newest = max((s.season_id for s in existing.stats), default="")
        seasons = len(existing.stats)
        complete = seasons >= 8 and _seasons_from(newest) <= 2
        if complete:
            return existing
        # Neúplný záznam (málo sezón) se dotáhne jen jednou za 12 hodin,
        # aby se při výpadku NBA API nezkoušel při každém kliknutí.
        from datetime import datetime, timedelta

        updated = getattr(existing, "updated_at", None)
        if updated and (datetime.utcnow() - updated) < timedelta(hours=12) and seasons >= 3:
            return existing
        logger.info(
            "Obnovuji data hráče %s (%s sezón, poslední %s)", player_id, seasons, newest
        )

    try:
        from nba_api.stats.endpoints import commonplayerinfo, playercareerstats, playerawards

        # 1. Player Info
        # NBA API občas odpoví chybovou odpovědí bez dat – zkusí se to víckrát,
        # než se hráč prohlásí za neexistujícího.
        info_df = None
        last_error: Optional[Exception] = None
        for attempt in range(3):
            try:
                info_endpoint = commonplayerinfo.CommonPlayerInfo(player_id=player_id, timeout=12)
                info_df = info_endpoint.common_player_info.get_data_frame()
                if info_df is not None and not info_df.empty:
                    break
            except Exception as exc:  # pragma: no cover
                last_error = exc
                time.sleep(1.5 * (attempt + 1))

        if info_df is None or info_df.empty:
            logger.error(
                "Hráč %s nebyl nalezen v CommonPlayerInfo (%s).", player_id, last_error or "prázdná odpověď"
            )
            return existing

        row = info_df.iloc[0]
        full_name = str(row.get("DISPLAY_FIRST_LAST") or f"Hráč {player_id}")
        first_name = str(row.get("FIRST_NAME") or "")
        last_name = str(row.get("LAST_NAME") or "")
        height_raw = str(row.get("HEIGHT") or "")
        weight_raw = row.get("WEIGHT")
        height_cm = parse_height_to_cm(height_raw)
        weight_kg = parse_weight_to_kg(weight_raw)
        position = str(row.get("POSITION") or "")
        is_active = (str(row.get("ROSTERSTATUS", "")).lower() == "active")

        draft_year = str(row.get("DRAFT_YEAR") or "Undrafted")
        draft_round = str(row.get("DRAFT_ROUND") or "-")
        draft_number = str(row.get("DRAFT_NUMBER") or "-")
        draft_team = ""  # Often filled in info or left clean
        college = str(row.get("SCHOOL") or "-")
        country = str(row.get("COUNTRY") or "USA")
        headshot_url = f"https://cdn.nba.com/headshots/nba/latest/1040x760/{player_id}.png"

        # 2. Career Stats
        career_df = _career_frame(player_id)

        stats_list = []
        parsed_season_stats = []

        if not career_df.empty:
            # Když hráč v sezóně vystřídal týmy, NBA API vrací řádek za každý
            # tým plus součet (TEAM_ID 0). Bere se jen součet, jinak by se
            # zápasy počítaly dvakrát.
            career_rows = _career_rows(career_df)
            for s_row in career_rows:
                gp = int(s_row.get("GP") or 0)
                if gp == 0:
                    continue

                def _val(key: str) -> float:
                    """
                    Hodnota ze sezóny. Starší sezóny zisky a bloky vůbec
                    neměly – NBA je začala měřit až v 70. letech. Taková
                    sezóna musí zůstat prázdná (None), ne nula, aby se
                    nezkreslil průměr ani porovnání stylu.
                    """
                    raw = s_row.get(key)
                    if raw is None or raw == "":
                        return None
                    try:
                        number = float(raw)
                    except (TypeError, ValueError):
                        return None
                    if number != number:  # NaN
                        return None
                    return number

                min_pg = _val("MIN") or 0.0
                pts_pg = _val("PTS") or 0.0
                reb_pg = _val("REB") or 0.0
                ast_pg = _val("AST") or 0.0
                stl_pg = _val("STL")
                blk_pg = _val("BLK")
                tov_pg = _val("TOV")
                pf_pg = _val("PF")

                fgm = _val("FGM") or 0.0
                fga = _val("FGA") or 0.0
                fg_pct = _val("FG_PCT")
                fg3m = _val("FG3M") or 0.0
                fg3a = _val("FG3A") or 0.0
                fg3_pct = _val("FG3_PCT")
                ftm = _val("FTM") or 0.0
                fta = _val("FTA") or 0.0
                ft_pct = _val("FT_PCT")

                def _r(value, decimals: int = 1):
                    return None if value is None else round(value, decimals)

                # Estimate Per 100 Possessions (standard league pace factor ~98-100)
                poss_mult = (48.0 / max(min_pg, 1.0)) * (100.0 / 98.0) if min_pg > 0 else 1.0

                stat_item = {
                    "season_id": str(s_row.get("SEASON_ID")),
                    "team_abbreviation": str(s_row.get("TEAM_ABBREVIATION") or ""),
                    "player_age": int(s_row.get("PLAYER_AGE") or 0),
                    "gp": gp,
                    "gs": int(s_row.get("GS") or 0),
                    "min_per_game": round(min_pg, 1),
                    "pts": round(pts_pg, 1),
                    "reb": round(reb_pg, 1),
                    "ast": round(ast_pg, 1),
                    "stl": _r(stl_pg),
                    "blk": _r(blk_pg),
                    "tov": _r(tov_pg),
                    "pf": _r(pf_pg),
                    "fgm": round(fgm, 1),
                    "fga": round(fga, 1),
                    "fg_pct": _r(fg_pct, 3),
                    "fg3m": round(fg3m, 1),
                    "fg3a": round(fg3a, 1),
                    "fg3_pct": _r(fg3_pct, 3),
                    "ftm": round(ftm, 1),
                    "fta": round(fta, 1),
                    "ft_pct": _r(ft_pct, 3),
                    "poss100_pts": round(pts_pg * poss_mult, 1),
                    "poss100_reb": round(reb_pg * poss_mult, 1),
                    "poss100_ast": round(ast_pg * poss_mult, 1),
                    "poss100_stl": None if stl_pg is None else round(stl_pg * poss_mult, 1),
                    "poss100_blk": None if blk_pg is None else round(blk_pg * poss_mult, 1),
                    "poss100_tov": None if tov_pg is None else round(tov_pg * poss_mult, 1),
                }
                parsed_season_stats.append(stat_item)

        # 3. Player Awards
        awards_list = []
        try:
            awards_endpoint = playerawards.PlayerAwards(player_id=player_id, timeout=10)
            awards_df = awards_endpoint.player_awards.get_data_frame()
            if not awards_df.empty:
                # Group awards by description to summarize
                grouped: Dict[str, Dict[str, Any]] = {}
                for _, a_row in awards_df.iterrows():
                    desc = str(a_row.get("DESCRIPTION") or "").strip()
                    if not desc:
                        continue
                    season = str(a_row.get("SEASON") or "")
                    if desc not in grouped:
                        grouped[desc] = {
                            "description": desc,
                            "description_cs": translate_award(desc),
                            "count": 1,
                            "seasons": [season] if season else []
                        }
                    else:
                        grouped[desc]["count"] += 1
                        if season:
                            grouped[desc]["seasons"].append(season)

                for g in grouped.values():
                    awards_list.append({
                        "description": g["description"],
                        "description_cs": g["description_cs"],
                        "count": g["count"],
                        "season": ", ".join(g["seasons"][:3])
                    })
        except Exception as e:
            logger.warning(f"Nelze stáhnout trofeje pro hráče {player_id}: {e}")

        # 4. Wikipedia summary & Playstyle Tags
        bio_summary = (existing.bio_summary if existing else "") or fetch_wikipedia_summary(full_name)
        playstyle_tags = calculate_playstyle_tags(parsed_season_stats, position)

        # 5. 3-Sentence AI Scouting Report in Czech
        #    (u známého hráče se nepočítá znovu, jen se doplní, když chybí)
        scouting_report = (existing.scouting_report if existing else "") or generate_scouting_report(
            full_name=full_name,
            position=position,
            height_cm=height_cm,
            stats=parsed_season_stats,
            awards=[a["description_cs"] for a in awards_list],
            tags=playstyle_tags
        )

        # 6. Save to SQLite database
        player_obj = existing or Player(id=player_id)
        player_obj.full_name = full_name
        player_obj.first_name = first_name
        player_obj.last_name = last_name
        player_obj.is_active = is_active
        player_obj.headshot_url = headshot_url
        player_obj.height_cm = height_cm
        player_obj.height_ft = height_raw
        player_obj.weight_kg = weight_kg
        player_obj.weight_lbs = parse_weight_lbs(weight_raw)
        player_obj.position = position
        player_obj.draft_year = draft_year
        player_obj.draft_round = draft_round
        player_obj.draft_number = draft_number
        player_obj.draft_team = draft_team
        player_obj.college = college
        player_obj.country = country
        player_obj.bio_summary = bio_summary
        player_obj.scouting_report = scouting_report
        player_obj.playstyle_tags = json.dumps(playstyle_tags, ensure_ascii=False)

        if not existing:
            db.add(player_obj)
        db.flush()

        # Delete existing stats & awards if updating
        db.query(PlayerSeasonStat).filter(PlayerSeasonStat.player_id == player_id).delete()
        db.query(PlayerAward).filter(PlayerAward.player_id == player_id).delete()

        # Add season stats
        for s in parsed_season_stats:
            stat_model = PlayerSeasonStat(
                player_id=player_id,
                season_id=s["season_id"],
                team_abbreviation=s["team_abbreviation"],
                player_age=s["player_age"],
                gp=s["gp"],
                gs=s["gs"],
                min_per_game=s["min_per_game"],
                pts=s["pts"],
                reb=s["reb"],
                ast=s["ast"],
                stl=s["stl"],
                blk=s["blk"],
                tov=s["tov"],
                pf=s["pf"],
                fgm=s["fgm"],
                fga=s["fga"],
                fg_pct=s["fg_pct"],
                fg3m=s["fg3m"],
                fg3a=s["fg3a"],
                fg3_pct=s["fg3_pct"],
                ftm=s["ftm"],
                fta=s["fta"],
                ft_pct=s["ft_pct"],
                poss100_pts=s["poss100_pts"],
                poss100_reb=s["poss100_reb"],
                poss100_ast=s["poss100_ast"],
                poss100_stl=s["poss100_stl"],
                poss100_blk=s["poss100_blk"],
                poss100_tov=s["poss100_tov"],
            )
            db.add(stat_model)

        # Add awards
        for a in awards_list:
            award_model = PlayerAward(
                player_id=player_id,
                description=a["description"],
                description_cs=a["description_cs"],
                count=a["count"],
                season=a.get("season", "")
            )
            db.add(award_model)

        db.commit()
        db.refresh(player_obj)
        return player_obj

    except Exception as e:
        db.rollback()
        logger.error(f"Kritická chyba při stahování dat hráče {player_id}: {e}", exc_info=True)
        return existing

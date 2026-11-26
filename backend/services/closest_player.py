"""
Nejbližší hráč – výběr podle basketbalové logiky, ne podle matematických vah.

Jak to funguje:

1. **Kandidáti.** Hráči se berou z externích zdrojů (NBA API,
   Basketball-Reference) – žádná vlastní databáze. Z nich se vyberou ti,
   kteří hrají stejnou roli (rozehrávač / křídlo / podkošový), jsou
   podobně vysocí a patří do podobné kategorie (superstar, all-star,
   role player). Tohle je jen předvýběr, aby AI nedostala celý seznam
   bez kontextu.

2. **AI rozhoduje o stylu.** Gemini dostane reálná data obou stran
   (pozice, výšku, váhu, body, doskoky, asistence, trojky, efektivitu)
   a podle system promptu vybere hráče, o kterém se reálně říká, že má
   stejný archetyp. temperature 0 + seed = stejná odpověď při každém
   načtení.

3. **Výstup.** AI nejdřív vypíše `top_3_candidates` a z nich vybere
   `closest_player_name`, plus tři porovnání: styl, fyzično, statistiky.
   Procenta shody počítá backend z reálných dat (AI je jen popisuje),
   aby číslo nebylo vymyšlené.

Výsledek se ukládá do tabulky `closest_cache` s verzí výpočtu
v klíči – po změně promptu se stará cache ignoruje a nic se nemusí mazat.

Vedle leží předchozí verze:
  - closest_player_v1.py.bak      – deterministické matematické váhy 50/30/20
  - closest_player_v2_old.py.bak  – meziverze
Kdyby se mělo něco vrátit, stačí soubor přejmenovat zpět.
"""

from __future__ import annotations

import json
import logging
import os
import unicodedata
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

from services import defense
from services.similarity_engine import shot_and_creation_features

# Když se změní prompt nebo logika, zvyš číslo – stará cache se přestane používat.
ENGINE_VERSION = 29
SIMILARITY_WEIGHTS = {"style": .56, "physical": .11, "stats": .17, "defense": .16}

# Kolik kandidátů se AI pošle (víc = horší soustředění, méně = může chybět správný)
CANDIDATE_LIMIT = 12


# --------------------------------------------------------------------------- #
# 1. Role a kategorie – hrubý, ale čitelný předvýběr
# --------------------------------------------------------------------------- #

def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", (text or "").lower())
    return "".join(c for c in text if not unicodedata.combining(c)).strip()


def coerce_position(value: Optional[str], height_cm: float = 198.0) -> str:
    """
    Sjednotí zápis pozice z různých zdrojů:
      "SG", "Shooting Guard"  -> "SG"
      "PG", "Point Guard"     -> "PG"
      "Guard"                 -> PG nebo SG podle výšky
      "Forward-Guard" / "Guard-Forward" -> SG / SF podle výšky
      "Forward"               -> SF nebo PF podle výšky
      "Center"                -> "C"
    Ostatní zdroje (Basketball-Reference píše „Shooting Guard and Small
    Forward") se berou podle první uvedené pozice.
    """
    text = _norm(value)
    if not text:
        return ""
    height = _num(height_cm, 198.0)

    def has(token: str) -> bool:
        return token in text.split()

    # přímé zkratky
    if text in ("pg", "sg", "sf", "pf", "c"):
        return text.upper()

    parts = [p.strip() for p in text.replace(" and ", ",").replace("-", " ").split(",")]
    tokens: List[str] = []
    for part in parts:
        tokens.extend(part.split())
    joined = " ".join(tokens)

    if "center" in joined:
        return "C"
    if "point guard" in joined:
        return "PG"
    if "shooting guard" in joined:
        return "SG"
    if "small forward" in joined:
        return "SF"
    if "power forward" in joined:
        return "PF"

    if text == "g":
        return "PG" if height < 191 else "SG"
    if text == "f":
        return "PF" if height >= 206 else "SF"
    if "guard" in tokens and "forward" in tokens:
        return "SG" if height < 201 else "SF"
    if "guard" in tokens:
        return "PG" if height < 191 else "SG"
    if "forward" in tokens:
        return "PF" if height >= 206 else "SF"
    return ""


def _num(value: Any, default: float = 0.0) -> float:
    try:
        number = default if value is None else float(value)
    except (TypeError, ValueError):
        return default
    # NBA API u starších sezón vrací NaN – bere se jako nula
    return default if number != number else number


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def role_group(position: Optional[str], height_cm: Optional[float]) -> str:
    """Tři základní skupiny: rozehrávač / křídlo / podkošový hráč."""
    height = _num(height_cm, 198.0)
    simple = coerce_position(position, height)
    if simple in ("PG", "SG"):
        return "guard"
    if simple == "C":
        return "big"
    if simple in ("SF", "PF"):
        return "wing"
    # Bez pozice rozhodne výška
    if height >= 208:
        return "big"
    if height <= 193:
        return "guard"
    return "wing"


POSITION_LABEL = {
    "SG": "shooting guard (SG)",
    "PG": "rozehrávač (PG)",
    "SF": "křídlo (SF)",
    "PF": "křídelní pivot (PF)",
    "C": "pivot (C)",
}


def position_type(position: Optional[str], height_cm: Optional[float]) -> str:
    """
    Konkrétní pozice, ne jen „guard / wing / big". MJ byl čistý SG,
    Harden je PG/SG (combo) – to je rozdíl, který musí být vidět.
    """
    height = _num(height_cm, 198.0)
    simple = coerce_position(position, height)
    if simple:
        return simple
    # Bez pozice rozhodne výška
    if height >= 211:
        return "C"
    if height >= 206:
        return "PF"
    if height >= 198:
        return "SF"
    if height >= 191:
        return "SG"
    return "PG"


# Kolik si toho pozice nechá: stejná pozice = plná, sousední = půlka
def _height_gap_cm(a: Dict[str, Any], b: Dict[str, Any]) -> float:
    """Rozdíl výšky v centimetrech; chybějící míra = neznámý rozdíl."""
    ha = _num(a.get("height_cm"))
    hb = _num(b.get("height_cm"))
    if ha <= 0 or hb <= 0:
        return 0.0
    return abs(ha - hb)


_POS_COMPAT = {
    ("SG", "SG"): 100.0, ("PG", "PG"): 100.0, ("SF", "SF"): 100.0,
    ("PF", "PF"): 100.0, ("C", "C"): 100.0,
    ("SG", "PG"): 40.0, ("PG", "SG"): 40.0,        # combo guard není čistý SG
    ("SF", "SG"): 80.0, ("SG", "SF"): 80.0,
    ("SF", "PF"): 78.0, ("PF", "SF"): 78.0,
    ("PF", "C"): 65.0, ("C", "PF"): 65.0,
}
# Archetypy, které k sobě mají blízko (střelec bez míče vs. skórující SG)
_RELATED_ARCHETYPES = {
    "scoring_sg": {"sharpshooter", "two_way_wing"},
    "sharpshooter": {"scoring_sg"},
    "sharpshooting_pg": {"scoring_pg", "creator_guard"},
    "scoring_pg": {"sharpshooting_pg", "combo_guard"},
    "creator_guard": {"sharpshooting_pg", "combo_creator", "big_creator"},
    "big_creator": {"combo_creator", "creator_guard", "point_forward"},
    "combo_creator": {"creator_guard", "big_creator"},
    "point_forward": {"scoring_wing", "big_creator"},
    "combo_guard": {"scoring_pg", "pass_first_pg"},
    "pass_first_pg": {"combo_guard"},
    "scoring_wing": {"two_way_wing", "stretch_big"},
    "two_way_wing": {"scoring_wing", "scoring_sg"},
    "point_forward": {"scoring_wing"},
    "stretch_big": {"post_scorer", "scoring_wing"},
    "post_scorer": {"paint_beast", "stretch_big"},
    "paint_beast": {"post_scorer", "energy_big"},
    "energy_big": {"paint_beast"},
    "post_hub": {"post_scorer", "stretch_big", "point_forward"},
    # Síla a atletičnost pod košem – blízké jsou jen další podobné typy
    "rim_runner": {"post_scorer", "paint_beast", "energy_big"},
}

# Rodiny archetypů – hráči ze stejné rodiny si jsou pořád blízko
_RIM_NEIGHBOURS = {"rim_runner", "post_scorer", "paint_beast", "energy_big"}

_ARCH_FAMILY = {
    "rim_runner": "big",
    "stretch_big": "stretch",
    "post_scorer": "stretch",
    "scoring_sg": "scorer_guard",
    "sharpshooter": "scorer_guard",
    "sharpshooting_pg": "scorer_guard",
    "scoring_pg": "scorer_guard",
    "creator_guard": "creator",
    "combo_creator": "creator",
    "big_creator": "creator",
    "pass_first_pg": "creator",
    "combo_guard": "creator",
    "role_guard": "creator",
    "point_forward": "wing",
    "scoring_wing": "wing",
    "two_way_wing": "wing",
    "paint_beast": "big",
    "energy_big": "big",
    "post_hub": "big",
}

_POS_WEIGHT = {"C": 110.0, "PF": 100.0, "SF": 100.0, "SG": 96.0, "PG": 88.0}


def position_score(a: Dict[str, Any], b: Dict[str, Any]) -> float:
    """Shoda konkrétní pozice (0-100) s vahou; pivot s rozehrávačem = nula."""
    pa, pb = a.get("position_type", ""), b.get("position_type", "")
    compat = _POS_COMPAT.get((pa, pb), 12.0)
    weight = _POS_WEIGHT.get(pa, 100.0)
    return _clamp(compat * weight / 100.0)


ROLE_GROUP_LABEL = {
    "guard": "rozehrávač / guard",
    "wing": "křídlo",
    "big": "podkošový hráč",
}


ARCHETYPE_LABEL = {
    "rim_runner": "síla a atletičnost pod košem",
    "scoring_pg": "skórující rozehrávač",
    "pass_first_pg": "pas-first rozehrávač",
    "combo_guard": "combo guard (střelba i tvorba)",
    "sharpshooter": "střelec bez míče",
    "scoring_wing": "skórující křídlo",
    "two_way_wing": "obousměrné křídlo",
    "point_forward": "tvořivé křídlo (point forward)",
    "paint_beast": "podkošová síla",
    "post_scorer": "podkošový zakončovatel",
    "stretch_big": "vytahující se pivot",
    "energy_big": "pohyblivý pivot",
    "post_hub": "podkošový tvůrce hry",
    "creator_guard": "tvořivý rozehrávač (hodně s míčem)",
    "scoring_sg": "skórující shooting guard",
    "combo_creator": "kombinovaný tvůrce hry",
    "big_creator": "velký tvůrce hry (jako Harden či Luka)",
    "sharpshooting_pg": "střílející rozehrávač",
    "role_guard": "rotační rozehrávač",
}


def scavenger(p: Dict[str, Any]) -> bool:
    """
    Hráč, který skóruje hlavně pod košem – minimum trojek a hodně šestek.
    Giannis (14 % střel za tři, 8,4 šestky) není stejný typ jako Durant
    (27 %, 7,3), i když mají stejnou pozici i body.
    """
    return p.get("three_rate", 1.0) < 0.20 and p.get("fta", 0.0) >= 6.5


def scoring_mode(p: Dict[str, Any]) -> str:
    """
    Jak hráč skóruje: z trojek, nebo z průniku a šestek.
    Ray Allen (3,8 šestek, 39 % střel z trojek) není Wade (5,8 šestek,
    ale jiný objem) – a Wade není střelec, i když trojky taky házel.
    """
    three_rate = p["three_rate"]
    fta = p.get("fta", 0.0)
    fg3m = p.get("fg3m", 0.0)
    if fg3m >= 1.5 and three_rate >= 0.33 and fta <= 5.0:
        return "shooter"                 # Ray Allen, Reggie Miller
    if fta >= 5.5:
        return "slasher"                 # Wade, Jordan, Luka – průnik a šestky
    if three_rate >= 0.38:
        return "perimeter"               # hodně trojek, ale i dost šestek
    return "balanced"                    # Dirk, Jokič – mix


def archetype(p: Dict[str, Any]) -> str:
    """
    Archetyp podle toho, JAK hráč hraje – z reálných dat, ne z pozice.
    Tohle je hlavní filtr: Curry (24,8 b, 6,4 a, 2,5 trojky) nesmí skončit
    u Tonyho Parkera (15,5 b, 1,3 trojky) a Jordan (5,3 a) nesmí skončit
    u Hardena (7,1 a, tvořivý rozehrávač).
    """
    pts = p["pts"]
    ast = p["ast"]
    fg3m = p.get("fg3m", 0.0)
    three_rate = p["three_rate"]
    group = p["role_group"]
    pos = p["position_type"]

    # Pozor na pořadí: vysoký hráč s velkým skóre je střelec (Durant),
    # ne tvůrce hry. Tvůrce se pozná podle toho, že dává body hlavně
    # z přihrávek druhým – proto ta podmínka na body.
    # Podkošový tvůrce (Jokič) – vysoký počet asistencí, ale bez velkého skóre
    if group == "big" and ast >= 5.0 and pts < 22.0 and p["blk"] < 1.5:
        return "post_hub"

    # Vysoký střelec s málo asistencemi = vytahující se pivot (Dirk),
    # jinak zůstává křídlem (Durant, LeBron).
    if group != "guard" and p["height_cm"] >= 206 and three_rate >= 0.28 and ast < 3.5:
        return "stretch_big"             # Dirk, Markkanen – vysoký střelec, málo asistencí

    if group == "guard":
        if pos == "PG" and pts >= 22.0 and ast >= 5.0 and fg3m < 2.0:
            return "scoring_pg"
        # Kdo má v ruce míč a tvoří (7+ asistencí) s velkým objemem bodů,
        # je tvůrce hry – Harden, Cade, Luka, Westbrook. Ne čisté SG.
        # Pozor: Jordan (1988) měl 8 asistencí a 8 doskoků, ale tvořil
        # hlavně sám za sebe. Tvůrce hry proto musí mít víc asistencí než
        # doskoků a střelecky silnou trojku – bez ní je to střelec, který
        # v dobré sezóně i přihrává.
        if (
            ast >= 6.0
            and pts >= 20.0
            and p["reb"] >= 5.5
            and p["height_cm"] >= 194
            and ast > p["reb"] - 1.0
            and fg3m >= 1.5
        ):
            return "big_creator"         # Harden, Luka – velký tvůrce s doskoky
        # Tvůrce hry s míčem v ruce (Westbrook, Harden) – hodně asistencí,
        # hodně střel a hodně míče. Jordan 1988 měl 6,2 asistence, ale jeho
        # hra stála na skórování (35 bodů), ne na tvoření pro druhé –
        # proto musí být asistencí víc než 6,5 a víc než doskoků.
        if (
            pts >= 20.0
            and ast >= 6.5
            and ast > p["reb"]
            and (p["fga"] >= 18.0 or p.get("usage", 0) >= 0.31)
            and p["reb"] < 7.5
            and fg3m < 2.5
        ):
            return "creator_guard"       # Westbrook – hodně míče, hodně bodů
        if ast >= 6.5 and pts >= 20.0 and pos != "PG" and fg3m < 2.5:
            return "combo_creator"       # Cade – velký tvůrce
        # Malý rozehrávač, který skóruje z trojek i po driblingu a tvoří
        if pos == "PG" and fg3m >= 2.0 and pts >= 20.0 and ast >= 5.0:
            return "sharpshooting_pg"    # Curry, Irving
        # Čistý SG: hodně bodů, tvoření pod 6,5 asistence
        # Jordan (1988) měl 6,2 asistence – hranice pro čistého střelce
        # musí být výš, jinak by se z něj stal tvůrce hry. Tvůrce hry
        # pozná podle toho, že přihrávkami opravdu řídí hru (6,5+).
        # A bez trojky se z hráče nestane tvůrce hry na křídle: křídlo
        # s asistencí a bez trojky je obránce, ne point forward.
        # Jordan 1988 dal 35 bodů na 25 střelách a přidal 6 asistencí –
        # to je střelec, který v dobré sezóně i přihrává, ne tvůrce hry.
        # Tvůrce hry musí mít VÍC asistencí než doskoků a objem střelby
        # na úrovni rozehrávače.
        if pts >= 22.0 and (ast < 6.5 or ast <= p["reb"]):
            return "scoring_sg"          # Jordan, Kobe, Wade, Iverson
        if pts >= 18.0 and ast >= 4.0:
            return "scoring_pg"          # Morant
        if ast >= 6.0:
            return "pass_first_pg"       # Stockton, CP3, Rondo
        if pts >= 15.0 and ast >= 3.5:
            return "combo_guard"
        if pts >= 15.0 and ast < 3.5:
            return "sharpshooter"        # Ray Allen, Reggie Miller
        return "role_guard"
    if group == "wing":
        # Vysoký tvůrce, který doskakuje a hraje vlastním tempem – Luka
        if ast >= 7.5 and pts >= 25.0 and p["reb"] >= 6.5 and fg3m >= 1.5:
            return "big_creator"         # Luka
        if ast >= 6.0 and pts >= 20.0 and fg3m >= 0.8:
            # Křídlo, které skóruje hlavně z trojek a tvoří, je střelec
            # s přehledem (Durant), ne rozehrávající forward (LeBron).
            if p.get("three_pts_share", 0.0) >= 0.18:
                return "scoring_wing"
            return "point_forward"       # LeBron, Bird
        # Křídlo bez trojky s asistencí = obránce a hráč bez míče
        # (Pippen, Kawhi), ne rozehrávač hry.
        if ast >= 4.0 and fg3m < 0.8 and p.get("fta", 0) < 6.5:
            return "two_way_wing"
        # Síla a atletičnost pod košem, ne střelba – Giannis, Zion.
        # Rozhoduje podíl bodů z trojek: křídlo, které dává 22 % bodů
        # z trojek, není stejný typ jako to, které dává 8 %. Musí k tomu
        # ale sedět i postava – 198cm hráč není 211cm atlet.
        if (
            pts >= 18.0
            and p.get("three_pts_share", 0.0) < 0.15
            and p.get("fta", 0) >= 5.5
            and p["height_cm"] >= 203
        ):
            return "rim_runner"          # Giannis, Zion
        if pts >= 18.0 and p.get("three_pts_share", 0.0) >= 0.15:
            return "scoring_wing"        # Durant, Dirk
        if pts >= 20.0:
            return "scoring_wing"
        if ast >= 4.5:
            return "two_way_wing"        # Pippen, Kawhi, Bird
        return "two_way_wing"
    # podkošoví
    # Jokić: podkošový tvůrce hry – vysoký počet asistencí a hodně střel
    if group == "big" and ast >= 5.0 and p["blk"] < 1.5:
        return "post_hub"                # Jokić, Sabonis
    if three_rate >= 0.30 and ast < 3.5:
        return "stretch_big"             # Dirk, Markkanen
    if three_rate >= 0.22:
        return "stretch_big"
    if scavenger(p) and pts >= 18.0:
        return "rim_runner"
    if pts >= 18.0:
        return "post_scorer"
    if p["reb"] >= 10.0 or p["blk"] >= 1.5:
        return "paint_beast"
    return "energy_big"


def impact_tier(pts: float, awards: int) -> str:
    """
    Kategorie dopadu – superstar se má srovnávat se superstarou.
    Bere se objem bodů a počet ocenění.
    """
    if pts >= 22.0 or awards >= 3:
        return "superstar"
    if pts >= 15.0 or awards >= 1:
        return "all_star"
    return "role_player"


TIER_LABEL = {
    "superstar": "superstar",
    "all_star": "all-star / lídr",
    "role_player": "role player",
}


# --------------------------------------------------------------------------- #
# 2. Profil hráče – reálná data, která jdou do promptu i do UI
# --------------------------------------------------------------------------- #

def build_profile(
    player_id: int,
    name: str,
    position: Optional[str],
    height_cm: Optional[float],
    weight_kg: Optional[float],
    stat: Dict[str, Any],
    awards_count: int = 0,
    award_detail: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    pts = _num(stat.get("pts"))
    reb = _num(stat.get("reb"))
    ast = _num(stat.get("ast"))
    stl = _num(stat.get("stl"))
    blk = _num(stat.get("blk"))
    tov = _num(stat.get("tov"))
    fga = max(_num(stat.get("fga"), 1.0), 1.0)
    fg3a = _num(stat.get("fg3a"))
    fg3m = _num(stat.get("fg3m"))
    fgm = _num(stat.get("fgm"))
    ftm = _num(stat.get("ftm"))
    fta = _num(stat.get("fta"))
    fg_pct = _num(stat.get("fg_pct"))
    fg3_pct = _num(stat.get("fg3_pct"))
    ft_pct = _num(stat.get("ft_pct"))
    minutes = _num(stat.get("min_per_game"), 32.0) or 32.0
    # Procenta chybí v průměru z více sezón – dopočítají se z počtů
    if not fg3_pct and fg3a:
        fg3_pct = fg3m / fg3a
    if not fg_pct and fga > 1.0:
        fg_pct = fgm / fga
    if not ft_pct and fta:
        ft_pct = ftm / fta

    three_rate = _clamp(fg3a / fga, 0.0, 1.0)
    usage = _clamp(((fga + 0.44 * fta + tov) * 48.0 / minutes) / 100.0, 0.08, 0.45)
    ts = _clamp((pts / (2.0 * (fga + 0.44 * fta))) if fga else fg_pct, 0.0, 1.0)

    # Odkud hráč skóruje: pod košem (2PT) vs. za trojkou. Tohle rozliší
    # Giannise (91 % střel za dva) od Duranta (73 %), i když mají stejná
    # čísla v bodech.
    two_pm = max(fgm - fg3m, 0.0)
    two_pa = max(fga - fg3a, 0.0)
    # Skórování: kolik bodů jde z trojek, kolik z šestek a jak daleko
    # od koše hráč střílí. Tohle je „jak hraje", ne „kolik dá".
    shot_profile = {
        "two_rate": _clamp(two_pa / fga, 0.0, 1.0),
        "three_rate": three_rate,
        "paint_share": _clamp(two_pm / fga, 0.0, 1.0),
        "rim_rate": 0.0,
        "three_pts_share": _clamp((3.0 * fg3m) / max(pts, 1.0), 0.0, 0.8),
        "ft_pts_share": _clamp(ftm / max(pts, 1.0), 0.0, 0.5),
    }

    # Jak hráč hraje: tvoří na sebe, nebo skóruje po przyhrávce? Bere
    # hodně doskoků, nebo je to zakončovatel? Dojíždí hodně na čáru trestných?
    play_style = {
        # Tvorba hry: asistence + nízký počet šestek na střelu
        "creator": _clamp(ast / 8.0, 0.0, 1.0),
        # Podíl doskoků na hru (vysoký = hráč, který žije z druhých šancí)
        "rebounder": _clamp((reb - 3.0) / 9.0, 0.0, 1.0),
        # Hodně střel = hráč, který si bere hodně míče na sebe
        "volume": _clamp((fga - 8.0) / 15.0, 0.0, 1.0),
        # Zakončení v pohybu a pod košem (atletičnost)
        "athletic": _clamp(
            ((1.0 - three_rate) * 0.6 + (fta / max(fga, 1.0)) * 0.4), 0.0, 1.0
        ),
    }

    group = role_group(position, height_cm)
    # Kategorie dopadu se pozná i bez ocenění – ze způsobu, jakým hráč skóruje.
    # Hráč, který dal 19 bodů na 50 % za tři, není „role player".
    if awards_count <= 0 and pts >= 17.0:
        awards_count = 1
    # Hráči, kteří dali přes 19 bodů na velký objem, jsou kategorie
    # „hvězda" i bez trofejí v datech – jinak by se srovnávali s náhradníky.
    if awards_count < 2 and pts >= 19.0:
        awards_count = 2
    tier = impact_tier(pts, awards_count)

    # --- Per 100 držení (tempo éry), obrana, postava, střelecký profil ---
    seasons_list = stat.get("seasons") if isinstance(stat.get("seasons"), list) else []
    season_hint = (seasons_list[len(seasons_list) // 2] if seasons_list else None) or stat.get("season_id") or stat.get("season")
    mins_raw = stat.get("min_per_game")
    pts100 = defense.per100(stat.get("pts"), mins_raw, season_hint)
    reb100 = defense.per100(stat.get("reb"), mins_raw, season_hint)
    ast100 = defense.per100(stat.get("ast"), mins_raw, season_hint)
    stl100 = defense.per100(stat.get("stl"), mins_raw, season_hint)
    blk100 = defense.per100(stat.get("blk"), mins_raw, season_hint)
    stocks100 = None if (stl100 is None and blk100 is None) else (stl100 or 0.0) + (blk100 or 0.0)
    detail = dict(award_detail or defense.empty_awards())
    d_tier = defense.defense_tier(stl100, blk100, group, detail)
    ft_rate = _clamp(fta / max(fga, 1.0), 0.0, 1.0)
    h_val = _num(height_cm, 198.0)
    w_val = _num(weight_kg, 98.0)
    b_type = defense.build_type(
        h_val, w_val, ft_rate, shot_profile["two_rate"], stocks100, group, three_rate
    )
    ath_score = defense.athleticism_score(ft_rate, shot_profile["two_rate"], stocks100)
    gravity = defense.shooting_gravity(fg3m, fg3a, fg3_pct)
    pos_type = position_type(position, height_cm)
    profile = {
        "role_group": group,
        "height_cm": _num(height_cm, 198.0),
        "position_type": pos_type,
        "pts": pts,
        "ast": ast,
        "reb": reb,
        "blk": blk,
        "fg3m": fg3m,
        "three_rate": three_rate,
        "usage": usage,
        "fta": fta,
        "fga": fga,
        "fg3a": fg3a,
        "two_rate": shot_profile["two_rate"],
        "paint_share": shot_profile["paint_share"],
        "rim_rate": shot_profile["rim_rate"],
        "three_pts_share": shot_profile["three_pts_share"],
        "ft_pts_share": shot_profile["ft_pts_share"],
        "ft_pct": ft_pct if stat.get("fta") and (stat.get("ft_pct") is not None or stat.get("ftm") is not None) else None,
        "fgm": fgm,
        "ftm": ftm,
        "creator": round(play_style["creator"], 3),
        "rebounder": round(play_style["rebounder"], 3),
        "volume": round(play_style["volume"], 3),
        "athletic": round(play_style["athletic"], 3),
    }
    features = shot_and_creation_features(stat, season_hint, usage, fg3_pct)
    profile["rim_rate"] = features["rim_pressure_index"] or 0.0
    arch = archetype(profile)
    profile["scoring_mode"] = scoring_mode(profile)

    return {
        **features,
        "id": player_id,
        "espn_id": stat.get("espn_id"),
        "name": name,
        "position": position or "",
        "height_cm": _num(height_cm, 198.0),
        "weight_kg": _num(weight_kg, 98.0),
        "pts": pts,
        "reb": reb,
        "ast": ast,
        "stl": stl,
        "blk": blk,
        "tov": tov,
        "fga": fga,
        "fg3a": fg3a,
        "fg3m": fg3m,
        "fg_pct": fg_pct,
        "fg3_pct": fg3_pct,
        "ft_pct": profile["ft_pct"],
        "three_rate": round(three_rate, 3),
        "two_rate": round(shot_profile["two_rate"], 3),
        "paint_share": round(shot_profile["paint_share"], 3),
        "creator": round(play_style["creator"], 3),
        "rebounder": round(play_style["rebounder"], 3),
        "volume": round(play_style["volume"], 3) if stat.get("fga") is not None else None,
        "athletic": round(play_style["athletic"], 3),
        "rim_rate": features["rim_pressure_index"],
        "three_pts_share": round(shot_profile["three_pts_share"], 3),
        "ft_pts_share": round(shot_profile["ft_pts_share"], 3),
        "usage": round(usage, 3),
        "ts": round(ts, 3) if stat.get("fga") and stat.get("fta") is not None else None,
        "fta": fta,
        "scoring_mode": profile["scoring_mode"],
        "role_group": group,
        "role_label": ROLE_GROUP_LABEL[group],
        "position_type": pos_type,
        "position_label": POSITION_LABEL[pos_type],
        "archetype": arch,
        "archetype_label": ARCHETYPE_LABEL[arch],
        "scoring_mode": scoring_mode(profile),
        "tier": tier,
        "tier_label": TIER_LABEL[tier],
        "awards": awards_count,
        "award_detail": detail,
        "pts100": pts100,
        "reb100": reb100,
        "ast100": ast100,
        "stl100": stl100,
        "blk100": blk100,
        "defense_tier": d_tier,
        "defense_label": defense.DEFENSE_LABEL[d_tier],
        "build_type": b_type,
        "build_label": defense.BUILD_LABEL[b_type],
        "athletic_score": ath_score,
        "gravity": gravity,
        "gravity_label": defense.GRAVITY_LABEL[gravity],
        "ft_rate": round(ft_rate, 3),
        "seasons": seasons_list,
    }


def apply_awards(profile: Dict[str, Any], detail: Dict[str, int]) -> Dict[str, Any]:
    """Doplní ocenění (DPOY, All-Defensive…) a přepočte obrannou úroveň."""
    profile["award_detail"] = dict(detail or defense.empty_awards())
    # Zisky a bloky jsou na zápas; defense_tier si je sám přepočítá na
    # 100 držení podle minut a tempa éry.
    profile["defense_tier"] = defense.defense_tier(
        profile.get("stl"),
        profile.get("blk"),
        profile.get("role_group", ""),
        profile["award_detail"],
        minutes=profile.get("min_per_game"),
        season=(profile.get("seasons") or [None])[0],
    )
    profile["defense_label"] = defense.DEFENSE_LABEL[profile["defense_tier"]]
    total = sum(profile["award_detail"].values())
    if total > profile.get("awards", 0):
        profile["awards"] = total
    return profile


def related_arch(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    """
    Sousední archetypy: skórující SG a střelec bez míče mají k sobě blízko.

    Sousední archetyp nestačí, když se jeden trefuje z dálky a druhý ne
    (KD a Siakam) – pak to nejsou podobní hráči.
    """
    arch_a, arch_b = a.get("archetype"), b.get("archetype")
    if not arch_a or not arch_b or arch_a == arch_b:
        return False
    if arch_b not in _RELATED_ARCHETYPES.get(arch_a, set()):
        return False
    return abs(_num(a.get("gravity"), 1) - _num(b.get("gravity"), 1)) < 2


def three_share(p: Dict[str, Any]) -> float:
    """Podíl bodů ze trojek (0–0,8). Počítá se i z profilu, kde chybí."""
    value = p.get("three_pts_share")
    if value is not None:
        return _clamp(_num(value), 0.0, 0.8)
    pts = _num(p.get("pts"))
    fg3m = _num(p.get("fg3m"))
    if pts <= 0:
        return 0.0
    return _clamp(3.0 * fg3m / pts, 0.0, 0.8)


def _similarity(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, float]:
    """
    Shoda dvou profilů: herní styl, fyzicko a statistiky.

    Styly a fyzicko rozhodují, statistiky jsou kontrola. Vrací i dílčí
    procenta, která vidí uživatel (stejná čísla na hlavní stránce
    i na stránce s porovnáváním).
    """
    style_pct = _style_similarity(a, b)
    physical_pct = _physical_similarity(a, b)
    stats_pct = _stats_similarity(a, b)

    defense_pct, coverage = defense.defense_similarity(a.get("defensive_rates", {}), b.get("defensive_rates", {}))
    weights = dict(SIMILARITY_WEIGHTS)
    weights["defense"] *= coverage
    weights["style"] += SIMILARITY_WEIGHTS["defense"] - weights["defense"]
    total = (weights["style"] * style_pct + weights["physical"] * physical_pct
             + weights["stats"] * stats_pct + weights["defense"] * (defense_pct or 0))
    load_gap = _feature_gap(a, b, "on_ball_load")
    pass_gap = _feature_gap(a, b, "pass_to_score")
    total -= min(8., 16 * max(0., (load_gap or 0) - .13) + 12 * max(0., (pass_gap or 0) - .16))
    return {
        "match_pct": round(_clamp(total), 1),
        "style_pct": round(style_pct, 1),
        "physical_pct": round(physical_pct, 1),
        "stats_pct": round(stats_pct, 1),
        "defense_pct": round(defense_pct, 1) if defense_pct is not None else None,
        "weights": {key: round(value, 4) for key, value in weights.items()},
    }


def _feature_gap(a, b, key):
    x, y = a.get(key), b.get(key)
    return abs(x - y) if x is not None and y is not None else None


def _style_similarity(a: Dict[str, Any], b: Dict[str, Any]) -> float:
    scores = []
    for key, weight, scale in (
        ("rel_3par", 13, .48), ("three_efficiency", 14, .20),
        ("rim_pressure_index", 21, .62), ("mid_range_index", 10, .65),
        ("on_ball_load", 20, .66), ("pass_to_score", 11, .5),
        ("volume", 6, .75), ("ft_pct", 5, .25),
    ):
        gap = _feature_gap(a, b, key)
        if gap is not None:
            scores.append((weight, max(0., 1 - gap / scale)))
    return 100 * sum(w * score for w, score in scores) / sum(w for w, _ in scores) if scores else 0.


def _physical_similarity(a: Dict[str, Any], b: Dict[str, Any]) -> float:
    """Výška, váha a atletičnost – jak moc jsou si hráči tělesně podobní."""
    height_gap = abs(_num(a.get("height_cm"), 198.0) - _num(b.get("height_cm"), 198.0))
    weight_gap = abs(_num(a.get("weight_kg"), 95.0) - _num(b.get("weight_kg"), 95.0))

    score = 100.0
    score -= min(height_gap * 1.9, 45.0)
    score -= min(weight_gap * 0.55, 30.0)
    return _clamp(score)


def _stats_similarity(a: Dict[str, Any], b: Dict[str, Any]) -> float:
    """Statistický dopad: body, doskoky, asistence, obrana a efektivita."""
    pairs = [
        ("pts", 2.6),
        ("reb", 1.8),
        ("ast", 1.8),
        ("ts", 5.0),
        ("fg3a", 1.0 if a.get("three_rate", 0) > .40 and b.get("three_rate", 0) > .40 else 0.0),
    ]
    diffs: List[float] = []
    total_weight = 0.0
    for key, weight in pairs:
        if a.get(key) is None or b.get(key) is None or not weight:
            continue
        va, vb = a[key], b[key]
        if va <= 0 and vb <= 0:
            continue
        base = max((va + vb) / 2.0, 0.35 if key not in ("pts", "reb", "ast") else 1.0)
        if key == "ts":
            base = .15
        diffs.append(min(abs(va - vb) / base, 1.0) * weight)
        total_weight += weight

    if not diffs:
        return 50.0
    penalty = sum(diffs) / total_weight
    return _clamp(100.0 - penalty * 100.0)


def compare_pair(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    """
    Porovnání dvou hráčů stejnou logikou, jakou používá „nejbližší hráč".
    Vrací stejné tři dílčí čísla (styl / fyzično / statistiky) i celkovou
    shodu, takže stránka s porovnáváním a hlavní stránka nikdy neukážou
    u stejné dvojice jiné procento.
    """
    sim = _similarity(a, b)
    style_note = _style_note(a, b)
    if isinstance(a, dict) and isinstance(b, dict):
        # Uživatel musí vidět stejná dílčí čísla na hlavní stránce
        # i na stránce s porovnáváním.
        a.setdefault("style_pct", sim["style_pct"])
        b.setdefault("style_pct", sim["style_pct"])
        a.setdefault("stylistic_pct", sim["style_pct"])
        b.setdefault("stylistic_pct", sim["style_pct"])
    same_arch = a["archetype"] == b["archetype"]
    same_pos = a["position_type"] == b["position_type"]
    return {
        **sim,
        "style_pct": sim["style_pct"],
        "physical_pct": sim["physical_pct"],
        "stats_pct": sim["stats_pct"],
        # popisky pro UI
        "archetype_a": a["archetype_label"],
        "archetype_b": b["archetype_label"],
        "position_a": a["position_label"],
        "position_b": b["position_label"],
        "same_archetype": same_arch,
        "same_position": same_pos,
        "style_note": style_note,
        # popisky, které ukazuje stránka s porovnáváním
        "style_pct": sim["style_pct"],
        "physical_pct": sim["physical_pct"],
        "stats_pct": sim["stats_pct"],
        # Plné profily pro volajícího (tabulka, popisky) – ve výstupu API
        # se přeskakují, protože začínají podtržítkem.
        "_p1": a,
        "_p2": b,
    }


def _style_note(a: Dict[str, Any], b: Dict[str, Any]) -> str:
    """Jedna věta, čím si jsou hráči podobní a v čem se liší."""
    same = a["archetype"] == b["archetype"]
    parts: List[str] = []
    if same:
        parts.append(f"oba jsou {a['archetype_label']}")
    else:
        parts.append(
            f"{a['name']} je {a['archetype_label']}, "
            f"{b['name']} je {b['archetype_label']}"
        )
    if abs(a.get("three_pts_share", 0) - b.get("three_pts_share", 0)) > 0.12:
        parts.append(
            f"body z trojek {a.get('three_pts_share', 0) * 100:.0f} % vs "
            f"{b.get('three_pts_share', 0) * 100:.0f} %"
        )
    if abs(a.get("height_cm", 0) - b.get("height_cm", 0)) > 8:
        parts.append(
            f"výška {a.get('height_cm', 0) / 100:.2f} m vs "
            f"{b.get('height_cm', 0) / 100:.2f} m"
        )
    return "; ".join(parts) + "."


def _one_line(p: Dict[str, Any]) -> str:
    """Řádek do promptu – jen reálná data, žádné odhady."""
    pos = p["position"] or "pozice neuvedena"
    return (
        f"- {p['name']} | {pos} | {p['height_cm']:.0f} cm, {p['weight_kg']:.0f} kg | "
        f"{p['pts']:.1f} b, {p['reb']:.1f} d, {p['ast']:.1f} a, "
        f"{p['fg3m']:.1f} trojky na zápas | "
        f"FG {p['fg_pct'] * 100:.1f} %, 3P {p['fg3_pct'] * 100:.1f} %, "
        f"TS {p['ts'] * 100:.1f} % | Usage {p['usage']:.2f} | "
        f"{p['archetype_label']}, {p['role_label']}, {p['tier_label']} | "
        f"obrana: {p.get('defense_label', '?')}, postava: {p.get('build_label', '?')}, "
        f"střelba: {p.get('gravity_label', '?')} | "
        f"na 100 držení {_fmt(p.get('pts100'))}/{_fmt(p.get('reb100'))}/{_fmt(p.get('ast100'))} "
        f"(zisky {_fmt(p.get('stl100'))}, bloky {_fmt(p.get('blk100'))}) | "
        f"ocenění: {_award_text(p)}"
    )


def _fallback_why(target: Dict[str, Any], cand: Dict[str, Any]) -> str:
    """Krátký důvod kandidáta z čísel – když AI nic nenapíše."""
    bits: List[str] = []
    if cand.get("archetype") == target.get("archetype"):
        bits.append("stejný archetyp")
    gap = _num(target.get("pts")) - _num(cand.get("pts"))
    if abs(gap) <= 2.5:
        bits.append(f"stejný objem bodů ({_num(cand.get('pts')):.1f} na zápas)")
    if abs(_num(target.get("height_cm")) - _num(cand.get("height_cm"))) <= 5:
        bits.append("podobná postava")
    sim = _similarity(target, cand)["match_pct"]
    bits.append(f"shoda {sim:.0f} %")
    return ", ".join(bits)


def _fallback_texts(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, str]:
    """Popisky trojice sloupců bez AI – vždy musí něco vrátit."""
    same_arch = a.get("archetype") == b.get("archetype")
    if same_arch:
        style = (
            f"Oba patří mezi {a.get('role_label')}, takže řeší stejné situace na hřišti. "
            f"Střelba: {a.get('gravity_label')} vs {b.get('gravity_label')}. "
            f"Obrana: {a.get('defense_label')} vs {b.get('defense_label')}."
        )
    else:
        style = (
            f"Role se liší: {a.get('archetype_label')} vs {b.get('archetype_label')}. "
            f"Střelba: {a.get('gravity_label')} vs {b.get('gravity_label')}. "
            f"Obrana: {a.get('defense_label')} vs {b.get('defense_label')}."
        )

    physical = (
        f"{_fmt(a.get('height_cm'))} vs {_fmt(b.get('height_cm'))} cm, "
        f"{_fmt(a.get('weight_kg'))} vs {_fmt(b.get('weight_kg'))} kg. "
        f"Typ postavy: {a.get('build_label')} vs {b.get('build_label')}."
    )

    stats = (
        f"Vrchol kariéry na 100 držení: "
        f"{_fmt(a.get('pts100'))}/{_fmt(a.get('reb100'))}/{_fmt(a.get('ast100'))} vs "
        f"{_fmt(b.get('pts100'))}/{_fmt(b.get('reb100'))}/{_fmt(b.get('ast100'))}; "
        f"TS {_fmt(_num(a.get('ts')) * 100.0)} % vs {_fmt(_num(b.get('ts')) * 100.0)} %. "
        f"Ocenění: {_award_text(a)} vs {_award_text(b)}."
    )

    return {
        "style_comparison": style,
        "physical_comparison": physical,
        "stats_comparison": stats,
    }


def _fallback_reasoning(p: Dict[str, Any]) -> str:
    """Jedna věta, proč se hledá právě v této skupině hráčů."""
    return (
        f"{p.get('name')} je {p.get('role_label')} na úrovni {p.get('tier_label')}, "
        "proto se shoda hledá ve stejné roli a stejné kategorii dopadu."
    )


def _fmt(value: Any) -> str:
    return "-" if value is None else f"{float(value):.1f}"


def _award_text(p: Dict[str, Any]) -> str:
    aw = p.get("award_detail") or {}
    parts = []
    for key, label in (("mvp", "MVP"), ("dpoy", "DPOY"), ("all_nba", "All-NBA"), ("all_def", "All-Defensive")):
        if aw.get(key):
            parts.append(f"{aw[key]}× {label}")
    return ", ".join(parts) or "žádná"


# --------------------------------------------------------------------------- #
# 3. Předvýběr kandidátů – stejná role, podobná výška, podobná kategorie
# --------------------------------------------------------------------------- #

def preselect(
    target: Dict[str, Any],
    pool: List[Dict[str, Any]],
    limit: int = CANDIDATE_LIMIT,
    stats_filler: Optional[Any] = None,
) -> List[Dict[str, Any]]:
    """
    Vybere kandidáty pro AI. Nevybírá „nejlepšího" – jen zúží seznam
    tak, aby v něm nebyli hráči z úplně jiné role (střelec bez míče pro
    rozehrávače) a aby se neporovnávala superstar s role playerem.
    Pořadí je deterministické (skupina, kategorie, výška, ID).
    """
    def same_caliber(c: Dict[str, Any]) -> bool:
        """
        Role player není „druhý nejpodobnější" hráč hvězdy. Hráč, který dá
        14 bodů, není srovnatelný s hráčem na 19+. Rozdíl se měří podílem,
        aby superstar (35 b) nespadla na kandidáta s 21 body – což je
        rozdíl 40 %, ne „podobný hráč".
        """
        gap = abs(c["pts"] - target["pts"])
        if target["pts"] >= 17.0:
            return gap <= 5.5 and gap <= max(0.30 * target["pts"], 3.0)
        return gap <= 6.0

    def nearby_tier(c: Dict[str, Any]) -> bool:
        # superstar a all-star jsou sousedé, role player je až další úroveň.
        # U kandidátů z ESPN ale kategorie dopadu vzniká z jedné sezóny,
        # takže se superstar (35 b, MVP) nesmí srovnávat s hráčem, který
        # má 21 bodů a žádné ocenění.
        if target["tier"] == "superstar":
            return c["pts"] >= 0.72 * target["pts"] and c["tier"] != "role_player"
        strong = {"superstar", "all_star"}
        return (c["tier"] in strong) == (target["tier"] in strong)

    def same_pos(c: Dict[str, Any]) -> bool:
        return c["position_type"] == target["position_type"]

    def related_arch(c: Dict[str, Any]) -> bool:
        """Sousední archetypy: skórující SG a střelec bez míče mají k sobě blízko."""
        pair = {target["archetype"], c["archetype"]}
        if not pair & _RELATED_ARCHETYPES.get(target["archetype"], set()) or len(pair) != 2:
            return False
        # Sousední archetyp nestačí, když se jeden trefuje z dálky a druhý
        # ne (KD a Siakam) – pak to nejsou podobní hráči.
        if abs(target.get("gravity", 1) - c.get("gravity", 1)) >= 2:
            return False
        return True

    def family(c: Dict[str, Any]) -> int:
        """
        Kategorie hráče (rodina archetypů). Když se najde shoda tady,
        dá se do kandidátů i bez toho, aby seděl přesný archetyp.
        """
        if c["archetype"] == target["archetype"]:
            return 0
        if related_arch(c):
            return 1
        fam_target = _ARCH_FAMILY.get(target["archetype"])
        if fam_target and _ARCH_FAMILY.get(c["archetype"]) == fam_target:
            return 2
        # Když archetyp není v žádné rodině, rozhodne role a styl skórování
        if _ARCH_FAMILY.get(c["archetype"]) == _ARCH_FAMILY.get(target["archetype"]):
            if c["scoring_mode"] == target["scoring_mode"]:
                return 2
        if c["role_group"] == target["role_group"] and c["scoring_mode"] == target["scoring_mode"]:
            return 3
        if c["role_group"] == target["role_group"]:
            return 4
        return 5

    def priority(c: Dict[str, Any]) -> int:
        # Tvrdý filtr obrany: elitní obránce nedostane slabého a naopak.
        if {target.get("defense_tier"), c.get("defense_tier")} == {"elite", "weak"}:
            return 18
        fam = family(c)
        pos_ok = same_pos(c)
        tier_ok = nearby_tier(c)
        # Podkošoví hráči se nikdy nevybírají z křídel nebo rozehrávačů
        if target["role_group"] == "big" and c["role_group"] != "big":
            return 20
        # Rozdíl postavy: o 10 cm menší hráč není stejný typ, i když hraje
        # stejně – 198cm křídlo není 211cm křídlo.
        if abs(target.get("height_cm", 0) - c.get("height_cm", 0)) > 11.0:
            return 12
        # Střelec z perimetru a hráč, který žije pod košem, nejsou stejný typ
        # – ani když mají stejnou pozici. Rozdíl se měří podílem bodů z trojek.
        # Střelecký profil se posuzuje jemněji: hráč bez trojky (Jordan)
        # a hráč, který trojku má, ale není její otrok (Kobe, Wade), jsou
        # pořád podobní. Tvrzení „elitní trojkař vs. hráč bez trojky" platí
        # až pro krajní rozdíl.
        share_gap = abs(
            target.get("three_pts_share", 0.0) - c.get("three_pts_share", 0.0)
        )
        if share_gap > 0.24:
            return 15
        if abs(target.get("gravity", 1) - c.get("gravity", 1)) >= 3:
            return 16
        # 0 = stejný archetyp i pozice; 1 = stejný archetyp, jiná pozice;
        # 2 = stejná kategorie a pozice; 3 = stejná kategorie; dál slabší shody.
        if fam == 0 and pos_ok:
            return 0 if tier_ok else 1
        if fam == 0:
            return 1 if tier_ok else 2
        if fam == 1 and pos_ok:
            return 2 if tier_ok else 3
        if fam == 1:
            return 3
        if fam == 2 and pos_ok:
            return 3 if tier_ok else 4
        if fam == 2:
            return 4 if tier_ok else 5
        # Podkošový tvůrce: i bez přesné rodiny musí jít o podkošové hráče
        if target["role_group"] == "big" and c["role_group"] == "big" and pos_ok:
            return 5
        if pos_ok and c["role_group"] == target["role_group"]:
            return 6 if tier_ok else 7
        if pos_ok:
            return 8
        if c["role_group"] == target["role_group"]:
            return 9
        return 10

    def style_gap(c: Dict[str, Any]) -> float:
        """
        Jak moc se liší zdroj skórování (trojky, šestky, dva body).
        Tohle je to, co dělá hráče hráčem – váží proto nejvíc.
        """
        return (
            abs(target.get("three_pts_share", 0) - c.get("three_pts_share", 0)) * 3.0
            + abs(target.get("ft_pts_share", 0) - c.get("ft_pts_share", 0)) * 2.0
            + abs(target.get("two_rate", 0) - c.get("two_rate", 0)) * 1.5
            + abs(target.get("ast", 0) - c.get("ast", 0)) * 0.03
            # Tvorba, doskoky, objem střelby a atletičnost – aby „hráč,
            # který všechno tvoří" nevycházel stejně jako „zakončovatel".
            + abs(target.get("creator", 0) - c.get("creator", 0)) * 0.5
            + abs(target.get("rebounder", 0) - c.get("rebounder", 0)) * 0.45
            + abs(target.get("volume", 0) - c.get("volume", 0)) * 0.35
            + abs(target.get("athletic", 0) - c.get("athletic", 0)) * 0.35
        )

    def sort_key(c: Dict[str, Any]) -> Tuple[int, int, float, int]:
        # U stejné priority rozhoduje shoda, ne výška – jinak vyhraje
        # hráč, který je jen podobně vysoký, ale hraje jinak.
        return (
            priority(c),
            0 if same_caliber(c) else 1,
            # Stejná kategorie a stejná role – rozhoduje, kdo nejvíc
            # připomíná svým stylem a postavou.
            -round(_similarity(target, c)["match_pct"], 1),
            c["id"],
        )

    others = [
        c
        for c in pool
        if c["id"] != target["id"]
        # Stejný hráč nesmí být ani kandidát – ani když ho seznam obsahuje
        # dvakrát pod jiným ID.
        and _norm(c.get("name", "")) != _norm(target.get("name", ""))
        # Bez míry a výšky se fyzično nedá porovnat – takový hráč by vyhrál
        # jen proto, že o něm nic nevíme.
        and _num(c.get("height_cm")) > 0
        and _num(c.get("weight_kg")) > 0
    ]
    # Hráči bez čísel se do výběru nepletou – o nich nic nevíme, takže by
    # vyhráli jen proto, že se u nich nic nepočítá.
    # Legendy a hráči mimo sezónní tabulku nemají čísla. Nejdřív se jim
    # doplní profil vrcholu kariéry (jen nejbližším podle postavy a role),
    # aby se s nimi dalo vůbec počítat a aby nevyhráli „naslepo".
    lacking = [c for c in others if _num(c.get("pts")) <= 0]
    if lacking and stats_filler is not None:
        lacking.sort(
            key=lambda c: (
                -_physical_similarity(target, c),
                -_style_similarity(target, c),
                c["id"],
            )
        )
        filled = {c["id"]: c for c in stats_filler(target, lacking[:30])}
        others = [filled.get(c["id"], c) for c in others]
    others = [c for c in others if _num(c.get("pts")) > 0]
    others.sort(key=sort_key)

    # Kandidáti se berou podle priority – stejná kategorie a pozice první,
    # ale vždy podle skutečné shody, ne podle výšky.
    # Ze širokého seznamu se bere prvních pár podle priority (jistota role
    # a kategorie) a zbytek se doplní podle skutečné shody. Bez toho se do
    # dvanácti kandidátů dostanou hráči, kteří sedí rolí, ale stylem ne –
    # a AI pak vybírá z užšího výběru, než by musela.
    core = 8
    chosen = others[:core]
    rest = others[core:]
    # Zbytek se doplňuje podle shody, ale jen z hráčů, kteří sedí rolí
    # (priorita do 5). Hráč z jiné role se do kandidátů nedostane jen
    # proto, že mu sedí čísla.
    rest = [c for c in rest if priority(c) <= 5]
    rest.sort(key=lambda c: (-round(_similarity(target, c)["match_pct"], 1), c["id"]))
    chosen.extend(rest)
    return chosen[:limit]


# --------------------------------------------------------------------------- #
# 4. System prompt – basketbalová logika, ne matematika
# --------------------------------------------------------------------------- #

SUGGEST_PROMPT = """Jsi zkušený NBA analytik, který zná historii ligy i současnost.

Dostaneš popis jednoho hráče (jeho vrchol kariéry). Navrhni 5 jiných hráčů
– z jakékoli éry – kteří se mu nejvíc podobají stylem hry, postavou a rolí.
Nikdy nenavrhuj hráče samotného. Nesnaž se o originalitu, hledej opravdovou
podobnost (stejná role, stejný způsob střílení, podobná obrana).

Odpověz POUZE JSON:
{"candidates": ["Jméno Příjmení", "…", "…", "…", "…"]}
"""

SYSTEM_PROMPT = """Jsi zkušený NBA analytik, který zná historii ligy i současnost.

ÚKOL: Ke zadanému hráči najdi hráče, o kterém NBA experti a fanoušci reálně
říkají, že má stejný basketbalový styl a archetyp. Nejde o matematickou
podobnost čísel, ale o to, jak hráč hraje a jakou roli na hřišti má.

STRIKTNÍ PRAVIDLA:
0. SROVNÁVÁ SE VRCHOLNÁ VERZE HRÁČE (Prime), ne průměr kariéry. Data,
   která dostaneš, jsou průměrem tří nejlepších po sobě jdoucích sezón –
   to je hráč, jak si ho lidé pamatují. Nepřihlížej k nováčkovským ani
   posledním sezónám a nepopisuj hráče jako „průměr kariéry".
1. Role na hřišti musí sedět. Čistokrevný rozehrávač a tvůrce hry musí
   dostat rozehrávače nebo tvůrce hry – NIKDY střelce bez míče typu
   Ray Allen. Střelec bez míče dostane střelce bez míče. Podkošový hráč
   dostane podkošového hráče.
2. Srovnávej podobnou kalibru: superstar se superstarou, all-star s
   all-starem, role player s role playerem.
3. Vyber jen z uvedeného seznamu kandidátů. Žádné jméno si nevymýšlej
   a nikdy nevyber stejného hráče, kterého hledáme.
4. Nejdřív si v poli `top_3_candidates` sepiš tři nejbližší kandidáty
   (v pořadí od nejlepšího) a teprve z nich vyber jednoho do
   `closest_player_name`. Musí sedět jak herně, tak fyzicky.
5. Všechny texty piš česky, úderně, bez frází, 1-2 věty na kategorii.

7. OBRANA je tvrdé pravidlo. Elitní obránce (DPOY, opakovaně All-Defensive,
   Ben Simmons, Kawhi Leonard) NIKDY nedostane podprůměrného obránce
   (Magic Johnson, Luka Dončić), i když mají podobná útočná čísla.
8. POSTAVA A ATLETIČNOST, ne jen výška a váha: explozivní atlet (raný
   LeBron, Giannis, Wade) ≠ dlouhý hubený střelec (KD, T-Mac, Dirk) ≠
   technický neexplozivní hráč (Bird, Jokić).
9. STŘELECKÝ PROFIL: elitního trojkaře (KD) nespojuj s hráčem bez spolehlivé
   trojky (Siakam). Mladý Jordan má blíž k explozivním slasherům se střední
   střelbou (Wade) než k moderním volume trojkařům (Jaylen Brown).
10. Čísla jsou na 100 držení (tempo éry) a doplněná oceněními – starší éry
   se tak dají férově srovnat s dnešními.

6. Pokud dostaneš navíc fázi kariéry („Raná kariéra" / „Pozdní kariéra"),
   posuzuj jen tu – hráč se v ní mohl chovat úplně jinak než ve vrcholu.

Vrať POUZE JSON v tomto tvaru:
{
  "reasoning": "1-2 věty: jak hráč hraje, jaká je jeho primární role a archetyp",
  "top_3_candidates": [
    {"name": "Jméno 1", "why": "proč stylově sedí (max 1 věta)"},
    {"name": "Jméno 2", "why": "..."},
    {"name": "Jméno 3", "why": "..."}
  ],
  "closest_player_name": "Jméno vybraného z top_3_candidates",
  "style_comparison": "1-2 věty: herní styl, role, střelecký profil A OBRANNÁ úroveň obou",
  "physical_comparison": "1-2 věty: výška, váha, STAVBA TĚLA a typ ATLETIČNOSTI",
  "stats_comparison": "1-2 věty: vrcholné sezóny (Prime) na 100 držení podle tempa éry a ocenění"
}"""


def _build_prompt(target: Dict[str, Any], candidates: List[Dict[str, Any]]) -> str:
    lines = [
        "HRÁČ, KE KTERÉMU HLEDÁMĚ SHODU:",
        _one_line(target),
        "",
        "KANDIDÁTI (vybírej pouze z těchto jmen):",
    ]
    lines.extend(_one_line(c) for c in candidates)
    lines.append("")
    lines.append(
        "Vyber hráče se stejným archetypem a podobnou kalibrou. "
        "Nejdřív top_3_candidates, pak closest_player_name."
    )
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# 5. Volání Gemini – temperature 0, seed, JSON
# --------------------------------------------------------------------------- #

def _gemini_key() -> Optional[str]:
    """Klíč pro Gemini: z prostředí, jinak z nastavení aplikace."""
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if key:
        return key
    try:
        from settings import GEMINI_API_KEY as configured

        return configured or None
    except Exception:
        return None


# Modely se zkoušejí popořadě – když je jeden přetížený (503) nebo zrušený
# (404), odpoví další. První, který vrátí JSON, vyhrává.
GEMINI_MODELS = [
    m.strip()
    for m in os.environ.get(
        "GEMINI_MODELS",
        "gemini-3.5-flash-lite,gemini-2.5-flash-lite,gemini-3.1-flash-lite,gemini-3.5-flash",
    ).split(",")
    if m.strip()
]


# Poslední úspěšná odpověď – když jsou všechny modely přetížené, použije se
# tato, aby se výsledek u stejného hráče neměnil mezi dvěma načteními.
_LAST_AI: Dict[str, Dict[str, Any]] = {}
_LAST_AI_LIMIT = 200


_AI_DOWN_UNTIL = 0.0


def _call_gemini_json(
    prompt: str, system: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Zkusí modely popořadě; vrátí první rozumnou JSON odpověď."""
    api_key = _gemini_key()
    if not api_key:
        logger.warning("AI výběr nejbližšího hráče: chybí GEMINI_API_KEY")
        return None
    try:
        from google import genai
        from google.genai import types
    except Exception as exc:  # pragma: no cover
        logger.warning("Knihovna google-genai není k dispozici: %s", exc)
        return None

    global _AI_DOWN_UNTIL
    import time as _time

    cached_answer = _LAST_AI.get(prompt)
    if _time.time() < _AI_DOWN_UNTIL:
        # Kvóta je vyčerpaná – nečeká se na čtyři modely po 15 s.
        return cached_answer

    forced = os.environ.get("GEMINI_MODEL")
    models = [forced] if forced else GEMINI_MODELS
    last_error = ""
    quota_errors = 0

    for model in models:
        try:
            client = genai.Client(
                api_key=api_key, http_options=types.HttpOptions(timeout=15000)
            )
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0,
                    top_p=0,
                    top_k=1,
                    seed=7,
                    response_mime_type="application/json",
                    system_instruction=system or SYSTEM_PROMPT,
                ),
            )
            text = (response.text or "").strip()
            if text.startswith("```"):
                text = text.strip("`")
                text = text[text.find("{") :]
            data = json.loads(text)
            if isinstance(data, dict):
                _LAST_AI[prompt] = data
                while len(_LAST_AI) > _LAST_AI_LIMIT:
                    _LAST_AI.pop(next(iter(_LAST_AI)))
                return data
        except Exception as exc:  # pragma: no cover
            last_error = str(exc)[:160]
            if "429" in last_error or "RESOURCE_EXHAUSTED" in last_error:
                quota_errors += 1
            logger.info("Model %s neodpověděl: %s", model, last_error)
            continue

    if quota_errors:
        _AI_DOWN_UNTIL = _time.time() + 15 * 60

    cached = _LAST_AI.get(prompt)
    if cached:
        logger.info("AI neodpověděla (%s), používá se poslední odpověď", last_error)
        return cached
    logger.warning(
        "AI výběr nejbližšího hráče selhal (použije se předvýběr): %s", last_error
    )
    return None


def ai_suggest(target: Dict[str, Any]) -> List[str]:
    """
    Fáze 1: AI navrhne 4–5 jmen. Bez klíče nebo při chybě vrací [].

    Volá se přes `_call_gemini_json`, takže se zkouší víc modelů a při
    přetížení se použije poslední odpověď – jinak by se výsledek u stejného
    hráče měnil podle toho, jak je zrovna Gemini zaneprázdněná.
    """
    prompt = "HRÁČ (vrchol kariéry):\n" + _one_line(target)
    data = _call_gemini_json(prompt, system=SUGGEST_PROMPT)
    if not data:
        logger.warning("AI návrh kandidátů: model neodpověděl")
        return []
    names = data.get("candidates") or []
    return [str(n).strip() for n in names if str(n).strip()][:5]


def _fill_candidate_stats(
    target: Dict[str, Any], candidates: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Doplní statistiky kandidátům, kteří přišli jen se jménem a mírami.

    Sezónní tabulka ESPN obsahuje jen 200 nejlepších podle bodů, takže
    legenda (Kobe, Pippen, Wade) dorazí bez čísel. Tady se jí dohledá
    nejlepší sezóna a přepočítá profil – jinak by se s ní nedalo počítat.
    """
    # Doplňují se hráči bez čísel – a ti s málo zápasy (legenda má
    # v aktuální sezóně třeba 14 zápasů, což o stylu nic neříká), ale jen
    # u nejbližších kandidátů, aby se nestahovaly stovky profilů.
    missing = [
        c for c in candidates
        if _num(c.get("pts")) <= 0
        or _num(c.get("gp"), 99.0) < 20
    ]
    if not missing:
        return candidates
    # Doplňuje se nejvýš 40 profilů na jedno hledání – nejdřív ti, kdo
    # mají nejblíž postavou a rolí. Legenda (Pippen, Wade) je mezi nimi.
    if len(missing) > 40:
        missing = sorted(
            missing,
            key=lambda c: (
                -_physical_similarity(target, c),
                -_style_similarity(target, c),
                abs(_num(c.get("height_cm"), 198.0) - _num(target.get("height_cm"), 198.0)),
                c["id"],
            ),
        )[:40]

    try:
        from services import nba_external
    except Exception:  # pragma: no cover
        return candidates

    from services import espn_seasons

    def best_season(player_id: int) -> Optional[Dict[str, Any]]:
        """Profil vrcholu kariéry: nejsilnější sezóna z kariérního logu."""
        try:
            history = espn_seasons.player_season_stats(int(player_id)) or []
        except Exception:  # pragma: no cover
            return None
        history = [r for r in history if _num(r.get("gp")) >= 20]
        if not history:
            return None
        return max(
            history,
            key=lambda r: _num(r.get("pts")) * min(_num(r.get("gp")), 70.0),
        )

    targets = {c["id"] for c in missing}
    filled: List[Dict[str, Any]] = []
    for cand in candidates:
        if cand["id"] not in targets:
            filled.append(cand)
            continue
        stat = best_season(int(cand["id"]))
        if not stat:
            continue
        # Statistiky se musí slít s mírami, které už kandidát měl
        # (ESPN profil hráče je nevrací).
        merged_stat = dict(stat)
        merged_stat.setdefault("name", cand.get("name") or "")
        profile = build_profile(
            player_id=cand["id"],
            name=cand.get("name") or stat.get("name") or "",
            position=cand.get("position") or stat.get("position"),
            height_cm=cand.get("height_cm") or stat.get("height_cm"),
            weight_kg=cand.get("weight_kg") or stat.get("weight_kg"),
            stat=merged_stat,
            awards_count=cand.get("awards") or 0,
        )
        profile["award_detail"] = cand.get("award_detail") or {}
        filled.append(profile)
    return filled or candidates


def enrich_awards(target: Dict[str, Any], candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Za běhu stáhne ocenění jen kandidátům (max ~12, paralelně, s dočasnou
    pamětí) a znovu rozhodne o obranné úrovni. Pak platí tvrdý filtr:
    elitní obránce nedostane slabého a naopak.
    """
    from concurrent.futures import ThreadPoolExecutor

    ids = [c["id"] for c in candidates]
    try:
        with ThreadPoolExecutor(max_workers=6) as pool:
            details = list(pool.map(defense.award_profile, ids))
    except Exception as exc:  # pragma: no cover
        logger.warning("Ocenění kandidátů se nenačetla: %s", exc)
        return candidates
    out: List[Dict[str, Any]] = []
    for cand, detail in zip(candidates, details):
        apply_awards(cand, detail)
        if {target.get("defense_tier"), cand.get("defense_tier")} == {"elite", "weak"}:
            continue
        out.append(cand)
    return out or candidates


def same_player(a, b):
    from services.nba_external import normalize_name

    name_a, name_b = (normalize_name(p.get("name", "")) for p in (a, b))
    return (a["id"] == b["id"] or bool(name_a and name_a == name_b)
            or bool(a.get("espn_id") and str(a["espn_id"]) == str(b.get("espn_id"))))


def resolve_cached(target: Dict[str, Any], pool: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Pořadí podle role a střelby, uvnitř nejbližší skupiny podle shody."""
    if not target.get("pts"):
        return None
    from services.nba_external import normalize_name

    candidates = [c for c in pool if not same_player(target, c) and c["pts"] > 0
                  and abs(target["height_cm"] - c["height_cm"]) <= 12
                  and min(c["pts"], target["pts"]) / max(c["pts"], target["pts"]) >= 0.65
                  and (_feature_gap(target, c, "rel_3par") is None
                       or _feature_gap(target, c, "rel_3par") <= .20 + 1e-9)]
    if not candidates:
        return None
    ranked = sorted(candidates, key=lambda c: (-_similarity(target, c)["match_pct"], c["id"]))
    unique = []
    for candidate in ranked:
        if not any(same_player(candidate, other) for other in unique):
            unique.append(candidate)
        if len(unique) == 3:
            break
    ranked = unique
    chosen = ranked[0]
    sim = _similarity(target, chosen)
    texts = _fallback_texts(target, chosen)
    return {
        "engine_version": ENGINE_VERSION,
        "player_id": target["id"], "player_name": target["name"],
        "player_role": target["role_label"], "player_tier": target["tier_label"],
        "closest": {"id": chosen["id"], "full_name": chosen["name"],
                    "position": chosen["position"], "role_label": chosen["role_label"], **sim},
        "top_3_candidates": [{"id": c["id"], "name": c["name"], "match_pct": _similarity(target, c)["match_pct"], "why": _fallback_why(target, c)} for c in ranked[:3]],
        "match_percentage": sim["match_pct"],
        "reasoning": _fallback_reasoning(target), **texts,
        "breakdown": {"herni_styl": texts["style_comparison"], "fyzicko": texts["physical_comparison"],
                      "statisticky_dopad": texts["stats_comparison"]},
        "ai_used": False, "two_phase": False,
        "generated_at": datetime.utcnow().isoformat(),
    }


def resolve(
    target: Dict[str, Any],
    pool: List[Dict[str, Any]],
    use_ai: bool = True,
    suggested: Optional[List[Dict[str, Any]]] = None,
    allow_below_pool: bool = False,
) -> Optional[Dict[str, Any]]:
    """
    Vybere nejbližšího hráče. AI rozhoduje o stylu, backend dodává čísla.
    Když AI není k dispozici, použije se první kandidát z předvýběru –
    výsledek je pak pořád stejný a čitelný.
    """
    # Fáze 2 dvoufázového výběru: AI navrhla jména, backend jim za běhu
    # stáhl data. Vítěze určuje matematika (nejvyšší reálná shoda), ne AI.
    suggested_mode = bool(suggested)
    if suggested_mode:
        candidates = [
            c for c in suggested
            if c["id"] != target["id"] and _norm(c["name"]) != _norm(target["name"])
        ]
    else:
        candidates = preselect(target, pool, stats_filler=_fill_candidate_stats)
    if not candidates:
        return None

    # Legendy a hráči mimo sezónní tabulku mají jen jméno a míry. Doplní se
    # jim profil vrcholu kariéry – ale jen nejbližším podle postavy a role,
    # aby se na jedno hledání nestahovaly stovky profilů.
    lacking = [
        c for c in candidates
        if _num(c.get("pts")) <= 0 and c["id"] != target["id"]
    ]
    if lacking:
        lacking = sorted(
            lacking,
            key=lambda c: (
                -_physical_similarity(target, c),
                -_style_similarity(target, c),
                c["id"],
            ),
        )[:24]
        filled = {
            c["id"]: c for c in _fill_candidate_stats(target, lacking)
        }
        candidates = [filled.get(c["id"], c) for c in candidates]
    candidates = [c for c in candidates if _num(c.get("pts")) > 0]
    if not candidates:
        return None
    # Ještě jednou: po výběru kandidátů se doplní ti, kteří zůstali bez
    # čísel (např. Kobe a Pippen se do výběru dostali jen mírami).
    still = [c for c in candidates if _num(c.get("pts")) <= 0]
    if still:
        filled2 = {c["id"]: c for c in _fill_candidate_stats(target, still)}
        candidates = [filled2.get(c["id"], c) for c in candidates]
    candidates = [c for c in candidates if _num(c.get("pts")) > 0] or candidates
    candidates = enrich_awards(target, candidates)
    if not candidates:
        return None

    by_name = {_norm(c["name"]): c for c in candidates}

    ai: Optional[Dict[str, Any]] = None
    if use_ai:
        ai = _call_gemini_json(_build_prompt(target, candidates))

    chosen: Optional[Dict[str, Any]] = None
    top_three: List[Dict[str, Any]] = []

    if ai:
        for entry in (ai.get("top_3_candidates") or [])[:3]:
            name = entry.get("name") if isinstance(entry, dict) else None
            match = by_name.get(_norm(name or ""))
            if match:
                top_three.append(
                    {
                        "id": match["id"],
                        "name": match["name"],
                        "why": (entry.get("why") or "").strip(),
                    }
                )
        picked = by_name.get(_norm((ai.get("closest_player_name") or "").strip()))
        # AI smí vybrat jen z kandidátů; když se netrefí, vezme se první z top 3
        chosen = picked or (by_name.get(_norm(top_three[0]["name"])) if top_three else None)

    if chosen is not None and not suggested_mode:
        # AI nesmí prosadit volbu, která je matematicky výrazně horší než
        # nejpodobnější kandidát (rozhoduje matematika, AI jen navrhuje).
        best = max(candidates, key=lambda c: _similarity(target, c)["match_pct"])
        if _similarity(target, best)["match_pct"] - _similarity(target, chosen)["match_pct"] > 6.0:
            chosen = best

    if suggested_mode and len(candidates) >= 2:
        # Návrhy od AI musí mít aspoň nějakou shodu. Když ani jeden
        # nepřesáhne 40 %, je to špatný návrh a rozhodne předvýběr.
        if max(_similarity(target, c)["match_pct"] for c in candidates) < 40.0:
            logger.info("Nejbližší hráč: návrhy AI mají nízkou shodu, bere se předvýběr")
            # Volba AI z takových návrhů se nesmí použít (Jordan dostal
            # Amena Thompsona s 28 %) – rozhoduje celý seznam kandidátů.
            return resolve(target, pool, use_ai=False)

    if suggested_mode and len(candidates) < 2:
        # Z návrhů zbyl jediný kandidát – s jedním se nedá vybírat, takže
        # se rozhodne podle celého seznamu (a ten jediný zůstane v nabídce).
        return resolve(target, pool, use_ai=use_ai)

    if suggested_mode:
        # matematika přebíjí AI: vítěz = nejvyšší shoda mezi navrženými
        ranked = sorted(candidates, key=lambda c: (-_similarity(target, c)["match_pct"], c["id"]))
        chosen = ranked[0]
        top_three = [{"id": c["id"], "name": c["name"], "why": ""} for c in ranked[:3]]
        # Když jsou navržení hráči slabší kategorií než cílový hráč, nesmí
        # vyhrát jen proto, že AI jiného nenavrhla. Srovnává se s celým
        # seznamem kandidátů, kde jsou i hráči ze stejné kategorie dopadu.
        # (Kawhi tak místo Jarena Jacksona dostane křídlo stejné úrovně.)
        if allow_below_pool and ranked[0]["pts"] < 0.85 * target["pts"]:
            best = resolve(target, pool, use_ai=False)
            if best and best["closest"]["match_pct"] >= _similarity(target, ranked[0])["match_pct"]:
                return best

    if chosen is not None and not suggested_mode:
        # AI smí vybrat jen z pěti nejlepších podle předvýběru (role a
        # archetyp). Jinak výsledek závisel na tom, zda Gemini odpověděla:
        # Jordan jednou Wade, jindy Amen Thompson s 28 %.
        head_ids = {
            c["id"] for c in [x for x in candidates if x["id"] != target["id"]][:5]
        }
        if chosen["id"] not in head_ids:
            chosen = None
            ai = None
            top_three = []

    if chosen is None:
        # Bez AI rozhoduje pořadí předvýběru: nejdřív se hledá mezi hráči,
        # kteří sedí rolí a archetypem (prvních pět). Teprve když tam nikdo
        # není, bere se nejpodobnější z celého seznamu. Bez toho by vyhrál
        # hráč, který má stejná čísla, ale hraje něco jiného (Jordan by
        # dostal Shai Gilgeous-Alexandera místo Kobeho).
        # Mezi nimi rozhoduje pořadí předvýběru, ne procenta – stejná role
        # a archetyp je důležitější než to, že čísla sedí o pár bodů víc.
        # Z pěti nejlepších z předvýběru vyhraje ten s nejvyšší reálnou
        # shodou. Dřív se bral první z pořadí, což dalo Kawhimu Cadea
        # Cunninghama (91 %) místo skutečně podobného křídla.
        head = [c for c in candidates if c["id"] != target["id"]][:5]
        if head:
            chosen = max(head, key=lambda c: (_similarity(target, c)["match_pct"], -c["id"]))
        else:
            chosen = candidates[0]
        ordered = sorted(
            [c for c in candidates if c["id"] != target["id"]],
            key=lambda c: -_similarity(target, c)["match_pct"],
        )
        top_three = [{"id": c["id"], "name": c["name"], "why": ""} for c in ordered[:3]]

    sim = _similarity(target, chosen)
    texts = _fallback_texts(target, chosen)
    reasoning = _fallback_reasoning(target)
    if ai:
        for key in ("style_comparison", "physical_comparison", "stats_comparison"):
            value = (ai.get(key) or "").strip()
            if value:
                texts[key] = value
        if (ai.get("reasoning") or "").strip():
            reasoning = ai["reasoning"].strip()

    # Každý kandidát musí mít důvod, proč tam je – bez něj UI vypadá, že
    # se nic nenačetlo. Když ho AI nedodala, odvodí se z čísel.
    if not top_three:
        top_three = [{"id": c["id"], "name": c["name"], "why": ""} for c in candidates[:3]]
    by_cand_id = {c["id"]: c for c in candidates}
    top_three = [
        dict(
            c,
            why=(c.get("why") or "").strip()
            or (_fallback_why(target, by_cand_id[c["id"]]) if c.get("id") in by_cand_id else ""),
        )
        for c in top_three
    ]

    return {
        "engine_version": ENGINE_VERSION,
        "player_id": target["id"],
        "player_name": target["name"],
        "player_role": target["role_label"],
        "player_tier": target["tier_label"],
        "closest": {
            "id": chosen["id"],
            "full_name": chosen["name"],
            "position": chosen["position"],
            "role_label": chosen["role_label"],
            "tier_label": chosen["tier_label"],
            "match_pct": sim["match_pct"],
            "style_pct": sim["style_pct"],
            "physical_pct": sim["physical_pct"],
            "stats_pct": sim["stats_pct"],
            # starší pole pro štítky v UI
            "stylistic_pct": sim["style_pct"],
            "statistical_pct": sim["stats_pct"],
        },
        "reasoning": reasoning,
        "top_3_candidates": top_three,
        "match_percentage": round(sim["match_pct"]),
        "style_comparison": texts["style_comparison"],
        "physical_comparison": texts["physical_comparison"],
        "stats_comparison": texts["stats_comparison"],
        # pole ze starší verze – frontend je pořád umí zobrazit
        "breakdown": {
            "herni_styl": texts["style_comparison"],
            "fyzicko": texts["physical_comparison"],
            "statisticky_dopad": texts["stats_comparison"],
        },
        "ai_used": bool(ai),
        "two_phase": suggested_mode,
        "generated_at": datetime.utcnow().isoformat(),
    }

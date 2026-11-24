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

# Když se změní prompt nebo logika, zvyš číslo – stará cache se přestane používat.
ENGINE_VERSION = 19

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
    # Když se trojky nedaly zjistit (kandidát z ESPN), odhadnou se z objemu
    # střelby a šestek. Když ale zdroj uvádí nulu, je to skutečná nula –
    # Jordan (1986-88) trojky skoro neházel a nesmí se z něj stát trojkař.
    if stat.get("fg3a") is None:
        stat = dict(stat)
        fta_guess = _num(stat.get("fta"), 0.0)
        three_guess = max(fga * 0.25 - fta_guess * 0.4, 0.6)
        stat["fg3a"] = round(min(three_guess, fga * 0.6), 2)
        stat["fg3m"] = round(stat["fg3a"] * 0.35, 2)
        stat["fgm"] = _num(stat.get("fgm"), 0.0) or round(
            (_num(stat.get("pts"), 0.0) - 0.44 * fta_guess - 3 * stat["fg3m"]) / 2.0, 2
        )
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
        # Podíl střel, které jdou z bezprostřední blízkosti koše. NBA API
        # přesnou vzdálenost nemá, ale dá se odhadnout: hráč, který nedá
        # trojky, střílí zblízka i ze střední vzdálenosti – proto se
        # „blízko koše" bere z poměru dvoubodových střel a šestek.
        "rim_rate": _clamp((two_pa * 0.62) / fga, 0.0, 1.0),
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
    season_hint = (seasons_list[0] if seasons_list else None) or stat.get("season")
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
    profile = {
        "role_group": group,
        "height_cm": _num(height_cm, 198.0),
        "position_type": position_type(position, height_cm),
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
        "ft_pct": ft_pct,
        "fgm": fgm,
        "ftm": ftm,
        "creator": round(play_style["creator"], 3),
        "rebounder": round(play_style["rebounder"], 3),
        "volume": round(play_style["volume"], 3),
        "athletic": round(play_style["athletic"], 3),
    }
    arch = archetype(profile)
    profile["scoring_mode"] = scoring_mode(profile)

    return {
        "id": player_id,
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
        "ft_pct": ft_pct,
        "three_rate": round(three_rate, 3),
        "two_rate": round(shot_profile["two_rate"], 3),
        "paint_share": round(shot_profile["paint_share"], 3),
        "creator": round(play_style["creator"], 3),
        "rebounder": round(play_style["rebounder"], 3),
        "volume": round(play_style["volume"], 3),
        "athletic": round(play_style["athletic"], 3),
        "rim_rate": round(shot_profile["rim_rate"], 3),
        "three_pts_share": round(shot_profile["three_pts_share"], 3),
        "ft_pts_share": round(shot_profile["ft_pts_share"], 3),
        "usage": round(usage, 3),
        "ts": round(ts, 3),
        "fta": fta,
        "scoring_mode": profile["scoring_mode"],
        "role_group": group,
        "role_label": ROLE_GROUP_LABEL[group],
        "position_type": position_type(position, height_cm),
        "position_label": POSITION_LABEL[position_type(position, height_cm)],
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


def compare_pair(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    """
    Porovnání dvou hráčů stejnou logikou, jakou používá „nejbližší hráč".
    Vrací stejné tři dílčí čísla (styl / fyzično / statistiky) i celkovou
    shodu, takže stránka s porovnáváním a hlavní stránka nikdy neukážou
    u stejné dvojice jiné procento.
    """
    sim = _similarity(a, b)
    style_note = _style_note(a, b)
    same_arch = a["archetype"] == b["archetype"]
    same_pos = a["position_type"] == b["position_type"]
    return {
        "match_pct": sim["match_pct"],
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
        share_gap = abs(
            target.get("three_pts_share", 0.0) - c.get("three_pts_share", 0.0)
        )
        if share_gap > 0.18:
            return 15
        # Střelecký profil: elitní trojkař a hráč bez trojky nejsou stejný typ
        if abs(target.get("gravity", 1) - c.get("gravity", 1)) >= 2:
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


def _call_gemini_json(prompt: str) -> Optional[Dict[str, Any]]:
    api_key = _gemini_key()
    if not api_key:
        logger.warning("AI výběr nejbližšího hráče: chybí GEMINI_API_KEY")
        return None
    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=15000))
        response = client.models.generate_content(
            model=os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite"),
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0,
                top_p=0,
                top_k=1,
                seed=7,
                response_mime_type="application/json",
                system_instruction=SYSTEM_PROMPT,
            ),
        )
        text = (response.text or "").strip()
        if text.startswith("```"):
            text = text.strip("`")
            text = text[text.find("{") :]
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except Exception as exc:  # pragma: no cover
        logger.warning("AI výběr nejbližšího hráče selhal (použije se předvýběr): %s", exc)
        return None


# --------------------------------------------------------------------------- #
# 6. Procenta shody – počítá backend z reálných dat, ne AI
# --------------------------------------------------------------------------- #

def _similarity(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, float]:
    """Tři dílčí čísla pro štítky v UI (styl / fyzično / statistiky)."""
    # styl: archetyp (35), pozice (18), odkud skóruje (18), trojky (12),
    # tvorba (9), objem hry (6), efektivita (6), šestky (6)
    style = 30.0 if a["archetype"] == b["archetype"] else 0.0
    style += 0.12 * position_score(a, b)
    # Pod košem, nebo za trojkou – tohle je hlavní rozdíl mezi Giannisem
    # (91 % střel za dva) a Durantem (73 %), i když mají stejné body.
    # Hlavní věc: odkud hráč skóruje. Kolik bodů jde z trojek, z šestek
    # a z blízkosti koše – z toho se pozná střelec od hráče, který žije
    # z nájezdů. Váží nejvíc, protože o stylu rozhoduje nejvíc.
    style += _clamp(22.0 - abs(a.get("three_pts_share", 0) - b.get("three_pts_share", 0)) * 55.0)
    style += _clamp(10.0 - abs(a.get("ft_pts_share", 0) - b.get("ft_pts_share", 0)) * 60.0)
    style += _clamp(10.0 - abs(a.get("two_rate", 0) - b.get("two_rate", 0)) * 22.0)
    style += _clamp(8.0 - abs(a["three_rate"] - b["three_rate"]) * 12.0)
    style += _clamp(9.0 - abs(a["ast"] - b["ast"]) * 2.0)
    style += _clamp(7.0 - abs(a.get("creator", 0) - b.get("creator", 0)) * 20.0)
    style += _clamp(7.0 - abs(a.get("rebounder", 0) - b.get("rebounder", 0)) * 22.0)
    style += _clamp(5.0 - abs(a.get("volume", 0) - b.get("volume", 0)) * 18.0)
    style += _clamp(4.0 - abs(a["usage"] - b["usage"]) * 30.0)
    style += _clamp(3.0 - abs(a["ts"] - b["ts"]) * 60.0)
    style += _clamp(4.0 - abs(a["fta"] - b["fta"]) * 1.2)
    # Střelec a slasher nejsou stejný hráč, i když mají stejnou pozici
    if a.get("scoring_mode") != b.get("scoring_mode"):
        style -= 18.0
    # Jiná pozice je vždy srážka – křídelní pivot není křídlo
    if a["position_type"] != b["position_type"]:
        style -= 12.0
    # Obrana: elitní obránce (DPOY, All-Defensive) nikdy nedostane slabého
    style -= defense.defense_penalty(a.get("defense_tier", "average"), b.get("defense_tier", "average"))
    # Střelecký profil: elitní trojkař se nespojuje s hráčem bez trojky
    g_gap = abs(a.get("gravity", 1) - b.get("gravity", 1))
    style -= {0: 0.0, 1: 4.0, 2: 14.0}.get(g_gap, 24.0)
    # Stejná pozice a stejný archetyp = plná shoda ve stylu, ale jen když
    # se shoduje i to, odkud hráč skóruje.
    if (
        a["archetype"] == b["archetype"]
        and a["position_type"] == b["position_type"]
        and abs(a.get("three_pts_share", 0) - b.get("three_pts_share", 0)) <= 0.06
        and abs(a.get("two_rate", 0) - b.get("two_rate", 0)) <= 0.18
    ):
        style = max(style, 95.0)

    # fyzično: výška, váha a typ postavy (křídlo vs. podkošový hráč se pozná)
    h = _clamp(100.0 - abs(a["height_cm"] - b["height_cm"]) * 6.0)
    w = _clamp(100.0 - abs(a["weight_kg"] - b["weight_kg"]) * 5.0)
    build_a = a["weight_kg"] / max(a["height_cm"], 1.0)
    build_b = b["weight_kg"] / max(b["height_cm"], 1.0)
    build = _clamp(100.0 - abs(build_a - build_b) * 900.0)
    physical = 0.58 * h + 0.10 * w + 0.32 * build
    # Typ postavy a atletičnost (explozivní atlet vs. dlouhý střelec vs.
    # technický hráč): stejná výška nestačí, když se hráči jinak pohybují.
    if a.get("build_type") != b.get("build_type"):
        physical -= 9.0
    physical -= min(abs(a.get("athletic_score", 0.5) - b.get("athletic_score", 0.5)) * 40.0, 14.0)
    physical = _clamp(physical)

    # statistiky: body, doskoky, efektivita, usage
    # Na 100 držení (tempo éry), když jsou k dispozici; jinak základní průměry.
    if a.get("pts100") is not None and b.get("pts100") is not None:
        pts = _clamp(100.0 - abs(a["pts100"] - b["pts100"]) * 3.0)
        reb_a, reb_b = (a.get("reb100") or a["reb"]), (b.get("reb100") or b["reb"])
        reb = _clamp(100.0 - abs(reb_a - reb_b) * 5.0)
    else:
        pts = _clamp(100.0 - abs(a["pts"] - b["pts"]) * 4.0)
        reb = _clamp(100.0 - abs(a["reb"] - b["reb"]) * 7.0)
    ts = _clamp(100.0 - abs(a["ts"] - b["ts"]) * 220.0)
    usage = _clamp(100.0 - abs(a["usage"] - b["usage"]) * 160.0)
    # Statistiky: hlavně zdroj skórování, ne kolik bodů – dva hráči, kteří
    # skórují stejně, jsou si blízcí i s jiným průměrem bodů.
    scoring = 0.55 * (
        100.0
        - abs(a.get("three_pts_share", 0) - b.get("three_pts_share", 0)) * 200.0
        - abs(a.get("ft_pts_share", 0) - b.get("ft_pts_share", 0)) * 120.0
    )
    scoring = _clamp(scoring)
    stats = 0.55 * scoring + 0.2 * pts + 0.15 * reb + 0.1 * usage
    # Ocenění (MVP, All-NBA, All-Defensive, DPOY): podobný dopad = podobná čísla
    aw_a = sum((a.get("award_detail") or {}).values())
    aw_b = sum((b.get("award_detail") or {}).values())
    stats = _clamp(stats - min(abs(aw_a - aw_b) * 1.2, 10.0))

    # Styl a fyzično rozhodují o tom, kdo je „nejbližší hráč"; statistiky
    # (vrchol na 100 držení a ocenění) jsou kontrola, proto váží méně.
    total = 0.62 * style + 0.22 * physical + 0.16 * stats
    # Kategorie dopadu: superstar (35 b) a hráč na 21 bodů nejsou „stejní".
    # Rozdíl v objemu bodů se počítá podílem, ne rozdílem.
    if a.get("pts") and b.get("pts"):
        ratio = min(a["pts"], b["pts"]) / max(a["pts"], b["pts"])
        if ratio < 0.85:
            total -= (0.85 - ratio) * 90.0
    # Elitní obránce (DPOY) a slabý obránce nejsou „nejbližší hráči",
    # ani když sedí čísla i postava – srážka se propíše do celkového čísla.
    tier_penalty = defense.defense_penalty(
        a.get("defense_tier", "average"), b.get("defense_tier", "average")
    )
    if tier_penalty:
        total -= tier_penalty * 0.6
    # Strop: stejný styl nestačí na 99 %, když se hráči liší postavou.
    # Dřív tu byl strop 70 + 0,28 × fyzično, který shodil i dvojice se
    # shodou 95 % ve stylu (Jordan–Kobe na 68,7 %).
    if physical < 95.0:
        total = min(total, 78.0 + physical * 0.21)
    return {
        "match_pct": round(min(99.0, _clamp(total)), 1),
        "style_pct": round(min(99.0, _clamp(style)), 1),
        "physical_pct": round(_clamp(physical), 1),
        "stats_pct": round(_clamp(stats), 1),
    }


# --------------------------------------------------------------------------- #
# 7. Texty bez AI – aby karta nebyla nikdy prázdná
# --------------------------------------------------------------------------- #

def _fallback_texts(target: Dict[str, Any], cand: Dict[str, Any]) -> Dict[str, str]:
    same = target["role_group"] == cand["role_group"]
    style = (
        f"Oba patří mezi {cand['role_label']}, "
        + ("takže řeší stejné situace na hřišti. " if same else "byť každý s jiným těžištěm hry. ")
        + f"Střelba: {target.get('gravity_label', '?')} vs {cand.get('gravity_label', '?')}. "
        + f"Obrana: {target.get('defense_label', '?')} vs {cand.get('defense_label', '?')}."
    )
    physical = (
        f"{target['height_cm']:.0f} vs {cand['height_cm']:.0f} cm, "
        f"{target['weight_kg']:.0f} vs {cand['weight_kg']:.0f} kg. "
        f"Typ postavy: {target.get('build_label', '?')} vs {cand.get('build_label', '?')}."
    )
    stats = (
        f"Vrchol kariéry na 100 držení: {_fmt(target.get('pts100'))}/{_fmt(target.get('reb100'))}/"
        f"{_fmt(target.get('ast100'))} vs {_fmt(cand.get('pts100'))}/{_fmt(cand.get('reb100'))}/"
        f"{_fmt(cand.get('ast100'))}; TS {target['ts'] * 100:.1f} % vs {cand['ts'] * 100:.1f} %. "
        f"Ocenění: {_award_text(target)} vs {_award_text(cand)}."
    )
    return {
        "style_comparison": style,
        "physical_comparison": physical,
        "stats_comparison": stats,
    }


def _fallback_reasoning(target: Dict[str, Any]) -> str:
    return (
        f"{target['name']} je {target['role_label']} na úrovni "
        f"{target['tier_label']}, proto se shoda hledá ve stejné roli "
        f"a stejné kategorii dopadu."
    )


# --------------------------------------------------------------------------- #
# 8. Hlavní funkce
# --------------------------------------------------------------------------- #

SUGGEST_PROMPT = """Jsi NBA analytik. Navrhni 5 hráčů NBA (jakékoli éry, ne zadaného hráče),
kteří mají nejbližší herní styl k zadanému hráči v jeho vrcholu.
Posuzuj: herní styl a roli, ATLETIČNOST a typ postavy (explozivní atlet /
dlouhý hubený střelec / technický neexplozivní hráč), STŘELECKÝ profil
(elitní trojkař vs. bez spolehlivé trojky), OBRANNOU úroveň (elitní obránce
nikdy se slabým) a éru. Vrať POUZE JSON: {"candidates": ["Jméno 1", ... 5 jmen]}"""


def ai_suggest(target: Dict[str, Any]) -> List[str]:
    """
    Fáze 1: AI navrhne 4–5 jmen. Bez klíče nebo při chybě vrací [].

    Klíč se bere z prostředí (GEMINI_API_KEY / GOOGLE_API_KEY) a z nastavení
    aplikace (backend/settings.py) – na serveru se klíč vkládá do prostředí
    přes proměnnou GEMINI_API_KEY.
    """
    api_key = _gemini_key()
    if not api_key:
        logger.warning("AI návrh kandidátů: chybí GEMINI_API_KEY")
        return []
    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=15000))
        response = client.models.generate_content(
            model=os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite"),
            contents="HRÁČ (vrchol kariéry):\n" + _one_line(target),
            config=types.GenerateContentConfig(
                temperature=0, top_p=0, top_k=1, seed=7,
                response_mime_type="application/json",
                system_instruction=SUGGEST_PROMPT,
            ),
        )
        text = (response.text or "").strip()
        if text.startswith("```"):
            text = text.strip("`")
            text = text[text.find("{"):]
        names = json.loads(text).get("candidates") or []
        return [str(n).strip() for n in names if str(n).strip()][:5]
    except Exception as exc:  # pragma: no cover
        logger.warning("AI návrh kandidátů selhal: %s", exc)
        return []


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
        candidates = preselect(target, pool)
    if not candidates:
        return None
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

    if not top_three:
        top_three = [{"id": c["id"], "name": c["name"], "why": ""} for c in candidates[:3]]

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

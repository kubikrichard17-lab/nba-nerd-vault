import os
import logging
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")


def _call_gemini(prompt: str) -> Optional[str]:
    """Helper to query Gemini API if API key is present."""
    if not GEMINI_API_KEY:
        return None
    try:
        from google import genai
        from google.genai import types as _t
        client = genai.Client(api_key=GEMINI_API_KEY, http_options=_t.HttpOptions(timeout=15000))
        response = client.models.generate_content(
            model=os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite"),
            contents=prompt
        )
        if response and response.text:
            return response.text.strip()
    except Exception as e:
        logger.warning(f"Volání Gemini API selhalo (použije se fallback): {e}")
    return None


def generate_scouting_report(
    full_name: str,
    position: Optional[str],
    height_cm: Optional[float],
    stats: List[Dict[str, Any]],
    awards: List[str],
    tags: List[str]
) -> str:
    """Generate a concise 3-sentence scouting report in Czech."""
    # Compute career averages
    # Starší sezóny nemají zisky a bloky (měří se až od 70. let), takže se
    # chybějící hodnoty berou jako nula – jinak by celý profil spadl.
    def _num(row: Dict[str, Any], field: str) -> float:
        value = row.get(field)
        if value is None or value != value:  # None nebo NaN
            return 0.0
        return float(value)

    total_gp = sum(int(r.get("gp") or 0) for r in stats)
    if total_gp > 0:
        def _avg(field: str) -> float:
            return round(
                sum(
                    _num(r, field) * int(r.get("gp") or 0)
                    for r in stats
                    if int(r.get("gp") or 0) > 0
                )
                / total_gp,
                1,
            )

        pts = _avg("pts")
        reb = _avg("reb")
        ast = _avg("ast")
        stl = _avg("stl")
        blk = _avg("blk")
    else:
        pts = reb = ast = stl = blk = 0.0

    # Try Gemini API first
    prompt = f"""Jsi elitní skaut NBA. Napiš přesně 3 české věty jako profesionální scouting report pro hráče: {full_name}.
Data hráče:
- Pozice: {position or 'N/A'}, Výška: {height_cm or 'N/A'} cm
- Kariérní průměry: {pts} bodů, {reb} doskoků, {ast} asistencí, {stl} zisků, {blk} bloků
- Trofeje/ocenění: {', '.join(awards[:5]) if awards else 'Bez významných trofejí'}
- Herní styl tagy: {', '.join(tags)}

Pravidla:
1. První věta popisuje způsob zakončení, útočnou dominanci a střelbu.
2. Druhá věta popisuje tvorbu hry, fyzické předpoklady nebo obranný přínos.
3. Třetí věta shrnuje jeho celkový basketbalový odkaz a vliv na vítězství týmu.
Odpověz POUZE těmito 3 větami v češtině."""

    gemini_result = _call_gemini(prompt)
    if gemini_result:
        return gemini_result

    # High quality fallback in Czech
    pos_desc = position or "všestranný hráč"
    height_desc = f"se svými {height_cm} cm " if height_cm else ""

    # Sentence 1: Offensive profile
    if pts >= 25.0:
        s1 = f"{full_name} patří k nejničivějším útočným zbraním NBA s průměrem {pts} bodu na zápas a schopností skórovat z jakékoliv pozice na palubovce."
    elif pts >= 18.0:
        s1 = f"{full_name} se vyznačuje vysokou ofenzivní konzistencí a spolehlivým zakončením s kariérním průměrem {pts} bodu."
    else:
        s1 = f"{full_name} na pozici {pos_desc} staví svou hru především na efektivním týmovém pojetí a taktické disciplíně v útoku."

    # Sentence 2: Playmaking / Defense / Physicality
    if ast >= 7.0:
        s2 = f"Díky vynikajícímu perifernímu vidění a {ast} asistencím na utkání funguje jako absolutní generál tempa a tvůrce volných střel pro své spoluhráče."
    elif reb >= 9.0 and blk >= 1.5:
        s2 = f"{height_desc.capitalize()}naprosto ovládá prostor pod košem, kde sbírá {reb} doskoku a s {blk} bloku na zápas vytváří neprostupný defenzivní val."
    elif stl >= 1.5 or blk >= 1.0:
        s2 = f"V defenzívě vyniká rychlým čtením soupeřových přihrávek a tvrdým presinkem na míč, což z něj činí obávaného obránce perimetru."
    else:
        s2 = f"Jeho herní všestrannost podtrhují vyrovnané statistiky doskoků ({reb} RPG) i přihrávek ({ast} APG) při vysokém herním nasazení."

    # Sentence 3: Legacy & Impact
    top_awards = [a for a in awards if any(k in a.lower() for k in ["mvp", "šampion", "champion", "all-star", "slávy"])]
    if top_awards:
        s3 = f"Zisk trofejí jako {top_awards[0]} jen potvrzuje jeho trvalý odkaz a nezpochybnitelný status mezi legendami soutěže."
    else:
        s3 = "Svým neutuchajícím nasazením a basketbalovým IQ představuje neocenitelný stavební kámen každé vítězné rotace."

    return f"{s1} {s2} {s3}"


def generate_comparison_verdict(
    p1_name: str,
    p2_name: str,
    p1_data: Dict[str, Any],
    p2_data: Dict[str, Any],
    match_pct: float,
    physical_pct: float,
    stat_pct: float,
    style_pct: float
) -> str:
    """Generate concise AI comparison verdict in Czech."""
    prompt = f"""Jsi basketbalový analytik NBA Nerd Vault. Porovnej herní styl dvou hráčů v češtině do 3 vět.
Hráč 1: {p1_name} ({p1_data.get('position', '')}, {p1_data.get('height_cm', '')} cm) - {p1_data.get('pts', 0)} PPG, {p1_data.get('reb', 0)} RPG, {p1_data.get('ast', 0)} APG. Tagy: {', '.join(p1_data.get('tags', []))}
Hráč 2: {p2_name} ({p2_data.get('position', '')}, {p2_data.get('height_cm', '')} cm) - {p2_data.get('pts', 0)} PPG, {p2_data.get('reb', 0)} RPG, {p2_data.get('ast', 0)} APG. Tagy: {', '.join(p2_data.get('tags', []))}
Výsledky matematické shody:
- Celková shoda: {match_pct}%
- Fyzická shoda: {physical_pct}%
- Statistická shoda: {stat_pct}%
- Stylistická shoda: {style_pct}%

Napiš stručný, úderný 3větý analytický verdikt v češtině srovnávající jejich herní profily, největší shody a odlišnosti."""

    gemini_result = _call_gemini(prompt)
    if gemini_result:
        return gemini_result

    # Deterministic fallback in Czech
    p1_pts = p1_data.get('pts', 0)
    p2_pts = p2_data.get('pts', 0)
    
    if match_pct >= 80:
        v1 = f"{p1_name} a {p2_name} vykazují mimořádně vysokou celkovou shodu {match_pct} %, což se projevuje téměř identickým způsobem pojetí hry a rolí na hřišti."
    elif match_pct >= 60:
        v1 = f"Srovnání mezi {p1_name} a {p2_name} ukazuje solidní shodu {match_pct} %, přičemž oba sdílejí podobné parametry ve vedení ofenzívy."
    else:
        v1 = f"Porovnání {p1_name} a {p2_name} dosahuje shody {match_pct} %, což poukazuje na výrazně odlišné taktické role a typologii hráčů."

    if physical_pct >= 75:
        v2 = f"Fyzicky jsou si oba atleti velice blízcí ({physical_pct} % shoda parametrů výšky a váhy), což jim umožňovalo dominovat ve stejném prostoru palubovky."
    else:
        v2 = f"Hlavní rozdíl spočívá ve fyzických proporcích a pozici ({physical_pct} % fyzická shoda), kde každý využívá jiné biomechanické přednosti."

    pts_diff = abs(p1_pts - p2_pts)
    if pts_diff < 3.0:
        v3 = f"V zakončení jsou oba prakticky stejně produktivní ({p1_pts:.1f} vs {p2_pts:.1f} PPG), což z nich činí fascinující all-time paralelu pro každého basketbalového nadšence."
    else:
        higher = p1_name if p1_pts > p2_pts else p2_name
        v3 = f"Zatímco {higher} disponuje větším objemem přímého skórování, druhý z dvojice nabízí odlišné nuance v distribuci míče a defenzivním přínosu."

    return f"{v1} {v2} {v3}"

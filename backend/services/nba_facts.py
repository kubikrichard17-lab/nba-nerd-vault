"""
Zajímavosti (fun facts) o NBA hráčích.

Data jsou psaná ručně z ověřených rekordů a milníků NBA – žádné stahování
z cizích webů. Fotku hráče bere aplikace z oficiálního NBA CDN podle ID,
takže obrázek vždy sedí k danému hráči.
"""

from __future__ import annotations

import gzip
import json
import os
import random
import threading
from typing import Any, Dict, List, Optional

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
_GENERATED_FILE = os.path.join(_DATA_DIR, 'facts_generated.json.gz')

_generated: Optional[List[Dict[str, Any]]] = None
_generated_lock = threading.Lock()


def _load_generated() -> List[Dict[str, Any]]:
    """
    Zajímavosti spočítané algoritmem (`build_facts.py`) – čte se jednou
    při startu ze souboru, za běhu žádné stahování ani AI.
    """
    global _generated
    if _generated is not None:
        return _generated
    with _generated_lock:
        if _generated is not None:
            return _generated
        items: List[Dict[str, Any]] = []
        if os.path.exists(_GENERATED_FILE):
            try:
                with gzip.open(_GENERATED_FILE, 'rt', encoding='utf-8') as fh:
                    items = json.load(fh).get('facts', [])
            except Exception:
                items = []
        _generated = items
        return _generated


def reload_generated() -> int:
    """Znovu načte soubor (po spuštění build_facts.py)."""
    global _generated
    _generated = None
    return len(_load_generated())

# id = ID hráče v NBA (stejné jako v DB a v NBA CDN)
FACTS: List[Dict[str, Any]] = [
    {
        "id": "wilt-100",
        "player_id": 76375,
        "player": "Wilt Chamberlain",
        "category": "Rekord",
        "text": "2. března 1962 nastřílel Wilt Chamberlain 100 bodů v jednom zápase – dodnes nepřekonaný rekord NBA. Zápas se nehrál v televizi, takže neexistuje žádný videozáznam.",
    },
    {
        "id": "wilt-minutes",
        "player_id": 76375,
        "player": "Wilt Chamberlain",
        "category": "Rekord",
        "text": "V sezóně 1961-62 odehrál Wilt Chamberlain 48,5 minuty na zápas – tedy víc, než má jedno utkání. Tehdy nastupoval prakticky bez střídání.",
    },
    {
        "id": "wilt-reb",
        "player_id": 76375,
        "player": "Wilt Chamberlain",
        "category": "Rekord",
        "text": "Wilt Chamberlain má 23 924 kariérních doskoků – o 2 300 víc než druhý Bill Russell. Průměr 22,9 doskoku na zápas je nejvyšší v historii.",
    },
    {
        "id": "russell-rings",
        "player_id": 78049,
        "player": "Bill Russell",
        "category": "Trofeje",
        "text": "Bill Russell vyhrál 11 titulů NBA ve 13 sezónách – víc než kterýkoli jiný hráč. Finále NBA dnes nosí jeho jméno (Bill Russell Finals MVP Award).",
    },
    {
        "id": "jordan-63",
        "player_id": 893,
        "player": "Michael Jordan",
        "category": "Rekord",
        "text": "Michael Jordan dal 63 bodů v zápase play-off proti Bostonu v roce 1986 – rekord play-off. Bylo mu tehdy 23 let a vynechal většinu sezóny kvůli zlomené noze.",
    },
    {
        "id": "jordan-ppg",
        "player_id": 893,
        "player": "Michael Jordan",
        "category": "Rekord",
        "text": "Jordan má nejvyšší kariérní průměr v historii: 30,12 bodu na zápas. Přes 30 bodů na utkání se dostal v osmi sezónách.",
    },
    {
        "id": "jordan-6-6",
        "player_id": 893,
        "player": "Michael Jordan",
        "category": "Trofeje",
        "text": "Jordan vyhrál všech šest finále NBA, do kterých nastoupil, a pokaždé byl vyhlášen nejužitečnějším hráčem finále (Finals MVP).",
    },
    {
        "id": "lebron-points",
        "player_id": 2544,
        "player": "LeBron James",
        "category": "Rekord",
        "text": "LeBron James překonal 7. února 2023 Kareema Abdul-Jabbara a stal se nejlepším střelcem historie NBA. Dnes má přes 43 000 bodů.",
    },
    {
        "id": "lebron-20",
        "player_id": 2544,
        "player": "LeBron James",
        "category": "Rekord",
        "text": "LeBron dal víc než 20 bodů ve 20 sezónách za sebou a je jediný hráč s 10 000+ body, doskoky i asistencemi v kariéře.",
    },
    {
        "id": "stockton-ast",
        "player_id": 304,
        "player": "John Stockton",
        "category": "Rekord",
        "text": "John Stockton má 15 806 kariérních asistencí – o 3 200 víc než druhý Chris Paul. Rekord, který se jen tak nepřekoná.",
    },
    {
        "id": "curry-3s",
        "player_id": 201939,
        "player": "Stephen Curry",
        "category": "Rekord",
        "text": "Stephen Curry jako první hráč v historii přesáhl 4 000 kariérních trojek. Jednu sezónu (2015-16) jich dal 402.",
    },
    {
        "id": "curry-unanimous",
        "player_id": 201939,
        "player": "Stephen Curry",
        "category": "Trofeje",
        "text": "V roce 2016 se Curry stal prvním jednomyslně zvoleným MVP v historii NBA – dostal všech 131 hlasů prvního místa.",
    },
    {
        "id": "kareem-scoring",
        "player_id": 76003,
        "player": "Kareem Abdul-Jabbar",
        "category": "Rekord",
        "text": "Kareem Abdul-Jabbar držel rekord v počtu bodů 38 let (1984–2023). Hrál 20 sezón a ve 41 letech byl ještě ve finále NBA.",
    },
    {
        "id": "kobe-81",
        "player_id": 977,
        "player": "Kobe Bryant",
        "category": "Rekord",
        "text": "Kobe Bryant dal 22. ledna 2006 proti Torontu 81 bodů – druhý nejvyšší výkon historie po Wiltově stovce.",
    },
    {
        "id": "kobe-60",
        "player_id": 977,
        "player": "Kobe Bryant",
        "category": "Příběh",
        "text": "Kobe ukončil kariéru zápasem s 60 body – nejvyšší bodový výkon, jaký kdy někdo předvedl ve svém posledním utkání.",
    },
    {
        "id": "duncan-tim",
        "player_id": 1495,
        "player": "Tim Duncan",
        "category": "Trofeje",
        "text": "Tim Duncan vyhrál titul ve třech různých desetiletích (1999, 2003, 2005, 2007, 2014) – celkem pět s jediným klubem, San Antoniem.",
    },
    {
        "id": "magic-rookie",
        "player_id": 77142,
        "player": "Magic Johnson",
        "category": "Příběh",
        "text": "Magic Johnson vyhrál Finals MVP už jako nováček v roce 1980 – nastoupil na pozici pivota za zraněného Kareema a dal 42 bodů.",
    },
    {
        "id": "bird-3pt",
        "player_id": 1449,
        "player": "Larry Bird",
        "category": "Příběh",
        "text": "Larry Bird vyhrál tři soutěže v trojkách za sebou (1986–1988) a při té poslední házel v teplákové bundě, protože se prý nudil.",
    },
    {
        "id": "hakeem-blocks",
        "player_id": 165,
        "player": "Hakeem Olajuwon",
        "category": "Rekord",
        "text": "Hakeem Olajuwon má 3 830 kariérních bloků – nejvíc v historii NBA. Je jediný hráč s 3 000+ bloky a 2 000+ zisky.",
    },
    {
        "id": "shaq-dunk",
        "player_id": 406,
        "player": "Shaquille O'Neal",
        "category": "Příběh",
        "text": "Shaquille O'Neal dvakrát rozbil basketbalovou desku. Jednou v roce 1993 se po jeho smeči celý koš zřítil na palubovku.",
    },
    {
        "id": "westbrook-td",
        "player_id": 201566,
        "player": "Russell Westbrook",
        "category": "Rekord",
        "text": "Russell Westbrook má 200+ triple-doublů v základní části – historický rekord. Sezónu 2016-17 zakončil s průměrem triple-double.",
    },
    {
        "id": "rodman-reb",
        "player_id": 23,
        "player": "Dennis Rodman",
        "category": "Rekord",
        "text": "Dennis Rodman má rekord v podílu doskočených míčů: v sezóně 1994-95 jich sbíral 29,7 % ze všech dostupných – nejvíc v historii.",
    },
    {
        "id": "iverson-size",
        "player_id": 947,
        "player": "Allen Iverson",
        "category": "Příběh",
        "text": "Allen Iverson měřil 183 cm a byl nejmenším hráčem, který kdy vyhrál bodový titul NBA (čtyřikrát).",
    },
    {
        "id": "nash-50-40-90",
        "player_id": 959,
        "player": "Steve Nash",
        "category": "Rekord",
        "text": "Steve Nash se čtyřikrát dostal do klubu 50-40-90 (úspěšnost střelby, trojek a trestných hodů) – nejvíc v historii.",
    },
    {
        "id": "dirk-31500",
        "player_id": 1717,
        "player": "Dirk Nowitzki",
        "category": "Příběh",
        "text": "Dirk Nowitzki strávil celou 21sezónní kariéru v Dallasu – nejdéle u jednoho klubu v historii NBA, a to přes 31 000 bodů.",
    },
    {
        "id": "giannis-mvp",
        "player_id": 203507,
        "player": "Giannis Antetokounmpo",
        "category": "Trofeje",
        "text": "Giannis vyhrál dvakrát MVP a v roce 2021 dovedl Milwaukee k titulu. Ve finále rozhodujícím zápase dal 50 bodů.",
    },
    {
        "id": "jokic-pick",
        "player_id": 203999,
        "player": "Nikola Jokić",
        "category": "Příběh",
        "text": "Nikola Jokić byl draftován jako 41. volba v roce 2014 – v reklamě, která se vysílala, když spal doma v Srbsku. Dnes má tři MVP.",
    },
    {
        "id": "luka-73",
        "player_id": 1629029,
        "player": "Luka Dončić",
        "category": "Rekord",
        "text": "Luka Dončić dal 26. ledna 2024 proti Atlantě 73 bodů – čtvrtý nejvyšší výkon historie NBA.",
    },
    {
        "id": "wemby-blocks",
        "player_id": 1641705,
        "player": "Victor Wembanyama",
        "category": "Rekord",
        "text": "Victor Wembanyama je jediný nováček v historii, který za sezónu nasbíral 1 500 bodů, 700 doskoků, 250 bloků a 100 trojek.",
    },
    {
        "id": "kawhi-fmvp",
        "player_id": 202695,
        "player": "Kawhi Leonard",
        "category": "Trofeje",
        "text": "Kawhi Leonard je jediný hráč, který vyhrál Finals MVP se dvěma různými kluby a nebyl přitom draftován v první desítce (15. volba).",
    },
    {
        "id": "barkley-5-5",
        "player_id": 787,
        "player": "Charles Barkley",
        "category": "Rekord",
        "text": "Charles Barkley měřil 198 cm a přesto patří k nejlepším doskakovačům historie – v roce 1987 jich měl 14,6 na zápas.",
    },
    {
        "id": "pippen-def",
        "player_id": 937,
        "player": "Scottie Pippen",
        "category": "Trofeje",
        "text": "Scottie Pippen byl desetkrát v All-Defensive týmu – jeden z nejlepších obránců historie, i když nikdy nevyhrál obrannou cenu roku.",
    },
    {
        "id": "ray-allen",
        "player_id": 951,
        "player": "Ray Allen",
        "category": "Příběh",
        "text": "Ray Allen rozhodl finále NBA 2013 trojkou v posledních sekundách prodloužení – a Miami pak zápas i celou sérii vyhrálo.",
    },
    {
        "id": "reggie-8s",
        "player_id": 397,
        "player": "Reggie Miller",
        "category": "Příběh",
        "text": "Reggie Miller dal v roce 1995 osm bodů za 8,9 sekundy proti New Yorku – dodnes se tomu říká „Miller Time“.",
    },
    {
        "id": "cp3-assists",
        "player_id": 101108,
        "player": "Chris Paul",
        "category": "Rekord",
        "text": "Chris Paul je druhý v historickém pořadí asistencí (12 500+) a zároveň jeden z nejlepších zlodějů míče všech dob.",
    },
    {
        "id": "westbrook-mvp",
        "player_id": 201566,
        "player": "Russell Westbrook",
        "category": "Trofeje",
        "text": "Westbrook se stal v roce 2017 MVP jako první hráč po Oskaru Robertsonovi (1962), který zakončil sezónu s průměrem triple-double.",
    },
    {
        "id": "duncan-1000",
        "player_id": 1495,
        "player": "Tim Duncan",
        "category": "Rekord",
        "text": "Tim Duncan má 1 000+ vítězných zápasů v kariéře – jediný hráč, který to dokázal jen s jedním klubem.",
    },
    {
        "id": "kareem-skyhook",
        "player_id": 76003,
        "player": "Kareem Abdul-Jabbar",
        "category": "Příběh",
        "text": "Kareemův „skyhook“ je považován za nejužitečnější střelu historie – nedala se blokovat, protože ji házel z výšky 2,18 m přes rameno.",
    },
    {
        "id": "bird-1985",
        "player_id": 1449,
        "player": "Larry Bird",
        "category": "Rekord",
        "text": "Larry Bird je jediný hráč s kariérním průměrem 24+ bodů, 10+ doskoků a 6+ asistencí – a to přesně 24,3 / 10,0 / 6,3.",
    },
    {
        "id": "magic-allstar",
        "player_id": 77142,
        "player": "Magic Johnson",
        "category": "Rekord",
        "text": "Magic Johnson byl 12krát v All-Star a devětkrát ve finále NBA – a v roce 1992 vyhrál i All-Star Game MVP jako vracející se hráč.",
    },
    {
        "id": "harden-3s",
        "player_id": 201935,
        "player": "James Harden",
        "category": "Rekord",
        "text": "James Harden je jediný hráč po Jordanovi, který měl v jedné sezóně průměr 36+ bodů (2018-19: 36,1).",
    },
    {
        "id": "durant-scoring",
        "player_id": 201142,
        "player": "Kevin Durant",
        "category": "Rekord",
        "text": "Kevin Durant je jeden z mála hráčů, kteří mají čtyři bodové tituly NBA, a patří mezi deset nejlepších střelců historie.",
    },
    {
        "id": "kidd-triple",
        "player_id": 467,
        "player": "Jason Kidd",
        "category": "Rekord",
        "text": "Jason Kidd má 107 triple-doublů v základní části – čtvrtý nejvyšší počet historie – a jako trenér dovedl Dallas do finále.",
    },
    {
        "id": "wade-2006",
        "player_id": 2548,
        "player": "Dwyane Wade",
        "category": "Trofeje",
        "text": "Dwyane Wade vyhrál Finals MVP už ve třetí sezóně (2006) a ve finále měl průměr 34,7 bodu na zápas.",
    },
]


def all_facts() -> List[Dict[str, Any]]:
    """Ručně psané zajímavosti + ty spočítané algoritmem."""
    return list(FACTS) + list(_load_generated())


def get_fact(fact_id: str) -> Optional[Dict[str, Any]]:
    for f in all_facts():
        if f["id"] == fact_id:
            return f
    return None


def facts_for_player(player_id: int) -> List[Dict[str, Any]]:
    return [f for f in all_facts() if int(f.get("player_id") or 0) == int(player_id)]


def random_fact(exclude: Optional[str] = None) -> Optional[Dict[str, Any]]:
    facts = all_facts()
    pool = [f for f in facts if f["id"] != exclude] or facts
    return random.choice(pool)


def categories() -> List[str]:
    seen: List[str] = []
    for f in all_facts():
        if f["category"] not in seen:
            seen.append(f["category"])
    return seen

import json
import sys
import os
import time

# Add current directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database import engine, SessionLocal, Base
from models import Player, PlayerSeasonStat, PlayerAward
from services.nba_fetcher import fetch_and_cache_player, calculate_playstyle_tags
from services.ai_scout import generate_scouting_report

# 30 NBA Legends and Superstars for immediate test & comparison
LEGENDS_METADATA = [
    {
        "id": 893, "full_name": "Michael Jordan", "pos": "G", "h_cm": 198.0, "h_ft": "6-6", "w_kg": 98.0, "w_lbs": 216.0,
        "college": "North Carolina", "country": "USA", "draft": ("1984", "1", "3", "Chicago Bulls"), "active": False,
        "pts": 30.1, "reb": 6.2, "ast": 5.3, "stl": 2.3, "blk": 0.8, "fg_pct": 0.497, "fg3_pct": 0.327, "ft_pct": 0.835, "gp": 1072,
        "awards": [("Šampion NBA", 6), ("Nejužitečnější hráč ligy (MVP)", 5), ("MVP Finále NBA", 6), ("Obránce roku (DPOY)", 1), ("Účast v NBA All-Star", 14), ("Síň slávy (Hall of Fame)", 1)],
        "bio": "Michael Jeffrey Jordan je bývalý americký profesionální basketbalista, obecně považovaný za jednoho z nejlepších hráčů všech dob. S týmem Chicago Bulls vybojoval šest titulů šampiona NBA a stal se globální sportovní ikonou."
    },
    {
        "id": 2544, "full_name": "LeBron James", "pos": "F", "h_cm": 206.0, "h_ft": "6-9", "w_kg": 113.0, "w_lbs": 250.0,
        "college": "St. Vincent-St. Mary HS", "country": "USA", "draft": ("2003", "1", "1", "Cleveland Cavaliers"), "active": True,
        "pts": 27.1, "reb": 7.5, "ast": 7.4, "stl": 1.5, "blk": 0.7, "fg_pct": 0.506, "fg3_pct": 0.348, "ft_pct": 0.736, "gp": 1492,
        "awards": [("Šampion NBA", 4), ("Nejužitečnější hráč ligy (MVP)", 4), ("MVP Finále NBA", 4), ("Účast v NBA All-Star", 20), ("Nejlepší střelec historie NBA", 1)],
        "bio": "LeBron Raymone James Sr. je americký profesionální basketbalista hrající za Los Angeles Lakers. Je historicky nejlepším střelcem v dějinách NBA a čtyřnásobným šampionem ligy."
    },
    {
        "id": 977, "full_name": "Kobe Bryant", "pos": "G", "h_cm": 198.0, "h_ft": "6-6", "w_kg": 96.0, "w_lbs": 212.0,
        "college": "Lower Merion HS", "country": "USA", "draft": ("1996", "1", "13", "Charlotte Hornets"), "active": False,
        "pts": 25.0, "reb": 5.2, "ast": 4.7, "stl": 1.4, "blk": 0.5, "fg_pct": 0.447, "fg3_pct": 0.329, "ft_pct": 0.837, "gp": 1346,
        "awards": [("Šampion NBA", 5), ("Nejužitečnější hráč ligy (MVP)", 1), ("MVP Finále NBA", 2), ("Účast v NBA All-Star", 18), ("Síň slávy (Hall of Fame)", 1)],
        "bio": "Kobe Bean Bryant byl americký basketbalista, který strávil celou svou dvacetiletou kariéru v klubu Los Angeles Lakers. Proslul svou neúnavnou pracovní morálkou známou jako Mamba Mentality."
    },
    {
        "id": 406, "full_name": "Shaquille O'Neal", "pos": "C", "h_cm": 216.0, "h_ft": "7-1", "w_kg": 147.0, "w_lbs": 325.0,
        "college": "LSU", "country": "USA", "draft": ("1992", "1", "1", "Orlando Magic"), "active": False,
        "pts": 23.7, "reb": 10.9, "ast": 2.5, "stl": 0.6, "blk": 2.3, "fg_pct": 0.582, "fg3_pct": 0.045, "ft_pct": 0.527, "gp": 1207,
        "awards": [("Šampion NBA", 4), ("Nejužitečnější hráč ligy (MVP)", 1), ("MVP Finále NBA", 3), ("Účast v NBA All-Star", 15), ("Síň slávy (Hall of Fame)", 1)],
        "bio": "Shaquille Rashaun O'Neal je bývalý americký basketbalový pivot, považovaný za jednoho z nejvíce fyzicky dominantních hráčů v dějinách sportu."
    },
    {
        "id": 201939, "full_name": "Stephen Curry", "pos": "G", "h_cm": 188.0, "h_ft": "6-2", "w_kg": 84.0, "w_lbs": 185.0,
        "college": "Davidson", "country": "USA", "draft": ("2009", "1", "7", "Golden State Warriors"), "active": True,
        "pts": 24.8, "reb": 4.7, "ast": 6.4, "stl": 1.5, "blk": 0.2, "fg_pct": 0.473, "fg3_pct": 0.426, "ft_pct": 0.910, "gp": 956,
        "awards": [("Šampion NBA", 4), ("Nejužitečnější hráč ligy (MVP)", 2), ("MVP Finále NBA", 1), ("Účast v NBA All-Star", 10), ("Lídr historie v počtu 3B", 1)],
        "bio": "Wardell Stephen Curry II je americký basketbalista Golden State Warriors. Je jednomyslně považován za nejlepšího střelce za tři body v historii basketbalu a revolucionáře moderní hry."
    },
    {
        "id": 77142, "full_name": "Magic Johnson", "pos": "G", "h_cm": 206.0, "h_ft": "6-9", "w_kg": 100.0, "w_lbs": 220.0,
        "college": "Michigan State", "country": "USA", "draft": ("1979", "1", "1", "Los Angeles Lakers"), "active": False,
        "pts": 19.5, "reb": 7.2, "ast": 11.2, "stl": 1.9, "blk": 0.4, "fg_pct": 0.520, "fg3_pct": 0.303, "ft_pct": 0.848, "gp": 906,
        "awards": [("Šampion NBA", 5), ("Nejužitečnější hráč ligy (MVP)", 3), ("MVP Finále NBA", 3), ("Účast v NBA All-Star", 12), ("Síň slávy (Hall of Fame)", 1)],
        "bio": "Earvin Magic Johnson Jr. je legendární rozehrávač Los Angeles Lakers, který definoval éru Showtime svým neopakovatelným citem pro přihrávku a rychlý protiútok."
    },
    {
        "id": 1449, "full_name": "Larry Bird", "pos": "F", "h_cm": 206.0, "h_ft": "6-9", "w_kg": 100.0, "w_lbs": 220.0,
        "college": "Indiana State", "country": "USA", "draft": ("1978", "1", "6", "Boston Celtics"), "active": False,
        "pts": 24.3, "reb": 10.0, "ast": 6.3, "stl": 1.7, "blk": 0.8, "fg_pct": 0.496, "fg3_pct": 0.376, "ft_pct": 0.886, "gp": 897,
        "awards": [("Šampion NBA", 3), ("Nejužitečnější hráč ligy (MVP)", 3), ("MVP Finále NBA", 2), ("Účast v NBA All-Star", 12), ("Síň slávy (Hall of Fame)", 1)],
        "bio": "Larry Joe Bird je bývalý křídelník Boston Celtics. V osmdesátých letech vytvořil slavnou rivalitu s Magicem Johnsonem a získal 3 po sobě jdoucí ocenění MVP."
    },
    {
        "id": 76003, "full_name": "Kareem Abdul-Jabbar", "pos": "C", "h_cm": 218.0, "h_ft": "7-2", "w_kg": 102.0, "w_lbs": 225.0,
        "college": "UCLA", "country": "USA", "draft": ("1969", "1", "1", "Milwaukee Bucks"), "active": False,
        "pts": 24.6, "reb": 11.2, "ast": 3.6, "stl": 0.9, "blk": 2.6, "fg_pct": 0.559, "fg3_pct": 0.056, "ft_pct": 0.721, "gp": 1560,
        "awards": [("Šampion NBA", 6), ("Nejužitečnější hráč ligy (MVP)", 6), ("MVP Finále NBA", 2), ("Účast v NBA All-Star", 19), ("Síň slávy (Hall of Fame)", 1)],
        "bio": "Kareem Abdul-Jabbar je jeden z nejúspěšnějších basketbalistů historie, proslavený svou nezastavitelnou střelou Skyhook a šesti tituly MVP ligy."
    },
    {
        "id": 1495, "full_name": "Tim Duncan", "pos": "F-C", "h_cm": 211.0, "h_ft": "6-11", "w_kg": 113.0, "w_lbs": 250.0,
        "college": "Wake Forest", "country": "USA", "draft": ("1997", "1", "1", "San Antonio Spurs"), "active": False,
        "pts": 19.0, "reb": 10.8, "ast": 3.0, "stl": 0.7, "blk": 2.2, "fg_pct": 0.506, "fg3_pct": 0.179, "ft_pct": 0.696, "gp": 1392,
        "awards": [("Šampion NBA", 5), ("Nejužitečnější hráč ligy (MVP)", 2), ("MVP Finále NBA", 3), ("Účast v NBA All-Star", 15), ("Síň slávy (Hall of Fame)", 1)],
        "bio": "Timothy Theodore Duncan, přezdívaný The Big Fundamental, byl oporou San Antonio Spurs po téměř dvě dekády, během nichž získal 5 prstenů šampiona."
    },
    {
        "id": 201142, "full_name": "Kevin Durant", "pos": "F", "h_cm": 211.0, "h_ft": "6-11", "w_kg": 109.0, "w_lbs": 240.0,
        "college": "Texas", "country": "USA", "draft": ("2007", "1", "2", "Seattle SuperSonics"), "active": True,
        "pts": 27.3, "reb": 7.0, "ast": 4.4, "stl": 1.1, "blk": 1.1, "fg_pct": 0.501, "fg3_pct": 0.387, "ft_pct": 0.884, "gp": 1061,
        "awards": [("Šampion NBA", 2), ("Nejužitečnější hráč ligy (MVP)", 1), ("MVP Finále NBA", 2), ("Účast v NBA All-Star", 14), ("Zlatá olympijská medaile", 4)],
        "bio": "Kevin Wayne Durant je americký basketbalový kanonýr s mimořádným rozpětím paží a střelbou, která je vzhledem k jeho výšce téměř nebránitelná."
    },
    {
        "id": 203507, "full_name": "Giannis Antetokounmpo", "pos": "F", "h_cm": 211.0, "h_ft": "6-11", "w_kg": 110.0, "w_lbs": 242.0,
        "college": "Filathlitikos (Řecko)", "country": "Greece", "draft": ("2013", "1", "15", "Milwaukee Bucks"), "active": True,
        "pts": 23.4, "reb": 9.8, "ast": 4.9, "stl": 1.1, "blk": 1.2, "fg_pct": 0.545, "fg3_pct": 0.286, "ft_pct": 0.702, "gp": 792,
        "awards": [("Šampion NBA", 1), ("Nejužitečnější hráč ligy (MVP)", 2), ("MVP Finále NBA", 1), ("Obránce roku (DPOY)", 1), ("Účast v NBA All-Star", 8)],
        "bio": "Giannis Sina Ugo Antetokounmpo, známý jako The Greek Freak, je řecký profesionální basketbalista hrající za Milwaukee Bucks, vynikající bezkonkurenční atletickou silou a nájezdy."
    },
    {
        "id": 203999, "full_name": "Nikola Jokic", "pos": "C", "h_cm": 211.0, "h_ft": "6-11", "w_kg": 129.0, "w_lbs": 284.0,
        "college": "Mega Basket (Srbsko)", "country": "Serbia", "draft": ("2014", "2", "41", "Denver Nuggets"), "active": True,
        "pts": 21.0, "reb": 10.7, "ast": 6.9, "stl": 1.2, "blk": 0.7, "fg_pct": 0.557, "fg3_pct": 0.350, "ft_pct": 0.827, "gp": 675,
        "awards": [("Šampion NBA", 1), ("Nejužitečnější hráč ligy (MVP)", 3), ("MVP Finále NBA", 1), ("Účast v NBA All-Star", 6)],
        "bio": "Nikola Jokić je srbský pivot Denver Nuggets. Je považován za nejlépe přihrávajícího a takticky nejvyspělejšího pivota v celé historii basketbalu."
    },
    {
        "id": 1629029, "full_name": "Luka Doncic", "pos": "G-F", "h_cm": 201.0, "h_ft": "6-7", "w_kg": 104.0, "w_lbs": 230.0,
        "college": "Real Madrid (Španělsko)", "country": "Slovenia", "draft": ("2018", "1", "3", "Atlanta Hawks"), "active": True,
        "pts": 28.7, "reb": 8.7, "ast": 8.3, "stl": 1.2, "blk": 0.5, "fg_pct": 0.470, "fg3_pct": 0.347, "ft_pct": 0.747, "gp": 400,
        "awards": [("Nováček roku (ROY)", 1), ("Člen All-NBA týmu", 5), ("Účast v NBA All-Star", 5), ("Nejlepší střelec sezóny", 1)],
        "bio": "Luka Dončić je slovinský rozehrávač Dallas Mavericks, proslulý svými neuvěřitelnými step-back trojkami, tvorbou hry a častými triple-doubly."
    },
    {
        "id": 76375, "full_name": "Wilt Chamberlain", "pos": "C", "h_cm": 216.0, "h_ft": "7-1", "w_kg": 125.0, "w_lbs": 275.0,
        "college": "Kansas", "country": "USA", "draft": ("1959", "Territorial", "1", "Philadelphia Warriors"), "active": False,
        "pts": 30.1, "reb": 22.9, "ast": 4.4, "stl": 1.0, "blk": 3.5, "fg_pct": 0.540, "fg3_pct": 0.0, "ft_pct": 0.511, "gp": 1045,
        "awards": [("Šampion NBA", 2), ("Nejužitečnější hráč ligy (MVP)", 4), ("MVP Finále NBA", 1), ("Účast v NBA All-Star", 13), ("Síň slávy (Hall of Fame)", 1)],
        "bio": "Wilton Norman Chamberlain byl jedním z největších atletů 20. století. Dodnes drží nepřekonatelný rekord 100 bodů vstřelených v jediném utkání NBA."
    },
    {
        "id": 78049, "full_name": "Bill Russell", "pos": "C", "h_cm": 208.0, "h_ft": "6-10", "w_kg": 100.0, "w_lbs": 220.0,
        "college": "San Francisco", "country": "USA", "draft": ("1956", "1", "2", "St. Louis Hawks"), "active": False,
        "pts": 15.1, "reb": 22.5, "ast": 4.3, "stl": 1.0, "blk": 4.0, "fg_pct": 0.440, "fg3_pct": 0.0, "ft_pct": 0.561, "gp": 963,
        "awards": [("Šampion NBA", 11), ("Nejužitečnější hráč ligy (MVP)", 5), ("Účast v NBA All-Star", 12), ("Síň slávy (Hall of Fame)", 1)],
        "bio": "William Felton Russell byl legendární obránce Boston Celtics a největší vítěz v historii týmových sportů v Severní Americe s 11 mistrovskými tituly."
    },
    {
        "id": 165, "full_name": "Hakeem Olajuwon", "pos": "C", "h_cm": 213.0, "h_ft": "7-0", "w_kg": 116.0, "w_lbs": 255.0,
        "college": "Houston", "country": "Nigeria", "draft": ("1984", "1", "1", "Houston Rockets"), "active": False,
        "pts": 21.8, "reb": 11.1, "ast": 2.5, "stl": 1.7, "blk": 3.1, "fg_pct": 0.512, "fg3_pct": 0.202, "ft_pct": 0.712, "gp": 1238,
        "awards": [("Šampion NBA", 2), ("Nejužitečnější hráč ligy (MVP)", 1), ("MVP Finále NBA", 2), ("Obránce roku (DPOY)", 2), ("Síň slávy (Hall of Fame)", 1)],
        "bio": "Hakeem Abdul Olajuwon, přezdívaný The Dream, byl nigerijsko-americký pivot Houston Rockets, slavný svým legendárním fíglem Dream Shake a rekordním počtem bloků."
    },
    {
        "id": 1717, "full_name": "Dirk Nowitzki", "pos": "F", "h_cm": 213.0, "h_ft": "7-0", "w_kg": 111.0, "w_lbs": 245.0,
        "college": "DJK Würzburg", "country": "Germany", "draft": ("1998", "1", "9", "Milwaukee Bucks"), "active": False,
        "pts": 20.7, "reb": 7.5, "ast": 2.4, "stl": 0.8, "blk": 0.8, "fg_pct": 0.471, "fg3_pct": 0.380, "ft_pct": 0.879, "gp": 1522,
        "awards": [("Šampion NBA", 1), ("Nejužitečnější hráč ligy (MVP)", 1), ("MVP Finále NBA", 1), ("Účast v NBA All-Star", 14), ("Síň slávy (Hall of Fame)", 1)],
        "bio": "Dirk Werner Nowitzki je německý basketbalista, který dovedl Dallas Mavericks k titulu v roce 2011 a zpopularizoval svou ikonickou střelu z jedné nohy (one-legged fadeaway)."
    },
    {
        "id": 947, "full_name": "Allen Iverson", "pos": "G", "h_cm": 183.0, "h_ft": "6-0", "w_kg": 75.0, "w_lbs": 165.0,
        "college": "Georgetown", "country": "USA", "draft": ("1996", "1", "1", "Philadelphia 76ers"), "active": False,
        "pts": 26.7, "reb": 3.7, "ast": 6.2, "stl": 2.2, "blk": 0.2, "fg_pct": 0.425, "fg3_pct": 0.313, "ft_pct": 0.780, "gp": 914,
        "awards": [("Nejužitečnější hráč ligy (MVP)", 1), ("Nováček roku (ROY)", 1), ("Nejlepší střelec sezóny", 4), ("Účast v NBA All-Star", 11), ("Síň slávy (Hall of Fame)", 1)],
        "bio": "Allen Ezail Iverson, známý jako The Answer, okouzlil basketbalový svět bleskovým crossoverem, nezkrotnou bojovností a výrazným vlivem na hip-hopovou kulturu."
    },
    {
        "id": 2548, "full_name": "Dwyane Wade", "pos": "G", "h_cm": 193.0, "h_ft": "6-4", "w_kg": 100.0, "w_lbs": 220.0,
        "college": "Marquette", "country": "USA", "draft": ("2003", "1", "5", "Miami Heat"), "active": False,
        "pts": 22.0, "reb": 4.7, "ast": 5.4, "stl": 1.5, "blk": 0.8, "fg_pct": 0.480, "fg3_pct": 0.293, "ft_pct": 0.765, "gp": 1054,
        "awards": [("Šampion NBA", 3), ("MVP Finále NBA", 1), ("Účast v NBA All-Star", 13), ("Nejlepší střelec sezóny", 1), ("Síň slávy (Hall of Fame)", 1)],
        "bio": "Dwyane Tyrone Wade Jr., přezdívaný Flash, byl neohrožený střelec Miami Heat, proslulý dynamickými nájezdy pod koš a skvělým blokováním z pozice rozehrávače."
    },
    {
        "id": 708, "full_name": "Kevin Garnett", "pos": "F-C", "h_cm": 211.0, "h_ft": "6-11", "w_kg": 109.0, "w_lbs": 240.0,
        "college": "Farragut Academy HS", "country": "USA", "draft": ("1995", "1", "5", "Minnesota Timberwolves"), "active": False,
        "pts": 17.8, "reb": 10.0, "ast": 3.7, "stl": 1.3, "blk": 1.4, "fg_pct": 0.497, "fg3_pct": 0.275, "ft_pct": 0.789, "gp": 1462,
        "awards": [("Šampion NBA", 1), ("Nejužitečnější hráč ligy (MVP)", 1), ("Obránce roku (DPOY)", 1), ("Účast v NBA All-Star", 15), ("Síň slávy (Hall of Fame)", 1)],
        "bio": "Kevin Maurice Garnett, přezdívaný The Big Ticket, přinesl do ligy elektrizující energii, všestrannost a nekompromisní defenzivní komunikaci s Bostonem i Minnesotou."
    },
    {
        "id": 959, "full_name": "Steve Nash", "pos": "G", "h_cm": 191.0, "h_ft": "6-3", "w_kg": 88.0, "w_lbs": 195.0,
        "college": "Santa Clara", "country": "Canada", "draft": ("1996", "1", "15", "Phoenix Suns"), "active": False,
        "pts": 14.3, "reb": 3.0, "ast": 8.5, "stl": 0.7, "blk": 0.1, "fg_pct": 0.490, "fg3_pct": 0.428, "ft_pct": 0.904, "gp": 1217,
        "awards": [("Nejužitečnější hráč ligy (MVP)", 2), ("Lídr asistencí sezóny", 5), ("Účast v NBA All-Star", 8), ("Síň slávy (Hall of Fame)", 1)],
        "bio": "Stephen John Nash je kanadský basketbalista, který jako mozek systému Seven Seconds or Less ve Phoenixu Suns dvakrát vyhrál cenu MVP."
    },
    {
        "id": 202695, "full_name": "Kawhi Leonard", "pos": "F", "h_cm": 201.0, "h_ft": "6-7", "w_kg": 102.0, "w_lbs": 225.0,
        "college": "San Diego State", "country": "USA", "draft": ("2011", "1", "15", "Indiana Pacers"), "active": True,
        "pts": 20.0, "reb": 6.4, "ast": 3.0, "stl": 1.7, "blk": 0.6, "fg_pct": 0.499, "fg3_pct": 0.391, "ft_pct": 0.862, "gp": 696,
        "awards": [("Šampion NBA", 2), ("MVP Finále NBA", 2), ("Obránce roku (DPOY)", 2), ("Účast v NBA All-Star", 6)],
        "bio": "Kawhi Anthony Leonard, známý jako The Claw, proslul obrovskýma rukama, neprostupnou perimetrovou obranou a ledovým klidem v rozhodujících momentech play-off."
    },
    {
        "id": 787, "full_name": "Charles Barkley", "pos": "F", "h_cm": 198.0, "h_ft": "6-6", "w_kg": 114.0, "w_lbs": 252.0,
        "college": "Auburn", "country": "USA", "draft": ("1984", "1", "5", "Philadelphia 76ers"), "active": False,
        "pts": 22.1, "reb": 11.7, "ast": 3.9, "stl": 1.5, "blk": 0.8, "fg_pct": 0.541, "fg3_pct": 0.266, "ft_pct": 0.735, "gp": 1073,
        "awards": [("Nejužitečnější hráč ligy (MVP)", 1), ("Lídr doskoků sezóny", 1), ("Účast v NBA All-Star", 11), ("Síň slávy (Hall of Fame)", 1)],
        "bio": "Charles Wade Barkley, přezdívaný The Round Mound of Rebound, patřil navzdory menší postavě na pozici křídla k nejbrutálnějším doskakovačům v historii ligy."
    },
    {
        "id": 252, "full_name": "Karl Malone", "pos": "F", "h_cm": 206.0, "h_ft": "6-9", "w_kg": 116.0, "w_lbs": 256.0,
        "college": "Louisiana Tech", "country": "USA", "draft": ("1985", "1", "13", "Utah Jazz"), "active": False,
        "pts": 25.0, "reb": 10.1, "ast": 3.6, "stl": 1.4, "blk": 0.8, "fg_pct": 0.516, "fg3_pct": 0.274, "ft_pct": 0.742, "gp": 1476,
        "awards": [("Nejužitečnější hráč ligy (MVP)", 2), ("Člen All-NBA týmu", 14), ("Účast v NBA All-Star", 14), ("Síň slávy (Hall of Fame)", 1)],
        "bio": "Karl Anthony Malone, zvaný The Mailman, vytvořil v Utahu Jazz s Johnem Stocktonem nejslavnější pick-and-roll duo historie a nastřílel přes 36 tisíc bodů."
    },
    {
        "id": 304, "full_name": "John Stockton", "pos": "G", "h_cm": 185.0, "h_ft": "6-1", "w_kg": 79.0, "w_lbs": 175.0,
        "college": "Gonzaga", "country": "USA", "draft": ("1984", "1", "16", "Utah Jazz"), "active": False,
        "pts": 13.1, "reb": 2.7, "ast": 10.5, "stl": 2.2, "blk": 0.2, "fg_pct": 0.515, "fg3_pct": 0.384, "ft_pct": 0.826, "gp": 1504,
        "awards": [("Lídr historie v asistencích a ziscích", 1), ("Účast v NBA All-Star", 10), ("Síň slávy (Hall of Fame)", 1)],
        "bio": "John Houston Stockton je absolutní historický lídr NBA v počtu asistencí (15 806) i zisků (3 265), který odehrál 19 neuvěřitelných sezón za Utah Jazz."
    },
    {
        "id": 101108, "full_name": "Chris Paul", "pos": "G", "h_cm": 183.0, "h_ft": "6-0", "w_kg": 79.0, "w_lbs": 175.0,
        "college": "Wake Forest", "country": "USA", "draft": ("2005", "1", "4", "New Orleans Hornets"), "active": True,
        "pts": 17.5, "reb": 4.5, "ast": 9.4, "stl": 2.1, "blk": 0.2, "fg_pct": 0.472, "fg3_pct": 0.369, "ft_pct": 0.870, "gp": 1272,
        "awards": [("Nováček roku (ROY)", 1), ("Účast v NBA All-Star", 12), ("Lídr asistencí sezóny", 5), ("Lídr zisků sezóny", 6)],
        "bio": "Christopher Emmanuel Paul, přezdívaný Point God, je prototypem klasického elitního rozehrávače s chirurgickou kontrolou tempa a taktickou precizností."
    },
    {
        "id": 201935, "full_name": "James Harden", "pos": "G", "h_cm": 196.0, "h_ft": "6-5", "w_kg": 100.0, "w_lbs": 220.0,
        "college": "Arizona State", "country": "USA", "draft": ("2009", "1", "3", "Oklahoma City Thunder"), "active": True,
        "pts": 24.1, "reb": 5.6, "ast": 7.1, "stl": 1.5, "blk": 0.6, "fg_pct": 0.441, "fg3_pct": 0.364, "ft_pct": 0.860, "gp": 1072,
        "awards": [("Nejužitečnější hráč ligy (MVP)", 1), ("Nejlepší střelec sezóny", 3), ("Lídr asistencí sezóny", 2), ("Účast v NBA All-Star", 10)],
        "bio": "James Edward Harden Jr., známý jako The Beard, zpopularizoval izolace a step-back trojky na vrcholu své éry v Houstonu Rockets, kdy střílel přes 36 PPG."
    },
    {
        "id": 201566, "full_name": "Russell Westbrook", "pos": "G", "h_cm": 193.0, "h_ft": "6-4", "w_kg": 91.0, "w_lbs": 200.0,
        "college": "UCLA", "country": "USA", "draft": ("2008", "1", "4", "Seattle SuperSonics"), "active": True,
        "pts": 21.7, "reb": 7.1, "ast": 8.1, "stl": 1.6, "blk": 0.3, "fg_pct": 0.438, "fg3_pct": 0.304, "ft_pct": 0.776, "gp": 1162,
        "awards": [("Nejužitečnější hráč ligy (MVP)", 1), ("Lídr historie v triple-doublech", 1), ("Nejlepší střelec sezóny", 2), ("Účast v NBA All-Star", 9)],
        "bio": "Russell Westbrook III je historickým rekordmanem NBA v počtu triple-doublů, proslulý svou neskutečnou dravostí od koše ke koši a nezlomným motorem."
    },
    {
        "id": 937, "full_name": "Scottie Pippen", "pos": "F", "h_cm": 203.0, "h_ft": "6-8", "w_kg": 103.0, "w_lbs": 228.0,
        "college": "Central Arkansas", "country": "USA", "draft": ("1987", "1", "5", "Seattle SuperSonics"), "active": False,
        "pts": 16.1, "reb": 6.4, "ast": 5.2, "stl": 2.0, "blk": 0.8, "fg_pct": 0.473, "fg3_pct": 0.326, "ft_pct": 0.704, "gp": 1178,
        "awards": [("Šampion NBA", 6), ("Člen All-Defensive týmu", 10), ("Účast v NBA All-Star", 7), ("Síň slávy (Hall of Fame)", 1)],
        "bio": "Scotty Maurice Pippen byl klíčovým partnerem Michaela Jordana v Chicagu Bulls a jedním z nejlepších obránců perimetru v celých dějinách basketbalu."
    },
    {
        "id": 23, "full_name": "Dennis Rodman", "pos": "F", "h_cm": 201.0, "h_ft": "6-7", "w_kg": 95.0, "w_lbs": 210.0,
        "college": "Southeastern Oklahoma State", "country": "USA", "draft": ("1986", "2", "27", "Detroit Pistons"), "active": False,
        "pts": 7.3, "reb": 13.1, "ast": 1.8, "stl": 0.7, "blk": 0.6, "fg_pct": 0.521, "fg3_pct": 0.231, "ft_pct": 0.584, "gp": 911,
        "awards": [("Šampion NBA", 5), ("Obránce roku (DPOY)", 2), ("Lídr doskoků sezóny", 7), ("Účast v NBA All-Star", 2), ("Síň slávy (Hall of Fame)", 1)],
        "bio": "Dennis Keith Rodman, zvaný The Worm, byl mistrem doskoků, defenzivního obtěžování a psychologického nátlaku na soupeře jak v dresu Pistons, tak Bulls."
    }
]


def seed_database(use_live_api: bool = False):
    print("=" * 60)
    print("🏀 NBA Nerd Vault – Inicializace databázové cache (Fáze 1)")
    print("=" * 60)

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    total = len(LEGENDS_METADATA)
    seeded_count = 0

    try:
        for idx, item in enumerate(LEGENDS_METADATA, start=1):
            p_id = item["id"]
            name = item["full_name"]
            print(f"[{idx}/{total}] Zpracovávám hráče: {name} (ID: {p_id})...")

            existing = db.query(Player).filter(Player.id == p_id).first()
            if existing and existing.stats:
                print(f"   -> Hráč {name} již v databázi existuje, přeskakuji.")
                seeded_count += 1
                continue

            if use_live_api:
                try:
                    time.sleep(0.5)
                    player_obj = fetch_and_cache_player(player_id=p_id, db=db)
                    if player_obj:
                        print(f"   -> Úspěšně staženo z live NBA API.")
                        seeded_count += 1
                        continue
                except Exception as live_err:
                    print(f"   -> Live API selhalo ({live_err}), použiji kurátorovaná all-time data.")

            # Seed curated accurate data
            name_parts = name.split(" ")
            f_name = name_parts[0]
            l_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""

            # Synthesize career / prime seasons for statistical depth
            pts = item["pts"]
            reb = item["reb"]
            ast = item["ast"]
            stl = item["stl"]
            blk = item["blk"]
            fg_pct = item["fg_pct"]
            fg3_pct = item["fg3_pct"]
            ft_pct = item["ft_pct"]
            gp = item["gp"]

            # Per 100 poss factor
            poss100_mult = 2.7

            # Prepare seasons
            sample_seasons = []
            draft_year_int = int(item["draft"][0]) if item["draft"][0].isdigit() else 1995
            num_seasons = min(15, max(5, gp // 70))
            for s_idx in range(num_seasons):
                yr = draft_year_int + s_idx
                s_id = f"{yr}-{str(yr+1)[-2:]}"
                # Slight variance around peak
                var = 1.0 + ((s_idx - num_seasons // 2) * 0.02)
                sample_seasons.append({
                    "season_id": s_id,
                    "team_abbreviation": item["draft"][3][:3].upper(),
                    "player_age": 20 + s_idx,
                    "gp": min(82, max(50, int(gp / num_seasons))),
                    "gs": min(82, max(45, int(gp / num_seasons))),
                    "min_per_game": 35.0,
                    "pts": round(pts * var, 1),
                    "reb": round(reb * var, 1),
                    "ast": round(ast * var, 1),
                    "stl": round(stl, 1),
                    "blk": round(blk, 1),
                    "tov": 2.8,
                    "pf": 2.5,
                    "fgm": round(pts * 0.38, 1),
                    "fga": round(pts * 0.38 / max(fg_pct, 0.4), 1),
                    "fg_pct": fg_pct,
                    "fg3m": round(pts * 0.1, 1),
                    "fg3a": round((pts * 0.1) / max(fg3_pct, 0.3), 1) if fg3_pct > 0.1 else 0.0,
                    "fg3_pct": fg3_pct,
                    "ftm": round(pts * 0.2, 1),
                    "fta": round((pts * 0.2) / max(ft_pct, 0.6), 1),
                    "ft_pct": ft_pct,
                    "poss100_pts": round(pts * var * poss100_mult, 1),
                    "poss100_reb": round(reb * var * poss100_mult, 1),
                    "poss100_ast": round(ast * var * poss100_mult, 1),
                    "poss100_stl": round(stl * poss100_mult, 1),
                    "poss100_blk": round(blk * poss100_mult, 1),
                    "poss100_tov": round(2.8 * poss100_mult, 1),
                })

            tags = calculate_playstyle_tags(sample_seasons, item["pos"])
            scout_rep = generate_scouting_report(
                full_name=name,
                position=item["pos"],
                height_cm=item["h_cm"],
                stats=sample_seasons,
                awards=[f"{a[0]} ({a[1]}x)" for a in item["awards"]],
                tags=tags
            )

            player = Player(
                id=p_id,
                full_name=name,
                first_name=f_name,
                last_name=l_name,
                is_active=item["active"],
                headshot_url=f"https://cdn.nba.com/headshots/nba/latest/1040x760/{p_id}.png",
                height_cm=item["h_cm"],
                height_ft=item["h_ft"],
                weight_kg=item["w_kg"],
                weight_lbs=item["w_lbs"],
                position=item["pos"],
                draft_year=item["draft"][0],
                draft_round=item["draft"][1],
                draft_number=item["draft"][2],
                draft_team=item["draft"][3],
                college=item["college"],
                country=item["country"],
                bio_summary=item["bio"],
                scouting_report=scout_rep,
                playstyle_tags=json.dumps(tags, ensure_ascii=False)
            )

            db.add(player)
            db.flush()

            # Add seasons
            for s in sample_seasons:
                stat_obj = PlayerSeasonStat(
                    player_id=p_id,
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
                db.add(stat_obj)

            # Add awards
            for aw_desc, aw_count in item["awards"]:
                aw_obj = PlayerAward(
                    player_id=p_id,
                    description=aw_desc,
                    description_cs=aw_desc,
                    count=aw_count,
                    season=""
                )
                db.add(aw_obj)

            db.commit()
            print(f"   -> Uloženo do SQLite: {name} ({len(sample_seasons)} sezón, {len(item['awards'])} ocenění).")
            seeded_count += 1

        print("=" * 60)
        print(f"✅ Seeding úspěšně dokončen! Celkem uloženo {seeded_count}/{total} legend NBA.")
        print("=" * 60)

    except Exception as e:
        db.rollback()
        print(f"❌ Chyba při seedingu: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    use_live = "--live" in sys.argv
    seed_database(use_live_api=use_live)

"""Ligový kontext střelby, nikoli databáze hráčů.

Zdroj: https://www.basketball-reference.com/leagues/NBA_stats_per_game.html
Základní část NBA, ligové průměry 3PA/FGA, od 1979–80 do 2025–26.
"""

_ATTEMPTS = (
    (2.8,90.6),(2.0,88.4),(2.3,88.2),(2.3,89.7),(2.4,88.4),
    (3.1,89.1),(3.3,88.6),(4.7,88.8),(5.0,87.7),(6.6,89.0),
    (6.6,87.2),(7.1,87.2),(7.6,87.3),(9.0,86.0),(9.9,84.4),
    (15.3,81.5),(16.0,80.2),(16.8,79.3),(12.7,79.7),(13.2,78.2),
    (13.7,80.5),(13.7,80.6),(14.7,81.3),(14.7,81.8),(14.9,79.8),
    (15.8,80.3),(16.0,79.0),(16.9,79.7),(18.1,81.5),(18.1,80.9),
    (18.1,81.7),(18.0,81.2),(18.4,81.4),(20.0,82.0),(21.5,83.0),
    (22.4,83.6),(24.1,84.6),(27.0,85.4),(29.0,86.1),(32.0,89.2),
    (34.1,88.8),(34.6,88.4),(35.2,88.1),(34.2,88.3),(35.1,88.9),
    (37.6,89.2),(37.0,89.1),
)


def season_year(season):
    try:
        return int(str(season)[:4])
    except (ValueError, TypeError):
        return None


def era_3par(season):
    year = season_year(season)
    if year is None:
        return None
    if year < 1979:
        return 0.0
    threes, attempts = _ATTEMPTS[min(year - 1979, len(_ATTEMPTS) - 1)]
    return threes / attempts

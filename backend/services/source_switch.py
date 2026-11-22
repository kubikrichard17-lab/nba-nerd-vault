"""
Přepínač zdroje dat: ESPN jako primární.

Když je nastaveno NBA_DATA_SOURCE=espn (na Renderu je), každé volání
stats.nba.com selže okamžitě, takže se kód rovnou přepne na ESPN záložní
větve. Dřív se na NBA API (z datového centra stejně nedostupné) čekalo
6–30 s u každého dotazu. Lokálně bez proměnné zůstává NBA API hlavní.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def espn_first() -> bool:
    return os.environ.get("NBA_DATA_SOURCE", "").strip().lower() == "espn"


def install() -> None:
    """Vypne síťová volání stats.nba.com (jen když je ESPN primární)."""
    if not espn_first():
        return
    try:
        from nba_api.library.http import NBAHTTP
        from nba_api.stats.library.http import NBAStatsHTTP

        def _blocked(self, *args, **kwargs):  # noqa: ANN001
            raise ConnectionError("stats.nba.com vypnuto – primární zdroj je ESPN")

        NBAStatsHTTP.send_api_request = _blocked
        NBAHTTP.send_api_request = _blocked
        logger.info("Primární zdroj dat: ESPN (NBA API vypnuto)")
    except Exception as exc:  # pragma: no cover
        logger.warning("Přepnutí na ESPN se nepovedlo: %s", exc)

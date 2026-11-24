"""
Společné nastavení backendu pro běh doma i pro nasazení online.

Port i povolené adresy se berou z proměnných prostředí, takže se kód
nemusí měnit, až budeš aplikaci chtít vystavit.
"""

from __future__ import annotations

import os
from typing import List


def port() -> int:
    """Port, na kterém backend poslouchá (výchozí 8000)."""
    try:
        return int(os.environ.get("PORT", "8000"))
    except ValueError:
        return 8000


def allowed_origins() -> List[str]:
    """
    Povolené adresy pro prohlížeč.

    Když proměnná ALLOWED_ORIGINS chybí (doma i na Renderu bez nastavení),
    povolí se všechno (`*`) – aplikace pak funguje z localhostu, z telefonu
    v domácí síti i z produkční adresy na Vercelu.

    Pro zpřísnění stačí na serveru nastavit třeba:
        ALLOWED_ORIGINS=https://nba-nerd-vault.vercel.app,https://muj-web.cz
    """
    raw = os.environ.get("ALLOWED_ORIGINS", "").strip()
    if not raw:
        return ["*"]
    origins = [o.strip().rstrip("/") for o in raw.split(",") if o.strip()]
    return origins or ["*"]


# Klíč pro Gemini (AI návrh a popisky u „nejbližšího hráče").
# Nastavuje se proměnnou prostředí, nikdy se neukládá do repozitáře.
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

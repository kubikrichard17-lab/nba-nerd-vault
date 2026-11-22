# NBA Nerd Vault – mobil, sdílení, externí data

## 1. Externí data – co se odkud tahá

Aplikace si **nic nestahuje předem** a nemá vlastní databázi hráčů. Vše se bere
z internetu za běhu:

| Zdroj | Co z něj je |
|---|---|
| NBA API (`stats.nba.com`) | kariérní a sezónní statistiky, pozice, výška, váha, trofeje |
| Basketball-Reference | záložní zdroj, když NBA API neodpovídá |
| Wikipedia | krátké bio hráče |

Jediné, co zůstává na disku, je **dočasná paměť odpovědí**
(`backend/external_pool.json.gz`, ~64 KB). Není to databáze: položky samy
vyprší (statistiky 3 dny, profil hráče 14 dní) a znovu se stáhnou z internetu.
Smazat se dá kdykoliv – aplikace si data dotáhne znovu.

## 2. Mobil

Web je responzivní – na telefonu jde otevřít stejná adresa, jen musí být
dostupná v síti, ne na `localhost`.

1. Na počítači zjisti IPv4 adresu (`ipconfig`), např. `192.168.1.50`.
2. V `frontend/.env.local`:
   ```
   NEXT_PUBLIC_API_URL=http://192.168.1.50:8000
   ```
3. Spusť `START.bat` – ten na konci sám vypíše adresu pro telefon.
4. Na telefonu ve stejné Wi-Fi otevři `http://192.168.1.50:3000`.
5. V prohlížeči dej „Přidat na plochu“ – chová se jako appka.

Mimo domácí síť to bez hostingu nejde – viz bod 4.

## 3. Sdílení jako soubor

Jeden spustitelný soubor to být nemůže, protože backend potřebuje Python.
Sdílí se celá složka projektu (bez `node_modules`, `.next`, `venv`) a na
druhém počítači se spustí `START.bat` – ten poprvé sám doinstaluje, co chybí.

## 4. Nasdílení mimo domácí síť (volitelné, teď není potřeba)

Aby to běželo i jinde než doma, musí někde běžet backend. Projekt je na to
připravený – stačí nastavit `NEXT_PUBLIC_API_URL` a `ALLOWED_ORIGINS` a
nasadit na Railway / Render / Fly.io.

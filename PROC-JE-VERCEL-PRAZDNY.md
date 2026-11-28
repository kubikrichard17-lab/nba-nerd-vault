# Proč je stránka na Vercelu prázdná – a co s tím

## Co se děje

Frontend na Vercelu **funguje správně**. Ověřil jsem to:

- `NEXT_PUBLIC_API_URL` je ve Vercelu správně vyplněná a **zabudovaná do buildu**
  (v JavaScriptu, který Vercel servíruje, je adresa `https://nba-nerd-vault.onrender.com`
  skutečně přítomná – zkontroloval jsem stažené soubory).
- Zdrojový kód je čistý, žádná natvrdo zapsaná adresa.

Problém je **v backendu na Renderu**, konkrétně v tom, co volá NBA API.

## Naměřené hodnoty

Testoval jsem to opakovaně, tady jsou skutečná čísla:

| Endpoint | Výsledek | Čas |
|---|---|---|
| `/api/health` | ✅ 200 | 0,2 s |
| `/api/players/893/closest` | ✅ 200 (Kobe Bryant 91,9 %) | 0,2 s |
| `/api/players/search` | ✅ 200 | 0,2 s |
| `/api/facts` | ✅ 200 | 0,4 s |
| `/api/players/893` (profil) | ⚠️ 200, ale | **46 s** |
| `/api/standings` | ❌ 503 | 98 s |
| `/api/leaders` | ❌ 503 | 98 s |
| `/api/news/schedule` | ❌ 503 | 98 s |
| `/api/players/893/last-game` | ❌ 503 | 12 s |

Vzorec je jasný: **všechno, co je v databázi nebo v `.json.gz`, jde okamžitě.
Všechno, co volá `stats.nba.com` živě, selže.**

## Kde je příčina

Stejný kód jsem pustil **na tvém počítači** a tabulka se načetla za pár sekund
(30 řádků). Na Renderu selže.

→ Kód je v pořádku, problém je **síť mezi Renderem a `stats.nba.com`**.

Konkrétně: NBA blokuje datová centra. Render běží ve Virginii (US), tedy
v cloudu, odkud NBA API požadavky zahazuje nebo na ně neodpovídá vůbec.
Z domácí IP adresy to projde, z cloudové ne.

Druhá věc: free tarif má 0,1 CPU a 512 MB RAM. Když se do toho přidá
`timeout=30` opakovaný třikrát, požadavek se dostane na 98 sekund – a to je
přes limit, kdy Vercel/prohlížeč spojení vzdá.

## Co s tím udělat

### Možnost 1: Nechat NBA API jen tam, kde funguje (doporučuji)

Data, která už jsou v repozitáři (`.json.gz`, `nba_vault.db`), jsou **statická**
a na Renderu fungují bezchybně. Živé dotazy na NBA API na Renderu nefungují
a fungovat nebudou.

Řešení: endpointy, které potřebují NBA API (`/api/standings`, `/api/leaders`,
`/api/news/*`), na Renderu **vypnout nebo obsloužit z uložených dat**, a ve
frontendu u nich zobrazit hlášku „tahle sekce běží jen lokálně".

### Možnost 2: Placený tarif + lepší region

Render placený tarif (7 $/měsíc) má trvalý disk a víc CPU, ale **blokaci
NBA API to nevyřeší** – ta je na úrovni sítě, ne výkonu.

### Možnost 3: Proxy přes vlastní server

Postavit malý proxy server na domácím počítači, který NBA API volá za vás,
a Render ho jen poslouchá. Funguje jen když je počítač zapnutý – což je
v podstatě dnešní stav, akorát složitější.

## Praktický závěr

**Na Vercelu bude fungovat:** vyhledávání hráčů, profily, „nejbližší hráč"
(včetně Prime a fází kariéry), porovnávač, zajímavosti, lídrí z historie.

**Na Vercelu fungovat nebude:** aktuální tabulka sezóny, sezónní žebříčky,
novinky a rozpisy zápasů – dokud se nevyřeší blokace NBA API z cloudu.

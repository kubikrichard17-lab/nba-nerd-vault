# 🏀 NBA Nerd Vault (Fáze 1 – Základ & Modulární architektura)

Moderní webová aplikace pro pokročilou analýzu, profilování a all-time porovnávání basketbalových hráčů NBA.

Celá aplikace je navržena podle striktních modulárních pravidel s odděleným backendem (**Python FastAPI + SQLite databáze**) a frontendem (**Next.js App Router + Tailwind CSS**) a **kompletně lokalizována do češtiny**.

---

## 🏛️ Architektura a struktura projektu

```
nba-nerd-vault/
├── backend/
│   ├── database.py              # Inicializace SQLite engine a SQLAlchemy Session
│   ├── models.py                # Databázové modely (Player, Stats, Awards, Cache)
│   ├── nba_vault.db             # Lokální SQLite databáze (cache)
│   ├── main.py                  # FastAPI REST API (CORS, search, profile, compare)
│   ├── seed.py                  # Seeding skript pro prvních 30 legend a hvězd NBA
│   └── services/
│       ├── nba_fetcher.py       # Stahování z nba_api + Wikipedia API + výpočet tagů
│       ├── similarity_engine.py # Scikit-learn Cosine Similarity & radar metrics
│       └── ai_scout.py          # Gemini API AI Scouting report & srovnávací verdikt
│
└── frontend/
    ├── src/
    │   ├── app/
    │   │   ├── layout.tsx       # Root layout, navigace, dark sports téma
    │   │   ├── page.tsx         # Stránka 1: Vyhledávání & Profil hráče (/)
    │   │   ├── compare/page.tsx # Stránka 2: All-Time Porovnávač (/compare)
    │   │   └── globals.css      # Globální Tailwind styly
    │   ├── components/
    │   │   ├── Navbar.tsx       # Horní navigace s odznaky
    │   │   ├── PlayerSearch.tsx # Našeptávač s autocomplete a rychlým výběrem
    │   │   ├── PlayerInfobox.tsx# Wikipedia infobox (foto, výška, váha, draft, trofeje)
    │   │   ├── StatsTabs.tsx    # Přepínací lišta (Statistiky vs Styl & Profil)
    │   │   └── CompareRadar.tsx # Překryvný radarový graf schopností
    │   └── types/
    │       └── index.ts         # TypeScript definice
    ├── package.json
    ├── tailwind.config.js
    └── tsconfig.json
```

---

## 🚀 Klíčové funkce Fáze 1

### 1. Vyhledávání & Profil hráče (`/`)
* **Našeptávač (Autocomplete)**: Okamžité vyhledávání aktivních i historických hráčů NBA.
* **Wikipedia-style levý panel (`PlayerInfobox.tsx`)**:
  * Oficiální headshot NBA (s automatickým záložním fallbackem)
  * Výška (cm i stopy/palce), váha (kg i libry), pozice
  * Draft (rok, kolo, výběr, tým), univerzita a země původu
  * Přehled získaných trofejí a ocenění NBA (Šampion NBA, MVP, All-Star, DPOY atd.)
* **Pravý panel s přepínací lištou (`StatsTabs.tsx`)**:
  * **Záložka „Statistiky“**: Kariérní přehled + kompletní tabulka všech odehraných sezón s přepínačem mezi **Základními průměry na zápas** a **Na 100 držení míče (Per 100 Possessions)**.
  * **Záložka „Herní styl & Profil“**: Biografický profil z Wikipedia API v češtině + pravidlově vypočítané tagy stylu hry z reálných statistik + **3větý scouting report** vygenerovaný přes Gemini API a uložený v SQLite.

### 2. All-Time Porovnávač (`/compare`)
* Výběr libovolných dvou hráčů s možností srovnat **průměr celé kariéry nebo konkrétní vybranou sezónu**.
* **Matematický Similarity Engine (`similarity_engine.py`)**:
  * Využívá **Cosine Similarity** knihovny `scikit-learn` a normalizované metriky na 100 držení míče.
  * Počítá celkovou shodu (0–100 %) i dílčí shody: **Fyzická %**, **Statistická %** a **Stylistická %**.
* **Vizuální výstup**:
  * **Překryvný radarový graf (`CompareRadar.tsx`)** v 7 klíčových dimenzích výkonu (Skórování, 3B Střelba, Tvorba hry, Doskakování, Obrana, Efektivita, Fyzická dominance).
  * **Srovnávací tabulka hodnot** s přesným výpočtem rozdílů (Δ).
  * **Stručný AI verdikt** srovnávající herní nuance a typologii obou atletů.

### 3. Databázová cache (SQLite `nba_vault.db`)
* Jakýkoliv stažený hráč a vygenerované srovnání se automaticky ukládá do lokální databáze `nba_vault.db`.
* Při dalším otevření se data načítají okamžitě z DB bez zbytečného zatěžování externích API.
* Seeding skript již předvyplnil 30 nejvýznamnějších legend NBA pro okamžité offline testování.

---

## 🛠️ Jak aplikaci spustit

### 1. Spuštění backendu (FastAPI):
```powershell
cd C:\Users\42077\.gemini\antigravity\scratch\nba-nerd-vault\backend
python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```
API běží na: `http://127.0.0.1:8000` (dokumentace Swagger na `http://127.0.0.1:8000/docs`).

### 2. Spuštění frontendu (Next.js):
```powershell
cd C:\Users\42077\.gemini\antigravity\scratch\nba-nerd-vault\frontend
npm run dev
```
Aplikace se otevře v prohlížeči na: `http://localhost:3000`.

*(Volitelně)* Pokud chcete pro generování scouting reportů použít vlastní Gemini API klíč, nastavte proměnnou prostředí:
```powershell
$env:GEMINI_API_KEY = "váš_api_klíč"
```
*(Pokud klíč není zadán, aplikace plynule využívá inteligentní analytický skauting v češtině založený na reálných statistikách, takže nikdy nespadne.)*

---

## ⚡ Rychlé spuštění jedním kliknutím

Dvakrát klikni na `START.bat` – uvolní porty 8000 a 3000, spustí backend
i frontend, ověří, že obě části odpovídají, otevře prohlížeč a vypíše
adresu pro telefon v domácí Wi-Fi (`http://<IP>:3000`).

---

## 🌐 Až budeš chtít aplikaci vystavit online

Kód je na to připravený – nic se nepřepisuje, jen se nastaví adresy:

- **Backend** (`backend/settings.py`) čte z prostředí:
  - `PORT` – port, výchozí `8000`
  - `ALLOWED_ORIGINS` – adresy frontendu oddělené čárkou,
    např. `https://app.tvoje-domena.cz` (prázdné = povoleno vše, pro běh doma)
- **Frontend** (`frontend/.env.local`, šablona `frontend/.env.local.example`):
  - `NEXT_PUBLIC_API_URL` – veřejná adresa backendu, např. `https://api.tvoje-domena.cz`
  - prázdné = bere se hostitel ze stránky + port 8000
    (funguje pro localhost, domácí síť i tunel)

Doma není potřeba nic nastavovat.

---

## 💾 Data

- Kariérní a klubové žebříčky (Basketball-Reference) se ukládají komprimovaně
  (`.json.gz`), celkem ~0,7 MB.
- Zajímavosti jsou ručně psané v `backend/services/nba_facts.py`.
- Profil hráče zobrazuje jen zajímavosti k danému hráči; když žádnou nemá,
  neukáže nic (žádné náhradní od jiných hráčů).

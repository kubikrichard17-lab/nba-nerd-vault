# Nasazení NBA Nerd Vault na GitHub, Render a Vercel

Aplikace má dvě části a každá patří na jiný server:

| Část | Co to je | Kam patří |
|---|---|---|
| `backend/` | Python FastAPI + SQLite databáze | **Render** (Web Service) |
| `frontend/` | Next.js 14 | **Vercel** |

Repozitář je jeden – obě složky vedle sebe. Render si bere jen `backend/`,
Vercel jen `frontend/` (nastaví se to při zakládání projektu).

---

## 1. Nahrání na GitHub

Složka projektu na disku:

```
C:\Users\42077\.gemini\antigravity\scratch\nba-nerd-vault
```

Nejjednodušší cesta: v téhle složce spusť **`NAHRAT-NA-GITHUB.bat`**
(nejdřív v něm uprav adresu repozitáře na svoji). Nebo to samé ručně –
v téhle složce otevři terminál (Windows: `cmd` nebo PowerShell) a spusť:

```bat
git init
git add .
git commit -m "NBA Nerd Vault – první nahrání"
git branch -M main
git remote add origin https://github.com/kubikrichard17-lab/nba-nerd-vault.git
git push -u origin main
```

Repozitář už je založený: **https://github.com/kubikrichard17-lab/nba-nerd-vault**
(včetně nahraných souborů), takže tenhle krok dělat nemusíš.

Co se nahraje a co ne, hlídá `.gitignore` v kořeni:

- **nenahraje se:** `node_modules/`, `frontend/.next/`, `__pycache__/`, `venv/`,
  `.env.local`, `*.log`
- **nahraje se:** `backend/nba_vault.db` a všechny `*.json.gz` – server tak má
  data hned od prvního spuštění

Velikost repozitáře je pár megabajtů, GitHub to zvládne bez potíží.

---

## 2. Backend na Render

1. Render → **New → Web Service** → **Build and deploy from a Git repository**
2. Vyber repozitář `nba-nerd-vault`
3. Nastav:
   - **Name:** `nba-nerd-vault-api`
   - **Root Directory:** `backend`
   - **Runtime:** Python 3
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `uvicorn main:app --host 0.0.0.0 --port $PORT`
   - **Instance Type:** Free
4. **Environment Variables** (nepovinné):
   - `ALLOWED_ORIGINS` – adresa frontendu na Vercelu, např.
     `https://nba-nerd-vault.vercel.app`. Když proměnnou nenastavíš,
     backend povolí všechny adresy (`*`) a funguje i z telefonu v domácí síti.
   - `GEMINI_API_KEY` – jen když chceš AI texty; bez něj aplikace používá
     vlastní české texty.
5. **Create Web Service**

Po chvíli dostaneš adresu typu `https://nba-nerd-vault-api.onrender.com`.
Ověř, že běží: otevři `https://nba-nerd-vault-api.onrender.com/api/health`
→ má vrátit `{"status": "online", ...}`.

**Pozor na free tarif:** služba se po 15 minutách nečinnosti uspí a první
požadavek pak trvá 30–60 sekund. Databáze se při restartu vrací k souboru
z repozitáře (SQLite na free tarifu nemá trvalý disk) – stažená data hráčů
se tak mohou ztratit, ale aplikace si je dotáhne znovu z NBA API.

Alternativa: v Renderu lze místo ručního nastavení použít soubor
`render.yaml` v kořeni (Blueprint) – obsahuje stejné hodnoty.

---

## 3. Frontend na Vercel

1. Vercel → **Add New → Project** → **Import Git Repository**
2. Vyber `nba-nerd-vault`
3. Nastav:
   - **Framework Preset:** Next.js
   - **Root Directory:** `frontend`
   - **Build Command:** `npm run build` (výchozí)
   - **Output Directory:** `.next` (výchozí)
4. **Environment Variables** – tady je to důležité:
   - `NEXT_PUBLIC_API_URL` = adresa backendu z Renderu,
     např. `https://nba-nerd-vault-api.onrender.com`
5. **Deploy**

Adresa, kterou Vercel přidělí (např. `https://nba-nerd-vault.vercel.app`),
patří do `ALLOWED_ORIGINS` na Renderu, pokud si CORS zpřísníš.

Když proměnnou `NEXT_PUBLIC_API_URL` nevyplníš, frontend volá backend na
stejném hostiteli na portu 8000 – to funguje doma, ale **ne na Vercelu**.
Na Vercelu ji vyplnit musíš.

---

## 4. Co je potřeba po každé změně

```bat
git add .
git commit -m "popis změny"
git push
```

Render i Vercel si změny všimnou sami a nasadí novou verzi.

---

## 5. Kdyby něco nefungovalo

| Problém | Příčina a řešení |
|---|---|
| Frontend hlásí „Chyba připojení k backendu" | Chybí `NEXT_PUBLIC_API_URL` na Vercelu, nebo backend spí (free tarif). Otevři `/api/health` backendu. |
| Backend se nespustí | V Renderu zkontroluj **Logs** – nejčastěji chybějící knihovna v `requirements.txt`. |
| CORS chyba v konzoli | `ALLOWED_ORIGINS` na Renderu musí obsahovat přesnou adresu Vercelu (s `https://`, bez lomítka na konci). |
| Data hráčů zmizela | Free tarif nemá trvalý disk. Data se dotáhnou znovu, nebo použij placený disk v Renderu. |

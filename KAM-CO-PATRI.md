# KAM CO PATŘÍ – jednoduchý přehled

Nejdůležitější věta: **ty nenahráváš soubory ručně nikam.**
Nahraješ **celou složku projektu na GitHub** a Render i Vercel si z ní vezmou
sami jen tu část, kterou potřebují.

---

## Krok 1: GitHub = celá složka

Na GitHub nahraješ **celou složku**:

```
C:\Users\42077\.gemini\antigravity\scratch\nba-nerd-vault
```

Nic nevybíráš, nic nepřesouváš. Všechno, co je uvnitř, jde najednou –
i `backend/`, i `frontend/`, i `render.yaml`, i `NASZENI.md`.

Dělá se to takhle:

1. Na GitHubu vytvoř **prázdný** repozitář (bez README, bez .gitignore).
2. Otevři soubor **`NAHRAT-NA-GITHUB.bat`** v té složce (dvojklik).
3. Repozitář je už založený a nahraný – adresa je v souboru vyplněná.
4. Hotovo – projekt je na GitHubu.

Co se **nenahraje**, protože je to velké nebo tajné (hlídá to `.gitignore`):
`node_modules/`, `frontend/.next/`, `__pycache__/`, `venv/`, `.env.local`, `*.log`.

---

## Krok 2: Render = jen složka `backend/`

Render si soubory **nekopíruješ**. Jen mu řekneš, ať se podívá do GitHubu
a vezme si podsložku `backend/`.

V Renderu při zakládání Web Service vyplň:

| Kolonka | Co tam napsat |
|---|---|
| Repository | `nba-nerd-vault` (tvůj repozitář z GitHubu) |
| **Root Directory** | `backend` ← tohle je to důležité |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `uvicorn main:app --host 0.0.0.0 --port $PORT` |

Tím je hotovo. Render si sám vezme z repozitáře jen obsah složky `backend/` –
tedy `main.py`, `services/`, `nba_vault.db`, `*.json.gz` a `requirements.txt`.

---

## Krok 3: Vercel = jen složka `frontend/`

Stejné jako u Renderu, jen s druhou složkou.

Ve Vercelu při importu projektu vyplň:

| Kolonka | Co tam napsat |
|---|---|
| Repository | `nba-nerd-vault` |
| **Root Directory** | `frontend` ← tohle je to důležité |
| Framework Preset | Next.js |
| Build Command | `npm run build` |
| Environment Variable | `NEXT_PUBLIC_API_URL` = adresa backendu z Renderu |

Vercel si sám vezme jen obsah složky `frontend/`.

---

## Celé je to o dvou kolonkách

Kdyby sis měl zapamatovat jedinou věc, tak tuhle:

- **Render → Root Directory: `backend`**
- **Vercel → Root Directory: `frontend`**

Všechno ostatní je automatické.

---

## Obrázek, ať je to jasné

```
nba-nerd-vault/            ← TOHLE CELÉ jde na GitHub
├── .gitignore
├── render.yaml
├── NASZENI.md
├── NAHRAT-NA-GITHUB.bat
├── backend/               ← z TOHOTO si bere Render
│   ├── main.py
│   ├── requirements.txt
│   ├── nba_vault.db
│   ├── *.json.gz
│   └── services/
└── frontend/              ← z TOHOTO si bere Vercel
    ├── package.json
    └── src/
```

---

## Časté nedorozumění

- ❌ „Musím na Render nahrát `main.py` přes jejich web." – Nemusíš. Render
  si ho vezme z GitHubu.
- ❌ „Musím složky rozdělit do dvou repozitářů." – Nemusíš. Jeden repozitář,
  dvě podsložky, každý server si vybere svou.
- ❌ „Musím nahrát i `node_modules`." – Nesmíš, je to obrovské. Vercel si
  balíčky nainstaluje sám z `package.json`.
- ✅ „Stačí nahrát celou složku na GitHub a nastavit dvě Root Directory." – Ano.

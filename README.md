# Liga Typerów — Mundial 2026

Aplikacja do typowania wyników meczów Mundialu 2026.
- Lokalnie: dane w SQLite
- Na Railway: dane w PostgreSQL (trwałe, wspólne dla wszystkich)

## Uruchomienie lokalne (Windows)

1. Zainstaluj Python: https://www.python.org/downloads/
   (zaznacz "Add Python to PATH")
2. Kliknij dwukrotnie `uruchom.bat`

## Deploy na Railway

### Krok 1 — GitHub
1. Załóż konto na https://github.com
2. New repository → nazwa np. `liga-typerow` → Create
3. Wgraj wszystkie pliki (bez liga.db)
4. Commit changes

### Krok 2 — Railway
1. Wejdź na https://railway.app → Login with GitHub
2. New Project → Deploy from GitHub repo → wybierz `liga-typerow`
3. Poczekaj ~1 minutę na build

### Krok 3 — Dodaj PostgreSQL
1. W projekcie kliknij **+ New** → **Database** → **PostgreSQL**
2. Railway automatycznie doda zmienną DATABASE_URL do aplikacji
3. Kliknij **Redeploy** na serwisie z aplikacją

### Krok 4 — Domena
1. Kliknij na serwis aplikacji → **Settings** → **Networking** → **Generate Domain**
2. Gotowy link udostępnij znajomym!

## Punktacja
- Dokładny wynik = 3 pkt
- Właściwy kierunek (wygrana/remis/porażka) = 1 pkt

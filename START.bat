@echo off
title NBA Nerd Vault - Spoustec
chcp 65001 >nul

set NODE_PATH=C:\Users\42077\AppData\Local\Programs\nodejs
set PYTHON_EXE=C:\Users\42077\AppData\Local\Programs\Python\Python311\python.exe
set BACKEND_DIR=C:\Users\42077\.gemini\antigravity\scratch\nba-nerd-vault\backend
set FRONTEND_DIR=C:\Users\42077\.gemini\antigravity\scratch\nba-nerd-vault\frontend
set HEALTH_URL=http://127.0.0.1:8000/api/health
set APP_URL=http://localhost:3000

echo.
echo  ====================================
echo   NBA Nerd Vault - Spousteni serveru
echo  ====================================
echo.

rem --- 0) Uvolneni portu 8000 a 3000 ---
echo [1/3] Kontrola portu 8000 a 3000...
for %%P in (8000 3000) do (
  for /f "tokens=5" %%A in ('netstat -ano ^| findstr /R /C:":%%P .*LISTENING"') do (
    echo   Port %%P je obsazeny (PID %%A^) - ukoncuji...
    taskkill /F /PID %%A >nul 2>&1
  )
)
ping -n 3 127.0.0.1 >nul

rem --- 1) Backend ---
echo [2/3] Spoustim Backend (FastAPI na portu 8000)...
rem 0.0.0.0 = backend je dostupny i z telefonu v domaci siti
start "NBA Backend" /MIN /D "%BACKEND_DIR%" cmd /k ""%PYTHON_EXE%" -m uvicorn main:app --host 0.0.0.0 --port 8000"

echo   Cekam, az backend odpovi...
set /a TRIES=0
:wait_backend
ping -n 3 127.0.0.1 >nul
curl -s -o NUL -m 3 %HEALTH_URL% && goto backend_ok
set /a TRIES+=1
if %TRIES% LSS 30 goto wait_backend
echo   ! Backend se nerozbehl vcas - podivej se do okna "NBA Backend".
goto backend_done
:backend_ok
echo   Backend bezi.
:backend_done

rem --- 2) Frontend (produkcni build, pripadne se nejdriv sestavi) ---
echo [3/3] Kontrola buildu a start frontendu (Next.js na portu 3000)...
if not exist "%FRONTEND_DIR%\.next\BUILD_ID" (
  echo   Build chybi - sestavuji frontend, muze to trvat 1-2 minuty...
  pushd "%FRONTEND_DIR%"
  set "PATH=%NODE_PATH%;%PATH%"
  call npm run build
  popd
)

start "NBA Frontend" /MIN /D "%FRONTEND_DIR%" cmd /k "set PATH=%NODE_PATH%;%PATH% && npm run start"

echo   Cekam, az frontend odpovi...
set /a TRIES=0
:wait_frontend
ping -n 3 127.0.0.1 >nul
curl -s -o NUL -m 3 %APP_URL% && goto frontend_ok
set /a TRIES+=1
if %TRIES% LSS 30 goto wait_frontend
echo   ! Frontend se nerozbehl vcas - podivej se do okna "NBA Frontend".
goto frontend_done
:frontend_ok
echo   Frontend bezi.
:frontend_done

rem --- 3) Kontrola, ze obe casti opravdu odpovidaji ---
curl -s -o NUL -m 5 %HEALTH_URL%
if errorlevel 1 (
  echo.
  echo   ! POZOR: Backend na portu 8000 neodpovida, stranka by byla prazdna.
  echo     Podivej se do okna "NBA Backend" a zjisti, co hlasi.
  echo.
  pause
  exit /b 1
)
curl -s -o NUL -m 5 %APP_URL%
if errorlevel 1 (
  echo.
  echo   ! POZOR: Frontend na portu 3000 neodpovida.
  echo     Podivej se do okna "NBA Frontend" a zjisti, co hlasi.
  echo.
  pause
  exit /b 1
)

echo.
echo  Oteviram prohlizec...
start "" "%APP_URL%"

rem --- 4) Adresa pro telefon / jine zarizeni v domaci siti ---
set LAN_IP=
for /f "tokens=2 delims=:" %%A in ('ipconfig ^| findstr /C:"IPv4"') do (
  if not defined LAN_IP set "LAN_IP=%%A"
)
if defined LAN_IP set "LAN_IP=%LAN_IP: =%"

echo.
echo  Aplikace bezi na:
echo   - Vyhledavani:     %APP_URL%
echo   - Porovnavac:      %APP_URL%/compare
echo   - Novinky:         %APP_URL%/novinky
echo   - Lidri:           %APP_URL%/lideri
echo   - Tabulka:         %APP_URL%/tabulka
echo   - Zajimavosti:     %APP_URL%/zajimavosti
echo   - API dokumentace: http://127.0.0.1:8000/docs
if defined LAN_IP (
  echo.
  echo  Z telefonu nebo jineho zarizeni ve stejne Wi-Fi:
  echo   http://%LAN_IP%:3000
)
echo.
echo  Pro zastaveni zavri okna "NBA Backend" a "NBA Frontend".
echo.
pause

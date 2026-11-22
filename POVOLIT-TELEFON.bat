@echo off
title NBA Nerd Vault - oprava pristupu z telefonu
chcp 65001 >nul

echo.
echo  ============================================================
echo   Oprava pristupu z telefonu (stejna Wi-Fi)
echo  ============================================================
echo.
echo  Windows musi povolit prijimani spojeni na portech 3000 a 8000.
echo  Tento skript vytvori dve pravidla firewallu. Spust ho jako
echo  spravce (pravym tlacitkem - Spustit jako spravce).
echo.

net session >nul 2>&1
if errorlevel 1 (
  echo  ! Neni spravcovsky rezim.
  echo    Zavri toto okno, klikni na soubor pravym tlacitkem a zvol
  echo    "Spustit jako spravce".
  echo.
  pause
  exit /b 1
)

echo  Povoluji port 3000 (frontend)...
netsh advfirewall firewall delete rule name="NBA Nerd Vault 3000" >nul 2>&1
netsh advfirewall firewall add rule name="NBA Nerd Vault 3000" dir=in action=allow protocol=TCP localport=3000 profile=any >nul
if errorlevel 1 (echo  ! Pravidlo pro 3000 se nepodarilo vytvorit.) else (echo    hotovo.)

echo  Povoluji port 8000 (backend)...
netsh advfirewall firewall delete rule name="NBA Nerd Vault 8000" >nul 2>&1
netsh advfirewall firewall add rule name="NBA Nerd Vault 8000" dir=in action=allow protocol=TCP localport=8000 profile=any >nul
if errorlevel 1 (echo  ! Pravidlo pro 8000 se nepodarilo vytvorit.) else (echo    hotovo.)

echo.
echo  Hotovo. Adresy pro telefon najdes vypisem nize:
echo.
for /f "tokens=2 delims=:" %%A in ('ipconfig ^| findstr /C:"IPv4"') do (
  for /f "tokens=* delims= " %%B in ("%%A") do echo    http://%%B:3000
)
echo.
echo  Telefon musi byt na stejne Wi-Fi. Pokud se stranka porad
echo  nenacte, zkontroluj, ze je Wi-Fi v Windows nastavena jako
echo  "Soukroma" (Nastaveni - Sit a internet - Wi-Fi - Vlastnosti).
echo.
pause

# Příkazy pro nahrání projektu na GitHub.
# Spusť v této složce (pravým tlačítkem → Spustit v terminálu, nebo dvojklik).
@echo off
chcp 65001 >nul
cd /d "%~dp0"

set REPO=https://github.com/TVUJ-UCET/nba-nerd-vault.git

echo.
echo  ==========================================
echo   NBA Nerd Vault - nahrani na GitHub
echo  ==========================================
echo.
echo  Nez zacnes: repozitar %REPO% musi existovat
echo  a byt prazdny (bez README a .gitignore).
echo.
echo  Adresu v tomto souboru uprav na svoji.
echo.

if not exist ".git" (
  echo  [1/4] Zakladam Git repozitar...
  git init || goto chyba
) else (
  echo  [1/4] Git repozitar uz existuje.
)

echo  [2/4] Pridavam soubory...
git add . || goto chyba

echo  [3/4] Vytvarim commit...
git commit -m "NBA Nerd Vault - prvni nahrani" || echo    (zadne zmeny k ulozeni)

echo  [4/4] Nahravam na GitHub...
git branch -M main
git remote remove origin >nul 2>&1
git remote add origin %REPO%
git push -u origin main || goto chyba

echo.
echo  Hotovo. Projekt je na GitHubu.
echo  Dal postupuj podle NASZENI.md (Render a Vercel).
echo.
pause
exit /b 0

:chyba
echo.
echo  ! Neco se nepovedlo. Precti chybu vyse.
echo    Nejcastěji: repozitar na GitHubu uz existuje a neni prazdny,
echo    nebo nejsi prihlaseny (git config --global user.name / user.email).
echo.
pause
exit /b 1

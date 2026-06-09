@echo off
chcp 65001 >nul
echo ================================================
echo   Liga Typerów - Mundial 2026
echo ================================================
echo.

python --version >nul 2>&1
if %errorlevel% == 0 (
    echo [OK] Znaleziono Python
    python serwer.py
    goto :end
)

py --version >nul 2>&1
if %errorlevel% == 0 (
    echo [OK] Znaleziono Python
    py serwer.py
    goto :end
)

echo [BLAD] Nie znaleziono Pythona!
echo Zainstaluj Python: https://www.python.org/downloads/
echo Zaznacz "Add Python to PATH" podczas instalacji!
pause
:end

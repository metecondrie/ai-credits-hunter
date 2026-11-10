@echo off
REM AI Credits Hunter v4 - solo busqueda (sin interfaz)
setlocal
cd /d "%~dp0"
py -3 -m ach init || exit /b 1
py -3 -m ach run %*
endlocal

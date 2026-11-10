@echo off
REM AI Credits Hunter v4 - arranque local (Windows)
REM 1) crea/migra la base de ensayo  2) corre una busqueda real  3) abre la interfaz
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
  echo ERROR: no se encontro el lanzador "py" de Python.
  exit /b 1
)

echo [1/3] Inicializando base de ensayo...
py -3 -m ach init || exit /b 1

echo [2/3] Ejecutando busqueda en fuentes publicas...
py -3 -m ach run

echo [3/3] Abriendo interfaz en http://127.0.0.1:8765
start "" http://127.0.0.1:8765
py -3 -m ach serve --port 8765
endlocal

@echo off
REM run.bat — Windows wrapper for cobol-safe-translator
REM Usage: run.bat [path\to\program.cob]
REM Default: samples\hello.cob

setlocal enabledelayedexpansion

REM ── Resolve project root ────────────────────────────────────────
cd /d "%~dp0"

REM ── Check Python 3.11+ ─────────────────────────────────────────
where python >nul 2>&1
if errorlevel 1 (
    echo ERROR: python not found on PATH. >&2
    exit /b 1
)

python -c "import sys; exit(0 if sys.version_info >= (3, 11) else 1)"
if errorlevel 1 (
    echo ERROR: Python 3.11+ required. >&2
    exit /b 1
)

REM ── Check cobol2py is installed ─────────────────────────────────
where cobol2py >nul 2>&1
if errorlevel 1 (
    echo ERROR: cobol2py not found. Install with: pip install -e . >&2
    exit /b 1
)

REM ── Determine input file ────────────────────────────────────────
set "COBOL_FILE=%~1"
if "%COBOL_FILE%"=="" set "COBOL_FILE=samples\hello.cob"

if not exist "%COBOL_FILE%" (
    echo ERROR: File not found: %COBOL_FILE% >&2
    exit /b 1
)

REM ── Derive output directory from filename ───────────────────────
for %%F in ("%COBOL_FILE%") do set "BASENAME=%%~nF"
set "OUT_DIR=output\%BASENAME%"

echo === cobol-safe-translator ===
echo Input:  %COBOL_FILE%
echo Output: %OUT_DIR%\
echo.

REM ── Run translate ───────────────────────────────────────────────
echo --- Translating to Python skeleton ---
cobol2py translate "%COBOL_FILE%" --output "%OUT_DIR%"
if errorlevel 1 (
    echo ERROR: translate failed. >&2
    exit /b 1
)
echo.

REM ── Run map ─────────────────────────────────────────────────────
echo --- Generating analysis reports ---
cobol2py map "%COBOL_FILE%" --output "%OUT_DIR%"
if errorlevel 1 (
    echo ERROR: map failed. >&2
    exit /b 1
)
echo.

REM ── Show output files ───────────────────────────────────────────
echo === Done ===
echo Output files:
dir /b "%OUT_DIR%\"

endlocal

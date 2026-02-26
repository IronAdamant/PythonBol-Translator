#!/usr/bin/env bash
# run.command — macOS wrapper for cobol-safe-translator
# Double-click from Finder or run from Terminal.
# Usage: ./run.command [path/to/program.cob]
# Default: samples/hello.cob

set -euo pipefail

# ── Switch to the script's directory (for Finder double-click) ────
cd "$(dirname "$0")"

# ── Check Python 3.11+ ───────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
    echo "ERROR: python3 not found on PATH." >&2
    echo "Press Enter to close."
    read -r
    exit 1
fi

PY_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$(echo "$PY_VERSION" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VERSION" | cut -d. -f2)

if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 11 ]; }; then
    echo "ERROR: Python 3.11+ required (found $PY_VERSION)." >&2
    echo "Press Enter to close."
    read -r
    exit 1
fi

# ── Check cobol2py is installed ───────────────────────────────────
if ! command -v cobol2py &>/dev/null; then
    echo "ERROR: cobol2py not found. Install with: pip install -e ." >&2
    echo "Press Enter to close."
    read -r
    exit 1
fi

# ── Determine input file ─────────────────────────────────────────
COBOL_FILE="${1:-samples/hello.cob}"

if [ ! -f "$COBOL_FILE" ]; then
    echo "ERROR: File not found: $COBOL_FILE" >&2
    echo "Press Enter to close."
    read -r
    exit 1
fi

# ── Derive output directory from filename ─────────────────────────
BASENAME="$(basename "$COBOL_FILE" | sed 's/\.[^.]*$//')"
OUT_DIR="output/${BASENAME}"

echo "=== cobol-safe-translator ==="
echo "Input:  $COBOL_FILE"
echo "Output: $OUT_DIR/"
echo ""

# ── Run translate ─────────────────────────────────────────────────
echo "--- Translating to Python skeleton ---"
cobol2py translate "$COBOL_FILE" --output "$OUT_DIR"
echo ""

# ── Run map ───────────────────────────────────────────────────────
echo "--- Generating analysis reports ---"
cobol2py map "$COBOL_FILE" --output "$OUT_DIR"
echo ""

# ── Show output files ─────────────────────────────────────────────
echo "=== Done ==="
echo "Output files:"
ls -1 "$OUT_DIR/"

# ── Keep terminal open when launched from Finder ──────────────────
echo ""
echo "Press Enter to close."
read -r

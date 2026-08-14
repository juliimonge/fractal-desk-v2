#!/usr/bin/env bash
#
# One-command end-to-end run.
#
#   ./run.sh              set up, build the warehouse, run the tests, print the report
#   ./run.sh dashboard    build if needed, then launch the Streamlit dashboard
#   ./run.sh clean        delete build artefacts and the virtualenv
#
# No accounts, no API keys, no cloud services. Everything runs locally against a
# DuckDB file under build/.
#
# ALL DATA IS SYNTHETIC. Nothing is filed, signed or transmitted.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"

VENV=".venv"
PY="$VENV/bin/python"

# Minimum supported interpreter is 3.11. Prefer the newest available.
find_python() {
    for candidate in python3.13 python3.12 python3.11 python3; do
        if command -v "$candidate" >/dev/null 2>&1; then
            if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
                echo "$candidate"
                return 0
            fi
        fi
    done
    echo "ERROR: Python 3.11 or newer is required but was not found." >&2
    exit 1
}

setup() {
    if [ ! -x "$PY" ]; then
        local base
        base="$(find_python)"
        echo "==> Creating virtualenv with $base"
        "$base" -m venv "$VENV"
        "$PY" -m pip install --quiet --upgrade pip
    fi
    echo "==> Installing pinned dependencies"
    "$PY" -m pip install --quiet -r requirements.txt
    "$PY" -m pip install --quiet -e .
}

build() {
    echo
    echo "==> Building the warehouse (synthetic data)"
    "$PY" -m fractal_desk.pipeline
}

test_suite() {
    echo
    echo "==> Running tests"
    "$PY" -m pytest -q
}

case "${1:-all}" in
    dashboard)
        setup
        [ -f build/fractal_desk.duckdb ] || build
        echo
        echo "==> Launching dashboard at http://localhost:8501"
        exec "$VENV/bin/streamlit" run app/streamlit_app.py
        ;;
    clean)
        echo "==> Removing build/ and $VENV"
        rm -rf build "$VENV" src/*.egg-info .pytest_cache
        find . -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
        echo "Clean."
        ;;
    all)
        setup
        build
        test_suite
        echo
        echo "===================================================================="
        echo "  Done. All data synthetic — nothing was filed, signed or sent."
        echo
        echo "  Full run report:  build/run_report.md"
        echo "  Dashboard:        ./run.sh dashboard"
        echo "===================================================================="
        ;;
    *)
        echo "Usage: ./run.sh [all|dashboard|clean]" >&2
        exit 2
        ;;
esac

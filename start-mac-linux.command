#!/bin/bash
# Mac: dublu-click pe fișier. Linux: ./start-mac-linux.command
cd "$(dirname "$0")"
if ! command -v python3 >/dev/null 2>&1; then
  echo "Python nu e instalat. Instalează-l de pe https://www.python.org/downloads/"
  exit 1
fi
if [ ! -x ".venv/bin/python" ]; then
  echo "Prima pornire: instalez ce trebuie, durează 1-2 minute..."
  python3 -m venv .venv
fi
.venv/bin/python -m pip install -q --disable-pip-version-check -r requirements.txt
.venv/bin/python -m autoposter start

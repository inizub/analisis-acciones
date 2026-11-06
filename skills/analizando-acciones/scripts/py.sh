#!/usr/bin/env bash
# Lanzador de los scripts del plugin con sus dependencias de Python.
# Uso: bash py.sh <CLAUDE_PLUGIN_DATA> <script relativo a scripts/> [argumentos...]
# uv crea la primera vez un entorno con requirements.txt (Python 3.12) y lo reutiliza después.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RAIZ="$(cd "$DIR/../../.." && pwd)"
if [ "$#" -lt 2 ]; then
  echo '{"error": "uso: py.sh <CLAUDE_PLUGIN_DATA> <script> [args]"}' >&2
  exit 2
fi
export CLAUDE_PLUGIN_DATA="$1"
shift
SCRIPT="$1"
shift
if ! command -v uv >/dev/null 2>&1; then
  echo '{"error": "Falta uv (https://docs.astral.sh/uv/). Instálalo y vuelve a intentarlo."}' >&2
  exit 2
fi
export PYTHONUTF8=1 PYTHONIOENCODING=utf-8
exec uv run --quiet --no-project --python 3.12 --with-requirements "$RAIZ/requirements.txt" \
  python "$DIR/$SCRIPT" "$@"

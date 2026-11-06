"""Guardias de los agentes del plugin (A5). Solo biblioteca estándar: se ejecuta en cada llamada a herramienta.

Uso (desde hooks/hooks.json, leyendo el JSON del hook por la entrada estándar):
    python guardia.py pre     PreToolUse: red, Bash, rutas de lectura y de escritura
    python guardia.py post    PostToolUse: traza en runs/.../traza.jsonl

Solo actúa si hay una ejecución activa (${CLAUDE_PLUGIN_DATA}/ejecucion_activa.json, creada por ejecucion.py iniciar)
y la herramienta la usa uno de los agentes del plugin. La sesión principal no tiene restricciones.
Bloqueo: código de salida 2 con el motivo en stderr (Claude Code lo muestra al agente).

Reglas:
  - analista-fundamental, forense y red-team: sin WebFetch, WebSearch, Bash ni herramientas MCP.
  - juez: Bash solo para py.sh con motor/escenarios.py, agregar.py o gate.py; sin red.
  - Lectura (Read, Glob, Grep) de esos cuatro agentes: solo en el directorio de la ejecución y en references/.
    Los analistas y el forense no pueden leer salidas de otros agentes (fase ciega); el red team no lee las del juez.
    Grep sobre un directorio no se permite a analistas ni al forense (leería todos los archivos).
  - Escritura (Write, Edit): cada agente solo puede escribir sus propios archivos dentro de la ejecución.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

PLUGIN = "analisis-acciones"
AGENTES = {"datos", "analista-fundamental", "forense", "red-team", "juez"}
SIN_RED = {"analista-fundamental", "forense", "red-team"}
CON_RUTAS = {"analista-fundamental", "forense", "red-team", "juez"}
HERRAMIENTAS_RED = re.compile(r"^(WebFetch|WebSearch|Bash|BashOutput|KillShell|mcp__.+)$")
LECTURA = {"Read", "Glob", "Grep"}
ESCRITURA = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
MAX_HORAS_ACTIVA = 12

# Salidas de otros agentes que cada agente no puede leer.
SALIDAS = r"(analista_\w+|escenarios_\w+|objeciones|juez|ajustes|agregado\w*|verdict|gate\w*|forense|hashes|baselines|sintesis|confirmacion_ruta)\.json"
PROHIBIDO_LEER = {
    "analista-fundamental": re.compile(rf"^{SALIDAS}$", re.I),
    "forense": re.compile(rf"^{SALIDAS}$", re.I),
    "red-team": re.compile(r"^(juez|ajustes|agregado\w*|verdict|gate\w*|baselines|sintesis)\.json$", re.I),
    "juez": re.compile(r"^$"),
}
PUEDE_ESCRIBIR = {
    "datos": re.compile(r"^datos_agente\.json$", re.I),
    "analista-fundamental": re.compile(r"^(analista_(A|B|N|B1)|confirmacion_ruta)\.json$", re.I),
    "forense": re.compile(r"^forense\.json$", re.I),
    "red-team": re.compile(r"^objeciones\.json$", re.I),
    "juez": re.compile(r"^(juez|ajustes)\.json$", re.I),
}
# El juez solo puede relanzar el motor, agregar o el checklist mediante el lanzador del plugin.
BASH_JUEZ = re.compile(r'^bash\s+"?[^"\s]*/scripts/py\.sh"?\s+"?[^"\s]+"?\s+(motor/escenarios|agregar|gate)\.py(\s+[^;&|<>`$()\n]*)?$')


def nombre_agente(agent_type: str | None) -> str | None:
    """'analisis-acciones:juez' → 'juez'. Acepta también el nombre sin prefijo."""
    if not agent_type:
        return None
    if ":" in agent_type:
        pref, _, nombre = agent_type.rpartition(":")
        return nombre if pref.split(":")[0] == PLUGIN and nombre in AGENTES else None
    return agent_type if agent_type in AGENTES else None


def leer_activa() -> dict | None:
    base = os.environ.get("CLAUDE_PLUGIN_DATA")
    if not base:
        return None
    ruta = Path(base) / "ejecucion_activa.json"
    try:
        a = json.loads(ruta.read_text(encoding="utf-8"))
        inicio = datetime.fromisoformat(a["inicio"].replace("Z", "+00:00"))
    except (OSError, ValueError, KeyError):
        return None
    if (datetime.now(timezone.utc) - inicio).total_seconds() > MAX_HORAS_ACTIVA * 3600:
        return None
    return a


def norm(p: str | os.PathLike) -> str:
    return os.path.normcase(os.path.realpath(os.path.expanduser(str(p))))


def dentro(p: str, raiz: str) -> bool:
    p, raiz = norm(p), norm(raiz)
    return p == raiz or p.startswith(raiz.rstrip(os.sep) + os.sep)


def raices_lectura(activa: dict) -> list[str]:
    raices = [activa["run_dir"]]
    plugin = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if plugin:
        raices.append(str(Path(plugin) / "skills" / "analizando-acciones" / "references"))
    return raices


def bloquear(motivo: str) -> None:
    print(f"[analisis-acciones] Bloqueado: {motivo}", file=sys.stderr)
    sys.exit(2)


def comprobar_lectura(agente: str, tool: str, ti: dict, cwd: str, activa: dict) -> None:
    raices = raices_lectura(activa)
    if tool == "Read":
        objetivos = [ti.get("file_path") or ""]
    elif tool == "Glob":
        objetivos = [ti.get("path") or cwd]
        if os.path.isabs(ti.get("pattern") or ""):
            objetivos.append(re.split(r"[*?\[]", ti["pattern"])[0] or cwd)
    else:
        objetivos = [ti.get("path") or cwd]
    for o in objetivos:
        if not any(dentro(o, r) for r in raices):
            bloquear(f"{agente} solo puede leer el directorio de la ejecución y references/ (intentó {o})")
        nombre = Path(o).name
        if tool in ("Read", "Grep") and PROHIBIDO_LEER[agente].match(nombre):
            bloquear(f"{agente} no puede leer {nombre}: es la salida de otro agente")
    if tool == "Grep" and agente in ("analista-fundamental", "forense") and not os.path.isfile(objetivos[0]):
        bloquear("Grep sobre un directorio no está permitido en la fase ciega; usa Read sobre los archivos permitidos")


def pre(evento: dict) -> None:
    agente = nombre_agente(evento.get("agent_type"))
    if agente is None:
        return
    activa = leer_activa()
    if activa is None:
        return
    tool, ti = evento.get("tool_name", ""), evento.get("tool_input") or {}
    cwd = evento.get("cwd") or os.getcwd()
    if agente in SIN_RED and HERRAMIENTAS_RED.match(tool):
        bloquear(f"{agente} no tiene acceso a {tool}: trabaja solo con los archivos de la ejecución")
    if agente == "juez":
        if tool in ("WebFetch", "WebSearch") or tool.startswith("mcp__"):
            bloquear(f"el juez no tiene acceso a {tool}")
        if tool == "Bash" and not BASH_JUEZ.match((ti.get("command") or "").strip()):
            bloquear("el juez solo puede ejecutar py.sh con motor/escenarios.py, agregar.py o gate.py")
    if agente in CON_RUTAS and tool in LECTURA:
        comprobar_lectura(agente, tool, ti, cwd, activa)
    if tool in ESCRITURA:
        destino = ti.get("file_path") or ti.get("notebook_path") or ""
        if not dentro(destino, activa["run_dir"]) or not PUEDE_ESCRIBIR[agente].match(Path(destino).name):
            bloquear(f"{agente} solo puede escribir sus propios archivos en el directorio de la ejecución (intentó {destino})")


def resumir(tool: str, ti: dict) -> dict:
    claves = {"Read": ["file_path"], "Write": ["file_path"], "Edit": ["file_path"], "Glob": ["pattern", "path"],
              "Grep": ["pattern", "path", "glob"], "Bash": ["command"], "WebFetch": ["url"], "WebSearch": ["query"],
              "Agent": ["subagent_type", "description"], "Task": ["subagent_type", "description"]}
    res = {k: str(ti.get(k))[:300] for k in claves.get(tool, []) if ti.get(k) is not None}
    return res or {"claves": sorted(ti)[:10]}


def post(evento: dict) -> None:
    activa = leer_activa()
    if activa is None:
        return
    linea = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "agent_type": evento.get("agent_type") or "principal", "agent_id": evento.get("agent_id"),
             "tool": evento.get("tool_name"), "args_resumidos": resumir(evento.get("tool_name", ""), evento.get("tool_input") or {})}
    try:
        with open(Path(activa["run_dir"]) / "traza.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(linea, ensure_ascii=False) + "\n")
    except OSError:
        pass


def main() -> int:
    modo = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        evento = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    if modo == "pre":
        pre(evento)
    elif modo == "post":
        post(evento)
    return 0


if __name__ == "__main__":
    sys.exit(main())

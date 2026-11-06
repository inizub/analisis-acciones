"""Hook SubagentStop (A5.3): valida la salida de un agente del plugin y, si no es válida, le impide terminar.

Lee el JSON del hook por la entrada estándar. Solo actúa con una ejecución activa y un agente del plugin.
Archivo que se valida según el agente:
  datos                 datos_agente.json   (se fusiona con datapack_base.json y se valida el datapack resultante)
  analista-fundamental  analista_<X>.json   (el que cite su último mensaje; si no cita ninguno, los modificados
                                             en los últimos 20 minutos) o confirmacion_ruta.json
  forense               forense.json
  red-team              objeciones.json
  juez                  juez.json y, si existe, ajustes.json
Bloqueo: código 2 con los errores en stderr. Para evitar bucles, tras 3 bloqueos del mismo agente se deja terminar
(el orquestador vuelve a validar con validar.py antes de seguir).
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import comun  # noqa: E402
import validar  # noqa: E402
from hooks.guardia import leer_activa, nombre_agente  # noqa: E402

MAX_BLOQUEOS = 3
RE_ANALISTA = re.compile(r"analista_(A|B|N|B1)\.json")
FIJOS = {"forense": ["forense.json"], "red-team": ["objeciones.json"], "juez": ["juez.json"]}


def archivos_a_validar(agente: str, evento: dict, d: Path) -> list[str]:
    if agente in FIJOS:
        extra = ["ajustes.json"] if agente == "juez" and (d / "ajustes.json").exists() else []
        return FIJOS[agente] + extra
    if agente == "datos":
        return ["datos_agente.json"]
    mensaje = evento.get("last_assistant_message") or ""
    citados = sorted(set(m.group(0) for m in RE_ANALISTA.finditer(mensaje)))
    if "confirmacion_ruta.json" in mensaje and not citados:
        return ["confirmacion_ruta.json"]
    if citados:
        return citados
    recientes = [p.name for p in d.glob("analista_*.json") if time.time() - p.stat().st_mtime < 20 * 60]
    return recientes or ["analista_<encuadre>.json"]


def errores_de(nombre: str, d: Path) -> list[str]:
    ruta = d / nombre
    if not ruta.exists():
        return [f"No existe {nombre}: escríbelo en {d}"]
    if nombre == "datos_agente.json":
        import ejecucion

        try:
            r = ejecucion.fusionar(d, comprobar=True)
        except (ValueError, KeyError, json.JSONDecodeError) as e:
            return [f"datos_agente.json no se puede fusionar: {e}"]
        return [] if r["valido"] else [f"datapack resultante: {e}" for e in r["errores"]]
    if nombre == "confirmacion_ruta.json":
        try:
            c = comun.leer_json(ruta)
        except json.JSONDecodeError as e:
            return [f"confirmacion_ruta.json no es JSON válido: {e}"]
        return [] if isinstance(c.get("mantiene"), bool) else ["confirmacion_ruta.json debe tener 'mantiene' (true/false)"]
    try:
        _, errores = validar.validar_archivo(ruta)
    except (ValueError, json.JSONDecodeError) as e:
        return [f"{nombre}: {e}"]
    return [f"{nombre}: {e}" for e in errores]


def main() -> int:
    try:
        evento = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    agente = nombre_agente(evento.get("agent_type"))
    activa = leer_activa()
    if agente is None or activa is None:
        return 0
    d = Path(activa["run_dir"])
    errores = [e for n in archivos_a_validar(agente, evento, d) for e in errores_de(n, d)]
    if not errores:
        return 0
    clave = evento.get("agent_id") or agente
    bloqueos = activa.setdefault("bloqueos_stop", {})
    bloqueos[clave] = bloqueos.get(clave, 0) + 1
    try:
        comun.escribir_json(Path(comun.dir_datos_plugin()) / "ejecucion_activa.json", activa)
    except OSError:
        pass
    if bloqueos[clave] > MAX_BLOQUEOS:
        return 0
    print("[analisis-acciones] Tu salida no es válida. Corrígela y vuelve a escribirla:\n- " + "\n- ".join(errores[:12]),
          file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())

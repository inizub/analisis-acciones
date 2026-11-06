"""Valida un artefacto JSON contra su esquema de assets/schemas/ y aplica reglas semánticas
que JSON Schema no expresa (p. ej. que las probabilidades de los escenarios sumen 1).

Uso CLI:
    python validar.py ARCHIVO [--esquema datapack|analista|objeciones|ajustes|verdict]

Si no se indica el esquema, se deduce del nombre del archivo. Código de salida: 0 válido, 1 inválido,
3 error de uso (archivo o esquema inexistente, JSON mal formado).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
import comun  # noqa: E402

TOLERANCIA_SUMA = 1e-6

PATRONES = [
    (re.compile(r"^datapack(_base)?\.json$"), "datapack"),
    (re.compile(r"^analista_[ABN]\.json$"), "analista"),
    (re.compile(r"^objeciones\.json$"), "objeciones"),
    (re.compile(r"^ajustes\.json$"), "ajustes"),
    (re.compile(r"^verdict\.json$"), "verdict"),
]


def esquemas_disponibles() -> list[str]:
    return sorted(p.name.removesuffix(".schema.json") for p in comun.DIR_SCHEMAS.glob("*.schema.json"))


def esquema_para(ruta: str | Path) -> str | None:
    nombre = Path(ruta).name
    return next((e for patron, e in PATRONES if patron.match(nombre)), None)


@lru_cache(maxsize=None)
def _validador(nombre: str):
    from jsonschema import Draft202012Validator

    ruta = comun.DIR_SCHEMAS / f"{nombre}.schema.json"
    if not ruta.exists():
        raise FileNotFoundError(f"Esquema inexistente: {nombre} (disponibles: {esquemas_disponibles()})")
    esquema = comun.leer_json(ruta)
    Draft202012Validator.check_schema(esquema)
    return Draft202012Validator(esquema)


def _ruta_error(e: Any) -> str:
    return "/".join(str(p) for p in e.absolute_path) or "(raíz)"


# ---------------------------------------------------------------- reglas semánticas

def _sem_analista(obj: dict) -> list[str]:
    errores = []
    esc = obj.get("escenarios", [])
    nombres = [e.get("nombre") for e in esc]
    if sorted(nombres) != ["alcista", "bajista", "base"]:
        errores.append(f"escenarios: deben ser exactamente bajista, base y alcista (hay {nombres})")
    suma = sum(e.get("p", 0) for e in esc)
    if abs(suma - 1) > TOLERANCIA_SUMA:
        errores.append(f"escenarios: las probabilidades suman {suma:.6f}, deben sumar 1")
    bajista = next((e for e in esc if e.get("nombre") == "bajista"), None)
    if bajista is not None and "perdida_permanente" not in bajista:
        errores.append("escenarios/bajista: falta perdida_permanente (pérdida explícita)")
    claves = [set(e.get("drivers", {})) for e in esc]
    if claves and any(c != claves[0] for c in claves):
        errores.append("escenarios: los tres escenarios deben usar los mismos drivers")
    return errores


def _sem_objeciones(obj: dict) -> list[str]:
    ids = [o.get("id") for o in obj.get("objeciones", [])]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    return [f"objeciones: ids duplicados {dup}"] if dup else []


def _sem_ajustes(obj: dict) -> list[str]:
    errores = []
    for i, a in enumerate(obj.get("ajustes", [])):
        if a.get("valor_anterior") == a.get("valor_nuevo"):
            errores.append(f"ajustes/{i}: valor_nuevo igual a valor_anterior")
    return errores


def _sem_verdict(obj: dict) -> list[str]:
    errores = []
    qids = [q.get("qid") for q in obj.get("preguntas", [])]
    if len(qids) != len(set(qids)):
        errores.append("preguntas: qid repetido")
    if obj.get("veredicto") != "no_analizable":
        val = obj.get("valoracion") or {}
        esc = val.get("escenarios", [])
        if esc:
            for analista in {e.get("analista") for e in esc}:
                suma = sum(e["p"] for e in esc if e.get("analista") == analista)
                if abs(suma - 1) > TOLERANCIA_SUMA:
                    errores.append(f"valoracion/escenarios: p del analista {analista} suma {suma:.6f}")
    if obj.get("checklist", {}).get("pasa") is False and obj.get("veredicto") != "no_analizable":
        errores.append("checklist fallido exige veredicto no_analizable")
    return errores


def _sem_datapack(obj: dict) -> list[str]:
    errores = []
    declarados = {d["campo"] for d in obj.get("campos_desconocidos", [])}
    for campo, v in (obj.get("fundamentales") or {}).items():
        if comun.es_desconocido(v) and campo not in declarados and f"fundamentales.{campo}" not in declarados:
            errores.append(f"fundamentales/{campo}: desconocido no listado en campos_desconocidos")
    return errores


SEMANTICA: dict[str, Callable[[dict], list[str]]] = {
    "analista": _sem_analista,
    "objeciones": _sem_objeciones,
    "ajustes": _sem_ajustes,
    "verdict": _sem_verdict,
    "datapack": _sem_datapack,
}


def validar_objeto(obj: Any, esquema: str) -> list[str]:
    """Lista de errores (vacía si es válido)."""
    v = _validador(esquema)
    errores = [f"{_ruta_error(e)}: {e.message}" for e in sorted(v.iter_errors(obj), key=lambda e: list(e.absolute_path))]
    if not errores and isinstance(obj, dict) and esquema in SEMANTICA:
        errores += SEMANTICA[esquema](obj)
    return errores


def validar_archivo(ruta: str | Path, esquema: str | None = None) -> tuple[str, list[str]]:
    esquema = esquema or esquema_para(ruta)
    if esquema is None:
        raise ValueError(f"No se puede deducir el esquema de {Path(ruta).name}; usa --esquema")
    return esquema, validar_objeto(comun.leer_json(ruta), esquema)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Valida un artefacto JSON contra su esquema.")
    p.add_argument("archivo")
    p.add_argument("--esquema", choices=esquemas_disponibles())
    a = p.parse_args(argv)
    try:
        esquema, errores = validar_archivo(a.archivo, a.esquema)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as e:
        print(json.dumps({"valido": False, "error": str(e)}, ensure_ascii=False))
        return 3
    print(json.dumps({"archivo": a.archivo, "esquema": esquema, "valido": not errores, "errores": errores},
                     ensure_ascii=False, indent=2))
    return 0 if not errores else 1


if __name__ == "__main__":
    sys.exit(main())

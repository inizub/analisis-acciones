"""Checklist de 11 puntos (A6.7). Cualquier fallo → no_analizable, con la lista de fallos.

Uso CLI:
    python gate.py --dir RUN_DIR --modo completo|rapido|degradado [--fase previo|final] [--salida gate.json]

Fases:
  previo  con el datapack y el router (puntos 1, 2, 3 y 11): permite cerrar un análisis imposible antes de
          gastar tokens en los analistas.
  final   los 11 puntos. Los puntos que dependen de salidas que no existen cuentan como fallo.
Si la ruta es fuera_de_alcance, el único fallo que se informa es el 3.

Archivos de RUN_DIR: datapack.json (o datapack_base.json), router.json, motor_inicial.json, analista_<X>.json,
escenarios_<X>.json, forense.json, juez.json o sintesis.json.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import comun  # noqa: E402
import validar  # noqa: E402

NOMBRES = {
    1: "Campos críticos de la ruta con fuente y fecha, sin desconocidos",
    2: "Discrepancia entre EDGAR y la fuente secundaria ≤ 2 % o resuelta a favor de EDGAR",
    3: "Ruta dentro del alcance",
    4: "Escenarios válidos: probabilidades suman 1 y el bajista tiene pérdida explícita",
    5: "DCF inverso ejecutado",
    6: "Pre-mortem presente",
    7: "Criterios de invalidación presentes (≥ 2)",
    8: "Mejor contraargumento presente (modo completo)",
    9: "Ninguna bandera forense invalidante",
    10: "El balance sobrevive al escenario bajista",
    11: "Datos de precio recientes",
}
ESTADOS_DISCREPANCIA_OK = {"ok", "discrepancia_resuelta_edgar", "sin_comparar"}


def _ok(detalle: str = "") -> dict:
    return {"estado": "ok", "detalle": detalle}


def _fallo(detalle: str) -> dict:
    return {"estado": "fallo", "detalle": detalle}


def _no_evaluado(detalle: str) -> dict:
    return {"estado": "no_evaluado", "detalle": detalle}


# ---------------------------------------------------------------- acceso a campos del datapack

def resolver_campo(dp: dict, ruta: str) -> tuple[Any, str | None]:
    nodo: Any = dp
    for parte in ruta.split("/"):
        if isinstance(nodo, dict) and parte in nodo:
            nodo = nodo[parte]
        else:
            return None, "ausente"
    return nodo, None


def _sin_fuente(c: dict) -> bool:
    return not c.get("fuente_url") or not c.get("fecha_dato")


def comprobar_campo(dp: dict, ruta: str) -> str | None:
    """Motivo del fallo de un campo crítico, o None si está presente con fuente y fecha."""
    nodo, err = resolver_campo(dp, ruta)
    if err:
        return f"{ruta}: ausente"
    if comun.es_desconocido(nodo):
        return f"{ruta}: desconocido ({nodo.get('causa')})"
    if isinstance(nodo, list):
        if not nodo:
            return f"{ruta}: vacío"
        for item in nodo:
            ing = item.get("ingresos") if isinstance(item, dict) else None
            if isinstance(ing, dict) and (comun.es_desconocido(ing) or _sin_fuente(ing)):
                return f"{ruta}: el segmento '{item.get('nombre')}' sin fuente o desconocido"
        return None
    if isinstance(nodo, dict) and "serie" in nodo:
        if not nodo["serie"]:
            return f"{ruta}: serie vacía"
        if nodo.get("desactualizada"):
            return f"{ruta}: desactualizado (último dato {nodo.get('ultimo_periodo')})"
        return f"{ruta}: último dato sin fuente o fecha" if _sin_fuente(nodo["serie"][-1]) else None
    if isinstance(nodo, dict) and "valor" in nodo:
        return f"{ruta}: sin fuente o fecha" if _sin_fuente(nodo) else None
    return f"{ruta}: formato no reconocido"


def campos_criticos(ruta: str, cfg: dict) -> list[str]:
    g = cfg["gate"]["campos_criticos"]
    return [] if ruta == "fuera_de_alcance" else list(g["_comunes"]) + list(g[ruta])


def capital_bancario(dp: dict) -> dict | None:
    """Ratio de capital y su requisito: CET1 si el emisor lo publica; si no, el ratio de capital total regulatorio.
    Devuelve {tipo, valor, requisito} o None si falta el par completo."""
    banca = dp.get("banca") or {}
    for tipo, clave in (("CET1", "cet1"), ("capital total", "capital_total")):
        if comprobar_campo(dp, f"banca/{clave}") is None and comprobar_campo(dp, f"banca/{clave}_requisito") is None:
            return {"tipo": tipo, "valor": ultimo_valor(banca[clave]),
                    "requisito": ultimo_valor(banca[f"{clave}_requisito"])}
    return None


def faltan_criticos(dp: dict, ruta: str, cfg: dict) -> list[str]:
    """Motivos de los campos críticos que faltan, incluido el capital en la ruta bancaria."""
    faltan = [m for c in campos_criticos(ruta, cfg) if (m := comprobar_campo(dp, c))]
    if ruta == "banco_credito" and capital_bancario(dp) is None:
        faltan.append("banca/cet1 y banca/cet1_requisito (o, si no se publica CET1, banca/capital_total y "
                      "banca/capital_total_requisito): sin datos con fuente y fecha")
    return faltan


def ultimo_valor(dp_nodo: Any) -> float | None:
    """Último valor de una serie o cifra; None si es desconocido o no existe."""
    if not dp_nodo or comun.es_desconocido(dp_nodo):
        return None
    if "serie" in dp_nodo:
        return dp_nodo["serie"][-1]["valor"] if dp_nodo["serie"] else None
    return dp_nodo.get("valor")


# ---------------------------------------------------------------- puntos del checklist

def punto_1(dp: dict, ruta: str, cfg: dict) -> dict:
    fallos = faltan_criticos(dp, ruta, cfg)
    if fallos:
        return _fallo("; ".join(fallos))
    r = _ok(f"{len(campos_criticos(ruta, cfg))} campos comprobados")
    cap = capital_bancario(dp) if ruta == "banco_credito" else None
    if cap and cap["tipo"] != "CET1":
        r["aviso"] = "El emisor no publica CET1: se usa el ratio de capital total regulatorio y su mínimo"
    return r


def punto_2(dp: dict) -> dict:
    v = dp.get("verificacion_cruzada") or {}
    mal = {c: d.get("estado") for c, d in v.items() if d.get("estado") not in ESTADOS_DISCREPANCIA_OK}
    if mal:
        return _fallo("discrepancia sin resolver en " + ", ".join(f"{c} ({e})" for c, e in mal.items()))
    avisos = [f"{c}: {d['estado']}" for c, d in v.items() if d.get("estado") != "ok"]
    r = _ok("sin discrepancias sin resolver")
    if avisos:
        r["avisos"] = avisos
    return r


def punto_3(router: dict) -> dict:
    if router["ruta"] == "fuera_de_alcance":
        return _fallo(f"ruta fuera de alcance: {router['motivo']}")
    return _ok(f"ruta {router['ruta']}")


def punto_4(analistas: dict[str, dict | None], esperados: list[str]) -> dict:
    fallos = []
    for n in esperados:
        a = analistas.get(n)
        if a is None:
            fallos.append(f"falta analista_{n}.json")
            continue
        errores = validar.validar_objeto(a, "analista")
        if errores:
            fallos.append(f"analista {n}: " + "; ".join(errores[:3]))
    return _fallo(" | ".join(fallos)) if fallos else _ok("escenarios válidos: " + ", ".join(esperados))


def punto_5(motor: dict | None) -> dict:
    if motor and motor.get("error"):
        return _fallo(f"el motor no pudo construir la base: {motor['error']}")
    r = (motor or {}).get("reverse_dcf")
    if not r or "principal" not in r:
        return _fallo("motor_inicial.json no contiene el DCF inverso")
    return _ok("sin raíz" if r.get("sin_raiz") else f"{r['principal']['driver']} = {r['principal']['valor']}")


def punto_6(analistas: dict[str, dict | None], esperados: list[str]) -> dict:
    mal = [n for n in esperados if not analistas.get(n) or
           len([x for x in analistas[n].get("pre_mortem", []) if str(x).strip()]) < 3]
    return _fallo("pre-mortem ausente o incompleto en " + ", ".join(mal)) if mal else _ok()


def punto_7(sintesis: dict | None) -> dict:
    n = len((sintesis or {}).get("criterios_invalidacion") or [])
    return _ok(f"{n} criterios") if n >= 2 else _fallo(f"{n} criterios de invalidación (mínimo 2)")


def punto_8(sintesis: dict | None, modo: str) -> dict:
    if modo != "completo":
        return _no_evaluado("solo se exige en modo completo")
    c = (sintesis or {}).get("mejor_contraargumento")
    return _ok() if isinstance(c, str) and c.strip() else _fallo("falta el mejor contraargumento")


def punto_9(forense: dict | None) -> dict:
    inval = [b["bandera"] for b in (forense or {}).get("banderas", []) if b.get("nivel") == "invalidante"]
    return _fallo("bandera forense invalidante: " + "; ".join(inval)) if inval else _ok()


def cobertura_bajista(dp: dict, motor: dict | None, escenarios: dict[str, dict | None]) -> tuple[float | None, str]:
    """EBIT del escenario bajista (ingresos actuales × margen bajista del peor analista) / gasto por intereses.
    Devuelve (cobertura, motivo_si_no_calculable)."""
    ingresos0 = ((motor or {}).get("base") or {}).get("ingresos0") or ultimo_valor(dp["fundamentales"].get("ingresos"))
    margenes = []
    for e in escenarios.values():
        baj = next((s for s in (e or {}).get("escenarios", []) if s["nombre"] == "bajista"), None)
        m = (baj or {}).get("drivers_usados", {}).get("margen_operativo")
        if isinstance(m, list):
            m = m[0] if m else None
        if m is not None:
            margenes.append(m)
    if ingresos0 is None or not margenes:
        return None, "el escenario bajista no incluye margen operativo"
    gi = dp["fundamentales"].get("gasto_intereses")
    if not gi or comun.es_desconocido(gi) or gi.get("desactualizada") or not gi.get("serie"):
        return None, "sin gasto por intereses actualizado"
    interes = abs(gi["serie"][-1]["valor"])
    if interes == 0:
        return float("inf"), ""
    return ingresos0 * min(margenes) / interes, ""


def punto_10(dp: dict, ruta: str, motor: dict | None, escenarios: dict[str, dict | None], cfg: dict) -> dict:
    g = cfg["gate"]
    if ruta == "banco_credito":
        cap = capital_bancario(dp)
        if cap is None:
            return _fallo("faltan CET1 (o el ratio de capital total) y su requisito")
        if cap["valor"] > cap["requisito"]:
            return _ok(f"{cap['tipo']} {cap['valor']:.2%} > requisito {cap['requisito']:.2%}")
        return _fallo(f"{cap['tipo']} {cap['valor']:.2%} no supera el requisito {cap['requisito']:.2%}")
    cob, motivo = cobertura_bajista(dp, motor, escenarios)
    if cob is None:
        deuda = ultimo_valor(dp["fundamentales"].get("deuda_total")) or 0
        if "intereses" in motivo and deuda > 0 and g["cobertura_sin_dato"] == "fallo":
            return _fallo(f"{motivo} con deuda de {deuda:.3g}")
        r = _no_evaluado(motivo)
        r["aviso"] = f"Punto 10 no evaluable: {motivo}"
        return r
    if cob > g["cobertura_bajista_min"]:
        return _ok("sin gasto por intereses" if cob == float("inf") else f"cobertura en el bajista {cob:.2f}")
    return _fallo(f"cobertura de intereses en el escenario bajista {cob:.2f} ≤ {g['cobertura_bajista_min']}")


def punto_11(dp: dict, cfg: dict) -> dict:
    p = dp.get("precios")
    if not p or comun.es_desconocido(p):
        return _fallo("sin datos de precio")
    dias, maximo = p["antiguedad_dias"], cfg["datos"]["precio_max_dias"]
    return _ok(f"{dias} días") if dias <= maximo else _fallo(f"precio de hace {dias} días (máximo {maximo})")


# ---------------------------------------------------------------- evaluación

def evaluar(dp: dict, router: dict, modo: str, fase: str = "final", motor: dict | None = None,
            analistas: dict[str, dict | None] | None = None, escenarios: dict[str, dict | None] | None = None,
            forense: dict | None = None, sintesis: dict | None = None, cfg: dict | None = None) -> dict:
    cfg = cfg or comun.cargar_config()
    analistas, escenarios = analistas or {}, escenarios or {}
    esperados = comun.analistas_de_modo(modo)
    items: dict[int, dict] = {}
    if router["ruta"] == "fuera_de_alcance":
        items = {n: _no_evaluado("ruta fuera de alcance") for n in NOMBRES}
        items[3] = punto_3(router)
    else:
        items[1] = punto_1(dp, router["ruta"], cfg)
        items[2] = punto_2(dp)
        items[3] = punto_3(router)
        items[11] = punto_11(dp, cfg)
        if fase == "previo":
            for n in (4, 5, 6, 7, 8, 9, 10):
                items[n] = _no_evaluado("fase previa")
        else:
            items[4] = punto_4(analistas, esperados)
            items[5] = punto_5(motor)
            items[6] = punto_6(analistas, esperados)
            items[7] = punto_7(sintesis)
            items[8] = punto_8(sintesis, modo)
            items[9] = punto_9(forense)
            items[10] = punto_10(dp, router["ruta"], motor, escenarios, cfg)
    fallos = [f"{n}. {NOMBRES[n]}: {r['detalle']}" for n, r in sorted(items.items()) if r["estado"] == "fallo"]
    avisos = [a for r in items.values() for a in ([r["aviso"]] if r.get("aviso") else []) + r.get("avisos", [])]
    return {"ticker": dp.get("ticker"), "modo": modo, "fase": fase, "ruta": router["ruta"], "pasa": not fallos,
            "fallos": fallos, "avisos": avisos,
            "items": {str(n): {"nombre": NOMBRES[n], **r} for n, r in sorted(items.items())}}


# ---------------------------------------------------------------- E/S

def _leer(d: Path, *nombres: str) -> Any:
    for n in nombres:
        if (d / n).exists():
            return comun.leer_json(d / n)
    return None


def cargar(directorio: Path, modo: str) -> dict:
    esperados = comun.analistas_de_modo(modo)
    return {
        "dp": _leer(directorio, "datapack.json", "datapack_base.json"),
        "router": _leer(directorio, "router.json"),
        "motor": _leer(directorio, "motor_inicial.json"),
        "analistas": {n: _leer(directorio, f"analista_{n}.json") for n in esperados},
        "escenarios": {n: _leer(directorio, f"escenarios_{n}.json") for n in esperados},
        "forense": _leer(directorio, "forense.json"),
        "sintesis": _leer(directorio, "juez.json", "sintesis.json"),
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Checklist de 11 puntos.")
    p.add_argument("--dir", required=True)
    p.add_argument("--modo", required=True, choices=comun.MODOS)
    p.add_argument("--fase", choices=["previo", "final"], default="final")
    p.add_argument("--salida")
    a = p.parse_args(argv)
    d = Path(a.dir)
    datos = cargar(d, a.modo)
    if datos["dp"] is None or datos["router"] is None:
        comun.salir_con_error("Faltan datapack.json (o datapack_base.json) o router.json")
    res = evaluar(datos["dp"], datos["router"], a.modo, a.fase, datos["motor"], datos["analistas"],
                  datos["escenarios"], datos["forense"], datos["sintesis"])
    destino = Path(a.salida) if a.salida else d / ("gate_previo.json" if a.fase == "previo" else "gate.json")
    comun.escribir_json(destino, res)
    print(destino)
    return 0


if __name__ == "__main__":
    sys.exit(main())

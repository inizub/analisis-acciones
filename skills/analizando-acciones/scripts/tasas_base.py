"""Tasas base: percentil y z de cada driver frente a su clase de referencia, banderas de plausibilidad y valor encogido.

Clase de referencia: tamaño de ventas (M$) y sector, en assets/base_rates.csv. Sin fila para el sector se usa `todos`;
sin fila para la clase de tamaño, la clase `todas` (se anota en `nota`).

Uso CLI:
    python tasas_base.py --datapack datapack.json [--drivers drivers.json] [--salida tasas_base.json]
        drivers.json: {"crecimiento_ventas_5a": 0.12, "margen_operativo": 0.25, "roic_roe": 0.30}
    python tasas_base.py --valor 0.12 --metrica crecimiento_ventas_5a --ventas-musd 3500

Banderas: z > 2 → requiere_evidencia_excepcional; z > 3 → casi_imposible_organicamente.
Encogimiento: estimación = media + k·(observado − media), con k de config.yaml (tasas_base_k).
"""
from __future__ import annotations

import argparse
import csv
import math
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import comun  # noqa: E402

RUTA_BASE_RATES = comun.DIR_ASSETS / "base_rates.csv"
KNOTS = (("p10", 10), ("p25", 25), ("p50", 50), ("p75", 75), ("p90", 90))
Z_P90 = 1.2815515655446004

# driver del analista -> (métrica de la tabla, clave de k en config)
ALIAS_DRIVER = {
    "crecimiento_ingresos": ("crecimiento_ventas_5a", "crecimiento_ventas"),
    "crecimiento_ventas": ("crecimiento_ventas_5a", "crecimiento_ventas"),
    "crecimiento_ventas_3a": ("crecimiento_ventas_3a", "crecimiento_ventas"),
    "crecimiento_ventas_5a": ("crecimiento_ventas_5a", "crecimiento_ventas"),
    "margen_operativo": ("margen_operativo", "margen_operativo"),
    "roic": ("roe", "roic_roe"),
    "roe": ("roe", "roic_roe"),
    "roic_roe": ("roe", "roic_roe"),
}


def clase_tamano(ventas_musd: float | None, limites: list[float] | None = None) -> str | None:
    """Etiqueta de la clase de tamaño ('2000-5000', '>50000') o None si no se conocen las ventas o son < mínimo."""
    if ventas_musd is None or ventas_musd <= 0:
        return None
    limites = limites or comun.cargar_config()["tasas_base"]["clases_musd"]
    if ventas_musd < limites[0]:
        return None
    for i, lo in enumerate(limites):
        hi = limites[i + 1] if i + 1 < len(limites) else None
        if ventas_musd >= lo and (hi is None or ventas_musd < hi):
            return f">{lo:g}" if hi is None else f"{lo:g}-{hi:g}"
    return None


@lru_cache(maxsize=4)
def cargar_tabla(ruta: str = str(RUTA_BASE_RATES)) -> tuple[dict, ...]:
    if not Path(ruta).exists():
        raise comun.ErrorDatos(f"No existe {ruta}; genera base_rates.csv con tasas_base_build.py", "not_covered")
    filas = []
    with open(ruta, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            for c in ("n", "media", "desv", "p10", "p25", "p50", "p75", "p90"):
                r[c] = float(r[c]) if r.get(c) not in (None, "") else None
            filas.append(r)
    return tuple(filas)


def buscar_fila(tabla, metrica: str, clase: str | None, sector: str = "todos") -> tuple[dict | None, str | None]:
    """Fila más específica disponible. Orden: (clase, sector) → (clase, todos) → (todas, sector) → (todas, todos).
    Devuelve (fila, nota) con nota explicando la degradación."""
    candidatos = []
    if clase:
        candidatos += [(clase, sector, None), (clase, "todos", f"sin sector {sector} en la clase {clase}; se usa 'todos'")]
    candidatos += [("todas", sector, "sin clase de tamaño; se usa la muestra completa"),
                   ("todas", "todos", "sin clase de tamaño ni sector; se usa la muestra completa")]
    for c, s, nota in candidatos:
        for r in tabla:
            if r["metrica"] == metrica and r["clase_musd"] == c and r["sector"] == s and r["media"] is not None \
                    and r["desv"]:
                return r, nota
    return None, None


def _cdf_normal(z: float) -> float:
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def percentil(valor: float, fila: dict) -> float:
    """Percentil (0-100). Con cuantiles empíricos interpola entre p10 y p90 y usa la normal fuera de ese rango
    (acotada a [90, 99.9] por arriba y [0.1, 10] por abajo). Sin cuantiles, normal."""
    z = (valor - fila["media"]) / fila["desv"]
    normal = 100 * _cdf_normal(z)
    puntos = [(fila[k], p) for k, p in KNOTS if fila.get(k) is not None]
    if len(puntos) < 5:
        return normal
    xs = [x for x, _ in puntos]
    if valor <= xs[0]:
        return min(max(normal, 0.1), 10.0)
    if valor >= xs[-1]:
        return min(max(normal, 90.0), 99.9)
    for (x0, p0), (x1, p1) in zip(puntos, puntos[1:]):
        if x0 <= valor <= x1:
            return p0 if x1 == x0 else p0 + (p1 - p0) * (valor - x0) / (x1 - x0)
    return normal


def z_score(valor: float, fila: dict) -> float:
    return (valor - fila["media"]) / fila["desv"]


def bandera(z: float, cfg: dict | None = None) -> str | None:
    t = (cfg or comun.cargar_config())["tasas_base"]
    if z > t["z_imposible"]:
        return "casi_imposible_organicamente"
    if z > t["z_evidencia"]:
        return "requiere_evidencia_excepcional"
    return None


def encoger(observado: float, media: float, k: float) -> float:
    return media + k * (observado - media)


def p90(fila: dict) -> float:
    """Percentil 90 de la clase: empírico si existe, si no media + 1,2816·desv."""
    return fila["p90"] if fila.get("p90") is not None else fila["media"] + Z_P90 * fila["desv"]


def evaluar(driver: str, valor: float, ventas_musd: float | None, sector: str = "todos", tabla=None,
            cfg: dict | None = None) -> dict:
    """Evalúa un driver. Devuelve percentil, z, bandera, valor encogido y la fila de referencia usada."""
    cfg = cfg or comun.cargar_config()
    if driver not in ALIAS_DRIVER:
        raise ValueError(f"Driver sin tasa base: {driver} (válidos: {sorted(ALIAS_DRIVER)})")
    metrica, clave_k = ALIAS_DRIVER[driver]
    tabla = tabla if tabla is not None else cargar_tabla()
    clase = clase_tamano(ventas_musd, cfg["tasas_base"]["clases_musd"])
    fila, nota = buscar_fila(tabla, metrica, clase, sector)
    if fila is None:
        return {"driver": driver, "metrica": metrica, "valor": valor, "estado": "sin_referencia",
                "nota": f"sin fila de tasa base para {metrica}"}
    z = z_score(valor, fila)
    k = cfg["tasas_base_k"][clave_k]
    return {"driver": driver, "metrica": metrica, "valor": valor, "estado": "ok", "clase": fila["clase_musd"],
            "sector": fila["sector"], "percentil": percentil(valor, fila), "z": z, "bandera": bandera(z, cfg),
            "referencia": {"media": fila["media"], "desv": fila["desv"], "n": fila["n"], "p90": p90(fila),
                           "fuente": fila["fuente"], "periodo": fila["periodo"]},
            "k": k, "valor_encogido": encoger(valor, fila["media"], k), "nota": nota}


# ---------------------------------------------------------------- observados a partir del datapack

def _serie(dp: dict, campo: str) -> list[dict]:
    v = (dp.get("fundamentales") or {}).get(campo)
    return [] if not v or comun.es_desconocido(v) else v["serie"]


def tcac(valores: list[float], anios: int) -> float | None:
    """TCAC de los últimos `anios` años; None si no hay datos suficientes o el inicio no es positivo."""
    if len(valores) < anios + 1 or valores[-anios - 1] <= 0 or valores[-1] <= 0:
        return None
    return (valores[-1] / valores[-anios - 1]) ** (1 / anios) - 1


def ventas_musd(dp: dict) -> float | None:
    """Ventas del último ejercicio en M$. Solo si el informe está en USD."""
    s = _serie(dp, "ingresos")
    if not s or s[-1].get("moneda") != "USD":
        return None
    return s[-1]["valor"] / 1e6


def observados(dp: dict) -> dict[str, float | None]:
    ing = [p["valor"] for p in _serie(dp, "ingresos")]
    ebit = {p["fecha_dato"]: p["valor"] for p in _serie(dp, "beneficio_operativo")}
    fechas = [p["fecha_dato"] for p in _serie(dp, "ingresos")]
    margen = ebit[fechas[-1]] / ing[-1] if fechas and fechas[-1] in ebit and ing[-1] else None
    bn = {p["fecha_dato"]: p["valor"] for p in _serie(dp, "beneficio_neto")}
    pat = {p["fecha_dato"]: p["valor"] for p in _serie(dp, "patrimonio")}
    f = fechas[-1] if fechas else None
    roe = bn[f] / pat[f] if f in bn and f in pat and pat[f] > 0 else None
    return {"crecimiento_ventas_3a": tcac(ing, 3), "crecimiento_ventas_5a": tcac(ing, 5),
            "margen_operativo": margen, "roe": roe}


def construir(dp: dict, drivers: dict[str, float] | None = None, sector: str = "todos", tabla=None,
              cfg: dict | None = None) -> dict:
    """Sección `tasas_base` del datapack: clase de referencia, observados con su percentil y encogimiento, y drivers."""
    cfg = cfg or comun.cargar_config()
    tabla = tabla if tabla is not None else cargar_tabla()
    v = ventas_musd(dp)
    clase = clase_tamano(v, cfg["tasas_base"]["clases_musd"])
    res: dict[str, Any] = {"ticker": dp.get("ticker"), "ventas_musd": v, "clase_tamano": clase, "sector": sector,
                           "observados": {}, "drivers": {}, "para_reverse_dcf": {}}
    if v is None:
        res["aviso"] = "ventas no disponibles en USD: se usa la muestra completa"
    for metrica, valor in observados(dp).items():
        if valor is None:
            res["observados"][metrica] = {"estado": "sin_datos"}
            continue
        res["observados"][metrica] = evaluar(metrica, valor, v, sector, tabla, cfg)
    for d, valor in (drivers or {}).items():
        res["drivers"][d] = evaluar(d, valor, v, sector, tabla, cfg)
    for d in ("crecimiento_ingresos", "margen_operativo", "roe"):
        metrica = ALIAS_DRIVER[d][0]
        fila, _ = buscar_fila(tabla, metrica, clase, sector)
        if fila:
            res["para_reverse_dcf"][d] = {"media": fila["media"], "desv": fila["desv"]}
    return res


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Tasas base: percentil, z, banderas y valor encogido.")
    p.add_argument("--datapack")
    p.add_argument("--drivers", help="JSON {driver: valor}")
    p.add_argument("--sector", default="todos")
    p.add_argument("--salida")
    p.add_argument("--valor", type=float)
    p.add_argument("--metrica")
    p.add_argument("--ventas-musd", type=float)
    a = p.parse_args(argv)
    try:
        if a.valor is not None:
            if not a.metrica:
                comun.salir_con_error("--valor exige --metrica")
            res = evaluar(a.metrica, a.valor, a.ventas_musd, a.sector)
        elif a.datapack:
            drivers = comun.leer_json(a.drivers) if a.drivers else None
            res = construir(comun.leer_json(a.datapack), drivers, a.sector)
        else:
            comun.salir_con_error("indica --datapack o --valor/--metrica")
    except (comun.ErrorDatos, ValueError) as e:
        comun.salir_con_error(str(e))
    if a.salida:
        comun.escribir_json(a.salida, res)
        print(a.salida)
    else:
        print(comun.volcar_json(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())

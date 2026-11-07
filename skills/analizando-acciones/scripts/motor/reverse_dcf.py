"""DCF inverso: qué expectativas descuenta el precio actual.

Orden (empresas no financieras), con scipy.optimize.brentq:
  1. crecimiento de ingresos implícito en [−20 %, 60 %], con los márgenes del escenario base
     (crecimiento constante 5 años y descenso lineal hasta g_terminal en el año 10);
  2. margen operativo implícito en [0 %, 60 %], con el crecimiento base;
  3. años de ventaja competitiva implícitos (búsqueda entera 1-40: años de crecimiento base antes del valor terminal).
Bancos: ROE implícito sostenido (excess return con ROE constante también en el valor terminal).
Sin raíz → sin_raiz: true. Si se da una tasa base {media, desv}, devuelve el percentil del valor implícito.

Uso CLI:
    python reverse_dcf.py ENTRADA.json   ({"precio": P, "base": {...}, "ruta": "general", "tasas_base": {...}})
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Callable

from scipy.optimize import brentq

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from motor.comun_motor import ErrorMotor, crecimiento_con_desvanecimiento, exigir  # noqa: E402
from motor.dcf import dcf_fcff  # noqa: E402
from motor.excess_return import valor_excess_return  # noqa: E402

RANGO_CRECIMIENTO = (-0.20, 0.60)
RANGO_MARGEN = (0.0, 0.60)
RANGO_ANIOS = (1, 40)
RANGO_ROE = (-0.10, 0.60)
CLAVES_DCF = {"ingresos0", "ventas_capital", "tasa_impuestos", "wacc", "g_terminal", "rf", "deuda", "caja", "acciones",
              "roic_terminal", "margen_inicial", "anios_convergencia_margen", "moat_documentado", "otros_activos",
              "minoritarios", "tasa_impuestos_terminal"}


def percentil_normal(x: float | None, media: float, desv: float) -> float | None:
    if x is None or desv <= 0:
        return None
    return 100 * 0.5 * (1 + math.erf((x - media) / (desv * math.sqrt(2))))


def valor_dcf(base: dict, crecimiento: float | None = None, margen: float | None = None, anios: int = 10) -> float:
    args = {k: v for k, v in base.items() if k in CLAVES_DCF}
    g = base["crecimiento"] if crecimiento is None else crecimiento
    g_term = base["g_terminal"]
    if isinstance(g, (int, float)):
        g = crecimiento_con_desvanecimiento(g, g_term, anios, min(5, anios)) if anios >= 5 else [g] * anios
    return dcf_fcff(crecimiento=g, margen_operativo=base["margen_operativo"] if margen is None else margen,
                    anios=anios, **args)["valor_por_accion"]


def _raiz(f: Callable[[float], float], a: float, b: float) -> float | None:
    fa, fb = f(a), f(b)
    if fa == 0:
        return a
    if fb == 0:
        return b
    if fa * fb > 0:
        return None
    return float(brentq(f, a, b, xtol=1e-10, rtol=1e-12, maxiter=500))


def _sentido(f: Callable[[float], float], a: float) -> str:
    """Sin raíz: "barato" si ya con el valor más bajo del rango el modelo supera el precio (el valor crece con el driver);
    "caro" si ni con el más alto se alcanza."""
    return "barato" if f(a) > 0 else "caro"


def resolver_crecimiento(precio: float, base: dict, rango: tuple[float, float] = RANGO_CRECIMIENTO) -> dict:
    f = lambda x: valor_dcf(base, crecimiento=x) - precio  # noqa: E731
    g = _raiz(f, *rango)
    return {"driver": "crecimiento_ingresos", "valor": g, "sin_raiz": g is None, "rango": list(rango),
            "sentido": None if g is not None else _sentido(f, rango[0])}


def resolver_margen(precio: float, base: dict, rango: tuple[float, float] = RANGO_MARGEN) -> dict:
    # El margen objetivo implícito; se anula la convergencia desde el margen inicial para que el margen sea único.
    b = {k: v for k, v in base.items() if k not in ("margen_inicial", "anios_convergencia_margen")}
    f = lambda x: valor_dcf(b, margen=x) - precio  # noqa: E731
    m = _raiz(f, *rango)
    return {"driver": "margen_operativo", "valor": m, "sin_raiz": m is None, "rango": list(rango),
            "sentido": None if m is not None else _sentido(f, rango[0])}


def resolver_anios_ventaja(precio: float, base: dict, rango: tuple[int, int] = RANGO_ANIOS) -> dict:
    """Menor número de años de crecimiento base (seguidos de valor terminal con ROIC = WACC) cuyo valor ≥ precio."""
    b = dict(base)
    b["moat_documentado"] = False
    valores = []
    for n in range(rango[0], rango[1] + 1):
        v = valor_dcf(b, crecimiento=[base["crecimiento"]] * n if isinstance(base["crecimiento"], (int, float))
                      else list(base["crecimiento"])[:n], anios=n)
        valores.append(v)
        if v >= precio:
            return {"driver": "anios_ventaja", "valor": n, "sin_raiz": False, "rango": list(rango)}
    return {"driver": "anios_ventaja", "valor": None, "sin_raiz": True, "rango": list(rango), "sentido": "caro",
            "valor_maximo_alcanzado": max(valores)}


def resolver_roe(precio: float, base_banco: dict, rango: tuple[float, float] = RANGO_ROE) -> dict:
    """ROE sostenido (explícito y terminal) que iguala el valor del excess return al precio."""
    def f(roe: float) -> float:
        return valor_excess_return(base_banco["patrimonio0"], roe, base_banco["ke"], base_banco["payout"],
                                   base_banco["acciones"], base_banco.get("anios", 5), roe_estable=roe,
                                   ke_estable=base_banco.get("ke_estable"), g_estable=base_banco.get("g_estable", 0.0)
                                   )["valor_por_accion"] - precio
    r = _raiz(f, *rango)
    return {"driver": "roe", "valor": r, "sin_raiz": r is None, "rango": list(rango),
            "sentido": None if r is not None else _sentido(f, rango[0])}


def resolver_roe_5_anios(precio: float, base_banco: dict, rango: tuple[float, float] = RANGO_ROE) -> dict:
    """ROE de los 5 años explícitos con ROE = Ke a partir del año 6: la convención terminal de los escenarios."""
    def f(roe: float) -> float:
        return valor_excess_return(base_banco["patrimonio0"], roe, base_banco["ke"], base_banco["payout"],
                                   base_banco["acciones"], base_banco.get("anios", 5),
                                   ke_estable=base_banco.get("ke_estable"), g_estable=base_banco.get("g_estable", 0.0)
                                   )["valor_por_accion"] - precio
    r = _raiz(f, *rango)
    return {"driver": "roe_5_anios_luego_ke", "valor": r, "sin_raiz": r is None, "rango": list(rango),
            "sentido": None if r is not None else _sentido(f, rango[0])}


def resolver(precio: float, base: dict, ruta: str, tasas_base: dict | None = None) -> dict:
    """Ejecuta los resolutores de la ruta. `tasas_base`: {driver: {media, desv}} para los percentiles."""
    exigir(precio > 0, "precio debe ser positivo")
    tasas_base = tasas_base or {}
    if ruta == "banco_credito":
        res = [resolver_roe(precio, base["banco"]), resolver_roe_5_anios(precio, base["banco"])]
    else:
        res = [resolver_crecimiento(precio, base), resolver_margen(precio, base), resolver_anios_ventaja(precio, base)]
    for r in res:
        tb = tasas_base.get("roe" if r["driver"] == "roe_5_anios_luego_ke" else r["driver"])
        r["percentil"] = percentil_normal(r["valor"], tb["media"], tb["desv"]) if tb else None
        if tb:
            r["z"] = None if r["valor"] is None else (r["valor"] - tb["media"]) / tb["desv"]
    principal = res[0]
    return {"precio": precio, "ruta": ruta, "principal": principal, "resultados": res,
            "sin_raiz": principal["sin_raiz"], "sentido": principal.get("sentido")}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="DCF inverso.")
    p.add_argument("entrada")
    a = p.parse_args(argv)
    e: dict[str, Any] = json.loads(Path(a.entrada).read_text(encoding="utf-8"))
    try:
        res = resolver(e["precio"], e["base"], e.get("ruta", "general"), e.get("tasas_base"))
    except (ErrorMotor, KeyError, TypeError) as err:
        print(json.dumps({"error": str(err)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

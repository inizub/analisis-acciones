"""Valoración de cíclicas con beneficio normalizado: margen operativo medio de 7-10 años × ingresos actuales,
y después un DCF de crecimiento estable (FCFF = NOPAT·(1 − g/ROC)) o el DCF de 10 años de dcf.py.

Uso CLI:
    python normalizado.py ENTRADA.json   (argumentos de valor_normalizado)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from motor.comun_motor import ErrorMotor, exigir, por_accion  # noqa: E402


def margen_normalizado(margenes: Sequence[float], min_anios: int = 7, max_anios: int = 10) -> dict:
    """Media de los últimos `max_anios` márgenes (exige al menos `min_anios`)."""
    m = [float(x) for x in margenes]
    exigir(len(m) >= min_anios, f"se necesitan al menos {min_anios} años de margen (hay {len(m)})")
    usados = m[-max_anios:]
    return {"margen": sum(usados) / len(usados), "anios": len(usados)}


def valor_normalizado(ingresos_actuales: float, margen: float, tasa_impuestos: float, wacc: float, g: float,
                      roc: float, deuda: float, caja: float, acciones: float, otros_activos: float = 0.0,
                      minoritarios: float = 0.0, crecer_primer_anio: bool = True) -> dict:
    """Empresa en crecimiento estable con EBIT normalizado.

    EBIT = ingresos × margen; NOPAT = EBIT·(1 − t); reinversión = g/ROC; FCFF₁ = NOPAT·(1+g)·(1 − g/ROC);
    valor operativo = FCFF₁/(WACC − g).
    """
    exigir(wacc > g, "WACC debe superar g")
    exigir(roc > 0, "ROC debe ser positivo")
    ebit = ingresos_actuales * margen
    nopat = ebit * (1 - tasa_impuestos)
    reinversion = g / roc
    base = nopat * (1 + g) if crecer_primer_anio else nopat
    fcff1 = base * (1 - reinversion)
    operativo = fcff1 / (wacc - g)
    patrimonio = operativo + caja + otros_activos - deuda - minoritarios
    return {
        "valor_por_accion": por_accion(patrimonio, acciones),
        "puente": {"ebit_normalizado": ebit, "nopat": nopat, "fcff_siguiente": fcff1, "valor_operativo": operativo,
                   "caja": caja, "otros_activos": otros_activos, "deuda": deuda, "minoritarios": minoritarios,
                   "valor_patrimonio": patrimonio, "acciones": acciones},
        "supuestos": {"margen_normalizado": margen, "tasa_impuestos": tasa_impuestos, "wacc": wacc, "g": g, "roc": roc,
                      "tasa_reinversion": reinversion},
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Valoración con margen normalizado (cíclicas).")
    p.add_argument("entrada")
    a = p.parse_args(argv)
    e = json.loads(Path(a.entrada).read_text(encoding="utf-8"))
    try:
        if "margenes" in e:
            e["margen"] = margen_normalizado(e.pop("margenes"))["margen"]
        res = valor_normalizado(**e)
    except (ErrorMotor, TypeError) as err:
        print(json.dumps({"error": str(err)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Modelos de contraste para bancos: DDM de dos etapas con g = (1 − payout)·ROE, y FCFE bancario
(beneficio neto − Δ activos ponderados por riesgo × ratio de capital objetivo).

Uso CLI:
    python ddm_fcfe.py ddm ENTRADA.json
    python ddm_fcfe.py fcfe ENTRADA.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from motor.comun_motor import ErrorMotor, exigir  # noqa: E402


def crecimiento_fundamental(payout: float, roe: float) -> float:
    return (1 - payout) * roe


def ddm_dos_etapas(bpa0: float, payout: float, ke: float, anios: int, g_estable: float, ke_estable: float,
                   roe: float | None = None, g: float | None = None, roe_estable: float | None = None,
                   payout_estable: float | None = None, valor_terminal: float | None = None) -> dict:
    """DDM: dividendos crecientes a g durante `anios` y valor terminal BPA_{n+1}·payout_estable/(Ke_estable − g_estable).

    g por defecto = (1 − payout)·ROE. payout_estable por defecto = 1 − g_estable/ROE_estable.
    `valor_terminal` permite fijar el valor terminal de una fuente (solo para contrastes).
    """
    exigir(bpa0 > 0, "bpa0 debe ser positivo")
    if g is None:
        exigir(roe is not None, "falta g o roe")
        g = crecimiento_fundamental(payout, roe)
    if payout_estable is None:
        exigir(roe_estable is not None and roe_estable > 0, "falta payout_estable o roe_estable")
        payout_estable = 1 - g_estable / roe_estable
    exigir(ke_estable > g_estable, "Ke estable debe superar g estable")
    filas, vp, bpa = [], 0.0, bpa0
    for t in range(1, anios + 1):
        bpa *= 1 + g
        dpa = bpa * payout
        f = (1 + ke) ** t
        filas.append({"anio": t, "bpa": bpa, "dpa": dpa, "vp": dpa / f})
        vp += dpa / f
    bpa_sig = bpa * (1 + g_estable)
    vt_calc = bpa_sig * payout_estable / (ke_estable - g_estable)
    vt = vt_calc if valor_terminal is None else valor_terminal
    vp_vt = vt / (1 + ke) ** anios
    return {
        "valor_por_accion": vp + vp_vt,
        "puente": {"vp_dividendos": vp, "valor_terminal": vt, "vp_valor_terminal": vp_vt},
        "supuestos": {"g": g, "payout": payout, "ke": ke, "g_estable": g_estable, "ke_estable": ke_estable,
                      "payout_estable": payout_estable, "bpa_siguiente": bpa_sig,
                      "valor_terminal_calculado": vt_calc, "valor_terminal_fijado": valor_terminal is not None},
        "flujos": filas,
    }


def fcfe_banco(beneficio_neto: Sequence[float], apr: Sequence[float], ratio_capital: float, apr0: float,
               ke: float, g_estable: float, acciones: float) -> dict:
    """FCFE_t = BN_t − (APR_t − APR_{t−1})·ratio_capital. Valor terminal = FCFE_{n}·(1+g)/(Ke − g)."""
    exigir(len(beneficio_neto) == len(apr) and len(apr) > 0, "beneficio_neto y apr deben tener la misma longitud")
    exigir(ke > g_estable, "Ke debe superar g estable")
    filas, vp, previo = [], 0.0, apr0
    for t, (bn, a) in enumerate(zip(beneficio_neto, apr), start=1):
        fcfe = bn - (a - previo) * ratio_capital
        filas.append({"anio": t, "beneficio_neto": bn, "apr": a, "inversion_capital": (a - previo) * ratio_capital,
                      "fcfe": fcfe, "vp": fcfe / (1 + ke) ** t})
        vp += fcfe / (1 + ke) ** t
        previo = a
    n = len(filas)
    vt = filas[-1]["fcfe"] * (1 + g_estable) / (ke - g_estable)
    vp_vt = vt / (1 + ke) ** n
    total = vp + vp_vt
    exigir(acciones > 0, "acciones debe ser positivo")
    return {"valor_por_accion": total / acciones,
            "puente": {"vp_fcfe": vp, "vp_valor_terminal": vp_vt, "valor_patrimonio": total, "acciones": acciones},
            "supuestos": {"ratio_capital": ratio_capital, "ke": ke, "g_estable": g_estable}, "flujos": filas}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="DDM y FCFE para bancos.")
    p.add_argument("modelo", choices=["ddm", "fcfe"])
    p.add_argument("entrada")
    a = p.parse_args(argv)
    e = json.loads(Path(a.entrada).read_text(encoding="utf-8"))
    try:
        res = ddm_dos_etapas(**e) if a.modelo == "ddm" else fcfe_banco(**e)
    except (ErrorMotor, TypeError) as err:
        print(json.dumps({"error": str(err)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

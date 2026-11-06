"""Excess return (bancos): valor del patrimonio = patrimonio actual + VP de (ROE − Ke)·patrimonio inicial de cada año
durante un periodo explícito + VP del valor terminal de los excesos. Incluye P/BV teórico = (ROE − g)/(Ke − g).

Uso CLI:
    python excess_return.py ENTRADA.json   (argumentos de valor_excess_return)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from motor.comun_motor import ErrorMotor, exigir, por_accion, serie_anual  # noqa: E402


def pbv_teorico(roe: float, ke: float, g: float) -> float:
    exigir(ke > g, "Ke debe superar g")
    return (roe - g) / (ke - g)


def valor_excess_return(patrimonio0: float, roe: float | Sequence[float], ke: float | Sequence[float],
                        payout: float | Sequence[float], acciones: float, anios: int = 5,
                        roe_estable: float | None = None, ke_estable: float | None = None,
                        g_estable: float = 0.0) -> dict:
    """Modelo de dos etapas. Por defecto, tras el periodo explícito ROE = Ke (sin valor añadido)."""
    exigir(patrimonio0 > 0, "patrimonio0 debe ser positivo")
    roes = serie_anual(roe, anios, "roe")
    kes = serie_anual(ke, anios, "ke")
    pay = serie_anual(payout, anios, "payout")
    filas, bv, acum, vp = [], patrimonio0, 1.0, 0.0
    for t in range(anios):
        bn = roes[t] * bv
        coste = kes[t] * bv
        exceso = bn - coste
        acum *= 1 + kes[t]
        filas.append({"anio": t + 1, "patrimonio_inicial": bv, "roe": roes[t], "ke": kes[t], "beneficio_neto": bn,
                      "coste_patrimonio": coste, "exceso": exceso, "vp": exceso / acum, "dividendos": bn * pay[t]})
        vp += exceso / acum
        bv = bv + bn * (1 - pay[t])
    ke_st = kes[-1] if ke_estable is None else ke_estable
    roe_st = ke_st if roe_estable is None else roe_estable
    exigir(ke_st > g_estable, "Ke estable debe superar g estable")
    exceso_term = (roe_st - ke_st) * bv
    vt = exceso_term / (ke_st - g_estable)
    vp_vt = vt / acum
    valor = patrimonio0 + vp + vp_vt
    return {
        "valor_por_accion": por_accion(valor, acciones),
        "puente": {"patrimonio_actual": patrimonio0, "vp_excesos": vp, "vp_valor_terminal": vp_vt,
                   "valor_patrimonio": valor, "acciones": acciones},
        "supuestos": {"roe_estable": roe_st, "ke_estable": ke_st, "g_estable": g_estable, "anios": anios,
                      "patrimonio_final": bv,
                      "pbv_teorico_estable": pbv_teorico(roe_st, ke_st, g_estable) if ke_st > g_estable else None},
        "flujos": filas,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Valoración por excess return (bancos).")
    p.add_argument("entrada")
    a = p.parse_args(argv)
    try:
        res = valor_excess_return(**json.loads(Path(a.entrada).read_text(encoding="utf-8")))
    except (ErrorMotor, TypeError) as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

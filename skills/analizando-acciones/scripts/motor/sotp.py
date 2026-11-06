"""Suma de partes (holdings): valor por segmento (múltiplo × métrica, o valor dado por un DCF del segmento)
menos deuda neta y el VP de los costes del holding.

Uso CLI:
    python sotp.py ENTRADA.json   (argumentos de valor_sotp)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from motor.comun_motor import ErrorMotor, exigir, por_accion  # noqa: E402


def valor_sotp(segmentos: Sequence[dict], deuda: float, caja: float, coste_holding_anual: float,
               tasa_descuento: float, acciones: float, g_costes: float = 0.0, minoritarios: float = 0.0) -> dict:
    """Segmento: {nombre, metodo: 'multiplo'|'valor', metrica?, multiplo?, valor?, participacion? (0-1)}.
    VP de costes del holding como perpetuidad: coste·(1+g)/(tasa − g)."""
    exigir(len(segmentos) > 0, "sin segmentos")
    exigir(tasa_descuento > g_costes, "tasa de descuento debe superar g_costes")
    detalle, suma = [], 0.0
    for s in segmentos:
        if s["metodo"] == "multiplo":
            v = s["metrica"] * s["multiplo"]
        elif s["metodo"] == "valor":
            v = s["valor"]
        else:
            raise ErrorMotor(f"método de segmento desconocido: {s['metodo']}")
        v *= s.get("participacion", 1.0)
        detalle.append({"nombre": s["nombre"], "metodo": s["metodo"], "valor": v})
        suma += v
    vp_costes = coste_holding_anual * (1 + g_costes) / (tasa_descuento - g_costes)
    patrimonio = suma + caja - deuda - minoritarios - vp_costes
    return {"valor_por_accion": por_accion(patrimonio, acciones),
            "puente": {"suma_segmentos": suma, "caja": caja, "deuda": deuda, "minoritarios": minoritarios,
                       "vp_costes_holding": vp_costes, "valor_patrimonio": patrimonio, "acciones": acciones},
            "supuestos": {"tasa_descuento": tasa_descuento, "g_costes": g_costes}, "segmentos": detalle}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Suma de partes.")
    p.add_argument("entrada")
    a = p.parse_args(argv)
    try:
        res = valor_sotp(**json.loads(Path(a.entrada).read_text(encoding="utf-8")))
    except (ErrorMotor, TypeError, KeyError) as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

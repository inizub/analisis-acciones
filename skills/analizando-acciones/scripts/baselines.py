"""Baselines contra los que se mide cada predicción (A6.8).

  B0  la tasa base (0,45)
  B1  un analista neutral sin red team ni juez: su p_final(E1) lo calcula agregar.py con --analistas B1
  B2  momentum 12-1 frente a VWCE: 0,55 si es superior, 0,40 si es inferior
  B3  valor: EV/EBIT (o P/BV÷ROE en bancos) frente al promedio sectorial de Damodaran:
      0,55 si es barato, 0,45 si es medio, 0,40 si es caro
Los baselines son probabilidades del evento "batir a VWCE" (E0, E1, E2). Para E4 solo hay B0 (config baselines.b0_e4)
y B1.

B3 desvía de la spec: Damodaran solo publica el promedio sectorial, no terciles, así que "barato" es una razón
≤ 0,8 frente a ese promedio y "caro" una razón ≥ 1,2 (config baselines.razon_barato / razon_caro).

Uso CLI:
    python baselines.py --datapack datapack.json (--ruta RUTA | --router router.json) [--b1 agregado_B1.json]
        [--salida baselines.json]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import comun  # noqa: E402


def _valor(x: Any) -> float | None:
    if not x or comun.es_desconocido(x):
        return None
    if "serie" in x:
        return x["serie"][-1]["valor"] if x["serie"] else None
    return x.get("valor")


def b0(cfg: dict) -> float:
    return cfg["agregacion"]["tasa_base_exceso"]


def b2(dp: dict, cfg: dict) -> tuple[float | None, str]:
    p = dp.get("precios")
    if not p or comun.es_desconocido(p):
        return None, "sin datos de precios"
    m = _valor(p["metricas_eur"].get("momentum_12_1_rel"))
    if m is None:
        return None, "sin momentum 12-1 relativo (historia insuficiente)"
    b = cfg["baselines"]["b2"]
    return (b["superior"] if m > 0 else b["inferior"]), f"momentum 12-1 relativo {m:+.1%}"


def _sector(dp: dict, clave: str) -> float | None:
    d = dp.get("damodaran")
    if not d or comun.es_desconocido(d):
        return None
    return _valor(d["sector"]["valores"].get(clave))


def _capitalizacion_comparable(dp: dict) -> float | None:
    """Capitalización en la moneda del informe; None si la acción cotiza en otra moneda."""
    p, e = dp.get("precios"), dp.get("empresa")
    if not p or comun.es_desconocido(p) or not e or comun.es_desconocido(e):
        return None
    cap = _valor(p.get("capitalizacion"))
    if cap is None or p.get("moneda") != e.get("moneda_informe"):
        return None
    return cap


def _clasificar(razon: float, cfg: dict) -> float:
    b = cfg["baselines"]
    if razon <= b["razon_barato"]:
        return b["b3"]["barato"]
    if razon >= b["razon_caro"]:
        return b["b3"]["caro"]
    return b["b3"]["medio"]


def b3(dp: dict, ruta: str, cfg: dict) -> tuple[float | None, str]:
    cap = _capitalizacion_comparable(dp)
    if cap is None:
        return None, "sin capitalización comparable con la moneda del informe"
    f = dp.get("fundamentales") or {}
    if ruta == "banco_credito":
        pat, bn = _valor(f.get("patrimonio")), _valor(f.get("beneficio_neto"))
        pbv_s, roe_s = _sector(dp, "pbv.pbv"), _sector(dp, "pbv.roe")
        if not pat or pat <= 0 or bn is None or bn <= 0 or not pbv_s or not roe_s or roe_s <= 0:
            return None, "faltan patrimonio, beneficio neto o los datos sectoriales de P/BV y ROE"
        razon = (cap / pat / (bn / pat)) / (pbv_s / roe_s)
        return _clasificar(razon, cfg), f"(P/BV÷ROE) / sector = {razon:.2f}"
    ebit, deuda, caja = _valor(f.get("beneficio_operativo")), _valor(f.get("deuda_total")), _valor(f.get("caja"))
    ev_ebit_s = _sector(dp, "ev_ebitda.ev_ebit")
    if ebit is None or ebit <= 0 or deuda is None or caja is None or not ev_ebit_s:
        return None, "EBIT no positivo o faltan deuda, caja o el EV/EBIT sectorial"
    razon = ((cap + deuda - caja) / ebit) / ev_ebit_s
    return _clasificar(razon, cfg), f"EV/EBIT / sector = {razon:.2f}"


def calcular(dp: dict, ruta: str, b1: float | None = None, cfg: dict | None = None,
             b1_e4: float | None = None) -> dict:
    """`b1` y `b1_e4` son p_final(E1) y p_final(E4) del analista neutral sin red team ni juez."""
    cfg = cfg or comun.cargar_config()
    v2, n2 = b2(dp, cfg)
    v3, n3 = b3(dp, ruta, cfg)
    return {"B0": b0(cfg), "B1": b1, "B1_E4": b1_e4, "B2": v2, "B3": v3, "B0_E4": cfg["baselines"]["b0_e4"],
            "detalle": {"B2": n2, "B3": n3, "B1": "no calculado" if b1 is None else "p_final del analista neutral"}}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Baselines B0-B3.")
    p.add_argument("--datapack", required=True)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--ruta")
    g.add_argument("--router")
    p.add_argument("--b1", help="agregado_B1.json (salida de agregar.py --analistas B1)")
    p.add_argument("--salida")
    a = p.parse_args(argv)
    try:
        ruta = a.ruta or comun.leer_json(a.router)["ruta"]
        b1 = comun.leer_json(a.b1)["p_final"] if a.b1 else {}
        res = calcular(comun.leer_json(a.datapack), ruta, b1.get("E1"), b1_e4=b1.get("E4"))
    except (FileNotFoundError, KeyError) as e:
        comun.salir_con_error(f"{type(e).__name__}: {e}")
    if a.salida:
        comun.escribir_json(a.salida, res)
        print(a.salida)
    else:
        print(comun.volcar_json(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())

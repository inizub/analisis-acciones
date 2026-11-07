"""Convierte los escenarios de un analista en valores, distribuciones y probabilidades de E0-E4.

Pasos:
  1. Valor V_i por escenario con el método de la ruta (drivers del analista sobre la base de motor_inicial).
  2. Precio esperado a h años: P_h,i = P0·(V_i/P0)^(h/T_conv), más el rendimiento al accionista (dividendos + recompras).
  3. Rentabilidad esperada de VWCE = Rf EUR + ERP.
  4. Monte Carlo (semilla fija): se elige un escenario según p_i y se añade ruido t de Student (ν = 4, escalado a
     varianza 1) con σ = volatilidad relativa histórica frente a VWCE en EUR, por √h.
     E3 (caída ≥ 30 % en 12 meses) se simula con 12 pasos mensuales y la volatilidad absoluta de la acción.

Uso CLI:
    python escenarios.py --analista analista_A.json --motor motor_inicial.json [--ajustes ajustes.json] [--salida f.json]

motor_inicial.json → clave "base":
  comunes: ruta, precio0, acciones, rendimiento_accionista, vol_rel, vol_abs, rf_eur, erp_vwce
  general / crecimiento_perdidas / ciclica: ingresos0, tasa_impuestos, wacc, rf, g_terminal, deuda, caja,
      ventas_capital, margen_operativo (base), crecimiento (base), [margen_inicial, anios_convergencia_margen,
      moat_documentado, roic_terminal, otros_activos, minoritarios]; ciclica además roc
  banco_credito: banco {patrimonio0, ke, payout, acciones, anios, g_estable, ke_estable?}
  biotech_precomercial: rnpv {activos, tabla, tasa, caja_neta, gastos_generales_anuales, anios_gastos, acciones}
  holding: sotp {segmentos, deuda, caja, coste_holding_anual, tasa_descuento, acciones}
Drivers por ruta (analista.escenarios[i].drivers.<nombre>.valor):
  general: crecimiento_ingresos, margen_operativo, [ventas_capital, roic_terminal (solo con moat documentado)]
  crecimiento_perdidas: los de general + [probabilidad_fracaso, valor_fracaso_por_accion]
  ciclica: margen_operativo (normalizado), [crecimiento_estable] o [crecimiento_ingresos] (DCF de 10 años con
      convergencia del margen; si lo da, crecimiento_estable no se usa)
  banco_credito: roe, [payout, roe_estable]
  biotech_precomercial: [factor_ventas_pico, factor_probabilidad]
  holding: [factor_multiplos]
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import comun  # noqa: E402
from motor.comun_motor import ErrorMotor, crecimiento_con_desvanecimiento, exigir  # noqa: E402
from motor.dcf import dcf_fcff  # noqa: E402
from motor.excess_return import valor_excess_return  # noqa: E402
from motor.normalizado import valor_normalizado  # noqa: E402
from motor.reverse_dcf import CLAVES_DCF  # noqa: E402
from motor.rnpv import valor_rnpv  # noqa: E402
from motor.sotp import valor_sotp  # noqa: E402

METODO_POR_RUTA = {"general": "dcf_fcff", "crecimiento_perdidas": "dcf_ingresos", "ciclica": "dcf_normalizado",
                   "banco_credito": "excess_return", "biotech_precomercial": "rnpv", "holding": "sotp"}
HORIZONTES = {"E0": 0.5, "E1": 1.0, "E2": 3.0}
PASOS_E3 = 12


def _v(drivers: dict, nombre: str, defecto: Any = None) -> Any:
    d = drivers.get(nombre)
    if d is None:
        exigir(defecto is not None, f"falta el driver obligatorio '{nombre}'")
        return defecto
    return d["valor"] if isinstance(d, dict) else d


def valorar(ruta: str, base: dict, drivers: dict) -> dict:
    """Valor por acción de un escenario. Devuelve {valor, metodo, drivers_usados, detalle}."""
    exigir(ruta in METODO_POR_RUTA, f"ruta sin método de valoración: {ruta}")
    usados: dict[str, Any] = {}
    if ruta in ("general", "crecimiento_perdidas"):
        args = {k: v for k, v in base.items() if k in CLAVES_DCF}
        g = _v(drivers, "crecimiento_ingresos", base.get("crecimiento"))
        if isinstance(g, (int, float)):
            g = crecimiento_con_desvanecimiento(g, base["g_terminal"])
        args["ventas_capital"] = _v(drivers, "ventas_capital", base["ventas_capital"])
        m = _v(drivers, "margen_operativo", base.get("margen_operativo"))
        roic_t = drivers.get("roic_terminal")
        if roic_t is not None:
            if base.get("moat_documentado"):
                args.update(moat_documentado=True, roic_terminal=_v(drivers, "roic_terminal"))
                usados["roic_terminal"] = args["roic_terminal"]
            else:
                usados["roic_terminal"] = "ignorado: el analista no documenta un moat con evidencia"
        r = dcf_fcff(crecimiento=g, margen_operativo=m, **args)
        valor = r["valor_por_accion"]
        usados.update(crecimiento_ingresos=g, margen_operativo=m, ventas_capital=args["ventas_capital"])
        if ruta == "crecimiento_perdidas" and "probabilidad_fracaso" in drivers:
            pf = _v(drivers, "probabilidad_fracaso")
            vf = _v(drivers, "valor_fracaso_por_accion", 0.0)
            exigir(0 <= pf <= 1, "probabilidad_fracaso fuera de [0, 1]")
            valor = (1 - pf) * valor + pf * vf
            usados.update(probabilidad_fracaso=pf, valor_fracaso_por_accion=vf)
    elif ruta == "ciclica" and "crecimiento_ingresos" in drivers:
        # Cíclica que crece mucho: DCF de 10 años; el margen converge del actual al normalizado del analista.
        args = {k: v for k, v in base.items() if k in CLAVES_DCF}
        g = _v(drivers, "crecimiento_ingresos")
        if isinstance(g, (int, float)):
            g = crecimiento_con_desvanecimiento(g, base["g_terminal"])
        m = _v(drivers, "margen_operativo", base.get("margen_operativo"))
        args["ventas_capital"] = base["ventas_capital"]
        r = dcf_fcff(crecimiento=g, margen_operativo=m, **args)
        valor = r["valor_por_accion"]
        usados.update(crecimiento_ingresos=g, margen_operativo=m, ventas_capital=args["ventas_capital"],
                      nota="dcf de 10 años con convergencia del margen (la ruta cíclica recibió crecimiento_ingresos)")
    elif ruta == "ciclica":
        m = _v(drivers, "margen_operativo", base.get("margen_operativo"))
        g = _v(drivers, "crecimiento_estable", base["g_terminal"])
        exigir(g <= base["rf"] + 1e-12, "crecimiento_estable no puede superar Rf")
        r = valor_normalizado(base["ingresos0"], m, base["tasa_impuestos"], base["wacc"], g, base["roc"],
                              base["deuda"], base["caja"], base["acciones"], base.get("otros_activos", 0.0),
                              base.get("minoritarios", 0.0))
        valor = r["valor_por_accion"]
        usados.update(margen_operativo=m, crecimiento_estable=g)
    elif ruta == "banco_credito":
        b = base["banco"]
        roe = _v(drivers, "roe")
        payout = _v(drivers, "payout", b["payout"])
        ke_st = b.get("ke_estable") or b["ke"]
        roe_st = ke_st
        if "roe_estable" in drivers:
            if base.get("moat_documentado"):
                roe_st = _v(drivers, "roe_estable")
            else:
                usados["roe_estable_propuesto"] = "ignorado: el analista no documenta un moat con evidencia"
        r = valor_excess_return(b["patrimonio0"], roe, b["ke"], payout, b["acciones"], b.get("anios", 5),
                                roe_estable=roe_st, ke_estable=b.get("ke_estable"), g_estable=b.get("g_estable", 0.0))
        valor = r["valor_por_accion"]
        usados.update(roe=roe, payout=payout, roe_estable=roe_st)
    elif ruta == "biotech_precomercial":
        e = copy.deepcopy(base["rnpv"])
        fv = _v(drivers, "factor_ventas_pico", 1.0)
        fp = _v(drivers, "factor_probabilidad", 1.0)
        for a in e["activos"]:
            a["ventas_pico"] *= fv
        e["tabla"] = [{**f, "p": min(1.0, f["p"] * fp ** 0.25)} for f in e["tabla"]]  # 4 transiciones → factor total fp
        r = valor_rnpv(**e)
        valor = r["valor_por_accion"]
        usados.update(factor_ventas_pico=fv, factor_probabilidad=fp)
    else:  # holding
        e = copy.deepcopy(base["sotp"])
        f = _v(drivers, "factor_multiplos", 1.0)
        for s in e["segmentos"]:
            if s["metodo"] == "multiplo":
                s["multiplo"] *= f
        r = valor_sotp(**e)
        valor = r["valor_por_accion"]
        usados.update(factor_multiplos=f)
    return {"valor": valor, "metodo": METODO_POR_RUTA[ruta], "drivers_usados": usados, "puente": r.get("puente")}


def moat_documentado(analista: dict) -> bool:
    """Moat con fuente identificada y al menos una evidencia con dato_ref: habilita un ROIC terminal mayor que el WACC."""
    m = analista.get("moat") or {}
    return m.get("fuente", "ninguna") != "ninguna" and m.get("amplitud", "ninguno") != "ninguno" and         any(e.get("dato_ref") for e in m.get("evidencia", []))


def aplicar_ajustes(analista: dict, ajustes: dict | None) -> tuple[dict, list[dict]]:
    """Aplica a una copia del analista los ajustes que le corresponden (por encuadre y escenario)."""
    a = copy.deepcopy(analista)
    aplicados = []
    for aj in (ajustes or {}).get("ajustes", []):
        if aj["analista"] not in (a["encuadre"], "todos") or aj["driver"] in AJUSTES_BASE:
            continue
        for esc in a["escenarios"]:
            if aj["escenario"] not in (esc["nombre"], "todos"):
                continue
            d = esc["drivers"].get(aj["driver"])
            exigir(d is not None, f"ajuste {aj['objecion_ref']}: driver '{aj['driver']}' no existe en {esc['nombre']}")
            if aj["valor_anterior"] is not None:
                exigir(d["valor"] == aj["valor_anterior"],
                       f"ajuste {aj['objecion_ref']}: valor_anterior {aj['valor_anterior']} ≠ {d['valor']} "
                       f"({esc['nombre']}.{aj['driver']})")
            aplicados.append({"escenario": esc["nombre"], "driver": aj["driver"], "de": d["valor"],
                              "a": aj["valor_nuevo"], "objecion_ref": aj["objecion_ref"]})
            d["valor"] = aj["valor_nuevo"]
    return a, aplicados


AJUSTES_BASE = ("ingresos0", "tasa_impuestos")   # inputs de la base (no de un escenario) que el juez puede corregir


def aplicar_ajustes_base(base: dict, ajustes: dict | None, encuadre: str) -> tuple[dict, list[dict]]:
    """Copia de `base` con los ajustes de inputs de la base (p. ej. ingresos0). Valen para todos los escenarios."""
    b = dict(base)
    aplicados = []
    for aj in (ajustes or {}).get("ajustes", []):
        if aj["driver"] not in AJUSTES_BASE or aj["analista"] not in (encuadre, "todos"):
            continue
        exigir(aj["escenario"] == "todos", f"ajuste {aj['objecion_ref']}: '{aj['driver']}' es de la base y solo admite escenario 'todos'")
        actual = b.get(aj["driver"])
        exigir(actual is not None, f"ajuste {aj['objecion_ref']}: la base no tiene '{aj['driver']}'")
        if aj["valor_anterior"] is not None:
            exigir(math.isclose(actual, aj["valor_anterior"], rel_tol=1e-9),
                   f"ajuste {aj['objecion_ref']}: valor_anterior {aj['valor_anterior']} ≠ {actual} (base.{aj['driver']})")
        exigir(isinstance(aj["valor_nuevo"], (int, float)) and aj["valor_nuevo"] > 0,
               f"ajuste {aj['objecion_ref']}: el valor nuevo de '{aj['driver']}' debe ser un número positivo")
        if aj["driver"] == "tasa_impuestos":
            exigir(aj["valor_nuevo"] < 0.6, f"ajuste {aj['objecion_ref']}: tasa_impuestos debe ser una fracción menor que 0,6")
        if aj["driver"] == "ingresos0":
            exigir((b.get("base_ingresos") or {}).get("metodo") != "ttm",
                   f"ajuste {aj['objecion_ref']}: la base de ingresos ya son los últimos doce meses reportados "
                   f"(hasta {(b.get('base_ingresos') or {}).get('fecha_fin')}); no se sustituye por estimaciones ni guidance")
        aplicados.append({"escenario": "todos", "driver": aj["driver"], "de": actual, "a": aj["valor_nuevo"],
                          "objecion_ref": aj["objecion_ref"]})
        b[aj["driver"]] = aj["valor_nuevo"]
    return b, aplicados


def cordura(rel: np.ndarray, cfg: dict) -> dict:
    """¿Encaja el precio con el rango de valores de los escenarios? Fuera de factor× por encima o por debajo → no fiable."""
    f = cfg["cordura"]["factor_precio_fuera_de_rango"]
    mx, mn = float(np.max(rel)), float(np.min(rel))
    if mx * f < 1:
        motivo = (f"incluso el escenario más alto vale {mx:.2f} veces el precio (el precio es {1 / mx:.1f} veces ese valor; "
                  f"límite {f:g}): revisa la base de ingresos y los supuestos antes de fiarte de las probabilidades")
    elif mn > f:
        motivo = (f"incluso el escenario más bajo vale {mn:.2f} veces el precio (límite {f:g}): "
                  f"revisa la base de ingresos y los supuestos antes de fiarte de las probabilidades")
    else:
        motivo = ""
    return {"fiable": not motivo, "motivo": motivo, "valor_max_sobre_p0": mx, "valor_min_sobre_p0": mn,
            "factor": f}


def _ruido_t(rng: np.random.Generator, nu: float, size: Any) -> np.ndarray:
    """t de Student con varianza 1."""
    return rng.standard_t(nu, size=size) * math.sqrt((nu - 2) / nu)


def simular(valores_rel: np.ndarray, probs: np.ndarray, base: dict, cfg: dict) -> dict:
    """valores_rel: V_i/P0 por escenario. Devuelve probabilidades E0-E3, percentiles y parámetros."""
    esc = cfg["escenarios"]
    T, n, nu = esc["T_conv_anios"], esc["mc_sims"], esc["t_nu"]
    caida = cfg["eventos"]["E3_caida"]
    rng = np.random.default_rng(esc["semilla"])
    y = base.get("rendimiento_accionista", 0.0)
    r_vw = base["rf_eur"] + base["erp_vwce"]
    s_rel = base["vol_rel"]
    s_abs = base.get("vol_abs", s_rel)
    exigir(s_rel > 0 and s_abs > 0, "las volatilidades deben ser positivas")
    idx = rng.choice(len(probs), size=n, p=probs)
    log_v = np.log(valores_rel)[idx]
    res: dict[str, Any] = {}
    rel12 = None
    for ev, h in HORIZONTES.items():
        accion = (h / T) * log_v + h * math.log1p(y)
        bench = h * math.log1p(r_vw)
        ruido = _ruido_t(rng, nu, n) * s_rel * math.sqrt(h)
        rel = np.exp(accion + ruido) - math.exp(bench)
        res[ev] = float(np.mean(rel > 0))
        if ev == "E1":
            rel12 = rel
    # E3: trayectoria mensual del precio (sin dividendos) en 12 meses.
    deriva = (log_v / T) / PASOS_E3
    pasos = _ruido_t(rng, nu, (n, PASOS_E3)) * s_abs * math.sqrt(1 / PASOS_E3) + deriva[:, None]
    minimo = np.minimum.accumulate(np.cumsum(pasos, axis=1), axis=1)[:, -1]
    res["E3"] = float(np.mean(minimo <= math.log1p(caida)))
    p5, p50, p95 = (float(x) for x in np.percentile(rel12, [5, 50, 95]))
    return {"probabilidades": res, "rel_12m_p5_p50_p95": [p5, p50, p95],
            "parametros": {"mc_sims": n, "semilla": esc["semilla"], "t_nu": nu, "T_conv_anios": T, "vol_rel": s_rel,
                           "vol_abs": s_abs, "rentabilidad_vwce": r_vw, "rendimiento_accionista": y}}


def ejecutar(analista: dict, motor: dict, ajustes: dict | None = None, cfg: dict | None = None) -> dict:
    cfg = cfg or comun.cargar_config()
    base = motor["base"]
    ruta = analista["ruta"]
    exigir(ruta == base.get("ruta", ruta) or base.get("permitir_ruta_distinta", False),
           f"la ruta del analista ({ruta}) no coincide con la del motor ({base.get('ruta')})")
    a, aplicados = aplicar_ajustes(analista, ajustes)
    base, aplicados_base = aplicar_ajustes_base(base, ajustes, a["encuadre"])
    aplicados += aplicados_base
    p0 = base["precio0"]
    exigir(p0 > 0, "precio0 debe ser positivo")
    escenarios = []
    base = {**base, "moat_documentado": moat_documentado(a)}
    for e in a["escenarios"]:
        v = valorar(ruta, base, e["drivers"])
        escenarios.append({"nombre": e["nombre"], "p": e["p"], "valor": v["valor"], "valor_sobre_p0": v["valor"] / p0,
                           "metodo": v["metodo"], "drivers_usados": v["drivers_usados"],
                           "valor_metrica_e4": e["valor_metrica_e4"]})
    probs = np.array([e["p"] for e in escenarios], dtype=float)
    exigir(abs(probs.sum() - 1) < 1e-6, f"las probabilidades de los escenarios suman {probs.sum():.6f}")
    rel = np.array([e["valor_sobre_p0"] for e in escenarios])
    exigir(np.all(rel > 0), "un escenario tiene valor ≤ 0: el modelo no admite pérdida total; usa un valor positivo mínimo")
    sim = simular(rel, probs, base, cfg)
    T = cfg["escenarios"]["T_conv_anios"]
    y = base.get("rendimiento_accionista", 0.0)
    r_vw = base["rf_eur"] + base["erp_vwce"]
    esperada = float(np.sum(probs * (rel ** (1 / T) * (1 + y)))) - 1
    bajista = next(e for e in escenarios if e["nombre"] == "bajista")
    umbral_e4 = a["metrica_e4"]["valor_base"]
    p_e4 = sum(e["p"] for e in escenarios if e["valor_metrica_e4"] >= umbral_e4)
    probabilidades = {**sim["probabilidades"], "E4": float(p_e4)}
    return {
        "ticker": a["ticker"], "fecha_analisis": a["fecha_analisis"], "analista": a["encuadre"], "ruta": ruta,
        "metodo": METODO_POR_RUTA[ruta], "precio0": p0, "escenarios": escenarios, "probabilidades": probabilidades,
        "rel_12m_p5_p50_p95": sim["rel_12m_p5_p50_p95"], "cordura": cordura(rel, cfg),
        "exceso_anual_esperado_pp": 100 * (esperada - r_vw),
        "rentabilidad_anual_esperada": esperada,
        "perdida_escenario_bajista": max(0.0, 1 - bajista["valor_sobre_p0"]),
        "metrica_e4": a["metrica_e4"], "ajustes_aplicados": aplicados, "parametros": sim["parametros"],
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Escenarios del analista → probabilidades de E0-E4.")
    p.add_argument("--analista", required=True)
    p.add_argument("--motor", required=True)
    p.add_argument("--ajustes")
    p.add_argument("--salida")
    a = p.parse_args(argv)
    try:
        analista = comun.leer_json(a.analista)
        motor = comun.leer_json(a.motor)
        ajustes = comun.leer_json(a.ajustes) if a.ajustes else None
        res = ejecutar(analista, motor, ajustes)
    except (ErrorMotor, KeyError, FileNotFoundError, json.JSONDecodeError) as e:
        print(json.dumps({"error": f"{type(e).__name__}: {e}"}, ensure_ascii=False), file=sys.stderr)
        return 1
    if a.salida:
        comun.escribir_json(a.salida, res)
        print(a.salida)
    else:
        print(comun.volcar_json(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())

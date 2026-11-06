"""Construye motor_inicial.json: la base de valoración de la ruta, el caso mecánico y el DCF inverso.

Uso CLI:
    python inicial.py --dir RUN_DIR [--salida motor_inicial.json]

Lee de RUN_DIR: datapack.json (con la sección tasas_base insertada), router.json y macro_regime.json.
Escribe motor_inicial.json con:
  base           inputs que escenarios.py combina con los drivers de cada analista
  caso_mecanico  valor con drivers puramente estadísticos (tasas base encogidas), como referencia
  reverse_dcf    qué expectativas descuenta el precio (reverse_dcf.py)
  supuestos      WACC, coste de la deuda, conversión de moneda y avisos
Si falta algo imprescindible, escribe {"error": ...} y el checklist (punto 5) lo convierte en no_analizable.

Unidades: la valoración se hace en la moneda del informe y por acción ordinaria. El precio se convierte a esas
unidades con el tipo de cambio cruzado (vía EUR) y el ratio de ADR (acciones ordinarias por título cotizado).
Monedas de informe admitidas para la tasa sin riesgo: USD (DGS10) y EUR (curva AAA del BCE a 10 años).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Callable

from scipy.optimize import brentq

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import comun  # noqa: E402
from motor import escenarios, reverse_dcf  # noqa: E402
from motor.comun_motor import ErrorMotor, exigir  # noqa: E402
from motor.dcf import wacc as calcular_wacc  # noqa: E402
from motor.normalizado import margen_normalizado  # noqa: E402
from motor.rnpv import cargar_tabla_bio  # noqa: E402

RUTAS_DCF = ("general", "crecimiento_perdidas", "ciclica")


# ---------------------------------------------------------------- lectura del datapack

def _valor(x: Any) -> float | None:
    if not x or comun.es_desconocido(x):
        return None
    if "serie" in x:
        return x["serie"][-1]["valor"] if x["serie"] else None
    return x.get("valor")


def _serie(dp: dict, campo: str) -> list[dict]:
    v = (dp.get("fundamentales") or {}).get(campo)
    return [] if not v or comun.es_desconocido(v) else v["serie"]


def _ultimo(dp: dict, campo: str) -> float | None:
    s = _serie(dp, campo)
    return s[-1]["valor"] if s else None


def _requerido(dp: dict, campo: str) -> float:
    v = _ultimo(dp, campo)
    exigir(v is not None, f"falta {campo} en el datapack")
    return v


def _sector(dp: dict, clave: str) -> float | None:
    d = dp.get("damodaran")
    if not d or comun.es_desconocido(d):
        return None
    return _valor(d["sector"]["valores"].get(clave))


def _prima(dp: dict, clave: str) -> float | None:
    d = dp.get("damodaran")
    if not d or comun.es_desconocido(d) or comun.es_desconocido(d.get("prima_pais")):
        return None
    return _valor(d["prima_pais"].get(clave))


def _encogido(dp: dict, metrica: str) -> float | None:
    o = ((dp.get("tasas_base") or {}).get("observados") or {}).get(metrica) or {}
    return o.get("valor_encogido") if o.get("estado") == "ok" else None


def rf_de(moneda: str, macro: dict) -> float:
    clave = {"USD": "rf_usd", "EUR": "rf_eur"}.get(moneda)
    exigir(clave is not None, f"moneda de informe {moneda} no admitida (solo USD y EUR tienen tasa sin riesgo)")
    v = macro.get(clave)
    exigir(isinstance(v, dict) and v.get("valor") is not None, f"macro_regime.json sin {clave}")
    return v["valor"]


def precio_en_moneda_informe(dp: dict, fx_eur: Callable[[str], float]) -> tuple[float, dict]:
    """Precio por acción ordinaria en la moneda del informe y detalle de la conversión."""
    p = dp.get("precios")
    exigir(p and not comun.es_desconocido(p), "sin datos de precio")
    precio, m_cot = p["precio"]["valor"], p["moneda"]
    m_inf = (dp.get("empresa") or {}).get("moneda_informe") or m_cot
    ratio_adr = _valor((dp.get("empresa") or {}).get("ratio_adr")) or 1.0
    exigir(ratio_adr > 0, "ratio_adr debe ser positivo")
    if m_cot == m_inf:
        fx = 1.0
    else:
        # unidades por EUR de cada moneda: cotización/informe = fx_cot / fx_inf
        fx_cot = _valor(p.get("fx_eur")) if m_cot != "EUR" else 1.0
        fx_inf = fx_eur(m_inf) if m_inf != "EUR" else 1.0
        exigir(fx_cot and fx_inf, f"sin tipo de cambio {m_cot}/{m_inf}")
        fx = fx_cot / fx_inf
    return precio / ratio_adr / fx, {"precio_cotizado": precio, "moneda_cotizacion": m_cot, "moneda_informe": m_inf,
                                     "cotizacion_por_informe": fx, "ratio_adr": ratio_adr}


def _fx_eur_yfinance(moneda: str) -> float:
    from datos.precios import ClientePrecios, serie_desde_dict, ticker_fx

    c = ClientePrecios()
    return float(serie_desde_dict(c._historia(ticker_fx(moneda)), "cierre").iloc[-1])


# ---------------------------------------------------------------- piezas de la base

def tasa_impuestos(dp: dict, cfg: dict, avisos: list[str]) -> float:
    t = _prima(dp, "tasa_impuestos")
    if t is None:
        t = cfg["motor"]["tasa_impuestos_defecto"]
        avisos.append(f"Sin tipo impositivo del país en Damodaran: se usa {t:.0%}")
    return t


def coste_deuda(dp: dict, rf: float, crp: float, avisos: list[str]) -> dict:
    """Rating sintético por cobertura de intereses (tabla de Damodaran); si no hay datos, el coste sectorial."""
    ebit, interes = _ultimo(dp, "beneficio_operativo"), _ultimo(dp, "gasto_intereses")
    gi = (dp.get("fundamentales") or {}).get("gasto_intereses") or {}
    tabla = (dp.get("damodaran") or {}).get("tabla_ratings")
    tabla_ok = isinstance(tabla, dict) and tabla.get("filas")
    if ebit is not None and interes and not gi.get("desactualizada") and tabla_ok:
        return {"cobertura": ebit / abs(interes), "tabla_ratings": tabla["filas"]}
    kd = _sector(dp, "wacc.coste_deuda")
    if kd is not None:
        avisos.append("Coste de la deuda: promedio sectorial de Damodaran (sin cobertura de intereses o sin tabla de ratings)")
        return {"coste_deuda_antes_impuestos": kd + crp}
    if ebit is not None and ebit > 0 and not interes:
        avisos.append("Sin gasto por intereses ni coste sectorial: se usa rf + 1 pp")
        return {"coste_deuda_antes_impuestos": rf + 0.01 + crp}
    raise ErrorMotor("no se puede estimar el coste de la deuda")


def ventas_capital(dp: dict, cfg: dict, avisos: list[str]) -> float:
    ing, deuda, pat, caja = (_ultimo(dp, c) for c in ("ingresos", "deuda_total", "patrimonio", "caja"))
    lo, hi = cfg["motor"]["ventas_capital_rango"]
    if None not in (ing, deuda, pat, caja):
        capital = deuda + pat - caja
        if capital > 0 and lo <= ing / capital <= hi:
            return ing / capital
    s = _sector(dp, "capex.ventas_capital")
    exigir(s is not None and s > 0, "sin ratio ventas/capital propio ni sectorial")
    avisos.append(f"Ventas/capital propio fuera de rango o sin datos: se usa el sectorial ({s:.2f})")
    return s


def rendimiento_accionista(dp: dict, capitalizacion: float) -> float:
    pagos = sum(abs(_ultimo(dp, c) or 0.0) for c in ("dividendos", "recompras"))
    return min(max(pagos / capitalizacion, 0.0), 0.15) if capitalizacion > 0 else 0.0


def volatilidades(dp: dict) -> tuple[float, float]:
    m = dp["precios"]["metricas_eur"]
    rel = _valor(m.get("vol_rel_3a")) or _valor(m.get("vol_rel_1a"))
    ab = _valor(m.get("vol_3a")) or _valor(m.get("vol_1a"))
    exigir(rel is not None and rel > 0, "sin volatilidad relativa frente a VWCE")
    return rel, ab or rel


def margenes_historicos(dp: dict) -> list[float]:
    ing = {p["fecha_dato"]: p["valor"] for p in _serie(dp, "ingresos")}
    ebit = {p["fecha_dato"]: p["valor"] for p in _serie(dp, "beneficio_operativo")}
    return [ebit[f] / ing[f] for f in sorted(ing) if f in ebit and ing[f] > 0]


def roc_historico(dp: dict, t: float) -> float | None:
    """EBIT·(1−t) / (deuda + patrimonio − caja), media de los últimos 3 ejercicios con capital positivo."""
    campos = {c: {p["fecha_dato"]: p["valor"] for p in _serie(dp, c)}
              for c in ("beneficio_operativo", "deuda_total", "patrimonio", "caja")}
    fechas = sorted(set.intersection(*(set(v) for v in campos.values())))[-3:]
    rocs = []
    for f in fechas:
        capital = campos["deuda_total"][f] + campos["patrimonio"][f] - campos["caja"][f]
        if capital > 0:
            rocs.append(campos["beneficio_operativo"][f] * (1 - t) / capital)
    return sum(rocs) / len(rocs) if rocs else None


# ---------------------------------------------------------------- construcción

def construir(dp: dict, router: dict, macro: dict, cfg: dict | None = None,
              fx_eur: Callable[[str], float] | None = None) -> dict:
    cfg = cfg or comun.cargar_config()
    mc = cfg["motor"]
    ruta = router["ruta"]
    exigir(ruta != "fuera_de_alcance", "ruta fuera de alcance")
    avisos: list[str] = []
    p0, conversion = precio_en_moneda_informe(dp, fx_eur or _fx_eur_yfinance)
    moneda = conversion["moneda_informe"]
    rf = rf_de(moneda, macro)
    acciones = _requerido(dp, "acciones_diluidas") / 1.0
    cap = p0 * acciones
    erp = _valor((dp.get("damodaran") or {}).get("erp_madura"))
    exigir(erp is not None, "sin ERP de Damodaran")
    crp = _prima(dp, "crp")
    if crp is None:
        crp = 0.0
        avisos.append("Sin prima de riesgo país: se usa 0")
    t = tasa_impuestos(dp, cfg, avisos)
    g_term = min(rf, mc["g_terminal_max"])
    vol_rel, vol_abs = volatilidades(dp)
    comunes = {"ruta": ruta, "moneda": moneda, "precio0": p0, "acciones": acciones,
               "rendimiento_accionista": rendimiento_accionista(dp, cap), "vol_rel": vol_rel, "vol_abs": vol_abs,
               "rf_eur": rf_de("EUR", macro), "erp_vwce": erp}
    supuestos: dict[str, Any] = {"rf": rf, "erp": erp, "crp": crp, "tasa_impuestos": t, "g_terminal": g_term,
                                 "conversion_precio": conversion, "capitalizacion_moneda_informe": cap}
    tasas_rev = (dp.get("tasas_base") or {}).get("para_reverse_dcf") or {}

    if ruta == "banco_credito":
        base, mec = _base_banco(dp, comunes, rf, erp, crp, g_term, avisos)
        supuestos["ke"] = base["banco"]["ke"]
        rev = reverse_dcf.resolver(p0, base, ruta, tasas_rev)
    elif ruta in RUTAS_DCF:
        base, mec = _base_dcf(dp, comunes, cfg, rf, erp, crp, t, g_term, cap, supuestos, avisos)
        rev = reverse_dcf.resolver(p0, base, ruta, tasas_rev)
    elif ruta == "biotech_precomercial":
        base, mec = _base_biotech(dp, comunes, cfg, rf, erp, crp, avisos)
        rev = resolver_factor(p0, base, ruta, "factor_ventas_pico")
    elif ruta == "holding":
        base, mec = _base_holding(dp, comunes, cfg, rf, erp, crp, t, cap, avisos)
        rev = resolver_factor(p0, base, ruta, "factor_multiplos")
    else:
        raise ErrorMotor(f"ruta desconocida: {ruta}")

    valor = escenarios.valorar(ruta, base, mec)
    supuestos["avisos"] = avisos
    return {"ticker": dp["ticker"], "fecha_analisis": dp["fecha_analisis"], "ruta": ruta, "base": base,
            "caso_mecanico": {"drivers": mec, "valor": valor["valor"], "valor_sobre_precio": valor["valor"] / p0,
                              "metodo": valor["metodo"], "puente": valor["puente"]},
            "reverse_dcf": rev, "supuestos": supuestos}


def _base_dcf(dp, comunes, cfg, rf, erp, crp, t, g_term, cap, supuestos, avisos):
    mc = cfg["motor"]
    ing, ebit = _requerido(dp, "ingresos"), _requerido(dp, "beneficio_operativo")
    deuda, caja = _requerido(dp, "deuda_total"), _requerido(dp, "caja")
    beta_u = _sector(dp, "betas.beta_desapalancada_caja") or _sector(dp, "betas.beta_desapalancada")
    exigir(beta_u is not None, "sin beta desapalancada sectorial")
    kd = coste_deuda(dp, rf, crp, avisos)
    w = calcular_wacc(rf=rf, erp=erp, beta_desapalancada=beta_u, deuda_capital=deuda / cap if cap > 0 else 0.0,
                      tasa_impuestos=t, crp=crp, **kd)
    supuestos["wacc"] = w
    margen0 = ebit / ing
    margen_obj = _encogido(dp, "margen_operativo")
    if margen_obj is None:
        margen_obj = margen0
        avisos.append("Sin tasa base de margen: el caso mecánico mantiene el margen actual")
    crec = _encogido(dp, "crecimiento_ventas_5a")
    if crec is None:
        crec = _encogido(dp, "crecimiento_ventas_3a")
    if crec is None:
        crec = ((dp.get("tasas_base") or {}).get("para_reverse_dcf") or {}).get("crecimiento_ingresos", {}).get("media")
    exigir(crec is not None, "sin crecimiento de referencia para el caso mecánico")
    base = {**comunes, "ingresos0": ing, "tasa_impuestos": t, "wacc": w["wacc"], "rf": rf, "g_terminal": g_term,
            "deuda": deuda, "caja": caja, "ventas_capital": ventas_capital(dp, cfg, avisos),
            # El DCF inverso mantiene el margen actual: describe lo que descuenta el precio sin añadir la reversión
            # a la media del caso mecánico. El caso mecánico usa el margen encogido (mec más abajo).
            "margen_operativo": margen0, "margen_inicial": margen0,
            "anios_convergencia_margen": mc["anios_convergencia_margen"], "crecimiento": crec}
    if comunes["ruta"] == "ciclica":
        hist = margenes_historicos(dp)
        if len(hist) >= 7:
            base["margen_operativo"] = margen_normalizado(hist)["margen"]
        else:
            avisos.append(f"Solo {len(hist)} años de márgenes: el margen normalizado usa la tasa base")
        roc = roc_historico(dp, t)
        lo, hi = mc["roc_rango"]
        base["roc"] = min(max(roc if roc is not None else w["wacc"], lo), hi)
        mec = {"margen_operativo": {"valor": base["margen_operativo"]}}
    else:
        mec = {"crecimiento_ingresos": {"valor": crec}, "margen_operativo": {"valor": margen_obj}}
    return base, mec


def _base_banco(dp, comunes, rf, erp, crp, g_term, avisos):
    pat, bn = _requerido(dp, "patrimonio"), _requerido(dp, "beneficio_neto")
    exigir(pat > 0, "patrimonio no positivo")
    beta = _sector(dp, "betas.beta")
    exigir(beta is not None, "sin beta sectorial")
    ke = rf + beta * erp + crp
    pagos = sum(abs(_ultimo(dp, c) or 0.0) for c in ("dividendos", "recompras"))
    payout = min(max(pagos / bn, 0.0), 1.0) if bn > 0 else 0.0
    if _ultimo(dp, "dividendos") is None and _ultimo(dp, "recompras") is None:
        avisos.append("Sin dividendos ni recompras en EDGAR: payout 0 (todo el beneficio se retiene)")
    roe0 = bn / pat
    roe_mec = _encogido(dp, "roe")
    if roe_mec is None:
        roe_mec = roe0
        avisos.append("Sin tasa base de ROE: el caso mecánico usa el ROE actual")
    banco = {"patrimonio0": pat, "ke": ke, "payout": payout, "acciones": comunes["acciones"], "anios": 5,
             "g_estable": g_term}
    return {**comunes, "banco": banco, "roe0": roe0}, {"roe": {"valor": roe_mec}}


def _base_biotech(dp, comunes, cfg, rf, erp, crp, avisos):
    mc = cfg["motor"]["rnpv"]
    pipeline = dp.get("pipeline") or []
    activos = []
    for a in pipeline:
        vp = _valor(a.get("ventas_pico"))
        if vp is None or a.get("fase") not in mc["anios_hasta_lanzamiento"]:
            avisos.append(f"Activo {a.get('nombre')} sin ventas pico con fuente o con fase no reconocida: excluido")
            continue
        activos.append({"nombre": a["nombre"], "fase": a["fase"], "area": a.get("area") or "todas", "ventas_pico": vp,
                        "margen": mc["margen"], "anios_hasta_lanzamiento": mc["anios_hasta_lanzamiento"][a["fase"]],
                        "anios_rampa": mc["anios_rampa"], "anios_meseta": mc["anios_meseta"],
                        "anios_declive": mc["anios_declive"]})
    exigir(activos, "biotech sin activos de pipeline con fase y ventas pico con fuente")
    beta_u = _sector(dp, "betas.beta_desapalancada") or 1.0
    caja, deuda = _ultimo(dp, "caja") or 0.0, _ultimo(dp, "deuda_total") or 0.0
    quema = max(0.0, -(_ultimo(dp, "fco") or 0.0))
    avisos.append("rNPV: margen, plazos de lanzamiento y curva de ventas son parámetros de config.yaml (motor.rnpv)")
    rnpv = {"activos": activos, "tabla": cargar_tabla_bio(grupo="area"), "tasa": rf + beta_u * erp + crp,
            "caja_neta": caja - deuda, "gastos_generales_anuales": quema * mc["fraccion_quema_generales"],
            "anios_gastos": mc["anios_gastos_generales"], "acciones": comunes["acciones"], "tasa_impuestos": 0.0}
    return {**comunes, "rnpv": rnpv}, {"factor_ventas_pico": {"valor": 1.0}}


def _base_holding(dp, comunes, cfg, rf, erp, crp, t, cap, avisos):
    segs = []
    for s in dp.get("segmentos") or []:
        if s.get("tipo") != "negocio":
            continue
        ebit, mult = _valor(s.get("beneficio_operativo")), _valor(s.get("multiplo_ev_ebit"))
        if ebit is None or mult is None:
            avisos.append(f"Segmento {s.get('nombre')} sin beneficio operativo o múltiplo con fuente: excluido")
            continue
        segs.append({"nombre": s["nombre"], "metodo": "multiplo", "metrica": ebit, "multiplo": mult})
    exigir(len(segs) >= 2, "holding sin al menos 2 segmentos con beneficio operativo y múltiplo")
    coste = _valor(dp.get("holding_coste_anual"))
    if coste is None:
        coste = 0.0
        avisos.append("Sin coste anual del holding: se toma 0")
    beta_u = _sector(dp, "betas.beta_desapalancada") or 1.0
    deuda = _ultimo(dp, "deuda_total") or 0.0
    w = calcular_wacc(rf=rf, erp=erp, beta_desapalancada=beta_u, deuda_capital=deuda / cap if cap > 0 else 0.0,
                      tasa_impuestos=t, crp=crp, coste_deuda_antes_impuestos=rf + 0.015 + crp)
    sotp = {"segmentos": segs, "deuda": deuda, "caja": _ultimo(dp, "caja") or 0.0, "coste_holding_anual": coste,
            "tasa_descuento": w["wacc"], "acciones": comunes["acciones"]}
    return {**comunes, "sotp": sotp}, {"factor_multiplos": {"valor": 1.0}}


def resolver_factor(precio: float, base: dict, ruta: str, driver: str, rango: tuple[float, float] = (0.01, 20.0)) -> dict:
    """DCF inverso de rutas sin DCF: el factor del driver (ventas pico o múltiplos) que iguala el valor al precio."""
    def f(x: float) -> float:
        return escenarios.valorar(ruta, base, {driver: {"valor": x}})["valor"] - precio

    a, b = f(rango[0]), f(rango[1])
    raiz = None if a * b > 0 else float(brentq(f, *rango, xtol=1e-10))
    principal = {"driver": driver, "valor": raiz, "sin_raiz": raiz is None, "rango": list(rango), "percentil": None}
    return {"precio": precio, "ruta": ruta, "principal": principal, "resultados": [principal], "sin_raiz": raiz is None}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Base de valoración, caso mecánico y DCF inverso.")
    p.add_argument("--dir", required=True)
    p.add_argument("--salida")
    a = p.parse_args(argv)
    d = Path(a.dir)
    destino = Path(a.salida) if a.salida else d / "motor_inicial.json"
    try:
        dp = comun.leer_json(d / "datapack.json") if (d / "datapack.json").exists() else comun.leer_json(d / "datapack_base.json")
        res = construir(dp, comun.leer_json(d / "router.json"), comun.leer_json(d / "macro_regime.json"))
    except (ErrorMotor, comun.ErrorDatos, FileNotFoundError, KeyError) as e:
        comun.escribir_json(destino, {"error": f"{type(e).__name__}: {e}"})
        print(comun.volcar_json({"error": str(e), "salida": str(destino)}))
        return 1
    comun.escribir_json(destino, res)
    print(comun.volcar_json({"salida": str(destino), "valor_mecanico": res["caso_mecanico"]["valor"],
                             "precio": res["base"]["precio0"], "reverse_dcf": res["reverse_dcf"]["principal"],
                             "avisos": res["supuestos"]["avisos"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Backtest del caso mecánico (solo la parte determinista del motor, sin analistas).

Para cada acción y cada fecha de corte (31 de diciembre) reconstruye los fundamentales tal como estaban presentados en la
SEC ese día (filtra por fecha de presentación), calcula el valor del DCF mecánico (el mismo `dcf_fcff` del plugin, con
crecimiento y margen encogidos hacia la media como en `motor/inicial.py`) y lo compara con el precio de ese día. Luego mide
si el cociente valor/precio anticipó el retraso o la ventaja del siguiente año frente al S&P 500 (SPY).

Limitaciones deliberadas (se repiten en el informe): sin analistas (el juicio del LLM no se puede reconstruir sin ver el
futuro), sin Damodaran por sector (beta propia con ajuste de Blume), tasas base fijas (media y desviación de la clase de
tamaño >50.000 M$ de hoy), ERP fija y base de ingresos anual (sin TTM). Mide el motor, no el plugin entero.

Uso: python backtest.py --salida RUTA.json [--tickers A,B] [--fechas 2016,2017,...]
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import comun  # noqa: E402
from datos import edgar  # noqa: E402
from motor.comun_motor import crecimiento_con_desvanecimiento  # noqa: E402
from motor.dcf import dcf_fcff, wacc as calcular_wacc  # noqa: E402

UNIVERSO = ("AAPL MSFT GOOGL AMZN META NVDA TSLA NFLX ADBE CRM V MA JNJ PG KO PEP WMT COST HD MCD NKE DIS CMCSA T VZ "
            "PFE MRK ABBV BMY UNH CVS XOM CVX CAT DE HON GE INTC CSCO ORCL IBM QCOM TXN AMD MO PM LMT BA F GM").split()
FECHAS = list(range(2016, 2025))
ERP = 0.045
G_TERMINAL = 0.03
# Tasas base de la clase de tamaño >50.000 M$ (valores del datapack de las pruebas): media y peso de la empresa (k).
MEDIA_CREC, K_CREC = 0.0367, 0.3
MEDIA_MARGEN, K_MARGEN = 0.1054, 0.6


def encoger(valor: float, media: float, k: float) -> float:
    return media + k * (valor - media)


def facts_hasta(facts: dict, corte: str) -> dict:
    """Copia de companyfacts con solo los hechos presentados hasta la fecha de corte (incluida)."""
    f = copy.deepcopy(facts)
    for tax in f.get("facts", {}).values():
        for concepto in tax.values():
            for unidad, hs in concepto.get("units", {}).items():
                concepto["units"][unidad] = [h for h in hs if h.get("filed", "9999") <= corte]
    return f


def _serie(fund: dict, campo: str) -> list[dict]:
    v = fund.get(campo)
    return [] if v is None or comun.es_desconocido(v) else (v.get("serie") or [])


def _ultimo(fund: dict, campo: str, corte: pd.Timestamp, max_meses: int = 16) -> float | None:
    s = _serie(fund, campo)
    if not s:
        return None
    p = max(s, key=lambda x: x["fecha_dato"])
    if (corte - pd.Timestamp(p["fecha_dato"])).days > max_meses * 30.4:
        return None
    return p["valor"]


def cagr(fund: dict, campo: str, anios: int) -> float | None:
    s = sorted(_serie(fund, campo), key=lambda x: x["fecha_dato"])
    if len(s) <= anios or s[-1 - anios]["valor"] <= 0 or s[-1]["valor"] <= 0:
        return None
    return (s[-1]["valor"] / s[-1 - anios]["valor"]) ** (1 / anios) - 1


VARIANTES = {"actual": (0.3, 0.6), "menos_encogido": (0.5, 0.8), "casi_sin_encoger": (0.7, 0.9)}


def valor_mecanico(fund: dict, corte: pd.Timestamp, precio: float, beta_propia: float | None, rf: float,
                   cfg: dict, k_crec: float = K_CREC, k_margen: float = K_MARGEN) -> dict:
    ing, ebit = _ultimo(fund, "ingresos", corte), _ultimo(fund, "beneficio_operativo", corte)
    acc = _ultimo(fund, "acciones_diluidas", corte)
    deuda, caja, pat = _ultimo(fund, "deuda_total", corte), _ultimo(fund, "caja", corte), _ultimo(fund, "patrimonio", corte)
    if None in (ing, ebit, acc) or ing <= 0 or acc <= 0:
        return {"error": "faltan ingresos, beneficio operativo o acciones"}
    deuda, caja = deuda or 0.0, caja or 0.0
    g = cagr(fund, "ingresos", 5) if cagr(fund, "ingresos", 5) is not None else cagr(fund, "ingresos", 3)
    if g is None:
        return {"error": "sin historia de ingresos para el crecimiento"}
    g_enc = encoger(g, MEDIA_CREC, k_crec)
    m0 = ebit / ing
    m_obj = encoger(m0, MEDIA_MARGEN, k_margen)
    cap = precio * acc
    lo, hi = cfg["motor"]["ventas_capital_rango"]
    sc = None
    if pat is not None and deuda + pat - caja > 0 and lo <= ing / (deuda + pat - caja) <= hi:
        sc = ing / (deuda + pat - caja)
    if sc is None:
        sc = 1.5
    beta = min(max(0.67 * beta_propia + 0.33, 0.4), 2.5) if beta_propia is not None else 1.0
    t = 0.25
    w = calcular_wacc(rf=rf, erp=ERP, beta_desapalancada=beta / (1 + (1 - t) * (deuda / cap)), deuda_capital=deuda / cap,
                      tasa_impuestos=t, coste_deuda_antes_impuestos=rf + 0.015)["wacc"]
    gt = min(G_TERMINAL, rf)
    crec = crecimiento_con_desvanecimiento(g_enc, gt, 10, 5)
    v = dcf_fcff(ing, crec, m_obj, sc, t, w, gt, rf, deuda, caja, acc, margen_inicial=m0,
                 anios_convergencia_margen=cfg["motor"]["anios_convergencia_margen"])["valor_por_accion"]
    return {"valor": v, "wacc": w, "crecimiento": g_enc, "margen_obj": m_obj, "ventas_capital": sc, "beta": beta}


def _cierre(serie: pd.Series, fecha: pd.Timestamp) -> float | None:
    s = serie.loc[:fecha]
    return float(s.iloc[-1]) if len(s) and (fecha - s.index[-1]).days <= 7 else None


def beta_semanal(a: pd.Series, b: pd.Series, fecha: pd.Timestamp, anios: int = 3) -> float | None:
    df = pd.concat([a.loc[:fecha].resample("W-FRI").last().pct_change(),
                    b.loc[:fecha].resample("W-FRI").last().pct_change()], axis=1, join="inner").dropna()
    df = df.loc[df.index > fecha - pd.DateOffset(years=anios)]
    if len(df) < 100 or df.iloc[:, 1].var() <= 0:
        return None
    return float(df.iloc[:, 0].cov(df.iloc[:, 1]) / df.iloc[:, 1].var())


def historia(yf, ticker: str) -> pd.Series | None:
    h = yf.Ticker(ticker).history(period="max", auto_adjust=False, actions=False)
    if h is None or h.empty:
        return None
    s = h["Close"].copy()
    s.index = pd.to_datetime(s.index).tz_localize(None)
    return s.dropna()


def historia_ajustada(yf, ticker: str) -> pd.Series | None:
    h = yf.Ticker(ticker).history(period="max", auto_adjust=True, actions=False)
    if h is None or h.empty:
        return None
    s = h["Close"].copy()
    s.index = pd.to_datetime(s.index).tz_localize(None)
    return s.dropna()


def ejecutar(tickers: list[str], anios: list[int]) -> dict:
    import yfinance as yf

    cfg = comun.cargar_config()
    cliente = edgar.ClienteEdgar()
    spy, spy_aj = historia(yf, "SPY"), historia_ajustada(yf, "SPY")
    tnx = historia(yf, "^TNX")
    filas, fallos = [], {}
    for t in tickers:
        try:
            cik, _ = cliente.cik(t)
            facts, _ = cliente.companyfacts(cik)
            px, px_aj = historia(yf, t), historia_ajustada(yf, t)
            if px is None or px_aj is None:
                raise comun.ErrorDatos("sin precios", "not_covered")
        except Exception as e:  # noqa: BLE001
            fallos[t] = str(e)[:120]
            continue
        for a in anios:
            corte, fin = pd.Timestamp(f"{a}-12-31"), pd.Timestamp(f"{a + 1}-12-31")
            p0, p1, s0, s1 = _cierre(px_aj, corte), _cierre(px_aj, fin), _cierre(spy_aj, corte), _cierre(spy_aj, fin)
            fin3 = pd.Timestamp(f"{a + 3}-12-31")
            p3, s3 = _cierre(px_aj, fin3), _cierre(spy_aj, fin3)
            precio = _cierre(px, corte)
            rf = _cierre(tnx, corte)
            if None in (p0, p1, s0, s1, precio, rf):
                continue
            rf = rf / 100
            _, fund, _ = edgar.extraer_fundamentales(facts_hasta(facts, corte.strftime("%Y-%m-%d")), 10, "bt")
            res = valor_mecanico(fund, corte, precio, beta_semanal(px_aj, spy_aj, corte), rf, cfg)
            if "error" in res:
                fallos[f"{t}-{a}"] = res["error"]
                continue
            extra = {}
            for nombre, (kc, km) in VARIANTES.items():
                r2 = valor_mecanico(fund, corte, precio, beta_semanal(px_aj, spy_aj, corte), rf, cfg, kc, km)
                extra[f"vp_{nombre}"] = r2["valor"] / precio if "valor" in r2 else None
            filas.append({"ticker": t, "anio": a, "precio": precio, **res, **extra, "v_sobre_p": res["valor"] / precio,
                          "ret_12m": p1 / p0 - 1, "ret_spy_12m": s1 / s0 - 1, "ret_rel_12m": p1 / p0 - s1 / s0,
                          "ret_rel_36m_anual": (p3 / p0) ** (1 / 3) - (s3 / s0) ** (1 / 3) if p3 and s3 else None})
        print(t, "ok", flush=True)
    return {"filas": filas, "fallos": fallos}


def resumen(filas: list[dict]) -> dict:
    df = pd.DataFrame(filas)
    df["ln_vp"] = np.log(df["v_sobre_p"].clip(lower=1e-3))
    out = {"n": len(df), "mediana_v_sobre_p": float(df["v_sobre_p"].median()),
           "porc_v_mayor_p": float((df["v_sobre_p"] > 1).mean()),
           "rho_spearman_lnVP_vs_rel12m": float(df["ln_vp"].corr(df["ret_rel_12m"], method="spearman"))}
    df["quintil"] = pd.qcut(df["v_sobre_p"], 5, labels=False, duplicates="drop")
    q = df.groupby("quintil").agg(n=("ticker", "size"), v_sobre_p_med=("v_sobre_p", "median"),
                                  rel_media=("ret_rel_12m", "mean"), rel_mediana=("ret_rel_12m", "median"),
                                  bate_spy=("ret_rel_12m", lambda x: float((x > 0).mean())))
    out["quintiles"] = q.round(3).reset_index().to_dict("records")
    out["por_anio_rho"] = {int(a): round(float(g["ln_vp"].corr(g["ret_rel_12m"], method="spearman")), 3)
                           for a, g in df.groupby("anio") if len(g) >= 8}
    for lim in (0.5, 1.0):
        s = df[df["v_sobre_p"] >= lim]
        out[f"v_sobre_p>={lim}"] = {"n": len(s), "rel_media": round(float(s["ret_rel_12m"].mean()), 3) if len(s) else None,
                                    "bate_spy": round(float((s["ret_rel_12m"] > 0).mean()), 3) if len(s) else None}
    d3 = df.dropna(subset=["ret_rel_36m_anual"])
    d3 = d3[d3["v_sobre_p"] < 50]               # fuera casos degenerados (capital invertido casi nulo)
    out["horizonte_3a"] = {"n": len(d3), "rho_spearman": float(d3["ln_vp"].corr(d3["ret_rel_36m_anual"], method="spearman"))}
    d3 = d3.assign(quintil=pd.qcut(d3["v_sobre_p"], 5, labels=False, duplicates="drop"))
    out["horizonte_3a"]["quintiles"] = (d3.groupby("quintil").agg(
        v_sobre_p_med=("v_sobre_p", "median"), rel_anual_media=("ret_rel_36m_anual", "mean"),
        rel_anual_mediana=("ret_rel_36m_anual", "median"),
        bate_spy=("ret_rel_36m_anual", lambda x: float((x > 0).mean())))).round(3).reset_index().to_dict("records")
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Backtest del caso mecánico del motor.")
    p.add_argument("--salida", required=True)
    p.add_argument("--tickers", default=",".join(UNIVERSO))
    p.add_argument("--fechas", default=",".join(map(str, FECHAS)))
    a = p.parse_args(argv)
    r = ejecutar(a.tickers.split(","), [int(x) for x in a.fechas.split(",")])
    r["resumen"] = resumen(r["filas"]) if r["filas"] else None
    Path(a.salida).write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(r["resumen"], ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())

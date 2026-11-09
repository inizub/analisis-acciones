"""Pruebas de claude-ai/lentes.py (funciones puras, sin datos de red)."""
from __future__ import annotations

import importlib.util
import math
from pathlib import Path

RUTA = Path(__file__).resolve().parents[3] / "claude-ai" / "lentes.py"
spec = importlib.util.spec_from_file_location("lentes", RUTA)
lentes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lentes)

DCF = dict(ingresos0=100.0, g=0.10, margen0=0.20, margen_obj=0.25, vc=2.0, t=0.21, wacc=0.09,
           g_term=0.03, roic_term=0.12, deuda=0.0, caja=0.0, acciones=10.0)


def test_phi_simetria():
    assert abs(lentes.phi(0) - 0.5) < 1e-12
    assert abs(lentes.phi(1.3) + lentes.phi(-1.3) - 1) < 1e-12


def test_dcf_crece_con_el_crecimiento():
    bajo = lentes.dcf(**{**DCF, "g": 0.02})
    alto = lentes.dcf(**{**DCF, "g": 0.20})
    assert alto > bajo > 0


def test_dcf_sin_valor_si_wacc_no_supera_g_terminal():
    assert lentes.dcf(**{**DCF, "wacc": 0.03}) is None


def test_dcf_caja_y_deuda_ajustan_por_accion():
    base = lentes.dcf(**DCF)
    con_caja = lentes.dcf(**{**DCF, "caja": 50.0})
    assert math.isclose(con_caja - base, 5.0, rel_tol=1e-9)


def test_biseccion_encuentra_la_raiz():
    raiz, estado = lentes.biseccion(lambda x: x - 0.37, -0.2, 0.6)
    assert estado == "ok" and abs(raiz - 0.37) < 1e-6


def test_biseccion_distingue_caro_de_barato():
    # f(lo) > 0: ya con el valor más bajo del rango se supera el precio -> barato
    assert lentes.biseccion(lambda x: 1.0 + x, 0.0, 1.0) == (None, "barato")
    # f(hi) < 0: ni con el valor más alto se alcanza el precio -> caro
    assert lentes.biseccion(lambda x: -1.0 - x, 0.0, 1.0) == (None, "caro")


# ---------------------------------------------------------------- adaptador FMP
import json  # noqa: E402

INC = [{"date": "2026-10-02", "reportedCurrency": "USD", "revenue": 100, "grossProfit": 60, "operatingIncome": 30,
        "netIncome": 20, "incomeTaxExpense": 5, "incomeBeforeTax": 25, "interestExpense": 2,
        "depreciationAndAmortization": 4, "weightedAverageShsOutDil": 1000}]
BAL = [{"date": "2026-10-02", "totalAssets": 500, "totalStockholdersEquity": 200, "cashAndCashEquivalents": 10,
        "cashAndShortTermInvestments": 15, "shortTermInvestments": 5, "totalDebt": 80, "longTermDebt": 70,
        "shortTermDebt": 10}]
CASH = [{"date": "2026-10-02", "netCashProvidedByOperatingActivities": 40, "capitalExpenditure": -12,
         "stockBasedCompensation": 3}]


def test_income_y_balance_fmp_mapean_campos_y_acciones():
    i = lentes.income_fmp(INC)[0]
    assert i["totalRevenue"] == "100" and i["operatingIncome"] == "30" and i["fiscalDateEnding"] == "2026-10-02"
    b = lentes.balance_fmp(BAL, INC)[0]
    assert b["commonStockSharesOutstanding"] == "1000" and b["shortLongTermDebtTotal"] == "80"
    assert b["totalShareholderEquity"] == "200"


def test_cash_fmp_capex_en_positivo():
    c = lentes.cash_fmp(CASH)[0]
    assert float(c["capitalExpenditures"]) == 12 and c["operatingCashflow"] == "40"


def test_estimaciones_fmp_sin_historial_de_revisiones():
    e = lentes.estimaciones_fmp([{"date": "2027-12-31", "epsAvg": 3.5, "revenueAvg": 9, "numAnalystsEps": 5}], "KO")
    fila = e["estimates"][0]
    assert e["fuente"] == "FMP" and fila["eps_estimate_average"] == 3.5
    assert "eps_estimate_average_90_days_ago" not in fila


def test_precios_fmp_ultimo_dia_de_cada_mes_y_mes_en_curso():
    light = [{"date": d, "price": p} for d, p in
             [("2026-11-09", 10.0), ("2026-11-02", 9.0), ("2026-10-30", 8.0), ("2026-10-29", 7.0)]]
    adj = [{"date": d, "adjClose": p} for d, p in
           [("2026-11-09", 10.0), ("2026-11-02", 9.0), ("2026-10-30", 7.9), ("2026-10-29", 6.9)]]
    assert lentes.precios_fmp(light, adj) == [("2026-11-09", 10.0, 10.0), ("2026-10-30", 8.0, 7.9)]


def test_leer_json_fmp_acepta_el_envoltorio_guardado(tmp_path):
    p = tmp_path / "x.json"
    p.write_text(json.dumps([{"type": "text", "text": json.dumps(INC)}]), encoding="utf-8")
    assert lentes.leer_json_fmp(p)[0]["revenue"] == 100


def test_preparar_fmp_crea_archivos_y_no_pisa_los_existentes(tmp_path):
    for nombre, datos in [("fmp_income_a", INC), ("fmp_income_q", INC), ("fmp_balance_a", BAL), ("fmp_balance_q", BAL),
                          ("fmp_cash_a", CASH), ("fmp_cash_q", CASH)]:
        (tmp_path / f"{nombre}.json").write_text(json.dumps(datos), encoding="utf-8")
    (tmp_path / "cashflow.json").write_text("{}", encoding="utf-8")  # ya existe (p. ej. de Alpha Vantage)
    hecho = lentes.preparar_fmp(tmp_path)
    assert set(hecho) == {"income.json", "balance.json"}
    anual, trimestral = lentes.leer_av(tmp_path / "balance.json")
    assert anual[0]["commonStockSharesOutstanding"] == "1000" and trimestral[0]["totalAssets"] == "500"
    assert (tmp_path / "cashflow.json").read_text(encoding="utf-8") == "{}"

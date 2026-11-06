import comun
import validar
from datos import datapack_base, precios
from test_damodaran import ClienteFalsoDam, archivo_ctryprem, archivo_histimpl, archivo_sector
from test_edgar import ClienteFalso
from test_precios import YFFalso, TickerFalso, yf_mundo


def clientes(fixture, cache_tmp, yf=None):
    sector = archivo_sector()
    yf = yf or yf_mundo()
    # El yfinance simulado conoce "XYZ"; se reutiliza para NU.
    yf.tickers["NU"] = yf.tickers["XYZ"]
    return {
        "edgar": ClienteFalso(fixture, {"NU": ("0001691493", "Nu Holdings Ltd.")}, None),
        "precios": precios.ClientePrecios(cache=cache_tmp, yf=yf, dormir=lambda s: None),
        "damodaran": ClienteFalsoDam({"ctryprem.xlsx": archivo_ctryprem(), "histimpl.xls": archivo_histimpl(),
                                      "pbv.xls": sector, "pbvemerg.xls": sector, "marginemerg.xls": sector}),
    }


def test_construir_datapack_valido(fixture, cache_tmp):
    dp, serie = datapack_base.construir("nu", fecha="2026-11-06", clientes=clientes(fixture, cache_tmp))
    assert validar.validar_objeto(dp, "datapack") == []
    assert dp["ticker"] == "NU" and dp["fecha_analisis"] == "2026-11-06"
    assert dp["empresa"]["sic"] == 6199
    assert dp["damodaran"]["sector"]["region"] == "emergentes"  # sede en Brasil
    assert dp["damodaran"]["prima_pais"]["pais"] == "Brazil"
    campos = {d["campo"] for d in dp["campos_desconocidos"]}
    assert "ultimo_informe_anual" in campos and "beneficio_operativo" in campos
    assert serie and len(serie["fechas"]) > 1000
    assert "serie_eur" not in dp["precios"]


def test_construir_sin_precios(fixture, cache_tmp):
    yf = YFFalso({"NU": TickerFalso(None, {"currency": "USD"}, error=RuntimeError("caída")),
                  "XYZ": TickerFalso(None, {"currency": "USD"}, error=RuntimeError("caída"))})
    c = clientes(fixture, cache_tmp, yf)
    c["precios"] = precios.ClientePrecios(cache=cache_tmp, yf=yf, dormir=lambda s: None)
    dp, serie = datapack_base.construir("NU", clientes=c)
    assert comun.es_desconocido(dp["precios"]) and serie is None
    assert {"campo": "precios", "causa": "source_down"} in dp["campos_desconocidos"]
    assert validar.validar_objeto(dp, "datapack") == []


def test_construir_ticker_fuera_de_la_sec(fixture, cache_tmp):
    c = clientes(fixture, cache_tmp)
    c["edgar"] = ClienteFalso(fixture, {})
    c["precios"].yf.tickers["SAP.DE"] = c["precios"].yf.tickers["XYZ"]
    dp, _ = datapack_base.construir("SAP.DE", ticker_precio="SAP.DE", pais="Germany", clientes=c)
    assert comun.es_desconocido(dp["empresa"]) and dp["empresa"]["causa"] == "not_covered"
    assert validar.validar_objeto(dp, "datapack") == []


def serie_f(valores):
    return {"concepto": "X", "serie": [comun.cifra(v, "unidades", "USD", "u", f, "t") for f, v in valores]}


def test_verificacion_cruzada():
    fund = {"ingresos": serie_f([("2024-12-31", 100.0), ("2025-12-31", 200.0)]),
            "beneficio_neto": serie_f([("2025-12-31", 10.0)]),
            "acciones_diluidas": comun.desconocido("not_covered")}
    sec = {"anual": {"ingresos": {"2025-12-28": 203.0}, "beneficio_neto": {"2025-12-31": 11.0}}}
    v = datapack_base.verificacion_cruzada(fund, sec, 0.02)
    assert v["ingresos"]["estado"] == "ok" and v["ingresos"]["diferencia_rel"] == 0.015
    assert v["beneficio_neto"]["estado"] == "discrepancia_resuelta_edgar"
    assert v["acciones_diluidas"]["estado"] == "sin_comparar"
    sin = datapack_base.verificacion_cruzada(fund, comun.desconocido("source_down"), 0.02)
    assert all(x["estado"] == "sin_comparar" for x in sin.values())


def test_verificacion_cruzada_sin_ejercicio_comun():
    fund = {"ingresos": serie_f([("2025-12-31", 200.0)])}
    v = datapack_base.verificacion_cruzada(fund, {"anual": {"ingresos": {"2024-12-31": 1.0}}}, 0.02)
    assert v["ingresos"] == {"estado": "sin_comparar", "motivo": "sin ejercicio común"}

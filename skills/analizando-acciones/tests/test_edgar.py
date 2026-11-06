import pandas as pd
import pytest

import comun
from datos import edgar

URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json"
OBT = "2026-11-06T00:00:00Z"


def h(val, end, filed, start=None, form="10-K", fp="FY", accn=None):
    d = {"val": val, "end": end, "filed": filed, "form": form, "fp": fp, "accn": accn or f"acc-{filed}"}
    if start:
        d["start"] = start
    return d


def facts(tax="us-gaap", **conceptos):
    return {"facts": {tax: {c: {"units": u} for c, u in conceptos.items()}}}


# ---------------------------------------------------------------- utilidades

@pytest.mark.parametrize("entrada,esperado", [("brk.b", "BRK-B"), (" aapl ", "AAPL"), ("BF/B", "BF-B")])
def test_normalizar_ticker(entrada, esperado):
    assert edgar.normalizar_ticker(entrada) == esperado


def test_normalizar_ticker_vacio():
    with pytest.raises(ValueError):
        edgar.normalizar_ticker("  ")


def test_ejercicio_de():
    assert edgar.ejercicio_de("2024-12-31") == 2024
    assert edgar.ejercicio_de("2025-01-31") == 2024  # cierre en enero (distribución minorista)
    assert edgar.ejercicio_de("2024-09-28") == 2024


def test_cik10():
    assert edgar.cik10(320193) == "0000320193"


def test_pais_de_direccion():
    assert edgar.pais_de_direccion({"stateOrCountry": "CA", "stateOrCountryDescription": "CA"}) == "United States"
    assert edgar.pais_de_direccion({"stateOrCountry": "D5", "stateOrCountryDescription": "Brazil"}) == "Brazil"
    assert edgar.pais_de_direccion({}) is None


def test_detectar_taxonomia():
    assert edgar.detectar_taxonomia(facts("us-gaap", Revenues={})) == "us-gaap"
    assert edgar.detectar_taxonomia(facts("ifrs-full", Revenue={})) == "ifrs-full"
    with pytest.raises(comun.ErrorDatos) as e:
        edgar.detectar_taxonomia({"facts": {"dei": {}}})
    assert e.value.causa == "not_covered"


# ---------------------------------------------------------------- deduplicación

def test_dedup_conserva_ultima_presentacion_y_filtra_duracion():
    f = facts(Revenues={"USD": [
        h(100, "2023-12-31", "2024-02-01", start="2023-01-01"),
        h(105, "2023-12-31", "2025-02-01", start="2023-01-01"),          # reexpresión posterior
        h(30, "2023-12-31", "2024-02-01", start="2023-10-01"),           # trimestre dentro del 10-K
        h(120, "2024-12-31", "2025-02-01", start="2024-01-01"),
        h(50, "2024-06-30", "2024-08-01", start="2024-01-01", form="10-Q", fp="Q2"),
    ]})
    serie, unidad = edgar.hechos_anuales(f, "us-gaap", "Revenues", "flujo")
    assert unidad == "USD"
    assert {k: v["val"] for k, v in serie.items()} == {"2023-12-31": 105, "2024-12-31": 120}


def test_saldos_sin_start():
    f = facts(Assets={"USD": [h(10, "2023-12-31", "2024-02-01"), h(11, "2023-12-31", "2024-02-01", start="2023-01-01")]})
    serie, _ = edgar.hechos_anuales(f, "us-gaap", "Assets", "saldo")
    assert serie["2023-12-31"]["val"] == 10


def test_compuesto_suma_y_opcionales():
    f = facts(
        LongTermDebtNoncurrent={"USD": [h(90, "2023-12-31", "2024-02-01"), h(80, "2024-12-31", "2025-02-01")]},
        LongTermDebtCurrent={"USD": [h(10, "2023-12-31", "2024-02-01")]},
        CommercialPaper={"USD": [h(5, "2024-12-31", "2025-02-01")]},
    )
    v = edgar.extraer_campo(f, "us-gaap", "deuda_total", 10, URL, OBT)
    assert [(p["fecha_dato"], p["valor"]) for p in v["serie"]] == [("2023-12-31", 100), ("2024-12-31", 85)]
    assert v["concepto"].startswith("LongTermDebtNoncurrent+")


def test_compuesto_con_resta():
    f = facts("ifrs-full",
              InterestRevenueCalculatedUsingEffectiveInterestMethod={"USD": [h(500, "2024-12-31", "2025-04-01", start="2024-01-01", form="20-F")]},
              InterestExpense={"USD": [h(200, "2024-12-31", "2025-04-01", start="2024-01-01", form="20-F")]})
    v = edgar.extraer_campo(f, "ifrs-full", "ingresos_intereses_netos", 10, URL, OBT)
    assert v["serie"][0]["valor"] == 300
    assert v["concepto"] == "InterestRevenueCalculatedUsingEffectiveInterestMethod-InterestExpense"


def test_compuesto_falta_obligatoria_no_devuelve_nada():
    f = facts("ifrs-full", InterestExpense={"USD": [h(200, "2024-12-31", "2025-04-01", start="2024-01-01", form="20-F")]})
    assert comun.es_desconocido(edgar.extraer_campo(f, "ifrs-full", "ingresos_intereses_netos", 10, URL, OBT))


def test_combina_candidatos_cuando_cambia_el_concepto():
    f = facts(
        Revenues={"USD": [h(100, "2016-12-31", "2017-02-01", start="2016-01-01"), h(110, "2017-12-31", "2018-02-01", start="2017-01-01")]},
        RevenueFromContractWithCustomerExcludingAssessedTax={"USD": [
            h(111, "2017-12-31", "2019-02-01", start="2017-01-01"), h(120, "2018-12-31", "2019-02-01", start="2018-01-01")]},
    )
    v = edgar.extraer_campo(f, "us-gaap", "ingresos", 10, URL, OBT)
    assert v["concepto"] == "RevenueFromContractWithCustomerExcludingAssessedTax"
    assert [(p["fecha_dato"], p["valor"], p["concepto"]) for p in v["serie"]] == [
        ("2016-12-31", 100, "Revenues"),
        ("2017-12-31", 111, "RevenueFromContractWithCustomerExcludingAssessedTax"),
        ("2018-12-31", 120, "RevenueFromContractWithCustomerExcludingAssessedTax"),
    ]


def test_limite_de_anios():
    f = facts(Assets={"USD": [h(i, f"{2010 + i}-12-31", f"{2011 + i}-02-01") for i in range(14)]})
    v = edgar.extraer_campo(f, "us-gaap", "activos_totales", 10, URL, OBT)
    assert len(v["serie"]) == 10 and v["serie"][-1]["fecha_dato"] == "2023-12-31"


def test_cifra_formato_y_acciones():
    f = facts(WeightedAverageNumberOfDilutedSharesOutstanding={"shares": [h(1000, "2024-12-31", "2025-02-01", start="2024-01-01")]})
    p = edgar.extraer_campo(f, "us-gaap", "acciones_diluidas", 10, URL, OBT)["serie"][0]
    assert p["unidad"] == "acciones" and p["moneda"] is None
    assert {"valor", "unidad", "moneda", "fuente_url", "fecha_dato", "fecha_obtencion"} <= set(p)
    assert p["ejercicio"] == 2024 and p["forma"] == "10-K"


def test_campos_bancarios_solo_si_sic_bancario():
    f = facts(Assets={"USD": [h(10, "2024-12-31", "2025-02-01")]})
    _, fund, desc = edgar.extraer_fundamentales(f, 10, URL, OBT, sic=3571)
    assert "depositos" not in fund and "depositos" not in [d["campo"] for d in desc]
    _, fund, desc = edgar.extraer_fundamentales(f, 10, URL, OBT, sic=6021)
    assert comun.es_desconocido(fund["depositos"]) and "depositos" in [d["campo"] for d in desc]


def test_patrimonio_tangible_y_desactualizadas():
    f = facts(
        StockholdersEquity={"USD": [h(100, "2023-12-31", "2024-02-01"), h(120, "2024-12-31", "2025-02-01")]},
        Goodwill={"USD": [h(30, "2023-12-31", "2024-02-01")]},
        Assets={"USD": [h(500, "2024-12-31", "2025-02-01")]},
    )
    _, fund, _ = edgar.extraer_fundamentales(f, 10, URL, OBT, sic=3571)
    pt = {p["fecha_dato"]: p for p in fund["patrimonio_tangible"]["serie"]}
    assert pt["2023-12-31"]["valor"] == 70 and pt["2024-12-31"]["valor"] == 120
    assert "goodwill" in pt["2024-12-31"]["nota"]
    assert fund["goodwill"]["desactualizada"] is True
    assert fund["patrimonio"]["desactualizada"] is False


# ---------------------------------------------------------------- fixtures reales (recortados)

def test_aapl_real(fixture):
    tax, fund, desc = edgar.extraer_fundamentales(fixture("companyfacts_aapl.json"), 10, URL, OBT, sic=3571)
    assert tax == "us-gaap"
    ing = {p["ejercicio"]: p["valor"] for p in fund["ingresos"]["serie"]}
    assert ing[2024] == 391_035_000_000 and ing[2023] == 383_285_000_000
    bn = {p["ejercicio"]: p["valor"] for p in fund["beneficio_neto"]["serie"]}
    assert bn[2024] == 93_736_000_000
    assert all(p["moneda"] == "USD" for p in fund["ingresos"]["serie"])
    assert not comun.es_desconocido(fund["acciones_diluidas"])
    assert edgar.moneda_informe(fund) == "USD"


def test_nu_real_ifrs(fixture):
    tax, fund, desc = edgar.extraer_fundamentales(fixture("companyfacts_nu.json"), 10, URL, OBT, sic=6199)
    assert tax == "ifrs-full"
    ing = {p["ejercicio"]: p["valor"] for p in fund["ingresos"]["serie"]}
    assert ing[2024] == 11_517_075_000 and ing[2023] == 8_028_976_000
    assert fund["beneficio_neto"]["concepto"] == "ProfitLossAttributableToOwnersOfParent"
    assert not comun.es_desconocido(fund["depositos"]) and not comun.es_desconocido(fund["prestamos"])
    # NU etiqueta su gasto por intereses como InterestRevenueExpense: no se toma como margen de intereses.
    assert comun.es_desconocido(fund["ingresos_intereses_netos"])


def test_resumen_submissions_nu(fixture):
    r = edgar.resumen_submissions(fixture("submissions_nu.json"))
    assert r["sic"] == 6199 and r["forma_anual"] == "20-F" and r["pais_negocio"] == "Brazil"
    inf = edgar.ultimo_anual_xbrl(fixture("submissions_nu.json"))
    assert inf["forma"] == "20-F" and inf["fecha"] >= "2026-04-01"


# ---------------------------------------------------------------- complemento edgartools

def df_edgartools():
    return pd.DataFrame([
        {"concept": "ifrs-full:Revenue", "numeric_value": 15.0, "unit_ref": "USD", "period_type": "duration",
         "period_start": "2025-01-01", "period_end": "2025-12-31", "period_instant": None, "is_dimensioned": False},
        {"concept": "ifrs-full:Revenue", "numeric_value": 9.0, "unit_ref": "USD", "period_type": "duration",
         "period_start": "2025-01-01", "period_end": "2025-12-31", "period_instant": None, "is_dimensioned": True},
        {"concept": "ifrs-full:Assets", "numeric_value": 70.0, "unit_ref": "USD", "period_type": "instant",
         "period_start": None, "period_end": None, "period_instant": "2025-12-31", "is_dimensioned": False},
        {"concept": "nu:Propio", "numeric_value": 1.0, "unit_ref": "USD", "period_type": "instant",
         "period_start": None, "period_end": None, "period_instant": "2025-12-31", "is_dimensioned": False},
        {"concept": "ifrs-full:Texto", "numeric_value": None, "unit_ref": None, "period_type": "duration",
         "period_start": "2025-01-01", "period_end": "2025-12-31", "period_instant": None, "is_dimensioned": False},
    ])


def test_hechos_desde_dataframe_y_fusion(fixture):
    extra = edgar.hechos_desde_dataframe(df_edgartools(), "ifrs-full", "acc-2026", "20-F", "2026-04-08")
    ifrs = extra["facts"]["ifrs-full"]
    assert set(ifrs) == {"Revenue", "Assets"}
    assert ifrs["Revenue"]["units"]["USD"] == [{"val": 15, "form": "20-F", "fp": "FY", "filed": "2026-04-08",
                                                "accn": "acc-2026", "start": "2025-01-01", "end": "2025-12-31"}]
    base = fixture("companyfacts_nu.json")
    fus = edgar.fusionar_facts(base, extra)
    assert len(base["facts"]["ifrs-full"]["Revenue"]["units"]["USD"]) + 1 == len(fus["facts"]["ifrs-full"]["Revenue"]["units"]["USD"])
    v = edgar.extraer_campo(fus, "ifrs-full", "ingresos", 10, URL, OBT)
    assert v["serie"][-1]["fecha_dato"] == "2025-12-31" and v["serie"][-1]["valor"] == 15


def test_importar_edgartools_no_confunde_con_este_modulo():
    et = edgar.importar_edgartools()
    assert hasattr(et, "find") and hasattr(et, "set_identity")
    assert et.__name__ == "edgar"


# ---------------------------------------------------------------- obtener() con cliente simulado

class ClienteFalso:
    def __init__(self, fixture, mapa, informe_extra=None):
        self.f, self.mapa, self.extra = fixture, mapa, informe_extra
        self.llamadas_xbrl = 0

    def cik(self, ticker):
        t = edgar.normalizar_ticker(ticker)
        if t not in self.mapa:
            raise comun.ErrorDatos(f"Ticker {t} no registrado en la SEC", "not_covered")
        return self.mapa[t]

    def submissions(self, cik):
        return self.f("submissions_nu.json"), {"origen": "cache", "ts": 1.7e9}

    def companyfacts(self, cik):
        return self.f("companyfacts_nu.json"), {"origen": "cache", "ts": 1.7e9}

    def hechos_informe(self, informe, tax):
        self.llamadas_xbrl += 1
        if self.extra is None:
            raise comun.ErrorDatos("sin edgartools", "source_down")
        return self.extra, {"origen": "red", "ts": 1.7e9}


def test_obtener_ticker_no_registrado(fixture):
    r = edgar.obtener("SAP.DE", cliente=ClienteFalso(fixture, {}))
    assert comun.es_desconocido(r["empresa"]) and r["empresa"]["causa"] == "not_covered"


def test_obtener_completa_con_ultimo_informe(fixture):
    extra = edgar.hechos_desde_dataframe(df_edgartools(), "ifrs-full", "0001292814-26-002166", "20-F", "2026-04-08")
    cli = ClienteFalso(fixture, {"NU": ("0001691493", "Nu Holdings Ltd.")}, extra)
    r = edgar.obtener("nu", anios=10, cliente=cli)
    assert cli.llamadas_xbrl == 1
    e = r["empresa"]
    assert (e["ticker"], e["sic"], e["taxonomia"], e["moneda_informe"]) == ("NU", 6199, "ifrs-full", "USD")
    ult = r["fundamentales"]["ingresos"]["serie"][-1]
    assert ult["fecha_dato"] == "2025-12-31"
    assert ult["fuente_url"] == "https://www.sec.gov/Archives/edgar/data/1691493/000129281426002166/"
    assert any(f.get("published_at") == "2026-04-08" for f in r["fuentes"])


def test_obtener_marca_stale_si_falla_edgartools(fixture):
    cli = ClienteFalso(fixture, {"NU": ("0001691493", "Nu Holdings Ltd.")}, None)
    r = edgar.obtener("NU", anios=10, cliente=cli)
    assert {"campo": "ultimo_informe_anual", "causa": "stale"} in r["desconocidos"]
    assert "aviso" in r["empresa"]
    assert r["fundamentales"]["ingresos"]["serie"][-1]["fecha_dato"] == "2024-12-31"


# ---------------------------------------------------------------- ClienteEdgar HTTP

class Resp:
    def __init__(self, status, data=None):
        self.status_code, self._d = status, data

    def json(self):
        return self._d


class Sesion:
    def __init__(self, respuestas):
        self.respuestas, self.cabeceras = list(respuestas), []

    def get(self, url, headers, timeout):
        self.cabeceras.append(headers)
        return self.respuestas.pop(0)


def cliente(cache_tmp, respuestas):
    from datos.cache import TokenBucket

    return edgar.ClienteEdgar(cache=cache_tmp, user_agent="Prueba prueba@example.com", sesion=Sesion(respuestas),
                              bucket=TokenBucket(1000), dormir=lambda s: None)


def test_cliente_404_es_not_covered_sin_reintentos(cache_tmp):
    c = cliente(cache_tmp, [Resp(404)])
    with pytest.raises(comun.ErrorDatos) as e:
        c.companyfacts("0000000001")
    assert e.value.causa == "not_covered"


def test_cliente_429_reintenta(cache_tmp):
    c = cliente(cache_tmp, [Resp(429), Resp(429), Resp(200, {"0": {"cik_str": 1, "ticker": "X", "title": "X Inc"}})])
    assert c.cik("x") == ("0000000001", "X Inc")
    assert c.sesion.cabeceras[0]["User-Agent"] == "Prueba prueba@example.com"
    # segunda llamada: caché, sin red
    assert c.cik("X") == ("0000000001", "X Inc")


def test_cliente_429_persistente_es_rate_limited(cache_tmp):
    c = cliente(cache_tmp, [Resp(429)] * 4)
    with pytest.raises(comun.ErrorDatos) as e:
        c.mapa_tickers()
    assert e.value.causa == "rate_limited"

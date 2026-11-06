import csv
import io

import pandas as pd
import pytest

import comun
from datos import damodaran

# Industrias de Damodaran (enero de 2026, margin.xls). El mapeo SIC solo puede usar estos nombres.
INDUSTRIAS_DAMODARAN = {
    "Advertising", "Aerospace/Defense", "Air Transport", "Apparel", "Auto & Truck", "Auto Parts", "Bank (Money Center)",
    "Banks (Regional)", "Beverage (Alcoholic)", "Beverage (Soft)", "Broadcasting", "Brokerage & Investment Banking",
    "Building Materials", "Business & Consumer Services", "Cable TV", "Chemical (Basic)", "Chemical (Diversified)",
    "Chemical (Specialty)", "Coal & Related Energy", "Computer Services", "Computers/Peripherals", "Construction Supplies",
    "Diversified", "Drugs (Biotechnology)", "Drugs (Pharmaceutical)", "Education", "Electrical Equipment",
    "Electronics (Consumer & Office)", "Electronics (General)", "Engineering/Construction", "Entertainment",
    "Environmental & Waste Services", "Farming/Agriculture", "Financial Svcs. (Non-bank & Insurance)", "Food Processing",
    "Food Wholesalers", "Furn/Home Furnishings", "Green & Renewable Energy", "Healthcare Products",
    "Healthcare Support Services", "Heathcare Information and Technology", "Homebuilding", "Hospitals/Healthcare Facilities",
    "Hotel/Gaming", "Household Products", "Information Services", "Insurance (General)", "Insurance (Life)",
    "Insurance (Prop/Cas.)", "Investments & Asset Management", "Machinery", "Metals & Mining", "Office Equipment & Services",
    "Oil/Gas (Integrated)", "Oil/Gas (Production and Exploration)", "Oil/Gas Distribution", "Oilfield Svcs/Equip.",
    "Packaging & Container", "Paper/Forest Products", "Power", "Precious Metals", "Publishing & Newspapers", "R.E.I.T.",
    "Real Estate (Development)", "Real Estate (General/Diversified)", "Real Estate (Operations & Services)", "Recreation",
    "Reinsurance", "Restaurant/Dining", "Retail (Automotive)", "Retail (Building Supply)", "Retail (Distributors)",
    "Retail (General)", "Retail (Grocery and Food)", "Retail (REITs)", "Retail (Special Lines)", "Rubber& Tires",
    "Semiconductor", "Semiconductor Equip", "Shipbuilding & Marine", "Shoe", "Software (Entertainment)",
    "Software (Internet)", "Software (System & Application)", "Steel", "Telecom (Wireless)", "Telecom. Equipment",
    "Telecom. Services", "Tobacco", "Transportation", "Transportation (Railroads)", "Trucking", "Utility (General)",
    "Utility (Water)", "Total Market", "Total Market (without financials)",
}
RUTAS_VALIDAS = {"general", "banco_credito", "biotech_candidata", "fuera_de_alcance"}


def xlsx(hojas: dict[str, list[list]]) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        for nombre, filas in hojas.items():
            pd.DataFrame(filas).to_excel(w, sheet_name=nombre, header=False, index=False)
    return buf.getvalue()


def archivo_sector() -> bytes:
    filas = [["Date updated:", "2026-01-05"], ["Created by:", "Aswath Damodaran"], [None], [None],
             ["Industry Name", "Number of firms", "Gross Margin", "Pre-tax Unadjusted Operating Margin",
              "Pre-tax Unadjusted Operating Margin", "EV/EBITDA"],
             ["Software (System & Application)", 300, 0.71, 0.30, 0.99, 25.0],
             ["Banks (Regional)", 600, None, "NA", 0.1, None],
             [None, None, None]]
    return xlsx({"Variables & FAQ": [["texto"]], "Industry Averages": filas})


def archivo_ctryprem() -> bytes:
    filas = [["Country and Equity Risk Premiums"],
             ["Date of update:", pd.Timestamp("2026-01-01"), "(Updated Feb 16)"],
             ["Enter the current risk premium", None, None, None, 0.0423, "Implied ERP for S&P 500 on January 1"],
             ["Enter the US ERP", None, None, None, 0.0446, "US equity risk premium"],
             [None],
             ["Country", "Region", "Moody's rating", "Rating-based Default Spread", "Total Equity Risk Premium",
              "Country Risk Premium", "Sovereign CDS, net of US", "Total Equity Risk Premium", "Country Risk Premium"],
             ["Brazil", "Central and South America", "Ba1", 0.0213, 0.0747, 0.0324, 0.02, 0.07, 0.03],
             ["Spain", "Western Europe", "Baa1", 0.0136, 0.0630, 0.0207, None, None, None],
             ["United States", "North America", "Aa1", 0.0023, 0.0458, 0.0035, None, None, None],
             ["Japan", "Asia", "A1", 0.006, 0.05, 0.008, None, None, None]]
    return xlsx({"Explanation and FAQ": [["x"]], "ERPs by country": filas})


def archivo_histimpl() -> bytes:
    filas = [["Date updated:", "2026-01-05"], [None],
             ["Year", "Earnings Yield", "T.Bond Rate", "Implied ERP (FCFE)"],
             [2024, 0.04, 0.0458, 0.0433], [2025, 0.039, 0.0418, 0.0423], [None], ["Period", "ERP"]]
    return xlsx({"Historical Impl Premiums": filas})


def test_tabla_industrias_detecta_cabecera_y_duplicados():
    t = damodaran.tabla_industrias(archivo_sector())
    assert list(t.index) == ["Software (System & Application)", "Banks (Regional)"]
    assert "pre-tax unadjusted operating margin" in t.columns and "pre-tax unadjusted operating margin #2" in t.columns
    assert t.at["Software (System & Application)", "pre-tax unadjusted operating margin"] == 0.30


def test_tabla_sin_hoja_falla():
    with pytest.raises(comun.ErrorDatos):
        damodaran.tabla_industrias(xlsx({"Otra": [["a"]]}))


def test_extraer_sector_valores_y_nulos():
    t = damodaran.tabla_industrias(archivo_sector())
    v = damodaran.extraer_sector({"margenes": t, "ev_ebitda": t}, "Software (System & Application)")
    assert v["margenes.margen_bruto"] == 0.71 and v["margenes.margen_operativo"] == 0.30
    assert v["ev_ebitda.ev_ebitda"] == 25.0
    assert v["betas.beta"] is None  # conjunto no cargado
    b = damodaran.extraer_sector({"margenes": t}, "Banks (Regional)")
    assert b["margenes.margen_bruto"] is None and b["margenes.margen_operativo"] is None  # NaN y "NA"


def test_erp_y_primas():
    b = archivo_ctryprem()
    erp = damodaran.erp_madura(b)
    assert erp == {"erp": 0.0423, "fecha_actualizacion": "2026-01-01"}
    p = damodaran.primas_pais(b)
    assert p["Brazil"] == {"region": "Central and South America", "rating_moodys": "Ba1", "diferencial_impago": 0.0213,
                           "erp_total": 0.0747, "crp": 0.0324}
    assert damodaran.region_sectorial("Brazil", p) == "emergentes"
    assert damodaran.region_sectorial("Spain", p) == "europa"
    assert damodaran.region_sectorial("Japan", p) == "global"
    assert damodaran.region_sectorial("USA", p) == "us"
    assert damodaran.region_sectorial(None, p) == "global"


def test_erp_historica():
    assert damodaran.erp_historica(archivo_histimpl()) == {"anio": 2025, "erp": 0.0423, "tbond": 0.0418}


@pytest.mark.parametrize("conj,region,archivo", [
    ("betas", "us", "betas.xls"), ("pbv", "us", "pbvdata.xls"), ("margenes", "us", "margin.xls"),
    ("betas", "europa", "betaEurope.xls"), ("roic", "emergentes", "EVAemerg.xls"), ("pbv", "global", "pbvGlobal.xls"),
])
def test_archivo_conjunto(conj, region, archivo):
    assert damodaran.archivo_conjunto(conj, region) == archivo


@pytest.mark.parametrize("sic,industria,ruta,ciclica", [
    (7372, "Software (System & Application)", "general", False),
    (6199, "Financial Svcs. (Non-bank & Insurance)", "banco_credito", False),
    (6021, "Banks (Regional)", "banco_credito", False),
    (6798, "R.E.I.T.", "fuera_de_alcance", False),
    (6311, "Insurance (Life)", "fuera_de_alcance", False),
    (6770, "Investments & Asset Management", "fuera_de_alcance", False),
    (2836, "Drugs (Biotechnology)", "biotech_candidata", False),
    (3674, "Semiconductor", "general", True),
    (3711, "Auto & Truck", "general", True),
    (1311, "Oil/Gas (Production and Exploration)", "general", True),
    (3571, "Computers/Peripherals", "general", False),
])
def test_clasificar_sic(sic, industria, ruta, ciclica):
    c = damodaran.clasificar_sic(sic)
    assert (c["industria_damodaran"], c["ruta_sic"], c["ciclica_sic"]) == (industria, ruta, ciclica)


def test_clasificar_sin_sic():
    assert damodaran.clasificar_sic(None)["industria_damodaran"] == "Total Market"
    assert damodaran.clasificar_sic(9999)["motivo"].startswith("SIC 9999")


def test_tabla_sic_coherente():
    with open(damodaran.RUTA_SIC, encoding="utf-8") as f:
        filas = list(csv.DictReader(f))
    for r in filas:
        assert r["industria_damodaran"] in INDUSTRIAS_DAMODARAN, r
        assert r["ruta"] in RUTAS_VALIDAS, r
        assert int(r["sic_desde"]) <= int(r["sic_hasta"]), r
        assert r["ciclica"] in ("0", "1")
    # Cada SIC tiene una única fila más específica (sin empates de anchura).
    for sic in range(100, 10000):
        cand = [r for r in filas if int(r["sic_desde"]) <= sic <= int(r["sic_hasta"])]
        if cand:
            anchos = sorted(int(r["sic_hasta"]) - int(r["sic_desde"]) for r in cand)
            assert len(anchos) == 1 or anchos[0] < anchos[1], (sic, cand)


class ClienteFalsoDam(damodaran.ClienteDamodaran):
    def __init__(self, archivos):
        self.cfg = comun.cargar_config()
        self.base = "https://x/"
        self.archivos = archivos

    def descargar(self, archivo):
        if archivo not in self.archivos:
            raise comun.ErrorDatos(f"404 {archivo}", "not_covered")
        return self.archivos[archivo], "red"


def test_construir_seccion():
    sector = archivo_sector()
    c = ClienteFalsoDam({"ctryprem.xlsx": archivo_ctryprem(), "histimpl.xls": archivo_histimpl(),
                         "margin.xls": sector, "vebitda.xls": sector})
    s = damodaran.construir_seccion(7372, "United States", c)
    assert s["erp_madura"]["valor"] == 0.0423 and s["erp_madura"]["fecha_dato"] == "2026-01-01"
    assert s["prima_pais"]["crp"]["valor"] == 0.0035 and s["prima_pais"]["pais"] == "United States"
    assert s["sector"]["region"] == "us"
    v = s["sector"]["valores"]
    assert v["margenes.margen_operativo"]["valor"] == 0.30 and v["margenes.margen_operativo"]["unidad"] == "ratio"
    assert v["ev_ebitda.ev_ebitda"]["unidad"] == "veces"
    assert comun.es_desconocido(v["betas.beta"])
    assert {"campo": "damodaran.sector.betas.beta", "causa": "not_covered"} in s["desconocidos"]


def test_construir_seccion_pais_desconocido():
    c = ClienteFalsoDam({"ctryprem.xlsx": archivo_ctryprem(), "histimpl.xls": archivo_histimpl()})
    s = damodaran.construir_seccion(7372, "Narnia", c)
    assert comun.es_desconocido(s["prima_pais"]) and s["sector"]["region"] == "global"


def test_tasas_impositivas_por_pais():
    filas = [["Country", "GDP (in millions)", "Moody's rating", "Sovereign CDS", "Adj. Default Spread",
              "Equity Risk Premium", "Country Risk Premium", "Corporate Tax Rate", "Region"],
             ["Brazil", 2e6, "Ba1", 0.02, 0.0213, 0.0747, 0.0324, 0.34, "Central and South America"],
             ["Spain", 1.5e6, "Baa1", None, 0.0136, 0.0630, 0.0207, 0.25, "Western Europe"]]
    contenido = xlsx({"ERPs by country": [["Country", "Region", "Moody's rating", "Rating-based Default Spread",
                                           "Total Equity Risk Premium", "Country Risk Premium"],
                                          ["Brazil", "Central and South America", "Ba1", 0.0213, 0.0747, 0.0324]],
                      "Regional breakdown": filas})
    assert damodaran.tasas_impositivas(contenido) == {"Brazil": 0.34, "Spain": 0.25}
    assert damodaran.primas_pais(contenido)["Brazil"]["tasa_impuestos"] == 0.34
    assert damodaran.tasas_impositivas(archivo_ctryprem()) == {}            # sin la hoja: no inventa nada


HTML_RATINGS = """<table><tr><td>If interest coverage ratio is</td></tr>
<tr><td>&gt;</td><td>&le; to</td><td>Rating is</td><td>Spread is</td></tr>
""" + "".join(f"<tr><td>{a}</td><td>{b}</td><td>{r}</td><td>{s}%</td><td></td><td>x</td></tr>" for a, b, r, s in [
    ("-100000", "0.199999", "D2/D", "19.00"), ("0.2", "0.649999", "C2/C", "16.00"), ("0.65", "0.799999", "Ca2/CC", "12.61"),
    ("0.8", "1.249999", "Caa/CCC", "8.85"), ("1.25", "1.499999", "B3/B-", "5.09"), ("1.5", "1.749999", "B2/B", "3.21"),
    ("1.75", "1.999999", "B1/B+", "2.75"), ("2", "2.2499999", "Ba2/BB", "1.84"), ("2.25", "2.49999", "Ba1/BB+", "1.38"),
    ("2.5", "2.999999", "Baa2/BBB", "1.11"), ("3", "4.249999", "A3/A-", "0.89"), ("8.50", "100000", "Aaa/AAA", "0.40")]) + "</table>"


def test_tabla_ratings():
    t = damodaran.tabla_ratings(HTML_RATINGS)
    assert len(t) == 12 and t[0] == {"cobertura_min": -100000.0, "rating": "D2/D", "diferencial": 0.19}
    assert t[-1] == {"cobertura_min": 8.5, "rating": "Aaa/AAA", "diferencial": 0.004}
    from motor.dcf import rating_sintetico
    assert rating_sintetico(2.6, t)["rating"] == "Baa2/BBB"
    with pytest.raises(comun.ErrorDatos):
        damodaran.tabla_ratings("<table><tr><td>nada</td></tr></table>")


def test_construir_seccion_incluye_la_tabla_de_ratings():
    c = ClienteFalsoDam({"ctryprem.xlsx": archivo_ctryprem(), "histimpl.xls": archivo_histimpl(),
                         comun.cargar_config()["damodaran"]["url_ratings"]: HTML_RATINGS.encode("latin-1")})
    s = damodaran.construir_seccion(7372, "United States", c)
    assert len(s["tabla_ratings"]["filas"]) == 12
    s = damodaran.construir_seccion(7372, "United States", ClienteFalsoDam({"ctryprem.xlsx": archivo_ctryprem(),
                                                                            "histimpl.xls": archivo_histimpl()}))
    assert comun.es_desconocido(s["tabla_ratings"])

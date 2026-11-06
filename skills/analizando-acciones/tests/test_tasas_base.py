import json
import math

import numpy as np
import pandas as pd
import pytest

import comun
import tasas_base
import tasas_base_build as build
from motor import rnpv
from dp_sintetico import crecer, datapack

MM = 1_000_000_000


def fila(metrica="crecimiento_ventas_5a", clase="2000-5000", sector="todos", media=0.069, desv=0.111, **q):
    base = {"clase_musd": clase, "sector": sector, "metrica": metrica, "n": 1000.0, "media": media, "desv": desv,
            "p10": None, "p25": None, "p50": None, "p75": None, "p90": None, "fuente": "test", "periodo": "x", "notas": ""}
    base.update(q)
    return base


# ---------------------------------------------------------------- clases y percentiles

@pytest.mark.parametrize("ventas,clase", [(50, None), (100, "100-500"), (499.9, "100-500"), (500, "500-2000"),
                                          (3500, "2000-5000"), (7000, "5000-10000"), (15775, "10000-50000"),
                                          (478834, ">50000"), (None, None), (-5, None)])
def test_clase_tamano(ventas, clase):
    assert tasas_base.clase_tamano(ventas) == clase


def test_percentil_normal_sin_cuantiles():
    f = fila()
    assert tasas_base.percentil(0.069, f) == pytest.approx(50.0)
    assert tasas_base.percentil(0.069 + 0.111, f) == pytest.approx(84.13, abs=0.01)
    assert tasas_base.z_score(0.069 + 2 * 0.111, f) == pytest.approx(2.0)


def test_percentil_con_cuantiles_interpola_y_acota_colas():
    f = fila(media=0.05, desv=0.10, p10=-0.05, p25=0.0, p50=0.05, p75=0.10, p90=0.15)
    assert tasas_base.percentil(0.05, f) == pytest.approx(50)
    assert tasas_base.percentil(0.025, f) == pytest.approx(37.5)   # a mitad entre p25 y p50
    assert tasas_base.percentil(0.15, f) == pytest.approx(90)
    cola = tasas_base.percentil(0.30, f)                            # normal daría 99,4; se acota a [90, 99.9]
    assert 90 < cola <= 99.9
    assert tasas_base.percentil(-1.0, f) <= 10


def test_banderas_z():
    assert tasas_base.bandera(2.0) is None
    assert tasas_base.bandera(2.01) == "requiere_evidencia_excepcional"
    assert tasas_base.bandera(3.0) == "requiere_evidencia_excepcional"
    assert tasas_base.bandera(3.01) == "casi_imposible_organicamente"


def test_encogimiento():
    assert tasas_base.encoger(0.20, 0.069, 0.3) == pytest.approx(0.069 + 0.3 * (0.20 - 0.069))
    assert tasas_base.encoger(0.30, 0.10, 0.6) == pytest.approx(0.22)
    assert tasas_base.encoger(0.10, 0.10, 0.6) == pytest.approx(0.10)


def test_evaluar_driver_con_k_de_config():
    tabla = (fila(),)
    r = tasas_base.evaluar("crecimiento_ingresos", 0.35, 3500, tabla=tabla)
    assert r["estado"] == "ok" and r["clase"] == "2000-5000" and r["k"] == 0.3
    assert r["z"] == pytest.approx((0.35 - 0.069) / 0.111)
    assert r["bandera"] == "requiere_evidencia_excepcional"
    assert r["valor_encogido"] == pytest.approx(0.069 + 0.3 * (0.35 - 0.069))
    assert r["referencia"]["p90"] == pytest.approx(0.069 + 1.2815515655446004 * 0.111)
    with pytest.raises(ValueError):
        tasas_base.evaluar("driver_inventado", 1.0, 3500, tabla=tabla)


def test_busqueda_con_degradacion():
    tabla = (fila(clase="todas", media=0.06), fila(clase="2000-5000", sector="todos", media=0.07),
             fila(clase="2000-5000", sector="IT", media=0.08))
    assert tasas_base.buscar_fila(tabla, "crecimiento_ventas_5a", "2000-5000", "IT")[0]["media"] == 0.08
    f, nota = tasas_base.buscar_fila(tabla, "crecimiento_ventas_5a", "2000-5000", "Energía")
    assert f["media"] == 0.07 and "sin sector Energía" in nota
    f, nota = tasas_base.buscar_fila(tabla, "crecimiento_ventas_5a", "10000-50000")
    assert f["media"] == 0.06 and "muestra completa" in nota
    assert tasas_base.buscar_fila(tabla, "roe", "2000-5000")[0] is None
    assert tasas_base.evaluar("roe", 0.1, 3500, tabla=tabla)["estado"] == "sin_referencia"


# ---------------------------------------------------------------- observados y datapack

def test_tcac_y_observados():
    assert tasas_base.tcac([100, 110, 121, 133.1], 3) == pytest.approx(0.10)
    assert tasas_base.tcac([100, 110], 3) is None
    assert tasas_base.tcac([0, 10, 20, 30], 3) is None
    ing = crecer(10 * MM, 0.10, 8)
    dp = datapack(ingresos=ing, beneficio_operativo=[i * 0.2 for i in ing], beneficio_neto=[i * 0.1 for i in ing],
                  patrimonio=[i * 0.5 for i in ing])
    o = tasas_base.observados(dp)
    assert o["crecimiento_ventas_5a"] == pytest.approx(0.10) and o["crecimiento_ventas_3a"] == pytest.approx(0.10)
    assert o["margen_operativo"] == pytest.approx(0.2) and o["roe"] == pytest.approx(0.2)
    assert tasas_base.ventas_musd(dp) == pytest.approx(ing[-1] / 1e6)
    assert tasas_base.ventas_musd(datapack(moneda="BRL", ingresos=ing)) is None


def test_construir_seccion():
    tabla = (fila(), fila("margen_operativo", media=0.10, desv=0.14), fila("roe", media=0.11, desv=0.37),
             fila("crecimiento_ventas_3a", media=0.05, desv=0.12))
    ing = crecer(2.0 * MM, 0.08, 8)  # termina en ~3.430 M$ → clase 2000-5000
    dp = datapack(ingresos=ing, beneficio_operativo=[i * 0.25 for i in ing])
    r = tasas_base.construir(dp, {"crecimiento_ingresos": 0.12, "roe": 0.30}, tabla=tabla)
    assert r["clase_tamano"] == "2000-5000" and r["ventas_musd"] == pytest.approx(ing[-1] / 1e6)
    assert r["observados"]["roe"] == {"estado": "sin_datos"}
    assert r["observados"]["margen_operativo"]["bandera"] is None
    assert set(r["drivers"]) == {"crecimiento_ingresos", "roe"}
    assert r["para_reverse_dcf"]["crecimiento_ingresos"] == {"media": 0.069, "desv": 0.111}
    sin_usd = tasas_base.construir(datapack(moneda="BRL", ingresos=ing), tabla=tabla)
    assert sin_usd["clase_tamano"] is None and "aviso" in sin_usd


# ---------------------------------------------------------------- assets reales

def test_base_rates_csv_real():
    tabla = tasas_base.cargar_tabla(str(tasas_base.RUTA_BASE_RATES))
    pub = [f for f in tabla if f["fuente"] == "mauboussin_2026"]
    assert {(f["sector"], f["metrica"]) for f in pub} == {("todos", "crecimiento_ventas_5a"),
                                                        ("todos", "crecimiento_ventas_5a_real"),
                                                        ("IT", "crecimiento_ventas_5a")}
    nominal = next(f for f in pub if f["metrica"] == "crecimiento_ventas_5a" and f["sector"] == "todos")
    assert (nominal["media"], nominal["desv"], nominal["n"], nominal["clase_musd"]) == (0.069, 0.111, 19264, "2000-5000")
    real = next(f for f in pub if f["metrica"] == "crecimiento_ventas_5a_real")
    assert (real["media"], real["desv"]) == (0.037, 0.106)
    calc = [f for f in tabla if f["fuente"] == "edgar_frames_calc"]
    clases = {f["clase_musd"] for f in calc}
    assert {"5000-10000", "10000-50000", ">50000", "todas"} <= clases  # las clases que pide A6.3
    for f in calc:
        assert f["n"] >= build.MIN_N and f["desv"] > 0
        assert f["p10"] < f["p25"] <= f["p50"] <= f["p75"] < f["p90"]
    # Una empresa de >50.000 M$ debe resolverse con su propia clase.
    assert tasas_base.buscar_fila(tabla, "margen_operativo", ">50000")[0]["clase_musd"] == ">50000"


def test_bio_csv_real():
    filas = rnpv.cargar_tabla_bio()
    todas = {f["transicion"]: f for f in filas if f["area"] == "todas"}
    assert [(todas[t]["p"], todas[t]["n"]) for t in rnpv.TRANSICIONES] == [(0.52, 4414), (0.289, 4933), (0.578, 1928), (0.906, 1453)]
    p = rnpv.probabilidad_acumulada(filas, "todas", "I")["p"]
    assert p == pytest.approx(0.079, abs=0.001)  # 7,9 % desde Fase I
    for grupo in ("area", "oncologia_vs_no", "oncologia_subtipo", "prevalencia", "clase_fa", "modalidad", "biomarcadores"):
        assert len(rnpv.cargar_tabla_bio(grupo=grupo)) >= 8
    with pytest.raises(Exception):
        rnpv.cargar_tabla_bio(grupo="no_existe")


def test_bio_csv_hematologia_y_urologia_sin_encoger():
    """Sin encogimiento, el producto de las transiciones reproduce el LOA publicado: hematología 23,9 %, urología 3,6 %."""
    filas = rnpv.cargar_tabla_bio()
    def producto(area):
        p = 1.0
        for t in rnpv.TRANSICIONES:
            p *= next(f["p"] for f in filas if f["area"] == area and f["transicion"] == t)
        return p
    assert producto("hematology") == pytest.approx(0.239, abs=0.001)
    assert producto("urology") == pytest.approx(0.036, abs=0.001)


def test_bio_encogimiento_en_areas_pequenas():
    filas = rnpv.cargar_tabla_bio()
    uro = rnpv.probabilidad_transicion(filas, "urology", "I_II")   # n=22 < 100
    assert uro["origen"] == "encogida"
    assert uro["p"] == pytest.approx((22 * 0.409 + 100 * 0.52) / 122)
    onc = rnpv.probabilidad_transicion(filas, "oncology", "I_II")  # n=1628
    assert onc["origen"] == "area" and onc["p"] == 0.488


# ---------------------------------------------------------------- construcción de tasas base (sin red)

def test_clase_de_y_clases():
    lim = [100, 500, 2000]
    assert [e for _, _, e in build.clases(lim)] == ["100-500", "500-2000", ">2000"]
    assert build.clase_de(99, lim) is None and build.clase_de(100, lim) == "100-500" and build.clase_de(5000, lim) == ">2000"


def datos_sinteticos():
    """100 emisores con ventas crecientes al 10 % y márgenes/ROE constantes, 2010-2016."""
    d = {"ventas": {}, "ebit": {}, "bn": {}, "patrimonio": {}}
    for cik in range(1, 101):
        for i, y in enumerate(range(2010, 2017)):
            v = 1e9 * (1.10 ** i)
            d["ventas"][(cik, y)] = v
            d["ebit"][(cik, y)] = v * 0.12
            d["bn"][(cik, y)] = v * 0.08
            d["patrimonio"][(cik, y)] = v * 0.5
    return d


def test_observaciones_y_agregacion():
    lim = [100, 500, 2000, 5000]
    df = build.observaciones(datos_sinteticos(), lim, 100)
    assert set(df["clase"]) == {"500-2000"} or "2000-5000" in set(df["clase"])
    inicial = df[df["anio"] == 2010].iloc[0]
    assert inicial["crec3"] == pytest.approx(0.10) and inicial["crec5"] == pytest.approx(0.10)
    assert inicial["margen"] == pytest.approx(0.12) and inicial["roe"] == pytest.approx(0.16)
    assert math.isnan(df[df["anio"] == 2016].iloc[0]["crec3"])  # sin datos a 3 años
    filas = build.agregar(df, lim, (1, 99), "2010-2016")
    por = {(f["clase_musd"], f["metrica"]): f for f in filas}
    f = por[("todas", "crecimiento_ventas_5a")]
    assert f["media"] == pytest.approx(0.10) and f["n"] == 200 and f["fuente"] == "edgar_frames_calc"
    assert por[("todas", "margen_operativo")]["media"] == pytest.approx(0.12)


def test_roe_excluye_patrimonio_negativo_y_agregar_exige_n_minimo():
    d = datos_sinteticos()
    d["patrimonio"][(1, 2010)] = -5.0
    df = build.observaciones(d, [100, 500, 2000, 5000], 100)
    assert math.isnan(df[(df["cik"] == 1) & (df["anio"] == 2010)].iloc[0]["roe"])
    poco = df[df["cik"] <= 3]
    assert not any(f["clase_musd"] == "todas" for f in build.agregar(poco, [100, 500, 2000, 5000], (1, 99), "x"))


def test_resumen_winsoriza_colas():
    v = np.concatenate([np.full(98, 0.05), [10.0, -10.0]])
    r = build.resumen(v, (1, 99))
    assert r["n"] == 100 and abs(r["media"]) < 0.5 and r["desv"] < 1.0   # sin winsorizar la desv sería ~1,4
    assert r["p50"] == pytest.approx(0.05)


class ClienteFrames:
    def __init__(self):
        self.pedidos = []

    def frame(self, concepto, unidad, periodo, taxonomia="us-gaap"):
        self.pedidos.append((concepto, periodo))
        anio = int(periodo[2:6])
        if concepto == "Revenues":
            return [[1, 1e9 * 1.1 ** (anio - 2010), "x", "y"], [2, 0, "x", "y"]]
        if concepto == "SalesRevenueNet":
            return [[1, 5.0, "x", "y"], [3, 2e9, "x", "y"]]  # el emisor 1 ya tiene Revenues: se ignora; el 3 se añade
        if concepto == "OperatingIncomeLoss":
            return [[1, 1e8, "x", "y"]]
        return []


def test_descargar_prioriza_conceptos_y_descarta_ventas_no_positivas():
    c = ClienteFrames()
    d = build.descargar(c, 2010, 2011)
    assert d["ventas"][(1, 2010)] == pytest.approx(1e9) and (2, 2010) not in d["ventas"]
    assert d["ventas"][(3, 2010)] == 2e9
    assert d["ebit"][(1, 2011)] == 1e8 and d["bn"] == {}
    assert ("StockholdersEquity", "CY2010Q4I") in c.pedidos


def test_escribir_y_filas_publicadas(tmp_path):
    filas = build.filas_publicadas() + [{"clase_musd": "todas", "sector": "todos", "metrica": "roe", "n": 40,
                                         "media": 0.1, "desv": 0.2, "p10": -0.1, "p25": 0.0, "p50": 0.1, "p75": 0.2,
                                         "p90": 0.3, "fuente": "edgar_frames_calc", "periodo": "x", "notas": "n"}]
    ruta = build.escribir(filas, tmp_path / "br.csv")
    tabla = tasas_base.cargar_tabla(str(ruta))
    assert len(tabla) == 4 and tabla[3]["p90"] == pytest.approx(0.3) and tabla[0]["p90"] is None
    assert build.main(["--solo-publicadas", "--salida", str(tmp_path / "pub.csv")]) == 0
    assert len(tasas_base.cargar_tabla(str(tmp_path / "pub.csv"))) == 3


def test_cli(tmp_path, capsys):
    assert tasas_base.main(["--valor", "0.4", "--metrica", "crecimiento_ventas_5a", "--ventas-musd", "3500"]) == 0
    r = json.loads(capsys.readouterr().out)
    assert r["clase"] == "2000-5000" and r["bandera"] == "requiere_evidencia_excepcional"
    ing = crecer(3.5 * MM, 0.08, 8)
    (tmp_path / "dp.json").write_text(json.dumps(datapack(ingresos=ing, beneficio_operativo=[i * .2 for i in ing])), encoding="utf-8")
    (tmp_path / "dr.json").write_text(json.dumps({"margen_operativo": 0.5}), encoding="utf-8")
    assert tasas_base.main(["--datapack", str(tmp_path / "dp.json"), "--drivers", str(tmp_path / "dr.json"),
                            "--salida", str(tmp_path / "tb.json")]) == 0
    assert json.loads((tmp_path / "tb.json").read_text(encoding="utf-8"))["drivers"]["margen_operativo"]["estado"] == "ok"

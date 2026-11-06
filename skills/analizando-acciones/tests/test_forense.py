import json

import pytest

import comun
import forense
from datos import edgar
from dp_sintetico import cifra_banca, crecer, datapack

CFG = comun.cargar_config()["forense"]


def sano(**kw):
    """Datapack con calidad contable correcta; `kw` sobrescribe campos."""
    ing = crecer(1000.0, 0.05, 6)
    campos = dict(ingresos=ing, beneficio_neto=[i * 0.10 for i in ing], fco=[i * 0.12 for i in ing],
                  activos_totales=[i * 1.5 for i in ing], cxc=[i * 0.15 for i in ing], inventario=[i * 0.10 for i in ing],
                  sbc=[i * 0.02 for i in ing], acciones_diluidas=[100.0] * 6, goodwill=[i * 0.05 for i in ing],
                  beneficio_operativo=[i * 0.15 for i in ing], gasto_intereses=[10.0] * 6)
    campos.update(kw)
    return datapack(**campos)


def graves(res):
    return {b["metrica"] for b in res["banderas"]}


def test_empresa_sana_sin_banderas():
    r = forense.calcular(sano(), "general", CFG)
    assert r["banderas"] == [] and r["resumen"]["graves"] == 0
    assert all(m["estado"] == "evaluada" for m in r["metricas"].values())
    assert r["metricas"]["fco_beneficio_neto"]["valor"] == pytest.approx(1.2)
    assert r["metricas"]["sbc_ingresos"]["valor"] == pytest.approx(0.02)
    assert r["metricas"]["cobertura_intereses"]["valor"] > 10


def test_fco_sobre_beneficio_neto():
    ing = crecer(1000.0, 0.05, 6)
    r = forense.calcular(sano(fco=[i * 0.05 for i in ing]), "general", CFG)  # FCO/BN = 0,5 < 0,8
    assert graves(r) >= {"fco_beneficio_neto"}
    assert r["metricas"]["fco_beneficio_neto"]["valor"] == pytest.approx(0.5)
    sobre_umbral = forense.calcular(sano(fco=[i * 0.09 for i in ing]), "general", CFG)  # 0,9 ≥ 0,8: no es grave
    assert "fco_beneficio_neto" not in graves(sobre_umbral)


def test_fco_no_aplica_con_perdidas():
    r = forense.calcular(sano(beneficio_neto=[-50.0] * 6), "general", CFG)
    assert r["metricas"]["fco_beneficio_neto"]["estado"] == "no_aplica"


def test_devengos():
    ing = crecer(1000.0, 0.05, 6)
    r = forense.calcular(sano(beneficio_neto=[i * 0.30 for i in ing], fco=[i * 0.05 for i in ing]), "general", CFG)
    # (BN − FCO)/activos medios = 0,25·ing / (1,5·ing medio) ≈ 16 %
    assert "devengos" in graves(r) and r["metricas"]["devengos"]["valor"] > 0.10


def test_cuentas_a_cobrar_dos_anios_seguidos():
    ing = [1000.0, 1050.0, 1100.0, 1150.0, 1200.0, 1250.0]
    cxc = [100.0, 105.0, 110.0, 115.0, 150.0, 200.0]  # +30 % y +33 % frente a +4 % de ingresos
    r = forense.calcular(sano(ingresos=ing, cxc=cxc), "general", CFG)
    assert "cxc_vs_ingresos" in graves(r)
    un_solo_anio = [100.0, 105.0, 110.0, 115.0, 150.0, 155.0]  # solo el penúltimo salto
    r = forense.calcular(sano(ingresos=ing, cxc=un_solo_anio), "general", CFG)
    assert "cxc_vs_ingresos" not in graves(r)


def test_inventario_y_empresa_sin_inventario():
    ing = [1000.0, 1050.0, 1100.0, 1150.0, 1200.0, 1250.0]
    r = forense.calcular(sano(ingresos=ing, inventario=[50.0, 55.0, 70.0, 90.0, 120.0, 160.0]), "general", CFG)
    assert "inventario_vs_ingresos" in graves(r)
    dp = sano()
    del dp["fundamentales"]["inventario"]
    assert forense.calcular(dp, "general", CFG)["metricas"]["inventario_vs_ingresos"]["estado"] == "no_aplica"


def test_sbc_y_dilucion():
    ing = crecer(1000.0, 0.05, 6)
    r = forense.calcular(sano(sbc=[i * 0.12 for i in ing], acciones_diluidas=crecer(100.0, 0.05, 6)), "general", CFG)
    assert {"sbc_ingresos", "dilucion"} <= graves(r)
    assert r["metricas"]["dilucion"]["valor"] == pytest.approx(0.05)
    recompras = forense.calcular(sano(acciones_diluidas=crecer(100.0, -0.02, 6)), "general", CFG)
    assert "dilucion" not in graves(recompras) and recompras["metricas"]["dilucion"]["valor"] < 0


def test_goodwill_alto_y_creciente():
    ing = crecer(1000.0, 0.05, 6)
    act = [i * 1.5 for i in ing]
    r = forense.calcular(sano(goodwill=[a * f for a, f in zip(act, [.30, .33, .36, .39, .42, .45])]), "general", CFG)
    assert "goodwill_activos" in graves(r)
    alto_pero_cae = forense.calcular(sano(goodwill=[a * f for a, f in zip(act, [.50, .49, .48, .47, .46, .45])]), "general", CFG)
    assert "goodwill_activos" not in graves(alto_pero_cae)


def test_cobertura_de_intereses():
    ing = crecer(1000.0, 0.05, 6)
    r = forense.calcular(sano(gasto_intereses=[i * 0.10 for i in ing]), "general", CFG)  # EBIT/int = 1,5
    assert "cobertura_intereses" in graves(r) and r["metricas"]["cobertura_intereses"]["valor"] == pytest.approx(1.5)
    sin_deuda = forense.calcular(sano(gasto_intereses=[0.0] * 6), "general", CFG)
    assert sin_deuda["metricas"]["cobertura_intereses"]["estado"] == "no_aplica"


def test_datos_ausentes_o_desactualizados_son_sin_datos():
    dp = sano()
    del dp["fundamentales"]["sbc"]
    dp["fundamentales"]["goodwill"]["desactualizada"] = True
    dp["fundamentales"]["goodwill"]["ultimo_periodo"] = "2017-12-31"
    r = forense.calcular(dp, "general", CFG)
    assert r["metricas"]["sbc_ingresos"]["estado"] == "sin_datos"
    assert r["metricas"]["goodwill_activos"]["estado"] == "sin_datos"
    assert {"sbc_ingresos", "goodwill_activos"} <= set(r["resumen"]["sin_datos"])
    corto = forense.calcular(sano(acciones_diluidas=[100.0, 100.0]), "general", CFG)
    assert corto["metricas"]["dilucion"]["estado"] == "sin_datos"


def test_nunca_genera_banderas_invalidantes():
    ing = crecer(1000.0, 0.05, 6)
    r = forense.calcular(sano(fco=[i * 0.01 for i in ing], sbc=[i * 0.3 for i in ing]), "general", CFG)
    assert r["banderas"] and {b["nivel"] for b in r["banderas"]} == {"grave"}


# ---------------------------------------------------------------- bancos

def test_banco_omite_metricas_industriales_y_pide_datos_bancarios():
    r = forense.calcular(sano(), "banco_credito", CFG)
    for n in forense.NO_BANCOS:
        assert r["metricas"][n]["estado"] == "no_aplica"
    for n in ("morosidad", "coste_riesgo", "cet1"):
        assert r["metricas"][n]["estado"] == "sin_datos"
    assert "sbc_ingresos" in r["metricas"] and r["metricas"]["sbc_ingresos"]["estado"] == "evaluada"


def test_banco_tendencia_adversa_y_cet1():
    dp = sano()
    dp["banca"] = {"morosidad": cifra_banca([0.040, 0.042, 0.047]),          # sube dos años seguidos
                   "coste_riesgo": cifra_banca([0.050, 0.045, 0.046]),       # no sube dos años seguidos
                   "cet1": cifra_banca([0.121]), "cet1_requisito": cifra_banca([0.115])}  # 12,1 % < 11,5 % + 1 pp
    r = forense.calcular(dp, "banco_credito", CFG)
    assert graves(r) == {"morosidad", "cet1"}
    dp["banca"]["cet1"] = cifra_banca([0.130])
    assert "cet1" not in graves(forense.calcular(dp, "banco_credito", CFG))
    dp["banca"]["cet1"] = comun.desconocido("not_covered")
    assert forense.calcular(dp, "banco_credito", CFG)["metricas"]["cet1"]["estado"] == "sin_datos"


# ---------------------------------------------------------------- datos reales (fixtures)

def datapack_desde_fixture(fixture, nombre, sic):
    url = "https://data.sec.gov/api/xbrl/companyfacts/x.json"
    tax, fund, _ = edgar.extraer_fundamentales(fixture(f"companyfacts_{nombre}.json"), 10, url, "2026-11-06T00:00:00Z", sic)
    return {"ticker": nombre.upper(), "fundamentales": fund}


def test_aapl_real_sin_banderas(fixture):
    r = forense.calcular(datapack_desde_fixture(fixture, "aapl", 3571), "general", CFG)
    assert r["banderas"] == []
    assert r["metricas"]["fco_beneficio_neto"]["estado"] == "evaluada"
    assert r["metricas"]["sbc_ingresos"]["valor"] == pytest.approx(0.029, abs=0.005)
    assert r["metricas"]["dilucion"]["valor"] < 0  # recompras


def test_nu_real_ruta_banco(fixture):
    r = forense.calcular(datapack_desde_fixture(fixture, "nu", 6199), "banco_credito", CFG)
    assert r["metricas"]["fco_beneficio_neto"]["estado"] == "no_aplica"
    assert r["metricas"]["sbc_ingresos"]["estado"] == "evaluada"
    assert r["metricas"]["cet1"]["estado"] == "sin_datos"


def test_cli(tmp_path):
    (tmp_path / "dp.json").write_text(json.dumps(sano()), encoding="utf-8")
    (tmp_path / "router.json").write_text(json.dumps({"ruta": "banco_credito"}), encoding="utf-8")
    assert forense.main(["--datapack", str(tmp_path / "dp.json"), "--router", str(tmp_path / "router.json"),
                         "--salida", str(tmp_path / "f.json")]) == 0
    assert json.loads((tmp_path / "f.json").read_text(encoding="utf-8"))["ruta"] == "banco_credito"


def test_capital_total_si_no_se_publica_cet1():
    dp = sano()
    dp["banca"] = {"capital_total": cifra_banca([0.112]), "capital_total_requisito": cifra_banca([0.105])}
    m = forense.calcular(dp, "banco_credito", CFG)["metricas"]["cet1"]
    assert m["estado"] == "evaluada" and m["grave"] is True and m["detalle"].startswith("Capital total")

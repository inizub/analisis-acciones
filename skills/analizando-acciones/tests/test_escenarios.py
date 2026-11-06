import copy
import json
import math

import pytest
from scipy import stats

import comun
from conftest import DIR_FIXTURES
from motor import escenarios
from motor.comun_motor import ErrorMotor

ANALISTA = json.loads((DIR_FIXTURES / "ejemplos" / "analista_A.json").read_text(encoding="utf-8"))
BASE = {"ruta": "general", "precio0": 40.0, "acciones": 50.0, "ingresos0": 1000.0, "tasa_impuestos": 0.25,
        "wacc": 0.08, "rf": 0.04, "g_terminal": 0.03, "deuda": 300.0, "caja": 100.0, "ventas_capital": 2.0,
        "margen_operativo": 0.20, "crecimiento": 0.08, "rendimiento_accionista": 0.0, "vol_rel": 0.25,
        "vol_abs": 0.30, "rf_eur": 0.025, "erp_vwce": 0.0423}


def cfg(sims=100_000):
    c = comun.cargar_config()
    c["escenarios"]["mc_sims"] = sims
    return c


def test_determinista_con_semilla():
    a = escenarios.ejecutar(ANALISTA, {"base": BASE}, cfg=cfg(20_000))
    b = escenarios.ejecutar(ANALISTA, {"base": BASE}, cfg=cfg(20_000))
    assert a == b
    c2 = cfg(20_000)
    c2["escenarios"]["semilla"] = 7
    assert escenarios.ejecutar(ANALISTA, {"base": BASE}, cfg=c2)["probabilidades"] != a["probabilidades"]


def test_salida_y_coherencia():
    r = escenarios.ejecutar(ANALISTA, {"base": BASE}, cfg=cfg(50_000))
    p = r["probabilidades"]
    assert set(p) == {"E0", "E1", "E2", "E3", "E4"}
    assert all(0 <= v <= 1 for v in p.values())
    v = {e["nombre"]: e["valor"] for e in r["escenarios"]}
    assert v["bajista"] < v["base"] < v["alcista"]
    lo, med, hi = r["rel_12m_p5_p50_p95"]
    assert lo < med < hi
    assert r["perdida_escenario_bajista"] == pytest.approx(max(0, 1 - v["bajista"] / 40))
    # E4: base y alcista tienen métrica ≥ valor base (0,08) → 0,5 + 0,25
    assert p["E4"] == pytest.approx(0.75)
    assert r["metodo"] == "dcf_fcff" and r["analista"] == "A"


def todos_en_p0(analista, base):
    """Fija los drivers de los tres escenarios para que todos valgan exactamente P0."""
    from scipy.optimize import brentq

    from motor.reverse_dcf import valor_dcf
    a = copy.deepcopy(analista)
    m = 0.20
    g = brentq(lambda x: valor_dcf(dict(base, margen_operativo=m), crecimiento=x) - base["precio0"], -0.2, 0.6)
    for e in a["escenarios"]:
        e["drivers"]["crecimiento_ingresos"]["valor"] = g
        e["drivers"]["margen_operativo"]["valor"] = m
    return a


def test_todos_los_escenarios_en_p0_y_benchmark_nulo_da_05():
    b = dict(BASE, rf_eur=0.0, erp_vwce=0.0)
    r = escenarios.ejecutar(todos_en_p0(ANALISTA, b), {"base": b}, cfg=cfg())
    assert all(e["valor_sobre_p0"] == pytest.approx(1.0, abs=1e-9) for e in r["escenarios"])
    for ev in ("E0", "E1", "E2"):
        assert r["probabilidades"][ev] == pytest.approx(0.5, abs=0.005)
    assert r["exceso_anual_esperado_pp"] == pytest.approx(0.0, abs=1e-9)


def test_todos_en_p0_con_benchmark_positivo_baja_de_05_lo_esperado():
    """p(E1) ≈ 0,5 menos el efecto de la rentabilidad esperada de VWCE: P(σ·Z > ln(1 + r_vw)), Z ~ t₄ escalada."""
    r = escenarios.ejecutar(todos_en_p0(ANALISTA, BASE), {"base": BASE}, cfg=cfg())
    r_vw = BASE["rf_eur"] + BASE["erp_vwce"]
    nu = 4
    teorico = {ev: 1 - stats.t.cdf(math.log1p(r_vw) * h / (BASE["vol_rel"] * math.sqrt(h)) / math.sqrt((nu - 2) / nu), nu)
               for ev, h in escenarios.HORIZONTES.items()}
    for ev in ("E0", "E1", "E2"):
        assert r["probabilidades"][ev] < 0.5
        assert r["probabilidades"][ev] == pytest.approx(teorico[ev], abs=0.005)
    assert r["exceso_anual_esperado_pp"] == pytest.approx(-100 * r_vw)


def test_e3_aumenta_con_la_volatilidad():
    a = todos_en_p0(ANALISTA, BASE)
    baja = escenarios.ejecutar(a, {"base": dict(BASE, vol_abs=0.15)}, cfg=cfg(40_000))["probabilidades"]["E3"]
    alta = escenarios.ejecutar(a, {"base": dict(BASE, vol_abs=0.60)}, cfg=cfg(40_000))["probabilidades"]["E3"]
    assert baja < 0.02 < alta


def test_ajustes():
    aj = json.loads((DIR_FIXTURES / "ejemplos" / "ajustes.json").read_text(encoding="utf-8"))
    sin = escenarios.ejecutar(ANALISTA, {"base": BASE}, cfg=cfg(20_000))
    con = escenarios.ejecutar(ANALISTA, {"base": BASE}, aj, cfg=cfg(20_000))
    assert con["ajustes_aplicados"] == [{"escenario": "alcista", "driver": "crecimiento_ingresos", "de": 0.14, "a": 0.11,
                                         "objecion_ref": "O1"}]
    va = {e["nombre"]: e["valor"] for e in sin["escenarios"]}
    vb = {e["nombre"]: e["valor"] for e in con["escenarios"]}
    assert vb["alcista"] < va["alcista"] and vb["base"] == va["base"]
    otro = copy.deepcopy(aj)
    otro["ajustes"][0]["analista"] = "B"
    assert escenarios.ejecutar(ANALISTA, {"base": BASE}, otro, cfg=cfg(20_000))["ajustes_aplicados"] == []
    malo = copy.deepcopy(aj)
    malo["ajustes"][0]["valor_anterior"] = 0.99
    with pytest.raises(ErrorMotor, match="valor_anterior"):
        escenarios.ejecutar(ANALISTA, {"base": BASE}, malo, cfg=cfg(20_000))


def test_ruta_distinta_falla():
    with pytest.raises(ErrorMotor, match="ruta"):
        escenarios.ejecutar(ANALISTA, {"base": dict(BASE, ruta="banco_credito")}, cfg=cfg(1000))


def test_valorar_banco_y_crecimiento_perdidas():
    base = {"banco": {"patrimonio0": 1000.0, "ke": 0.10, "payout": 0.3, "acciones": 100.0, "anios": 5, "g_estable": 0.03}}
    v = escenarios.valorar("banco_credito", base, {"roe": {"valor": 0.10}})
    assert v["valor"] == pytest.approx(10.0) and v["metodo"] == "excess_return"
    v2 = escenarios.valorar("banco_credito", base, {"roe": {"valor": 0.15}, "roe_estable": {"valor": 0.12}})
    assert v2["valor"] > 10
    general = escenarios.valorar("general", BASE, {"crecimiento_ingresos": {"valor": 0.1}})
    fracaso = escenarios.valorar("crecimiento_perdidas", BASE, {"crecimiento_ingresos": {"valor": 0.1},
                                                                "probabilidad_fracaso": {"valor": 0.4}})
    assert fracaso["valor"] == pytest.approx(0.6 * general["valor"])
    with pytest.raises(ErrorMotor, match="roe"):
        escenarios.valorar("banco_credito", base, {})


def test_valorar_ciclica_y_holding():
    b = dict(BASE, roc=0.10)
    v = escenarios.valorar("ciclica", b, {"margen_operativo": {"valor": 0.10}})
    assert v["metodo"] == "dcf_normalizado" and v["valor"] > 0
    s = {"sotp": {"segmentos": [{"nombre": "A", "metodo": "multiplo", "metrica": 100, "multiplo": 10}], "deuda": 0,
                  "caja": 0, "coste_holding_anual": 0, "tasa_descuento": 0.1, "acciones": 10}}
    assert escenarios.valorar("holding", s, {"factor_multiplos": {"valor": 0.8}})["valor"] == pytest.approx(80)


def test_cli(tmp_path):
    (tmp_path / "a.json").write_text(json.dumps(ANALISTA), encoding="utf-8")
    (tmp_path / "m.json").write_text(json.dumps({"base": BASE}), encoding="utf-8")
    assert escenarios.main(["--analista", str(tmp_path / "a.json"), "--motor", str(tmp_path / "m.json"),
                            "--salida", str(tmp_path / "s.json")]) == 0
    s = json.loads((tmp_path / "s.json").read_text(encoding="utf-8"))
    assert s["parametros"]["semilla"] == 42 and s["parametros"]["mc_sims"] == 100_000
    (tmp_path / "m.json").write_text(json.dumps({"base": dict(BASE, ruta="holding")}), encoding="utf-8")
    assert escenarios.main(["--analista", str(tmp_path / "a.json"), "--motor", str(tmp_path / "m.json")]) == 1


def test_roe_estable_solo_con_moat_documentado():
    base = {"banco": {"patrimonio0": 1000.0, "ke": 0.10, "payout": 0.3, "acciones": 100.0, "anios": 5, "g_estable": 0.03}}
    drivers = {"roe": {"valor": 0.15}, "roe_estable": {"valor": 0.14}}
    sin_moat = escenarios.valorar("banco_credito", base, drivers)
    assert sin_moat["drivers_usados"]["roe_estable"] == pytest.approx(0.10)
    assert "ignorado" in sin_moat["drivers_usados"]["roe_estable_propuesto"]
    con_moat = escenarios.valorar("banco_credito", dict(base, moat_documentado=True), drivers)
    assert con_moat["drivers_usados"]["roe_estable"] == pytest.approx(0.14)
    assert con_moat["valor"] > sin_moat["valor"]

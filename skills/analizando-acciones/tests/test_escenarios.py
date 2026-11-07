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


def _p_neutral_teorica(h, s_rel):
    """p(R_h > 0) con R_h ≈ N(−σ²h/2, σ²h): la suma de pasos t mensuales se aproxima a una normal."""
    return 1 - stats.norm.cdf(0.5 * s_rel * math.sqrt(h))


def test_todos_en_p0_da_la_tasa_base_por_asimetria_sea_cual_sea_vwce():
    """Una acción a su valor rinde en media como VWCE: p(batir) = P(N(−σ²h/2, σ²h) > 0) < 0,5, sin depender de r_vw."""
    for b in (dict(BASE, rf_eur=0.0, erp_vwce=0.0), BASE):
        r = escenarios.ejecutar(todos_en_p0(ANALISTA, b), {"base": b}, cfg=cfg())
        assert all(e["valor_sobre_p0"] == pytest.approx(1.0, abs=1e-9) for e in r["escenarios"])
        for ev, h in escenarios.HORIZONTES.items():
            assert r["probabilidades"][ev] == pytest.approx(_p_neutral_teorica(h, b["vol_rel"]), abs=0.01)
        assert r["exceso_anual_esperado_pp"] == pytest.approx(0.0, abs=1e-9)
    assert r["probabilidades"]["E1"] == pytest.approx(0.45, abs=0.01)       # σ_rel = 25 % → la tasa base empírica


def test_e3_aumenta_con_la_volatilidad():
    a = todos_en_p0(ANALISTA, BASE)
    baja = escenarios.ejecutar(a, {"base": dict(BASE, vol_abs=0.26)}, cfg=cfg(40_000))["probabilidades"]["E3"]
    alta = escenarios.ejecutar(a, {"base": dict(BASE, vol_abs=0.60)}, cfg=cfg(40_000))["probabilidades"]["E3"]
    assert baja < alta and baja < 0.15 and alta > 0.25


# ---------------------------------------------------------------- coherencia entre eventos

@pytest.mark.parametrize("precio", [10.0, 25.0, 40.0, 70.0, 160.0])
def test_eventos_y_percentiles_salen_de_la_misma_distribucion(precio):
    r = escenarios.ejecutar(ANALISTA, {"base": dict(BASE, precio0=precio)}, cfg=cfg(50_000))
    p, (p5, p50, p95) = r["probabilidades"], r["rel_12m_p5_p50_p95"]
    # p(E1) es la fracción de rel_12m > 0: los percentiles no pueden contradecirla
    if p95 < 0:
        assert p["E1"] < 0.05
    if p5 > 0:
        assert p["E1"] > 0.95
    assert (p50 > 0) == (p["E1"] > 0.5)
    # batir a VWCE y caer ≥ 30 % no pueden ser a la vez muy probables
    assert p["E1"] + p["E3"] <= 1.05
    # el exceso esperado tiene el signo del valor frente al precio
    v = sum(e["p"] * e["valor_sobre_p0"] for e in r["escenarios"])
    if v > 1.3:
        assert r["exceso_anual_esperado_pp"] > 0 and p["E1"] > 0.45
    if v < 0.7:
        assert r["exceso_anual_esperado_pp"] < 0 and p["E1"] < 0.45


def test_cuanto_mas_caro_menos_p_de_batir_y_mas_p_de_caer():
    ps = [escenarios.ejecutar(ANALISTA, {"base": dict(BASE, precio0=x)}, cfg=cfg(30_000))["probabilidades"]
          for x in (20.0, 40.0, 80.0, 160.0)]
    e1, e3 = [q["E1"] for q in ps], [q["E3"] for q in ps]
    assert e1 == sorted(e1, reverse=True) and e3 == sorted(e3)


def test_la_mezcla_con_el_neutral_modera_los_extremos():
    """Aun con todos los escenarios a 1/4 del precio, el peso del neutral (1 − k) impide certezas."""
    r = escenarios.ejecutar(ANALISTA, {"base": dict(BASE, precio0=400.0)}, cfg=cfg(30_000))
    assert r["probabilidades_modelo"]["E3"] > r["probabilidades"]["E3"] > r["probabilidades_neutral"]["E3"]
    assert r["probabilidades"]["E3"] < 0.6 and r["probabilidades"]["E1"] > 0.2


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


# ---------------------------------------------------------------- ajustes de la base y cordura

def _ajuste_base(valor_anterior, valor_nuevo, escenario="todos", analista="todos"):
    return {"ticker": "XYZ", "fecha_analisis": "2026-11-06", "ajustes": [{
        "analista": analista, "driver": "ingresos0", "escenario": escenario, "valor_anterior": valor_anterior,
        "valor_nuevo": valor_nuevo, "objecion_ref": "O1", "motivo": "La base debe ser de los últimos doce meses"}]}


def test_el_juez_puede_ajustar_ingresos0_de_la_base():
    sin = escenarios.ejecutar(ANALISTA, {"base": BASE}, cfg=cfg(20_000))
    con = escenarios.ejecutar(ANALISTA, {"base": BASE}, _ajuste_base(1000.0, 2000.0), cfg=cfg(20_000))
    assert con["ajustes_aplicados"] == [{"escenario": "todos", "driver": "ingresos0", "de": 1000.0, "a": 2000.0,
                                         "objecion_ref": "O1"}]
    assert all(c["valor"] > s["valor"] for c, s in zip(con["escenarios"], sin["escenarios"]))


def test_ajuste_de_la_base_valida_valor_anterior_y_escenario():
    with pytest.raises(ErrorMotor, match="valor_anterior"):
        escenarios.ejecutar(ANALISTA, {"base": BASE}, _ajuste_base(999.0, 2000.0), cfg=cfg(1000))
    with pytest.raises(ErrorMotor, match="solo admite escenario 'todos'"):
        escenarios.ejecutar(ANALISTA, {"base": BASE}, _ajuste_base(1000.0, 2000.0, escenario="base"), cfg=cfg(1000))
    with pytest.raises(ErrorMotor, match="positivo"):
        escenarios.ejecutar(ANALISTA, {"base": BASE}, _ajuste_base(1000.0, -5.0), cfg=cfg(1000))


def test_cordura_fiable_si_el_precio_esta_en_el_rango():
    r = escenarios.ejecutar(ANALISTA, {"base": BASE}, cfg=cfg(5_000))
    assert r["cordura"]["fiable"] is True and r["cordura"]["motivo"] == ""


def test_cordura_no_fiable_si_todos_los_escenarios_valen_muy_poco_o_muchisimo():
    c = cfg(5_000)
    barato = escenarios.ejecutar(ANALISTA, {"base": {**BASE, "precio0": 4000.0}}, cfg=c)     # precio ≫ valores
    assert barato["cordura"]["fiable"] is False and "más alto vale" in barato["cordura"]["motivo"]
    caro = escenarios.ejecutar(ANALISTA, {"base": {**BASE, "precio0": 0.5}}, cfg=c)           # valores ≫ precio
    assert caro["cordura"]["fiable"] is False and "más bajo vale" in caro["cordura"]["motivo"]
    # el umbral sale de config.yaml
    c["cordura"]["factor_precio_fuera_de_rango"] = 1e6
    assert escenarios.ejecutar(ANALISTA, {"base": {**BASE, "precio0": 4000.0}}, cfg=c)["cordura"]["fiable"] is True


# ---------------------------------------------------------------- cíclica con crecimiento

BASE_CICLICA = {**BASE, "ruta": "ciclica", "roc": 0.15, "margen_inicial": 0.60, "anios_convergencia_margen": 5,
                "margen_operativo": 0.38}


def test_ciclica_sin_crecimiento_usa_el_modo_estable_y_con_crecimiento_el_dcf_de_10_anios():
    estable = escenarios.valorar("ciclica", BASE_CICLICA, {"margen_operativo": {"valor": 0.38}})
    crece = escenarios.valorar("ciclica", BASE_CICLICA, {"margen_operativo": {"valor": 0.38},
                                                         "crecimiento_ingresos": {"valor": 0.25}})
    assert estable["metodo"] == "dcf_normalizado" and "nota" not in estable["drivers_usados"]
    assert "dcf de 10 años" in crece["drivers_usados"]["nota"]
    assert crece["valor"] > 2 * estable["valor"]            # 5 años de +25 % pesan mucho frente a ingresos planos


def test_ciclica_con_crecimiento_respeta_margen_y_crecimiento():
    d = {"margen_operativo": {"valor": 0.38}}
    v = lambda g, m: escenarios.valorar("ciclica", BASE_CICLICA, {"margen_operativo": {"valor": m},
                                                                 "crecimiento_ingresos": {"valor": g}})["valor"]
    assert v(0.10, 0.38) < v(0.25, 0.38) and v(0.25, 0.30) < v(0.25, 0.50)


def test_el_juez_no_puede_sustituir_los_doce_meses_reportados_por_una_estimacion():
    base = {**BASE, "base_ingresos": {"metodo": "ttm", "fecha_fin": "2026-07-26"}}
    with pytest.raises(ErrorMotor, match="doce meses reportados"):
        escenarios.ejecutar(ANALISTA, {"base": base}, _ajuste_base(1000.0, 1500.0), cfg=cfg(1000))
    base["base_ingresos"]["metodo"] = "anual"
    r = escenarios.ejecutar(ANALISTA, {"base": base}, _ajuste_base(1000.0, 1500.0), cfg=cfg(1000))
    assert r["ajustes_aplicados"][0]["a"] == 1500.0


def test_el_juez_puede_ajustar_el_tipo_impositivo():
    aj = {"ticker": "XYZ", "fecha_analisis": "2026-11-06", "ajustes": [{
        "analista": "todos", "driver": "tasa_impuestos", "escenario": "todos", "valor_anterior": 0.25,
        "valor_nuevo": 0.17, "objecion_ref": "O4", "motivo": "El guidance de la empresa fija un tipo del 16-18 %"}]}
    sin = escenarios.ejecutar(ANALISTA, {"base": BASE}, cfg=cfg(1000))
    con = escenarios.ejecutar(ANALISTA, {"base": BASE}, aj, cfg=cfg(1000))
    assert con["ajustes_aplicados"][0]["driver"] == "tasa_impuestos"
    assert all(c["valor"] > s["valor"] for c, s in zip(con["escenarios"], sin["escenarios"]))
    aj["ajustes"][0]["valor_nuevo"] = 17
    with pytest.raises(ErrorMotor, match="fracción"):
        escenarios.ejecutar(ANALISTA, {"base": BASE}, aj, cfg=cfg(1000))

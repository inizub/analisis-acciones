"""Tests del motor de valoración, con tests dorados a partir de las fuentes de A14."""
import copy
import json

import pytest

from motor import ddm_fcfe, dcf, excess_return, normalizado, reverse_dcf, rnpv, sotp
from motor.comun_motor import ErrorMotor, crecimiento_con_desvanecimiento, serie_anual, trayectoria


# ================================================================ dorados

def test_dorado_goldman_sachs_excess_return():
    """Damodaran, Investment Valuation 3.ª ed., cap. 21, ilustración 21.4 (mayo de 2011).
    ROE = 8.354 / 71.674 = 11,66 %; Ke = 3,5 % + 1,2 × 5 % = 9,5 %; payout 10 %; patrimonio 78.228 M$;
    5 años; después ROE = Ke (sin valor añadido); 517,735 M de acciones → 166,24 $/acción.
    (El texto da 7.880 como VP de los excesos, pero su tabla suma 7.840, que es lo que lleva a 86.068 y a 166,24.)"""
    r = excess_return.valor_excess_return(patrimonio0=78_228, roe=8_354 / 71_674, ke=0.095, payout=0.10,
                                          acciones=517.735, anios=5)
    assert r["valor_por_accion"] == pytest.approx(166.24, abs=0.01)
    assert r["puente"]["vp_excesos"] == pytest.approx(7_840, abs=1)
    assert r["puente"]["vp_valor_terminal"] == 0
    f = r["flujos"]
    assert [round(x["beneficio_neto"]) for x in f] == [9_118, 10_074, 11_131, 12_299, 13_589]
    assert [round(x["vp"]) for x in f] == [1_540, 1_554, 1_568, 1_582, 1_596]
    assert round(f[-1]["patrimonio_inicial"]) == 116_588


ABN = dict(bpa0=1.60, payout=0.375, roe=0.1556, ke=0.0502 + 0.95 * 0.04, anios=5,
           g_estable=0.05, ke_estable=0.0502 + 1.00 * 0.04, roe_estable=0.15)


def test_dorado_abn_amro_ddm_con_valor_terminal_de_la_fuente():
    """Damodaran, 'Valuing Financial Service Firms' (finsvce.pdf), diapositiva 16: ABN Amro = 30,87 €/acción.
    BPA 1,60 €; payout 37,5 %; g = 62,5 % × 15,56 % = 9,73 %; Ke = 5,02 % + 0,95 × 4 % = 8,82 %; 5 años.
    La diapositiva muestra un valor terminal de 42,41 € que no se deduce de sus propias entradas estables
    (con ellas sale 44,31 €, ver el test siguiente). Este test usa el 42,41 € de la fuente y comprueba que el
    descuento de dividendos y del valor terminal reproduce los 30,87 €."""
    r = ddm_fcfe.ddm_dos_etapas(**ABN, valor_terminal=42.41)
    assert r["supuestos"]["g"] == pytest.approx(0.625 * 0.1556)  # 9,725 %, que la fuente redondea a 9,73 %
    assert [round(x["dpa"], 2) for x in r["flujos"]] == [0.66, 0.72, 0.79, 0.87, 0.95]
    assert r["valor_por_accion"] == pytest.approx(30.87, abs=0.01)


def test_abn_amro_ddm_recalculo_propio():
    """Con las entradas estables de la diapositiva (g 5 %, ROE 15 %, payout 1 − 5/15, Ke 9,02 %):
    BPA₆ = 1,60 × 1,09725⁵ × 1,05 = 2,672 €; valor terminal = 2,672 × ⅔ / (0,0902 − 0,05) = 44,31 €;
    VP dividendos 3,08 € + 44,31 / 1,0882⁵ = 29,04 € → 32,11 €/acción."""
    r = ddm_fcfe.ddm_dos_etapas(**ABN)
    assert r["supuestos"]["bpa_siguiente"] == pytest.approx(2.672, abs=0.0005)
    assert r["supuestos"]["payout_estable"] == pytest.approx(2 / 3)
    assert r["puente"]["valor_terminal"] == pytest.approx(44.31, abs=0.005)
    assert r["puente"]["vp_dividendos"] == pytest.approx(3.08, abs=0.005)
    assert r["valor_por_accion"] == pytest.approx(32.11, abs=0.01)


BASE_DCF = dict(ingresos0=1_000.0, margen_operativo=0.20, ventas_capital=2.0, tasa_impuestos=0.25, wacc=0.08,
                g_terminal=0.03, rf=0.04, deuda=300.0, caja=100.0, acciones=50.0, crecimiento=0.12)


@pytest.mark.parametrize("g_real", [0.12, -0.05, 0.35])
def test_dorado_reverse_dcf_recupera_el_crecimiento(g_real):
    precio = reverse_dcf.valor_dcf(BASE_DCF, crecimiento=g_real)
    r = reverse_dcf.resolver_crecimiento(precio, BASE_DCF)
    assert not r["sin_raiz"]
    assert r["valor"] == pytest.approx(g_real, abs=1e-8)


def test_reverse_dcf_recupera_el_margen():
    precio = reverse_dcf.valor_dcf(BASE_DCF, margen=0.27)
    r = reverse_dcf.resolver_margen(precio, BASE_DCF)
    assert r["valor"] == pytest.approx(0.27, abs=1e-8)


def test_reverse_dcf_anios_ventaja():
    b = dict(BASE_DCF, crecimiento=0.15)
    p7 = reverse_dcf.valor_dcf(b, crecimiento=[0.15] * 7, anios=7)
    r = reverse_dcf.resolver_anios_ventaja(p7, b)
    assert r["valor"] == 7 and not r["sin_raiz"]
    r = reverse_dcf.resolver_anios_ventaja(1e9, b)
    assert r["sin_raiz"] and r["valor"] is None


def test_reverse_dcf_sin_raiz():
    r = reverse_dcf.resolver_crecimiento(1e7, BASE_DCF)
    assert r["sin_raiz"] and r["valor"] is None


def test_reverse_dcf_banco_roe():
    b = dict(patrimonio0=1_000.0, ke=0.10, payout=0.4, acciones=100.0, anios=5, g_estable=0.03)
    from motor.excess_return import valor_excess_return
    precio = valor_excess_return(1_000.0, 0.14, 0.10, 0.4, 100.0, 5, roe_estable=0.14, g_estable=0.03)["valor_por_accion"]
    r = reverse_dcf.resolver(precio, {"banco": b}, "banco_credito", {"roe": {"media": 0.10, "desv": 0.05}})
    assert r["principal"]["valor"] == pytest.approx(0.14, abs=1e-8)
    assert r["principal"]["percentil"] == pytest.approx(78.81, abs=0.01)
    assert r["principal"]["z"] == pytest.approx(0.8)


def test_reverse_dcf_resolver_general_con_percentiles():
    precio = reverse_dcf.valor_dcf(BASE_DCF, crecimiento=0.10)
    r = reverse_dcf.resolver(precio, BASE_DCF, "general", {"crecimiento_ingresos": {"media": 0.069, "desv": 0.111}})
    assert [x["driver"] for x in r["resultados"]] == ["crecimiento_ingresos", "margen_operativo", "anios_ventaja"]
    assert r["principal"]["valor"] == pytest.approx(0.10, abs=1e-8)
    assert 50 < r["principal"]["percentil"] < 70
    assert r["sin_raiz"] is False


# ================================================================ DCF

def test_dcf_crecimiento_cero_y_sin_reinversion_es_perpetuidad():
    """Con g = 0 todos los años y g_terminal = 0, el valor operativo = NOPAT / WACC."""
    r = dcf.dcf_fcff(ingresos0=1000, crecimiento=0.0, margen_operativo=0.2, ventas_capital=2, tasa_impuestos=0.25,
                     wacc=0.1, g_terminal=0.0, rf=0.04, deuda=0, caja=0, acciones=1)
    assert r["puente"]["valor_operativo"] == pytest.approx(150 / 0.1)


def test_dcf_g_terminal_mayor_que_rf_falla():
    with pytest.raises(ErrorMotor, match="Rf"):
        dcf.dcf_fcff(**dict(BASE_DCF, g_terminal=0.05))


def test_dcf_roic_terminal_solo_con_moat():
    sin = dcf.dcf_fcff(**dict(BASE_DCF, roic_terminal=0.30))
    con = dcf.dcf_fcff(**dict(BASE_DCF, roic_terminal=0.30, moat_documentado=True))
    assert sin["supuestos"]["roic_terminal"] == 0.08
    assert con["supuestos"]["roic_terminal"] == 0.30
    assert con["valor_por_accion"] > sin["valor_por_accion"]


def test_dcf_puente_cuadra():
    r = dcf.dcf_fcff(**BASE_DCF)
    p = r["puente"]
    assert p["valor_operativo"] == pytest.approx(p["vp_flujos"] + p["vp_valor_terminal"])
    assert p["valor_patrimonio"] == pytest.approx(p["valor_operativo"] + 100 - 300)
    assert r["valor_por_accion"] == pytest.approx(p["valor_patrimonio"] / 50)
    assert len(r["flujos"]) == 10
    assert r["flujos"][0]["reinversion"] == pytest.approx(120 / 2)


def test_dcf_convergencia_de_margen():
    r = dcf.dcf_fcff(**dict(BASE_DCF, margen_inicial=0.10, anios_convergencia_margen=5))
    margenes = [f["margen"] for f in r["flujos"]]
    assert margenes[:5] == pytest.approx([0.12, 0.14, 0.16, 0.18, 0.20]) and margenes[5:] == pytest.approx([0.2] * 5)


def test_wacc_y_beta():
    assert dcf.beta_reapalancada(1.0, 0.5, 0.25) == pytest.approx(1.375)
    w = dcf.wacc(rf=0.04, erp=0.05, beta_desapalancada=1.0, deuda_capital=0.5, tasa_impuestos=0.25,
                 coste_deuda_antes_impuestos=0.06, crp=0.01)
    assert w["ke"] == pytest.approx(0.04 + 1.375 * 0.05 + 0.01)
    assert w["wacc"] == pytest.approx((2 / 3) * w["ke"] + (1 / 3) * 0.045)


def test_wacc_rating_sintetico():
    tabla = [{"cobertura_min": -1e9, "rating": "D", "diferencial": 0.15},
             {"cobertura_min": 3.0, "rating": "BBB", "diferencial": 0.02},
             {"cobertura_min": 8.5, "rating": "AAA", "diferencial": 0.005}]
    assert dcf.rating_sintetico(5.0, tabla)["rating"] == "BBB"
    assert dcf.rating_sintetico(10, tabla)["rating"] == "AAA"
    assert dcf.rating_sintetico(-2, tabla)["rating"] == "D"
    w = dcf.wacc(rf=0.04, erp=0.05, beta_desapalancada=1.0, deuda_capital=0.2, tasa_impuestos=0.25,
                 cobertura=5.0, tabla_ratings=tabla)
    assert w["kd_antes_impuestos"] == pytest.approx(0.06)
    with pytest.raises(ErrorMotor):
        dcf.wacc(rf=0.04, erp=0.05, beta_desapalancada=1.0, deuda_capital=0.2, tasa_impuestos=0.25)


def test_dcf_cli(tmp_path, capsys):
    e = tmp_path / "e.json"
    e.write_text(json.dumps({"dcf": {k: v for k, v in BASE_DCF.items()}}), encoding="utf-8")
    assert dcf.main([str(e)]) == 0
    assert "valor_por_accion" in capsys.readouterr().out
    e.write_text(json.dumps({"dcf": dict(BASE_DCF, g_terminal=0.09)}), encoding="utf-8")
    assert dcf.main([str(e)]) == 1


# ================================================================ utilidades

def test_utilidades():
    assert serie_anual(0.1, 3, "x") == [0.1, 0.1, 0.1]
    assert serie_anual([0.1, 0.2], 4, "x") == [0.1, 0.2, 0.2, 0.2]
    assert trayectoria(0.0, 1.0, 4, 2) == [0.5, 1.0, 1.0, 1.0]
    assert crecimiento_con_desvanecimiento(0.2, 0.0, 10, 5) == pytest.approx([0.2] * 5 + [0.16, 0.12, 0.08, 0.04, 0.0])
    with pytest.raises(ErrorMotor):
        serie_anual(float("nan"), 2, "x")


# ================================================================ bancos

def test_excess_return_roe_igual_ke_vale_el_patrimonio():
    r = excess_return.valor_excess_return(1000, 0.10, 0.10, 0.5, 10, roe_estable=0.10, g_estable=0.03)
    assert r["valor_por_accion"] == pytest.approx(100)


def test_excess_return_terminal_coherente_con_pbv():
    """Si ROE es constante para siempre y g = (1 − payout)·ROE, el valor = P/BV teórico × patrimonio."""
    roe, ke, payout = 0.15, 0.10, 0.6
    g = (1 - payout) * roe
    r = excess_return.valor_excess_return(1000, roe, ke, payout, 1, anios=5, roe_estable=roe, g_estable=g)
    assert r["valor_por_accion"] == pytest.approx(1000 * excess_return.pbv_teorico(roe, ke, g), rel=1e-9)


def test_ddm_crecimiento_fundamental():
    assert ddm_fcfe.crecimiento_fundamental(0.375, 0.1556) == pytest.approx(0.09725)


def test_fcfe_banco():
    r = ddm_fcfe.fcfe_banco([100, 110], [1000, 1100], 0.10, 900, 0.10, 0.02, 10)
    assert [f["fcfe"] for f in r["flujos"]] == pytest.approx([90, 100])
    vt = 100 * 1.02 / 0.08
    esperado = 90 / 1.1 + 100 / 1.21 + vt / 1.21
    assert r["valor_por_accion"] == pytest.approx(esperado / 10)


# ================================================================ cíclicas

def test_margen_normalizado():
    assert normalizado.margen_normalizado([0.05, 0.1, 0.02, 0.08, 0.07, 0.09, 0.06])["margen"] == pytest.approx(0.067142857)
    r = normalizado.margen_normalizado(list(range(12)))
    assert r["anios"] == 10 and r["margen"] == pytest.approx(6.5)
    with pytest.raises(ErrorMotor):
        normalizado.margen_normalizado([0.1] * 6)


def test_valor_normalizado_calculo_a_mano():
    """EBIT = 1000 × 0,1 = 100; NOPAT = 70; reinversión = 0,02/0,10 = 20 %;
    FCFF₁ = 70 × 1,02 × 0,8 = 57,12; operativo = 57,12 / 0,06 = 952; patrimonio = 952 + 50 − 200 = 802."""
    r = normalizado.valor_normalizado(1000, 0.10, 0.30, 0.08, 0.02, 0.10, 200, 50, 10)
    assert r["puente"]["fcff_siguiente"] == pytest.approx(57.12)
    assert r["valor_por_accion"] == pytest.approx(80.2)


# ================================================================ biotech

TABLA = [
    {"area": "todas", "transicion": "I_II", "p": 0.52, "n": 4000},
    {"area": "todas", "transicion": "II_III", "p": 0.289, "n": 4000},
    {"area": "todas", "transicion": "III_NDA", "p": 0.578, "n": 2000},
    {"area": "todas", "transicion": "NDA_APROB", "p": 0.906, "n": 1000},
    {"area": "hematologia", "transicion": "II_III", "p": 0.40, "n": 300},
    {"area": "rara", "transicion": "II_III", "p": 0.60, "n": 50},
    {"area": "rara", "transicion": "NDA_APROB", "p": 0.99, "n": 500},
]


def test_probabilidad_acumulada_bio():
    p = rnpv.probabilidad_acumulada(TABLA, "oncologia", "I")
    assert p["p"] == pytest.approx(0.52 * 0.289 * 0.578 * 0.906)  # 7,9 % desde Fase I (BIO 2011-2020)
    assert p["p"] == pytest.approx(0.079, abs=0.0005)


def test_encogimiento_y_tope():
    t = rnpv.probabilidad_transicion(TABLA, "rara", "II_III")
    assert t["origen"] == "encogida" and t["p"] == pytest.approx((50 * 0.60 + 100 * 0.289) / 150)
    assert rnpv.probabilidad_transicion(TABLA, "rara", "NDA_APROB")["p"] == 0.95
    assert rnpv.probabilidad_transicion(TABLA, "hematologia", "II_III")["p"] == 0.40


def test_valor_rnpv():
    act = [{"nombre": "X1", "fase": "III", "area": "oncologia", "ventas_pico": 1000, "margen": 0.5,
            "anios_hasta_lanzamiento": 2, "anios_rampa": 1, "anios_meseta": 1, "anios_declive": 0}]
    r = rnpv.valor_rnpv(act, TABLA, 0.10, 100, 10, 2, 10, tasa_impuestos=0.0)
    vp = 500 / 1.1 ** 3 + 500 / 1.1 ** 4
    p = 0.578 * 0.906
    gg = 10 / 1.1 + 10 / 1.21
    assert r["valor_por_accion"] == pytest.approx((p * vp + 100 - gg) / 10)
    with pytest.raises(ErrorMotor):
        rnpv.probabilidad_acumulada(TABLA, "x", "IV")


# ================================================================ holdings

def test_sotp():
    seg = [{"nombre": "A", "metodo": "multiplo", "metrica": 100, "multiplo": 10},
           {"nombre": "B", "metodo": "valor", "valor": 500, "participacion": 0.5}]
    r = sotp.valor_sotp(seg, deuda=300, caja=50, coste_holding_anual=10, tasa_descuento=0.10, acciones=10)
    assert r["puente"]["suma_segmentos"] == 1250
    assert r["valor_por_accion"] == pytest.approx((1250 + 50 - 300 - 100) / 10)
    with pytest.raises(ErrorMotor):
        sotp.valor_sotp([{"nombre": "X", "metodo": "raro"}], 0, 0, 0, 0.1, 1)

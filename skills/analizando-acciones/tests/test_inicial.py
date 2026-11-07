import copy
import json

import pytest

import comun
import tasas_base
from artefactos import cifra, dp_completo, router
from dp_sintetico import crecer
from motor import escenarios, inicial, reverse_dcf
from motor.comun_motor import ErrorMotor

MACRO = {"rf_usd": {"valor": 0.045}, "rf_eur": {"valor": 0.030}}
MM = 1_000_000_000


def dp_con_tasas(**kw):
    dp = dp_completo(**kw)
    dp["tasas_base"] = tasas_base.construir(dp)
    return dp


def construir(dp=None, ruta="general", **kw):
    return inicial.construir(dp or dp_con_tasas(), router(ruta), MACRO, **kw)


# ---------------------------------------------------------------- conversión de precio y tasa sin riesgo

def test_precio_misma_moneda():
    p, conv = inicial.precio_en_moneda_informe(dp_completo(), lambda m: 1 / 0)
    assert p == 100.0 and conv["cotizacion_por_informe"] == 1.0 and conv["ratio_adr"] == 1.0


def test_precio_con_otra_moneda_y_ratio_adr():
    """Cotiza en USD (1,12 por EUR), informa en BRL (6,0 por EUR): 1 BRL = 0,1867 USD. ADR = 2 acciones ordinarias."""
    dp = dp_completo()
    dp["empresa"]["moneda_informe"] = "BRL"
    dp["empresa"]["ratio_adr"] = cifra(2.0, "acciones")
    p, conv = inicial.precio_en_moneda_informe(dp, lambda m: {"BRL": 6.0}[m])
    assert conv["cotizacion_por_informe"] == pytest.approx(1.12 / 6.0)
    assert p == pytest.approx(100.0 / 2 / (1.12 / 6.0))      # BRL por acción ordinaria


def test_rf_por_moneda():
    assert inicial.rf_de("USD", MACRO) == 0.045 and inicial.rf_de("EUR", MACRO) == 0.03
    with pytest.raises(ErrorMotor, match="JPY"):
        inicial.rf_de("JPY", MACRO)
    with pytest.raises(ErrorMotor):
        inicial.rf_de("USD", {"rf_usd": comun.desconocido("source_down")})


# ---------------------------------------------------------------- ruta general

def test_base_general():
    m = construir()
    b = m["base"]
    assert b["ruta"] == "general" and b["moneda"] == "USD" and b["precio0"] == 100.0 and b["acciones"] == 1e9
    ing = 10 * MM * 1.05 ** 9
    assert b["ingresos0"] == pytest.approx(ing) and b["margen_inicial"] == pytest.approx(0.20)
    assert b["tasa_impuestos"] == 0.25 and b["rf"] == 0.045 and b["g_terminal"] == 0.03
    # ventas/capital propio: ingresos / (deuda + patrimonio − caja) = ing / (5 + 0,6·ing − 3)
    assert b["ventas_capital"] == pytest.approx(ing / (5 * MM + 0.6 * ing - 3 * MM))
    w = m["supuestos"]["wacc"]
    # cobertura = 0,2·ing / 200 M ≈ 15,5 → AAA (0,40 %); Kd = Rf + diferencial + CRP
    assert w["rating_sintetico"]["rating"] == "Aaa/AAA"
    assert w["kd_antes_impuestos"] == pytest.approx(0.045 + 0.004 + 0.0035)
    beta_l = 1.15 * (1 + 0.75 * (5 * MM / 1e11))
    assert w["ke"] == pytest.approx(0.045 + beta_l * 0.0423 + 0.0035)
    assert b["wacc"] == pytest.approx(w["wacc"])
    assert b["rf_eur"] == 0.03 and b["erp_vwce"] == 0.0423 and b["vol_rel"] == 0.25 and b["vol_abs"] == 0.30


def test_caso_mecanico_usa_las_tasas_base_encogidas():
    dp = dp_con_tasas()
    m = construir(dp)
    obs = dp["tasas_base"]["observados"]
    assert m["caso_mecanico"]["drivers"]["crecimiento_ingresos"]["valor"] == pytest.approx(obs["crecimiento_ventas_5a"]["valor_encogido"])
    assert m["caso_mecanico"]["drivers"]["margen_operativo"]["valor"] == pytest.approx(obs["margen_operativo"]["valor_encogido"])
    assert m["caso_mecanico"]["valor"] > 0 and m["caso_mecanico"]["metodo"] == "dcf_fcff"
    assert m["caso_mecanico"]["valor_sobre_precio"] == pytest.approx(m["caso_mecanico"]["valor"] / 100.0)


def test_dcf_inverso_coherente_con_escenarios():
    """El DCF inverso mantiene el margen actual: si el precio fuese el valor de un escenario con ese margen y un
    crecimiento g, devolvería g."""
    m = construir()
    b = m["base"]
    assert b["margen_operativo"] == pytest.approx(b["margen_inicial"])
    v = escenarios.valorar("general", b, {"crecimiento_ingresos": {"valor": 0.07},
                                          "margen_operativo": {"valor": b["margen_operativo"]}})["valor"]
    r = reverse_dcf.resolver(v, b, "general")
    assert r["principal"]["valor"] == pytest.approx(0.07, abs=1e-7)
    assert m["reverse_dcf"]["principal"]["driver"] == "crecimiento_ingresos"
    assert "percentil" in m["reverse_dcf"]["principal"]


def test_la_base_sirve_a_escenarios():
    m = construir()
    a = json.loads((__import__("conftest").DIR_FIXTURES / "ejemplos" / "analista_A.json").read_text(encoding="utf-8"))
    cfg = comun.cargar_config()
    cfg["escenarios"]["mc_sims"] = 5000
    r = escenarios.ejecutar(a, m, cfg=cfg)
    v = {e["nombre"]: e["valor"] for e in r["escenarios"]}
    assert v["bajista"] < v["base"] < v["alcista"]


def test_coste_de_deuda_sectorial_sin_intereses():
    dp = dp_con_tasas()
    dp["fundamentales"]["gasto_intereses"]["desactualizada"] = True
    m = construir(dp)
    assert m["supuestos"]["wacc"]["kd_antes_impuestos"] == pytest.approx(0.055 + 0.0035)
    assert any("Coste de la deuda" in a for a in m["supuestos"]["avisos"])


def test_ventas_capital_sectorial_si_el_propio_no_es_razonable():
    dp = dp_con_tasas(patrimonio=[-1e10] * 10)      # capital invertido negativo
    m = construir(dp)
    assert m["base"]["ventas_capital"] == 1.8 and any("sectorial" in a for a in m["supuestos"]["avisos"])


def test_sin_prima_pais_ni_tipo_impositivo():
    dp = dp_con_tasas()
    dp["damodaran"]["prima_pais"] = comun.desconocido("not_covered")
    m = construir(dp)
    assert m["supuestos"]["crp"] == 0.0 and m["base"]["tasa_impuestos"] == 0.25
    assert len([a for a in m["supuestos"]["avisos"] if "prima" in a or "impositivo" in a]) == 2


def test_errores_de_datos_imprescindibles():
    dp = dp_con_tasas()
    del dp["fundamentales"]["acciones_diluidas"]
    with pytest.raises(ErrorMotor, match="acciones_diluidas"):
        construir(dp)
    dp = dp_con_tasas()
    dp["precios"] = comun.desconocido("source_down")
    with pytest.raises(ErrorMotor, match="precio"):
        construir(dp)
    dp = dp_con_tasas()
    dp["empresa"]["moneda_informe"] = "JPY"
    with pytest.raises(ErrorMotor, match="JPY"):
        construir(dp, fx_eur=lambda m: 160.0)
    with pytest.raises(ErrorMotor, match="fuera de alcance"):
        construir(ruta="fuera_de_alcance")


# ---------------------------------------------------------------- otras rutas

def test_ruta_banco():
    dp = dp_con_tasas(dividendos=[1e9] * 10, recompras=[5e8] * 10)
    m = construir(dp, "banco_credito")
    b = m["base"]["banco"]
    pat = 0.6 * 10 * MM * 1.05 ** 9
    bn = 0.12 * 10 * MM * 1.05 ** 9
    assert b["patrimonio0"] == pytest.approx(pat) and b["ke"] == pytest.approx(0.045 + 1.2 * 0.0423 + 0.0035)
    assert b["payout"] == pytest.approx(1.5e9 / bn) and m["base"]["roe0"] == pytest.approx(0.2)
    assert m["reverse_dcf"]["principal"]["driver"] == "roe" and m["caso_mecanico"]["metodo"] == "excess_return"
    # coherencia: el ROE implícito al precio = valor mecánico… con ROE sostenido igual que en el motor
    r = reverse_dcf.resolver(m["caso_mecanico"]["valor"], m["base"], "banco_credito")
    assert r["principal"]["valor"] is not None


def test_ruta_ciclica_normaliza_el_margen():
    ing = crecer(10 * MM, 0.02, 10)
    margenes = [0.02, 0.18, 0.04, 0.20, -0.02, 0.16, 0.05, 0.19, 0.03, 0.17]
    dp = dp_con_tasas(ingresos=ing, beneficio_operativo=[i * m for i, m in zip(ing, margenes)])
    m = construir(dp, "ciclica")
    assert m["base"]["margen_operativo"] == pytest.approx(sum(margenes) / 10)
    lo, hi = comun.cargar_config()["motor"]["roc_rango"]
    assert lo <= m["base"]["roc"] <= hi and m["caso_mecanico"]["metodo"] == "dcf_normalizado"


def test_ruta_crecimiento_perdidas_admite_margen_negativo():
    ing = crecer(1 * MM, 0.35, 6)
    dp = dp_con_tasas(ingresos=ing, beneficio_operativo=[-i * 0.1 for i in ing], acciones_diluidas=[1e8] * 6)
    m = construir(dp, "crecimiento_perdidas")
    assert m["base"]["margen_inicial"] == pytest.approx(-0.1) and m["caso_mecanico"]["valor"] is not None


def test_ruta_biotech_con_pipeline():
    dp = dp_con_tasas(ingresos=[1e6] * 5, beneficio_operativo=[-2e8] * 5, fco=[-1.5e8] * 5, acciones_diluidas=[1e8] * 5)
    dp["pipeline"] = [{"nombre": "X-101", "fase": "III", "area": "oncology", "ventas_pico": cifra(1.5e9, "unidades", "USD"),
                       "fuente_url": "https://x"},
                      {"nombre": "X-202", "fase": "I", "area": "neurology", "fuente_url": "https://x"}]   # sin ventas pico
    m = construir(dp, "biotech_precomercial")
    activos = m["base"]["rnpv"]["activos"]
    assert [a["nombre"] for a in activos] == ["X-101"] and any("X-202" in a for a in m["supuestos"]["avisos"])
    assert m["reverse_dcf"]["principal"]["driver"] == "factor_ventas_pico"
    assert m["base"]["rnpv"]["gastos_generales_anuales"] == pytest.approx(1.5e8 * 0.3)
    del dp["pipeline"]
    with pytest.raises(ErrorMotor, match="pipeline"):
        construir(dp, "biotech_precomercial")


def test_ruta_holding():
    dp = dp_con_tasas()
    seg = lambda n, ebit, mult: {"nombre": n, "tipo": "negocio", "ingresos": cifra(1e9, "unidades", "USD"),  # noqa: E731
                                 "beneficio_operativo": cifra(ebit, "unidades", "USD"), "multiplo_ev_ebit": cifra(mult, "veces")}
    dp["segmentos"] = [seg("A", 2e9, 12.0), seg("B", 1e9, 18.0)]
    m = construir(dp, "holding")
    assert len(m["base"]["sotp"]["segmentos"]) == 2 and m["reverse_dcf"]["principal"]["driver"] == "factor_multiplos"
    f = m["reverse_dcf"]["principal"]["valor"]
    assert escenarios.valorar("holding", m["base"], {"factor_multiplos": {"valor": f}})["valor"] == pytest.approx(100.0)


def test_resolver_factor_sin_raiz():
    dp = dp_con_tasas()
    seg = {"nombre": "A", "tipo": "negocio", "ingresos": cifra(1.0, "u", "USD"), "beneficio_operativo": cifra(1.0, "u", "USD"),
           "multiplo_ev_ebit": cifra(1.0, "veces")}
    dp["segmentos"] = [seg, {**seg, "nombre": "B"}]
    m = construir(dp, "holding")
    assert m["reverse_dcf"]["sin_raiz"] is True


def test_cli_escribe_el_error(tmp_path):
    dp = dp_con_tasas()
    (tmp_path / "datapack.json").write_text(json.dumps(dp), encoding="utf-8")
    (tmp_path / "router.json").write_text(json.dumps(router("general")), encoding="utf-8")
    (tmp_path / "macro_regime.json").write_text(json.dumps(MACRO), encoding="utf-8")
    assert inicial.main(["--dir", str(tmp_path)]) == 0
    assert "reverse_dcf" in json.loads((tmp_path / "motor_inicial.json").read_text(encoding="utf-8"))
    (tmp_path / "macro_regime.json").write_text(json.dumps({}), encoding="utf-8")
    assert inicial.main(["--dir", str(tmp_path)]) == 1
    assert "rf_usd" in json.loads((tmp_path / "motor_inicial.json").read_text(encoding="utf-8"))["error"]


def test_roic_terminal_solo_con_moat_documentado():
    m = construir()
    a = json.loads((__import__("conftest").DIR_FIXTURES / "ejemplos" / "analista_A.json").read_text(encoding="utf-8"))
    for e in a["escenarios"]:
        e["drivers"]["roic_terminal"] = {"valor": 0.25, "justificacion": "ROIC histórico sostenido"}
    cfg = comun.cargar_config()
    cfg["escenarios"]["mc_sims"] = 2000
    con = escenarios.ejecutar(a, m, cfg=cfg)
    assert escenarios.moat_documentado(a) is True
    assert con["escenarios"][1]["drivers_usados"]["roic_terminal"] == 0.25
    sin_moat = copy.deepcopy(a)
    sin_moat["moat"] = {"fuente": "ninguna", "amplitud": "ninguno", "evidencia": []}
    r = escenarios.ejecutar(sin_moat, m, cfg=cfg)
    assert "ignorado" in r["escenarios"][1]["drivers_usados"]["roic_terminal"]
    assert con["escenarios"][1]["valor"] > r["escenarios"][1]["valor"]       # menos reinversión terminal


# ---------------------------------------------------------------- base de últimos doce meses

def _trim(valores_por_fecha, campo="ingresos"):
    """Serie trimestral: {(inicio, fin): valor}."""
    serie = []
    for (ini, fin), v in valores_por_fecha.items():
        c = cifra(v, "unidades", "USD", f=fin)
        c["periodo_inicio"] = ini
        serie.append(c)
    return {"concepto": f"{campo} trimestral", "serie": serie}


def _dp_con_trimestres(completos=True):
    """Ejercicio anual cerrado en 2025-12-31 (el último de dp_completo usa fecha_dato 2026-11-05: se reasigna)."""
    dp = dp_completo()
    for c in ("ingresos", "beneficio_operativo"):
        dp["fundamentales"][c]["serie"][-1]["fecha_dato"] = "2025-12-31"
    anual_ing = dp["fundamentales"]["ingresos"]["serie"][-1]["valor"]
    anual_ebit = dp["fundamentales"]["beneficio_operativo"]["serie"][-1]["valor"]
    q = {("2026-01-01", "2026-03-31"): anual_ing * 0.30, ("2026-04-01", "2026-06-30"): anual_ing * 0.35}
    prev = {("2025-04-01", "2025-06-30"): anual_ing * 0.20}
    if completos:
        prev[("2025-01-01", "2025-03-31")] = anual_ing * 0.18
    dp["trimestrales"] = {"ingresos": _trim({**prev, **q}),
                          "beneficio_operativo": _trim({k: v * (anual_ebit / anual_ing) for k, v in {**prev, **q}.items()})}
    dp["tasas_base"] = tasas_base.construir(dp)
    return dp, anual_ing, anual_ebit


def test_base_doce_meses_con_trimestres_posteriores():
    dp, anual, anual_ebit = _dp_con_trimestres()
    m = construir(dp)
    esperado = anual + (0.30 + 0.35 - 0.18 - 0.20) * anual
    assert m["base"]["ingresos0"] == pytest.approx(esperado)
    assert m["base"]["margen_inicial"] == pytest.approx(anual_ebit / anual)      # mismo margen en ambos
    assert m["base"]["base_ingresos"]["metodo"] == "ttm" and m["base"]["base_ingresos"]["fecha_fin"] == "2026-06-30"
    assert any("últimos doce meses hasta 2026-06-30" in a for a in m["supuestos"]["avisos"])


def test_sin_comparable_del_ano_anterior_usa_el_ejercicio_y_lo_avisa():
    dp, anual, _ = _dp_con_trimestres(completos=False)
    m = construir(dp)
    assert m["base"]["ingresos0"] == pytest.approx(anual) and m["base"]["base_ingresos"]["metodo"] == "anual"
    assert any("Base de ingresos anual" in a and "falta el trimestre del año anterior" in a for a in m["supuestos"]["avisos"])


def test_trimestres_no_contiguos_no_se_encadenan():
    dp, anual, _ = _dp_con_trimestres()
    for c in ("ingresos", "beneficio_operativo"):
        dp["trimestrales"][c]["serie"] = [q for q in dp["trimestrales"][c]["serie"] if q["fecha_dato"] != "2026-03-31"]
    m = construir(dp)
    assert m["base"]["base_ingresos"]["metodo"] == "anual" and any("no son contiguos" in a for a in m["supuestos"]["avisos"])


def test_sin_beneficio_operativo_trimestral_se_usan_los_ingresos_de_12_meses_con_el_margen_anual():
    """Nucor: hay ingresos trimestrales pero no resultado operativo trimestral."""
    dp, anual, anual_ebit = _dp_con_trimestres()
    del dp["trimestrales"]["beneficio_operativo"]
    m = construir(dp)
    esperado = anual + (0.30 + 0.35 - 0.18 - 0.20) * anual
    b = m["base"]
    assert b["base_ingresos"]["metodo"] == "ttm_ingresos" and b["ingresos0"] == pytest.approx(esperado)
    assert b["margen_inicial"] == pytest.approx(anual_ebit / anual)          # margen del último ejercicio
    assert any("se mantiene el margen operativo del último ejercicio" in a for a in m["supuestos"]["avisos"])
    assert not any("de hace" in a and "sin trimestres posteriores" in a for a in m["supuestos"]["avisos"])


def _balance_trimestral(dp, campo, valor, fecha):
    dp.setdefault("trimestrales", {})[campo] = {"concepto": campo, "serie": [cifra(valor, "unidades", "USD", f=fecha)]}


def test_caja_y_deuda_del_ultimo_balance_trimestral():
    dp, _, _ = _dp_con_trimestres()
    anual = inicial.saldo_reciente(dp, "caja")
    assert anual[1] == "2025-12-31" or anual[1] <= "2026-01-01"              # sin saldos trimestrales: el del ejercicio
    _balance_trimestral(dp, "caja", 1.0 * MM, "2026-09-30")
    _balance_trimestral(dp, "deuda_total", 9.0 * MM, "2026-09-30")
    assert inicial.saldo_reciente(dp, "caja") == (1.0 * MM, "2026-09-30")
    dp["tasas_base"] = tasas_base.construir(dp)
    b = construir(dp)["base"]
    assert b["caja"] == 1.0 * MM and b["deuda"] == 9.0 * MM
    assert b["balance_fecha"] == {"deuda": "2026-09-30", "caja": "2026-09-30"}
    # un saldo trimestral anterior al del ejercicio no sustituye al del ejercicio
    dp2, _, _ = _dp_con_trimestres()
    _balance_trimestral(dp2, "caja", 99.0 * MM, "2020-01-01")
    assert inicial.saldo_reciente(dp2, "caja")[0] != 99.0 * MM


def test_balance_antiguo_se_avisa_y_el_reciente_no():
    dp, _, _ = _dp_con_trimestres()
    dp["fecha_analisis"] = "2026-11-06"
    assert any("Caja y deuda del balance a" in a and "de hace" in a for a in construir(dp)["supuestos"]["avisos"])
    for c in ("caja", "deuda_total"):
        _balance_trimestral(dp, c, 3.0 * MM, "2026-09-30")
    assert not any("Caja y deuda del balance a" in a for a in construir(dp)["supuestos"]["avisos"])


def test_beneficio_operativo_aproximado_se_avisa():
    dp = dp_con_tasas()
    assert not any("aproximado" in a for a in construir(dp)["supuestos"]["avisos"])
    for p in dp["fundamentales"]["beneficio_operativo"]["serie"]:
        p["concepto"] = "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest+InterestExpense"
    assert any("Beneficio operativo aproximado" in a for a in construir(dp)["supuestos"]["avisos"])


def test_base_anual_antigua_sin_trimestres_avisa():
    dp, _, _ = _dp_con_trimestres()
    del dp["trimestrales"]
    dp["fecha_analisis"] = "2026-11-06"
    m = construir(dp)
    assert any("de hace 10 meses y sin trimestres posteriores" in a for a in m["supuestos"]["avisos"])


def test_sin_trimestres_la_base_es_anual_sin_avisos_nuevos():
    m = construir()
    assert m["base"]["base_ingresos"]["metodo"] == "anual"
    assert not any("últimos doce meses" in a or "no se pueden encadenar" in a for a in m["supuestos"]["avisos"])


def test_beta_mixta_mezcla_sector_y_propia_con_ajuste_de_blume():
    cfg = comun.cargar_config()
    dp = dp_con_tasas()
    dp["precios"]["metricas_eur"]["beta_3a"] = {"valor": 1.0}
    b, d = inicial.beta_desapalancada_mixta(dp, cfg, 1.55, deuda=0.0, cap=100.0, t=0.25, avisos=[])
    propia = 0.67 * 1.0 + 0.33
    assert d["propia_ajustada"] == pytest.approx(propia)
    assert b == pytest.approx(0.5 * propia + 0.5 * 1.55)


def test_beta_mixta_sin_beta_propia_usa_el_sector_y_peso_cero_tambien():
    cfg = comun.cargar_config()
    dp = dp_con_tasas()
    dp["precios"]["metricas_eur"].pop("beta_3a", None)
    assert inicial.beta_desapalancada_mixta(dp, cfg, 1.2, 0.0, 100.0, 0.25, [])[0] == 1.2
    dp["precios"]["metricas_eur"]["beta_3a"] = {"valor": 0.5}
    cfg["beta"]["peso_propia"] = 0
    assert inicial.beta_desapalancada_mixta(dp, cfg, 1.2, 0.0, 100.0, 0.25, [])[0] == 1.2


def test_beta_mixta_limita_la_beta_propia_al_rango():
    cfg = comun.cargar_config()
    dp = dp_con_tasas()
    dp["precios"]["metricas_eur"]["beta_3a"] = {"valor": 9.0}
    _, d = inicial.beta_desapalancada_mixta(dp, cfg, 1.0, 0.0, 100.0, 0.25, [])
    assert d["propia_ajustada"] == cfg["beta"]["rango_propia"][1]

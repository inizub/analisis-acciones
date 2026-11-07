import copy
import json

import pytest

import comun
import gate
from artefactos import (analista, dp_completo, escenarios, escribir_run, forense, motor, router, run, sintesis)
from dp_sintetico import cifra_banca

CFG = comun.cargar_config()


def evaluar(modo="completo", fase="final", **ov):
    art = run(modo, **ov)
    return gate.evaluar(art["dp"], art["router"], modo, fase, art["motor"], art["analistas"], art["escenarios"],
                        art["forense"], art["sintesis"])


def fallos(r):
    return {int(n) for n, i in r["items"].items() if i["estado"] == "fallo"}


def test_ejecucion_sana_pasa_los_12_puntos():
    r = evaluar()
    assert r["pasa"] and r["fallos"] == []
    assert fallos(r) == set()
    assert r["items"]["8"]["estado"] == "ok" and len(r["items"]) == 12
    assert r["items"]["1"]["detalle"].startswith("10 campos")


def test_rapido_no_exige_contraargumento_ni_a_y_b():
    s = sintesis()
    s["mejor_contraargumento"] = None
    r = evaluar("rapido", sintesis=s)
    assert r["pasa"] and r["items"]["8"]["estado"] == "no_evaluado"


# ---------------------------------------------------------------- 1: campos críticos

def test_resolver_campo_con_claves_con_puntos():
    dp = dp_completo()
    nodo, err = gate.resolver_campo(dp, "damodaran/sector/valores/betas.beta_desapalancada")
    assert err is None and nodo["valor"] == 1.1
    assert gate.resolver_campo(dp, "damodaran/inexistente")[1] == "ausente"


def test_campo_critico_desconocido_ausente_o_sin_fuente():
    dp = dp_completo()
    dp["fundamentales"]["ingresos"] = comun.desconocido("rate_limited")
    r = evaluar(dp=dp)
    assert fallos(r) == {1} and "ingresos: desconocido (rate_limited)" in r["fallos"][0]
    dp = dp_completo()
    del dp["fundamentales"]["caja"]
    assert "caja: ausente" in evaluar(dp=dp)["fallos"][0]
    dp = dp_completo()
    del dp["fundamentales"]["deuda_total"]["serie"][-1]["fuente_url"]
    assert "sin fuente o fecha" in evaluar(dp=dp)["fallos"][0]
    dp = dp_completo()
    dp["fundamentales"]["beneficio_operativo"]["desactualizada"] = True
    dp["fundamentales"]["beneficio_operativo"]["ultimo_periodo"] = "2020-12-31"
    assert "desactualizado" in evaluar(dp=dp)["fallos"][0]
    dp = dp_completo()
    dp["precios"] = comun.desconocido("source_down")
    r = evaluar(dp=dp)
    assert {1, 11} <= fallos(r)


def test_cada_ruta_define_campos_criticos_y_los_del_ejemplo_general_existen():
    from router import PRIORIDAD
    for ruta in PRIORIDAD:
        campos = gate.campos_criticos(ruta, CFG)
        assert (campos == []) == (ruta == "fuera_de_alcance")
    assert "banca/cet1" not in gate.campos_criticos("banco_credito", CFG)       # el capital se comprueba aparte
    dp = dp_completo()
    assert [gate.comprobar_campo(dp, c) for c in gate.campos_criticos("general", CFG)] == [None] * 10


def test_segmentos_como_campo_critico():
    from dp_sintetico import segmento
    dp = dp_completo(); dp["segmentos"] = [segmento("A", 50), segmento("B", 50), segmento("C", 50)]
    assert gate.comprobar_campo(dp, "segmentos") is None
    dp["segmentos"] = []
    assert "vacío" in gate.comprobar_campo(dp, "segmentos")
    dp["segmentos"] = [{"nombre": "A", "tipo": "negocio", "ingresos": comun.desconocido("not_covered")}]
    assert "sin fuente o desconocido" in gate.comprobar_campo(dp, "segmentos")


# ---------------------------------------------------------------- 2: discrepancias

def test_discrepancia_resuelta_pasa_y_sin_resolver_falla():
    dp = dp_completo()
    dp["verificacion_cruzada"]["ingresos"] = {"estado": "discrepancia_resuelta_edgar", "diferencia_rel": 0.3}
    dp["verificacion_cruzada"]["acciones_diluidas"] = {"estado": "sin_comparar"}
    r = evaluar(dp=dp)
    assert r["pasa"] and len(r["items"]["2"]["avisos"]) == 2 and len(r["avisos"]) >= 2
    dp["verificacion_cruzada"]["beneficio_neto"] = {"estado": "discrepancia_sin_resolver"}
    assert fallos(evaluar(dp=dp)) == {2}


# ---------------------------------------------------------------- 3: ruta fuera de alcance

def test_fuera_de_alcance_solo_informa_el_fallo_3():
    r = evaluar(router=router("fuera_de_alcance") | {"motivo": "SIC 6798: REIT/SOCIMI"}, dp=dp_completo(sic=6798))
    assert not r["pasa"] and len(r["fallos"]) == 1 and r["fallos"][0].startswith("3.")
    assert "REIT" in r["fallos"][0]
    assert all(i["estado"] == "no_evaluado" for n, i in r["items"].items() if n != "3")


# ---------------------------------------------------------------- 4-8: analistas y síntesis

def test_escenarios_invalidos_o_ausentes():
    a = analista("A"); a["escenarios"][0]["p"] = 0.4
    r = evaluar(analistas={"A": a, "B": analista("B")})
    assert fallos(r) == {4} and "analista A" in r["fallos"][0] and "suman" in r["fallos"][0]
    r = evaluar(analistas={"A": analista("A"), "B": None})
    assert fallos(r) == {4, 6}                                  # sin analista B tampoco hay su pre-mortem
    assert "falta analista_B.json" in r["items"]["4"]["detalle"]
    a = analista("A"); del a["escenarios"][0]["perdida_permanente"]
    assert fallos(evaluar(analistas={"A": a, "B": analista("B")})) == {4}


def test_dcf_inverso_ausente():
    m = motor(); del m["reverse_dcf"]
    assert fallos(evaluar(motor=m)) == {5}
    assert "sin raíz" in gate.punto_5(motor(sin_raiz=True))["detalle"]     # sin raíz cuenta como ejecutado


def test_premortem():
    a = analista("A"); a["pre_mortem"] = ["x", "y", "  "]
    r = gate.punto_6({"A": a, "B": analista("B")}, ["A", "B"])
    assert r["estado"] == "fallo" and "A" in r["detalle"] and "B" not in r["detalle"]


def test_criterios_de_invalidacion_minimo_2():
    s = sintesis(); s["criterios_invalidacion"] = s["criterios_invalidacion"][:1]
    assert fallos(evaluar(sintesis=s)) == {7}
    assert fallos(evaluar(sintesis=None)) == {7, 8}


def test_contraargumento_solo_en_completo():
    s = sintesis(); s["mejor_contraargumento"] = "  "
    assert fallos(evaluar("completo", sintesis=s)) == {8}
    assert fallos(evaluar("rapido", sintesis=s)) == set()
    assert fallos(evaluar("degradado", sintesis=s)) == set()


def test_bandera_invalidante():
    f = forense([{"bandera": "Opinión de auditoría con salvedades", "nivel": "invalidante", "origen": "cualitativa",
                  "dato_ref": "cambios.opinion_auditoria"}])
    r = evaluar(forense=f)
    assert fallos(r) == {9} and "salvedades" in r["fallos"][0]
    graves = forense([{"bandera": "x" * 10, "nivel": "grave", "origen": "cuantitativa", "dato_ref": "d"}])
    assert gate.punto_9(graves)["estado"] == "ok"        # una bandera grave no invalida; solo bloquea 'atractiva'


# ---------------------------------------------------------------- 10: el balance sobrevive al bajista

def test_cobertura_en_el_bajista():
    dp = dp_completo()     # ingresos0 ≈ 15.513 M, margen bajista 15 % → EBIT ≈ 2.327 M; intereses 200 M → 11,6
    r = evaluar(dp=dp)
    assert r["items"]["10"]["estado"] == "ok" and "11." in r["items"]["10"]["detalle"]
    dp = dp_completo(gasto_intereses=[2e9] * 10)       # 2.327 / 2.000 = 1,16 ≤ 1,5
    r = evaluar(dp=dp)
    assert fallos(r) == {10} and "1.16" in r["fallos"][0]


def test_cobertura_usa_el_peor_analista():
    a, b = escenarios("A", margen_bajista=.30), escenarios("B", margen_bajista=.02)
    dp = dp_completo()
    cob, _ = gate.cobertura_bajista(dp, motor(), {"A": a, "B": b})
    assert cob == pytest.approx(motor()["base"]["ingresos0"] * 0.02 / 2e8)


def test_sin_gasto_por_intereses():
    dp = dp_completo(gasto_intereses=[0.0] * 10)
    assert evaluar(dp=dp)["items"]["10"]["detalle"] == "sin gasto por intereses"
    dp = dp_completo()
    dp["fundamentales"]["gasto_intereses"]["desactualizada"] = True
    dp["fundamentales"]["gasto_intereses"]["ultimo_periodo"] = "2023-12-31"
    r = evaluar(dp=dp)
    assert r["pasa"] and r["items"]["10"]["estado"] == "no_evaluado" and any("Punto 10" in a for a in r["avisos"])


def test_sin_gasto_por_intereses_con_politica_estricta(monkeypatch):
    dp = dp_completo()
    del dp["fundamentales"]["gasto_intereses"]
    cfg = copy.deepcopy(CFG); cfg["gate"]["cobertura_sin_dato"] = "fallo"
    art = run("completo", dp=dp)
    r = gate.evaluar(art["dp"], art["router"], "completo", "final", art["motor"], art["analistas"], art["escenarios"],
                     art["forense"], art["sintesis"], cfg)
    assert fallos(r) == {10} and "con deuda" in r["fallos"][0]


def test_banco_cet1_sobre_requisito():
    dp = dp_completo()
    dp["banca"] = {"cet1": cifra_banca([0.13]), "cet1_requisito": cifra_banca([0.115])}
    r = gate.punto_10(dp, "banco_credito", None, {}, CFG)
    assert r["estado"] == "ok"
    dp["banca"]["cet1"] = cifra_banca([0.11])
    assert gate.punto_10(dp, "banco_credito", None, {}, CFG)["estado"] == "fallo"
    dp["banca"] = {}
    assert "faltan CET1" in gate.punto_10(dp, "banco_credito", None, {}, CFG)["detalle"]


# ---------------------------------------------------------------- 11: antigüedad del precio

@pytest.mark.parametrize("dias,ok", [(0, True), (3, True), (4, False), (10, False)])
def test_antiguedad_del_precio(dias, ok):
    r = evaluar(dp=dp_completo(antiguedad=dias))
    assert (11 not in fallos(r)) == ok


# ---------------------------------------------------------------- fase previa y E/S

def test_fase_previa_evalua_solo_1_2_3_y_11():
    art = run("completo", dp=dp_completo(antiguedad=9))
    r = gate.evaluar(art["dp"], art["router"], "completo", "previo")
    assert fallos(r) == {11}
    assert {n for n, i in r["items"].items() if i["estado"] == "no_evaluado"} == {"4", "5", "6", "7", "8", "9", "10", "12"}


def test_cli(tmp_path):
    escribir_run(tmp_path, run("rapido"))
    (tmp_path / "gate.json").unlink()
    assert gate.main(["--dir", str(tmp_path), "--modo", "rapido"]) == 0
    assert json.loads((tmp_path / "gate.json").read_text(encoding="utf-8"))["pasa"] is True
    assert gate.main(["--dir", str(tmp_path), "--modo", "rapido", "--fase", "previo"]) == 0
    assert (tmp_path / "gate_previo.json").exists()
    (tmp_path / "router.json").unlink()
    with pytest.raises(SystemExit):
        gate.main(["--dir", str(tmp_path), "--modo", "rapido"])


def test_capital_bancario_cet1_o_capital_total():
    from dp_sintetico import cifra_banca
    dp = dp_completo()
    assert gate.capital_bancario(dp) is None
    assert any("capital_total" in f for f in gate.faltan_criticos(dp, "banco_credito", CFG))
    dp["banca"] = {"capital_total": cifra_banca([0.166]), "capital_total_requisito": cifra_banca([0.105])}
    cap = gate.capital_bancario(dp)
    assert cap == {"tipo": "capital total", "valor": 0.166, "requisito": 0.105}
    r = gate.punto_10(dp, "banco_credito", None, {}, CFG)
    assert r["estado"] == "ok" and r["detalle"].startswith("capital total")
    dp["banca"]["cet1"] = cifra_banca([0.13])
    dp["banca"]["cet1_requisito"] = cifra_banca([0.115])
    assert gate.capital_bancario(dp)["tipo"] == "CET1"                         # CET1 tiene prioridad
    dp["banca"]["cet1"] = comun.desconocido("not_covered")
    assert gate.capital_bancario(dp)["tipo"] == "capital total"


# ---------------------------------------------------------------- 12: cordura del modelo

def test_modelo_no_fiable_falla_el_checklist_con_el_motivo():
    esc = escenarios("A")
    esc["cordura"] = {"fiable": False, "motivo": "incluso el escenario más alto vale 0,25 veces el precio"}
    art = run("rapido", escenarios={"N": {**esc, "analista": "N"}})
    r = gate.evaluar(art["dp"], art["router"], "rapido", "final", art["motor"], art["analistas"], art["escenarios"],
                     art["forense"], art["sintesis"])
    assert not r["pasa"] and fallos(r) == {12}
    assert "modelo no fiable" in r["fallos"][0] and "0,25 veces el precio" in r["fallos"][0]


def test_cordura_fiable_o_sin_dato_no_falla():
    esc = escenarios("A")
    assert gate.punto_12({"A": esc}, ["A"])["estado"] == "no_evaluado"
    esc["cordura"] = {"fiable": True, "motivo": ""}
    assert gate.punto_12({"A": esc}, ["A"])["estado"] == "ok"


def test_cierre_anticipado_por_modelo_no_fiable_no_cuenta_la_falta_de_sintesis_como_fallo():
    esc = {n: {**escenarios(n), "cordura": {"fiable": False, "motivo": "valores muy por debajo del precio"}}
           for n in ("A", "B")}
    art = run("completo", escenarios=esc)
    r = gate.evaluar(art["dp"], art["router"], "completo", "final", art["motor"], art["analistas"], esc,
                     art["forense"], None)
    assert fallos(r) == {12}
    assert r["items"]["7"]["estado"] == "no_evaluado" and r["items"]["8"]["estado"] == "no_evaluado"
    # con modelo fiable y sin síntesis, la falta de síntesis sigue siendo un fallo
    sana = {n: {**escenarios(n), "cordura": {"fiable": True, "motivo": ""}} for n in ("A", "B")}
    r2 = gate.evaluar(art["dp"], art["router"], "completo", "final", art["motor"], art["analistas"], sana,
                      art["forense"], None)
    assert {7, 8} <= fallos(r2)

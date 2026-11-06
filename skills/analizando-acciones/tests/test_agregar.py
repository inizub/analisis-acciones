import json

import pytest

import agregar
from artefactos import escenarios as esc, motor, run

B, K = 0.45, 0.4


def test_logit_sigmoide_y_media():
    assert agregar.sigmoide(agregar.logit(0.73)) == pytest.approx(0.73)
    assert agregar.agregar_logit([0.8, 0.2]) == pytest.approx(0.5)
    # media de log-odds: logit(.7)=0,8473; logit(.5)=0 → sigmoide(0,4236)
    assert agregar.agregar_logit([0.7, 0.5]) == pytest.approx(agregar.sigmoide(agregar.logit(0.7) / 2))
    assert agregar.agregar_logit([0.6]) == pytest.approx(0.6)
    assert 0.9 < agregar.agregar_logit([1.0, 0.9]) < 1.0          # los extremos no producen infinitos


def test_encoger_y_limitar():
    assert agregar.encoger(0.70, B, K) == pytest.approx(0.55)      # p_agg 0,70 es el mínimo para p_final 0,55
    assert agregar.encoger(0.45, B, K) == pytest.approx(0.45)
    assert agregar.encoger(0.0, B, K) == pytest.approx(0.27)
    assert agregar.limitar(0.99, [0.05, 0.95]) == 0.95 and agregar.limitar(0.01, [0.05, 0.95]) == 0.05


def test_agregacion_completa():
    a = {"A": esc("A", e1=.80, e3=.20, exceso=9.0, perdida=.20), "B": esc("B", e1=.60, e3=.02, exceso=5.0, perdida=.35)}
    r = agregar.agregar(a, "completo")
    esperado = agregar.sigmoide((agregar.logit(.80) + agregar.logit(.60)) / 2)
    assert r["p_agg"]["E1"] == pytest.approx(esperado)
    assert r["p_final"]["E1"] == pytest.approx(B + K * (esperado - B))
    assert r["dispersion"]["E1"] == pytest.approx(0.20)
    # E3 sin encoger y limitada a [0,05; 0,95]
    assert r["p_final"]["E3"] == pytest.approx(agregar.agregar_logit([.20, .02]))
    assert r["p_final"]["E3"] >= 0.05
    assert r["exceso_anual_esperado_pp"] == pytest.approx(7.0)    # media
    assert r["perdida_escenario_bajista"] == pytest.approx(0.35)  # peor caso
    assert r["tasa_base"] == 0.45 and r["tasa_base_tipo"] == "heuristica" and r["k"] == 0.4
    assert r["analistas"] == ["A", "B"]


def test_e3_se_limita_a_5_por_ciento():
    r = agregar.agregar({"A": esc("A", e3=.001), "B": esc("B", e3=.002)}, "completo")
    assert r["p_final"]["E3"] == 0.05


def test_un_solo_analista_no_agrega_ni_tiene_dispersion():
    r = agregar.agregar({"N": esc("N", e1=.66)}, "rapido")
    assert r["p_agg"]["E1"] == 0.66 and r["dispersion"]["E1"] is None
    assert r["p_final"]["E1"] == pytest.approx(B + K * (0.66 - B))


def test_modo_y_analistas_invalidos():
    with pytest.raises(ValueError, match="A y de B"):
        agregar.agregar({"N": esc("N")}, "completo")
    with pytest.raises(ValueError, match="A y B"):
        agregar.agregar({"A": esc("A"), "N": esc("N")}, "completo")
    with pytest.raises(ValueError):
        agregar.agregar({}, "rapido")
    r = agregar.agregar({"B1": esc("B1")}, "completo")             # el analista del baseline B1 va solo
    assert r["analistas"] == ["B1"]


# ---------------------------------------------------------------- veredicto

def ver(e1, exceso=8.0, perdida=0.30, banderas=None, motor_=None, **kw):
    a = {"A": esc("A", e1=e1, exceso=exceso, perdida=perdida), "B": esc("B", e1=e1, exceso=exceso, perdida=perdida)}
    return agregar.agregar(a, "completo", banderas=banderas, reverse_dcf=(motor_ or motor())["reverse_dcf"])


def test_atractiva():
    r = ver(.75)   # p_agg .75 → p_final .57
    assert r["veredicto"] == "atractiva" and all(r["condiciones"]["atractiva"].values())


def test_frontera_exacta_p_final_055():
    r = ver(.70)   # p_final = 0,55 exacto: debe contar como ≥ 0,55
    assert r["p_final"]["E1"] == pytest.approx(0.55) and r["veredicto"] == "atractiva"
    assert ver(.699)["veredicto"] == "neutral"


@pytest.mark.parametrize("kw,falta", [({"exceso": 4.9}, "exceso"), ({"perdida": 0.51}, "pérdida")])
def test_neutral_si_falla_una_condicion_de_atractiva(kw, falta):
    r = ver(.75, **kw)
    assert r["veredicto"] == "neutral" and falta in r["motivo_veredicto"]


def test_perdida_justo_50_cuenta():
    assert ver(.75, perdida=0.50)["veredicto"] == "atractiva"


def test_banderas_graves_bloquean_atractiva_pero_no_las_informativas():
    graves = [{"bandera": "FCO/BN 0,5", "nivel": "grave"}]
    assert ver(.75, banderas=graves)["veredicto"] == "neutral"
    assert ver(.75, banderas=[{"bandera": "x", "nivel": "invalidante"}])["veredicto"] == "neutral"
    assert ver(.75, banderas=[{"bandera": "x", "nivel": "informativa"}])["veredicto"] == "atractiva"


def test_no_atractiva_por_probabilidad():
    r = ver(.30)   # p_final = 0,45 + 0,4·(0,30 − 0,45) = 0,39
    assert r["veredicto"] == "no_atractiva" and r["p_final"]["E1"] == pytest.approx(0.39)
    assert ver(.3125)["veredicto"] == "no_atractiva"       # p_final 0,395
    assert ver(.375)["veredicto"] == "neutral"             # p_final 0,42


def test_no_atractiva_por_dcf_inverso_sin_raiz_aunque_lo_demas_sea_atractivo():
    r = ver(.75, motor_=motor(sin_raiz=True))
    assert r["veredicto"] == "no_atractiva" and "sin raíz" in r["motivo_veredicto"]
    assert all(r["condiciones"]["atractiva"].values())     # precedencia de no_atractiva


def test_no_atractiva_por_driver_con_z_mayor_que_3():
    assert ver(.75, motor_=motor(z=3.5))["veredicto"] == "no_atractiva"
    assert ver(.75, motor_=motor(z=3.0))["veredicto"] == "atractiva"      # z = 3 no es > 3
    r = ver(.75, motor_=motor(z=3.5))
    assert "crecimiento_ingresos (z=3.5)" in r["condiciones"]["detalle"]["z_altos"]


def test_sin_dcf_inverso_no_dispara_no_atractiva():
    a = {"A": esc("A", e1=.75), "B": esc("B", e1=.75)}
    r = agregar.agregar(a, "completo", reverse_dcf=None)
    assert r["veredicto"] == "atractiva" and r["condiciones"]["detalle"]["dcf_inverso_disponible"] is False


# ---------------------------------------------------------------- E4 con umbral común

def test_e4_umbral_comun_recalcula_la_p_de_cada_analista():
    # A: base 8 %, escenarios (2 %, 8 %, 13 %) → con umbral 7 % pasan base y alcista: 0,75
    # B: base 6 %, escenarios (2 %, 5 %, 12 %) → con umbral 7 % solo pasa el alcista: 0,25
    a = esc("A", e4_base=.08, e4_valores=(.02, .08, .13), e4=.75)
    b = esc("B", e4_base=.06, e4_valores=(.02, .05, .12), e4=.75)   # su p(E4) propia (0,75) ya no vale
    r = agregar.agregar({"A": a, "B": b}, "completo")
    assert r["metrica_e4"]["valor_base"] == pytest.approx(0.07)
    assert r["metrica_e4"]["valores_propuestos"] == {"A": 0.08, "B": 0.06}
    assert r["p_por_analista"]["A"]["E4"] == pytest.approx(0.75)
    assert r["p_por_analista"]["B"]["E4"] == pytest.approx(0.25)
    assert r["p_agg"]["E4"] == pytest.approx(agregar.agregar_logit([.75, .25]))


def test_e4_metricas_distintas_es_un_error():
    b = esc("B")
    b["metrica_e4"]["metrica"] = "roe"
    with pytest.raises(ValueError, match="métricas E4 distintas"):
        agregar.agregar({"A": esc("A"), "B": b}, "completo")


def test_e4_analista_unico_conserva_su_p():
    r = agregar.agregar({"N": esc("N", e4=.75)}, "rapido")
    assert r["p_por_analista"]["N"]["E4"] == pytest.approx(0.75)


# ---------------------------------------------------------------- E/S

def test_cli(tmp_path):
    from artefactos import escribir_run
    escribir_run(tmp_path, run("completo"))
    (tmp_path / "agregado.json").unlink()
    assert agregar.main(["--dir", str(tmp_path), "--modo", "completo"]) == 0
    r = json.loads((tmp_path / "agregado.json").read_text(encoding="utf-8"))
    assert r["veredicto"] == "atractiva" and r["analistas"] == ["A", "B"]
    (tmp_path / "escenarios_B.json").unlink()
    with pytest.raises(SystemExit) as e:
        agregar.main(["--dir", str(tmp_path), "--modo", "completo"])
    assert e.value.code == 1


def test_banderas_toman_forense_json_o_metricas(tmp_path):
    assert agregar.cargar_banderas(tmp_path) == []
    (tmp_path / "forense_metricas.json").write_text(json.dumps({"banderas": [{"bandera": "m", "nivel": "grave"}]}), encoding="utf-8")
    assert agregar.cargar_banderas(tmp_path)[0]["bandera"] == "m"
    (tmp_path / "forense.json").write_text(json.dumps({"banderas": [{"bandera": "a", "nivel": "informativa"}]}), encoding="utf-8")
    assert agregar.cargar_banderas(tmp_path)[0]["bandera"] == "a"     # el del agente tiene prioridad

import json

import pytest

import agregar
from artefactos import escenarios as esc, motor, run

def test_limitar_y_percentiles_de_la_mezcla():
    assert agregar.limitar(0.99, [0.05, 0.95]) == 0.95 and agregar.limitar(0.01, [0.05, 0.95]) == 0.05
    # mezcla a partes iguales de dos uniformes U(0, 1) y U(1, 2): la mediana es 1 y el p5, 0,1
    u1 = [q / 100 for q in range(1, 100)]
    u2 = [1 + q / 100 for q in range(1, 100)]
    p5, p50, p95 = agregar.percentiles_mezcla([u1, u2])
    assert p50 == pytest.approx(1.0, abs=0.02) and p5 == pytest.approx(0.10, abs=0.02) and p95 == pytest.approx(1.90, abs=0.02)


def test_agregacion_completa():
    a = {"A": esc("A", e1=.80, e3=.20, exceso=9.0, perdida=.20), "B": esc("B", e1=.60, e3=.02, exceso=5.0, perdida=.35)}
    r = agregar.agregar(a, "completo")
    # media lineal (mezcla de las dos distribuciones), sin encogimiento adicional: ya va dentro de escenarios.py
    assert r["p_agg"]["E1"] == pytest.approx(0.70) and r["p_final"]["E1"] == pytest.approx(0.70)
    assert r["dispersion"]["E1"] == pytest.approx(0.20)
    assert r["p_final"]["E3"] == pytest.approx(0.11)
    assert r["exceso_anual_esperado_pp"] == pytest.approx(7.0)    # media
    assert r["perdida_escenario_bajista"] == pytest.approx(0.35)  # peor caso
    assert r["k"] == 0.4 and r["analistas"] == ["A", "B"]
    # salidas sin p neutral (antiguas): tasa base heurística de config.yaml
    assert r["tasa_base"] == 0.45 and r["tasa_base_tipo"] == "heuristica"


def test_tasa_base_calculada_con_el_escenario_neutral():
    a, b = esc("A"), esc("B")
    a["probabilidades_neutral"] = {"E0": .47, "E1": .44, "E2": .40, "E3": .08}
    b["probabilidades_neutral"] = {"E0": .47, "E1": .46, "E2": .40, "E3": .08}
    r = agregar.agregar({"A": a, "B": b}, "completo")
    assert r["tasa_base"] == pytest.approx(0.45) and r["tasa_base_tipo"] == "calculada"


def test_e3_se_limita_a_5_por_ciento():
    r = agregar.agregar({"A": esc("A", e3=.001), "B": esc("B", e3=.002)}, "completo")
    assert r["p_final"]["E3"] == 0.05


def test_un_solo_analista_no_agrega_ni_tiene_dispersion():
    r = agregar.agregar({"N": esc("N", e1=.66)}, "rapido")
    assert r["p_agg"]["E1"] == 0.66 and r["dispersion"]["E1"] is None and r["p_final"]["E1"] == 0.66


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
    r = ver(.75)
    assert r["veredicto"] == "atractiva" and all(r["condiciones"]["atractiva"].values())


def test_frontera_exacta_p_final_055():
    r = ver(.55)   # p_final = 0,55 exacto: debe contar como ≥ 0,55
    assert r["p_final"]["E1"] == pytest.approx(0.55) and r["veredicto"] == "atractiva"
    assert ver(.549)["veredicto"] == "neutral"


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
    r = ver(.39)
    assert r["veredicto"] == "no_atractiva" and r["p_final"]["E1"] == pytest.approx(0.39)
    assert ver(.40)["veredicto"] == "no_atractiva"         # frontera incluida
    assert ver(.42)["veredicto"] == "neutral"


def test_no_atractiva_por_dcf_inverso_sin_raiz_aunque_lo_demas_sea_atractivo():
    r = ver(.75, motor_=motor(sin_raiz=True))
    assert r["veredicto"] == "no_atractiva" and "sin raíz" in r["motivo_veredicto"]
    assert all(r["condiciones"]["atractiva"].values())     # precedencia de no_atractiva


def test_dcf_inverso_sin_raiz_por_precio_barato_no_penaliza():
    r = ver(.75, motor_=motor(sin_raiz=True, sentido="barato"))
    assert r["veredicto"] == "atractiva"


def test_no_atractiva_por_driver_con_z_mayor_que_3():
    assert ver(.75, motor_=motor(z=3.5))["veredicto"] == "no_atractiva"
    assert ver(.75, motor_=motor(z=3.0))["veredicto"] == "atractiva"      # z = 3 no es > 3
    r = ver(.75, motor_=motor(z=3.5))
    assert "crecimiento_ingresos (z=3.5)" in r["condiciones"]["detalle"]["z_altos"]


def test_sin_dcf_inverso_no_dispara_no_atractiva():
    a = {"A": esc("A", e1=.75), "B": esc("B", e1=.75)}
    r = agregar.agregar(a, "completo", reverse_dcf=None)
    assert r["veredicto"] == "atractiva" and r["condiciones"]["detalle"]["dcf_inverso_disponible"] is False


# ---------------------------------------------------------------- veredicto relativo a la p de partida

def con_partida(partida, e1, exceso=8.0, **kw):
    """Dos analistas con la p(E1) del escenario neutral (partida) y la p(E1) de la mezcla `e1`."""
    a = {}
    for n in ("A", "B"):
        s = esc(n, e1=e1, exceso=exceso, **kw)
        s["probabilidades_neutral"] = {"E0": partida, "E1": partida, "E2": partida, "E3": 0.1}
        a[n] = s
    return agregar.agregar(a, "completo", reverse_dcf=motor()["reverse_dcf"])


def test_el_veredicto_mide_la_ventaja_sobre_la_probabilidad_de_partida():
    # volatilidad baja (partida 0,45): atractiva desde 0,51 (= 0,45 + 0,06)
    assert con_partida(0.45, 0.51)["veredicto"] == "atractiva"
    assert con_partida(0.45, 0.50)["veredicto"] == "neutral"
    # volatilidad alta (partida 0,41): el 0,55 absoluto era inalcanzable; ahora basta 0,47
    assert con_partida(0.41, 0.47)["veredicto"] == "atractiva"
    assert con_partida(0.41, 0.46)["veredicto"] == "neutral"


def test_no_atractiva_tambien_es_relativa_y_una_accion_a_precio_justo_no_cae_ahi():
    # partida 0,41 (vol alta): precio justo (p = 0,41) debe ser neutral, no "no atractiva" por el 0,40 absoluto
    r = con_partida(0.41, 0.41)
    assert r["veredicto"] == "neutral"
    assert con_partida(0.41, 0.36)["veredicto"] == "no_atractiva"          # 0,41 − 0,05
    assert con_partida(0.41, 0.365)["veredicto"] == "neutral"
    assert "partida 0,41" in next(iter(r["condiciones"]["no_atractiva"]))


def test_el_exceso_y_la_perdida_siguen_siendo_obligatorios_para_atractiva():
    assert con_partida(0.45, 0.60, exceso=4.0)["veredicto"] == "neutral"
    assert con_partida(0.45, 0.60, perdida=0.60)["veredicto"] == "neutral"


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
    assert r["p_agg"]["E4"] == pytest.approx(0.50)


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

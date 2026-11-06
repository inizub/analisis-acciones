import json
from datetime import date, datetime, timezone

import pytest

import comun
import diario as dr
import gate
import validar
from artefactos import dp_completo, escribir_run, run, sintesis

AHORA = datetime(2026, 11, 6, 18, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------- fechas

@pytest.mark.parametrize("inicio,meses,esperado", [
    ("2026-11-06", 6, "2027-05-06"), ("2026-11-06", 12, "2027-11-06"), ("2026-11-06", 36, "2029-11-06"),
    ("2026-08-31", 6, "2027-02-28"), ("2027-08-31", 6, "2028-02-29"), ("2026-01-31", 1, "2026-02-28"),
    ("2026-12-15", 1, "2027-01-15"), ("2024-02-29", 12, "2025-02-28")])
def test_sumar_meses(inicio, meses, esperado):
    assert dr.sumar_meses(date.fromisoformat(inicio), meses).isoformat() == esperado


# ---------------------------------------------------------------- diario append-only

def reg(hash_prev=None, **kw):
    return {"id": "X-2026-11-06-a", "hash_prev": hash_prev, **kw}


def test_cadena_de_hashes(tmp_path):
    d = tmp_path / "diario" / "predicciones.jsonl"
    assert dr.ultimo_hash(d) is None and dr.verificar_cadena(d) == {"ok": True, "lineas": 0}
    r1 = dr.anexar(d, reg(None, n=1))
    h1 = dr.ultimo_hash(d)
    dr.anexar(d, reg(h1, n=2))
    texto = d.read_text(encoding="utf-8")
    primera = texto.split("\n")[0]
    assert h1 == comun.sha256_texto(primera) and r1["hash_prev"] is None
    assert dr.verificar_cadena(d) == {"ok": True, "lineas": 2}
    assert "\r" not in texto


def test_anexar_rechaza_hash_prev_incorrecto(tmp_path):
    d = tmp_path / "p.jsonl"
    dr.anexar(d, reg(None, n=1))
    with pytest.raises(ValueError, match="hash_prev"):
        dr.anexar(d, reg("sha256:" + "0" * 64, n=2))
    with pytest.raises(ValueError):
        dr.anexar(d, reg(None, n=3))                   # la primera línea ya existe
    assert len(dr.leer_lineas(d)) == 1


def test_verificar_detecta_manipulacion(tmp_path):
    d = tmp_path / "p.jsonl"
    dr.anexar(d, reg(None, n=1))
    dr.anexar(d, reg(dr.ultimo_hash(d), n=2))
    dr.anexar(d, reg(dr.ultimo_hash(d), n=3))
    lineas = d.read_text(encoding="utf-8").split("\n")
    lineas[0] = lineas[0].replace('"n":1', '"n":9')
    d.write_text("\n".join(lineas), encoding="utf-8")
    v = dr.verificar_cadena(d)
    assert v["ok"] is False and "línea 2" in v["error"]
    d.write_text("{roto\n", encoding="utf-8")
    assert "JSON inválido" in dr.verificar_cadena(d)["error"]


def test_siguiente_id(tmp_path):
    assert dr.siguiente_id([], "NU", "2026-11-06") == "NU-2026-11-06-a"
    regs = [{"id": "NU-2026-11-06-a"}, {"tipo": "update", "id": "NU-2026-11-06-a", "verdict": {"id": "NU-2026-11-06-b"}},
            {"tipo": "resolucion", "id": "NU-2026-11-06-a", "qid": "E1"}]
    assert dr.siguiente_id(regs, "NU", "2026-11-06") == "NU-2026-11-06-c"
    assert dr.siguiente_id(regs, "NU", "2026-11-07") == "NU-2026-11-07-a"
    assert dr.siguiente_id(regs, "AAPL", "2026-11-06") == "AAPL-2026-11-06-a"


# ---------------------------------------------------------------- preguntas

def test_construir_preguntas():
    cfg = comun.cargar_config()
    dp = dp_completo(fecha="2026-11-06")
    p_final = {"E0": .48, "E1": .5, "E2": .51, "E3": .12, "E4": .7}
    m = {"metrica": "crecimiento_ingresos", "valor_base": 0.08, "unidad": "ratio", "periodo": "FY2026"}
    qs = {q["qid"]: q for q in dr.construir_preguntas(dp, "2026-11-06", p_final, m, cfg)}
    assert list(qs) == ["E0", "E1", "E2", "E3", "E4"]
    assert [qs[k]["resolve_date"] for k in ("E0", "E1", "E2", "E3")] == ["2027-05-06", "2027-11-06", "2029-11-06", "2027-11-06"]
    assert qs["E4"]["resolve_date"] is None and all(q["p"] == p_final[k] for k, q in qs.items())
    assert qs["E1"]["texto"] == "RT(XYZ)-RT(VWCE.DE) en EUR > 0, 2026-11-06→2027-11-06"
    assert all(q["anular_si"] == ["opa", "delisting", "escision", "sin_datos"] for q in qs.values())
    assert qs["E1"]["detalle"] == {"tipo": "exceso_rt", "ticker_precio": "XYZ", "benchmark": "VWCE.DE",
                                   "fecha_ref": "2026-11-06", "meses": 12}
    assert qs["E3"]["detalle"]["umbral"] == -0.30 and "30 %" in qs["E3"]["texto"]
    e4 = qs["E4"]
    assert e4["texto"] == "Crecimiento de ingresos FY2026 ≥ 8,0 %"
    assert e4["detalle"]["ejercicio_objetivo"] == 2026 and e4["detalle"]["fin_ejercicio_esperado"] == "2026-12-31"
    assert e4["detalle"]["manual"] is False


def test_pregunta_e4_roe_y_hito_clinico():
    cfg = comun.cargar_config()
    dp = dp_completo()
    roe = dr.construir_preguntas(dp, "2026-11-06", {k: .5 for k in ("E0", "E1", "E2", "E3", "E4")},
                                 {"metrica": "roe", "valor_base": 0.21, "unidad": "ratio", "periodo": "FY2026"}, cfg)[-1]
    assert roe["texto"] == "ROE FY2026 ≥ 21,0 %"
    hito = dr.construir_preguntas(dp, "2026-11-06", {k: .5 for k in ("E0", "E1", "E2", "E3", "E4")},
                                  {"metrica": "hito_clinico", "valor_base": 3, "unidad": "fase", "periodo": "2027",
                                   "descripcion": "Inicio de Fase III"}, cfg)[-1]
    assert hito["detalle"]["manual"] is True and "Inicio de Fase III" in hito["texto"]
    assert hito["fuente_resolucion"].startswith("revisión manual")


# ---------------------------------------------------------------- ensamblado

def ensamblar(modo="completo", **ov):
    art = run(modo, **ov)
    return dr.ensamblar_verdict(art, modo, None, "XYZ-2026-11-06-a", None, "2026-11-06T18:00:00Z"), art


@pytest.mark.parametrize("modo", ["completo", "rapido", "degradado"])
def test_verdict_valido_en_cada_modo(modo):
    v, _ = ensamblar(modo)
    assert validar.validar_objeto(v, "verdict") == []
    assert v["skill"]["modo"] == modo and v["independencia"] is (modo != "degradado")
    assert v["veredicto"] == "atractiva" and len(v["preguntas"]) == 5
    assert v["motivo_veredicto"].startswith("Se cumplen")


def test_verdict_completo_incluye_red_team_y_ajustes():
    v, _ = ensamblar("completo")
    assert v["red_team"]["fuente"] == "claude"
    o = v["red_team"]["objeciones"][0]
    assert o["validada"] is True and o["dato_ref"] == "fundamentales.ingresos"
    assert o["ajuste"]["driver"] == "crecimiento_ingresos" and o["ajuste"]["valor_nuevo"] == 0.11
    assert {e["analista"] for e in v["valoracion"]["escenarios"]} == {"A", "B"} and len(v["valoracion"]["escenarios"]) == 6
    assert v["valoracion"]["escenarios"][0]["percentiles_tasa_base"] == {"crecimiento_ingresos": 40, "margen_operativo": 45}
    assert v["agregacion"]["p_A"]["E1"] == 0.75 and "p_N" not in v["agregacion"]
    assert v["valoracion"]["reverse_dcf"] == {"driver": "crecimiento_ingresos", "valor": 0.09, "percentil": 65.0, "sin_raiz": False}
    assert v["modelos"]["juez"] == "opus" and v["baselines"]["B1_E4"] == 0.6


def test_verdict_rapido_sin_red_team_ni_juez():
    v, _ = ensamblar("rapido")
    assert v["red_team"] == {"fuente": "ninguno", "objeciones": []}
    assert v["modelos"]["juez"] is None and v["modelos"]["red_team"] is None
    assert "p_N" in v["agregacion"] and v["agregacion"]["dispersion"]["E1"] is None


def test_rechazada_no_es_validada():
    s = sintesis()
    s["objeciones_verificadas"][0]["veredicto"] = "rechazada"
    v, _ = ensamblar("completo", sintesis=s)
    assert v["red_team"]["objeciones"][0]["validada"] is False


def test_checklist_fallido_da_no_analizable_sin_preguntas():
    dp = dp_completo()
    dp["fundamentales"]["caja"] = comun.desconocido("source_down")
    v, _ = ensamblar("completo", dp=dp)
    assert v["veredicto"] == "no_analizable" and v["preguntas"] == [] and v["valoracion"] is None
    assert "caja: desconocido (source_down)" in v["motivo_no_analizable"]
    assert v["checklist"]["pasa"] is False and validar.validar_objeto(v, "verdict") == []


def test_fuera_de_alcance_no_necesita_analistas():
    from artefactos import router
    art = run("completo", router=router("fuera_de_alcance"))
    art.update(agregado=None, escenarios={}, analistas={}, sintesis=None, forense=None, objeciones=None, baselines=None)
    v = dr.ensamblar_verdict(art, "completo", None, "XYZ-2026-11-06-a", None, "2026-11-06T18:00:00Z")
    assert v["veredicto"] == "no_analizable" and v["razones"] == [] and v["baselines"]["B0"] == 0.45
    assert validar.validar_objeto(v, "verdict") == []


def test_snapshot_con_precios_desconocidos():
    dp = dp_completo()
    dp["precios"] = comun.desconocido("source_down")
    v, _ = ensamblar("completo", dp=dp)
    assert v["input_snapshot"]["precio"]["valor"] is None and v["veredicto"] == "no_analizable"
    assert validar.validar_objeto(v, "verdict") == []


def test_modelos_explicitos_y_hashes():
    art = run("rapido")
    v = dr.ensamblar_verdict(art, "rapido", {"analista": "claude-sonnet-5-5"}, "XYZ-2026-11-06-a", None, "2026-11-06T18:00:00Z")
    assert v["modelos"]["analista"] == "claude-sonnet-5-5"
    assert v["skill"]["hash_config"] == comun.hash_config() and v["skill"]["hash_prompts"].startswith("sha256:")
    assert v["skill"]["version"] == "0.1.0"


# ---------------------------------------------------------------- cerrar

def test_cerrar_escribe_verdict_resumen_y_diario(tmp_path):
    d = escribir_run(tmp_path / "run", run("completo"))
    diario = tmp_path / "journal" / "diario" / "predicciones.jsonl"
    r = dr.cerrar(d, diario, "completo", ahora=AHORA)
    assert r["id"] == "XYZ-2026-11-06-a" and r["veredicto"] == "atractiva" and r["update_de"] is None
    v = json.loads((d / "verdict.json").read_text(encoding="utf-8"))
    assert validar.validar_archivo(d / "verdict.json") == ("verdict", [])
    assert v["created_at"] == "2026-11-06T18:00:00Z"
    registros = dr.leer_registros(diario)
    assert len(registros) == 1 and registros[0] == v and dr.verificar_cadena(diario)["ok"]
    resumen = (d / "resumen.md").read_text(encoding="utf-8")
    assert resumen.startswith("# XYZ: atractiva") and "No es asesoramiento financiero" in resumen
    assert len(resumen.split("\n")) <= 60                          # cabe en una página


def test_segundo_analisis_con_la_prediccion_abierta_es_un_update(tmp_path):
    diario = tmp_path / "p.jsonl"
    d1 = escribir_run(tmp_path / "r1", run("completo"))
    dr.cerrar(d1, diario, "completo", ahora=AHORA)
    d2 = escribir_run(tmp_path / "r2", run("completo"))
    r = dr.cerrar(d2, diario, "completo", ahora=AHORA)
    assert r["id"] == "XYZ-2026-11-06-b" and r["update_de"] == "XYZ-2026-11-06-a"
    regs = dr.leer_registros(diario)
    assert [dr.tipo(x) for x in regs] == ["prediccion", "update"]
    assert regs[1]["id"] == "XYZ-2026-11-06-a" and regs[1]["verdict"]["id"] == "XYZ-2026-11-06-b"
    assert regs[1]["hash_prev"] == comun.sha256_texto(dr.leer_lineas(diario)[0])
    assert dr.verificar_cadena(diario)["ok"]


def test_resuelta_la_anterior_el_nuevo_analisis_es_prediccion_nueva(tmp_path):
    diario = tmp_path / "p.jsonl"
    dr.cerrar(escribir_run(tmp_path / "r1", run("completo")), diario, "completo", ahora=AHORA)
    dr.anexar(diario, {"tipo": "resolucion", "id": "XYZ-2026-11-06-a", "qid": "E1", "hash_prev": dr.ultimo_hash(diario),
                       "estado": "resuelta", "resultado": 1})
    r = dr.cerrar(escribir_run(tmp_path / "r2", run("completo")), diario, "completo", ahora=AHORA)
    assert r["update_de"] is None and dr.tipo(dr.leer_registros(diario)[-1]) == "prediccion"


def test_no_analizable_nunca_es_update(tmp_path):
    diario = tmp_path / "p.jsonl"
    dr.cerrar(escribir_run(tmp_path / "r1", run("completo")), diario, "completo", ahora=AHORA)
    dp = dp_completo(); dp["fundamentales"]["caja"] = comun.desconocido("source_down")
    r = dr.cerrar(escribir_run(tmp_path / "r2", run("completo", dp=dp)), diario, "completo", ahora=AHORA)
    assert r["veredicto"] == "no_analizable" and r["update_de"] is None


def test_cerrar_no_escribe_nada_si_el_verdict_no_valida(tmp_path):
    art = run("completo")
    art["agregado"]["p_final"]["E1"] = 1.7                                 # probabilidad imposible
    d = escribir_run(tmp_path / "run", art)
    diario = tmp_path / "p.jsonl"
    with pytest.raises(ValueError, match="no valida"):
        dr.cerrar(d, diario, "completo", ahora=AHORA)
    assert not diario.exists() and not (d / "verdict.json").exists() and not (d / "resumen.md").exists()


def test_cerrar_exige_gate(tmp_path):
    art = run("completo")
    d = escribir_run(tmp_path / "run", art)
    (d / "gate.json").unlink()
    with pytest.raises(FileNotFoundError, match="gate"):
        dr.cerrar(d, tmp_path / "p.jsonl", "completo", ahora=AHORA)


def test_cerrar_acepta_gate_previo(tmp_path):
    """Un análisis imposible se cierra tras la fase previa, sin analistas ni escenarios."""
    dp = dp_completo(); dp["fundamentales"]["caja"] = comun.desconocido("source_down")
    art = run("completo", dp=dp)
    previo = gate.evaluar(art["dp"], art["router"], "completo", "previo")
    d = tmp_path / "run"
    d.mkdir()
    for nombre, obj in (("datapack.json", dp), ("router.json", art["router"]), ("gate_previo.json", previo)):
        (d / nombre).write_text(json.dumps(obj), encoding="utf-8")
    r = dr.cerrar(d, tmp_path / "p.jsonl", "completo", ahora=AHORA)
    assert r["veredicto"] == "no_analizable"
    v = json.loads((d / "verdict.json").read_text(encoding="utf-8"))
    assert v["preguntas"] == [] and "caja" in v["motivo_no_analizable"]
    assert "Por qué no se puede analizar" in (d / "resumen.md").read_text(encoding="utf-8")


def test_cli(tmp_path, capsys):
    d = escribir_run(tmp_path / "run", run("rapido"))
    diario = tmp_path / "p.jsonl"
    assert dr.main(["cerrar", "--dir", str(d), "--diario", str(diario), "--modo", "rapido",
                    "--modelos", '{"analista": "claude-sonnet-5-5"}']) == 0
    assert json.loads(capsys.readouterr().out)["id"] == "XYZ-2026-11-06-a"
    assert dr.main(["verificar", "--diario", str(diario)]) == 0
    assert dr.main(["resumen", "--verdict", str(d / "verdict.json")]) == 0
    assert "# XYZ" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        dr.main(["cerrar", "--dir", str(tmp_path / "vacio"), "--diario", str(diario), "--modo", "rapido"])

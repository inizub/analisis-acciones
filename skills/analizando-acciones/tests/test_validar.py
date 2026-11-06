import copy
import json

import pytest
from jsonschema import Draft202012Validator

import comun
import validar
from conftest import DIR_FIXTURES

EJEMPLOS = DIR_FIXTURES / "ejemplos"


def ejemplo(nombre):
    return json.loads((EJEMPLOS / nombre).read_text(encoding="utf-8"))


def test_hay_los_siete_esquemas_y_son_validos():
    assert validar.esquemas_disponibles() == ["ajustes", "analista", "datapack", "forense", "juez", "objeciones", "verdict"]
    for nombre in validar.esquemas_disponibles():
        esquema = comun.leer_json(comun.DIR_SCHEMAS / f"{nombre}.schema.json")
        assert esquema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        Draft202012Validator.check_schema(esquema)


@pytest.mark.parametrize("archivo,esquema", [
    ("datapack_base.json", "datapack"), ("datapack.json", "datapack"), ("analista_A.json", "analista"),
    ("analista_N.json", "analista"), ("analista_B1.json", "analista"), ("objeciones.json", "objeciones"),
    ("ajustes.json", "ajustes"), ("verdict.json", "verdict"), ("forense.json", "forense"), ("juez.json", "juez"),
    ("sintesis.json", "juez"), ("analista_C.json", None), ("otro.json", None),
])
def test_esquema_para(archivo, esquema):
    assert validar.esquema_para(f"runs/X/2026-11-06/{archivo}") == esquema


@pytest.mark.parametrize("archivo", ["analista_A.json", "objeciones.json", "ajustes.json", "verdict.json"])
def test_ejemplos_validos(archivo):
    esquema, errores = validar.validar_archivo(EJEMPLOS / archivo)
    assert errores == [], errores


def test_analista_probabilidades_no_suman_1():
    a = ejemplo("analista_A.json")
    a["escenarios"][0]["p"] = 0.3
    assert any("suman 1.050000" in e for e in validar.validar_objeto(a, "analista"))


def test_analista_bajista_sin_perdida():
    a = ejemplo("analista_A.json")
    del a["escenarios"][0]["perdida_permanente"]
    assert any("perdida_permanente" in e for e in validar.validar_objeto(a, "analista"))


def test_analista_escenarios_repetidos_y_drivers_distintos():
    a = ejemplo("analista_A.json")
    a["escenarios"][2]["nombre"] = "base"
    assert any("exactamente" in e for e in validar.validar_objeto(a, "analista"))
    a = ejemplo("analista_A.json")
    del a["escenarios"][1]["drivers"]["margen_operativo"]
    assert any("mismos drivers" in e for e in validar.validar_objeto(a, "analista"))


def test_analista_no_admite_probabilidades_de_eventos():
    a = ejemplo("analista_A.json")
    a["escenarios"][0]["p"] = 1.2
    assert validar.validar_objeto(a, "analista")


def test_analista_premortem_debe_tener_tres():
    a = ejemplo("analista_A.json")
    a["pre_mortem"] = a["pre_mortem"][:2]
    assert validar.validar_objeto(a, "analista")


def test_objecion_sin_dato_ref_invalida():
    o = ejemplo("objeciones.json")
    o["objeciones"][0]["dato_ref"] = ""
    assert any("dato_ref" in e for e in validar.validar_objeto(o, "objeciones"))
    o = ejemplo("objeciones.json")
    del o["objeciones"][0]["dato_ref"]
    assert validar.validar_objeto(o, "objeciones")


def test_objeciones_ids_duplicados():
    o = ejemplo("objeciones.json")
    o["objeciones"].append(copy.deepcopy(o["objeciones"][0]))
    assert any("duplicados" in e for e in validar.validar_objeto(o, "objeciones"))


def test_ajuste_sin_cambio():
    a = ejemplo("ajustes.json")
    a["ajustes"][0]["valor_nuevo"] = a["ajustes"][0]["valor_anterior"]
    assert any("igual" in e for e in validar.validar_objeto(a, "ajustes"))


def test_verdict_no_analizable_exige_motivo():
    v = ejemplo("verdict.json")
    v["veredicto"] = "no_analizable"
    assert validar.validar_objeto(v, "verdict")
    v["motivo_no_analizable"] = "ruta fuera de alcance"
    v["valoracion"] = None
    v["preguntas"] = []
    assert validar.validar_objeto(v, "verdict") == []


def test_verdict_checklist_fallido_exige_no_analizable():
    v = ejemplo("verdict.json")
    v["checklist"] = {"pasa": False, "fallos": ["6. pre-mortem ausente"]}
    assert any("checklist" in e for e in validar.validar_objeto(v, "verdict"))


def test_verdict_hash_prev_formato():
    v = ejemplo("verdict.json")
    v["hash_prev"] = "sha256:abc"
    assert validar.validar_objeto(v, "verdict")
    v["hash_prev"] = "sha256:" + "a" * 64
    assert validar.validar_objeto(v, "verdict") == []


def datapack_minimo():
    c = comun.cifra(1.0, "ratio", None, "https://x", "2026-11-05", "2026-11-06T00:00:00Z")
    return {
        "version_esquema": 1, "ticker": "XYZ", "fecha_analisis": "2026-11-06",
        "empresa": {"ticker": "XYZ", "nombre": "XYZ Inc", "sic": 7372, "taxonomia": "us-gaap", "anios_estados": 5},
        "fundamentales": {"ingresos": {"concepto": "Revenues", "serie": [c]}, "inventario": comun.desconocido("not_covered")},
        "precios": {"moneda": "USD", "precio": c, "precio_eur": c, "fx_eur": c, "antiguedad_dias": 1, "metricas_eur": {"vol_rel_3a": c}},
        "campos_desconocidos": [{"campo": "inventario", "causa": "not_covered"}],
        "fuentes": [{"url": "https://x"}],
    }


def test_datapack_minimo_valido():
    assert validar.validar_objeto(datapack_minimo(), "datapack") == []


def test_datapack_desconocido_no_declarado():
    d = datapack_minimo()
    d["campos_desconocidos"] = []
    assert any("no listado" in e for e in validar.validar_objeto(d, "datapack"))


def test_datapack_cifra_sin_fuente_o_mezclada():
    d = datapack_minimo()
    del d["fundamentales"]["ingresos"]["serie"][0]["fuente_url"]
    assert validar.validar_objeto(d, "datapack")
    d = datapack_minimo()
    d["precios"]["precio"]["desconocido"] = True  # cifra con valor y marcada desconocida
    assert validar.validar_objeto(d, "datapack")


def test_datapack_causa_invalida():
    d = datapack_minimo()
    d["fundamentales"]["inventario"] = {"desconocido": True, "causa": "lo_estimo_yo"}
    assert validar.validar_objeto(d, "datapack")


def test_datapack_nota_larga_rechazada():
    d = datapack_minimo()
    d["hechos_recientes"] = [{"fecha": "2026-11-01", "resumen": "x" * 601, "fuente_url": "https://x"}]
    assert validar.validar_objeto(d, "datapack")


def test_cli(tmp_path, capsys):
    p = tmp_path / "analista_B.json"
    a = ejemplo("analista_A.json")
    a["encuadre"] = "B"
    p.write_text(json.dumps(a), encoding="utf-8")
    assert validar.main([str(p)]) == 0
    a["escenarios"][0]["p"] = 0.9
    p.write_text(json.dumps(a), encoding="utf-8")
    assert validar.main([str(p)]) == 1
    salida = capsys.readouterr().out
    assert '"valido": false' in salida and "suman" in salida
    assert validar.main([str(tmp_path / "raro.json")]) == 3
    (tmp_path / "verdict.json").write_text("{no json", encoding="utf-8")
    assert validar.main([str(tmp_path / "verdict.json")]) == 3


def test_forense_y_juez_validos_y_con_errores():
    from artefactos import forense, sintesis
    assert validar.validar_objeto(forense(), "forense") == []
    assert validar.validar_objeto(sintesis(), "juez") == []
    f = forense()
    f["banderas"][0]["nivel"] = "critica"
    assert validar.validar_objeto(f, "forense")
    f = forense()
    del f["banderas"][0]["dato_ref"]
    assert validar.validar_objeto(f, "forense")
    s = sintesis()
    s["razones"] = s["razones"][:2]
    assert validar.validar_objeto(s, "juez")
    s = sintesis()
    s["objeciones_verificadas"][0]["veredicto"] = "dudosa"
    assert validar.validar_objeto(s, "juez")
    s = sintesis()
    s["criterios_invalidacion"] = []
    assert validar.validar_objeto(s, "juez") == []        # el mínimo de 2 lo exige el checklist, no el esquema

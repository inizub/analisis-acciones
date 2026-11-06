import pytest

import comun
import router
from dp_sintetico import crecer, datapack, segmento

MM = 1_000_000_000  # ventas del orden de 10.000 M$ (clase 10000-50000)
TABLA = ()  # sin tabla: la regla de crecimiento no se evalúa


def clasificar(dp):
    return router.clasificar(dp, tabla=TABLA)


def dp_general(**kw):
    ing = crecer(10 * MM, 0.03, 10)
    base = dict(ingresos=ing, beneficio_operativo=[i * 0.15 for i in ing])
    base.update(kw)
    return datapack(**base)


def test_general_por_defecto():
    r = clasificar(dp_general())
    assert (r["ruta"], r["confianza"], r["requiere_confirmacion"]) == ("general", "alta", False)
    assert r["metrica_e4"] == "crecimiento_ingresos" and r["candidatas"] == []


@pytest.mark.parametrize("sic,motivo", [(6798, "REIT"), (6311, "aseguradora"), (6770, "SPAC"), (6726, "fondo")])
def test_fuera_de_alcance_por_sic(sic, motivo):
    r = clasificar(dp_general(sic=sic))
    assert r["ruta"] == "fuera_de_alcance" and r["confianza"] == "alta" and motivo in r["motivo"]
    assert r["metrica_e4"] is None


def test_fuera_de_alcance_por_pocos_anios_y_concurso():
    assert clasificar(datapack(ingresos=[10.0, 12.0]))["ruta"] != "fuera_de_alcance"  # 2 años: justo el mínimo
    r = clasificar(datapack(ingresos=[10.0]))
    assert r["ruta"] == "fuera_de_alcance" and "1 años" in r["motivo"]
    r = clasificar(dp_general(empresa_extra={"en_concurso": True}))
    assert r["ruta"] == "fuera_de_alcance" and "concurso" in r["motivo"]


def test_banco_con_y_sin_datos_bancarios():
    con = clasificar(dp_general(sic=6199, prestamos=crecer(5 * MM, .1, 10), depositos=crecer(8 * MM, .1, 10)))
    assert (con["ruta"], con["confianza"]) == ("banco_credito", "alta") and con["metrica_e4"] == "roe"
    sin = clasificar(dp_general(sic=6199))
    assert sin["ruta"] == "banco_credito" and sin["confianza"] == "media" and not sin["requiere_confirmacion"]


def test_biotech_por_ingresos_de_producto():
    pequena = clasificar(datapack(sic=2836, ingresos=[1e6, 2e6, 30e6], beneficio_operativo=[-5e7, -6e7, -7e7]))
    assert pequena["ruta"] == "biotech_precomercial" and pequena["metrica_e4"] == "hito_clinico"
    grande = clasificar(dp_general(sic=2836))
    assert grande["ruta"] == "general"  # 10.000 M$ de ingresos: biotech comercial
    otra_moneda = clasificar(datapack(sic=2836, moneda="EUR", ingresos=[1e6, 2e6, 3e6]))
    assert otra_moneda["ruta"] == "biotech_precomercial" and otra_moneda["confianza"] == "baja"


def test_crecimiento_perdidas_por_ebit_negativo():
    ing = crecer(1 * MM, 0.4, 6)
    r = clasificar(datapack(ingresos=ing, beneficio_operativo=[1e7, 2e7, 5e6, -3e7, 1e7, 2e7]))
    assert r["ruta"] == "general"  # solo 1 de los 3 últimos ejercicios con EBIT negativo
    r = clasificar(datapack(ingresos=ing, beneficio_operativo=[1e7, 2e7, 5e6, -3e7, -2e7, -5e6]))
    assert r["ruta"] == "crecimiento_perdidas" and r["confianza"] == "alta"
    assert r["evidencia"]["ebit_negativo_ultimos"] == "3 de 3"


def test_crecimiento_perdidas_por_crecimiento_sobre_p90():
    tabla = ({"metrica": "crecimiento_ventas_5a", "clase_musd": "todas", "sector": "todos", "media": 0.06, "desv": 0.12,
              "n": 1000, "p90": 0.20, "p10": None, "p25": None, "p50": None, "p75": None, "fuente": "x", "periodo": "x"},)
    ing = crecer(1 * MM, 0.30, 7)
    dp = datapack(ingresos=ing, beneficio_operativo=[i * 0.1 for i in ing])
    r = router.clasificar(dp, tabla=tabla)
    assert r["ruta"] == "crecimiento_perdidas" and r["candidatas"][0]["fuerza"] == "media"
    assert r["confianza"] == "media"
    ing_lento = crecer(1 * MM, 0.05, 7)
    r = router.clasificar(datapack(ingresos=ing_lento, beneficio_operativo=[i * 0.1 for i in ing_lento]), tabla=tabla)
    assert r["ruta"] == "general"


def test_ciclica_por_sic_y_por_margen():
    ing = crecer(10 * MM, 0.02, 10)
    estable = [i * 0.10 for i in ing]
    volatil = [i * m for i, m in zip(ing, [0.02, 0.18, 0.04, 0.20, -0.02, 0.16, 0.05, 0.19, 0.03, 0.17])]
    # SIC cíclico + margen volátil → alta
    r = clasificar(datapack(sic=3674, ingresos=ing, beneficio_operativo=volatil))
    assert r["ruta"] == "ciclica" and r["confianza"] == "alta"
    # SIC cíclico + margen estable → media
    r = clasificar(datapack(sic=3674, ingresos=ing, beneficio_operativo=estable))
    assert r["ruta"] == "ciclica" and r["confianza"] == "media"
    # SIC no cíclico + margen volátil → media
    r = clasificar(datapack(sic=7372, ingresos=ing, beneficio_operativo=volatil))
    assert r["ruta"] == "ciclica" and r["confianza"] == "media"
    # menos de 7 años: no se evalúa el margen
    r = clasificar(datapack(sic=7372, ingresos=ing[-6:], beneficio_operativo=volatil[-6:]))
    assert r["ruta"] == "general"


def test_holding():
    segs = [segmento("A", 40), segmento("B", 35), segmento("C", 20), segmento("D", 5)]
    r = clasificar(dp_general(segmentos=segs))
    assert r["ruta"] == "holding" and r["confianza"] == "media" and len(r["evidencia"]["segmentos_materiales"]) == 3
    solo_dos = [segmento("A", 60), segmento("B", 35), segmento("C", 5)]
    assert clasificar(dp_general(segmentos=solo_dos))["ruta"] == "general"
    geo = [segmento("EE. UU.", 40, "geografia"), segmento("UE", 35, "geografia"), segmento("Asia", 25, "geografia")]
    assert clasificar(dp_general(segmentos=geo))["ruta"] == "general"
    declarada = clasificar(dp_general(empresa_extra={"holding_declarada": True}))
    assert declarada["ruta"] == "holding" and declarada["confianza"] == "alta"


def test_conflicto_baja_confianza_y_prioridad():
    ing = crecer(10 * MM, 0.02, 10)
    volatil = [i * m for i, m in zip(ing, [0.02, 0.18, 0.04, 0.20, -0.02, 0.16, 0.05, -0.19, -0.03, -0.17])]
    r = clasificar(datapack(sic=3674, ingresos=ing, beneficio_operativo=volatil))
    assert r["ruta"] == "crecimiento_perdidas"  # prioridad sobre ciclica
    assert r["alternativas"] == ["ciclica"] and r["confianza"] == "baja" and r["requiere_confirmacion"]


def test_empresa_desconocida_y_huecos():
    dp = datapack(ingresos=crecer(MM, .05, 5))
    dp["empresa"] = comun.desconocido("not_covered", "no está en la SEC")
    r = router.clasificar(dp, tabla=TABLA)
    assert r["ruta"] == "general" and r["confianza"] == "baja" and r["requiere_confirmacion"]
    sin_ingresos = clasificar(datapack(sic=7372, anios=10))
    assert "ingresos" in sin_ingresos["huecos"] and sin_ingresos["confianza"] == "baja"


def test_confirmar_reglas():
    ing = crecer(10 * MM, 0.02, 10)
    volatil = [i * m for i, m in zip(ing, [0.02, 0.18, 0.04, 0.20, -0.02, 0.16, 0.05, -0.19, -0.03, -0.17])]
    rt = clasificar(datapack(sic=3674, ingresos=ing, beneficio_operativo=volatil))
    assert router.confirmar(rt, None)["cambio"] is False
    assert router.confirmar(rt, rt["ruta"], "x")["cambio"] is False
    ok = router.confirmar(rt, "ciclica", "fundamentales.beneficio_operativo", "margen estable salvo 2 años")
    assert ok["cambio"] and ok["ruta"] == "ciclica" and ok["metrica_e4"] == "crecimiento_ingresos"
    assert router.confirmar(rt, "ciclica", "")["cambio"] is False
    assert router.confirmar(rt, "banco_credito", "fundamentales.depositos")["cambio"] is False  # no candidata
    assert router.confirmar(rt, "inventada", "x")["cambio"] is False
    assert router.confirmar(rt, "general", "fundamentales.ingresos")["cambio"] is True  # general siempre es válida
    fuera = clasificar(dp_general(sic=6798))
    assert router.confirmar(fuera, "general", "fundamentales.ingresos")["cambio"] is False


def test_cli(tmp_path):
    import json
    (tmp_path / "dp.json").write_text(json.dumps(dp_general()), encoding="utf-8")
    assert router.main(["clasificar", "--datapack", str(tmp_path / "dp.json"), "--salida", str(tmp_path / "r.json")]) == 0
    assert json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))["ruta"] == "general"
    assert router.main(["confirmar", "--router", str(tmp_path / "r.json"), "--propuesta", "general"]) == 0

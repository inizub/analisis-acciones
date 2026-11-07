import json
from pathlib import Path

import pytest

import comun
import diario as dr
import ejecucion
import validar
from artefactos import cifra, dp_completo, ejemplo, sintesis

MACRO = {"generado": "2026-11-06T00:00:00Z", "rf_usd": {"valor": 0.045}, "rf_eur": {"valor": 0.030},
         "tipos": {"etiqueta": "subiendo"}, "credito": {"etiqueta": "relajado"}, "curva": {"etiqueta": "normal"}}


# ---------------------------------------------------------------- entrada

@pytest.mark.parametrize("texto,ticker,modo,ignorado", [
    ("NU", "NU", "completo", False), ("nu rapido", "NU", "rapido", False), ("NU rápido", "NU", "rapido", False),
    ("AAPL completo", "AAPL", "completo", False), ("brk.b", "BRK.B", "completo", False),
    ("NU rapido creo que va a subir mucho, analízala bien", "NU", "rapido", True),
    ("MSFT me encanta esta empresa", "MSFT", "completo", True)])
def test_parsear_entrada(texto, ticker, modo, ignorado):
    assert ejecucion.parsear_entrada(texto) == {"ticker": ticker, "modo": modo, "ignorado": ignorado}


@pytest.mark.parametrize("texto", ["", "   ", "¿qué opinas de NU?", "una-cadena-demasiado-larga-para-ser-un-ticker"])
def test_entrada_sin_ticker(texto):
    with pytest.raises(ValueError):
        ejecucion.parsear_entrada(texto)


def test_iniciar_crea_directorio_y_ejecucion_activa(tmp_path):
    r = ejecucion.iniciar("NU rapido me gusta", tmp_path / "journal", "2026-11-06")
    d = Path(r["run_dir"])
    assert d.is_dir() and d.parts[-3:] == ("runs", "NU", "2026-11-06") and r["texto_ignorado"] is True
    activa = ejecucion.leer_activa()
    assert activa["ticker"] == "NU" and activa["modo"] == "rapido" and activa["fase"] == "datos"
    assert "me gusta" not in json.dumps(activa)                   # el comentario no se guarda en ningún sitio
    assert ejecucion.cambiar_fase("ciega")["fase"] == "ciega"
    (d / "verdict.json").write_text("{}", encoding="utf-8")         # ejecución ya cerrada ese día
    r2 = ejecucion.iniciar("NU", tmp_path / "journal", "2026-11-06")
    assert Path(r2["run_dir"]).name == "2026-11-06-b"
    assert ejecucion.terminar()["terminada"] == r2["run_dir"] and ejecucion.leer_activa() is None
    with pytest.raises(ValueError):
        ejecucion.cambiar_fase("juez")


# ---------------------------------------------------------------- fusión del datapack

def test_fusionar_rellena_huecos_sin_tocar_edgar():
    base = dp_completo()
    base["fundamentales"]["inventario"] = comun.desconocido("not_covered")
    base["campos_desconocidos"] = [{"campo": "inventario", "causa": "not_covered"}]
    agente = {
        "fundamentales": {"inventario": cifra(5e8, "unidades", "USD", "2025-12-31"),
                          "ingresos": cifra(1.0, "unidades", "USD", "2025-12-31")},          # EDGAR ya lo tiene
        "banca": {"cet1": cifra(0.14)}, "segmentos": [], "hechos_recientes": [
            {"fecha": "2026-10-30", "tipo": "resultados", "resumen": "Resultados del T3", "fuente_url": "https://ir"}],
        "empresa": {"ratio_adr": cifra(1.0, "acciones"), "nombre": "Otro nombre"},
        "no_encontrados": [{"campo": "guidance", "causa": "not_covered"}],
        "fuentes": [{"url": "https://ir", "retrieved_at": "2026-11-06T10:00:00Z"}]}
    dp, avisos = ejecucion.fusionar_datapack(base, agente)
    assert dp["fundamentales"]["inventario"]["serie"][0]["valor"] == 5e8
    assert dp["fundamentales"]["ingresos"]["serie"][-1]["valor"] != 1.0
    assert any("ingresos" in a for a in avisos) and any("empresa.nombre" in a for a in avisos)
    assert dp["empresa"]["nombre"] == "XYZ Inc" and dp["empresa"]["ratio_adr"]["valor"] == 1.0
    assert dp["banca"]["cet1"]["valor"] == 0.14 and len(dp["hechos_recientes"]) == 1
    assert {"campo": "guidance", "causa": "not_covered"} in dp["campos_desconocidos"]
    assert not any(x["campo"] == "inventario" for x in dp["campos_desconocidos"])
    assert dp["fuentes"][-1]["url"] == "https://ir"
    assert validar.validar_objeto(dp, "datapack") == []


def test_fusionar_reemplaza_series_desactualizadas():
    base = dp_completo()
    base["fundamentales"]["gasto_intereses"]["desactualizada"] = True
    dp, _ = ejecucion.fusionar_datapack(base, {"fundamentales": {"gasto_intereses": cifra(3e8, "unidades", "USD", "2025-12-31")}})
    assert dp["fundamentales"]["gasto_intereses"]["serie"][-1]["valor"] == 3e8


def test_fusionar_detecta_cifras_mal_formadas(tmp_path):
    (tmp_path / "datapack_base.json").write_text(json.dumps(dp_completo()), encoding="utf-8")
    (tmp_path / "datos_agente.json").write_text(json.dumps({"banca": {"cet1": {"valor": 0.14}}}), encoding="utf-8")
    r = ejecucion.fusionar(tmp_path, comprobar=True)
    assert r["valido"] is False and r["errores"] and not (tmp_path / "datapack.json").exists()
    (tmp_path / "datos_agente.json").write_text(json.dumps({"banca": {"cet1": cifra(0.14)}}), encoding="utf-8")
    r = ejecucion.fusionar(tmp_path)
    assert r["valido"] and (tmp_path / "datapack.json").exists() and r["ruta_provisional"] == "general"


def test_insertar_tasas_base_las_pone_primero():
    dp = ejecucion.insertar_tasas_base({"ticker": "X", "tasas_base": {"viejo": 1}, "empresa": {}}, {"nuevo": 2})
    assert list(dp)[0] == "tasas_base" and dp["tasas_base"] == {"nuevo": 2} and list(dp)[1:] == ["ticker", "empresa"]


# ---------------------------------------------------------------- flujo completo sin red

def preparar_run(tmp_path, modo="rapido", dp=None):
    r = ejecucion.iniciar(f"XYZ {modo}", tmp_path / "journal", "2026-11-06")
    d = Path(r["run_dir"])
    (d / "datapack_base.json").write_text(json.dumps(dp or dp_completo()), encoding="utf-8")
    (d / "macro_regime.json").write_text(json.dumps(MACRO), encoding="utf-8")
    return d


def test_flujo_rapido_de_codigo_a_diario(tmp_path):
    d = preparar_run(tmp_path)
    res = ejecucion.codigo(d, "rapido")
    assert res["ruta"] == "general" and res["gate_previo"]["pasa"] and res["siguiente"] == "fase ciega"
    for f in ("datapack.json", "router.json", "forense_metricas.json", "gate_previo.json", "motor_inicial.json"):
        assert (d / f).exists(), f
    assert list(comun.leer_json(d / "datapack.json"))[0] == "tasas_base"
    a = ejemplo("analista_A.json")
    a["encuadre"] = "N"
    (d / "analista_N.json").write_text(json.dumps(a), encoding="utf-8")
    hechos = ejecucion.ejecutar_escenarios(d, "rapido")
    assert set(hechos) == {"N", "cierre_anticipado"} and hechos["cierre_anticipado"] is False
    esc = comun.leer_json(d / "escenarios_N.json")
    assert "percentiles_codigo" in esc and "crecimiento_ingresos" in esc["percentiles_codigo"]["base"]
    (d / "sintesis.json").write_text(json.dumps(sintesis()), encoding="utf-8")
    cierre = ejecucion.cerrar(d, "rapido", tmp_path / "journal")
    assert cierre["veredicto"] in ("atractiva", "neutral", "no_atractiva")
    v = comun.leer_json(d / "verdict.json")
    assert validar.validar_objeto(v, "verdict") == [] and v["skill"]["modo"] == "rapido"
    assert v["valoracion"]["escenarios"][0]["percentiles_tasa_base"]["crecimiento_ingresos"] is not None
    diario = tmp_path / "journal" / "diario" / "predicciones.jsonl"
    assert dr.verificar_cadena(diario)["ok"] and len(dr.leer_registros(diario)) == 1
    assert (d / "resumen.md").exists() and ejecucion.leer_activa() is None


def test_ticker_con_datos_criticos_que_faltan_se_cierra_tras_el_codigo(tmp_path):
    dp = dp_completo()
    dp["fundamentales"]["caja"] = comun.desconocido("not_covered")
    dp["campos_desconocidos"] = [{"campo": "caja", "causa": "not_covered"}]
    d = preparar_run(tmp_path, dp=dp)
    res = ejecucion.codigo(d, "rapido")
    assert res["gate_previo"]["pasa"] is False and "no_analizable" in res["siguiente"]
    assert not (d / "motor_inicial.json").exists()
    cierre = ejecucion.cerrar(d, "rapido", tmp_path / "journal")
    assert cierre["veredicto"] == "no_analizable"
    assert "caja" in comun.leer_json(d / "verdict.json")["motivo_no_analizable"]


def test_error_del_motor_da_un_motivo_claro(tmp_path):
    dp = dp_completo()
    dp["empresa"]["moneda_informe"] = "JPY"
    d = preparar_run(tmp_path, dp=dp)
    res = ejecucion.codigo(d, "rapido", motor_fx=lambda m: 160.0)
    assert "JPY" in res["error_motor"] and "error" in comun.leer_json(d / "motor_inicial.json")
    cierre = ejecucion.cerrar(d, "rapido", tmp_path / "journal")
    v = comun.leer_json(d / "verdict.json")
    assert cierre["veredicto"] == "no_analizable" and "JPY" in v["motivo_no_analizable"]


def test_confirmar_ruta_y_codigo_respeta_la_confirmacion(tmp_path):
    d = preparar_run(tmp_path)
    ejecucion.codigo(d, "rapido")
    r = ejecucion.confirmar_ruta(d, "banco_credito", "fundamentales.depositos", "es un banco")
    assert r["cambio"] is False and r["repetir_codigo"] is False                 # no era candidata
    rt = comun.leer_json(d / "router.json")
    assert rt["confirmada"] is True and rt["ruta"] == "general"
    rt["ruta"] = "ciclica"                                                        # simula un cambio aceptado
    (d / "router.json").write_text(json.dumps(rt), encoding="utf-8")
    assert ejecucion.codigo(d, "rapido")["ruta"] == "ciclica"


def test_hashes_de_la_fase_ciega(tmp_path):
    d = preparar_run(tmp_path, "completo")
    ejecucion.codigo(d, "completo")
    for n in ("A", "B"):
        a = ejemplo("analista_A.json")
        a["encuadre"] = n
        (d / f"analista_{n}.json").write_text(json.dumps(a), encoding="utf-8")
    h = ejecucion.congelar(d)
    assert set(h) == {"analista_A.json", "analista_B.json"} and ejecucion.verificar_congelados(d) == []
    a = comun.leer_json(d / "analista_A.json")
    a["narrativa"] += " Modificado después de congelar."
    (d / "analista_A.json").write_text(json.dumps(a), encoding="utf-8")
    assert ejecucion.verificar_congelados(d) == ["analista_A.json"]
    with pytest.raises(ValueError, match="modificadas"):
        ejecucion.cerrar(d, "completo", tmp_path / "journal")


def test_escenarios_con_ajustes_guarda_la_version_sin_ajustes(tmp_path):
    d = preparar_run(tmp_path, "completo")
    ejecucion.codigo(d, "completo")
    for n in ("A", "B"):
        a = ejemplo("analista_A.json")
        a["encuadre"] = n
        (d / f"analista_{n}.json").write_text(json.dumps(a), encoding="utf-8")
    (d / "ajustes.json").write_text(json.dumps(ejemplo("ajustes.json")), encoding="utf-8")
    hechos = ejecucion.ejecutar_escenarios(d, "completo")
    assert hechos["A"]["ajustes"] == 1 and "ajustes" not in hechos["B"] or hechos["B"].get("ajustes", 0) == 0
    assert (d / "escenarios_A_sin_ajustes.json").exists()
    con = comun.leer_json(d / "escenarios_A.json")
    assert con["ajustes_aplicados"][0]["objecion_ref"] == "O1"


def test_datos_con_clientes_simulados(tmp_path, fixture, cache_tmp):
    from test_datapack_base import clientes
    r = ejecucion.iniciar("NU rapido", tmp_path / "journal", "2026-11-06")
    d = Path(r["run_dir"])
    c = clientes(fixture, cache_tmp)
    c["sin_macro"] = True
    res = ejecucion.datos(d, clientes=c)
    assert (d / "datapack_base.json").exists() and res["ticker"] == "NU"
    assert res["ruta_provisional"] == "banco_credito" and res["ticker_inexistente"] is False
    assert any("banca/cet1" in f for f in res["campos_criticos_faltan"]) and res["necesita_agente_datos"] is True


def test_trimestres_pendientes_si_la_base_anual_es_antigua_y_no_hay_trimestres():
    from test_inicial import _dp_con_trimestres
    dp, _, _ = _dp_con_trimestres()                                  # ejercicio al 2025-12-31 y trimestres hasta 2026-06-30
    dp["fecha_analisis"] = "2026-11-06"
    assert ejecucion.trimestres_pendientes(dp) is False              # ya trae los trimestres
    del dp["trimestrales"]
    assert ejecucion.trimestres_pendientes(dp) is True               # 10 meses sin trimestres
    dp["fecha_analisis"] = "2026-03-01"
    assert ejecucion.trimestres_pendientes(dp) is False              # base de hace 2 meses: no hace falta


def test_cli(tmp_path, capsys):
    assert ejecucion.main(["iniciar", "--entrada", "XYZ rapido", "--journal", str(tmp_path / "j"), "--fecha", "2026-11-06"]) == 0
    assert json.loads(capsys.readouterr().out)["modo"] == "rapido"
    assert ejecucion.main(["estado"]) == 0 and "XYZ" in capsys.readouterr().out
    assert ejecucion.main(["fase", "--fase", "ciega"]) == 0
    assert ejecucion.main(["terminar"]) == 0
    with pytest.raises(SystemExit):
        ejecucion.main(["iniciar", "--entrada", "¿?", "--journal", str(tmp_path / "j")])


@pytest.mark.parametrize("valor", ["", "${user_config.journal_dir}", "$JOURNAL"])
def test_journal_sin_configurar_usa_el_defecto(valor):
    j, aviso = ejecucion.resolver_journal(valor)
    assert j == Path.home() / "analisis-acciones" / "journal" and "no está configurado" in aviso
    assert ejecucion.resolver_journal("C:/diario") == (Path("C:/diario"), None)


def test_auditar_traza_detecta_lecturas_cruzadas(tmp_path):
    d = tmp_path
    lineas = [
        {"agent_type": "analisis-acciones:analista-fundamental", "tool": "Read", "args_resumidos": {"file_path": str(d / "datapack.json")}},
        {"agent_type": "analisis-acciones:analista-fundamental", "tool": "Read", "args_resumidos": {"file_path": str(d / "analista_B.json")}},
        {"agent_type": "analisis-acciones:red-team", "tool": "Read", "args_resumidos": {"file_path": str(d / "analista_B.json")}},
        {"agent_type": "principal", "tool": "Read", "args_resumidos": {"file_path": str(d / "juez.json")}}]
    (d / "traza.jsonl").write_text("\n".join(json.dumps(l) for l in lineas) + "\nno-json\n", encoding="utf-8")
    v = ejecucion.auditar_traza(d)
    assert len(v) == 1 and v[0]["archivo"] == "analista_B.json" and v[0]["agente"] == "analista-fundamental"
    assert ejecucion.auditar_traza(tmp_path / "vacio") == []


def test_lectura_cruzada_quita_la_independencia(tmp_path):
    d = preparar_run(tmp_path)
    ejecucion.codigo(d, "rapido")
    a = ejemplo("analista_A.json")
    a["encuadre"] = "N"
    (d / "analista_N.json").write_text(json.dumps(a), encoding="utf-8")
    ejecucion.ejecutar_escenarios(d, "rapido")
    (d / "sintesis.json").write_text(json.dumps(sintesis()), encoding="utf-8")
    (d / "traza.jsonl").write_text(json.dumps({"agent_type": "analisis-acciones:forense", "tool": "Read",
                                               "args_resumidos": {"file_path": str(d / "analista_N.json")}}) + "\n", encoding="utf-8")
    r = ejecucion.cerrar(d, "rapido", tmp_path / "journal")
    assert r["lecturas_cruzadas"] and comun.leer_json(d / "verdict.json")["independencia"] is False


def test_fuera_de_alcance_no_lanza_el_agente_de_datos(tmp_path, fixture, cache_tmp, monkeypatch):
    from datos import datapack_base
    r = ejecucion.iniciar("O completo", tmp_path / "journal", "2026-11-06")
    dp = dp_completo(sic=6798)
    monkeypatch.setattr(datapack_base, "construir", lambda *a, **k: (dp, None))
    res = ejecucion.datos(Path(r["run_dir"]), clientes={"sin_macro": True})
    assert res["fuera_de_alcance"] is True and res["necesita_agente_datos"] is False

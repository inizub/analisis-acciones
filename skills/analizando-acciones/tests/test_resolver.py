import json
from datetime import date, datetime, timezone

import numpy as np
import pandas as pd
import pytest

import comun
import diario as dr
import resolver
from artefactos import dp_completo, escribir_run, run

AHORA = datetime(2026, 11, 6, 18, 0, tzinfo=timezone.utc)
D = date.fromisoformat


def serie(inicio, fin, f):
    """Serie de días hábiles con valor f(i)."""
    idx = pd.bdate_range(inicio, fin)
    return pd.Series([f(i) for i in range(len(idx))], index=idx, dtype="float64")


class ProveedorFalso:
    def __init__(self, acc=None, bench=None, fund=None, error_precios=None, error_fund=None):
        self.acc, self.bench, self.fund = acc, bench, fund
        self.error_precios, self.error_fund = error_precios, error_fund
        self.llamadas_fund = 0

    def series_eur(self, ticker, benchmark):
        if self.error_precios:
            raise self.error_precios
        return self.acc, self.bench

    def fundamentales(self, ticker):
        self.llamadas_fund += 1
        if self.error_fund:
            raise self.error_fund
        return self.fund


def pregunta(qid="E1", ref="2026-11-06", fin="2027-11-06", tipo="exceso_rt", **extra):
    d = {"tipo": tipo, "ticker_precio": "XYZ", "benchmark": "VWCE.DE", "fecha_ref": ref}
    d.update(extra)
    return {"qid": qid, "resolve_date": fin, "detalle": d}


# ---------------------------------------------------------------- piezas puras

def test_cobertura():
    s = serie("2026-01-01", "2027-11-08", lambda i: 100.0)
    assert resolver.cobertura([s], D("2026-11-06"), D("2027-11-06"), D("2027-11-20"), 7) == ("ok", "")
    corta = serie("2026-01-01", "2027-10-29", lambda i: 100.0)           # termina 8 días antes
    est, _ = resolver.cobertura([corta], D("2026-11-06"), D("2027-11-06"), D("2027-11-08"), 7)
    assert est == "pendiente"                                            # aún dentro del plazo de espera
    est, motivo = resolver.cobertura([corta], D("2026-11-06"), D("2027-11-06"), D("2027-11-13"), 7)
    assert est == "sin_datos" and "OPA" in motivo
    tarde = serie("2026-12-01", "2027-11-08", lambda i: 100.0)
    assert resolver.cobertura([tarde], D("2026-11-06"), D("2027-11-06"), D("2027-11-20"), 7)[0] == "sin_datos"
    assert resolver.cobertura([pd.Series(dtype=float)], D("2026-11-06"), D("2027-11-06"), D("2027-11-20"), 7)[0] == "sin_datos"


def test_cierre_en_fin_de_semana_se_resuelve_con_el_viernes():
    """resolve_date sábado: hay un cierre posterior (lunes) en cuanto el dato se actualiza."""
    s = serie("2026-01-01", "2027-11-03", lambda i: 100.0)              # termina el miércoles 3-nov-2027
    assert D("2027-11-06").weekday() == 5
    assert resolver.cobertura([s], D("2026-11-06"), D("2027-11-06"), D("2027-11-07"), 7)[0] == "pendiente"
    s2 = serie("2026-01-01", "2027-11-08", lambda i: 100.0)
    assert resolver.cobertura([s2], D("2026-11-06"), D("2027-11-06"), D("2027-11-09"), 7)[0] == "ok"


def test_retorno_total_y_minimo():
    s = pd.Series([100.0, 120.0, 60.0, 90.0], index=pd.to_datetime(["2026-11-06", "2027-01-04", "2027-05-03", "2027-11-05"]))
    assert resolver.retorno_total(s, D("2026-11-06"), D("2027-11-06")) == pytest.approx(-0.10)
    assert resolver.minimo_relativo(s, D("2026-11-06"), D("2027-11-06")) == pytest.approx(-0.40)
    assert resolver.retorno_total(s, D("2026-11-06"), D("2027-02-01")) == pytest.approx(0.20)   # último cierre ≤ fecha
    with pytest.raises(ValueError):
        resolver.retorno_total(s, D("2026-01-01"), D("2027-01-01"))


def test_valor_e4():
    def pt(e, v):
        return comun.cifra(v, "unidades", "USD", "u", f"{e}-12-31", ejercicio=e)
    fund = {"ingresos": {"concepto": "x", "serie": [pt(2025, 100.0), pt(2026, 110.0)]},
            "beneficio_neto": {"concepto": "x", "serie": [pt(2026, 22.0)]},
            "patrimonio": {"concepto": "x", "serie": [pt(2026, 100.0)]}}
    assert resolver.valor_e4(fund, "crecimiento_ingresos", 2026)[0] == pytest.approx(0.10)
    assert resolver.valor_e4(fund, "crecimiento_ingresos", 2027)[0] is None
    assert resolver.valor_e4(fund, "roe", 2026)[0] == pytest.approx(0.22)
    assert resolver.valor_e4({"beneficio_neto": comun.desconocido("not_covered")}, "roe", 2026)[0] is None
    assert resolver.valor_e4(fund, "hito_clinico", 2026)[0] is None


# ---------------------------------------------------------------- E0-E2

def test_exceso_positivo_y_negativo():
    ref, fin = "2026-11-06", "2027-11-06"
    bench = serie("2026-01-01", "2027-11-20", lambda i: 100.0 * 1.0003 ** i)
    base = {"1": serie("2026-01-01", "2027-11-20", lambda i: 100.0 * 1.0006 ** i),
            "0": serie("2026-01-01", "2027-11-20", lambda i: 100.0 * 1.0001 ** i)}
    for y, acc in ((1, base["1"]), (0, base["0"])):
        r = resolver.resolver_precios(pregunta(), D("2027-11-20"), ProveedorFalso(acc, bench), 7)
        assert r["estado"] == "resuelta" and r["resultado"] == y
        d = r["detalle"]
        assert d["diferencia"] == pytest.approx(d["rt_accion"] - d["rt_benchmark"]) and d["fecha_fin"] == fin


def test_antes_del_vencimiento_no_se_resuelve():
    s = serie("2026-01-01", "2027-11-20", lambda i: 100.0)
    assert resolver.resolver_precios(pregunta(), D("2027-11-05"), ProveedorFalso(s, s), 7) is None


def test_sin_datos_tras_el_plazo_anula_y_antes_espera():
    acc = serie("2026-01-01", "2027-08-03", lambda i: 100.0)              # cotiza hasta agosto: ¿OPA?
    bench = serie("2026-01-01", "2027-11-20", lambda i: 100.0)
    assert resolver.resolver_precios(pregunta(), D("2027-11-09"), ProveedorFalso(acc, bench), 7) is None
    r = resolver.resolver_precios(pregunta(), D("2027-11-20"), ProveedorFalso(acc, bench), 7)
    assert r["estado"] == "anulada" and r["causa"] == "sin_datos" and "2027-08-03" in r["detalle"]["motivo"]


def test_errores_de_proveedor():
    f = ProveedorFalso(error_precios=comun.ErrorDatos("yfinance caído", "source_down"))
    assert resolver.resolver_precios(pregunta(), D("2027-12-30"), f, 7) is None        # transitorio: se reintenta
    f = ProveedorFalso(error_precios=comun.ErrorDatos("sin ticker", "not_covered"))
    assert resolver.resolver_precios(pregunta(), D("2027-11-08"), f, 7) is None        # dentro del plazo
    r = resolver.resolver_precios(pregunta(), D("2027-12-30"), f, 7)
    assert r["estado"] == "anulada" and r["causa"] == "sin_datos"


# ---------------------------------------------------------------- E3

def test_e3_caida_en_algun_momento():
    q = pregunta("E3", tipo="caida", umbral=-0.30)
    def trayectoria(minimo):
        idx = pd.bdate_range("2026-01-01", "2027-11-20")
        v = pd.Series(100.0, index=idx)
        v.loc["2027-03-01":"2027-03-10"] = minimo
        return v
    r = resolver.resolver_precios(q, D("2027-11-20"), ProveedorFalso(trayectoria(65.0), None), 7)
    assert r["resultado"] == 1 and r["detalle"]["minimo_retorno"] == pytest.approx(-0.35)
    r = resolver.resolver_precios(q, D("2027-11-20"), ProveedorFalso(trayectoria(75.0), None), 7)
    assert r["resultado"] == 0
    r = resolver.resolver_precios(q, D("2027-11-20"), ProveedorFalso(trayectoria(70.0), None), 7)
    assert r["resultado"] == 1                                                      # −30 % exacto cuenta


def test_e3_no_exige_serie_del_benchmark():
    q = pregunta("E3", tipo="caida", umbral=-0.30)
    acc = serie("2026-01-01", "2027-11-20", lambda i: 100.0)
    corta = serie("2026-01-01", "2027-01-01", lambda i: 100.0)
    assert resolver.resolver_precios(q, D("2027-11-20"), ProveedorFalso(acc, corta), 7)["estado"] == "resuelta"


# ---------------------------------------------------------------- E4

def reg_e4(metrica="crecimiento_ingresos", base=0.08, manual=False):
    return {"ticker": "XYZ"}, {"qid": "E4", "resolve_date": None, "detalle": {
        "tipo": "metrica_fundamental", "metrica": metrica, "valor_base": base, "ejercicio_objetivo": 2026,
        "fin_ejercicio_esperado": "2026-12-31", "manual": manual}}


def fund(ing25, ing26):
    def pt(e, v):
        return comun.cifra(v, "unidades", "USD", "u", f"{e}-12-31", ejercicio=e)
    return {"ingresos": {"concepto": "x", "serie": [pt(2025, ing25), pt(2026, ing26)]}}


def test_e4_espera_al_informe_anual_y_resuelve():
    r, q = reg_e4()
    f = ProveedorFalso(fund=fund(100.0, 110.0))
    assert resolver.resolver_e4(r, q, D("2027-01-10"), f, 20) is None and f.llamadas_fund == 0   # demasiado pronto
    res = resolver.resolver_e4(r, q, D("2027-03-01"), f, 20)
    assert res["resultado"] == 1 and res["detalle"]["valor"] == pytest.approx(0.10)
    r, q = reg_e4(base=0.12)
    assert resolver.resolver_e4(r, q, D("2027-03-01"), f, 20)["resultado"] == 0
    r, q = reg_e4(base=0.10)
    assert resolver.resolver_e4(r, q, D("2027-03-01"), f, 20)["resultado"] == 1            # ≥ en el umbral exacto


def test_e4_sin_informe_todavia_o_anulada_tras_un_anio():
    r, q = reg_e4()
    f = ProveedorFalso(fund={"ingresos": comun.desconocido("not_covered")})
    assert resolver.resolver_e4(r, q, D("2027-03-01"), f, 20) is None
    a = resolver.resolver_e4(r, q, D("2028-02-15"), f, 20)
    assert a["estado"] == "anulada" and a["causa"] == "sin_datos"
    assert resolver.resolver_e4(r, q, D("2027-03-01"), ProveedorFalso(error_fund=comun.ErrorDatos("x", "rate_limited")), 20) is None


def test_e4_hito_clinico_solo_manual():
    r, q = reg_e4("hito_clinico", manual=True)
    f = ProveedorFalso(fund=fund(100.0, 110.0))
    assert resolver.resolver_e4(r, q, D("2030-01-01"), f, 20) is None and f.llamadas_fund == 0


# ---------------------------------------------------------------- diario completo

def diario_con_prediccion(tmp_path, fecha="2026-11-06"):
    dp = dp_completo(fecha=fecha)
    d = escribir_run(tmp_path / "run", run("completo", dp=dp))
    diario = tmp_path / "p.jsonl"
    dr.cerrar(d, diario, "completo", ahora=AHORA)
    return diario


def proveedor_ganador():
    bench = serie("2026-01-01", "2029-12-31", lambda i: 100.0 * 1.0002 ** i)
    acc = serie("2026-01-01", "2029-12-31", lambda i: 100.0 * 1.0005 ** i)
    return ProveedorFalso(acc, bench, fund=fund(100.0, 112.0))


def test_resolver_pendientes_es_idempotente_y_resuelve_por_fecha(tmp_path):
    diario = diario_con_prediccion(tmp_path)
    prov = proveedor_ganador()
    r = resolver.resolver_pendientes(diario, D("2026-12-01"), prov)
    assert r["resueltas"] == [] and r["pendientes"] == 5
    r = resolver.resolver_pendientes(diario, D("2027-05-10"), prov)                  # vence E0; E4 ya tiene su informe
    assert [x["qid"] for x in r["resueltas"]] == ["E0", "E4"]
    assert r["resueltas"][0]["resultado"] == 1 and r["pendientes"] == 3
    r = resolver.resolver_pendientes(diario, D("2027-11-10"), prov)                  # vencen E1 y E3
    assert sorted(x["qid"] for x in r["resueltas"]) == ["E1", "E3"]
    assert [x["resultado"] for x in r["resueltas"] if x["qid"] == "E3"] == [0]       # no cayó un 30 %
    r = resolver.resolver_pendientes(diario, D("2027-11-10"), prov)
    assert r["resueltas"] == [] and r["pendientes"] == 1                              # idempotente: queda E2
    r = resolver.resolver_pendientes(diario, D("2029-12-01"), prov)
    assert [x["qid"] for x in r["resueltas"]] == ["E2"] and r["pendientes"] == 0
    assert dr.verificar_cadena(diario)["ok"]
    lineas = [x for x in dr.leer_registros(diario) if dr.tipo(x) == "resolucion"]
    assert len(lineas) == 5 and all(x["estado"] == "resuelta" and x["resuelta_por"] == "automatico" for x in lineas)
    e4 = next(x for x in lineas if x["qid"] == "E4")
    assert e4["resultado"] == 1 and e4["detalle"]["ejercicio"] == 2026 and e4["detalle"]["valor"] == pytest.approx(0.12)


def test_un_error_en_una_pregunta_no_detiene_las_demas(tmp_path):
    diario = diario_con_prediccion(tmp_path)

    class Roto(ProveedorFalso):
        def series_eur(self, ticker, benchmark):
            raise KeyError("columna rara")
    r = resolver.resolver_pendientes(diario, D("2027-11-10"), Roto(fund=fund(100.0, 112.0)))
    assert sorted(o["qid"] for o in r["omitidas"]) == ["E0", "E1", "E3"] and "KeyError" in r["omitidas"][0]["error"]
    assert [x["qid"] for x in r["resueltas"]] == ["E4"]          # E4 usa EDGAR, no los precios


def test_resolucion_manual_y_anulacion(tmp_path):
    diario = diario_con_prediccion(tmp_path)
    id_ = "XYZ-2026-11-06-a"
    resolver.resolver_manual(diario, id_, "E4", 1, "hito alcanzado en febrero")
    anul = resolver.anular_manual(diario, id_, "E1", "opa", "Adquirida por ACME")
    assert anul["estado"] == "anulada" and anul["causa"] == "opa" and anul["resultado"] is None
    assert dr.verificar_cadena(diario)["ok"]
    with pytest.raises(ValueError, match="No hay una pregunta pendiente"):
        resolver.resolver_manual(diario, id_, "E4", 0)                      # ya resuelta
    with pytest.raises(ValueError, match="causa de anulación"):
        resolver.anular_manual(diario, id_, "E2", "me_apetece")
    with pytest.raises(ValueError, match="resultado"):
        resolver.resolver_manual(diario, id_, "E0", 2)
    r = resolver.resolver_pendientes(diario, D("2027-11-10"), proveedor_ganador())
    assert "E1" not in [x["qid"] for x in r["resueltas"]]                    # la anulada no vuelve a resolverse


def test_los_updates_no_crean_preguntas_nuevas(tmp_path):
    diario = diario_con_prediccion(tmp_path)
    d2 = escribir_run(tmp_path / "run2", run("completo"))
    dr.cerrar(d2, diario, "completo", ahora=AHORA)
    assert [dr.tipo(x) for x in dr.leer_registros(diario)] == ["prediccion", "update"]
    assert len(resolver.pendientes(dr.leer_registros(diario))) == 5


def test_cli(tmp_path, capsys, monkeypatch):
    diario = diario_con_prediccion(tmp_path)
    assert resolver.main(["pendientes", "--diario", str(diario)]) == 0
    assert len(json.loads(capsys.readouterr().out)) == 5
    monkeypatch.setattr(resolver, "ProveedorReal", proveedor_ganador)
    assert resolver.main(["resolver", "--diario", str(diario), "--hoy", "2027-05-10"]) == 0
    assert json.loads(capsys.readouterr().out)["resueltas"][0]["qid"] == "E0"
    assert resolver.main(["manual", "--diario", str(diario), "--id", "XYZ-2026-11-06-a", "--qid", "E1",
                          "--resultado", "0"]) == 0
    assert resolver.main(["anular", "--diario", str(diario), "--id", "XYZ-2026-11-06-a", "--qid", "E2",
                          "--causa", "delisting"]) == 0
    with pytest.raises(SystemExit):
        resolver.main(["anular", "--diario", str(diario), "--id", "XYZ-2026-11-06-a", "--qid", "E2", "--causa", "opa"])

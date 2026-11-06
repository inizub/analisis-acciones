import json
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

import comun
import macro


def serie_diaria(valores, fin="2026-11-04"):
    """Serie diaria (días naturales) que termina en `fin`."""
    f = date.fromisoformat(fin)
    n = len(valores)
    return [((f - timedelta(days=n - 1 - i)).isoformat(), float(v)) for i, v in enumerate(valores)]


# ---------------------------------------------------------------- reglas de etiquetado

def test_cambio_pb_y_etiquetas():
    s = serie_diaria(np.linspace(4.0, 4.5, 400))
    c = macro.cambio_pb(s, 26)
    assert c["hasta"] == "2026-11-04" and c["desde"] == "2026-05-06"
    esperado = (s[-1][1] - macro.valor_en(s, "2026-05-06")[1]) * 100
    assert c["cambio_pb"] == pytest.approx(esperado)
    assert macro.etiqueta_tipos(25.1, 25) == "subiendo" and macro.etiqueta_tipos(25.0, 25) == "estables"
    assert macro.etiqueta_tipos(-25.0, 25) == "estables" and macro.etiqueta_tipos(-25.1, 25) == "bajando"
    assert macro.cambio_pb(serie_diaria([4.0] * 20), 26) is None  # historia insuficiente
    assert macro.cambio_pb([], 26) is None


@pytest.mark.parametrize("p,etiqueta", [(0, "relajado"), (29.9, "relajado"), (30, "normal"), (70, "normal"),
                                        (70.1, "tenso"), (100, "tenso")])
def test_etiqueta_credito(p, etiqueta):
    assert macro.etiqueta_credito(p, [30, 70]) == etiqueta


def test_percentil_historico():
    s = serie_diaria(list(range(1, 101)) + [50], fin="2026-11-04")
    p = macro.percentil_historico(s, 10)
    assert p["percentil"] == pytest.approx(100 * 51 / 101)   # 51 observaciones ≤ 50 de 101
    assert p["n"] == 101 and p["completa"] is False          # solo ~0,3 años de historia
    largo = serie_diaria([1.0] * 4000)
    assert macro.percentil_historico(largo, 10)["completa"] is True


def test_curva():
    assert macro.etiqueta_curva(4.0, 4.5) == {"etiqueta": "invertida", "pendiente_10a_2a_pb": pytest.approx(-50)}
    assert macro.etiqueta_curva(4.5, 4.0)["etiqueta"] == "normal"
    assert macro.etiqueta_curva(4.0, 4.0)["etiqueta"] == "normal"


# ---------------------------------------------------------------- régimen con clientes simulados

class ClienteFalso:
    def __init__(self, fred, bce, caidos=()):
        self.f, self.b, self.caidos = fred, bce, set(caidos)
        self.pedidos = []

    def fred(self, serie, anios=11):
        self.pedidos.append(serie)
        if serie in self.caidos:
            raise comun.ErrorDatos(f"FRED caído: {serie}", "source_down")
        return self.f[serie]

    def bce(self, clave, anios=11):
        if clave in self.caidos:
            raise comun.ErrorDatos("BCE caído", "rate_limited")
        return self.b[clave]


class DamodaranFalso:
    def erp(self):
        return {"erp": 0.0423, "fecha_actualizacion": "2026-01-01", "fuente_url": "https://x", "historica": {"anio": 2025}}


def mundo(tipos10=None, credito=None):
    cfg = comun.cargar_config()["macro"]
    sube = np.linspace(4.0, 4.6, 400) if tipos10 is None else tipos10
    return {
        cfg["fred"]["tipos_10a"]: serie_diaria(sube), cfg["fred"]["tipos_2a"]: serie_diaria([4.3] * 400),
        cfg["fred"]["tipos_3m"]: serie_diaria([4.1] * 400),
        cfg["fred"]["credito"]: serie_diaria(np.linspace(1.0, 2.0, 4000) if credito is None else credito),
        cfg["fred"]["hy"]: serie_diaria(np.linspace(3.0, 4.0, 800)), cfg["eurusd_fred"]: serie_diaria([1.1] * 400),
    }, {cfg["ecb"]["estr"]: serie_diaria([2.4] * 30), cfg["ecb"]["rendimiento_10a"]: serie_diaria([3.3] * 30)}


def test_regimen_completo():
    f, b = mundo()
    r = macro.regimen(ClienteFalso(f, b), DamodaranFalso())
    assert r["tipos"]["etiqueta"] == "subiendo" and r["tipos"]["cambio_pb"] > 25
    assert r["curva"]["etiqueta"] == "normal" and r["curva"]["pendiente_10a_2a_pb"] == pytest.approx(30, abs=1)
    assert r["curva"]["pendiente_10a_3m_pb"] == pytest.approx(50, abs=1)
    assert r["credito"]["etiqueta"] == "tenso" and r["credito"]["serie"] == "BAA10Y" and r["credito"]["ventana_completa"]
    assert r["credito"]["hy"]["serie"] == "BAMLH0A0HYM2" and r["credito"]["hy"]["anios_disponibles"] < 3
    assert r["rf_usd"]["valor"] == pytest.approx(0.046, abs=0.001)
    assert r["rf_eur"]["valor"] == pytest.approx(0.033) and r["estr"]["valor"] == pytest.approx(0.024)
    assert r["erp"]["valor"] == 0.0423 and r["desconocidos"] == []
    assert r["fx"]["eurusd"]["valor"] == 1.1


def test_regimen_tipos_a_la_baja_y_curva_invertida():
    f, b = mundo(tipos10=np.linspace(4.8, 3.9, 400))
    f["DGS2"] = serie_diaria([4.5] * 400)
    r = macro.regimen(ClienteFalso(f, b), DamodaranFalso())
    assert r["tipos"]["etiqueta"] == "bajando" and r["curva"]["etiqueta"] == "invertida"


def test_regimen_fuente_caida_no_inventa_datos():
    f, b = mundo()
    r = macro.regimen(ClienteFalso(f, b, caidos={"DGS10", "BAA10Y"}), DamodaranFalso())
    assert comun.es_desconocido(r["tipos"]) and r["tipos"]["causa"] == "source_down"
    assert comun.es_desconocido(r["credito"]) and comun.es_desconocido(r["rf_usd"])
    assert comun.es_desconocido(r["curva"])           # depende de DGS10
    assert r["rf_eur"]["valor"] == pytest.approx(0.033)  # el resto sigue
    assert {d["campo"] for d in r["desconocidos"]} >= {"tipos.dgs10", "credito"}


def test_regimen_bce_caido():
    f, b = mundo()
    cfg = comun.cargar_config()["macro"]["ecb"]
    r = macro.regimen(ClienteFalso(f, b, caidos={cfg["rendimiento_10a"]}), DamodaranFalso())
    assert comun.es_desconocido(r["rf_eur"]) and r["rf_eur"]["causa"] == "rate_limited"


def test_vigente_y_si_caducado(tmp_path, monkeypatch, capsys):
    ruta = tmp_path / "macro_regime.json"
    assert macro.vigente(ruta, 7) is False
    ahora = comun.ahora_iso()
    ruta.write_text(json.dumps({"generado": ahora}), encoding="utf-8")
    assert macro.vigente(ruta, 7) is True
    viejo = (pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=8)).strftime("%Y-%m-%dT%H:%M:%SZ")
    ruta.write_text(json.dumps({"generado": viejo}), encoding="utf-8")
    assert macro.vigente(ruta, 7) is False
    ruta.write_text("{roto", encoding="utf-8")
    assert macro.vigente(ruta, 7) is False
    ruta.write_text(json.dumps({"generado": ahora}), encoding="utf-8")
    assert macro.main(["regimen", "--salida", str(ruta), "--si-caducado"]) == 0
    assert '"estado": "vigente"' in capsys.readouterr().out


# ---------------------------------------------------------------- sensibilidades

def mundo_sensibilidades(beta_tipos=2.0, beta_fx=1.5, ruido=0.0, semanas=200):
    """Rendimientos semanales construidos con betas conocidas respecto al DGS10 (en pp) y a la divisa (log)."""
    rng = np.random.default_rng(3)
    fin = pd.Timestamp("2026-11-06")  # viernes
    viernes = pd.date_range(end=fin, periods=semanas + 1, freq="W-FRI")
    dy = rng.normal(0, 0.10, semanas)                       # pp semanales
    dfx = rng.normal(0, 0.01, semanas)                      # log semanal de la divisa en EUR
    ret = beta_tipos * dy + beta_fx * dfx + rng.normal(0, ruido, semanas)
    nivel = np.concatenate([[4.0], 4.0 + np.cumsum(dy)])
    eur_div = np.concatenate([[0.18], 0.18 * np.exp(np.cumsum(dfx))])   # EUR por BRL
    precio = 100 * np.exp(np.concatenate([[0.0], np.cumsum(ret)]))
    dias = pd.date_range(viernes[0] - pd.Timedelta(days=6), fin, freq="D")
    def a_diario(vals):
        s = pd.Series(vals, index=viernes).reindex(dias).ffill().bfill()
        return [(d.date().isoformat(), float(v)) for d, v in s.items()]
    # FRED cota: DGS10 en %, DEXUSEU = USD por EUR (1,10), DEXBZUS = BRL por USD → EUR por BRL = 1 / (BRL/USD · USD/EUR)
    eurusd = 1.10
    dexbzus = 1.0 / (eur_div * eurusd)
    fred = {"DGS10": a_diario(nivel), "DEXUSEU": a_diario(np.full(len(viernes), eurusd)), "DEXBZUS": a_diario(dexbzus)}
    serie_eur = {"fechas": [d.date().isoformat() for d in viernes], "accion": [float(p) for p in precio]}
    return fred, serie_eur


class ClienteSens:
    def __init__(self, fred):
        self.f = fred

    def fred(self, serie, anios=11):
        return self.f[serie]


def datapack_min(**kw):
    dp = {"ticker": "XYZ", "empresa": {"ticker": "XYZ", "moneda_informe": "USD"}}
    dp.update(kw)
    return dp


def test_sensibilidad_a_tipos_recupera_la_beta():
    """Las regresiones son univariantes, así que cada beta se prueba en un mundo donde la otra es cero."""
    fred, serie = mundo_sensibilidades(beta_tipos=2.0, beta_fx=0.0)
    r = macro.sensibilidades(datapack_min(), serie, ClienteSens(fred), divisa="BRL")
    assert r["tipos"]["beta_por_100pb"] == pytest.approx(2.0, abs=1e-6)
    assert r["tipos"]["n_semanas"] >= 150 and r["tipos"]["r2"] == pytest.approx(1.0)
    assert r["ventana"]["anios"] == 3 and r["ventana"]["desde"] >= "2023-11-01"


def test_sensibilidad_a_la_divisa_recupera_la_elasticidad_y_su_signo():
    fred, serie = mundo_sensibilidades(beta_tipos=0.0, beta_fx=1.5)
    r = macro.sensibilidades(datapack_min(), serie, ClienteSens(fred), divisa="BRL")
    assert r["divisa"]["divisa"] == "BRL" and r["divisa"]["beta"] == pytest.approx(1.5, abs=1e-6)
    assert r["divisa"]["r2"] == pytest.approx(1.0)
    # Si la acción se mueve en sentido contrario a la divisa, la beta sale negativa (comprueba la orientación del cruce).
    fred, serie = mundo_sensibilidades(beta_tipos=0.0, beta_fx=-1.0)
    r = macro.sensibilidades(datapack_min(), serie, ClienteSens(fred), divisa="BRL")
    assert r["divisa"]["beta"] == pytest.approx(-1.0, abs=1e-6)


def test_sensibilidades_con_ruido_y_ventana_de_3_anios():
    fred, serie = mundo_sensibilidades(ruido=0.01, semanas=300)
    r = macro.sensibilidades(datapack_min(), serie, ClienteSens(fred), divisa="BRL")
    assert r["tipos"]["n_semanas"] <= 157                      # solo 3 años aunque haya 300 semanas
    assert 0.5 < r["tipos"]["beta_por_100pb"] < 3.5 and r["tipos"]["r2"] < 1


def test_divisa_relevante_por_segmentos_de_moneda():
    seg = lambda n, v: {"nombre": n, "tipo": "moneda", "ingresos": comun.cifra(v, "unidades", "USD", "u", "2025-12-31")}  # noqa: E731
    dp = datapack_min(segmentos=[seg("BRL", 70), seg("MXN", 20), seg("USD", 10)])
    assert macro.divisa_relevante(dp) == "BRL"
    pesos = macro.ingresos_por_moneda(dp)
    assert {p["moneda"]: round(p["peso"], 2) for p in pesos} == {"BRL": 0.7, "MXN": 0.2, "USD": 0.1}
    assert macro.divisa_relevante(datapack_min()) == "USD"
    assert comun.es_desconocido(macro.ingresos_por_moneda(datapack_min()))
    solo_eur = datapack_min(segmentos=[seg("EUR", 100)])
    assert macro.divisa_relevante(solo_eur) == "USD"


def test_sensibilidades_divisa_eur_o_sin_serie_son_desconocidas():
    fred, serie = mundo_sensibilidades()
    cli = ClienteSens(fred)
    assert comun.es_desconocido(macro.sensibilidades(datapack_min(), serie, cli, divisa="EUR")["divisa"])
    r = macro.sensibilidades(datapack_min(), serie, cli, divisa="ZZZ")
    assert comun.es_desconocido(r["divisa"]) and r["divisa"]["causa"] == "not_covered"
    # deuda y vencimientos sin dato quedan desconocidos, no inventados
    assert comun.es_desconocido(r["deuda_tipo_variable"]) and comun.es_desconocido(r["vencimientos_24m"])
    dp = datapack_min(deuda={"tipo_variable_pct": comun.cifra(0.3, "ratio", None, "u", "2025-12-31")})
    assert macro.sensibilidades(dp, serie, cli, divisa="EUR")["deuda_tipo_variable"]["valor"] == 0.3


def test_cruce_eur_por_divisa():
    eurusd = serie_diaria([1.25] * 400)
    gbp = serie_diaria([1.50] * 400)    # USD por GBP
    brl = serie_diaria([5.0] * 400)     # BRL por USD
    assert macro.eur_por_divisa("GBP", eurusd, gbp, usd_por_divisa=True).iloc[-1] == pytest.approx(1.50 / 1.25)
    assert macro.eur_por_divisa("BRL", eurusd, brl, usd_por_divisa=False).iloc[-1] == pytest.approx((1 / 5.0) / 1.25)
    assert macro.eur_por_divisa("USD", eurusd, None, usd_por_divisa=False).iloc[-1] == pytest.approx(1 / 1.25)


def test_regresion_casos_limite():
    x = pd.Series(np.arange(40.0), index=pd.date_range("2024-01-05", periods=40, freq="W-FRI"))
    assert macro.regresion(2 * x + 1, x)["beta"] == pytest.approx(2.0)
    assert macro.regresion(x, x * 0 + 3.0) is None           # x sin varianza
    assert macro.regresion(x.iloc[:10], x.iloc[:10]) is None  # < 30 semanas

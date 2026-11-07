import numpy as np
import pandas as pd
import pytest

import comun
from datos import precios


def serie(valores, inicio="2020-01-01", freq="B"):
    return pd.Series(valores, index=pd.date_range(inicio, periods=len(valores), freq=freq), dtype="float64")


def paseo(n, mu=0.0003, sigma=0.01, semilla=1, inicio="2020-01-01"):
    rng = np.random.default_rng(semilla)
    return serie(100 * np.exp(np.cumsum(rng.normal(mu, sigma, n))), inicio)


def test_normalizar_moneda():
    assert precios.normalizar_moneda("GBp") == ("GBP", 100.0)
    assert precios.normalizar_moneda("usd") == ("USD", 1.0)
    assert precios.ticker_fx("EUR") is None
    assert precios.ticker_fx("USD") == "EURUSD=X"


def test_a_eur_alinea_y_divide():
    s = serie([110.0, 121.0, 132.0], "2024-01-01", "D")
    fx = pd.Series([1.1, 1.2], index=pd.to_datetime(["2024-01-01", "2024-01-02"]))  # USD por EUR
    eur = precios.a_eur(s, fx)
    assert eur.tolist() == pytest.approx([100.0, 100.833333, 110.0])  # el último usa el fx del día anterior (ffill)
    assert precios.a_eur(s, None, divisor=100).tolist() == pytest.approx([1.1, 1.21, 1.32])


def test_a_eur_recorta_si_fx_empieza_tarde():
    s = serie([1.0, 2.0, 3.0], "2024-01-01", "D")
    fx = pd.Series([2.0], index=pd.to_datetime(["2024-01-02"]))
    assert precios.a_eur(s, fx).tolist() == [1.0, 1.5]


def test_retorno_y_historia_insuficiente():
    s = serie(np.linspace(100, 200, 800))
    r1 = precios.retorno(s, 1)
    assert r1 is not None and r1 > 0
    assert precios.retorno(s, 5) is None


def test_retorno_exacto():
    idx = pd.to_datetime(["2023-01-02", "2024-01-02", "2025-01-02"])
    s = pd.Series([100.0, 110.0, 121.0], index=idx)
    assert precios.retorno(s, 1) == pytest.approx(0.1)
    assert precios.retorno(s, 2) == pytest.approx(0.21)


def test_vol_relativa_y_correlacion():
    a = paseo(900)
    assert precios.vol_relativa(a, a, 3) == pytest.approx(0.0, abs=1e-12)
    assert precios.correlacion(a, a, 3) == pytest.approx(1.0)
    b = paseo(900, semilla=2)
    v = precios.vol_relativa(a, b, 3)
    # σ diaria 1 % por serie, independientes: σ_rel ≈ 0.01·√2·√252 ≈ 0.22 anual
    assert 0.15 < v < 0.30
    assert precios.vol_relativa(a.iloc[-100:], b.iloc[-100:], 3) is None


def test_momentum_12_1():
    idx = pd.date_range("2023-01-01", "2024-12-31", freq="D")
    s = pd.Series(np.arange(len(idx), dtype=float) + 100, index=idx)
    fin = s.index[-1]
    esperado = s.loc[: fin - pd.DateOffset(months=1)].iloc[-1] / s.loc[: fin - pd.DateOffset(months=12)].iloc[-1] - 1
    assert precios.momentum_12_1(s) == pytest.approx(esperado)


def test_metricas_relativas_claves():
    a, b = paseo(1400, semilla=3), paseo(1400, semilla=4)
    m = precios.metricas_relativas(a, b)
    assert set(m) == {"rt_1a", "rt_bench_1a", "rt_rel_1a", "rt_3a", "rt_bench_3a", "rt_rel_3a", "rt_5a",
                      "rt_bench_5a", "rt_rel_5a", "vol_rel_1a", "vol_rel_3a", "vol_1a", "vol_3a", "correlacion_3a", "beta_3a",
                      "momentum_12_1", "momentum_12_1_bench", "momentum_12_1_rel"}
    assert m["rt_rel_1a"] == pytest.approx(m["rt_1a"] - m["rt_bench_1a"])
    assert m["rt_5a"] is not None


# ---------------------------------------------------------------- ClientePrecios con yfinance simulado

class TickerFalso:
    def __init__(self, hist, info, income=None, error=None):
        self._hist, self.fast_info, self.income_stmt, self._error = hist, info, income, error

    def history(self, period, auto_adjust, actions):
        if self._error:
            raise self._error
        return self._hist


class YFFalso:
    def __init__(self, tickers):
        self.tickers = tickers
        self.llamadas = []

    def Ticker(self, t):
        self.llamadas.append(t)
        return self.tickers[t]


def hist(s, div=None):
    df = pd.DataFrame({"Close": s.values, "Adj Close": s.values, "Dividends": 0.0}, index=s.index.tz_localize("America/New_York"))
    if div:
        for fecha, v in div.items():
            df.loc[pd.Timestamp(fecha, tz="America/New_York"), "Dividends"] = v
    return df


def yf_mundo():
    n = 1600
    idx = pd.bdate_range(end="2026-11-05", periods=n)
    acc = pd.Series(np.linspace(50, 100, n), index=idx)
    vw = pd.Series(np.linspace(80, 120, n), index=idx)
    fx = pd.Series(1.10, index=idx)
    income = pd.DataFrame({pd.Timestamp("2025-12-31"): [1000.0, 100.0, 10.0]},
                          index=["Total Revenue", "Net Income Common Stockholders", "Diluted Average Shares"])
    return YFFalso({
        "XYZ": TickerFalso(hist(acc, {"2026-06-01": 1.0, "2025-06-02": 0.5}), {"currency": "USD", "market_cap": 1e9, "shares": 1e7}, income),
        "VWCE.DE": TickerFalso(hist(vw), {"currency": "EUR", "market_cap": None, "shares": None}),
        "EURUSD=X": TickerFalso(hist(fx), {"currency": "USD"}),
    })


def test_cliente_precios_completo(cache_tmp):
    yf = yf_mundo()
    r = precios.ClientePrecios(cache=cache_tmp, yf=yf, dormir=lambda s: None).obtener("XYZ")
    p = r["precios"]
    assert p["moneda"] == "USD"
    assert p["precio"]["valor"] == pytest.approx(100.0)
    assert p["precio_eur"]["valor"] == pytest.approx(100 / 1.10)
    assert p["fx_eur"]["valor"] == pytest.approx(1.10)
    assert p["dividendos_12m"]["valor"] == pytest.approx(1.0)
    assert p["capitalizacion_eur"]["valor"] == pytest.approx(1e9 / 1.10)
    assert not comun.es_desconocido(p["metricas_eur"]["vol_rel_3a"])
    assert r["fundamentales_secundarios"]["anual"]["ingresos"] == {"2025-12-31": 1000.0}
    assert len(r["serie_eur"]["fechas"]) == len(r["serie_eur"]["accion"]) == len(r["serie_eur"]["benchmark"])
    # segunda llamada: todo sale de la caché
    n = len(yf.llamadas)
    precios.ClientePrecios(cache=cache_tmp, yf=yf, dormir=lambda s: None).obtener("XYZ")
    assert len(yf.llamadas) == n


def test_cliente_precios_sin_datos_es_not_covered(cache_tmp):
    yf = YFFalso({"NADA": TickerFalso(pd.DataFrame(), {"currency": "USD"})})
    with pytest.raises(comun.ErrorDatos) as e:
        precios.ClientePrecios(cache=cache_tmp, yf=yf, dormir=lambda s: None).obtener("NADA")
    assert e.value.causa == "not_covered"


def test_cliente_precios_rate_limit_reintenta_y_falla(cache_tmp):
    esperas = []
    yf = YFFalso({"X": TickerFalso(None, {"currency": "USD"}, error=RuntimeError("Too Many Requests. Rate limited"))})
    with pytest.raises(comun.ErrorDatos) as e:
        precios.ClientePrecios(cache=cache_tmp, yf=yf, dormir=esperas.append).obtener("X")
    assert e.value.causa == "rate_limited"
    assert esperas == [2, 4, 8, 16, 32]


def test_beta_semanal_frente_al_benchmark():
    rng = np.random.default_rng(1)
    r_b = rng.normal(0.002, 0.02, 800)
    r_a = 1.5 * r_b + rng.normal(0, 0.005, 800)
    b = serie(100 * np.cumprod(1 + r_b))
    a = serie(100 * np.cumprod(1 + r_a))
    assert precios.beta(a, b, 3) == pytest.approx(1.5, abs=0.2)
    assert precios.beta(a, b, 30) is None            # sin historia suficiente

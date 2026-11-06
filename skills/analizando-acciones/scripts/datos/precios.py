"""Precios diarios (5 años) de la acción y de VWCE.DE, conversión a EUR y métricas relativas.

Uso CLI:
    python precios.py TICKER [--salida precios.json] [--benchmark VWCE.DE]

Las métricas se calculan con cierres ajustados (incluyen dividendos) convertidos a EUR:
  - retornos totales a 1, 3 y 5 años (acción, VWCE y diferencia)
  - volatilidad relativa: desviación típica anualizada de (r_semanal_acción − r_semanal_VWCE), a 1 y 3 años
  - correlación de retornos semanales a 3 años
  - momentum 12-1: retorno de t−12m a t−1m, acción menos VWCE
También devuelve ingresos, beneficio neto y acciones diluidas de yfinance como fuente secundaria
para la verificación cruzada con EDGAR.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import comun  # noqa: E402
from datos.cache import CacheDisco, con_backoff  # noqa: E402

FUENTE_URL = "https://finance.yahoo.com/quote/{t}"
# Divisas que yfinance cotiza en subunidades: (divisa real, divisor).
SUBUNIDADES = {"GBp": ("GBP", 100.0), "GBX": ("GBP", 100.0), "ILA": ("ILS", 100.0), "ZAc": ("ZAR", 100.0)}
SEMANAS_ANIO = 52


# ---------------------------------------------------------------- utilidades puras

def normalizar_moneda(moneda: str) -> tuple[str, float]:
    if moneda in SUBUNIDADES:
        return SUBUNIDADES[moneda]
    return moneda.upper(), 1.0


def ticker_fx(moneda: str) -> str | None:
    """Ticker yfinance que da unidades de `moneda` por 1 EUR (p. ej. EURUSD=X)."""
    return None if moneda == "EUR" else f"EUR{moneda}=X"


def a_eur(serie: pd.Series, fx: pd.Series | None, divisor: float = 1.0) -> pd.Series:
    """Convierte una serie en moneda local a EUR. `fx` = unidades locales por EUR, alineada por fecha (ffill)."""
    s = serie / divisor
    if fx is None:
        return s
    fx_al = fx.reindex(s.index.union(fx.index)).sort_index().ffill().reindex(s.index)
    if fx_al.isna().any():
        primera = fx_al.first_valid_index()
        if primera is None:
            raise comun.ErrorDatos("Serie de tipo de cambio vacía", "source_down")
        s, fx_al = s.loc[primera:], fx_al.loc[primera:]
    return s / fx_al


def precio_en(serie: pd.Series, fecha: pd.Timestamp) -> float | None:
    """Último valor con fecha ≤ `fecha`."""
    sub = serie.loc[:fecha]
    return None if sub.empty else float(sub.iloc[-1])


def retorno(serie: pd.Series, anios: float, fin: pd.Timestamp | None = None) -> float | None:
    fin = fin if fin is not None else serie.index[-1]
    ini = fin - pd.DateOffset(days=round(365.25 * anios))
    if serie.index[0] > ini + pd.Timedelta(days=7):
        return None  # historia insuficiente
    p0, p1 = precio_en(serie, ini), precio_en(serie, fin)
    return None if not p0 or p1 is None else p1 / p0 - 1


def semanales(serie: pd.Series) -> pd.Series:
    return np.log(serie.resample("W-FRI").last().dropna()).diff().dropna()


def vol_relativa(accion: pd.Series, bench: pd.Series, anios: float) -> float | None:
    ra, rb = semanales(accion), semanales(bench)
    df = pd.concat([ra, rb], axis=1, join="inner").dropna()
    df = df.loc[df.index > df.index[-1] - pd.DateOffset(days=round(365.25 * anios))]
    if len(df) < int(SEMANAS_ANIO * anios * 0.8):
        return None
    return float((df.iloc[:, 0] - df.iloc[:, 1]).std(ddof=1) * np.sqrt(SEMANAS_ANIO))


def vol_absoluta(serie: pd.Series, anios: float) -> float | None:
    r = semanales(serie)
    r = r.loc[r.index > r.index[-1] - pd.DateOffset(days=round(365.25 * anios))]
    if len(r) < int(SEMANAS_ANIO * anios * 0.8):
        return None
    return float(r.std(ddof=1) * np.sqrt(SEMANAS_ANIO))


def correlacion(accion: pd.Series, bench: pd.Series, anios: float) -> float | None:
    df = pd.concat([semanales(accion), semanales(bench)], axis=1, join="inner").dropna()
    df = df.loc[df.index > df.index[-1] - pd.DateOffset(days=round(365.25 * anios))]
    if len(df) < int(SEMANAS_ANIO * anios * 0.8):
        return None
    return float(df.iloc[:, 0].corr(df.iloc[:, 1]))


def momentum_12_1(serie: pd.Series, fin: pd.Timestamp | None = None) -> float | None:
    fin = fin if fin is not None else serie.index[-1]
    t12, t1 = fin - pd.DateOffset(months=12), fin - pd.DateOffset(months=1)
    if serie.index[0] > t12 + pd.Timedelta(days=7):
        return None
    p12, p1 = precio_en(serie, t12), precio_en(serie, t1)
    return None if not p12 or p1 is None else p1 / p12 - 1


def metricas_relativas(accion_eur: pd.Series, bench_eur: pd.Series) -> dict[str, float | None]:
    fin = min(accion_eur.index[-1], bench_eur.index[-1])
    a, b = accion_eur.loc[:fin], bench_eur.loc[:fin]
    res: dict[str, float | None] = {}
    for n in (1, 3, 5):
        ra, rb = retorno(a, n), retorno(b, n)
        res[f"rt_{n}a"] = ra
        res[f"rt_bench_{n}a"] = rb
        res[f"rt_rel_{n}a"] = None if ra is None or rb is None else ra - rb
    res["vol_rel_1a"] = vol_relativa(a, b, 1)
    res["vol_rel_3a"] = vol_relativa(a, b, 3)
    res["vol_1a"] = vol_absoluta(a, 1)
    res["vol_3a"] = vol_absoluta(a, 3)
    res["correlacion_3a"] = correlacion(a, b, 3)
    ma, mb = momentum_12_1(a), momentum_12_1(b)
    res["momentum_12_1"] = ma
    res["momentum_12_1_bench"] = mb
    res["momentum_12_1_rel"] = None if ma is None or mb is None else ma - mb
    return res


def serie_desde_dict(d: dict, campo: str) -> pd.Series:
    s = pd.Series(d[campo], index=pd.to_datetime(d["fechas"]), dtype="float64").dropna()
    return s.sort_index()


# ---------------------------------------------------------------- acceso a red (yfinance)

class ClientePrecios:
    def __init__(self, cache: CacheDisco | None = None, yf: Any = None, dormir: Any = None):
        import time

        cfg = comun.cargar_config()["yfinance"]
        self.cache = cache or CacheDisco()
        self.reintentos = cfg["reintentos"]
        self.espera = cfg["espera_base_seg"]
        self.anios = cfg["anios"]
        self.dormir = dormir or time.sleep
        if yf is None:
            import yfinance as yf
        self.yf = yf

    def _historia(self, ticker: str) -> dict:
        def pedir() -> dict:
            try:
                # Un año de margen para que los retornos a `anios` años tengan precio inicial.
                h = self.yf.Ticker(ticker).history(period=f"{self.anios + 1}y", auto_adjust=False, actions=True)
            except Exception as e:  # yfinance lanza excepciones heterogéneas
                msg = str(e).lower()
                causa = "rate_limited" if "rate" in msg or "too many" in msg else "source_down"
                raise comun.ErrorDatos(f"yfinance falló para {ticker}: {e}", causa) from e
            if h is None or h.empty:
                raise _SinDatos(ticker)
            idx = pd.DatetimeIndex(h.index)
            if idx.tz is not None:
                idx = idx.tz_localize(None)
            idx = idx.normalize()
            aj = h["Adj Close"] if "Adj Close" in h else h["Close"]
            div = h["Dividends"] if "Dividends" in h else pd.Series(0.0, index=h.index)
            return {
                "fechas": [d.date().isoformat() for d in idx],
                "cierre": [None if pd.isna(v) else float(v) for v in h["Close"]],
                "cierre_aj": [None if pd.isna(v) else float(v) for v in aj],
                "dividendos": [0.0 if pd.isna(v) else float(v) for v in div],
            }

        def con_reintentos() -> dict:
            try:
                return con_backoff(pedir, self.reintentos, self.espera, (comun.ErrorDatos,), self.dormir)
            except _SinDatos:
                raise comun.ErrorDatos(f"yfinance no tiene precios de {ticker}", "not_covered") from None

        datos, info = self.cache.obtener_o_calcular("precios", f"hist:{ticker}:{self.anios + 1}y", con_reintentos)
        datos["_info_cache"] = info
        return datos

    def _info_rapida(self, ticker: str) -> dict:
        def pedir() -> dict:
            try:
                fi = self.yf.Ticker(ticker).fast_info
                return {"moneda": fi.get("currency") if hasattr(fi, "get") else fi["currency"],
                        "capitalizacion": _float(_leer(fi, "market_cap")),
                        "acciones": _float(_leer(fi, "shares"))}
            except Exception as e:
                raise comun.ErrorDatos(f"yfinance fast_info falló para {ticker}: {e}", "source_down") from e

        datos, _ = self.cache.obtener_o_calcular(
            "precios", f"info:{ticker}", lambda: con_backoff(pedir, self.reintentos, self.espera, (comun.ErrorDatos,), self.dormir))
        return datos

    def _fundamentales_secundarios(self, ticker: str) -> dict:
        def pedir() -> dict:
            try:
                df = self.yf.Ticker(ticker).income_stmt
            except Exception as e:
                raise comun.ErrorDatos(f"yfinance income_stmt falló para {ticker}: {e}", "source_down") from e
            if df is None or df.empty:
                raise comun.ErrorDatos(f"yfinance sin income_stmt para {ticker}", "not_covered")
            res = {}
            for campo, filas in (("ingresos", ["Total Revenue", "Operating Revenue"]),
                                 ("beneficio_neto", ["Net Income Common Stockholders", "Net Income"]),
                                 ("acciones_diluidas", ["Diluted Average Shares"])):
                fila = next((f for f in filas if f in df.index), None)
                if fila is None:
                    continue
                res[campo] = {pd.Timestamp(c).date().isoformat(): float(v)
                              for c, v in df.loc[fila].items() if not pd.isna(v)}
            return res

        datos, _ = self.cache.obtener_o_calcular("precios", f"fund:{ticker}", pedir)
        return datos

    def series_eur(self, ticker: str, benchmark: str = "VWCE.DE") -> tuple[pd.Series, pd.Series]:
        """Cierres ajustados (retorno total) de la acción y del benchmark, convertidos a EUR. Para resolver eventos."""
        info = self._info_rapida(ticker)
        if not info.get("moneda"):
            raise comun.ErrorDatos(f"yfinance no da la moneda de {ticker}", "source_down")
        moneda, divisor = normalizar_moneda(info["moneda"])
        moneda_b, divisor_b = normalizar_moneda(self._info_rapida(benchmark).get("moneda") or "EUR")
        fx = serie_desde_dict(self._historia(ticker_fx(moneda)), "cierre") if ticker_fx(moneda) else None
        fx_b = serie_desde_dict(self._historia(ticker_fx(moneda_b)), "cierre") if ticker_fx(moneda_b) else None
        accion = a_eur(serie_desde_dict(self._historia(ticker), "cierre_aj"), fx, divisor)
        bench = a_eur(serie_desde_dict(self._historia(benchmark), "cierre_aj"), fx_b, divisor_b)
        return accion, bench

    def obtener(self, ticker: str, benchmark: str = "VWCE.DE") -> dict:
        obtenido = comun.ahora_iso()
        desconocidos: list[dict] = []
        h = self._historia(ticker)
        info = self._info_rapida(ticker)
        if not info.get("moneda"):
            raise comun.ErrorDatos(f"yfinance no da la moneda de {ticker}", "source_down")
        moneda, divisor = normalizar_moneda(info["moneda"])
        hb = self._historia(benchmark)
        info_b = self._info_rapida(benchmark)
        moneda_b, divisor_b = normalizar_moneda(info_b.get("moneda") or "EUR")

        fx = fx_b = None
        fuentes = [FUENTE_URL.format(t=ticker), FUENTE_URL.format(t=benchmark)]
        if ticker_fx(moneda):
            fx = serie_desde_dict(self._historia(ticker_fx(moneda)), "cierre")
            fuentes.append(FUENTE_URL.format(t=ticker_fx(moneda)))
        if ticker_fx(moneda_b):
            fx_b = serie_desde_dict(self._historia(ticker_fx(moneda_b)), "cierre")

        cierre = serie_desde_dict(h, "cierre")
        aj = serie_desde_dict(h, "cierre_aj")
        aj_eur = a_eur(aj, fx, divisor)
        bench_eur = a_eur(serie_desde_dict(hb, "cierre_aj"), fx_b, divisor_b)

        fecha = cierre.index[-1]
        precio_local = float(cierre.iloc[-1]) / divisor
        fx_ultimo = float(fx.loc[:fecha].iloc[-1]) if fx is not None else 1.0
        fx_fecha = fx.loc[:fecha].index[-1].date().isoformat() if fx is not None else fecha.date().isoformat()
        divs = pd.Series(h["dividendos"], index=pd.to_datetime(h["fechas"]))
        div_12m = float(divs.loc[divs.index > fecha - pd.DateOffset(years=1)].sum()) / divisor

        url = FUENTE_URL.format(t=ticker)
        ff = fecha.date().isoformat()
        precio = {
            "ticker_precio": ticker,
            "moneda": moneda,
            "precio": comun.cifra(precio_local, "por_accion", moneda, url, ff, obtenido),
            "precio_eur": comun.cifra(precio_local / fx_ultimo, "por_accion", "EUR", url, ff, obtenido),
            "fx_eur": comun.cifra(fx_ultimo, f"{moneda}_por_EUR", None, FUENTE_URL.format(t=ticker_fx(moneda) or "EUR"),
                                  fx_fecha, obtenido),
            "dividendos_12m": comun.cifra(div_12m, "por_accion", moneda, url, ff, obtenido),
            "rentabilidad_dividendo": comun.cifra(div_12m / precio_local if precio_local else 0.0, "ratio", None, url, ff, obtenido),
            "antiguedad_dias": (date.today() - fecha.date()).days,
        }
        if info.get("capitalizacion"):
            cap = info["capitalizacion"] / (divisor if moneda != info["moneda"] else 1.0)
            precio["capitalizacion"] = comun.cifra(cap, "unidades", moneda, url, ff, obtenido)
            precio["capitalizacion_eur"] = comun.cifra(cap / fx_ultimo, "unidades", "EUR", url, ff, obtenido)
        else:
            precio["capitalizacion"] = comun.desconocido("source_down", "yfinance no da capitalización")
            desconocidos.append({"campo": "precios.capitalizacion", "causa": "source_down"})

        rel = metricas_relativas(aj_eur, bench_eur)
        metricas = {}
        for k, v in rel.items():
            if v is None:
                metricas[k] = comun.desconocido("not_covered", "historia insuficiente")
                desconocidos.append({"campo": f"precios.metricas.{k}", "causa": "not_covered"})
            else:
                metricas[k] = comun.cifra(v, "ratio", "EUR", url, ff, obtenido)
        precio["metricas_eur"] = metricas

        try:
            secundarios = self._fundamentales_secundarios(ticker)
            secundarios = {"fuente_url": url + "/financials", "fecha_obtencion": obtenido, "anual": secundarios}
        except comun.ErrorDatos as e:
            secundarios = comun.desconocido(e.causa, str(e))
            desconocidos.append({"campo": "fundamentales_secundarios", "causa": e.causa})

        return {
            "precios": precio,
            "serie_eur": {"fechas": [d.date().isoformat() for d in aj_eur.index],
                          "accion": [round(float(v), 6) for v in aj_eur],
                          "benchmark": [round(float(v), 6) for v in bench_eur.reindex(aj_eur.index).ffill()]},
            "fundamentales_secundarios": secundarios,
            "desconocidos": desconocidos,
            "fuentes": [{"url": u, "retrieved_at": obtenido} for u in fuentes],
        }


class _SinDatos(Exception):
    pass


def _leer(fi: Any, clave: str) -> Any:
    try:
        return fi[clave]
    except Exception:
        return getattr(fi, clave, None)


def _float(v: Any) -> float | None:
    try:
        f = float(v)
        return None if np.isnan(f) else f
    except (TypeError, ValueError):
        return None


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Precios en EUR y métricas relativas frente a VWCE.")
    p.add_argument("ticker")
    p.add_argument("--benchmark", default=comun.cargar_config()["eventos"]["benchmark"])
    p.add_argument("--salida")
    p.add_argument("--sin-serie", action="store_true", help="No incluir la serie diaria en la salida")
    a = p.parse_args(argv)
    try:
        res = ClientePrecios().obtener(a.ticker.strip().upper(), a.benchmark)
    except comun.ErrorDatos as e:
        comun.salir_con_error(f"{e} [causa={e.causa}]")
    if a.sin_serie:
        res.pop("serie_eur", None)
    if a.salida:
        comun.escribir_json(a.salida, res)
        print(a.salida)
    else:
        print(comun.volcar_json(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())

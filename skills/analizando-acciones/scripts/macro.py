"""Macro: régimen semanal compartido por todas las acciones y sensibilidades por empresa.

Uso CLI:
    python macro.py regimen [--salida macro_regime.json] [--si-caducado]
    python macro.py sensibilidades --datapack datapack.json --serie precios_serie.json [--divisa BRL] [--salida f.json]

Régimen (fuentes: FRED, BCE, Damodaran). Etiquetas por reglas, con umbrales en config.yaml:
  tipos    cambio del 10 años en 26 semanas: > +25 pb subiendo, < −25 pb bajando, resto estables
  crédito  percentil a 10 años del spread: < 30 relajado, 30-70 normal, > 70 tenso
           (se usa BAA10Y; FRED solo ofrece 3 años del spread HY, que se reporta como dato informativo)
  curva    invertida si 10 años − 2 años < 0
Sensibilidades por empresa (retornos semanales en EUR de los últimos 3 años):
  beta frente al cambio semanal del DGS10 (por +100 pb) y frente al cambio semanal de la divisa relevante en EUR.
"""
from __future__ import annotations

import argparse
import csv
import io
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import comun  # noqa: E402
from datos.cache import CacheDisco, con_backoff  # noqa: E402

URL_FRED = "https://api.stlouisfed.org/fred/series/observations"
URL_BCE = "https://data-api.ecb.europa.eu/service/data/{clave}"
Serie = list[tuple[str, float]]


# ---------------------------------------------------------------- funciones puras

def valor_en(serie: Serie, fecha: str) -> tuple[str, float] | None:
    """Última observación con fecha ≤ `fecha`."""
    previas = [(d, v) for d, v in serie if d <= fecha]
    return previas[-1] if previas else None


def cambio_pb(serie: Serie, semanas: int) -> dict | None:
    """Cambio en puntos básicos entre la última observación y la de `semanas` semanas antes (series en %)."""
    if not serie:
        return None
    fin_d, fin_v = serie[-1]
    ini = (date.fromisoformat(fin_d) - timedelta(weeks=semanas)).isoformat()
    previo = valor_en(serie, ini)
    if previo is None or date.fromisoformat(previo[0]) < date.fromisoformat(ini) - timedelta(days=10):
        return None
    return {"cambio_pb": (fin_v - previo[1]) * 100, "desde": previo[0], "hasta": fin_d}


def etiqueta_tipos(cambio: float, umbral_pb: float) -> str:
    if cambio > umbral_pb:
        return "subiendo"
    if cambio < -umbral_pb:
        return "bajando"
    return "estables"


def percentil_historico(serie: Serie, anios: float) -> dict | None:
    """Percentil (0-100) de la última observación entre las de los últimos `anios` años (% de obs ≤ último)."""
    if not serie:
        return None
    fin_d, fin_v = serie[-1]
    ini = (date.fromisoformat(fin_d) - timedelta(days=round(365.25 * anios))).isoformat()
    ventana = [v for d, v in serie if d >= ini]
    cobertura = (date.fromisoformat(fin_d) - date.fromisoformat(serie[0][0])).days / 365.25
    return {"percentil": 100 * sum(1 for v in ventana if v <= fin_v) / len(ventana), "n": len(ventana),
            "anios_cubiertos": min(anios, cobertura), "completa": cobertura >= anios - 0.1}


def etiqueta_credito(percentil: float, cortes: list[float]) -> str:
    lo, hi = cortes
    return "relajado" if percentil < lo else ("tenso" if percentil > hi else "normal")


def etiqueta_curva(dgs10: float, dgs2: float) -> dict:
    d = dgs10 - dgs2
    return {"etiqueta": "invertida" if d < 0 else "normal", "pendiente_10a_2a_pb": d * 100}


def semanal(serie: Serie) -> pd.Series:
    s = pd.Series({pd.Timestamp(d): v for d, v in serie}, dtype="float64")
    return s.sort_index().resample("W-FRI").last().ffill()


def eur_por_divisa(divisa: str, eurusd: Serie, cruce: Serie | None, usd_por_divisa: bool) -> pd.Series:
    """Valor de 1 unidad de `divisa` en EUR (semanal). `cruce` es la serie FRED de la divisa frente al USD."""
    eu = semanal(eurusd)  # USD por EUR
    if divisa == "USD":
        return 1.0 / eu
    c = semanal(cruce)
    usd = c if usd_por_divisa else 1.0 / c
    return (usd / eu).dropna()


def regresion(y: pd.Series, x: pd.Series) -> dict | None:
    df = pd.concat([y, x], axis=1, join="inner").dropna()
    if len(df) < 30:
        return None
    yy, xx = df.iloc[:, 0].to_numpy(), df.iloc[:, 1].to_numpy()
    vx = xx.var(ddof=1)
    if vx == 0:
        return None
    beta = float(np.cov(xx, yy, ddof=1)[0, 1] / vx)
    alfa = float(yy.mean() - beta * xx.mean())
    resid = yy - (alfa + beta * xx)
    n = len(df)
    r2 = float(1 - resid.var(ddof=2) * (n - 2) / ((yy - yy.mean()) ** 2).sum()) if yy.var() > 0 else 0.0
    se = float(np.sqrt(resid.var(ddof=2) / ((xx - xx.mean()) ** 2).sum()))
    return {"beta": beta, "r2": r2, "t": beta / se if se > 0 else None, "n_semanas": n}


def retornos_semanales(fechas: list[str], valores: list[float]) -> pd.Series:
    s = pd.Series(valores, index=pd.to_datetime(fechas), dtype="float64")
    return np.log(s.resample("W-FRI").last().dropna()).diff().dropna()


def divisa_relevante(dp: dict) -> str:
    """Divisa de mayor peso entre los segmentos de tipo `moneda` distintos de EUR; si no hay, la de informe o USD."""
    pesos: dict[str, float] = {}
    for s in dp.get("segmentos") or []:
        if s.get("tipo") != "moneda" or comun.es_desconocido(s["ingresos"]):
            continue
        pesos[s["nombre"].strip().upper()] = pesos.get(s["nombre"].strip().upper(), 0) + s["ingresos"]["valor"]
    pesos.pop("EUR", None)
    if pesos:
        return max(pesos, key=pesos.get)
    empresa = dp.get("empresa") or {}
    return (empresa.get("moneda_informe") if not comun.es_desconocido(empresa) else None) or "USD"


def ingresos_por_moneda(dp: dict) -> Any:
    segs = [s for s in dp.get("segmentos") or [] if s.get("tipo") == "moneda" and not comun.es_desconocido(s["ingresos"])]
    if not segs:
        return comun.desconocido("not_covered", "sin segmentos de ingresos por moneda en el datapack")
    total = sum(s["ingresos"]["valor"] for s in segs)
    return [{"moneda": s["nombre"].strip().upper(), "peso": s["ingresos"]["valor"] / total,
             "fuente_url": s["ingresos"]["fuente_url"], "fecha_dato": s["ingresos"]["fecha_dato"]} for s in segs]


# ---------------------------------------------------------------- acceso a red

class ClienteMacro:
    def __init__(self, cache: CacheDisco | None = None, sesion: Any = None, clave_fred: str | None = None,
                 dormir: Any = None):
        import requests

        self.cache = cache or CacheDisco()
        self.sesion = sesion or requests.Session()
        self._clave = clave_fred
        self.dormir = dormir or time.sleep

    @property
    def clave_fred(self) -> str:
        return self._clave or comun.variable_requerida("FRED_API_KEY")

    def _get(self, url: str, params: dict | None = None) -> Any:
        import requests

        def pedir():
            try:
                r = self.sesion.get(url, params=params, timeout=60)
            except requests.RequestException as e:
                raise comun.ErrorDatos(f"No responde {url}: {e}", "source_down") from e
            if r.status_code == 429:
                raise comun.ErrorDatos(f"Límite de peticiones en {url}", "rate_limited")
            if r.status_code in (400, 401, 403):
                raise _Fatal(comun.ErrorDatos(f"Acceso rechazado ({r.status_code}) en {url}", "source_down"))
            if r.status_code == 404:
                raise _Fatal(comun.ErrorDatos(f"No existe {url}", "not_covered"))
            if r.status_code >= 400:
                raise comun.ErrorDatos(f"Error {r.status_code} en {url}", "source_down")
            return r

        try:
            return con_backoff(pedir, reintentos=3, espera_base=1.0, excepciones=(comun.ErrorDatos,), dormir=self.dormir)
        except _Fatal as e:
            raise e.error from None

    def fred(self, serie: str, anios: int = 11) -> Serie:
        desde = f"{date.today().year - anios}-01-01"

        def calcular() -> list:
            r = self._get(URL_FRED, {"series_id": serie, "api_key": self.clave_fred, "file_type": "json",
                                     "observation_start": desde})
            return [[o["date"], float(o["value"])] for o in r.json()["observations"] if o["value"] != "."]

        datos, _ = self.cache.obtener_o_calcular("macro", f"fred:{serie}:{desde}", calcular)
        if not datos:
            raise comun.ErrorDatos(f"FRED sin observaciones para {serie}", "not_covered")
        return [(d, v) for d, v in datos]

    def bce(self, clave: str, anios: int = 11) -> Serie:
        desde = f"{date.today().year - anios}-01-01"

        def calcular() -> list:
            r = self._get(URL_BCE.format(clave=clave), {"startPeriod": desde, "format": "csvdata"})
            filas = csv.DictReader(io.StringIO(r.text))
            return [[f["TIME_PERIOD"], float(f["OBS_VALUE"])] for f in filas if f.get("OBS_VALUE")]

        datos, _ = self.cache.obtener_o_calcular("macro", f"bce:{clave}:{desde}", calcular)
        if not datos:
            raise comun.ErrorDatos(f"BCE sin observaciones para {clave}", "not_covered")
        return [(d, v) for d, v in datos]


class _Fatal(Exception):
    def __init__(self, error: comun.ErrorDatos):
        super().__init__(str(error))
        self.error = error


def _intentar(desconocidos: list[dict], campo: str, f):
    """Ejecuta f(); si falla, registra el campo como desconocido y devuelve la marca."""
    try:
        return f()
    except comun.ErrorDatos as e:
        desconocidos.append({"campo": campo, "causa": e.causa, "detalle": str(e)})
        return comun.desconocido(e.causa, str(e))


def regimen(cliente: ClienteMacro | None = None, damodaran: Any = None, cfg: dict | None = None) -> dict:
    cfg = cfg or comun.cargar_config()
    m = cfg["macro"]
    cliente = cliente or ClienteMacro()
    desc: list[dict] = []
    ahora = comun.ahora_iso()

    s10 = _intentar(desc, "tipos.dgs10", lambda: cliente.fred(m["fred"]["tipos_10a"]))
    s2 = _intentar(desc, "curva.dgs2", lambda: cliente.fred(m["fred"]["tipos_2a"]))
    s3m = _intentar(desc, "curva.dgs3mo", lambda: cliente.fred(m["fred"]["tipos_3m"]))
    scr = _intentar(desc, "credito", lambda: cliente.fred(m["fred"]["credito"]))
    shy = _intentar(desc, "credito.hy", lambda: cliente.fred(m["fred"]["hy"]))
    seur = _intentar(desc, "fx.eurusd", lambda: cliente.fred(m["eurusd_fred"]))
    estr = _intentar(desc, "bce.estr", lambda: cliente.bce(m["ecb"]["estr"]))
    y10e = _intentar(desc, "bce.rendimiento_10a", lambda: cliente.bce(m["ecb"]["rendimiento_10a"]))

    ok = lambda s: isinstance(s, list)  # noqa: E731
    res: dict[str, Any] = {"generado": ahora, "fecha": date.today().isoformat(), "version_config": cfg["version"]}

    # tipos
    if ok(s10):
        c = cambio_pb(s10, m["tipos_ventana_sem"])
        res["tipos"] = ({"etiqueta": etiqueta_tipos(c["cambio_pb"], m["tipos_umbral_pb"]), "dgs10": s10[-1][1],
                         "fecha_dato": s10[-1][0], "ventana_semanas": m["tipos_ventana_sem"], **c}
                        if c else comun.desconocido("stale", "historia insuficiente para el cambio a 26 semanas"))
        res["rf_usd"] = {"valor": s10[-1][1] / 100, "fecha_dato": s10[-1][0], "fuente": f"FRED {m['fred']['tipos_10a']}"}
    else:
        res["tipos"] = res["rf_usd"] = s10
    # curva
    if ok(s10) and ok(s2):
        f = min(s10[-1][0], s2[-1][0])
        a, b = valor_en(s10, f), valor_en(s2, f)
        res["curva"] = {**etiqueta_curva(a[1], b[1]), "fecha_dato": f}
        if ok(s3m) and (c3 := valor_en(s3m, f)):
            res["curva"]["pendiente_10a_3m_pb"] = (a[1] - c3[1]) * 100
    else:
        res["curva"] = comun.desconocido("source_down", "faltan DGS10 o DGS2")
    # crédito
    if ok(scr):
        p = percentil_historico(scr, m["credito_ventana_anios"])
        res["credito"] = {"etiqueta": etiqueta_credito(p["percentil"], m["hy_percentiles"]), "serie": m["credito_serie"],
                          "nivel": scr[-1][1], "fecha_dato": scr[-1][0], "percentil": p["percentil"],
                          "ventana_anios": m["credito_ventana_anios"], "ventana_completa": p["completa"]}
        if ok(shy):
            ph = percentil_historico(shy, m["credito_ventana_anios"])
            res["credito"]["hy"] = {"serie": m["fred"]["hy"], "nivel": shy[-1][1], "fecha_dato": shy[-1][0],
                                    "percentil_en_ventana_disponible": ph["percentil"],
                                    "anios_disponibles": round(ph["anios_cubiertos"], 1)}
    else:
        res["credito"] = scr
    # euro
    res["estr"] = ({"valor": estr[-1][1] / 100, "fecha_dato": estr[-1][0], "fuente": "BCE EST"} if ok(estr) else estr)
    res["rf_eur"] = ({"valor": y10e[-1][1] / 100, "fecha_dato": y10e[-1][0],
                      "fuente": "BCE curva de tipos AAA del área euro, 10 años"} if ok(y10e) else y10e)
    if ok(seur):
        c = cambio_pb(seur, m["tipos_ventana_sem"])
        res["fx"] = {"eurusd": {"valor": seur[-1][1], "fecha_dato": seur[-1][0],
                                "cambio_pct_26s": None if not c else 100 * (seur[-1][1] / valor_en(seur, c["desde"])[1] - 1)}}
    else:
        res["fx"] = seur
    # ERP
    def erp():
        d = damodaran or _cliente_damodaran()
        e = d.erp()
        return {"valor": e["erp"], "fecha_dato": e["fecha_actualizacion"], "fuente": e["fuente_url"],
                "historica": e["historica"]}
    res["erp"] = _intentar(desc, "erp", erp)
    res["desconocidos"] = desc
    return res


def _cliente_damodaran():
    from datos.damodaran import ClienteDamodaran

    return ClienteDamodaran()


def sensibilidades(dp: dict, serie_eur: dict, cliente: ClienteMacro | None = None, divisa: str | None = None,
                   cfg: dict | None = None) -> dict:
    cfg = cfg or comun.cargar_config()
    m = cfg["macro"]
    cliente = cliente or ClienteMacro()
    desc: list[dict] = []
    divisa = (divisa or divisa_relevante(dp)).upper()
    anios = m["sensibilidad_anios"]
    ret = retornos_semanales(serie_eur["fechas"], serie_eur["accion"])
    ret = ret.loc[ret.index > ret.index[-1] - pd.DateOffset(years=anios)]

    s10 = _intentar(desc, "dgs10", lambda: cliente.fred(m["fred"]["tipos_10a"]))
    tipos: Any = s10
    if isinstance(s10, list):
        dy = semanal(s10).diff().dropna()  # puntos porcentuales por semana
        r = regresion(ret, dy)
        # x está en puntos porcentuales, así que la pendiente es el retorno semanal por +1 pp (= +100 pb).
        tipos = ({"beta_por_100pb": r["beta"], "r2": r["r2"], "t": r["t"], "n_semanas": r["n_semanas"],
                  "unidad": "retorno semanal de la acción en EUR (fracción) por +100 pb de variación semanal del DGS10",
                  "serie": m["fred"]["tipos_10a"]}
                 if r else comun.desconocido("stale", "menos de 30 semanas comunes"))

    fx: Any
    if divisa == "EUR":
        fx = comun.desconocido("not_covered", "la divisa relevante es el EUR: sin riesgo de cambio frente al euro")
    else:
        usd_por_div = divisa in m["fx_usd_por_divisa"]
        clave = m["fx_usd_por_divisa"].get(divisa) or m["fx_divisa_por_usd"].get(divisa)
        if divisa != "USD" and clave is None:
            fx = comun.desconocido("not_covered", f"sin serie FRED para la divisa {divisa}")
        else:
            seur = _intentar(desc, "eurusd", lambda: cliente.fred(m["eurusd_fred"]))
            cruce = None if divisa == "USD" else _intentar(desc, f"fx.{divisa}", lambda: cliente.fred(clave))
            if isinstance(seur, list) and (divisa == "USD" or isinstance(cruce, list)):
                v = eur_por_divisa(divisa, seur, cruce, usd_por_div)
                cambio = np.log(v).diff().dropna()
                r = regresion(ret, cambio)
                fx = ({"divisa": divisa, "beta": r["beta"], "r2": r["r2"], "t": r["t"], "n_semanas": r["n_semanas"],
                       "unidad": "elasticidad: % de variación semanal de la acción en EUR por cada +1 % de la "
                                 "divisa frente al EUR"} if r
                      else comun.desconocido("stale", "menos de 30 semanas comunes"))
            else:
                fx = comun.desconocido("source_down", f"no se pudo obtener la serie de {divisa}")

    deuda = dp.get("deuda") or {}
    return {
        "ticker": dp.get("ticker"), "generado": comun.ahora_iso(), "divisa_relevante": divisa,
        "ventana": {"anios": anios, "desde": str(ret.index[0].date()), "hasta": str(ret.index[-1].date()),
                    "frecuencia": "semanal", "retornos": "log, acción en EUR (cierre ajustado)"},
        "tipos": tipos, "divisa": fx, "ingresos_por_moneda": ingresos_por_moneda(dp),
        "deuda_tipo_variable": deuda.get("tipo_variable_pct") or comun.desconocido("not_covered", "sin dato en el datapack"),
        "vencimientos_24m": deuda.get("vencimientos_24m") or comun.desconocido("not_covered", "sin dato en el datapack"),
        "desconocidos": desc,
    }


def vigente(ruta: Path, max_dias: float) -> bool:
    if not ruta.exists():
        return False
    try:
        gen = datetime.fromisoformat(comun.leer_json(ruta)["generado"].replace("Z", "+00:00"))
    except (KeyError, ValueError):
        return False
    return (datetime.now(timezone.utc) - gen).total_seconds() < max_dias * 86400


def main(argv: list[str] | None = None) -> int:
    cfg = comun.cargar_config()
    p = argparse.ArgumentParser(description="Macro: régimen semanal y sensibilidades.")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("regimen")
    r.add_argument("--salida", default="macro_regime.json")
    r.add_argument("--si-caducado", action="store_true", help=f"No hace nada si el archivo tiene menos de "
                   f"{cfg['macro']['max_dias_regimen']} días")
    s = sub.add_parser("sensibilidades")
    s.add_argument("--datapack", required=True)
    s.add_argument("--serie", required=True, help="precios_serie.json generado por datapack_base.py")
    s.add_argument("--divisa")
    s.add_argument("--salida")
    a = p.parse_args(argv)
    try:
        if a.cmd == "regimen":
            if a.si_caducado and vigente(Path(a.salida), cfg["macro"]["max_dias_regimen"]):
                print(comun.volcar_json({"estado": "vigente", "archivo": a.salida}))
                return 0
            res = regimen(cfg=cfg)
        else:
            res = sensibilidades(comun.leer_json(a.datapack), comun.leer_json(a.serie), divisa=a.divisa, cfg=cfg)
    except (comun.ErrorDatos, FileNotFoundError, KeyError) as e:
        comun.salir_con_error(f"{type(e).__name__}: {e}")
    destino = a.salida
    if destino:
        comun.escribir_json(destino, res)
        print(destino)
    else:
        print(comun.volcar_json(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())

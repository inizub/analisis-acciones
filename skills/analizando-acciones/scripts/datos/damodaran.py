"""Datos de Damodaran: ERP implícita, primas de riesgo país y métricas por industria (EE. UU., Europa,
emergentes, global), con mapeo SIC → industria de Damodaran (assets/sic_rutas.csv).

Uso CLI:
    python damodaran.py erp
    python damodaran.py pais Brazil
    python damodaran.py sector --sic 7372 [--region us|europa|emergentes|global]
    python damodaran.py datapack --sic 6199 --pais Brazil [--salida damodaran.json]
"""
from __future__ import annotations

import argparse
import csv
import io
import re
import sys
import warnings
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import comun  # noqa: E402
from datos.cache import CacheDisco, con_backoff  # noqa: E402

RUTA_SIC = comun.DIR_ASSETS / "sic_rutas.csv"

# Columnas extraídas de cada conjunto: clave de salida -> nombre de columna normalizado (minúsculas,
# espacios simples). Si un nombre aparece repetido en el archivo se toma la primera aparición.
COLUMNAS: dict[str, dict[str, str]] = {
    "betas": {"n_empresas": "number of firms", "beta": "beta", "de_ratio": "d/e ratio",
              "tipo_impositivo_efectivo": "effective tax rate", "beta_desapalancada": "unlevered beta",
              "beta_desapalancada_caja": "unlevered beta corrected for cash",
              "desv_tipica_acciones": "standard deviation of equity",
              "desv_tipica_beneficio_operativo_10a": "standard deviation in operating income (last 10 years)"},
    "margenes": {"margen_bruto": "gross margin", "margen_neto": "net margin",
                 "margen_operativo": "pre-tax unadjusted operating margin",
                 "margen_operativo_despues_impuestos": "after-tax unadjusted operating margin",
                 "margen_operativo_ajustado_arrend": "pre-tax lease adjusted margin",
                 "sbc_ventas": "stock-based compensation/sales"},
    "roic": {"roe": "roe", "coste_capital_propio": "cost of equity", "roic": "roc", "wacc": "cost of capital"},
    "pbv": {"pbv": "pbv", "roe": "roe", "ev_capital_invertido": "ev/ invested capital", "roic": "roic"},
    "ev_ebitda": {"ev_ebitda": "ev/ebitda", "ev_ebit": "ev/ebit"},
    "roe": {"roe": "roe (unadjusted)"},
    "wacc": {"coste_deuda": "cost of debt", "deuda_sobre_capital": "d/(d+e)", "wacc": "cost of capital",
             "coste_capital_propio": "cost of equity"},
    "capex": {"ventas_capital": "sales/ invested capital (ltm)"},
}

# Región de los conjuntos sectoriales según la región de ctryprem.xlsx.
REGION_POR_REGION_CRP = {
    "Western Europe": "europa", "North America": "global", "Australia & New Zealand": "global",
    "Caribbean": "emergentes", "Central and South America": "emergentes", "Africa": "emergentes",
    "Asia": "emergentes", "Eastern Europe & Russia": "emergentes", "Middle East": "emergentes",
}
PAISES_DESARROLLADOS_ASIA = {"Japan", "Singapore", "Hong Kong", "South Korea", "Korea", "Taiwan", "Israel"}
ALIAS_PAISES = {"united states": "United States", "usa": "United States", "us": "United States",
                "brasil": "Brazil", "uk": "United Kingdom", "españa": "Spain", "cayman islands": "Cayman Islands"}


def _norm(s: Any) -> str:
    return re.sub(r"\s+", " ", str(s).replace("\n", " ")).strip().lower()


def archivo_conjunto(conjunto: str, region: str, cfg: dict | None = None) -> str:
    d = (cfg or comun.cargar_config())["damodaran"]
    if conjunto not in d["conjuntos"]:
        raise ValueError(f"Conjunto desconocido: {conjunto}")
    if region not in d["regiones"]:
        raise ValueError(f"Región desconocida: {region}")
    prefijo = d["conjuntos"][conjunto]
    if region == "us":
        return d["us_excepciones"].get(prefijo, prefijo) + ".xls"
    return prefijo + d["regiones"][region] + ".xls"


# ---------------------------------------------------------------- parsers (puros)

def _leer_excel(contenido: bytes, hoja: str | int, **kw: Any) -> pd.DataFrame:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return pd.read_excel(io.BytesIO(contenido), sheet_name=hoja, header=None, **kw)


def tabla_industrias(contenido: bytes) -> pd.DataFrame:
    """Hoja 'Industry Averages' con la fila cuyo primer valor es 'Industry Name' como cabecera."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        hojas = pd.ExcelFile(io.BytesIO(contenido)).sheet_names
    hoja = next((h for h in hojas if _norm(h) == "industry averages"), None)
    if hoja is None:
        raise comun.ErrorDatos(f"Archivo de Damodaran sin hoja 'Industry Averages' (hojas: {hojas})", "source_down")
    df = _leer_excel(contenido, hoja)
    filas = [i for i in range(len(df)) if _norm(df.iat[i, 0]) == "industry name"]
    if not filas:
        raise comun.ErrorDatos("No se encuentra la fila de cabecera 'Industry Name'", "source_down")
    f = filas[0]
    columnas, vistos = [], set()
    for c in df.iloc[f].tolist():
        n = _norm(c)
        while n in vistos:
            n += " #2"
        vistos.add(n)
        columnas.append(n)
    datos = df.iloc[f + 1:].copy()
    datos.columns = columnas
    datos = datos[datos["industry name"].notna()]
    datos["industry name"] = datos["industry name"].map(lambda s: str(s).strip())
    return datos.set_index("industry name")


def _num(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(f) else f


def erp_madura(contenido_ctryprem: bytes) -> dict:
    """ERP implícita del mercado maduro (S&P 500) y fecha de actualización, de la hoja 'ERPs by country'."""
    df = _leer_excel(contenido_ctryprem, "ERPs by country")
    erp = fecha = None
    for i in range(min(len(df), 15)):
        fila = [df.iat[i, j] for j in range(df.shape[1])]
        textos = [_norm(x) for x in fila]
        if textos[0].startswith("date of update") and fecha is None:
            fecha = pd.Timestamp(fila[1]).date().isoformat() if _fecha_valida(fila[1]) else None
        for j, t in enumerate(textos):
            if t.startswith("implied erp") and j > 0 and erp is None:
                erp = next((_num(fila[k]) for k in range(j - 1, -1, -1) if _num(fila[k]) is not None), None)
    if erp is None:
        raise comun.ErrorDatos("No se encuentra la ERP implícita en ctryprem", "source_down")
    return {"erp": erp, "fecha_actualizacion": fecha}


def _fecha_valida(v: Any) -> bool:
    try:
        pd.Timestamp(v)
        return True
    except (ValueError, TypeError):
        return False


def erp_historica(contenido_histimpl: bytes) -> dict:
    """Última fila anual de histimpl.xls: ERP implícita (FCFE) y T-bond a 10 años."""
    df = _leer_excel(contenido_histimpl, 0)
    cab = next(i for i in range(len(df)) if _norm(df.iat[i, 0]) == "year")
    cols = [_norm(c) for c in df.iloc[cab]]
    if "implied erp (fcfe)" not in cols:
        raise comun.ErrorDatos("histimpl.xls sin columna 'Implied ERP (FCFE)'", "source_down")
    j_erp, j_tb = cols.index("implied erp (fcfe)"), cols.index("t.bond rate")
    ultimo = None
    for i in range(cab + 1, len(df)):
        anio = _num(df.iat[i, 0])
        if anio is None or not 1900 < anio < 2200:
            break
        if _num(df.iat[i, j_erp]) is not None:
            ultimo = (int(anio), _num(df.iat[i, j_erp]), _num(df.iat[i, j_tb]))
    if ultimo is None:
        raise comun.ErrorDatos("histimpl.xls sin datos anuales", "source_down")
    return {"anio": ultimo[0], "erp": ultimo[1], "tbond": ultimo[2]}


def primas_pais(contenido_ctryprem: bytes) -> dict[str, dict]:
    df = _leer_excel(contenido_ctryprem, "ERPs by country")
    cab = next(i for i in range(len(df)) if _norm(df.iat[i, 0]) == "country")
    cols = [_norm(c) for c in df.iloc[cab]]

    def col(prefijo: str) -> int:
        return next(j for j, c in enumerate(cols) if c.startswith(prefijo))

    j_rat = col("moody")
    j_ds = col("rating-based default")
    j_erp = col("total equity risk")
    j_crp = col("country risk premium")
    res = {}
    for i in range(cab + 1, len(df)):
        pais = df.iat[i, 0]
        if pd.isna(pais) or _num(df.iat[i, j_erp]) is None:
            continue
        res[str(pais).strip()] = {
            "region": str(df.iat[i, 1]).strip(), "rating_moodys": str(df.iat[i, j_rat]).strip(),
            "diferencial_impago": _num(df.iat[i, j_ds]), "erp_total": _num(df.iat[i, j_erp]),
            "crp": _num(df.iat[i, j_crp]),
        }
    for pais, tasa in tasas_impositivas(contenido_ctryprem).items():
        if pais in res:
            res[pais]["tasa_impuestos"] = tasa
    return res


def tasas_impositivas(contenido_ctryprem: bytes) -> dict[str, float]:
    """Tipo del impuesto de sociedades por país (hoja 'Regional breakdown'). Vacío si la hoja no existe."""
    try:
        df = _leer_excel(contenido_ctryprem, "Regional breakdown")
    except (ValueError, KeyError):
        return {}
    filas = [i for i in range(min(len(df), 10)) if _norm(df.iat[i, 0]) == "country"]
    if not filas:
        return {}
    cols = [_norm(c) for c in df.iloc[filas[0]]]
    j = next((k for k, c in enumerate(cols) if c.startswith("corporate tax rate")), None)
    if j is None:
        return {}
    return {str(df.iat[i, 0]).strip(): _num(df.iat[i, j]) for i in range(filas[0] + 1, len(df))
            if not pd.isna(df.iat[i, 0]) and _num(df.iat[i, j]) is not None}


def tabla_ratings(html: str) -> list[dict]:
    """Tabla de rating sintético para empresas grandes no financieras de ratings.htm de Damodaran:
    [{cobertura_min, rating, diferencial}] ordenada por cobertura."""
    import html as html_mod

    filas = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, flags=re.S | re.I):
        celdas = [html_mod.unescape(re.sub(r"<[^>]+>", " ", c)).strip()
                  for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, flags=re.S | re.I)]
        if len(celdas) < 4:
            continue
        minimo, rating, dif = celdas[0].replace(",", ""), celdas[2], celdas[3]
        if re.fullmatch(r"-?\d+(\.\d+)?", minimo) and dif.endswith("%") and rating:
            filas.append({"cobertura_min": float(minimo), "rating": rating,
                          "diferencial": float(dif.rstrip("%").strip()) / 100})
    if len(filas) < 10:
        raise comun.ErrorDatos("No se reconoce la tabla de rating sintético de Damodaran", "source_down")
    return sorted(filas, key=lambda f: f["cobertura_min"])


@lru_cache(maxsize=1)
def _tabla_sic() -> tuple[tuple[int, int, str, str, bool, str], ...]:
    with open(RUTA_SIC, encoding="utf-8") as f:
        return tuple((int(r["sic_desde"]), int(r["sic_hasta"]), r["industria_damodaran"], r["ruta"],
                      r["ciclica"] == "1", r["motivo"]) for r in csv.DictReader(f))


def clasificar_sic(sic: int | None) -> dict:
    """Fila más específica (rango más estrecho) de sic_rutas.csv que contiene `sic`."""
    if sic is None:
        return {"industria_damodaran": "Total Market", "ruta_sic": "general", "ciclica_sic": False,
                "motivo": "sin código SIC", "sic_rango": None}
    candidatas = [r for r in _tabla_sic() if r[0] <= sic <= r[1]]
    if not candidatas:
        return {"industria_damodaran": "Total Market", "ruta_sic": "general", "ciclica_sic": False,
                "motivo": f"SIC {sic} sin mapeo", "sic_rango": None}
    d, h, ind, ruta, cic, mot = min(candidatas, key=lambda r: r[1] - r[0])
    return {"industria_damodaran": ind, "ruta_sic": ruta, "ciclica_sic": cic, "motivo": mot, "sic_rango": [d, h]}


def normalizar_pais(pais: str) -> str:
    return ALIAS_PAISES.get(pais.strip().lower(), pais.strip())


def region_sectorial(pais: str | None, primas: dict[str, dict] | None = None) -> str:
    if not pais:
        return "global"
    p = normalizar_pais(pais)
    if p == "United States":
        return "us"
    if p in PAISES_DESARROLLADOS_ASIA:
        return "global"
    if primas and p in primas:
        return REGION_POR_REGION_CRP.get(primas[p]["region"], "global")
    return "global"


def unidad_columna(clave: str) -> str:
    """'veces' para múltiplos y betas, 'empresas' para el recuento, 'ratio' para el resto."""
    campo = clave.split(".")[-1]
    if campo == "n_empresas":
        return "empresas"
    if campo in ("pbv", "ev_ebitda", "ev_ebit", "ev_capital_invertido", "de_ratio", "ventas_capital") \
            or campo.startswith("beta"):
        return "veces"
    return "ratio"


def extraer_sector(tablas: dict[str, pd.DataFrame], industria: str) -> dict[str, float | None]:
    res: dict[str, float | None] = {}
    for conjunto, cols in COLUMNAS.items():
        t = tablas.get(conjunto)
        for clave, col in cols.items():
            nombre = f"{conjunto}.{clave}"
            if t is None or industria not in t.index or col not in t.columns:
                res[nombre] = None
                continue
            res[nombre] = _num(t.at[industria, col])
    return res


# ---------------------------------------------------------------- acceso a red

class ClienteDamodaran:
    def __init__(self, cache: CacheDisco | None = None, sesion: Any = None):
        import requests

        self.cfg = comun.cargar_config()
        self.base = self.cfg["damodaran"]["base_url"]
        self.cache = cache or CacheDisco()
        self.sesion = sesion or requests.Session()

    def url(self, archivo: str) -> str:
        return self.base + archivo

    def descargar(self, archivo: str) -> tuple[bytes, str]:
        """Descarga un archivo de datasets/ (o una URL completa si empieza por http) con caché de 30 días."""
        import requests

        url = archivo if archivo.startswith("http") else self.url(archivo)
        b = self.cache.obtener_bytes("damodaran", url)
        if b is not None:
            return b, "cache"

        def pedir() -> bytes:
            try:
                r = self.sesion.get(url, timeout=90)
            except requests.RequestException as e:
                raise comun.ErrorDatos(f"Damodaran no responde ({url}): {e}", "source_down") from e
            if r.status_code == 404:
                raise comun.ErrorDatos(f"Damodaran 404: {url}", "not_covered")
            if r.status_code >= 400:
                raise comun.ErrorDatos(f"Damodaran error {r.status_code}: {url}", "source_down")
            return r.content

        try:
            b = con_backoff(pedir, reintentos=2, espera_base=2.0, excepciones=(comun.ErrorDatos,))
        except comun.ErrorDatos:
            viejo = self.cache.obtener_bytes("damodaran", url, permitir_caducado=True)
            if viejo is None:
                raise
            return viejo, "cache_caducada"
        self.cache.guardar_bytes("damodaran", url, b)
        return b, "red"

    def erp(self) -> dict:
        b, _ = self.descargar(self.cfg["damodaran"]["archivo_primas_pais"])
        res = erp_madura(b)
        try:
            h, _ = self.descargar(self.cfg["damodaran"]["archivo_erp_historica"])
            res["historica"] = erp_historica(h)
        except comun.ErrorDatos as e:
            res["historica"] = comun.desconocido(e.causa, str(e))
        res["fuente_url"] = self.url(self.cfg["damodaran"]["archivo_primas_pais"])
        return res

    def primas(self) -> dict[str, dict]:
        b, _ = self.descargar(self.cfg["damodaran"]["archivo_primas_pais"])
        return primas_pais(b)

    def ratings(self) -> list[dict]:
        b, _ = self.descargar(self.cfg["damodaran"]["url_ratings"])
        return tabla_ratings(b.decode("latin-1"))

    def sector(self, industria: str, region: str) -> dict:
        tablas, urls = {}, {}
        for conjunto in COLUMNAS:
            archivo = archivo_conjunto(conjunto, region, self.cfg)
            try:
                b, _ = self.descargar(archivo)
                tablas[conjunto] = tabla_industrias(b)
                urls[conjunto] = self.url(archivo)
            except comun.ErrorDatos as e:
                urls[conjunto] = comun.desconocido(e.causa, str(e))
        return {"valores": extraer_sector(tablas, industria), "urls": urls}


def construir_seccion(sic: int | None, pais: str | None, cliente: ClienteDamodaran | None = None,
                      region: str | None = None) -> dict:
    """Sección `damodaran` del datapack: ERP, prima del país y métricas del sector (como cifras)."""
    cliente = cliente or ClienteDamodaran()
    obtenido = comun.ahora_iso()
    desconocidos: list[dict] = []
    clas = clasificar_sic(sic)
    erp = cliente.erp()
    fecha_dam = erp.get("fecha_actualizacion") or obtenido[:10]
    url_crp = erp["fuente_url"]
    primas = cliente.primas()
    region = region or region_sectorial(pais, primas)
    pais_n = normalizar_pais(pais) if pais else None
    if pais_n and pais_n in primas:
        p = primas[pais_n]
        prima = {k: (comun.cifra(v, "ratio", None, url_crp, fecha_dam, obtenido) if v is not None
                     else comun.desconocido("not_covered")) for k, v in p.items() if k not in ("region", "rating_moodys")}
        prima.update({"pais": pais_n, "region": p["region"], "rating_moodys": p["rating_moodys"]})
    else:
        prima = comun.desconocido("not_covered", f"País sin prima en Damodaran: {pais}")
        desconocidos.append({"campo": "damodaran.prima_pais", "causa": "not_covered"})
    sec = cliente.sector(clas["industria_damodaran"], region)
    valores = {}
    for k, v in sec["valores"].items():
        conjunto = k.split(".")[0]
        url = sec["urls"].get(conjunto)
        if v is None or not isinstance(url, str):
            valores[k] = comun.desconocido("not_covered", f"{clas['industria_damodaran']} / {region}")
            desconocidos.append({"campo": f"damodaran.sector.{k}", "causa": "not_covered"})
        else:
            valores[k] = comun.cifra(v, unidad_columna(k), None, url, fecha_dam, obtenido)
    try:
        ratings: Any = {"fuente_url": cliente.cfg["damodaran"]["url_ratings"], "fecha_obtencion": obtenido,
                        "filas": cliente.ratings()}
    except comun.ErrorDatos as e:
        ratings = comun.desconocido(e.causa, str(e))
        desconocidos.append({"campo": "damodaran.tabla_ratings", "causa": e.causa})
    return {
        "erp_madura": comun.cifra(erp["erp"], "ratio", "USD", url_crp, fecha_dam, obtenido),
        "erp_historica": erp["historica"],
        "prima_pais": prima,
        "sector": {"industria": clas["industria_damodaran"], "region": region, "clasificacion_sic": clas,
                   "valores": valores},
        "tabla_ratings": ratings,
        "desconocidos": desconocidos,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Datos de Damodaran (ERP, primas país, sectores).")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("erp")
    pp = sub.add_parser("pais")
    pp.add_argument("pais")
    ps = sub.add_parser("sector")
    ps.add_argument("--sic", type=int, required=True)
    ps.add_argument("--region", choices=["us", "europa", "emergentes", "global"], default="us")
    pd_ = sub.add_parser("datapack")
    pd_.add_argument("--sic", type=int)
    pd_.add_argument("--pais")
    pd_.add_argument("--region", choices=["us", "europa", "emergentes", "global"])
    pd_.add_argument("--salida")
    a = p.parse_args(argv)
    try:
        c = ClienteDamodaran()
        if a.cmd == "erp":
            res = c.erp()
        elif a.cmd == "pais":
            primas = c.primas()
            n = normalizar_pais(a.pais)
            if n not in primas:
                comun.salir_con_error(f"País no encontrado: {a.pais}")
            res = {"pais": n, **primas[n], "region_sectorial": region_sectorial(n, primas)}
        elif a.cmd == "sector":
            clas = clasificar_sic(a.sic)
            res = {"clasificacion": clas, **c.sector(clas["industria_damodaran"], a.region)}
        else:
            res = construir_seccion(a.sic, a.pais, c, a.region)
    except comun.ErrorDatos as e:
        comun.salir_con_error(f"{e} [causa={e.causa}]")
    if getattr(a, "salida", None):
        comun.escribir_json(a.salida, res)
        print(a.salida)
    else:
        print(comun.volcar_json(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())

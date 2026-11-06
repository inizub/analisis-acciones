"""Fundamentales anuales desde SEC EDGAR (submissions + companyfacts), taxonomía us-gaap o ifrs-full.

Uso CLI:
    python edgar.py TICKER [--salida edgar.json] [--anios 10]

Salida: {empresa, fundamentales, desconocidos, fuentes}. Cada punto de una serie es una cifra
{valor, unidad, moneda, fuente_url, fecha_dato, fecha_obtencion} con `ejercicio`, `concepto`,
`forma`, `presentado` y `accn`.

Deduplicación: dentro de los informes anuales (10-K, 20-F, 40-F y enmiendas, fp=FY) se agrupa por
periodo (`start`/`end`) y se conserva la última presentación (`filed`), de modo que las
reexpresiones prevalecen. Se agrupa por periodo y no por `fy` porque `fy` identifica el ejercicio
del informe, no el del dato (un 10-K de 2024 trae también cifras de 2022 y 2023).
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import comun  # noqa: E402
from datos.cache import CacheDisco, TokenBucket, con_backoff  # noqa: E402

URL_TICKERS = "https://www.sec.gov/files/company_tickers.json"
URL_SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik}.json"
URL_FACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"

FORMAS_ANUALES = {"10-K", "10-K/A", "10-KT", "10-KT/A", "20-F", "20-F/A", "40-F", "40-F/A"}

# Candidatos por campo y taxonomía, en orden de preferencia. Un candidato puede ser:
#   "Concepto"                      -> concepto simple
#   ("A", "B", "?C")                -> suma; los marcados con "?" son opcionales (0 si faltan en el periodo)
CAMPOS: dict[str, dict[str, Any]] = {
    "ingresos": {"tipo": "flujo", "unidad": "moneda",
        "us-gaap": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet",
                    "RevenueFromContractWithCustomerIncludingAssessedTax", "RevenuesNetOfInterestExpense"],
        "ifrs-full": ["Revenue", "RevenueFromContractsWithCustomers"]},
    "beneficio_operativo": {"tipo": "flujo", "unidad": "moneda",
        "us-gaap": ["OperatingIncomeLoss"],
        "ifrs-full": ["ProfitLossFromOperatingActivities"]},
    "beneficio_neto": {"tipo": "flujo", "unidad": "moneda",
        "us-gaap": ["NetIncomeLoss", "NetIncomeLossAvailableToCommonStockholdersBasic", "ProfitLoss"],
        "ifrs-full": ["ProfitLossAttributableToOwnersOfParent", "ProfitLoss"]},
    "fco": {"tipo": "flujo", "unidad": "moneda",
        "us-gaap": ["NetCashProvidedByUsedInOperatingActivities",
                    "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"],
        "ifrs-full": ["CashFlowsFromUsedInOperatingActivities"]},
    "capex": {"tipo": "flujo", "unidad": "moneda",
        "us-gaap": ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"],
        "ifrs-full": ["PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
                      "PurchaseOfPropertyPlantAndEquipment"]},
    "da": {"tipo": "flujo", "unidad": "moneda",
        "us-gaap": ["DepreciationDepletionAndAmortization", "DepreciationAndAmortization",
                    "DepreciationAmortizationAndAccretionNet", "Depreciation"],
        "ifrs-full": ["DepreciationAndAmortisationExpense", "AdjustmentsForDepreciationAndAmortisationExpense"]},
    "sbc": {"tipo": "flujo", "unidad": "moneda",
        "us-gaap": ["ShareBasedCompensation", "AllocatedShareBasedCompensationExpense"],
        "ifrs-full": ["AdjustmentsForSharebasedPayments", "ExpenseFromSharebasedPaymentTransactionsWithEmployees"]},
    "acciones_diluidas": {"tipo": "flujo", "unidad": "acciones",
        "us-gaap": ["WeightedAverageNumberOfDilutedSharesOutstanding"],
        "ifrs-full": ["AdjustedWeightedAverageShares", "WeightedAverageShares"]},
    "deuda_total": {"tipo": "saldo", "unidad": "moneda",
        "us-gaap": ["LongTermDebt", "DebtLongtermAndShorttermCombinedAmount",
                    ("LongTermDebtNoncurrent", "?LongTermDebtCurrent", "?CommercialPaper", "?ShortTermBorrowings"),
                    "LongTermDebtNoncurrent"],
        "ifrs-full": ["Borrowings", ("LongtermBorrowings", "?ShorttermBorrowings", "?CurrentPortionOfLongtermBorrowings")]},
    "caja": {"tipo": "saldo", "unidad": "moneda",
        "us-gaap": ["CashAndCashEquivalentsAtCarryingValue",
                    "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents", "Cash"],
        "ifrs-full": ["CashAndCashEquivalents"]},
    "patrimonio": {"tipo": "saldo", "unidad": "moneda",
        "us-gaap": ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
        "ifrs-full": ["EquityAttributableToOwnersOfParent", "Equity"]},
    "cxc": {"tipo": "saldo", "unidad": "moneda",
        "us-gaap": ["AccountsReceivableNetCurrent", "ReceivablesNetCurrent"],
        "ifrs-full": ["TradeAndOtherCurrentReceivables", "CurrentTradeReceivables", "TradeAndOtherReceivables"]},
    "inventario": {"tipo": "saldo", "unidad": "moneda",
        "us-gaap": ["InventoryNet"],
        "ifrs-full": ["Inventories"]},
    "goodwill": {"tipo": "saldo", "unidad": "moneda",
        "us-gaap": ["Goodwill"],
        "ifrs-full": ["Goodwill"]},
    "intangibles": {"tipo": "saldo", "unidad": "moneda",
        "us-gaap": ["IntangibleAssetsNetExcludingGoodwill", "FiniteLivedIntangibleAssetsNet"],
        "ifrs-full": ["IntangibleAssetsOtherThanGoodwill"]},
    "activos_totales": {"tipo": "saldo", "unidad": "moneda",
        "us-gaap": ["Assets"],
        "ifrs-full": ["Assets"]},
    "gasto_intereses": {"tipo": "flujo", "unidad": "moneda",
        "us-gaap": ["InterestExpense", "InterestExpenseNonoperating", "InterestExpenseDebt"],
        "ifrs-full": ["FinanceCosts", "InterestExpense"]},
    "dividendos": {"tipo": "flujo", "unidad": "moneda",
        "us-gaap": ["PaymentsOfDividends", "PaymentsOfDividendsCommonStock"],
        "ifrs-full": ["DividendsPaidClassifiedAsFinancingActivities", "DividendsPaid"]},
    "recompras": {"tipo": "flujo", "unidad": "moneda",
        "us-gaap": ["PaymentsForRepurchaseOfCommonStock"],
        "ifrs-full": ["PaymentsToAcquireOrRedeemEntitysShares"]},
    # Bancos
    "prestamos": {"tipo": "saldo", "unidad": "moneda", "banco": True,
        "us-gaap": ["LoansAndLeasesReceivableNetReportedAmount",
                    "FinancingReceivableExcludingAccruedInterestAfterAllowanceForCreditLoss",
                    "LoansAndLeasesReceivableNetOfDeferredIncome"],
        "ifrs-full": ["LoansAndAdvancesToCustomers"]},
    "depositos": {"tipo": "saldo", "unidad": "moneda", "banco": True,
        "us-gaap": ["Deposits"],
        "ifrs-full": ["DepositsFromCustomers"]},
    "provisiones": {"tipo": "flujo", "unidad": "moneda", "banco": True,
        "us-gaap": ["ProvisionForLoanLeaseAndOtherLosses", "ProvisionForLoanAndLeaseLosses",
                    "ProvisionForCreditLossesNet", "FinancingReceivableCreditLossExpenseReversal"],
        "ifrs-full": ["ImpairmentLossImpairmentGainAndReversalOfImpairmentLossDeterminedInAccordanceWithIFRS9",
                      "ImpairmentLossOnFinancialAssets"]},
    "ingresos_intereses_netos": {"tipo": "flujo", "unidad": "moneda", "banco": True,
        "us-gaap": ["InterestIncomeExpenseNet", "InterestIncomeExpenseOperatingNet"],
        # No se usa ifrs-full:InterestRevenueExpense: hay emisores (p. ej. NU) que etiquetan con él
        # el gasto total por intereses. Si no hay ingresos por intereses separados, queda desconocido.
        "ifrs-full": [("InterestRevenueCalculatedUsingEffectiveInterestMethod", "-InterestExpense"),
                      ("RevenueFromInterest", "-InterestExpense")]},
}

SIC_BANCARIOS = range(6000, 6200)

DUR_ANUAL_MIN, DUR_ANUAL_MAX = 330, 400


# ---------------------------------------------------------------- utilidades puras

def normalizar_ticker(ticker: str) -> str:
    t = ticker.strip().upper()
    if not t:
        raise ValueError("Ticker vacío")
    return t.replace(".", "-").replace("/", "-")


def cik10(cik: int | str) -> str:
    return str(int(cik)).zfill(10)


def ejercicio_de(fin: str) -> int:
    """Ejercicio fiscal a partir de la fecha de cierre. Un cierre en enero se asigna al año anterior."""
    d = date.fromisoformat(fin)
    return d.year - 1 if d.month == 1 else d.year


def _dias(inicio: str, fin: str) -> int:
    return (date.fromisoformat(fin) - date.fromisoformat(inicio)).days


def detectar_taxonomia(facts: dict) -> str:
    f = facts.get("facts", {})
    us, ifrs = len(f.get("us-gaap", {})), len(f.get("ifrs-full", {}))
    if not us and not ifrs:
        raise comun.ErrorDatos("El emisor no tiene hechos us-gaap ni ifrs-full en companyfacts", "not_covered")
    return "us-gaap" if us >= ifrs else "ifrs-full"


def hechos_anuales(facts: dict, taxonomia: str, concepto: str, tipo: str) -> tuple[dict[str, dict], str | None]:
    """Devuelve ({periodo_fin: hecho}, unidad) con un hecho por periodo, el de presentación más reciente."""
    nodo = facts.get("facts", {}).get(taxonomia, {}).get(concepto)
    if not nodo:
        return {}, None
    unidades = nodo.get("units", {})
    if not unidades:
        return {}, None
    # Unidad con más hechos anuales (normalmente la única).
    unidad = max(unidades, key=lambda u: sum(1 for h in unidades[u] if h.get("form") in FORMAS_ANUALES))
    por_periodo: dict[str, dict] = {}
    for h in unidades[unidad]:
        if h.get("form") not in FORMAS_ANUALES or h.get("fp") != "FY" or h.get("val") is None:
            continue
        if tipo == "flujo":
            if "start" not in h:
                continue
            if not DUR_ANUAL_MIN <= _dias(h["start"], h["end"]) <= DUR_ANUAL_MAX:
                continue
        elif "start" in h:
            continue
        fin = h["end"]
        previo = por_periodo.get(fin)
        if previo is None or (h["filed"], h.get("accn", "")) > (previo["filed"], previo.get("accn", "")):
            por_periodo[fin] = h
    return por_periodo, unidad


def _serie_candidato(facts: dict, tax: str, cand: Any, tipo: str) -> tuple[dict[str, dict], str | None, str]:
    """Serie {fin: {val, filed, form, accn, start?}} para un candidato simple o compuesto."""
    if isinstance(cand, str):
        s, u = hechos_anuales(facts, tax, cand, tipo)
        return s, u, cand
    # Prefijos: "?" opcional (0 si falta), "-" se resta (obligatorio).
    partes = [(c.lstrip("?-"), c.startswith("?"), -1.0 if c.startswith("-") else 1.0) for c in cand]
    nombre_comp = "".join(("-" if s < 0 else ("+" if i else "")) + n for i, (n, _, s) in enumerate(partes))
    series = {nombre: hechos_anuales(facts, tax, nombre, tipo) for nombre, _, _ in partes}
    obligatorias = [n for n, opc, _ in partes if not opc]
    if not obligatorias:
        raise ValueError("Un candidato compuesto necesita al menos un concepto obligatorio")
    unidades = {series[n][1] for n in obligatorias if series[n][1]}
    if len(unidades) != 1 or any(not series[n][0] for n in obligatorias):
        return {}, None, nombre_comp
    unidad = unidades.pop()
    fines = set.intersection(*(set(series[n][0]) for n in obligatorias))
    res = {}
    for fin in fines:
        total, ultimo = 0.0, None
        for nombre, _, signo in partes:
            s, u = series[nombre]
            h = s.get(fin)
            if h is None or (u and u != unidad):
                continue
            total += signo * h["val"]
            if ultimo is None or h["filed"] > ultimo["filed"]:
                ultimo = h
        res[fin] = {**ultimo, "val": total}
    return res, unidad, nombre_comp


def extraer_campo(facts: dict, tax: str, campo: str, anios: int, url: str, obtenido: str) -> dict:
    """Serie anual de un campo (las `anios` más recientes) o desconocido(not_covered)."""
    spec = CAMPOS[campo]
    candidatos = []
    for orden, cand in enumerate(spec[tax]):
        serie, unidad, nombre = _serie_candidato(facts, tax, cand, spec["tipo"])
        if serie:
            candidatos.append((serie, unidad, nombre, orden))
    if not candidatos:
        return comun.desconocido("not_covered", f"Ningún concepto {tax} disponible para {campo}")
    # Principal: el candidato con el dato más reciente (a igualdad, el de mayor prioridad).
    # Los demás solo rellenan periodos que el principal no tiene y con la misma unidad
    # (las empresas cambian de concepto XBRL con los años).
    candidatos.sort(key=lambda c: (max(c[0]), -c[3]), reverse=True)
    principal, unidad, nombre_p, _ = candidatos[0]
    combinada = {fin: (h, nombre_p) for fin, h in principal.items()}
    for serie, u, nombre, _ in candidatos[1:]:
        if u != unidad:
            continue
        for fin, h in serie.items():
            combinada.setdefault(fin, (h, nombre))
    es_moneda = spec["unidad"] == "moneda"
    puntos = []
    for fin in sorted(combinada)[-anios:]:
        h, nombre = combinada[fin]
        puntos.append(comun.cifra(
            h["val"], "unidades" if es_moneda else "acciones", unidad if es_moneda else None,
            url, fin, obtenido,
            ejercicio=ejercicio_de(fin), periodo_inicio=h.get("start"), concepto=nombre,
            forma=h.get("form"), presentado=h.get("filed"), accn=h.get("accn"),
        ))
    return {"concepto": nombre_p, "serie": puntos}


def patrimonio_tangible(fund: dict) -> dict:
    """patrimonio − goodwill − intangibles, por periodo. Goodwill/intangibles ausentes cuentan como 0 (se anota)."""
    pat = fund.get("patrimonio")
    if not pat or comun.es_desconocido(pat):
        return comun.desconocido("not_covered", "Sin patrimonio")
    gw = {p["fecha_dato"]: p["valor"] for p in fund.get("goodwill", {}).get("serie", [])}
    it = {p["fecha_dato"]: p["valor"] for p in fund.get("intangibles", {}).get("serie", [])}
    puntos = []
    for p in pat["serie"]:
        f = p["fecha_dato"]
        faltan = [n for n, d in (("goodwill", gw), ("intangibles", it)) if f not in d]
        q = dict(p)
        q["valor"] = p["valor"] - gw.get(f, 0) - it.get(f, 0)
        q["concepto"] = "calculado: patrimonio - goodwill - intangibles"
        if faltan:
            q["nota"] = "sin dato de " + " y ".join(faltan) + " en el periodo; se toma 0"
        puntos.append(q)
    return {"concepto": "calculado", "serie": puntos}


def marcar_desactualizadas(fund: dict) -> None:
    """Marca las series cuyo último dato es anterior al último ejercicio de ingresos o activos."""
    refs = [fund[c]["serie"][-1]["fecha_dato"] for c in ("ingresos", "activos_totales")
            if c in fund and not comun.es_desconocido(fund[c]) and fund[c]["serie"]]
    if not refs:
        return
    ultimo = max(refs)
    for v in fund.values():
        if comun.es_desconocido(v) or not v.get("serie"):
            continue
        fin = v["serie"][-1]["fecha_dato"]
        v["ultimo_periodo"] = fin
        v["desactualizada"] = fin < ultimo


def extraer_fundamentales(facts: dict, anios: int, url: str, obtenido: str | None = None,
                          sic: int | None = None) -> tuple[str, dict, list]:
    """Extrae todos los campos. Los campos bancarios solo se piden a emisores con SIC 6000-6199;
    en el resto se incluyen si existen y se omiten si no."""
    obtenido = obtenido or comun.ahora_iso()
    tax = detectar_taxonomia(facts)
    es_banco = sic is not None and sic in SIC_BANCARIOS
    fund = {}
    for c, spec in CAMPOS.items():
        v = extraer_campo(facts, tax, c, anios, url, obtenido)
        if spec.get("banco") and not es_banco and comun.es_desconocido(v):
            continue
        fund[c] = v
    fund["patrimonio_tangible"] = patrimonio_tangible(fund)
    marcar_desactualizadas(fund)
    desconocidos = [{"campo": c, "causa": v["causa"]} for c, v in fund.items() if comun.es_desconocido(v)]
    return tax, fund, desconocidos


def max_presentado_anual(facts: dict) -> str | None:
    fechas = [h["filed"] for tax in facts.get("facts", {}).values() for n in tax.values()
              for u in n.get("units", {}).values() for h in u if h.get("form") in FORMAS_ANUALES]
    return max(fechas) if fechas else None


def ultimo_anual_xbrl(sub: dict) -> dict | None:
    """Último informe anual con XBRL según submissions: {accn, fecha, forma}."""
    r = sub.get("filings", {}).get("recent", {})
    for f, d, a, x in zip(r.get("form", []), r.get("filingDate", []), r.get("accessionNumber", []),
                          r.get("isXBRL", [])):
        if f in FORMAS_ANUALES and not f.endswith("/A") and x:
            return {"accn": a, "fecha": d, "forma": f}
    return None


def hechos_desde_dataframe(df: Any, tax: str, accn: str, forma: str, presentado: str) -> dict:
    """Convierte el DataFrame de hechos de edgartools al formato companyfacts (solo hechos sin dimensiones)."""
    import pandas as pd

    res: dict[str, dict] = {}
    pref = tax + ":"
    sub = df[df["concept"].astype(str).str.startswith(pref) & df["numeric_value"].notna()]
    if "is_dimensioned" in sub:
        sub = sub[~sub["is_dimensioned"].fillna(False).astype(bool)]
    for _, f in sub.iterrows():
        unidad = str(f.get("unit_ref") or "")
        if not unidad:
            continue
        unidad = "shares" if unidad.lower() == "shares" else unidad
        h = {"val": float(f["numeric_value"]), "form": forma, "fp": "FY", "filed": presentado, "accn": accn}
        if f.get("period_type") == "duration":
            if pd.isna(f.get("period_start")) or pd.isna(f.get("period_end")):
                continue
            h["start"], h["end"] = str(f["period_start"])[:10], str(f["period_end"])[:10]
        else:
            if pd.isna(f.get("period_instant")):
                continue
            h["end"] = str(f["period_instant"])[:10]
        if float(h["val"]).is_integer():
            h["val"] = int(h["val"])
        concepto = str(f["concept"])[len(pref):]
        lista = res.setdefault(concepto, {"units": {}})["units"].setdefault(unidad, [])
        if h not in lista:
            lista.append(h)
    return {"facts": {tax: res}}


def fusionar_facts(base: dict, extra: dict) -> dict:
    """Añade a `base` los hechos de `extra` (mismo formato companyfacts). No modifica `base`."""
    import copy

    res = copy.deepcopy(base)
    for tax, conceptos in extra.get("facts", {}).items():
        dst = res.setdefault("facts", {}).setdefault(tax, {})
        for c, nodo in conceptos.items():
            for u, hechos in nodo.get("units", {}).items():
                dst.setdefault(c, {"units": {}})["units"].setdefault(u, []).extend(hechos)
    return res


def moneda_informe(fund: dict) -> str | None:
    c = Counter(
        p["moneda"] for v in fund.values() if not comun.es_desconocido(v) for p in v["serie"] if p.get("moneda")
    )
    return c.most_common(1)[0][0] if c else None


ESTADOS_EEUU = set(
    "AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND "
    "OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY PR".split()
)


def pais_de_direccion(direccion: dict) -> str | None:
    """País de una dirección de submissions. Los códigos de estado de EE. UU. → 'United States'."""
    codigo = (direccion or {}).get("stateOrCountry")
    if not codigo:
        return None
    if codigo.upper() in ESTADOS_EEUU:
        return "United States"
    return (direccion.get("stateOrCountryDescription") or codigo).strip()


def resumen_submissions(sub: dict) -> dict:
    recientes = sub.get("filings", {}).get("recent", {})
    formas = recientes.get("form", [])
    fechas = recientes.get("filingDate", [])
    anuales = [(f, d) for f, d in zip(formas, fechas) if f in FORMAS_ANUALES]
    dir_negocio = (sub.get("addresses") or {}).get("business") or {}
    return {
        "nombre": sub.get("name"),
        "sic": int(sub["sic"]) if str(sub.get("sic", "")).isdigit() else None,
        "sic_descripcion": sub.get("sicDescription"),
        "fin_ejercicio": sub.get("fiscalYearEnd"),
        "bolsas": sub.get("exchanges", []),
        "categoria": sub.get("category"),
        "estado_constitucion": sub.get("stateOfIncorporation"),
        "pais_negocio": pais_de_direccion(dir_negocio),
        "forma_anual": anuales[0][0].replace("/A", "") if anuales else None,
        "ultimo_informe_anual": anuales[0][1] if anuales else None,
        "formas_recientes_8k_6k_90d": _recientes(formas, fechas, {"8-K", "6-K"}, 90),
    }


def _recientes(formas: list, fechas: list, tipos: set, dias: int) -> int:
    hoy = date.today()
    return sum(1 for f, d in zip(formas, fechas) if f in tipos and (hoy - date.fromisoformat(d)).days <= dias)


# ---------------------------------------------------------------- acceso a red

class ClienteEdgar:
    def __init__(self, cache: CacheDisco | None = None, user_agent: str | None = None,
                 sesion: Any = None, bucket: TokenBucket | None = None, dormir: Callable[[float], None] | None = None):
        import time

        import requests

        cfg = comun.cargar_config()
        self.cache = cache or CacheDisco()
        self.ua = user_agent or comun.user_agent_sec()
        self.sesion = sesion or requests.Session()
        self.bucket = bucket or TokenBucket(cfg["edgar"]["max_peticiones_seg"])
        self.dormir = dormir or time.sleep

    def _get(self, url: str) -> Any:
        import requests

        def pedir():
            self.bucket.adquirir()
            try:
                r = self.sesion.get(url, headers={"User-Agent": self.ua, "Accept-Encoding": "gzip, deflate"}, timeout=60)
            except requests.RequestException as e:
                raise comun.ErrorDatos(f"EDGAR no responde ({url}): {e}", "source_down") from e
            if r.status_code == 404:
                raise _NoReintentar(comun.ErrorDatos(f"EDGAR 404: {url}", "not_covered"))
            if r.status_code in (403, 429):
                raise comun.ErrorDatos(f"EDGAR limita el acceso ({r.status_code}): {url}", "rate_limited")
            if r.status_code >= 400:
                raise comun.ErrorDatos(f"EDGAR error {r.status_code}: {url}", "source_down")
            return r.json()

        try:
            return con_backoff(pedir, reintentos=3, espera_base=1.0, excepciones=(comun.ErrorDatos,), dormir=self.dormir)
        except _NoReintentar as e:
            raise e.error from None

    def _cacheado(self, fuente: str, url: str) -> tuple[Any, dict]:
        return self.cache.obtener_o_calcular(fuente, url, lambda: self._get(url))

    def mapa_tickers(self) -> dict[str, dict]:
        datos, _ = self._cacheado("tickers", URL_TICKERS)
        return {v["ticker"].upper(): v for v in datos.values()}

    def cik(self, ticker: str) -> tuple[str, str]:
        t = normalizar_ticker(ticker)
        m = self.mapa_tickers()
        if t not in m:
            raise comun.ErrorDatos(f"Ticker {t} no registrado en la SEC", "not_covered")
        return cik10(m[t]["cik_str"]), m[t]["title"]

    def submissions(self, cik: str) -> tuple[dict, dict]:
        return self._cacheado("submissions", URL_SUBMISSIONS.format(cik=cik))

    def companyfacts(self, cik: str) -> tuple[dict, dict]:
        return self._cacheado("companyfacts", URL_FACTS.format(cik=cik))

    def hechos_informe(self, informe: dict, tax: str) -> tuple[dict, dict]:
        """Hechos XBRL de un informe concreto vía edgartools (para cuando companyfacts va retrasado)."""
        def calcular() -> dict:
            import os

            os.environ.setdefault("EDGAR_LOCAL_DATA_DIR", str(comun.dir_datos_plugin() / "edgartools"))
            try:
                et = importar_edgartools()
                et.set_identity(self.ua)
                df = et.find(informe["accn"]).xbrl().facts.to_dataframe()
            except Exception as e:  # edgartools lanza excepciones heterogéneas
                raise comun.ErrorDatos(f"edgartools no pudo leer {informe['accn']}: {e}", "source_down") from e
            return hechos_desde_dataframe(df, tax, informe["accn"], informe["forma"], informe["fecha"])

        return self.cache.obtener_o_calcular("companyfacts", f"xbrl:{informe['accn']}:{tax}", calcular)


def importar_edgartools() -> Any:
    """Importa el paquete `edgar` de edgartools. Este archivo también se llama edgar.py: si su carpeta
    está en sys.path (al ejecutar un script de datos/), taparía al paquete; se excluye durante la importación."""
    import importlib
    import sys as _sys

    propia = Path(__file__).resolve().parent
    previo = _sys.modules.get("edgar")
    if previo is not None and getattr(previo, "__file__", None) and Path(previo.__file__).resolve().parent == propia:
        del _sys.modules["edgar"]
    guardado = list(_sys.path)
    _sys.path[:] = [p for p in _sys.path if Path(p or ".").resolve() != propia]
    try:
        modulo = importlib.import_module("edgar")
    finally:
        _sys.path[:] = guardado
    if not hasattr(modulo, "find"):
        raise ImportError("El módulo 'edgar' importado no es edgartools")
    return modulo


class _NoReintentar(Exception):
    def __init__(self, error: comun.ErrorDatos):
        super().__init__(str(error))
        self.error = error


def obtener(ticker: str, anios: int | None = None, cliente: ClienteEdgar | None = None) -> dict:
    """Descarga y estructura los datos EDGAR de un ticker. Si no está en la SEC, devuelve empresa desconocida."""
    anios = anios or comun.cargar_config()["edgar"]["anios"]
    t = normalizar_ticker(ticker)
    try:
        cliente = cliente or ClienteEdgar()
        cik, titulo = cliente.cik(t)
    except comun.ErrorDatos as e:
        return {"empresa": comun.desconocido(e.causa, str(e)), "fundamentales": {}, "desconocidos":
                [{"campo": "empresa", "causa": e.causa}], "fuentes": []}
    sub, info_s = cliente.submissions(cik)
    resumen = resumen_submissions(sub)
    url_f = URL_FACTS.format(cik=cik)
    fuentes = [{"url": URL_SUBMISSIONS.format(cik=cik), "retrieved_at": _ts(info_s), "origen": info_s["origen"]}]
    desc: list[dict] = []
    tax, fund = None, {}
    try:
        facts, info_f = cliente.companyfacts(cik)
        fuentes.append({"url": url_f, "retrieved_at": _ts(info_f), "origen": info_f.get("origen")})
        tax = detectar_taxonomia(facts)
        # companyfacts puede no incluir aún el último informe anual: se completa con su XBRL.
        informe = ultimo_anual_xbrl(sub)
        ultimo_cf = max_presentado_anual(facts)
        if informe and (ultimo_cf is None or informe["fecha"] > ultimo_cf):
            try:
                extra, info_x = cliente.hechos_informe(informe, tax)
                facts = fusionar_facts(facts, extra)
                fuentes.append({"url": url_informe(cik, informe["accn"]), "retrieved_at": _ts(info_x),
                                "published_at": informe["fecha"], "origen": info_x.get("origen")})
            except comun.ErrorDatos as e:
                desc.append({"campo": "ultimo_informe_anual", "causa": "stale"})
                resumen["aviso"] = f"Último informe anual ({informe['fecha']}) sin procesar: {e}"
        tax, fund, d = extraer_fundamentales(facts, anios, url_f, sic=resumen.get("sic"))
        desc += d
        if informe:
            # Las cifras que proceden del informe leído con edgartools citan ese informe.
            for v in fund.values():
                for p in ([] if comun.es_desconocido(v) else v.get("serie", [])):
                    if p.get("accn") == informe["accn"] and p["fuente_url"] == url_f:
                        p["fuente_url"] = url_informe(cik, informe["accn"])
    except comun.ErrorDatos as e:
        desc.append({"campo": "fundamentales", "causa": e.causa})
    ing = fund.get("ingresos")
    anios_estados = len(ing["serie"]) if ing and not comun.es_desconocido(ing) else 0
    empresa = {
        "ticker": t, "cik": cik, "nombre": titulo, **resumen,
        "taxonomia": tax, "moneda_informe": moneda_informe(fund) if fund else None,
        "anios_estados": anios_estados,
    }
    return {"empresa": empresa, "fundamentales": fund, "desconocidos": desc, "fuentes": fuentes}


def url_informe(cik: str, accn: str) -> str:
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accn.replace('-', '')}/"


def _ts(info: dict) -> str | None:
    from datetime import datetime, timezone

    ts = info.get("ts")
    return datetime.fromtimestamp(ts, timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z") if ts else None


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Fundamentales anuales de SEC EDGAR para un ticker.")
    p.add_argument("ticker")
    p.add_argument("--salida", help="Ruta del JSON de salida (por defecto, stdout)")
    p.add_argument("--anios", type=int)
    a = p.parse_args(argv)
    try:
        res = obtener(a.ticker, a.anios)
    except comun.ErrorDatos as e:
        comun.salir_con_error(f"{e} [causa={e.causa}]")
    if a.salida:
        comun.escribir_json(a.salida, res)
        print(a.salida)
    else:
        print(comun.volcar_json(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())

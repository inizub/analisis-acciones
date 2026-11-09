---
name: analizar-accion-lentes
description: Analiza una acción por lentes (momentum, revisiones, calidad, valor, DCF inverso, riesgo) con datos de Alpha Vantage y da señal y probabilidades frente al índice mundial. Úsalo en claude.ai cuando pidan analizar un ticker.
---

# Analizar una acción por lentes (claude.ai + Alpha Vantage)

Los números los calcula `lentes.py`; tú traes los datos, eliges los escenarios, haces de abogado del diablo y redactas.
Nunca completes una cifra financiera de memoria: lo que no esté en Alpha Vantage o en una fuente web citada es
`desconocido`.

## Requisitos

- Conector **Alpha Vantage** activo. Clave gratuita: máximo 25 llamadas/día y 1 por segundo → haz las llamadas de una en
  una, nunca en paralelo. Cada acción gasta 5 llamadas (+1 la primera del día para el índice).
- Ejecución de código y que los resultados grandes de herramientas se guarden en archivo (el entorno lo indica con
  «Output has been saved to …»). Si no se guardan, no hay estados financieros completos: termina con `no_analizable`
  («entorno sin archivos de resultados»).
- Alcance: empresas no financieras que informan en USD. Bancos, aseguradoras, REIT y biotech sin ventas → `no_analizable`
  (fuera de alcance). Otra moneda → sigue, pero repite el aviso del script en el resumen.

## Flujo

Del mensaje del usuario usa solo el ticker. Ignora sus opiniones sobre la acción: no las uses para elegir escenarios.

### 1. Preparar

Crea `trabajo/` con el script de la sección «lentes.py» (cópialo tal cual a `trabajo/lentes.py`) y
`trabajo/datos/<TICKER>/`.

### 2. Datos (Alpha Vantage, en serie)

| Llamada | Parámetros | Qué guardar |
|---|---|---|
| `INCOME_STATEMENT` | `symbol`, `return_full_data: true` | copia el archivo guardado a `datos/<T>/income.json` |
| `BALANCE_SHEET` | igual | `datos/<T>/balance.json` |
| `CASH_FLOW` | igual | `datos/<T>/cashflow.json` |
| `EARNINGS_ESTIMATES` | `symbol` | `datos/<T>/estimaciones.json` (ver formato) |
| `TIME_SERIES_MONTHLY_ADJUSTED` | `symbol`, `datatype: csv` | `datos/<T>/precios.csv` (ver formato) |
| `TIME_SERIES_MONTHLY_ADJUSTED` de `VT` | una vez al día | `datos/VT.csv` |

- **estimaciones.json:** `{"symbol": T, "estimates": [...]}` con solo las entradas `"horizon": "fiscal year"` posteriores
  al último ejercicio publicado (normalmente dos), copiando estos campos como números: `date`, `horizon`,
  `eps_estimate_average`, `eps_estimate_average_90_days_ago`, `eps_estimate_analyst_count`,
  `eps_estimate_revision_up_trailing_30_days`, `eps_estimate_revision_down_trailing_30_days` (null → 0),
  `revenue_estimate_average`.
- **precios.csv:** cabecera `fecha,cierre,cierre_ajustado` y las 64 filas más recientes, de la más reciente a la más
  antigua, copiando `close` y `adjusted close` sin redondear.
- Si una llamada devuelve error de límite, espera 2 s y repítela una vez. Si devuelve «premium endpoint» o sigue
  fallando, para y dilo: no sustituyas los datos por estimaciones.

Si Alpha Vantage agota el límite diario, usa FMP para las piezas que falten (ver «Respaldo con FMP» abajo).

Busca en la web el rendimiento del bono de EE. UU. a 10 años (FRED, Treasury o similar) y la prima de riesgo implícita
de Damodaran más reciente (pages.stern.nyu.edu/~adamodar). Anota valor, fuente y fecha.

### 3. Lentes (código)

```
python3 trabajo/lentes.py --dir trabajo/datos/<T> --bench trabajo/datos/VT.csv --rf <RF> --erp <ERP> --salida trabajo/datos/<T>/lentes.json
```

Si la salida trae `"senal": "no_analizable"`, ve al paso 7 con el motivo.

### 4. Analista

Lee `lentes.json` y, con búsqueda web solo para contexto cualitativo (últimos resultados, guía, catalizadores; cita
cada fuente), escribe en `trabajo/datos/<T>/analisis.md`:

1. **Negocio** en ≤ 5 frases, cada una ligada a un driver (crecimiento, margen, reinversión, riesgo).
2. **Lectura de cada lente** en una línea: qué dice y si el dato tiene trampas (p. ej. beneficio con plusvalías no
   operativas, capex extraordinario que hunde el FCF, estimaciones del ejercicio en curso infladas por partidas únicas).
3. **DCF inverso:** qué crecimiento descuenta el precio, en qué percentil de la tasa base cae y si te parece exigente,
   razonable o conservador, con el porqué.
4. **Tres escenarios** en `trabajo/datos/<T>/escenarios.json`:
   `{"escenarios": [{"nombre": "bajista", "p": .., "crecimiento_5a": .., "margen_objetivo": .., "roic_terminal": ..}, ...]}`
   - Ancla el base en el consenso (`consenso_ventas_fy1`, ventas_cagr_3a) y en la tasa base, no en el precio.
   - `roic_terminal` solo si documentas una ventaja competitiva con dato; si no, omítelo (= WACC).
   - Probabilidades granulares que sumen 1. El bajista debe ser una pérdida real y plausible.

Vuelve a ejecutar el paso 3 añadiendo `--escenarios trabajo/datos/<T>/escenarios.json`. A partir de aquí no cambies los
escenarios.

### 5. Abogado del diablo

En `analisis.md`, sección nueva y sin editar las anteriores:
- Las 3 objeciones que más moverían el resultado (dato erróneo, supuesto implausible, riesgo omitido), cada una con su
  dato.
- El mejor argumento contrario a la señal.
- Si una objeción demuestra un **error de dato**, corrige el archivo de datos, repite el paso 3 y anótalo. Las
  discrepancias de opinión no cambian los números.

### 6. Criterios de invalidación

Al menos dos, cada uno con dato, umbral y efecto (p. ej. «revisiones del BPA FY1 a 90 días < −5 % → la tesis de
revisiones cae; revisar»).

### 7. Responder

Primero la señal y las probabilidades, después el resto. Máximo una pantalla y media:

```
**<TICKER> · <señal> · p(batir al índice 12 m) = X % (partida Y %) · 36 m = Z % · p(caída ≥30 % en 12 m) = W %**
Exceso anual esperado: ±N pp (momentum a, revisiones b, calidad c, valor d)

| Lente | Puntuación | Dato clave |
(momentum, revisiones, calidad, valor, DCF inverso, riesgo)

Escenarios: bajista V/P · base V/P · alcista V/P → valor esperado V/P
Tensiones: …
Razones (3) · Mejor argumento contrario · Qué me haría cambiar de opinión (criterios)
Datos: Alpha Vantage (fecha), rf y ERP con fuente; avisos del script
```

- Separa [dato], [E] (evidencia empírica) y [O] (opinión o heurística). Los pesos y umbrales del script son [O] sin
  calibrar: dilo una vez.
- Si estás dentro de un Project con su propio formato de recomendación, aplícalo después usando esta salida.

### 8. Diario

Si hay acceso a los documentos del Project, añade una fila a `claude/diario-predicciones.md` (créalo si no existe):
`| fecha | ticker | precio | señal | p12 | partida | p36 | p_caída30 | exceso pp | versión lentes 1 |`
Nunca edites filas anteriores. Si no hay acceso, da la fila al final de la respuesta para que el usuario la guarde.

### Respaldo con FMP (cuando Alpha Vantage no responde por límite)

Conector **FMP**. Con el plan actual el `limit` de los estados no puede pasar de 5 y el ETF VT no está disponible
(«ACCESS DENIED»: no repitas la llamada con el mismo valor). El índice sigue saliendo de `datos/VT.csv` de Alpha Vantage:
refréscalo una vez al mes; si su último mes no coincide con el de la acción, el script se detiene.

| Herramienta y endpoint | Parámetros | Guardar como (en `datos/<T>/`) |
|---|---|---|
| `statements` · `income-statement` | `symbol`, `period` annual / quarter, `limit` 5 | `fmp_income_a.json` / `fmp_income_q.json` |
| `statements` · `balance-sheet-statement` | igual | `fmp_balance_a.json` / `fmp_balance_q.json` |
| `statements` · `cashflow-statement` | igual | `fmp_cash_a.json` / `fmp_cash_q.json` |
| `analyst` · `financial-estimates` | `symbol`, `period` annual, `limit` 3 | `fmp_estimaciones.json` |
| `chart` · `historical-price-eod-light` | `symbol`, `from_date` (hace 5 años), `to_date` (hoy) | `fmp_precio_light.json` |
| `chart` · `historical-price-eod-dividend-adjusted` | igual | `fmp_precio_adj.json` |

- Guarda cada respuesta completa tal cual: si el resultado se guardó en archivo, cópialo; si llegó dentro del chat,
  escribe el JSON entero sin omitir, redondear ni reordenar nada. Un número copiado mal falsea la señal.
- `lentes.py` convierte solo lo que falta, así que se puede mezclar (p. ej. precios de FMP y estados de Alpha Vantage).
- Qué se pierde con FMP: el historial de revisiones del consenso (la lente queda vacía, sin peso, y la señal se acerca a
  neutral; dilo en la respuesta), el crecimiento interanual de ventas TTM (solo hay 5 trimestres) y las acciones del
  balance (se usan las diluidas medias del trimestre [O]).

## Qué significa cada lente

| Lente | Mide | Por qué cuenta |
|---|---|---|
| Momentum | Rentabilidad relativa al índice 12-1 y 6-1 meses (sin el último mes) | [E] prima documentada en acciones, con caídas bruscas ocasionales |
| Revisiones | Cambio del BPA de consenso a 90 días y saldo de revisiones a 30 días | [E] las sorpresas y revisiones tienden a continuar |
| Calidad | ROIC, beneficio bruto/activos, FCF/beneficio | [E] prima de rentabilidad (Novy-Marx) |
| Valor | EBIT/EV, rentabilidad FCF, EV/EBIT frente a su historia, escenarios | [E] prima débil en la última década, mejor combinada |
| DCF inverso | Crecimiento que descuenta el precio frente a la tasa base | Informa; no veta |
| Riesgo | Volatilidad, beta, caída máxima, deuda | Escala las probabilidades |

Señal: `atractiva` si el exceso esperado ≥ +3 pp, `no_atractiva` si ≤ −3 pp, si no `neutral`. Simétrica a propósito.

## lentes.py

```python
"""Lentes de análisis de una acción a partir de datos de Alpha Vantage. Solo biblioteca estándar.

Uso:
  python lentes.py --dir DATOS/TICKER --bench DATOS/VT.csv --rf 0.0486 --erp 0.0441 [--escenarios esc.json] [--salida out.json]

DATOS/TICKER contiene: income.json, balance.json, cashflow.json (respuestas completas de Alpha Vantage),
estimaciones.json (ejercicios fiscales de EARNINGS_ESTIMATES) y precios.csv (fecha,cierre,cierre_ajustado; mensual,
más reciente primero, ≥ 40 filas). VT.csv igual para el índice de referencia.

Respaldo con FMP (si se acaban las llamadas de Alpha Vantage): guarda las respuestas de FMP como fmp_income_a.json,
fmp_income_q.json, fmp_balance_a.json, fmp_balance_q.json, fmp_cash_a.json, fmp_cash_q.json, fmp_estimaciones.json,
fmp_precio_light.json y fmp_precio_adj.json en DATOS/TICKER; el script los convierte solo a los archivos de arriba
cuando faltan. FMP no trae historial de revisiones (esa lente queda vacía) y el plan gratuito limita los estados a 5 periodos.

Todos los umbrales y pesos de PARAM son heurísticos [O] hasta calibrarlos con el diario.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics as st
from pathlib import Path

PARAM = {
    # puntuación de cada lente en [-1, 1]: (valor - centro) / escala, recortado
    "momentum": {"rel_12_1": (0.0, 0.30), "rel_6_1": (0.0, 0.20)},
    "revisiones": {"cambio_bpa_90d": (0.0, 0.08), "amplitud_30d": (0.0, 0.30)},
    "calidad": {"roic": (0.10, 0.15), "gp_activos": (0.25, 0.20), "conversion_fcf": (0.80, 0.40)},
    "valor": {"ebit_ev": (0.05, 0.04), "fcf_yield": (0.04, 0.03), "vs_historia": (0.0, 0.40), "escenarios": (0.0, 0.69),
              "max_cagr_historia": 0.25},
    # exceso anual esperado frente al índice por unidad de puntuación (prima histórica recortada a la mitad)
    "prima": {"momentum": 0.025, "revisiones": 0.025, "calidad": 0.015, "valor": 0.020},
    "senal": {"mu_atractiva": 0.03, "mu_no_atractiva": -0.03, "concentracion_max": 0.6},
    # colas gruesas: la caída ≥ 30 % se calcula con la volatilidad inflada y un suelo
    "colas": {"factor_vol": 1.15, "suelo_p_caida": 0.03},
    "dcf": {"anios": 10, "anios_altos": 5, "g_terminal_max": 0.03, "beta_rango": (0.6, 2.0)},
    # tasas base de crecimiento de ventas a 5 años (Mauboussin y Callahan 2026 / EDGAR 2009-2025, assets/base_rates.csv)
    "base_crec_5a": [(500, 0.0917, 0.1711), (2000, 0.0606, 0.1183), (5000, 0.0473, 0.0952),
                     (10000, 0.0455, 0.0907), (50000, 0.0301, 0.0831), (1e18, 0.0367, 0.0771)],
}


def f(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def clip(x, lo=-1.0, hi=1.0):
    return max(lo, min(hi, x))


def puntuar(valor, centro_escala):
    if valor is None:
        return None
    c, e = centro_escala
    return clip((valor - c) / e)


def media(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def phi(x):
    return 0.5 * math.erfc(-x / math.sqrt(2))


# ------------------------------------------------------------------ lectura
def leer_av(p: Path):
    d = json.loads(p.read_text(encoding="utf-8"))
    if "annualReports" not in d:
        raise SystemExit(f"{p.name}: no es una respuesta completa de Alpha Vantage ({list(d)[:3]})")
    return d["annualReports"], d["quarterlyReports"]


def leer_precios(p: Path):
    filas = list(csv.DictReader(p.open(encoding="utf-8")))
    out = [(r["fecha"], float(r["cierre"]), float(r["cierre_ajustado"])) for r in filas]
    fechas = [r[0] for r in out]
    if fechas != sorted(fechas, reverse=True):
        raise SystemExit(f"{p.name}: las fechas deben ir de la más reciente a la más antigua")
    return out


def avisos_precios(nombre, pr):
    av = []
    for (d1, _, a1), (d2, _, a2) in zip(pr, pr[1:]):
        if a1 == a2:
            av.append(f"{nombre}: cierre ajustado idéntico en {d1} y {d2} (posible error del proveedor)")
    return av


def cierre_sin_splits(pr):
    """Cierre ajustado solo por splits: detecta saltos del cociente cierre/ajustado (> 1,5×) y los deshace."""
    out, factor = [], 1.0
    prev = None
    for fecha, c, a in pr:  # de reciente a antiguo
        r = c / a
        if prev is not None and r / prev > 1.5:
            factor *= round(r / prev)
        prev = r
        out.append((fecha, c / factor))
    return out


# ------------------------------------------------------------------ adaptador FMP
def leer_json_fmp(p: Path):
    """Lee una respuesta de FMP: lista JSON o el envoltorio [{"type":"text","text":"..."}] que guarda Claude."""
    d = json.loads(p.read_text(encoding="utf-8"))
    if isinstance(d, list) and d and isinstance(d[0], dict) and d[0].get("type") == "text" and "text" in d[0]:
        d = json.loads(d[0]["text"])
    if not isinstance(d, list) or not d:
        raise SystemExit(f"{p.name}: respuesta de FMP vacía o no válida: {str(d)[:80]}")
    return d


def _s(x):
    return None if x is None else str(x)


def income_fmp(filas):
    return [{"fiscalDateEnding": r["date"], "reportedCurrency": r.get("reportedCurrency"),
             "totalRevenue": _s(r.get("revenue")), "grossProfit": _s(r.get("grossProfit")),
             "operatingIncome": _s(r.get("operatingIncome")), "netIncome": _s(r.get("netIncome")),
             "incomeTaxExpense": _s(r.get("incomeTaxExpense")), "incomeBeforeTax": _s(r.get("incomeBeforeTax")),
             "interestExpense": _s(r.get("interestExpense")),
             "depreciationAndAmortization": _s(r.get("depreciationAndAmortization"))} for r in filas]


def balance_fmp(filas, income_filas):
    """FMP no trae acciones en el balance: se toman las diluidas medias del resultado de la misma fecha [O]."""
    acc = {r["date"]: r.get("weightedAverageShsOutDil") for r in income_filas}
    return [{"fiscalDateEnding": r["date"], "totalAssets": _s(r.get("totalAssets")),
             "totalShareholderEquity": _s(r.get("totalStockholdersEquity")),
             "cashAndCashEquivalentsAtCarryingValue": _s(r.get("cashAndCashEquivalents")),
             "cashAndShortTermInvestments": _s(r.get("cashAndShortTermInvestments")),
             "shortTermInvestments": _s(r.get("shortTermInvestments")),
             "shortLongTermDebtTotal": _s(r.get("totalDebt")),
             "longTermDebt": _s(r.get("longTermDebt")), "shortTermDebt": _s(r.get("shortTermDebt")),
             "commonStockSharesOutstanding": _s(acc.get(r["date"]))} for r in filas]


def cash_fmp(filas):
    out = []
    for r in filas:
        capex = f(r.get("capitalExpenditure"))
        fco = r.get("netCashProvidedByOperatingActivities", r.get("operatingCashFlow"))
        out.append({"fiscalDateEnding": r["date"], "operatingCashflow": _s(fco),
                    "capitalExpenditures": None if capex is None else str(abs(capex)),
                    "stockBasedCompensation": _s(r.get("stockBasedCompensation"))})
    return out


def estimaciones_fmp(filas, simbolo):
    return {"symbol": simbolo, "fuente": "FMP", "estimates": [
        {"horizon": "fiscal year", "date": r["date"], "eps_estimate_average": r.get("epsAvg"),
         "revenue_estimate_average": r.get("revenueAvg"), "eps_estimate_analyst_count": r.get("numAnalystsEps")}
        for r in filas]}


def precios_fmp(light, adj):
    """Diarios de FMP -> último día hábil de cada mes (el mes en curso, su última sesión). Reciente primero."""
    aj = {r["date"]: r["adjClose"] for r in adj}
    mes = {}
    for r in light:
        d = r["date"]
        if d in aj and (d[:7] not in mes or d > mes[d[:7]][0]):
            mes[d[:7]] = (d, float(r["price"]), float(aj[d]))
    return sorted(mes.values(), reverse=True)


def preparar_fmp(dir_: Path):
    """Convierte los fmp_*.json de `dir_` a los archivos que lee analizar(), solo donde falta el de Alpha Vantage."""
    hecho = []
    ruta = lambda n: dir_ / n
    inc_a = leer_json_fmp(ruta("fmp_income_a.json")) if ruta("fmp_income_a.json").exists() else None
    inc_q = leer_json_fmp(ruta("fmp_income_q.json")) if ruta("fmp_income_q.json").exists() else None
    for nom, ia_, iq_, fa, fq, fun in [
            ("income.json", None, None, "fmp_income_a.json", "fmp_income_q.json", lambda x, _: income_fmp(x)),
            ("balance.json", inc_a, inc_q, "fmp_balance_a.json", "fmp_balance_q.json", None),
            ("cashflow.json", None, None, "fmp_cash_a.json", "fmp_cash_q.json", lambda x, _: cash_fmp(x))]:
        if ruta(nom).exists() or not (ruta(fa).exists() and ruta(fq).exists()):
            continue
        A, Q = leer_json_fmp(ruta(fa)), leer_json_fmp(ruta(fq))
        if nom == "balance.json":
            if inc_a is None or inc_q is None:
                raise SystemExit("para convertir el balance de FMP hacen falta también fmp_income_a.json y fmp_income_q.json")
            A, Q = balance_fmp(A, inc_a), balance_fmp(Q, inc_q)
        else:
            A, Q = fun(A, None), fun(Q, None)
        ruta(nom).write_text(json.dumps({"annualReports": A, "quarterlyReports": Q}), encoding="utf-8")
        hecho.append(nom)
    if not ruta("estimaciones.json").exists() and ruta("fmp_estimaciones.json").exists():
        sim = (leer_json_fmp(ruta("fmp_estimaciones.json"))[0].get("symbol"))
        ruta("estimaciones.json").write_text(json.dumps(estimaciones_fmp(leer_json_fmp(ruta("fmp_estimaciones.json")), sim)),
                                             encoding="utf-8")
        hecho.append("estimaciones.json")
    if not ruta("precios.csv").exists() and ruta("fmp_precio_light.json").exists() and ruta("fmp_precio_adj.json").exists():
        filas = precios_fmp(leer_json_fmp(ruta("fmp_precio_light.json")), leer_json_fmp(ruta("fmp_precio_adj.json")))
        with ruta("precios.csv").open("w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh); w.writerow(["fecha", "cierre", "cierre_ajustado"]); w.writerows(filas)
        hecho.append("precios.csv")
    return hecho


# ------------------------------------------------------------------ cálculos
def ttm(q, campo, desde=0):
    vals = [f(r.get(campo)) for r in q[desde:desde + 4]]
    return sum(vals) if len(vals) == 4 and all(v is not None for v in vals) else None


def caja_total(b):
    ce = f(b.get("cashAndCashEquivalentsAtCarryingValue")) or 0
    cst = f(b.get("cashAndShortTermInvestments")) or 0
    sti = f(b.get("shortTermInvestments")) or 0
    return max(cst, ce + sti) if abs(cst - ce) < 1 else cst


def deuda_total(b):
    d = f(b.get("shortLongTermDebtTotal"))
    if d is None:
        d = (f(b.get("longTermDebt")) or 0) + (f(b.get("shortTermDebt")) or 0)
    return d


def rent_log_mensual(pr):
    a = [x[2] for x in pr]
    return [math.log(a[i] / a[i + 1]) for i in range(len(a) - 1)]


def retorno(pr, ini, fin):
    """Rentabilidad total entre `fin` meses atrás y `ini` meses atrás (índices de fila, 0 = hoy)."""
    return pr[ini][2] / pr[fin][2] - 1


def dcf(ingresos0, g, margen0, margen_obj, vc, t, wacc, g_term, roic_term, deuda, caja, acciones, anios=10, altos=5):
    if wacc <= g_term:
        return None
    ing, valor, m = ingresos0, 0.0, margen0
    for k in range(1, anios + 1):
        gk = g if k <= altos else g + (g_term - g) * (k - altos) / (anios - altos)
        nuevo = ing * (1 + gk)
        m = margen0 + (margen_obj - margen0) * min(k, altos) / altos
        fcff = nuevo * m * (1 - t) - (nuevo - ing) / vc
        valor += fcff / (1 + wacc) ** k
        ing = nuevo
    nopat_t = ing * (1 + g_term) * margen_obj * (1 - t)
    vt = nopat_t * (1 - g_term / roic_term) / (wacc - g_term)
    valor += vt / (1 + wacc) ** anios
    return (valor - deuda + caja) / acciones


def biseccion(fun, lo, hi, it=80):
    flo, fhi = fun(lo), fun(hi)
    if flo is None or fhi is None:
        return None, "sin_valor"
    if flo > 0:
        return None, "barato"   # ni con el valor más bajo del rango baja hasta el precio
    if fhi < 0:
        return None, "caro"     # ni con el valor más alto alcanza el precio
    for _ in range(it):
        mid = (lo + hi) / 2
        if fun(mid) < 0:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2, "ok"


def analizar(dir_: Path, bench: Path, rf: float, erp: float, escenarios: dict | None):
    ia, iq = leer_av(dir_ / "income.json")
    ba, bq = leer_av(dir_ / "balance.json")
    ca, cq = leer_av(dir_ / "cashflow.json")
    est = json.loads((dir_ / "estimaciones.json").read_text(encoding="utf-8"))
    pr = leer_precios(dir_ / "precios.csv")
    pv = leer_precios(bench)
    avisos = avisos_precios("acción", pr) + avisos_precios("índice", pv)
    if pr[0][0][:7] != pv[0][0][:7]:
        raise SystemExit(f"el índice ({pv[0][0]}) y la acción ({pr[0][0]}) deben terminar en el mismo mes: "
                         "las rentabilidades se alinean por fila. Actualiza el archivo del índice.")
    faltan = []

    if iq[0]["fiscalDateEnding"] != bq[0]["fiscalDateEnding"] or iq[0]["fiscalDateEnding"] != cq[0]["fiscalDateEnding"]:
        avisos.append("los últimos trimestres de resultados, balance y flujos no coinciden")
    moneda = iq[0].get("reportedCurrency")
    if moneda != "USD":
        avisos.append(f"moneda de los estados: {moneda}; precios en USD: revisa la conversión antes de fiarte de los múltiplos")

    # --- base TTM
    ventas = ttm(iq, "totalRevenue"); ventas_ant = ttm(iq, "totalRevenue", 4)
    bruto = ttm(iq, "grossProfit"); ebit = ttm(iq, "operatingIncome"); bn = ttm(iq, "netIncome")
    imp = ttm(iq, "incomeTaxExpense"); bai = ttm(iq, "incomeBeforeTax"); intereses = ttm(iq, "interestExpense")
    da = ttm(iq, "depreciationAndAmortization")
    fco = ttm(cq, "operatingCashflow"); capex = ttm(cq, "capitalExpenditures"); sbc = ttm(cq, "stockBasedCompensation")
    b0 = bq[0]
    activos = f(b0.get("totalAssets")); patrimonio = f(b0.get("totalShareholderEquity"))
    deuda = deuda_total(b0); caja = caja_total(b0); acciones = f(b0.get("commonStockSharesOutstanding"))
    acciones_1a = f(bq[4].get("commonStockSharesOutstanding")) if len(bq) > 4 else None
    for n, v in [("ventas_ttm", ventas), ("ebit_ttm", ebit), ("beneficio_neto_ttm", bn), ("fco_ttm", fco),
                 ("capex_ttm", capex), ("activos", activos), ("patrimonio", patrimonio), ("acciones", acciones)]:
        if v is None:
            faltan.append(n)
    if faltan:
        return {"senal": "no_analizable", "motivo": "faltan campos críticos: " + ", ".join(faltan), "avisos": avisos}

    precio = pr[0][1]
    capitalizacion = precio * acciones
    ev = capitalizacion + deuda - caja
    t = clip((imp / bai) if (imp is not None and bai and bai > 0) else 0.21, 0.10, 0.30)
    fcf = fco - abs(capex)
    capital_invertido = patrimonio + deuda - caja
    margen_op = ebit / ventas

    # --- riesgo y beta (36 meses)
    ra, rv = rent_log_mensual(pr)[:36], rent_log_mensual(pv)[:36]
    n = min(len(ra), len(rv))
    ra, rv = ra[:n], rv[:n]
    vol = st.stdev(ra) * math.sqrt(12)
    rel = [x - y for x, y in zip(ra, rv)]
    vol_rel = st.stdev(rel) * math.sqrt(12)
    beta_bruta = st.covariance(ra, rv) / st.variance(rv)
    beta = clip(0.67 * beta_bruta + 0.33, *PARAM["dcf"]["beta_rango"])
    nivel = [x[2] for x in pr[:37]][::-1]
    pico, mdd = nivel[0], 0.0
    for x in nivel:
        pico = max(pico, x); mdd = min(mdd, x / pico - 1)

    # --- lentes
    L = {}
    m12 = retorno(pr, 1, 13) - retorno(pv, 1, 13)
    m6 = retorno(pr, 1, 7) - retorno(pv, 1, 7)
    m1 = retorno(pr, 0, 1) - retorno(pv, 0, 1)
    s_mom = media([puntuar(m12, PARAM["momentum"]["rel_12_1"]), puntuar(m6, PARAM["momentum"]["rel_6_1"])])
    L["momentum"] = {"puntuacion": s_mom, "rel_12_1": m12, "rel_6_1": m6, "rel_ultimo_mes": m1,
                     "nota": "el último mes se excluye (reversión a corto plazo)"}

    fy = sorted([e for e in est.get("estimates", []) if e.get("horizon") == "fiscal year"], key=lambda e: e["date"])
    ultimo_fy = ia[0]["fiscalDateEnding"]
    fy = [e for e in fy if e["date"] > ultimo_fy][:2]
    cambios, amplitudes = [], []
    for e in fy:
        a, a90 = f(e.get("eps_estimate_average")), f(e.get("eps_estimate_average_90_days_ago"))
        if a is not None and a90 and abs(a90) > 1e-9:
            cambios.append((a - a90) / abs(a90))
        nan = f(e.get("eps_estimate_analyst_count"))
        up, dn = f(e.get("eps_estimate_revision_up_trailing_30_days")) or 0, f(e.get("eps_estimate_revision_down_trailing_30_days")) or 0
        if nan:
            amplitudes.append((up - dn) / nan)
    c_rev, a_rev = media(cambios), media(amplitudes)
    L["revisiones"] = {"puntuacion": media([puntuar(c_rev, PARAM["revisiones"]["cambio_bpa_90d"]),
                                            puntuar(a_rev, PARAM["revisiones"]["amplitud_30d"])]),
                       "cambio_bpa_90d": c_rev, "amplitud_30d": a_rev, "ejercicios": [e["date"] for e in fy]}
    if not fy:
        avisos.append("sin estimaciones de ejercicios futuros: lente de revisiones vacía")
    elif c_rev is None and a_rev is None:
        avisos.append("sin historial de revisiones (FMP solo da el consenso actual): lente de revisiones vacía y sin peso; "
                      "la señal queda más cerca de neutral porque no se reparte su peso entre las demás")

    roic = ebit * (1 - t) / capital_invertido if capital_invertido > 0 else None
    gpa = bruto / activos if bruto is not None else None
    conv = fcf / bn if bn > 0 else None
    margenes = [f(r["operatingIncome"]) / f(r["totalRevenue"]) for r in ia[:5]
                if f(r.get("operatingIncome")) is not None and f(r.get("totalRevenue"))]
    L["calidad"] = {"puntuacion": media([puntuar(roic, PARAM["calidad"]["roic"]), puntuar(gpa, PARAM["calidad"]["gp_activos"]),
                                         puntuar(conv, PARAM["calidad"]["conversion_fcf"])]),
                    "roic": roic, "gp_activos": gpa, "conversion_fcf": conv, "margen_operativo": margen_op,
                    "desv_margen_5a": st.pstdev(margenes) if len(margenes) >= 3 else None,
                    "sbc_ventas": sbc / ventas if sbc is not None else None,
                    "dilucion_1a": acciones / acciones_1a - 1 if acciones_1a else None}

    # valoración frente a su propia historia (EV/EBIT al cierre de cada ejercicio)
    ss = dict(cierre_sin_splits(pr))
    hist = []
    for r_i, r_b in zip(ia[1:6], ba[1:6]):
        fe = r_i["fiscalDateEnding"][:7]
        p_fe = next((v for k, v in ss.items() if k[:7] == fe), None)
        eb, sh = f(r_i.get("operatingIncome")), f(r_b.get("commonStockSharesOutstanding"))
        if p_fe and eb and eb > 0 and sh:
            if not 0.5 < sh / acciones < 2:
                avisos.append(f"acciones de {fe} no comparables con las actuales (¿split sin ajustar?): historia omitida")
                continue
            hist.append((p_fe * sh + deuda_total(r_b) - caja_total(r_b)) / eb)
    ev_ebit = ev / ebit if ebit > 0 else None
    vs_hist = math.log(st.median(hist) / ev_ebit) if (hist and ev_ebit) else None
    cagr3 = (f(ia[0]["totalRevenue"]) / f(ia[3]["totalRevenue"])) ** (1 / 3) - 1 if len(ia) > 3 else None
    if vs_hist is not None and cagr3 is not None and cagr3 > PARAM["valor"]["max_cagr_historia"]:
        avisos.append(f"ventas creciendo {cagr3:.0%} anual: el EV/EBIT histórico no es comparable; se omite de la lente de valor")
        vs_hist = None
    componentes_valor = [puntuar(ebit / ev if ev > 0 else None, PARAM["valor"]["ebit_ev"]),
                         puntuar(fcf / capitalizacion, PARAM["valor"]["fcf_yield"]),
                         puntuar(vs_hist, PARAM["valor"]["vs_historia"])]
    eps_fy1 = f(fy[0]["eps_estimate_average"]) if fy else None
    L["valor"] = {"ev_ebit": ev_ebit, "ev_ebit_mediana_5a": st.median(hist) if hist else None, "fcf_yield": fcf / capitalizacion,
                  "per_adelantado": precio / eps_fy1 if eps_fy1 and eps_fy1 > 0 else None}

    # --- WACC y DCF inverso
    d_e = deuda / capitalizacion
    ke = rf + beta * erp
    kd = rf + 0.015
    wacc = (ke + d_e * kd * (1 - t)) / (1 + d_e)
    g_term = min(rf, PARAM["dcf"]["g_terminal_max"])
    vc_hist = None
    if len(ba) > 3:
        ci3 = f(ba[3]["totalShareholderEquity"]) + deuda_total(ba[3]) - caja_total(ba[3])
        dv = ventas - f(ia[3]["totalRevenue"])
        if capital_invertido - ci3 > 0 and dv > 0:
            vc_hist = dv / (capital_invertido - ci3)
    vc = clip(vc_hist or 1.5, 0.5, 5.0)
    base = dict(ingresos0=ventas, margen0=margen_op, margen_obj=margen_op, vc=vc, t=t, wacc=wacc, g_term=g_term,
                roic_term=max(wacc, roic or wacc), deuda=deuda, caja=caja, acciones=acciones)
    g_impl, sentido = biseccion(lambda g: dcf(g=g, **base) - precio, -0.20, 0.80)
    clase = next(c for c in PARAM["base_crec_5a"] if ventas / 1e6 < c[0])
    z = (g_impl - clase[1]) / clase[2] if g_impl is not None else None
    L["dcf_inverso"] = {"crecimiento_implicito_5a": g_impl, "sentido": sentido, "z_frente_tasa_base": z,
                        "percentil_aprox": phi(z) if z is not None else None,
                        "supuestos": {"margen": margen_op, "ventas_capital": vc, "wacc": wacc, "beta": beta,
                                      "roic_terminal": base["roic_term"], "g_terminal": g_term},
                        "nota": "informa; no veta. Supone el margen actual y ROIC terminal = max(WACC, ROIC actual)"}

    # --- escenarios del analista (opcional)
    esc_out = None
    if escenarios:
        esc_out, ev_esc = [], 0.0
        for e in escenarios["escenarios"]:
            v = dcf(ingresos0=ventas, g=e["crecimiento_5a"], margen0=margen_op, margen_obj=e["margen_objetivo"], vc=vc, t=t,
                    wacc=wacc, g_term=g_term, roic_term=e.get("roic_terminal", wacc), deuda=deuda, caja=caja, acciones=acciones)
            v = max(v, 0.02 * precio)
            esc_out.append({**e, "valor": v, "valor_sobre_precio": v / precio})
            ev_esc += e["p"] * v
        if abs(sum(e["p"] for e in escenarios["escenarios"]) - 1) > 1e-6:
            raise SystemExit("las probabilidades de los escenarios deben sumar 1")
        componentes_valor.append(puntuar(math.log(ev_esc / precio), PARAM["valor"]["escenarios"]))
        L["escenarios"] = {"detalle": esc_out, "valor_esperado": ev_esc, "valor_esperado_sobre_precio": ev_esc / precio,
                           "perdida_bajista": max(0.0, 1 - min(x["valor_sobre_precio"] for x in esc_out))}
    L["valor"]["puntuacion"] = media(componentes_valor)

    L["crecimiento"] = {"ventas_ttm_interanual": ventas / ventas_ant - 1 if ventas_ant else None,
                        "ventas_cagr_3a": cagr3,
                        "consenso_ventas_fy1": (f(fy[0]["revenue_estimate_average"]) / f(ia[0]["totalRevenue"]) - 1) if fy and fy[0].get("revenue_estimate_average") else None,
                        "nota": "informativa: el crecimiento por sí solo no tiene prima documentada; cuenta a través del DCF"}
    L["riesgo"] = {"vol_anual": vol, "vol_relativa": vol_rel, "beta": beta, "beta_bruta": beta_bruta, "max_caida_3a": mdd,
                   "deuda_neta_ebitda": (deuda - caja) / (ebit + (da or 0)) if ebit + (da or 0) > 0 else None,
                   "cobertura_intereses": ebit / intereses if intereses and intereses > 0 else None}

    # --- agregación
    mu, contrib = 0.0, {}
    for k, w in PARAM["prima"].items():
        s = L[k]["puntuacion"]
        contrib[k] = (s or 0) * w
        mu += contrib[k]
    r_ind = rf + erp
    p12 = phi((mu - vol_rel ** 2 / 2) / vol_rel)
    p36 = phi((3 * mu - 3 * vol_rel ** 2 / 2) / (vol_rel * math.sqrt(3)))
    p_partida = phi((-vol_rel ** 2 / 2) / vol_rel)
    vt = vol * PARAM["colas"]["factor_vol"]
    m = math.log(1 + r_ind + mu) - vt ** 2 / 2
    b = math.log(0.70)
    p_caida = max(PARAM["colas"]["suelo_p_caida"], phi((b - m) / vt) + math.exp(2 * m * b / vt ** 2) * phi((b + m) / vt))
    if mu >= PARAM["senal"]["mu_atractiva"]:
        senal = "atractiva"
    elif mu <= PARAM["senal"]["mu_no_atractiva"]:
        senal = "no_atractiva"
    else:
        senal = "neutral"
    tensiones = []
    s = {k: L[k]["puntuacion"] for k in PARAM["prima"]}
    if (s["momentum"] or 0) > 0.3 and (s["valor"] or 0) < -0.3:
        tensiones.append("impulso fuerte con valoración exigente: el mercado ya paga la tesis")
    if (s["valor"] or 0) > 0.3 and (s["momentum"] or 0) < -0.3:
        tensiones.append("barata pero con impulso negativo: posible trampa de valor")
    if (s["revisiones"] or 0) < -0.3 and (s["momentum"] or 0) > 0.3:
        tensiones.append("el precio sube mientras el consenso recorta estimaciones")
    total = sum(abs(v) for v in contrib.values())
    dominante = max(contrib, key=lambda k: abs(contrib[k]))
    if total > 0 and abs(contrib[dominante]) / total > PARAM["senal"]["concentracion_max"]:
        tensiones.append(f"la señal depende sobre todo de {dominante} ({abs(contrib[dominante]) / total:.0%} del total)")
    if (s["calidad"] or 0) > 0.5 and (s["valor"] or 0) < -0.3:
        tensiones.append("calidad alta a precio alto: el riesgo es de múltiplo, no de negocio")

    return {
        "ticker": est.get("symbol"), "fecha_precio": pr[0][0], "precio": precio, "moneda_estados": moneda,
        "ultimo_trimestre": iq[0]["fiscalDateEnding"], "capitalizacion": capitalizacion, "ev": ev,
        "senal": senal, "exceso_anual_esperado": mu, "contribuciones": contrib,
        "p_batir_indice_12m": p12, "p_partida_12m": p_partida, "p_batir_indice_36m": p36, "p_caida_30_12m": p_caida,
        "lentes": L, "tensiones": tensiones, "avisos": avisos,
        "parametros": {"rf": rf, "erp": erp, "rentabilidad_indice": r_ind, "pesos": PARAM["prima"],
                       "calibrado": False},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True); ap.add_argument("--bench", required=True)
    ap.add_argument("--rf", type=float, required=True); ap.add_argument("--erp", type=float, required=True)
    ap.add_argument("--escenarios"); ap.add_argument("--salida")
    a = ap.parse_args()
    convertidos = preparar_fmp(Path(a.dir))
    esc = json.loads(Path(a.escenarios).read_text(encoding="utf-8")) if a.escenarios else None
    res = analizar(Path(a.dir), Path(a.bench), a.rf, a.erp, esc)
    if convertidos:
        res.setdefault("avisos", []).append("convertido desde FMP: " + ", ".join(convertidos))
    txt = json.dumps(res, ensure_ascii=False, indent=2, default=lambda x: None)
    if a.salida:
        Path(a.salida).write_text(txt, encoding="utf-8")
    print(txt)


if __name__ == "__main__":
    main()
```

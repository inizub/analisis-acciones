# 0011. Correcciones de datos: sector de Coca-Cola, deuda de Nucor, codificación y forense

**Estado:** aplicadas (v0.2.0 a v0.3.0). **Commits:** `d8ba3e0`, `0637a5b` y el de la v0.3.0 (forense).

Son arreglos pequeños, cada uno con una causa concreta descubierta probando acciones reales.

## Sector de Coca-Cola (SIC 2080)
Coca-Cola declara en EDGAR el SIC 2080 ("Beverages", genérico). La tabla `sic_rutas.csv` lo mandaba a "bebidas alcohólicas"
(rango 2080-2085), con lo que la beta y los márgenes de referencia eran de otra industria. Ahora 2080 → *Beverage (Soft)*
y 2081-2085 → *Beverage (Alcoholic)*. Los tests comprueban 2080, 2086, 2082 y 2085.

## Deuda total de Nucor
Nucor dejó de usar `LongTermDebt` (2016) y `LongTermDebtNoncurrent` (2018); hoy reporta la deuda con
`LongTermDebtAndCapitalLeaseObligations`. Se añadió como candidato compuesto (con deuda corriente y papel comercial).

## Codificación del archivo del agente de datos
En Windows el agente escribió `datos_agente.json` en cp1252 y el plugin falló al leerlo. `comun.leer_json` ahora
acepta cp1252 y reescribe el archivo en UTF-8, y `agents/datos.md` pide UTF-8.

## Bandera forense informativa
La regla del SPEC marca "grave" el inventario (y las cuentas a cobrar) solo si el diferencial con los ingresos supera
10 pp **dos años seguidos**. Con NVDA el último año fue +47 pp y el anterior −23 pp: nada se marcó y el forense llegó a
afirmar que el inventario no crecía por encima de los ingresos. Se mantiene la regla grave, pero si el último año
supera el umbral sin ser grave se añade una bandera **informativa** ("el último año supera el umbral, aún no dos
seguidos"). El resumen cuenta aparte graves e informativas.

## Dónde está
`assets/sic_rutas.csv`, `scripts/datos/edgar.py`, `scripts/comun.py`, `agents/datos.md`, `scripts/forense.py`, sus tests.

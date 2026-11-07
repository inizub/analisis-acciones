# Backtest del caso mecánico (7-nov-2026)

Script: `skills/analizando-acciones/scripts/backtest.py` (datos en `backtest-resultados.json`).

## Qué mide y qué no
Para 50 acciones estadounidenses y 9 fechas (31-dic de 2016 a 2024) reconstruye los fundamentales **tal como estaban
presentados en la SEC ese día**, calcula el valor del DCF mecánico (mismo `dcf_fcff`, crecimiento y margen encogidos hacia
la media, beta propia con Blume) y mira si el cociente valor/precio anticipó el rendimiento relativo al S&P 500 (SPY) a 12
meses y a 3 años. Salieron 380 observaciones (GOOGL no se pudo reconstruir: sin ingresos, beneficio operativo o acciones
con fuente a esas fechas).

**No mide el plugin entero:** no hay analistas (su juicio no se puede reconstruir sin ver el futuro), ni Damodaran por
sector, ni TTM; las tasas base y la ERP (4,5 %) son fijas.

## Resultados
| | n | Correlación de rangos (ln V/P vs rendimiento relativo) |
|---|---|---|
| A 12 meses | 380 | 0,006 |
| A 3 años (anualizado) | 290 | 0,077 |

- Los quintiles de V/P **no son monótonos**: el quintil más barato y el más caro rinden por encima en media (efecto de
  unos pocos valores extremos) y por debajo en mediana. Por años la correlación oscila entre −0,33 y +0,12 sin patrón.
- **Nivel conservador:** mediana de V/P = 0,64; solo el 31 % de las observaciones sale con valor mayor que el precio.
- **Acciones populares** (AAPL, MSFT, AMZN, META, NVDA, NFLX, ADBE, CRM, V, MA, COST, TSLA): V/P mediano 0,67 (el
  motor las veía caras) y aun así batieron al S&P 3 años en el 76 % de las observaciones, +15 pp anuales de media. El resto de
  acciones: −3,5 pp anuales, 40 % de aciertos.
- Encoger menos el crecimiento y el margen hacia la media (k de 0,3/0,6 a 0,5/0,8 y 0,7/0,9) no mejora la capacidad de
  discriminar (correlación a 3 años 0,077 → 0,039 → 0,009). Las constantes actuales se mantienen.

## Lectura (con cautela)
1. El DCF mecánico **no discrimina de forma útil** a 12 meses y casi nada a 3 años en esta muestra. Es coherente con la
   literatura (la valoración fundamental es una señal débil y lenta), pero significa que un "no atractiva" no equivale a
   "irá peor que el mercado".
2. El motor **es conservador en nivel** y en 2016-2024 infravaloró a las grandes empresas de crecimiento. La sospecha del
   usuario sobre las acciones populares tiene respaldo en estos datos.

## Sesgos que impiden concluir más
- **Supervivencia:** el universo son nombres conocidos hoy; las "populares" se eligieron sabiendo que triunfaron. Esto
  infla el +15 pp. Un universo con las mayores empresas de cada año corregiría este sesgo.
- Periodo dominado por el crecimiento tecnológico (2016-2024); no incluye un ciclo de valor largo.
- Observaciones solapadas (las de 3 años comparten años) y pocas fechas: la significación estadística es baja.
- Benchmark SPY y no VWCE; sin divisas.

## Qué haría falta
Un universo sin sesgo de supervivencia, el pipeline completo (analistas incluidos) sobre una muestra pequeña con fechas
pasadas en un entorno sin acceso al futuro, y el diario de predicciones real (resolver las predicciones a 12 meses).
Hasta entonces, las probabilidades no están calibradas (ver `limitaciones-conocidas.md`).

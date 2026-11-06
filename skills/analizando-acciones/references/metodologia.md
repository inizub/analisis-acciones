# Metodología del análisis

Índice: 1. Negocio · 2. Moat · 3. Gestión · 4. Estados financieros · 5. Valoración y drivers · 6. Escenarios ·
7. Riesgos y catalizador · 8. Checklist

## 1. Negocio

- Qué vende, a quién, cómo cobra y de qué depende el crecimiento. Usa `segmentos` y `guidance` del datapack.
- Tipología de Lynch: crecimiento lento (crece ≈ PIB, paga dividendo), sólida (crece 10-12 %, grande), crecimiento
  rápido (> 20 %, pequeña o mediana), cíclica (beneficios ligados al ciclo), recuperación (salida de pérdidas o crisis),
  activos ocultos (valor no reflejado en beneficios).
- La narrativa (≤ 5 frases) debe poder traducirse a números: cada frase apunta a un driver.

## 2. Moat

- Fuentes: activos intangibles (marca, patentes, licencias), costes de cambio, efecto red, ventaja de costes, escala
  eficiente. Si no hay evidencia, `ninguna`.
- Evidencia numérica: ROIC − WACC sostenido varios años (bancos: ROE − Ke). Compara con `damodaran.sector.valores`
  (`roic.roic`, `wacc.wacc`, `roe.roe`). Un ROIC alto un solo año no es moat.
- Amplitud: `amplio` si la ventaja dura previsiblemente > 10 años, `estrecho` si es real pero erosionable.

## 3. Gestión y asignación de capital

- Usos del flujo de caja: reinversión, adquisiciones, dividendos, recompras, deuda (`fundamentales`).
- Señales: recompras a precios razonables, dilución por remuneración en acciones (`sbc`, `acciones_diluidas`),
  adquisiciones con goodwill creciente, guidance cumplido o incumplido (`hechos_recientes`).

## 4. Estados financieros

- Calidad del beneficio: el flujo de caja operativo acompaña al beneficio neto. Las métricas y banderas de
  `forense_metricas.json` y `tasas_base.observados` resumen lo cuantitativo.
- Balance: deuda neta, cobertura de intereses y vencimientos. En bancos: capital (CET1), morosidad, coste del riesgo.
- Coherencia: el crecimiento exige reinversión (`ventas_capital` en `motor_inicial.base`); márgenes muy por encima del
  sector exigen explicación.

## 5. Valoración y drivers

- El motor valora con los drivers de tu ruta (ver `ruta-<ruta>.md`). Tú eliges los drivers; no calculas el valor.
- Parte de la tasa base: `tasas_base.observados` (dónde está hoy la empresa frente a su clase) y
  `tasas_base.para_reverse_dcf` (media y desviación). El caso mecánico de `motor_inicial.json` usa esas tasas
  encogidas: es tu punto de partida, no una conclusión.
- z = (driver − media) / desviación. z > 2 exige evidencia excepcional y concreta; z > 3 es casi imposible de forma
  orgánica.
- DCF inverso (`motor_inicial.reverse_dcf`): qué crecimiento, margen o años de ventaja descuenta el precio y en qué
  percentil de la tasa base está. Explica si esa expectativa es exigente, razonable o conservadora.

## 6. Escenarios

- Tres escenarios (bajista, base, alcista) con los mismos drivers y probabilidades que suman 1.
- Probabilidades granulares (p. ej. 0,22 / 0,53 / 0,25), no por defecto 0,25 / 0,50 / 0,25.
- El bajista incluye la pérdida permanente posible: qué tendría que pasar y cuánto valor se perdería (magnitud 0-1).
- El alcista no es «todo sale bien»: es un resultado plausible con evidencia.
- La métrica E4 de cada escenario debe ser coherente con sus drivers (si el driver de crecimiento base es 8 %, el E4
  base de crecimiento de ingresos del próximo ejercicio no puede ser 20 %).

## 7. Riesgos y catalizador

- Riesgos: los del pre-mortem, más los de `cambios.factores_riesgo` y la sensibilidad macro (`sensibilidades.json`:
  beta frente a tipos y a la divisa).
- Catalizador: qué evento concreto haría que el mercado cambie de expectativa y cuándo (meses).

## 8. Checklist

Antes de escribir tu salida comprueba:

1. Cada afirmación factual cita un `dato_ref` del datapack.
2. Cada driver con tasa base tiene percentil y z; los de z > 2 tienen `evidencia_excepcional`.
3. Las probabilidades de los escenarios suman exactamente 1 y el bajista tiene pérdida explícita.
4. Has leído el DCF inverso y lo comentas.
5. El pre-mortem tiene tres causas concretas.
6. La métrica E4 corresponde a tu ruta y al próximo ejercicio fiscal.
7. No has usado información que no esté en los archivos de la ejecución.

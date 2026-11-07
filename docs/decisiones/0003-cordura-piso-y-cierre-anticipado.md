# 0003. Cordura del modelo (aviso), piso de valor y cierre anticipado

**Estado:** aplicada (v0.2.0). **Fecha:** 7-nov-2026. **Commits:** `b6b3fa6`, `a360a9b`, `ad6e0e3`, `399652d`.

## Contexto
Con todos los escenarios valiendo 0,10-0,25 veces el precio, el modelo emitía probabilidades extremas como si fueran
fiables. Además, el escenario bajista de empresas con pérdidas y deuda (Rivian) daba un valor ≤ 0 y el motor abortaba.

## Decisión
- **Cordura (punto 12 del checklist):** si el precio queda a más de 2× del rango de valores de los escenarios
  (todos muy por debajo o muy por encima), se muestra un **aviso** en el resumen. Con `cordura.bloquea: true` el
  punto 12 pasa a ser un fallo (`no_analizable`). Por defecto es aviso.
- **Cierre anticipado:** si el bloqueo está activo y todos los analistas salen no fiables, el flujo salta red team y
  juez (`cierre_anticipado` en la salida de `escenarios`); sus puntos 7 y 8 no cuentan como fallo.
- **Piso de valor:** una acción no vale menos que cero. Si el DCF de un escenario da ≤ 0 se usa el 2 % del precio
  (`escenarios.valor_minimo_sobre_precio`) y se deja constancia (`piso_aplicado`, `valor_bruto`).

## Alternativas descartadas
- **Bloquear por defecto:** lo probé primero y las tres acciones de la prueba (AAPL, NU, NVDA) pasaron a `no_analizable`.
  Esas acciones están caras de verdad (Apple vale como mucho ~0,5× su precio en un DCF), así que bloquear ocultaba una
  conclusión válida. Se dejó como aviso.
- **Abortar con valor negativo (comportamiento original):** convertía cualquier empresa con pérdidas en `no_analizable`
  por un detalle matemático, no por falta de datos.

## Consecuencias
- El punto 12 del checklist es nuevo (el SPEC pasa de 11 a 12 puntos).
- Con el piso, los escenarios de una empresa con valor negativo en todos (Rivian) salen como 0,02 veces el precio; el
  veredicto final de Rivian lo da el punto 10 (el balance no sobrevive al bajista), no el piso.

## Dónde está
`scripts/motor/escenarios.py` (`cordura`, piso en `ejecutar`), `scripts/gate.py` (`punto_12`), `scripts/ejecucion.py`
(`cierre_anticipado`), `SKILL.md`, `assets/config.yaml`.

# Ruta banco y crédito

**Método:** excess return sobre el patrimonio (valor = patrimonio + valor presente de (ROE − Ke) × patrimonio) y
P/BV teórico = (ROE − g) / (Ke − g). Contraste: DDM y FCFE. No uses el DCF de la empresa entera: en un banco la deuda
es materia prima.

## Drivers obligatorios (mismos en los tres escenarios)

| Driver | Qué es | Unidad |
|---|---|---|
| `roe` | ROE medio de los próximos 5 años (también admite una lista de 5 valores anuales) | fracción |

Opcionales:

- `payout`: dividendos más recompras sobre beneficio. Por defecto, el de `motor_inicial.base.banco.payout`.
- `roe_estable`: ROE a partir del año 6. Por defecto igual al Ke (sin valor añadido después del año 5). El motor
  solo acepta un valor mayor si tu `moat` tiene fuente, amplitud y evidencia con `dato_ref`.

El DCF inverso da dos lecturas: `roe` (el ROE sostenido para siempre que justifica el precio) y
`roe_5_anios_luego_ke` (el ROE de los próximos 5 años si después baja al Ke, que es la convención de los escenarios).
Si la segunda es muy superior a la primera, el precio descuenta rentabilidades extraordinarias más allá del año 5:
decide con evidencia si fijas `roe_estable` por encima del Ke.

El coste del capital (`motor_inicial.base.banco.ke`) lo calcula el código.

## Campos críticos

Ingresos, beneficio neto, patrimonio, acciones diluidas, préstamos, depósitos, CET1 y su requisito (o, si no se
publica CET1, el ratio de capital total y su mínimo), precio y ERP.

## Trampas típicas

- Proyectar el ROE de un año de coste del riesgo anormalmente bajo.
- Crecimiento de préstamos muy rápido sin capital que lo respalde (el CET1 baja).
- Ignorar la exposición a la divisa y a los tipos del país de operación (`sensibilidades.json`).
- Confundir el gasto por intereses (coste de los depósitos) con deuda financiera.

## Banderas forenses específicas

Morosidad o coste del riesgo al alza dos años seguidos; CET1 a menos de 1 pp del requisito; crecimiento de préstamos
muy por encima del de depósitos.

## Métrica E4

`roe` del próximo ejercicio fiscal (beneficio neto / patrimonio al cierre), con `periodo` `FY<año>`.

# Ruta cíclica

**Método:** DCF con margen normalizado (media de 7-10 años) sobre los ingresos actuales y crecimiento estable;
o, si hay `crecimiento_ingresos`, DCF de 10 años con convergencia del margen al normalizado.
Contraste: múltiplo sobre beneficio normalizado frente al sector.

## Drivers obligatorios (mismos en los tres escenarios)

| Driver | Qué es | Unidad |
|---|---|---|
| `margen_operativo` | Margen operativo normalizado a lo largo del ciclo. El motor parte de la media histórica (`motor_inicial.base.margen_operativo`) | fracción |

Opcional: `crecimiento_estable` (crecimiento perpetuo; nunca por encima de la tasa sin riesgo `motor_inicial.base.rf`).

**Obligatorio** si el crecimiento de ventas de la empresa queda muy por encima de su clase (z > 2 en `tasas_base`,
o el router lo cita como evidencia): sin él, los ingresos se congelan en su nivel actual y el valor sale muy por debajo
del precio de forma artificial. Driver `crecimiento_ingresos` (crecimiento anual de los
ingresos durante 5 años, que luego desciende hasta la tasa terminal). Con este driver el motor usa el DCF de 10 años:
el margen converge desde el actual (`motor_inicial.base.margen_inicial`) hasta tu `margen_operativo` normalizado, y
`crecimiento_estable` no se usa. Sin él, los ingresos se mantienen en su nivel actual (modo estable): úsalo solo si
los datos con fuente (trimestres, guidance) apoyan un crecimiento sostenido.

## Campos críticos

Ingresos, beneficio operativo (idealmente 10 años), acciones diluidas, deuda total, caja, precio, ERP y beta sectorial.

## Trampas típicas

- Valorar con el margen del pico o del valle del ciclo.
- Usar el PER actual: es mínimo en el pico y máximo en el valle.
- Deuda que es asumible en el pico pero no en el valle: comprueba la cobertura de intereses con el margen bajista.

## Banderas forenses específicas

Inventario creciendo más que los ingresos al final del ciclo; cobertura de intereses baja.

## Métrica E4

`crecimiento_ingresos` del próximo ejercicio fiscal.

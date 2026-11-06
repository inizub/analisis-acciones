# Ruta biotech precomercial

**Método:** rNPV por activo del pipeline: ventas pico × probabilidad acumulada de aprobación (tabla BIO 2011-2020 por
fase y área), descontado; más la caja neta y menos el valor presente de los gastos generales.

## Drivers obligatorios (mismos en los tres escenarios)

| Driver | Qué es | Unidad |
|---|---|---|
| `factor_ventas_pico` | Multiplicador sobre las ventas pico con fuente del pipeline (1 = la estimación publicada) | veces |
| `factor_probabilidad` | Multiplicador sobre la probabilidad acumulada de aprobación de la tabla BIO (1 = la de la tabla; < 1 si los datos clínicos son peores que la media) | veces |

`motor_inicial.base.rnpv` muestra los activos, sus fases y las probabilidades. El margen, los plazos de lanzamiento y
la curva de ventas son parámetros fijos del motor.

## Campos críticos

Ingresos, flujo de caja operativo, caja, deuda total, acciones diluidas, precio y ERP; además, el pipeline con fase,
área y ventas pico con fuente.

## Trampas típicas

- Tomar el éxito de la fase actual como seguro: la fase II es el cuello de botella.
- Olvidar la dilución necesaria para financiar los ensayos (años de caja = caja / quema anual).
- Ventas pico de la propia empresa sin contraste externo.

## Banderas forenses específicas

Caja para menos de 12 meses; dilución anual alta; dependencia de un único activo.

## Métrica E4

`hito_clinico`: el próximo hito del activo principal (por ejemplo, «Lectura positiva de fase III de X-101»), con
`valor_base` 1 si en el escenario base se cumple; `valor_metrica_e4` es 1 en los escenarios donde se cumple y 0 donde
no. Se resuelve a mano.

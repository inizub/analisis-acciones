# Ruta general

**Método:** DCF de la empresa (FCFF) a 10 años y DCF inverso. Contraste: múltiplos frente al sector de Damodaran
(`damodaran.sector.valores`: `ev_ebitda.ev_ebit`, `ev_ebitda.ev_ebitda`).

## Drivers obligatorios (mismos en los tres escenarios)

| Driver | Qué es | Unidad |
|---|---|---|
| `crecimiento_ingresos` | Crecimiento anual de ingresos en los años 1-5; después el motor lo baja linealmente hasta el crecimiento terminal en el año 10. También admite una lista de hasta 10 tasas anuales | fracción (0.08) |
| `margen_operativo` | Margen operativo objetivo, al que se llega desde el actual (`motor_inicial.base.margen_inicial`) en 5 años | fracción |

Opcionales:

- `ventas_capital`: euros de ventas por euro de capital invertido nuevo (por defecto el de `motor_inicial.base`).
  Súbelo solo si hay evidencia de que el crecimiento necesitará menos inversión.
- `roic_terminal`: rentabilidad del capital a partir del año 10 (fracción). Por defecto es igual al WACC (sin valor
  añadido a largo plazo). El motor solo lo acepta si tu `moat` tiene fuente, amplitud y evidencia con `dato_ref`;
  usa como referencia el ROIC histórico y el del sector (`roic.roic`), sin superarlos.

El DCF inverso de `motor_inicial.json` mantiene el margen operativo actual; el caso mecánico usa la tasa base
encogida de margen y crecimiento.

## Campos críticos

Ingresos, beneficio operativo, acciones diluidas, deuda total, caja, precio, ERP y beta sectorial.

## Trampas típicas

- Crecimiento alto y margen alto a la vez sin reinversión acorde.
- Margen objetivo por encima del máximo histórico de la empresa y del p90 de su clase.
- Ignorar la dilución por remuneración en acciones (`sbc`).
- Tomar el guidance como escenario base sin contrastarlo con la tasa base.

## Banderas forenses específicas

Las de `forense_metricas.json`; atención a cuentas a cobrar e inventario creciendo más que los ingresos.

## Métrica E4

`crecimiento_ingresos` del próximo ejercicio fiscal (fracción), con `periodo` `FY<año>`.

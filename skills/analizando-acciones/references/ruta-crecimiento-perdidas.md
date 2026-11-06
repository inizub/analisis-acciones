# Ruta crecimiento con pérdidas

**Método:** DCF desde los ingresos (crecimiento → margen objetivo → reinversión por ventas/capital) con una
probabilidad de fracaso explícita en el escenario bajista. Contraste: DCF inverso.

## Drivers obligatorios (mismos en los tres escenarios)

| Driver | Qué es | Unidad |
|---|---|---|
| `crecimiento_ingresos` | Crecimiento anual en los años 1-5 (después baja hasta el terminal en el año 10), o lista de hasta 10 tasas | fracción |
| `margen_operativo` | Margen operativo objetivo a 5 años; puede partir de un margen actual negativo | fracción |
| `probabilidad_fracaso` | Probabilidad de que la empresa no llegue a ser viable (quiebra, dilución masiva). Pon 0 en base y alcista si no aplica | fracción 0-1 |
| `valor_fracaso_por_accion` | Valor por acción si fracasa (caja neta recuperable por acción; 0 si no hay) en la moneda del informe | por acción |

Opcional: `roic_terminal`, con las mismas condiciones que en `ruta-general.md`.

## Campos críticos

Ingresos, beneficio operativo, flujo de caja operativo, acciones diluidas, deuda total, caja, precio, ERP y beta
sectorial.

## Trampas típicas

- Margen objetivo de empresa madura sin explicar cómo se alcanza.
- Ignorar la caja disponible frente a la quema (`fco` negativo): cuántos años aguanta sin ampliar capital.
- Crecimiento sostenido muy por encima del p90 de su clase.

## Banderas forenses específicas

Dilución anual alta, remuneración en acciones elevada, peso creciente de métricas ajustadas.

## Métrica E4

`crecimiento_ingresos` del próximo ejercicio fiscal.

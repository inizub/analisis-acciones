# Ruta holding

**Método:** suma de partes: beneficio operativo de cada segmento × múltiplo EV/EBIT de su industria, menos la deuda
neta y el valor presente de los costes del holding.

## Drivers obligatorios (mismos en los tres escenarios)

| Driver | Qué es | Unidad |
|---|---|---|
| `factor_multiplos` | Multiplicador común sobre los múltiplos sectoriales de los segmentos (1 = el múltiplo de la industria; < 1 si los negocios son peores que su sector) | veces |

`motor_inicial.base.sotp` muestra los segmentos, sus beneficios y sus múltiplos.

## Campos críticos

Ingresos, acciones diluidas, deuda total, caja y segmentos con beneficio operativo y múltiplo con fuente; precio, ERP y
beta sectorial.

## Trampas típicas

- Ignorar el descuento habitual de los holdings y sus costes centrales.
- Segmentos con beneficio de un año excepcional.
- Participaciones minoritarias contadas al 100 %.

## Banderas forenses específicas

Operaciones entre segmentos y con partes vinculadas; goodwill alto y creciente.

## Métrica E4

`crecimiento_ingresos` del próximo ejercicio fiscal.

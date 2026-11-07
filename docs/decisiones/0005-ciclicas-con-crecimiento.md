# 0005. Cíclicas que crecen: DCF de 10 años con convergencia del margen

**Estado:** aplicada (v0.2.0). **Fecha:** 7-nov-2026. **Commit:** `a360a9b`.

## Contexto
La ruta cíclica valoraba con el margen normalizado sobre los **ingresos actuales** y crecimiento estable: los ingresos
quedaban congelados. Para NVDA, que crece más de un 100 % interanual, eso hundía el valor de forma artificial. Dos agentes
(red team y analista B) lo advirtieron: el crecimiento que declaraba el analista no entraba en el cálculo.

## Decisión
Si el analista da `crecimiento_ingresos` en la ruta cíclica, el motor usa el **DCF de 10 años** (el SPEC ya lo permitía:
"el DCF de 10 años de `dcf.py`") con el margen convergiendo desde el actual hasta el normalizado del analista. Sin ese
driver, todo sigue como antes. La referencia de la ruta (`references/ruta-ciclica.md`) lo hace **obligatorio** cuando el
crecimiento de ventas está muy por encima de su clase (z > 2).

## Alternativas descartadas
- **Decidirlo en código por el crecimiento observado:** los números los fija el analista con evidencia; el código no
  debería imponer un crecimiento.
- **Usar siempre el DCF de 10 años:** perdería la simplicidad (y la robustez) del método normalizado para cíclicas estables.

## Consecuencias
- Comprobado: el analista B de NVDA pasó de valer 0,12-0,30× el precio a 0,18-0,82×, y los analistas A y N lo declararon
  tras actualizar la referencia.
- El analista tiene ahora una responsabilidad que antes no tenía: dar crecimiento con evidencia (guía, trimestres).

## Dónde está
`scripts/motor/escenarios.py` (`valorar`, rama cíclica), `references/ruta-ciclica.md`.

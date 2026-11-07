# 0001. Un solo modelo de trayectorias para todas las probabilidades

**Estado:** aplicada (v0.2.0). **Fecha:** 7-nov-2026. **Commits:** `ad6e0e3`, `8543524`.

## Contexto
El primer análisis real de NVDA dio: 28 % de batir a VWCE a 12 meses, **81 % de caer un 30 %** y un rango de retornos
relativos (p5 / p50 / p95) de −78 % / −54 % / −11 %. Eso es incoherente: un p95 negativo implica menos de un 5 % de
batir a VWCE, y una probabilidad de caída del 81 % no cuadra con ninguna de las otras cifras. El usuario lo señaló:
"no puedo decir que tengo 55 % de superar al VWCE y luego 60 % de que baje 30 %".

La causa era que cada número salía de un cálculo distinto:
- Batir a VWCE (E0-E2) se "encogía" hacia 0,45 con un peso k = 0,4.
- La caída del 30 % (E3) no se encogía y venía de otra simulación.
- Los percentiles tampoco se encogían.
- Además, una acción a su valor rendía solo sus dividendos mientras VWCE rendía ~7 %: un pesimismo de fondo.

## Decisión
`escenarios.simular` genera **trayectorias mensuales conjuntas** (ruido t de Student, ν = 4) y de ellas salen E0-E3, los
percentiles y el exceso esperado, así que no pueden contradecirse.
- Cada trayectoria sigue, con probabilidad k = 0,4, un escenario del analista y, con 1 − k, el escenario **neutral**
  (precio = valor). El encogimiento hacia la tasa base ya va dentro de la distribución.
- Una acción a su valor rinde en media (aritmética) lo mismo que VWCE: su probabilidad de batirlo queda en ~0,45
  por la asimetría, sin imponerla a mano.
- `agregar.py` hace la media lineal de A y B (mezcla de distribuciones) y calcula los percentiles de la mezcla.
- **Tope suave a la diferencia valor/precio (~2×):** ln(V/P0) se satura con L·tanh(ln(V/P0)/L). Un DCF que dice
  que una acción vale 4 veces menos que su precio es más probable que esté equivocado que el mercado. Es monótono
  (más caro nunca da mejores probabilidades).

## Alternativas descartadas
- **Poner un techo fijo a E3** (por ejemplo, 40 %): arregla el número, no la causa, y deja el resto incoherente.
- **Convergencia en 5 años (`T_conv_anios`) en vez de 3:** bajaba la caída del 30 %, pero hacía "atractiva" inalcanzable
  (incluso valiendo 3× el precio quedaba en 53 % de batir a VWCE). Se mantiene en 3.
- **Bajar el peso del modelo de golpe al pasar de 2×:** habría hecho que una acción algo más cara saliera mejor que
  otra algo más barata. El tope suave evita ese salto.

## Consecuencias
- NVDA pasó de 51 % a 40 % de caer ≥30 % (a 81 % antes de esta decisión); KO ≈ 10 %, VZ ≈ 12 %: ordenadas por volatilidad.
- Con datos reales, un 40 % de NVDA sigue por encima del histórico de 5 años (23 %), pero ese periodo fue muy
  alcista. La calibración fina se hará con el diario cuando se resuelvan predicciones, no a ojo.
- Cambió el SPEC (A6.4 y A6.6).
- Los tests comprueban la coherencia entre percentiles y p(E1), la monotonía respecto al precio y el efecto de la mezcla.

## Dónde está
`skills/analizando-acciones/scripts/motor/escenarios.py` (`simular`, `desviacion_creible`), `scripts/agregar.py`,
`assets/config.yaml` (`escenarios.tope_desviacion`, `agregacion.k`), `SPEC.md` A6.4 y A6.6.

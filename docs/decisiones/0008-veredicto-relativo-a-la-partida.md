# 0008. Veredicto relativo a la probabilidad de partida de cada acción

**Estado:** aplicada (v0.3.0). **Fecha:** 7-nov-2026. **Commit:** el de la v0.3.0.

## Contexto
Las reglas de A1 usaban umbrales fijos: "atractiva" si p(E1) ≥ 0,55 y "no atractiva" si p(E1) ≤ 0,40. Pero la
probabilidad que sale si una acción vale justo su precio (la **partida**) depende de su volatilidad: ≈ 0,45 con
volatilidad relativa del 20 % y ≈ 0,41 con el 40 %. Consecuencias medidas con simulaciones:
- Para acciones con volatilidad ~40 % (NVDA, NU, Valero) "atractiva" era **inalcanzable**: la p(E1) se queda en ~51 %
  aunque la acción valga 4 veces su precio.
- Una acción volátil a precio justo (p = 0,41) quedaba a una décima de "no atractiva" sin que el modelo viera nada malo.

## Decisión
Medir la **ventaja sobre la partida** de esa misma acción (`p_partida` = p(E1) del escenario neutral):
- `atractiva`: p_final(E1) ≥ partida + 0,06, exceso esperado ≥ +5 pp, pérdida bajista ≤ 50 % y sin banderas graves.
- `no_atractiva`: p_final(E1) ≤ partida − 0,05 (además de las condiciones de DCF inverso y z > 3, que no cambian).
Con la partida 0,45 coincide con los umbrales originales (0,55 y 0,40). Sin partida calculada (salidas antiguas) se usan los
absolutos. Parámetros: `veredicto.ventaja_atractiva` y `ventaja_no_atractiva` en `config.yaml`.

## Alternativas descartadas
- **Mantener 0,55 y 0,40 fijos:** ver el contexto.
- **Usar el horizonte de 36 meses (E2) para el veredicto:** añade ruido de largo plazo y la puntuación del diario se
  diseñó con E1 como evento principal.
- **Subir el peso del modelo (k) o quitar el tope de 2×:** recalibrarlo habría deshecho [0001](0001-probabilidades-coherentes.md).

## Consecuencias
- Medido con simulaciones: a volatilidad relativa del 20 % basta un valor de ~2× el precio para "atractiva"; a 40 %, ~3×.
  Sigue siendo exigente, como corresponde a un modelo prudente con peso del 40 % en las opiniones del analista.
- Los 8 análisis reales dan el mismo veredicto que antes (6 no atractivas, 2 neutrales: Verizon y Valero), pero con motivos
  que muestran la partida de cada acción.
- Cambió el SPEC (A1).
- No se ha visto aún una acción real claramente barata que salga "atractiva": se comprobó con acciones sintéticas.

## Dónde está
`scripts/agregar.py` (`condiciones_veredicto`), `assets/config.yaml` (`veredicto`), `SPEC.md` A1, `tests/test_agregar.py`.

# 0002. Base de ingresos de los últimos doce meses y balance reciente

**Estado:** aplicada (v0.2.0 a v0.3.0). **Fecha:** 7-nov-2026. **Commits:** `b6b3fa6`, `0637a5b`, `9c5285a`.

## Contexto
El motor valoraba con los ingresos del **último ejercicio anual**. En NVDA eso eran 215,9 mil M cuando los últimos
doce meses ya eran ~303 mil M: el valor salía unas 5 veces menor de lo razonable. Probando más acciones apareció lo mismo en
Freeport y Rivian (base de hace 10 meses sin ningún aviso) y, para empresas que queman caja, la caja y deuda también
eran del último ejercicio.

## Decisión
- **Últimos doce meses (TTM)** = último ejercicio + trimestres posteriores − sus comparables del año anterior
  (`inicial.base_doce_meses`). **Nunca se estima**: si faltan trimestres o no encadenan con el cierre anual, se usa el
  último ejercicio y se avisa.
- **`ttm_ingresos`:** si solo se pueden encadenar los ingresos (p. ej. el emisor no publica resultado operativo
  trimestral), se usan los ingresos de 12 meses con el margen del último ejercicio, y se avisa.
- **Trimestres pendientes:** si el último ejercicio tiene más de 6 meses y no hay trimestres posteriores
  (`datos.base_max_meses`), `ejecucion.datos` llama al agente de datos aunque no falte ningún campo crítico
  (`trimestrales_pendientes`).
- **Balance reciente (v0.3.0):** el agente trae `trimestrales.caja` y `trimestrales.deuda_total` del último balance
  trimestral; `inicial.saldo_reciente` usa el saldo trimestral si es posterior al anual, y avisa si el balance tiene
  más de 6 meses.

## Alternativas descartadas
- **Anualizar el último trimestre:** es una estimación; las reglas del proyecto prohíben estimar datos financieros.
- **Dejar que el juez corrija la base con estimaciones:** ocurrió (el juez puso 346 mil M calculados con la guía de la
  empresa) y se prohibió; véase [0006](0006-ajustes-del-juez-sobre-la-base.md).

## Consecuencias
- NVDA: crecimiento exigido por el precio de 47,6 % a 39,5 %; valor mecánico de 28 a 40 USD.
- Cada ejecución necesita ahora el agente de datos para casi todas las empresas con ejercicio antiguo (más coste).
- El margen de `ttm_ingresos` es el del último ejercicio: conservador si el margen actual es mayor (Nucor: 8 % frente a ~15 %).

## Dónde está
`scripts/motor/inicial.py` (`base_doce_meses`, `saldo_reciente`), `scripts/ejecucion.py` (`trimestres_pendientes`),
`agents/datos.md`, `SKILL.md` (paso 3), `assets/config.yaml` (`datos.base_max_meses`).

# 0007. Beneficio operativo aproximado cuando el emisor no lo publica

**Estado:** aplicada (v0.2.1). **Fecha:** 7-nov-2026. **Commit:** `9c5285a`.

## Contexto
Nucor (siderúrgica) no publica `OperatingIncomeLoss` en XBRL, solo el resultado antes de impuestos. La ruta cíclica
exige 7-10 años de margen operativo, así que el plugin la daba como `no_analizable`. Las reglas del proyecto
dicen que nunca se estima un dato financiero; aquí no es una estimación inventada sino un cálculo con partidas reportadas,
pero es una aproximación. El usuario autorizó implementarlo ("sigue") tras ver la propuesta.

## Decisión
`edgar.CAMPOS["beneficio_operativo"]["respaldo"]`: resultado antes de impuestos + gasto por intereses − ingresos por
intereses (`InvestmentIncomeInterest`), **solo** si el emisor no tiene ningún candidato principal. Nunca se mezcla con
`OperatingIncomeLoss`. El nombre del concepto compuesto queda en cada cifra y el motor añade un aviso explícito.
El agente de datos no calcula el beneficio operativo trimestral: si no se publica, lo marca desconocido.

## Alternativas descartadas
- **Dejar `no_analizable`:** es la opción más pura, pero descarta emisores que son claramente analizables.
- **Aproximar también los trimestres:** multiplica la incertidumbre; se prefiere usar el margen del último ejercicio ([0002](0002-base-de-doce-meses-y-balance-reciente.md)).

## Consecuencias
- Nucor: ruta cíclica con confianza alta, 38 % de batir a VWCE y 26 % de caer ≥30 % (resultado coherente).
- La aproximación ignora partidas no operativas distintas de intereses; para quitarla basta borrar la clave `respaldo`.

## Dónde está
`scripts/datos/edgar.py`, `scripts/motor/inicial.py` (aviso), `tests/test_edgar.py`.

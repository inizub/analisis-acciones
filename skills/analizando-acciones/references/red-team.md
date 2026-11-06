# Red team: formato y procedimiento

## Objeciones

Busca, por este orden, los errores que más moverían el resultado:

1. `dato_erroneo`: una cifra usada por un analista que no coincide con el datapack o con su periodo o moneda.
2. `supuesto_implausible`: un driver alejado de la tasa base sin evidencia (mira su z y percentil en
   `tasas_base`), o incoherente con otros drivers (crecimiento alto sin reinversión, margen por encima del sector sin
   moat demostrado).
3. `riesgo_omitido`: un riesgo presente en el datapack (`cambios`, `hechos_recientes`, `banca`, `sensibilidades`,
   `forense_metricas`) que ningún escenario recoge.
4. `contradiccion_interna`: la narrativa, los drivers, las probabilidades o la métrica E4 de un analista no casan entre
   sí, o el bajista no refleja la pérdida permanente que el propio analista describe.

Cada objeción:

- `id`: O1, O2…, ordenadas de mayor a menor impacto.
- `dato_ref`: el campo del datapack o del informe del analista al que se refiere (obligatorio; sin él se descarta).
- `objecion`: qué está mal, en una o dos frases.
- `prueba`: cómo verificarla con los archivos (qué campo mirar y qué valor esperar).
- `impacto_estimado`: el driver afectado, el escenario, el analista, la dirección (`sube`/`baja`) y la magnitud del
  cambio propuesto en el driver (en sus unidades).
- `severidad`: `alta` si cambiaría el escenario base o la probabilidad del bajista de forma relevante; `media` si
  mueve un escenario; `baja` si es un matiz.

Entre 3 y 8 objeciones. Mejor pocas y verificables que muchas y vagas.

## Mejor argumento contrario

El argumento más fuerte contra la tesis dominante (la del analista con el escenario base más optimista si A y B
difieren, o la común si coinciden). Basado en datos del datapack, en ≤ 1.000 caracteres.

## Pre-mortem propio

«Dentro de 12 meses la acción ha quedado un 30 % por detrás de VWCE; las causas más probables son…». Al menos tres
causas concretas y distintas de las que ya dieron los analistas, si las hay.

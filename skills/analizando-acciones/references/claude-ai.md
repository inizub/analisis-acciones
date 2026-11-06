# Modo degradado (chat de claude.ai)

En el chat de claude.ai no hay subagentes ni hooks. El análisis se hace en serie en una sola conversación, se marca
`modo: degradado` e `independencia: false` y se puntúa aparte.

## 1. Datos

- Si el usuario ha subido un `datapack.json` generado en local, úsalo.
- Si no, pide que lo genere en su ordenador con
  `bash scripts/py.sh <directorio de datos> datos/datapack_base.py <TICKER> --dir <carpeta>` y lo suba.
- Si no puede, construye el datapack con búsqueda web siguiendo `references/esquemas.md` (formato de cifra): cada cifra
  con `fuente_url`, `fecha_dato` y `fecha_obtencion`; lo que no encuentres, `desconocido` con su causa. No completes
  nada con tu conocimiento.

## 2. Motor

- Si tienes ejecución de código, instala las dependencias de `requirements.txt` y ejecuta los mismos scripts que en
  Claude Code: `ejecucion.py codigo`, después el análisis y `ejecucion.py escenarios` y `ejecucion.py cerrar` con
  `--modo degradado`.
- **Sin ejecución de código, el veredicto es `no_analizable`** con el motivo «sin motor de valoración». No calcules
  valoraciones ni probabilidades a mano.

## 3. Análisis, en serie

1. Analista con encuadre neutral («Evalúa la acción»): sigue `agents/analista-fundamental.md`, `metodologia.md`, la
   referencia de la ruta y `sesgos.md`, y escribe `analista_N.json`.
2. Red team sobre ese análisis: sigue `red-team.md` y escribe `objeciones.json`.
3. Síntesis: tres razones, el mejor contraargumento (del red team) y al menos dos criterios de invalidación en
   `sintesis.json`.

Escribe el análisis antes de leer las objeciones y no lo cambies después: el red team corrige drivers solo a través de
`ajustes.json`.

## 4. Salida

El mismo `verdict.json` y `resumen.md` que en Claude Code, con `modo: degradado`. Si no hay diario accesible, entrega
el verdict.json al usuario para que lo añada a su diario local.

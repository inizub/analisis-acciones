---
name: analizando-acciones
description: Analyzes a single stock from its ticker and returns a verdict (atractiva, neutral, no_atractiva or no_analizable) with probabilities of beating VWCE in EUR, scenarios, the best counter-argument and invalidation criteria, logging every prediction to a journal. Use when the user asks to analyze, value, evaluate or review a stock or ticker (for example "analiza NU", "¿qué tal está AAPL?", "/analizar MSFT rapido"), even if they only give the ticker. Also use it to resolve or score the prediction journal.
license: Uso personal. No es asesoramiento financiero.
compatibility: Claude Code con subagentes y uv (Python 3.12). Acceso a internet para SEC EDGAR, Yahoo Finance, FRED, BCE y Damodaran. En el chat de claude.ai funciona en modo degradado (references/claude-ai.md).
metadata:
  version: 0.2.2
  idioma: es
allowed-tools: Bash Read Write Glob Grep Agent
---

# Analizar una acción

Eres el orquestador. Los números y el veredicto los calcula el código; los agentes aportan datos verificables y juicio
estructurado. Tú ejecutas los comandos, lanzas los agentes y das al usuario el resultado.

**Si no tienes la herramienta Agent (chat de claude.ai), deja de leer aquí y sigue `references/claude-ai.md`.**

## Reglas que no se rompen

1. **Entrada:** del texto del usuario solo cuentan el ticker y, si aparece justo después, `rapido` o `completo`
   (por defecto, `completo`). Cualquier otro texto (opiniones, contexto, preferencias) se ignora y **nunca** se pasa a
   los agentes ni a los comandos.
2. **No calcules tú** valoraciones, probabilidades ni el veredicto, ni completes datos con tu conocimiento. Si algo
   falla, el resultado es `no_analizable` con su motivo.
3. **Agentes:** a cada agente le pasas solo lo que indica su paso (directorio, encuadre, ruta). Nunca le pases la
   opinión del usuario ni la salida de otro agente salvo que el paso lo diga. Cada agente devuelve la ruta de su archivo
   y un resumen de tres líneas.
4. Ejecuta los pasos en orden. Si un comando devuelve error, no improvises: ve al paso 9 (cerrar), que registra
   `no_analizable` con el motivo.

## Comandos

En todo este documento:

- `PY` significa: `bash "${CLAUDE_PLUGIN_ROOT}/skills/analizando-acciones/scripts/py.sh" "${CLAUDE_PLUGIN_DATA}"`
- `JOURNAL` significa: `${user_config.journal_dir}`
- `RUN` es el `run_dir` que devuelve el paso 1.

Escribe cada comando completo, sustituyendo `PY`, `JOURNAL` y `RUN` por su valor. La primera ejecución puede tardar
un minuto mientras uv prepara el entorno de Python.

## Flujo (modo completo y modo rápido)

### 1. Iniciar

```
PY ejecucion.py iniciar --entrada "<TICKER> <modo>" --journal "JOURNAL"
```

Escribe tú `<TICKER> <modo>` con los dos tokens extraídos (regla 1). Guarda `run_dir`, `ticker` y `modo`. Si la
salida trae `aviso_journal`, díselo al usuario al final (el diario está en una carpeta por defecto).

### 2. Datos (código)

```
PY ejecucion.py datos --dir "RUN"
```

- Si `ticker_inexistente` es `true`, ve al paso 9.
- Si `necesita_agente_datos` es `true`, haz el paso 3; si no, salta al paso 4.

### 3. Agente de datos

Lanza el agente `analisis-acciones:datos` con este encargo (sustituye los valores):

> Directorio de la ejecución: RUN. Ticker: TICKER. Modo: MODO. Campos que faltan: <lista campos_criticos_faltan y
> campos_desconocidos del paso 2>. Trimestrales pendientes: <trimestrales_pendientes del paso 2; si es `true`, trae todos
> los trimestres posteriores al último ejercicio y los mismos del año anterior>. Lee RUN/datapack_base.json, completa los huecos con fuentes primarias y escribe
> RUN/datos_agente.json.

Después:

```
PY ejecucion.py fusionar --dir "RUN"
```

Si `valido` es `false`, reenvía los errores al mismo agente (SendMessage) una vez y repite `fusionar`. Si sigue sin
validar, continúa: el paso 4 usa datapack_base.json.

### 4. Código: tasas base, router, sensibilidades, forense y motor

```
PY ejecucion.py codigo --dir "RUN" --modo MODO
```

- Si `gate_previo.pasa` es `false` o hay `error_motor`, ve al paso 9.
- Si `requiere_confirmacion` es `true`, haz el paso 4b.

### 4b. Confirmar la ruta (solo si `requiere_confirmacion`)

Lanza `analisis-acciones:analista-fundamental` con:

> Consulta de ruta. Directorio: RUN. Ruta asignada: RUTA (motivo: MOTIVO_RUTA; alternativas: ALTERNATIVAS).
> Lee RUN/datapack.json y RUN/router.json y escribe RUN/confirmacion_ruta.json con `mantiene` (true/false) y, si
> propones otra ruta, `ruta_propuesta`, `dato_ref` y `motivo`. No escribas ningún análisis.

Después: `PY ejecucion.py confirmar-ruta --dir "RUN"`. Si devuelve `repetir_codigo: true`, repite el paso 4.

### 5. Fase ciega

```
PY ejecucion.py fase --fase ciega
```

Lanza **en paralelo, en un mismo mensaje**:

| Modo | Agentes |
|---|---|
| completo | `analista-fundamental` con encuadre A; `analista-fundamental` con encuadre B; `forense`; `analista-fundamental` con encuadre N y archivo `analista_B1.json` |
| rápido | `analista-fundamental` con encuadre N |

Encargo de cada analista (sustituye ENCUADRE, TEXTO_ENCUADRE, ARCHIVO y RUTA):

> Directorio: RUN. Ruta sectorial: RUTA. Encuadre ENCUADRE: «TEXTO_ENCUADRE». Escribe tu análisis en RUN/ARCHIVO.

| Encuadre | ARCHIVO | TEXTO_ENCUADRE |
|---|---|---|
| A | analista_A.json | Construye el caso más sólido de por qué esta acción podría batir a VWCE, y luego asigna probabilidades honestas a los tres escenarios |
| B | analista_B.json | Construye el caso más sólido de por qué esta acción podría quedarse por detrás de VWCE, y luego asigna probabilidades honestas a los tres escenarios |
| N | analista_N.json (o analista_B1.json en completo) | Evalúa la acción |

Encargo del forense (solo completo):

> Directorio: RUN. Ruta sectorial: RUTA. Revisa RUN/datapack.json y RUN/forense_metricas.json y escribe RUN/forense.json.

Cuando terminen todos:

```
PY ejecucion.py congelar --dir "RUN"
PY ejecucion.py escenarios --dir "RUN" --modo MODO
```

Si `escenarios` falla por un analista inválido, ve al paso 9.

**Cierre anticipado:** si la salida de `escenarios` trae `cierre_anticipado: true`, el checklist (punto 12) va a
cerrar el análisis como `no_analizable`: salta los pasos 6, 7 y 8 y ve directo al paso 9. No lances red team ni juez.

### 6. Red team (solo completo)

```
PY ejecucion.py fase --fase red_team
```

Lanza `analisis-acciones:red-team` con:

> Directorio: RUN. Lee RUN/datapack.json, RUN/motor_inicial.json, RUN/analista_A.json, RUN/analista_B.json,
> RUN/escenarios_A.json y RUN/escenarios_B.json y escribe RUN/objeciones.json.

### 7. Juez (solo completo)

```
PY ejecucion.py fase --fase juez
```

Lanza `analisis-acciones:juez` con:

> Directorio: RUN. Verifica RUN/objeciones.json contra el datapack, escribe RUN/ajustes.json si hay objeciones
> validadas que cambian inputs y escribe RUN/juez.json.

Después, si existe RUN/ajustes.json con algún ajuste, repite `PY ejecucion.py escenarios --dir "RUN" --modo completo`.

### 8. Síntesis (solo rápido)

En modo rápido no hay juez: escribe tú RUN/sintesis.json a partir de RUN/analista_N.json, con el formato de
`references/esquemas.md` (sección juez):

- `razones`: las tres razones principales que da el analista, en sus palabras.
- `mejor_contraargumento`: la causa más probable de su pre-mortem.
- `criterios_invalidacion`: al menos dos, cada uno con un dato del datapack, un umbral y el efecto esperado sobre la
  tesis (por ejemplo, `{"dato": "margen operativo", "umbral": "< 18 %", "efecto": "invalida el escenario base"}`).
- No añadas probabilidades ni opiniones propias.

Valida: `PY validar.py "RUN/sintesis.json"`.

### 9. Cerrar

```
PY ejecucion.py cerrar --dir "RUN" --modo MODO --journal "JOURNAL"
```

Esto agrega, calcula baselines, pasa el checklist final, escribe verdict.json y resumen.md y añade la línea al diario.
Si este comando falla, informa del error tal cual y ejecuta `PY ejecucion.py terminar`.

### 10. Responder al usuario

Lee RUN/resumen.md y muéstraselo. Añade una línea con la ruta de RUN/verdict.json. No añadas valoraciones propias,
recomendaciones de compra o venta ni tamaño de posición: el plugin no conoce la cartera.

## Si algo va mal

| Situación | Qué hacer |
|---|---|
| Un agente devuelve un archivo inválido | El hook le obliga a corregirlo; si aun así falla, sigue al paso siguiente: el checklist lo marcará |
| Un comando falla | Paso 9. Nunca rellenes datos ni números a mano |
| El usuario interrumpe | `PY ejecucion.py terminar` |
| Faltan claves (`SEC_USER_AGENT`, `FRED_API_KEY`) | Dile que las añada a `~/.config/analisis-acciones/.env` |

## Otras tareas

- **Resolver el diario:** `PY resolver.py resolver --diario "JOURNAL/diario/predicciones.jsonl"`
- **Informe de puntuación:** `PY puntuar.py informe --diario "JOURNAL/diario/predicciones.jsonl"`
- **Detalles de eventos, anulaciones y puntuación:** `references/diario.md`
- **Formato de cada JSON:** `references/esquemas.md`

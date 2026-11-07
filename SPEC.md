# Plugin `analisis-acciones`: especificación completa

Versión del documento: 1.0 · 2026-11-06 · Autor de las decisiones: Iñigo (usuario) con Claude.

---

## 0. Cómo usar este documento

Este documento contiene todo lo necesario para construir el plugin. Tiene dos partes:

- **Parte A: Especificación.** Qué construir, exactamente. Es la fuente de instrucciones.
- **Parte B: Justificación.** Por qué cada decisión es como es, con la evidencia que la respalda. Sirve para que entiendas el diseño y no deshagas decisiones por error.

**Regla de redacción para todo lo que construyas:** los prompts de los agentes (`agents/*.md`), el `SKILL.md` y los archivos de `references/` contienen **solo instrucciones operativas**: qué hacer, con qué entradas, qué salida producir y en qué formato. Nunca incluyen justificaciones, citas de estudios, alternativas descartadas ni la Parte B. Un agente necesita saber qué tiene que hacer, no por qué se eligió así.

Si al construir algo encuentras que una decisión de la Parte A es inviable o contradice la Parte B, **pregunta al usuario antes de cambiarla**. La sección A16 lista lo que hay que verificar durante la construcción.

### Contexto del usuario
- Iñigo, 21 años, residente en España, invierte con Revolut. Núcleo de cartera: VWCE (FTSE All-World, en EUR, Xetra). Satélite: acciones individuales.
- Plan Claude **Pro**. Python local disponible; acepta claves de API gratuitas.
- Universo de acciones: las disponibles en Revolut. En la práctica: acciones de EE. UU., ADR de emisores extranjeros (20-F, p. ej. NU Holdings) y algunas europeas.
- Documento metodológico de referencia: **"Cómo invertir y analizar una acción: guía basada en evidencia para diseñar un sistema multiagente"** (en el Project "Portafolio"). Secciones relevantes: 3 (proceso de análisis), 4 (macro y precedentes), 6 (sesgos), 8 (checklist), 9 (diseño multiagente). Las secciones 5.1 y 5.6 (núcleo-satélite, fiscalidad) y el punto A del checklist (encaje en cartera) quedan fuera del plugin.
- El plugin es **genérico**: recibe un ticker y devuelve un análisis con veredicto. No conoce la cartera, el tamaño de posición ni la fiscalidad del usuario. Su salida la consume otro proyecto (Project "Portafolio" en claude.ai), que decide la acción concreta (comprar, mantener, etc.) y el tamaño.

---

# PARTE A: ESPECIFICACIÓN

## A1. Contrato de entrada y salida

**Entrada:** `/analizar TICKER [rapido|completo]`. Por defecto `completo`. El orquestador ignora cualquier otro texto que acompañe al ticker (opiniones, contexto, preferencias del usuario) y nunca lo pasa a los subagentes.

**Salida:**
1. `verdict.json`, validado contra `assets/schemas/verdict.schema.json`.
2. `resumen.md`, legible para humanos (≤ 1 página).
3. Una línea añadida al diario de predicciones (`diario/predicciones.jsonl`).

**Veredicto (uno de cuatro):** `atractiva` | `neutral` | `no_atractiva` | `no_analizable`.

**Eventos que el plugin predice** (todos en rentabilidad total en EUR, con dividendos; precio de referencia: cierre del día del análisis; benchmark: VWCE en Xetra, `VWCE.DE`):

| ID | Evento | Horizonte | Uso |
|---|---|---|---|
| E1 | RT(acción) − RT(VWCE) > 0 | 12 meses | **Evento principal**: decide el veredicto |
| E0 | RT(acción) − RT(VWCE) > 0 | 6 meses | Secundario |
| E2 | RT(acción) − RT(VWCE) > 0 | 36 meses | Tesis larga, informativo |
| E3 | La acción cae ≥ 30 % desde el precio de entrada en algún momento | 12 meses | Riesgo |
| E4 | La métrica fundamental clave del siguiente ejercicio fiscal ≥ el valor del escenario base | Próximo informe anual | **Evento de aprendizaje** |

La métrica de E4 depende de la ruta sectorial: crecimiento de ingresos (general, cíclica, crecimiento), ROE (banco), hito clínico (biotech).

Cada evento lleva una cláusula de anulación definida antes de emitir: OPA o fusión, exclusión de cotización, escisión, o dato de resolución no disponible.

**Reglas del veredicto** (las aplica `gate.py` y `agregar.py`; los parámetros viven en `assets/config.yaml`):

| Veredicto | Regla |
|---|---|
| `no_analizable` | Ruta fuera de alcance, **o** campo crítico `desconocido`, **o** discrepancia de fuentes sin resolver en campo crítico, **o** bandera forense invalidante, **o** checklist fallido |
| `atractiva` | p_final(E1) ≥ 0,55 **y** exceso de rentabilidad anual esperado frente a VWCE ≥ +5 pp **y** pérdida en escenario bajista ≤ 50 % **y** ninguna bandera forense grave |
| `no_atractiva` | p_final(E1) ≤ 0,40, **o** el DCF inverso no encuentra solución en rangos razonables, **o** el precio implica un driver con z > 3 frente a su tasa base |
| `neutral` | Todo lo demás |

## A2. Plataforma y empaquetado

- **Entorno principal:** Claude Code, local, como plugin.
- **Entorno secundario:** chat de claude.ai (modo degradado, sección A3.3). Allí solo se carga el skill: los agentes y los hooks del plugin se ignoran.
- **Distribución:** repositorio git privado del usuario, que funciona como marketplace propio. Durante el desarrollo se usa `claude --plugin-dir ./analisis-acciones`.
- **Nombres:** ni el plugin ni el skill pueden contener `claude` ni `anthropic`.

### Estructura de carpetas

```
analisis-acciones/
├── .claude-plugin/plugin.json          # name, version, description, userConfig {journal_dir}
├── skills/analizando-acciones/
│   ├── SKILL.md                        # orquestador, < 500 líneas
│   ├── references/                     # ver A13
│   ├── scripts/
│   │   ├── datos/   edgar.py precios.py macro.py damodaran.py cache.py
│   │   ├── motor/   dcf.py reverse_dcf.py excess_return.py ddm_fcfe.py
│   │   │            normalizado.py rnpv.py sotp.py escenarios.py
│   │   ├── router.py  tasas_base.py  tasas_base_build.py  forense.py
│   │   ├── agregar.py  gate.py  validar.py  red_team_externo.py
│   │   └── resolver.py  puntuar.py  baselines.py
│   ├── assets/
│   │   ├── config.yaml                 # parámetros versionados (ver A6.9)
│   │   ├── base_rates.csv  bio_pos_2011_2020.csv  sic_rutas.csv
│   │   └── schemas/  datapack  analista  objeciones  ajustes  verdict  (.schema.json)
│   ├── tests/                          # pytest, incluye tests dorados (A14)
│   └── evals/                          # evals del skill (A14)
├── agents/   datos.md  analista-fundamental.md  forense.md  red-team.md  juez.md
├── commands/ analizar.md  resolver-diario.md  macro-semanal.md
├── hooks/hooks.json
└── requirements.txt
```

### Frontmatter del `SKILL.md`
Solo seis campos: `name`, `description`, `license`, `compatibility`, `metadata`, `allowed-tools`. Cualquier otro campo hace fallar la subida a claude.ai. La `description` va en tercera persona, dice cuándo usar el skill y es explícita y algo insistente (p. ej. "Use when the user asks to analyze, value or evaluate a single stock or ticker…").

El flujo crítico va en los primeros 5.000 tokens del `SKILL.md`, porque tras una autocompactación Claude Code solo vuelve a cargar esa parte.

### Rutas y secretos
- **Ejecuciones:** `${journal_dir}/runs/<TICKER>/<YYYY-MM-DD>/`. Aquí van todos los artefactos de cada análisis.
- **Diario:** `${journal_dir}/diario/predicciones.jsonl`, append-only. `journal_dir` es un repositorio git privado del usuario.
- **Caché de datos:** `${CLAUDE_PLUGIN_DATA}/cache/`. Nunca dentro de `${CLAUDE_PLUGIN_ROOT}`, que cambia con cada actualización.
- **Secretos:** `~/.config/analisis-acciones/.env`, con `SEC_USER_AGENT` ("Nombre email"), `FRED_API_KEY`, `GEMINI_API_KEY` (opcional) y `OPENROUTER_API_KEY` (opcional). Los scripts los cargan con `python-dotenv`.

## A3. Flujos

### A3.1 Modo completo
1. **Normalizar.** Extraer el ticker y comprobar que existe. Crear el directorio de la ejecución.
2. **Macro.** Si `macro_regime.json` en caché tiene más de 7 días, ejecutar `macro.py`.
3. **Datos (código).** `edgar.py`, `precios.py` y `damodaran.py` generan `datapack_base.json`.
4. **Datos (agente).** El subagente `datos` completa los huecos y escribe `datapack.json`. Lo valida `validar.py`.
5. **Código.** En este orden: `router.py` → `tasas_base.py` → sensibilidades macro (en `macro.py`) → `forense.py` → motor con caso mecánico y DCF inverso. Todo se escribe en `motor_inicial.json`.
6. **Fase ciega, en paralelo.** `analista-fundamental` con encuadre A, `analista-fundamental` con encuadre B y `forense` (cualitativo). Cada uno escribe su JSON. El orquestador calcula el SHA-256 de cada salida y lo guarda en `hashes.json` (salidas congeladas).
7. **Motor por analista.** `escenarios.py` convierte los escenarios de A y de B en distribuciones y probabilidades de E0 a E4 por analista.
8. **Red team.** Si existe una API key externa, `red_team_externo.py`; si no, el subagente `red-team`. Escribe `objeciones.json`.
9. **Juez.** Verifica cada objeción contra el datapack. Las válidas las traduce a cambios de inputs en `ajustes.json`. Si hay ajustes, ejecuta de nuevo el motor solo con ellos. Después redacta las razones, el mejor contraargumento y los criterios de invalidación en `juez.json`.
10. **Código.** `agregar.py` → `gate.py` → `verdict.json` → `validar.py` → línea en el diario → `resumen.md`.

### A3.2 Modo rápido
Pasos 1-5 igual, salvo que el agente de datos solo se lanza si falta un campo crítico. Paso 6 con **un único** analista y encuadre neutral. Paso 7 igual. Sin red team ni juez: las razones y el contraargumento los toma el orquestador de la salida del analista. Paso 10 igual. El diario registra `modo: rapido`.

### A3.3 Modo degradado (chat de claude.ai)
El orquestador detecta que no hay subagentes y sigue `references/claude-ai.md`:
- Fases en serie en un solo contexto, con un analista de encuadre neutral y después el red team.
- Datos: pide al usuario que suba un `datapack.json` generado en local. Si no lo hay, usa búsqueda web y marca cada cifra con fuente y fecha.
- Motor: se ejecuta con code execution si está disponible; si no, el veredicto es `no_analizable`.
- Salida con `modo: degradado` e `independencia: false`. Se puntúa aparte.

## A4. Agentes

Reglas comunes a todos los agentes:
- Escriben su salida en `runs/<TICKER>/<fecha>/` como JSON validado por su esquema.
- Devuelven al orquestador solo la ruta del archivo y un resumen de tres líneas.
- Los analistas, el forense, el red team y el juez llevan `omitClaudeMd: true`.

| Agente | Modelo por defecto | `tools` | `disallowedTools` |
|---|---|---|---|
| datos | `sonnet` | Bash, WebSearch, WebFetch, Read, Write, Glob | — |
| analista-fundamental | `sonnet` (configurable a `opus`) | Read, Glob, Grep, Write | WebFetch, WebSearch, Bash, mcp__* |
| forense | `sonnet` | Read, Glob, Grep, Write | WebFetch, WebSearch, Bash, mcp__* |
| red-team (respaldo) | `sonnet` | Read, Glob, Grep, Write | WebFetch, WebSearch, Bash, mcp__* |
| juez | `opus` | Read, Glob, Grep, Write, Bash | WebFetch, WebSearch, mcp__* |

El Bash del juez queda limitado por hook a `python …/scripts/(motor/escenarios|agregar|gate).py`.

### A4.1 `datos`
- **Entrada:** `datapack_base.json` y la lista de campos `desconocido`.
- **Tarea:** completar los huecos con fuentes primarias, en este orden de preferencia: filings en SEC (10-K, 10-Q, 20-F, 6-K), web de relación con inversores del emisor, comunicados de resultados y, por último, prensa financiera.
- **Qué busca:**
  - Últimos datos trimestrales (sobre todo de emisores con 20-F).
  - Guidance vigente.
  - Ingresos por segmento y por geografía/moneda.
  - Cambios de auditor, de políticas contables o de factores de riesgo.
  - Hechos materiales de los últimos 90 días.
  - En bancos: morosidad, coste del riesgo, CET1 y crecimiento de préstamos y depósitos.
- **Formato de cada cifra:** `{valor, unidad, moneda, fuente_url, fecha_dato, fecha_obtencion}`.
- **Si no encuentra un dato:** lo deja como `desconocido` con su causa. Nunca estima ni completa con conocimiento propio.
- **Contra inyección:** el texto de las páginas se resume en campos estructurados. No copia texto libre largo al datapack.
- **Salida:** `datapack.json`.

### A4.2 `analista-fundamental`
- **Entrada:**
  - `datapack.json`, que presenta primero las tasas base y luego los datos de la empresa.
  - `motor_inicial.json`.
  - `macro_regime.json` con las sensibilidades de la empresa.
  - `references/metodologia.md`.
  - `references/ruta-<ruta>.md` (solo la de su ruta).
  - `references/sesgos.md`.
  - El encuadre asignado por el orquestador.
- **Encuadres:**
  - **A:** "Construye el caso más sólido de por qué esta acción podría batir a VWCE, y luego asigna probabilidades honestas a los tres escenarios".
  - **B:** "Construye el caso más sólido de por qué esta acción podría quedarse por detrás de VWCE, y luego asigna probabilidades honestas a los tres escenarios".
  - **Neutral** (modo rápido): "Evalúa la acción".
- **Tarea:**
  1. Clasificar la empresa (tipología de Lynch) y escribir la narrativa en ≤ 5 frases.
  2. Identificar el moat: fuente entre las cinco de Morningstar y evidencia numérica (ROIC − WACC histórico, o ROE − Ke en bancos).
  3. Evaluar gestión y asignación de capital.
  4. Traducir la narrativa a drivers para tres escenarios (bajista, base, alcista) con las probabilidades que exige el esquema. Las probabilidades suman 1. El escenario bajista incluye la pérdida permanente posible.
  5. Para cada driver, citar su percentil frente a la tasa base (lo da `tasas_base.py`). Si un driver tiene z > 2, aportar evidencia específica o moderarlo.
  6. Leer el DCF inverso: qué expectativas descuenta el precio y por qué cree que están mal o bien.
  7. Definir el catalizador y su horizonte.
  8. Escribir un pre-mortem: "dentro de 12 meses la acción ha quedado un 30 % por detrás de VWCE; las tres causas más probables son…".
  9. Proponer la métrica clave de E4 y su valor en el escenario base.
- **Salida:** `analista_A.json` / `analista_B.json` / `analista_N.json`. Contiene drivers por escenario y probabilidades por escenario. **No contiene probabilidades de los eventos**, porque esas las calcula el código.

### A4.3 `forense`
- **Entrada:** `datapack.json` (con notas y extractos de filings que aporta el agente de datos) y la salida de `forense.py`.
- **Tarea:** interpretar las banderas cuantitativas y revisar las cualitativas:
  - cambio de auditor o salvedades;
  - operaciones con partes vinculadas;
  - cambios de políticas contables;
  - peso creciente de métricas "ajustadas";
  - deuda fuera de balance;
  - nuevos factores de riesgo.

  Clasifica cada bandera como `informativa`, `grave` o `invalidante`.
- **Salida:** `forense.json`.

### A4.4 `red-team` (respaldo de `red_team_externo.py`)
- **Entrada:** `datapack.json`, `motor_inicial.json`, las salidas congeladas de los analistas y las probabilidades por analista, y `references/red-team.md`.
- **Tarea:** encontrar los errores que más moverían el resultado. Cada objeción tiene:
  - `tipo`: `dato_erroneo`, `supuesto_implausible`, `riesgo_omitido` o `contradiccion_interna`;
  - `dato_ref`: el campo del datapack o del informe al que se refiere;
  - `prueba`: cómo verificarla;
  - `impacto_estimado` en el driver;
  - `severidad`.

  Además, el mejor argumento contrario a la tesis dominante y un pre-mortem propio.
- **Restricción:** toda objeción cita un `dato_ref`. Las objeciones sin referencia se descartan.
- **Salida:** `objeciones.json`.

### A4.5 `juez`
- **Entrada:** todo lo anterior y `references/juez.md`.
- **Tarea:**
  1. Para cada objeción, verificarla contra el datapack y marcarla `validada` o `rechazada`, con el motivo y la referencia.
  2. Una objeción validada que cambia un input se convierte en una entrada de `ajustes.json` (driver, escenario, valor anterior, valor nuevo, motivo).
  3. Si hay ajustes, ejecutar `escenarios.py --ajustes`.
  4. Escribir las 3 razones principales, el mejor contraargumento y los criterios de invalidación (dato, umbral y efecto esperado, p. ej. "si el ROE del T1 cae por debajo del 20 %, p(E1) → < 0,45").
  5. Documentar los desacuerdos entre A y B sin resolverlos artificialmente.
- **Restricciones:**
  - No fija ninguna probabilidad: las calculan `escenarios.py` y `agregar.py`.
  - Para rechazar una objeción o una opinión minoritaria, cita un dato.
- **Salida:** `juez.json` y `ajustes.json`.

## A5. Hooks (`hooks/hooks.json`, a nivel de plugin)

1. **PreToolUse**, matcher `WebFetch|WebSearch|Bash|mcp__.*`. Si `agent_type` es `analista-fundamental`, `forense` o `red-team`, salir con código 2 (bloqueo). Si es `juez` y el comando Bash no coincide con la lista permitida, salir con código 2.
2. **PreToolUse**, matcher `Read|Glob|Grep`. Para los agentes anteriores, bloquear rutas fuera de `runs/<TICKER>/<fecha>/` y de `references/`. Durante la fase ciega, bloquear además la lectura de `analista_*.json` ajenos: el analista A no puede leer `analista_B.json` y viceversa.
3. **SubagentStop.** Ejecutar `validar.py` sobre el archivo de salida del agente. Si no valida, salir con código 2 para que el agente lo corrija.
4. **PostToolUse**, matcher `*`. Añadir `{ts, agent_type, tool, args_resumidos}` a `runs/.../traza.jsonl`.

Los hooks se implementan en `scripts/hooks/*.py`, que leen el JSON de la entrada estándar. Antes de escribir las reglas, verificar el valor exacto de `agent_type` en agentes de plugin (A16).

## A6. Módulos Python

**Stack:**
- Python ≥ 3.11, gestionado con `uv`.
- `numpy`, `scipy`, `pandas`, `requests`, `requests-cache`, `yfinance` (versión fijada), `edgartools`, `jsonschema`, `pyyaml`, `python-dotenv`, `xlrd`/`openpyxl`, `pytest`.
- Opcional: `google-genai` (Gemini).

**Reglas comunes:**
- Todos los scripts son CLI (`argparse`), leen y escriben JSON y son deterministas: Monte Carlo con semilla fija.
- Errores con mensajes claros, sin fallos silenciosos.

### A6.1 Datos
- **`cache.py`**
  - Caché en disco con TTL por fuente: companyfacts 24 h, precios 12 h, Damodaran 30 días, macro 7 días.
  - Token bucket de EDGAR a ≤ 8 peticiones por segundo.
  - Backoff exponencial para yfinance.
- **`edgar.py`**
  - CIK a partir del ticker (`company_tickers.json`), `submissions` y `companyfacts`.
  - Taxonomía `us-gaap` o `ifrs-full` según el emisor.
  - Deduplicar por `end`/`fy`/`fp`/`form` y quedarse con la última presentación.
  - Extrae 10 años (o los disponibles) de:
    - ingresos, beneficio operativo, beneficio neto, flujo de caja operativo, capex, D&A, SBC;
    - acciones diluidas, deuda total, caja, patrimonio, cuentas a cobrar, inventario, goodwill, activos totales, gasto por intereses, dividendos y recompras;
    - en bancos: préstamos, depósitos, provisiones, patrimonio tangible e ingresos por intereses netos.
  - Código SIC.
  - Usa `edgartools` si soporta bien la taxonomía `ifrs-full`; si no, llamadas directas a la API.
- **`precios.py`**
  - Diarios ajustados de 5 años de la acción y de `VWCE.DE`, y FX hacia EUR.
  - Capitalización, dividendos y retornos en EUR.
  - Volatilidad relativa frente a VWCE a 1 y 3 años, correlación y momentum 12-1.
- **`damodaran.py`**
  - Descarga y cachea de `pages.stern.nyu.edu/~adamodar/pc/datasets/`: ERP implícita, primas de riesgo país, betas, márgenes, ROIC y múltiplos por sector (versiones de EE. UU., Europa, emergentes y global).
  - Hace el mapeo de sector a industria de Damodaran.
- **`macro.py`**
  - **Régimen semanal:**
    - FRED: DGS10, DGS2, DGS3MO, BAA10Y, BAMLH0A0HYM2 y tipos de cambio (DEXUSEU, DEXBZUS…).
    - ECB Data Portal: €STR y rendimiento a 10 años del área euro (SDMX 2.1).
    - Damodaran: ERP.
  - **Etiquetas por reglas** (umbrales en `config.yaml`):
    - Tipos: `subiendo` / `bajando` / `estables`, según el cambio del 10 años en 26 semanas, ±25 pb.
    - Crédito: `relajado` / `normal` / `tenso`, según el percentil a 10 años del spread HY (< 30 / 30-70 / > 70).
    - Curva: invertida si 10a − 2a < 0.
  - **Por empresa** (subcomando `sensibilidades`):
    - Beta de los retornos semanales a 3 años frente al cambio del DGS10 y frente a la divisa relevante.
    - Porcentaje de ingresos por moneda (del datapack).
    - Deuda a tipo variable y vencimientos a 24 meses.

### A6.2 `router.py`
Asigna la ruta con `assets/sic_rutas.csv` y reglas (ver A8). Salida: `{ruta, motivo, confianza}`. Si la confianza es baja, el orquestador pide confirmación al analista: puede mantener la ruta o proponer otra con un dato que lo justifique, y la decisión final la toma el código con una regla documentada.

### A6.3 `tasas_base.py` y `tasas_base_build.py`
- **`tasas_base.py`**
  - Para cada driver propuesto (crecimiento de ventas a 3 y 5 años, margen operativo, ROIC/ROE), calcula su percentil y su z frente a la clase de referencia de `base_rates.csv` (por tamaño de ventas y sector).
  - Banderas: z > 2 → `requiere_evidencia_excepcional`; z > 3 → `casi_imposible_organicamente`.
  - Calcula el valor encogido: estimación = media + k_métrica × (observado − media), con los `k` de `config.yaml` (iniciales: crecimiento de ventas 0,3; margen operativo 0,6; ROIC/ROE 0,6; margen bruto 0,8).
- **`tasas_base_build.py`**
  - Construye `base_rates.csv` a partir de EDGAR `frames` (desde ~2009) para cubrir las clases de tamaño sin datos publicados: 5-10 mil M$, 10-50 mil M$ y más de 50 mil M$.
  - Incluye empresas deslistadas cuando estén en frames.
  - Marca la columna `fuente` (`mauboussin_2026` | `edgar_frames_calc`).
- **Contenido inicial de `base_rates.csv`:** ver A9.

### A6.4 Motor (`motor/`)
Todas las funciones devuelven valor por acción, puente de valor y supuestos usados.
- **`dcf.py`**
  - FCFF a 10 años: crecimiento de ingresos → margen operativo → ratio ventas/capital (reinversión) → impuestos.
  - Valor terminal con g ≤ Rf y ROIC terminal → WACC salvo moat documentado.
  - WACC con Rf de la moneda, ERP + CRP de Damodaran, beta sectorial reapalancada y coste de deuda por rating sintético (cobertura de intereses).
- **`reverse_dcf.py`**
  - Resuelve con `scipy.optimize.brentq`, en este orden:
    1. el crecimiento de ingresos implícito en [−20 %, 60 %], con márgenes del escenario base;
    2. el margen implícito en [0 %, 60 %];
    3. los años de ventaja competitiva implícitos (búsqueda entera, 1-40).
  - En bancos resuelve el ROE implícito sostenido.
  - Sin raíz → `sin_raiz: true`.
  - Devuelve además el percentil del valor implícito en la tasa base.
- **`excess_return.py`** (bancos): valor del patrimonio = patrimonio actual + VP de (ROE − Ke) × patrimonio, durante un periodo explícito y con valor terminal. Incluye también P/BV teórico = (ROE − g)/(Ke − g).
- **`ddm_fcfe.py`** (bancos, contraste):
  - DDM con g = (1 − payout) × ROE.
  - FCFE = beneficio neto − Δactivos ponderados por riesgo × ratio de capital objetivo.
- **`normalizado.py`** (cíclicas): margen operativo medio de 7-10 años × ingresos actuales, y después DCF.
- **`rnpv.py`** (biotech):
  - Por activo: ventas pico × probabilidad acumulada de aprobación (tabla BIO por fase y área), con descuento.
  - Más caja neta y menos VP de los gastos generales.
  - Encoge hacia la media de la tabla las celdas con n < 100 y limita la transición de solicitud a aprobación al 95 %.
- **`sotp.py`** (holdings): suma de partes por segmento (múltiplo o DCF por segmento) menos deuda y costes del holding.
- **`escenarios.py`**
  - **Entrada:** drivers y probabilidades por escenario de un analista, más `ajustes.json` opcional.
  - **Pasos:**
    1. Valor V_i por escenario, con el método de la ruta. En la ruta cíclica, si el analista da `crecimiento_ingresos`, se usa el DCF de 10 años con el margen convergiendo al normalizado.
    2. La diferencia entre precio y valor se cierra en T_conv = 3 años (`config.yaml`); aparte, una acción a su valor rinde en media (aritmética) lo mismo que VWCE. La diferencia que entra en la simulación se satura de forma suave en ~2× (`tope_desviacion`): un DCF que contradice al mercado por 4× es más probable que esté equivocado. Con T_conv = 5 el veredicto atractiva quedaba fuera de alcance, por eso se mantiene en 3.
    3. Rentabilidad de VWCE esperada = Rf EUR + ERP (Damodaran).
    4. Monte Carlo de 100.000 trayectorias mensuales con semilla fija y ruido t de Student (ν = 4). Cada trayectoria sigue, con probabilidad k = 0,4, un escenario del analista (según p_i) y, con 1 − k, el escenario neutral (V = P0). La rentabilidad relativa frente a VWCE usa la volatilidad relativa histórica en EUR; el precio, la volatilidad absoluta.
    5. **Coherencia:** E0-E3, los percentiles y el exceso esperado salen de esas mismas trayectorias. No se encoge cada evento por separado (eso producía, p. ej., 28 % de batir a VWCE junto a 81 % de caer un 30 % y un p95 negativo). *Cambio de noviembre de 2026 respecto a la versión inicial, a petición del usuario.*
  - **Salida por analista:**
    - p(E0), p(E1), p(E2), p(E3) de la mezcla, y por separado las del modelo y las del escenario neutral;
    - percentiles p5/p50/p95 (y cuantiles 1-99) de la rentabilidad relativa a 12 meses;
    - cordura: si el precio queda a más de 2× del rango de valores de los escenarios, aviso (o bloqueo, según `config.yaml`);
    - exceso de rentabilidad anual esperado;
    - pérdida en el escenario bajista;
    - p(E4) = suma de p_i de los escenarios cuya métrica E4 ≥ el valor base.

### A6.5 `forense.py`
Calcula métricas y banderas con umbrales en `config.yaml`:

| Métrica | Bandera grave (inicial) |
|---|---|
| Flujo de caja operativo / beneficio neto (media de 3 años) | < 0,8 |
| Devengos: (BN − FCO) / activos medios | > 10 % |
| Crecimiento de cuentas a cobrar − crecimiento de ingresos | > 10 pp durante 2 años |
| Crecimiento de inventario − crecimiento de ingresos | > 10 pp durante 2 años |
| SBC / ingresos | > 10 % |
| Dilución anual de acciones | > 3 % |
| Goodwill / activos | > 40 % y creciente |
| Cobertura de intereses (EBIT / intereses) | < 3 |
| Bancos: morosidad, coste del riesgo, CET1 | Tendencia adversa de 2 años o CET1 < requisito + 1 pp |

Las banderas `invalidante` las asigna el agente `forense` (p. ej. opinión de auditoría con salvedades, reexpresión de cuentas).

### A6.6 `agregar.py`
- Por evento: p_agg = media de p_A y p_B (mezcla de sus distribuciones, que conserva la coherencia entre eventos). En modo rápido o degradado: p_agg = p_N.
- El encogimiento hacia la tasa base ya va dentro de cada distribución (paso 4 de `escenarios.py`): p_final = p_agg. La tasa base es la p(E1) del escenario neutral (`tasa_base_tipo: calculada`; ≈ 0,45 con volatilidad relativa del 25 %). E3 y E4 se limitan a [0,05; 0,95].
- Percentiles de la rentabilidad relativa: los de la mezcla de A y B, no la media de percentiles.
- `dispersion` = |p_A − p_B| por evento; se reporta como señal de desacuerdo.
- Aplica las reglas de veredicto de A1.

### A6.7 `gate.py`
Checklist (adaptado de la sección 8 del documento metodológico). Cualquier fallo → `no_analizable`, con la lista de fallos.

1. Campos críticos de la ruta con fuente y fecha, y sin `desconocido`.
2. Discrepancia entre EDGAR y la fuente secundaria ≤ 2 % en ingresos, beneficio neto y acciones, o resuelta a favor de EDGAR.
3. Ruta dentro del alcance.
4. Escenarios con probabilidades que suman 1 y escenario bajista con pérdida explícita.
5. DCF inverso ejecutado.
6. Pre-mortem presente.
7. Criterios de invalidación presentes (≥ 2).
8. Mejor contraargumento presente (modo completo).
9. Ninguna bandera forense `invalidante`.
10. El balance sobrevive al escenario bajista: cobertura de intereses > 1,5 en el bajista; en bancos, CET1 sobre el requisito.
11. Datos de precio con antigüedad ≤ 3 días.
12. Cordura del modelo: el precio no queda a más de 2× del rango de valores de los escenarios. Por defecto es un aviso visible en el resumen; con `cordura.bloquea: true` es un fallo y el flujo salta red team y juez.

### A6.8 Otros
- **`validar.py`:** valida cualquier artefacto contra su esquema de `assets/schemas/`.
- **`red_team_externo.py`:**
  - Envía a Gemini (`GEMINI_API_KEY`, modelo en `config.yaml`) o a OpenRouter un prompt fijo (`references/red-team.md`) con el datapack, la salida del motor y los informes congelados.
  - Exige salida en el esquema `objeciones` y guarda la respuesta **en bruto**.
  - Si no hay clave → devuelve `no_disponible` y el orquestador lanza el subagente `red-team`.
  - Registra el modelo usado.
- **`baselines.py`:** calcula para cada análisis:
  - **B0:** la tasa base, p = 0,45.
  - **B2 (momentum 12-1 frente a VWCE):** 0,55 si es superior, 0,40 si es inferior.
  - **B3 (valor):** tercil de EV/EBIT, o P/BV-ROE en bancos, frente al sector de Damodaran. 0,55 si es el más barato, 0,45 si es el medio, 0,40 si es el más caro.
  - **B1** (prompt único): en modo completo, el orquestador lanza un subagente `analista-fundamental` adicional con encuadre neutral **sin** red team ni juez, y `escenarios.py` + `agregar.py` le calculan las probabilidades.
- **`resolver.py`:** recorre el diario, resuelve los eventos vencidos con precios y filings, y aplica las cláusulas de anulación. Python puro, ejecutable con cron.
- **`puntuar.py`:**
  - Log score (p limitada a [0,02; 0,98]) y Brier por evento, modo y baseline.
  - Brier skill score frente a B0.
  - Pendiente de calibración: regresión logística del resultado sobre logit(p).
  - Comparación por pares con Diebold-Mariano + corrección HLN y varianza HAC con h−1 retardos.
  - Informe trimestral en `diario/informes/`.

### A6.9 `assets/config.yaml` (valores iniciales)

```yaml
version: 1
modelos: {datos: sonnet, analista: sonnet, forense: sonnet, red_team_fallback: sonnet, juez: opus}
red_team_externo: {proveedor: gemini, modelo: "<configurar>", activo: true}
eventos: {E0_meses: 6, E1_meses: 12, E2_meses: 36, E3_caida: -0.30, benchmark: VWCE.DE, moneda: EUR}
agregacion: {tasa_base_exceso: 0.45, k: 0.4, clip_E3_E4: [0.05, 0.95]}
veredicto: {atractiva_p_E1: 0.55, atractiva_exceso_pp: 5, atractiva_max_perdida_bear: 0.50, no_atractiva_p_E1: 0.40, z_no_atractiva: 3}
escenarios: {T_conv_anios: 3, mc_sims: 100000, t_nu: 4, semilla: 42}
tasas_base_k: {crecimiento_ventas: 0.3, margen_operativo: 0.6, roic_roe: 0.6, margen_bruto: 0.8}
forense: {fco_bn_min: 0.8, devengos_max: 0.10, cxc_gap_pp: 10, inv_gap_pp: 10, sbc_max: 0.10, dilucion_max: 0.03, goodwill_max: 0.40, cobertura_min: 3}
macro: {tipos_umbral_pb: 25, tipos_ventana_sem: 26, hy_percentiles: [30, 70]}
datos: {discrepancia_max: 0.02, precio_max_dias: 3}
```

## A7. Fuentes de datos

| Necesidad | Primaria | Respaldo | Notas |
|---|---|---|---|
| Fundamentales EE. UU. | EDGAR companyfacts `us-gaap` | FMP gratis (250 llamadas/día, solo EE. UU.), Finnhub gratis | User-Agent obligatorio; ≤ 10 req/s |
| ADR / emisores extranjeros (20-F) | EDGAR companyfacts `ifrs-full` (anual) | Agente de datos: comunicados 6-K e IR; yfinance | Los trimestrales suelen no estar en XBRL; vigilar moneda (p. ej. BRL) y escala |
| Europeas sin registro SEC | Informes ESEF del emisor (agente de datos) | yfinance | Cobertura menor: más `no_analizable` |
| Precios, capitalización, dividendos, FX | yfinance con caché | Finnhub; FRED para FX | Fijar la versión de yfinance |
| Tipos, spreads, FX | FRED (API key gratis) | — | |
| Tipos del área euro | ECB Data Portal (SDMX 2.1) | — | |
| ERP, CRP, betas, márgenes y múltiplos por sector | Damodaran (.xls) | — | Actualización anual (última completa: 9-ene-2026) |
| Tasas base | `base_rates.csv` (A9) | — | |
| Probabilidades clínicas | BIO/Informa/QLS 2011-2020 | — | |

**Política de datos faltantes:**
- Cada cifra lleva fuente y fecha.
- Lo que falta se marca `desconocido` con su causa (`source_down`, `rate_limited`, `not_covered`, `stale`). Nunca se imputa en silencio.
- Ingresos, beneficio neto y acciones se verifican cruzando dos fuentes; si difieren más del 2 %, prevalece EDGAR y se registra la discrepancia.
- Comprobar siempre moneda y escala (miles, millones, ratio de ADR).

## A8. Router sectorial (alcance v1)

| Ruta | Detección | Método principal | Contraste | Métrica E4 |
|---|---|---|---|---|
| `general` | Por defecto | DCF FCFF + DCF inverso | Múltiplos frente al sector de Damodaran | Crecimiento de ingresos |
| `crecimiento_perdidas` | EBIT < 0 en 2 de los últimos 3 años, o crecimiento de ventas > p90 de su clase | DCF desde ingresos (crecimiento → margen objetivo → ventas/capital) con probabilidad de fracaso explícita en el escenario bajista | DCF inverso | Crecimiento de ingresos |
| `ciclica` | SIC de materiales, energía, automóvil, semiconductores, o desviación típica del margen operativo de 10 años > umbral | DCF con margen normalizado de 7-10 años | Múltiplo sobre beneficio normalizado | Crecimiento de ingresos |
| `banco_credito` | SIC 6000-6199 (incluye fintech con licencia bancaria, p. ej. NU) | Excess return + P/BV-ROE | DDM / FCFE | ROE |
| `biotech_precomercial` | SIC 2834/2836 e ingresos de producto < 50 M$ | rNPV por activo | — | Hito clínico (lectura de fase) |
| `holding` | ≥ 3 segmentos materiales (> 15 % de ingresos cada uno) en negocios distintos, o holding declarada | Suma de partes | — | Crecimiento de ingresos |
| `fuera_de_alcance` | REIT/SOCIMI (SIC 6798), aseguradoras (SIC 6300-6411), SPAC, fondos/ETF, empresas en concurso, menos de 2 años de estados financieros | — | — | Veredicto `no_analizable` |

**Precedencia entre rutas.** `fuera_de_alcance`, `banco_credito`, `biotech_precomercial` y `holding` siguen una prioridad estricta en ese orden. Entre `crecimiento_perdidas`, `ciclica` y `general`, una candidata de fuerza alta gana a una de fuerza media, y la prioridad (en ese orden) solo desempata a igual fuerza. Una alternativa más débil que la elegida no obliga a consultar al analista (confianza media); un conflicto entre candidatas de fuerza igual o mayor sí (confianza baja). A fuerza media, `ciclica` va antes que `crecimiento_perdidas` (un crecimiento puntual sobre el p90 es peor evidencia que un sector cíclico). *Cambio de noviembre de 2026: NVDA y Freeport, cíclicas claras, caían en `crecimiento_perdidas` por superar el p90 de crecimiento por décimas; Valero (refinería) por un crecimiento de ventas que sigue al crudo.*

## A9. Tasas base: contenido inicial

**Crecimiento compuesto de ventas a 5 años**, empresas de EE. UU. con ventas iniciales de 2-5 mil M$, 1950-2025, n = 19.264 (Mauboussin y Callahan, "Bayes and Base Rates 2.0", 13-may-2026):

| Muestra | Media | Desviación típica |
|---|---|---|
| Total, nominal | 6,9 % | 11,1 % |
| Total, real | 3,7 % | 10,6 % |
| IT | 6,1 % | 13,3 % |
| Software y servicios | ~5,1-5,4 % | 14,7 % |

Verificar el valor de software en el PDF al transcribir. Transcribir también la tabla por décadas.

**Resto de clases de tamaño y métricas:** calcularlas con `tasas_base_build.py`.

**Probabilidades clínicas (BIO 2011-2020, 12.728 transiciones):**
- Fase I→II: 52,0 %. Fase II→III: 28,9 %. Fase III→solicitud: 57,8 %. Solicitud→aprobación: 90,6 %.
- Probabilidad de aprobación desde Fase I: 7,9 %, con rango por área de 3,6 % (urología) a 23,9 % (hematología).
- Transcribir la tabla completa por área, tipo de fármaco y biomarcadores a `bio_pos_2011_2020.csv` desde https://go.bio.org/rs/490-EHZ-999/images/ClinicalDevelopmentSuccessRates2011_2020.pdf

**Tasa base de "batir a VWCE":** 0,45 para todos los horizontes, marcada `heuristica`. `tasas_base_build.py` la recalcula más adelante con un universo que incluya deslistadas.

## A10. Diario de predicciones

`diario/predicciones.jsonl`, append-only. Cada línea incluye `hash_prev` (SHA-256 de la línea anterior). Las revisiones de un mismo ticker se registran como `updates` del mismo `id` de pregunta, no como preguntas nuevas.

Esquema (en YAML para legibilidad; se guarda como JSON):

```yaml
id: NU-2026-11-06-a
created_at: 2026-11-06T18:00:00Z
hash_prev: "sha256:…"
skill: {version: 0.1.0, hash_prompts: "sha256:…", hash_config: "sha256:…", modo: completo}
modelos: {analista: claude-sonnet-5-5, red_team: gemini-…, juez: claude-opus-5-5}
ticker: NU
ruta_sectorial: banco_credito
input_snapshot:
  precio: {valor: , moneda: USD, fuente: yfinance, ts: }
  fx_eur: {valor: , fuente: , ts: }
  fuentes: [{url: , retrieved_at: , published_at: }]
  campos_desconocidos: [{campo: , causa: }]
veredicto: atractiva | neutral | no_atractiva | no_analizable
motivo_no_analizable: null
valoracion:
  metodo: excess_return
  escenarios: [{nombre: bajista, p: , valor: , drivers: {}, percentiles_tasa_base: {}}]
  reverse_dcf: {driver: , valor: , percentil: , sin_raiz: false}
  exceso_anual_esperado_pp: 
  rel_12m_p5_p50_p95: []
  perdida_escenario_bajista: 
agregacion: {p_A: {}, p_B: {}, dispersion: {}, tasa_base: 0.45, tasa_base_tipo: heuristica, k: 0.4}
preguntas:
  - {qid: E0, texto: "RT(NU)-RT(VWCE.DE) EUR > 0, 2026-11-06→2027-05-06", p: , resolve_date: , fuente_resolucion: "yfinance cierres ajustados", anular_si: [opa, delisting, escision, sin_datos]}
  - {qid: E1, …}
  - {qid: E2, …}
  - {qid: E3, …}
  - {qid: E4, texto: "ROE FY2027 (20-F) ≥ X", p: , …}
razones: [ , , ]
mejor_contraargumento: 
criterios_invalidacion: [{dato: , umbral: , efecto: }]
red_team: {fuente: externo|claude, objeciones: [{objecion: , dato_ref: , validada: , ajuste: }]}
banderas_forenses: [{bandera: , nivel: }]
checklist: {pasa: true, fallos: []}
baselines: {B0: 0.45, B1: , B2: , B3: }
updates: []
resolucion: {}
```

La decisión real del usuario, su opinión previa y la marca de "operación por impulso" van en el diario de decisiones del Project "Portafolio", enlazado por `id`.

## A11. Esquemas JSON (`assets/schemas/`)
Definir con JSON Schema (draft 2020-12):
- **`datapack`:** tasas base, empresa, precios, macro, sensibilidades, segmentos y hechos recientes. Cada cifra con `{valor, unidad, moneda, fuente_url, fecha_dato, fecha_obtencion}` o `{desconocido: true, causa}`.
- **`analista`:** tipología, narrativa, moat (fuente y evidencia), gestión, escenarios[3] (con drivers, p y justificación por driver con percentil), lectura del DCF inverso, catalizador, pre-mortem[3] y métrica E4.
- **`objeciones`:** lista de objeciones con tipo, dato_ref, prueba, impacto_estimado y severidad; más mejor_contraargumento y pre-mortem.
- **`ajustes`:** lista de ajustes con driver, escenario, valor_anterior, valor_nuevo, objecion_ref y motivo.
- **`verdict`:** el esquema de A10.

## A12. Evaluación
- **Forward test:** cada análisis queda en el diario. `resolver.py` se ejecuta semanalmente con cron.
- **Métricas preregistradas:** log score de E1 (precio) y Brier de E4 (fundamental), por modo, frente a B0-B3.
- **Revisiones:**
  - Trimestral, con `puntuar.py`.
  - A los 18 meses, regla de decisión: el modo completo sigue siendo el predeterminado solo si no es peor que B1 en E1 y E4 y si las objeciones validadas del red team mueven p_final más de 0,03 en al menos el 20 % de los análisis. Si no se cumple, el modo rápido pasa a ser el predeterminado.
- **Recalibración:** con ≥ 100 eventos E1 resueltos, ajustar `k` y evaluar Platt scaling. Hasta entonces, valores fijos.
- **Backtests históricos:** solo para probar la fontanería (parsing, router, checklist, esquemas). Nunca se usan como medida de acierto.
- **Sondeo de memorización** antes de cualquier prueba histórica: preguntar al modelo, sin herramientas, el precio de cierre y la rentabilidad anual del ticker en una fecha concreta. Si acierta, ese ticker y periodo quedan excluidos.
- **Contrafactual:** invertir el signo de un driver clave en el datapack y comprobar que el veredicto cambia en la dirección esperada.

## A13. `references/`

| Archivo | Contenido (solo instrucciones operativas) | Lo lee |
|---|---|---|
| `metodologia.md` | Proceso de análisis destilado de la sección 3 del documento metodológico: negocio, moat, gestión, estados financieros, valoración, escenarios, riesgos. Checklist de la sección 8 (sin el bloque A). | Analistas, juez |
| `ruta-general.md`, `ruta-crecimiento-perdidas.md`, `ruta-ciclica.md`, `ruta-banco-credito.md`, `ruta-biotech.md`, `ruta-holding.md` | Método, drivers obligatorios, campos críticos, trampas típicas, banderas forenses específicas y métrica E4 de la ruta | Solo el analista y el forense de esa ruta |
| `sesgos.md` | Reglas operativas de la sección 6: base rate primero, pre-mortem, inversión, buscar desconfirmación, no extrapolar lo reciente, probabilidades granulares | Analistas, red team, juez |
| `red-team.md` | Formato de objeción, tipos, prohibición de objeciones sin `dato_ref`, plantilla de pre-mortem. También es el prompt de `red_team_externo.py` | Red team |
| `juez.md` | Procedimiento de verificación de objeciones, formato de ajustes y de criterios de invalidación | Juez |
| `esquemas.md` | Descripción de cada campo de los JSON | Todos |
| `claude-ai.md` | Procedimiento del modo degradado | Orquestador en claude.ai |
| `diario.md` | Eventos, cláusulas de anulación y uso de `resolver.py` y `puntuar.py` | Orquestador |

Los agentes no precargan el skill orquestador (campo `skills`); cada uno lee solo sus referencias. Los archivos de más de 100 líneas llevan índice al principio.

## A14. Pruebas
- **Tests unitarios** de todos los módulos.
- **Tests dorados del motor**, con los datos de entrada sacados de las fuentes:
  - DDM de ABN Amro = 30,87 €/acción (Damodaran, cap. 21: https://pages.stern.nyu.edu/~adamodar/pdfiles/val3ed/c21.pdf).
  - Excess return de Goldman Sachs = 166,24 $/acción con Ke 9,5 % y ROE 11,66 % (mismo capítulo, y https://pages.stern.nyu.edu/~adamodar/pdfiles/country/finsvce.pdf).
  - Valor normalizado de Toyota con margen medio del 7,33 %: usar el recálculo propio (≈ 4.718 ¥), no los 4.735 ¥ del artículo, que tiene un error aritmético (https://www.gurufocus.com/news/752576/valuation-how-to-value-cyclical-and-commodity-companies).
  - Del DCF inverso: recuperar el crecimiento usado para generar un precio sintético.
- **Tests de `escenarios.py`:** con la semilla fija, resultado idéntico; si todos los escenarios valen P0, p(E1) ≈ 0,5 menos el efecto de la diferencia de rentabilidad esperada.
- **Evals del skill** (formato de `skill-creator`, con `claude plugin eval`), al menos estas 4:
  1. Ticker de EE. UU. general.
  2. ADR con 20-F (NU).
  3. Ruta fuera de alcance (un REIT) → `no_analizable`.
  4. Ticker inexistente.

  Se comprueban la activación del skill, la validez del JSON, que la fase ciega no tenga lecturas cruzadas (revisando la traza) y el modo degradado.

## A15. Orden de construcción
1. `datos/` + `cache.py` + esquemas + `validar.py`.
2. `motor/` con los tests dorados.
3. `router.py` + `tasas_base*.py` + `forense.py` + `macro.py`.
4. `agregar.py` + `gate.py` + diario + `resolver.py` + `puntuar.py` + `baselines.py`.
5. Modo rápido de extremo a extremo (agente `datos` + un `analista-fundamental`). Desde aquí ya se acumula forward test.
6. Agentes `forense`, `red-team` y `juez`, hooks y modo completo.
7. `red_team_externo.py`.
8. Modo degradado de claude.ai y empaquetado final.

## A16. Por verificar al construir (preguntar al usuario si algo falla)
- El valor exacto de `agent_type` que reciben los hooks para agentes de plugin (con o sin el prefijo `analisis-acciones:`).
- Que `tools`/`disallowedTools` se respeten en agentes de plugin (los campos `hooks`, `mcpServers` y `permissionMode` del frontmatter de agentes de plugin se ignoran).
- Si `edgartools` normaliza bien `ifrs-full` en emisores con 20-F; si no, llamadas directas a companyfacts.
- El estado de los bloqueos de yfinance y si conviene `yfinance-cache`.
- El límite real de uso del plan Pro: medir con `/status` el consumo de un análisis completo y bajar el juez a `sonnet` si no caben al menos 2 análisis completos por ventana de 5 horas.
- La API y los modelos gratuitos actuales de Gemini.
- Si un plugin instalado en la cuenta de claude.ai está disponible dentro de un Project concreto.
- El valor exacto de software y servicios en la tabla de Mauboussin 2026.

---

# PARTE B: JUSTIFICACIÓN

Contexto para quien construye. No se copia a prompts, SKILL.md ni references.

## B1. Principio de diseño
Los LLM producen **inputs auditables**: narrativa, drivers, escenarios, objeciones con referencia a datos y lectura de documentos. El código produce **los números y la decisión**: valoración, probabilidades, agregación, veredicto y checklist. Así una sola regla ataca cuatro problemas: la falsa precisión de promediar opiniones de un mismo modelo, la conformidad entre agentes, la contaminación por memoria del modelo y la complacencia con el usuario.

- La crítica a los marcos de trading con LLM recomienda usar el LLM como "interfaz auditable de información aguas arriba", con módulos independientes de calibración, riesgo y ejecución que tengan la decisión final (The Alpha Illusion, arXiv 2605.16895).
- No hay evidencia creíble de que los sistemas multiagente con LLM generen alfa en acciones individuales: en ventanas largas suelen perder o empatar con comprar y mantener (FINSABER, arXiv 2505.07078; Alpha Illusion). El valor defendible del plugin es la disciplina de proceso y la reducción de sesgos.

## B2. Por qué cinco roles LLM
El documento metodológico (sección 9.2) propone once agentes. Este diseño los reorganiza así:

| Agentes de la 9.2 | Dónde quedan | Por qué |
|---|---|---|
| Value, Quality, Growth, Contrarian | Un analista fundamental (drivers) + motor en código (DCF, DCF inverso, tasas base) | Son facetas de una sola valoración: el valor depende de crecimiento, márgenes, reinversión y riesgo. Separados producirían valoraciones con supuestos incompatibles. Contrarian = DCF inverso, que es cálculo. |
| Macro | Módulo de código semanal compartido + sensibilidades por empresa | El régimen macro es igual para todas las acciones en una fecha dada. La conciencia de régimen sí importa: las estrategias LLM resultaron demasiado conservadoras en mercados alcistas y demasiado agresivas en bajistas (FINSABER). |
| Historiador | `tasas_base.py` (clases de referencia de empresa) | Las tasas base son cuantificables. Las analogías macro elegidas por un LLM salen de su memoria, que recuerda precios e índices con precisión e ignora la orden de "no uses el futuro" (The Memorization Problem, arXiv 2504.14765). |
| Riesgo / técnico | Parte de `precios.py` + `escenarios.py`; el tamaño de posición, en el proyecto de cartera | El tamaño depende de la cartera, que el plugin no conoce. |
| Datos, Forense, Abogado del diablo, Sintetizador | Datos, Forense, Red team, Juez | Se mantienen, pero el juez no fija probabilidades. |

- Anthropic reporta que los sistemas multiagente gastan unas 15 veces más tokens que un chat, y que compensan en tareas amplias y paralelizables, no cuando comparten mucho contexto ("How we built our multi-agent research system", Anthropic Engineering, junio de 2025).
- Mejorar el modelo rinde más que duplicar el presupuesto de tokens. Por eso el juez va en Opus y el resto en Sonnet, que además es lo que cabe en el plan Pro.

## B3. Fase ciega, encuadres opuestos, una sola ronda de crítica
- **Votar supera a debatir.** En "Debate or Vote" (Choi et al., NeurIPS 2025, arXiv 2508.17536), el voto mayoritario explica la mayor parte de las mejoras que se atribuyen al debate, más rondas reducen la precisión y más agentes independientes la suben. En "The Cost of Consensus" (arXiv 2605.00914), la autocorrección aislada iguala o supera al debate en las 6 configuraciones probadas, con 2,1-3,4 veces menos tokens.
- **Conformidad.** Entre el 26 % y el 86 % de los agentes adoptan la respuesta mayoritaria; hasta el 70 % de los que tenían razón la abandonan; respuestas correctas presentes en el equipo se descartan con brechas de 6 a 32 pp. Todo esto se midió con modelos de 7-8B; en modelos frontera la magnitud es desconocida.
- **Errores correlacionados.** Cuando dos LLM fallan a la vez, coinciden en la misma respuesta errónea ~60 % de las veces, frente al ~33 % esperable por azar. La correlación es mayor dentro del mismo proveedor y entre los modelos más precisos (arXiv 2506.07962). Los prompts de persona no mueven el Brier: −0,001 y −0,002, no significativo (arXiv 2506.01578).
- **Consecuencia:** las salidas de los analistas se congelan, no hay rondas de réplica y las objeciones cambian inputs verificables. Los encuadres A/B existen para neutralizar el sesgo de aquiescencia y cubrir más argumentos, no para simular opiniones independientes: A y B cuentan como menos de dos votos efectivos.
- **Sesgo de aquiescencia:** pronóstico medio del 57 % cuando solo el 45 % de las preguntas resolvió "sí" (arXiv 2402.19379).

## B4. El código agrega y encoge hacia la tasa base
- En AIA Forecaster (arXiv 2511.07678), media, mediana y media recortada rinden parecido, y pedir a un LLM que sintetice los pronósticos funcionó peor que la media.
- Los LLM tienden a dar probabilidades cercanas a 0,5 y necesitan Platt scaling, que requiere historial de predicciones resueltas.
- En mercados líquidos, el LLM solo (Brier 0,126) pierde frente al mercado (0,111), pero la combinación con ~1/3 de peso para el LLM mejora a ambos (0,106).
- k = 0,4 es una analogía con ese 1/3: en una acción líquida, el precio es el pronosticador fuerte y su "predicción" de exceso de rentabilidad se aproxima a la tasa base. Es un parámetro versionado, no estimado.
- La media de log-odds no está probada específicamente en LLM, pero en AIA las agregaciones simples rinden parecido.
- La tasa base de 0,45 para "batir al índice" es heurística. Coherente con Bessembinder (2018): la mayoría de acciones individuales rinde menos que el mercado a lo largo de su vida.

## B5. Umbrales del veredicto y horizonte
- El usuario pidió un horizonte de 6-12 meses, preferiblemente también más largo. Por eso E1 (12 meses) es el evento principal, E0 (6 meses) el secundario y E2 (36 meses) recoge la tesis larga.
- Con b = 0,45 y k = 0,4, que p_final(E1) sea ≥ 0,55 exige p_agg ≥ 0,70. Es una barra deliberadamente alta: el núcleo del usuario ya es VWCE, así que "mantener / no hacer nada" es el resultado por defecto, y desviarse del índice requiere una ventaja clara.
- El +5 pp de exceso anual esperado cubre el error de estimación habitual del DCF y los costes de operar.
- La pérdida máxima del 50 % en el escenario bajista viene del principio de Marks: riesgo = pérdida permanente.

## B6. Por qué E4 (fundamental) importa tanto como E1
- El exceso de rentabilidad a 12 meses de una acción es casi ruido, y con 20-50 análisis al año no habrá significación estadística sobre E1 en años.
- Para una curva de calibración útil hacen falta unos 100 eventos por tramo, es decir, 300-500 eventos independientes. Las predicciones a 12 meses emitidas cada mes se solapan, así que el N efectivo se parece más al número de cohortes trimestrales no solapadas.
- E4 mide justo la habilidad que el analista dice tener (prever crecimiento, márgenes o ROE), resuelve en ≤ 12 meses y tiene menos varianza. Da señal de aprendizaje antes.

## B7. Router sectorial
- En bancos, el DCF de la empresa entera (FCFF/WACC) no sirve: la deuda es materia prima y la reinversión es capital regulatorio. Damodaran valora el patrimonio con DDM, FCFE, excess return y P/BV-ROE (Damodaran, cap. 21 y "Valuing financial service firms").
- En cíclicas, los múltiplos engañan: son mínimos en el pico y máximos en el valle. Se normaliza con el margen medio del ciclo (Damodaran, *The Little Book of Valuation*, vía GuruFocus).
- En biotech, la probabilidad de aprobación desde Fase I es del 7,9 %, y el paso de Fase II a III (28,9 %) es el cuello de botella (BIO 2021).
- REITs y aseguradoras quedan fuera de la v1 porque no se encontraron fuentes metodológicas primarias verificadas para FFO/AFFO/NAV ni para el float de aseguradoras.
- No existe una librería Python madura de valoración fundamental. El proyecto más cercano (stockvaluation_io) sigue el patrón "el LLM investiga, el código calcula" y excluye las financieras. Por eso el motor es propio.

## B8. Tasas base
- Mauboussin y Callahan (2026): elegir la clase de referencia es el problema principal, y estrechar a un sector no produce crecedores más rápidos que los que ya contiene la muestra total.
- El encogimiento hacia la media viene del Base Rate Book (2016): estimación = media + k × (observado − media), con k ≈ la persistencia de la métrica.
- Los valores iniciales de k (crecimiento 0,3; márgenes y ROIC 0,6-0,8) son heurísticas: los márgenes y el ROIC persisten más que el crecimiento de ventas.
- Las colas del crecimiento son gruesas; por eso el Monte Carlo usa una t de Student.
- Pedir "tasa base primero" es el único cambio de prompt con algo de señal en pronóstico (ΔBrier −0,016, débil; arXiv 2506.01578). Por eso el datapack presenta primero las tasas base.

## B9. Por qué solo el agente de datos accede a la web
- **Consistencia:** todos los agentes trabajan con las mismas cifras.
- **Seguridad:** el contenido descargado puede llevar instrucciones maliciosas, y los skills que traen datos de URLs externas tienen un riesgo particular (docs de Agent Skills).
- **Auditabilidad:** cada cifra tiene fuente y fecha.
- Bash se deniega a los analistas porque permite `curl` aunque WebFetch esté bloqueado.
- Los hooks a nivel de plugin son la segunda capa: los campos `hooks` del frontmatter de agentes de plugin se ignoran, y los hooks de settings o de plugin sí se ejecutan dentro de los subagentes y reciben `agent_type`.

## B10. Red team con otro modelo
- El red team es el rol donde la heterogeneidad de modelos tiene más sentido: su trabajo es encontrar errores que el modelo base no ve, y los errores entre familias están menos correlacionados.
- La evidencia de que mezclar modelos ayuda viene de benchmarks de razonamiento, no de finanzas, y los propios autores dicen que "no es una panacea". Por eso se usa con coste de céntimos (Gemini gratis u OpenRouter por uso) y no con una suscripción.
- La respuesta se guarda en bruto: si un subagente Claude la parafraseara, se perdería parte de la diversidad.
- Su aportación se mide (A12).

## B11. Complacencia con el usuario
- Reformular en un paso separado, donde el modelo que responde solo ve la pregunta neutral, reduce la complacencia mucho más que ordenar "no seas complaciente" (AISI, arXiv 2602.23971, cifras de un resumen).
- La interfaz de "solo ticker" hace esa reformulación por construcción, siempre que el orquestador no pase nunca el comentario del usuario a los subagentes.

## B12. Evaluación sin contaminación
- Los agentes de trading con LLM pierden entre el 50 % y el 72 % de su rentabilidad cuando se evalúan después de la fecha de corte de entrenamiento del modelo (Profit Mirage, arXiv 2510.07920).
- GPT-4o identifica la empresa en el 100 % de las earnings calls anonimizadas de Apple, Meta y Microsoft (The Memorization Problem).
- Lo que el modelo ya sabe de la empresa ("efecto distracción") pesa más que el look-ahead, sobre todo en empresas grandes (Glasserman y Lin, arXiv 2309.17322).
- Conclusión: solo el forward test mide habilidad. B1 (un solo prompt con los mismos datos) aísla si el multiagente aporta algo.

## B13. Plataforma
- Los plugins se cargan distinto según la superficie: en el chat de claude.ai solo se cargan skills, commands y MCP remotos; agentes, hooks, MCP locales y `bin/` se ignoran, y un `bin/` en la raíz impide la instalación (docs de plugins, "Platform support").
- claude.ai no tiene subagentes. Por eso existe el modo degradado y se puntúa aparte.
- `claude -p --bare` exige API key y no usa la suscripción Pro. Por eso los análisis son interactivos y solo `resolver.py` (Python puro) va en cron.
- Coste estimado, no medido, de un análisis completo: ~210-240k tokens de entrada (unos 1 $ a precio de API).

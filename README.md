# analisis-acciones

Plugin de Claude Code para analizar acciones individuales. Recibe un ticker y devuelve un análisis con veredicto (`atractiva`, `neutral`, `no_atractiva` o `no_analizable`), probabilidades de batir a VWCE en EUR, escenarios, mejor argumento contrario y criterios de invalidación. Cada predicción queda registrada en un diario para comprobar más adelante si acertó.

El plugin no conoce la cartera, el tamaño de posición ni la fiscalidad de quien lo usa. Esas decisiones se toman fuera, con el resultado del análisis.

> Herramienta de análisis y estudio personal. No es asesoramiento financiero.

## Cómo funciona

- **Código en Python** para lo que tiene fórmula: descarga de datos (SEC EDGAR, Yahoo Finance, FRED, BCE, Damodaran), valoración (DCF, DCF inverso, métodos para bancos, cíclicas, biotech y holdings), tasas base, simulación de escenarios, agregación, checklist y diario.
- **Cinco agentes** para lo que requiere juicio: datos, analista fundamental (con dos encuadres opuestos en modo completo), forense, red team y juez. Ninguno calcula probabilidades: las calcula el código con sus drivers.
- **Hooks** que impiden que los analistas accedan a internet o lean el trabajo de los demás, validan cada salida y dejan una traza.
- **Diario de predicciones** append-only con cadena de hashes, que se resuelve y se puntúa con el tiempo.

El diseño completo está en [`SPEC.md`](SPEC.md).

## Requisitos

- Claude Code (plan Pro o superior).
- [`uv`](https://docs.astral.sh/uv/): el plugin crea con él su propio entorno de Python 3.12 la primera vez que se usa (tarda alrededor de un minuto).
- En Windows, Git for Windows (Claude Code usa su bash para ejecutar los scripts).
- Claves y datos de acceso en `~/.config/analisis-acciones/.env`:

```
SEC_USER_AGENT=Nombre Apellido correo@ejemplo.com
FRED_API_KEY=tu_clave
```

`SEC_USER_AGENT` es tu nombre y email (EDGAR lo exige; no es una clave). `FRED_API_KEY` es gratuita en https://fredaccount.stlouisfed.org/apikeys

## Instalación

Desde Claude Code:

```
/plugin marketplace add inizub/analisis-acciones
/plugin install analisis-acciones@analisis-acciones
```

Al instalarlo te pide `journal_dir`: la carpeta donde se guardan las ejecuciones (`runs/`) y el diario (`diario/`). Si el repositorio es privado, Claude Code usa las credenciales de git de tu equipo.

Desde la terminal, en un solo paso y fijando el diario:

```
claude plugin install analisis-acciones --marketplace inizub/analisis-acciones --config journal_dir=C:/ruta/al/diario
```

Para actualizar: `claude plugin update analisis-acciones@analisis-acciones` (la actualización automática viene desactivada en marketplaces propios).

Durante el desarrollo, desde la carpeta del repositorio:

```
claude --plugin-dir .
```

## Uso

| Comando | Qué hace |
|---|---|
| `/analisis-acciones:analizar TICKER` | Análisis completo (dos analistas, forense, red team y juez) |
| `/analisis-acciones:analizar TICKER rapido` | Un solo analista, sin red team ni juez |
| `/analisis-acciones:resolver-diario [informe]` | Resuelve las predicciones vencidas y, con `informe`, escribe el informe trimestral |
| `/analisis-acciones:macro-semanal` | Actualiza el régimen macro |

También basta con pedirlo con naturalidad («analiza NU»). Del texto solo se usan el ticker y el modo: cualquier opinión que añadas se ignora y no llega a los agentes.

Cada análisis se guarda en `<journal_dir>/runs/<TICKER>/<fecha>/` con un `resumen.md` legible y un `verdict.json`, y añade una línea a `<journal_dir>/diario/predicciones.jsonl`.

`resolver.py` no usa ningún modelo, así que puede ir en una tarea programada semanal:

```
bash skills/analizando-acciones/scripts/py.sh ~/.cache/analisis-acciones resolver.py resolver --diario <journal_dir>/diario/predicciones.jsonl
```

## Estructura

```
.claude-plugin/        manifiesto del plugin y del marketplace
skills/analizando-acciones/
  SKILL.md             orquestador
  references/          instrucciones de los agentes por tarea y por ruta sectorial
  scripts/             datos, motor de valoración, router, tasas base, forense, macro, agregación,
                       checklist, diario, resolución, puntuación, hooks y control de la ejecución
  assets/              config.yaml, esquemas JSON, tasas base, probabilidades clínicas, mapeo SIC
  tests/               pytest
  evals/               evals del skill (claude plugin eval)
agents/                los cinco agentes
commands/              analizar, resolver-diario, macro-semanal
hooks/                 aislamiento, validación y traza
SPEC.md                especificación completa
```

## Pruebas

```
uv venv .venv --python 3.12
uv pip install -r requirements.txt --python .venv
.venv/Scripts/python -m pytest        # en macOS o Linux: .venv/bin/python -m pytest
```

Las evals ejecutan análisis reales y necesitan Bash, que `claude plugin eval` solo permite dentro del sandbox del sistema: en Windows hay que lanzarlas desde WSL2. Como las evals no leen tu `.env`, exporta las claves con el prefijo `EVAL_`:

```
EVAL_SEC_USER_AGENT="Nombre correo@ejemplo.com" EVAL_FRED_API_KEY=... \
claude plugin eval . --allow-tools Bash Write Edit WebFetch WebSearch --runs 1
```

## Decisiones de diseño

El porqué de los cambios hechos tras las primeras pruebas reales (qué falló, qué se decidió y qué alternativas se descartaron) está en [`docs/decisiones/`](docs/decisiones/README.md), junto con el registro de pruebas y las [limitaciones conocidas](docs/decisiones/limitaciones-conocidas.md).

## Estado

Versión 0.3.2. Construido según la sección A15 de `SPEC.md` (pasos 1 a 6 y 8). El red team externo (paso 7) no se usa: el red team lo hace siempre el subagente de Claude.

Limitaciones conocidas:

- Solo valora empresas que informan en USD o EUR; el resto da `no_analizable` con el motivo.
- Las tasas base calculadas con EDGAR no distinguen sector.
- El etiquetado de crédito usa el spread BAA10Y porque FRED solo ofrece tres años del spread high yield.

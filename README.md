# analisis-acciones

Plugin de Claude Code para analizar acciones individuales. Recibe un ticker y devuelve un análisis con veredicto (`atractiva`, `neutral`, `no_atractiva` o `no_analizable`), probabilidades, escenarios, mejor argumento contrario y criterios de invalidación. Cada predicción queda registrada en un diario para comprobar más adelante si acertó.

El plugin no conoce la cartera, el tamaño de posición ni la fiscalidad de quien lo usa. Esas decisiones se toman fuera, con el resultado del análisis.

> Herramienta de análisis y estudio personal. No es asesoramiento financiero.

## Cómo funciona

- **Código en Python** para lo que tiene fórmula: descarga de datos, valoración (DCF, DCF inverso, métodos para bancos, cíclicas y biotech), tasas base, simulación de escenarios, agregación y checklist.
- **Cinco agentes** para lo que requiere juicio: datos, analista fundamental (se ejecuta con dos encuadres opuestos), forense, red team y juez.
- **Hooks** que impiden que los analistas accedan a internet o lean el trabajo de los demás.
- **Diario de predicciones** que se resuelve y se puntúa con el tiempo.

El diseño completo está en [`SPEC.md`](SPEC.md).

## Requisitos

- Claude Code (plan Pro o superior).
- Python ≥ 3.11 y [`uv`](https://docs.astral.sh/uv/).
- Claves y datos de acceso:
  - `SEC_USER_AGENT`: tu nombre y email, por ejemplo `Nombre Apellido correo@ejemplo.com` (EDGAR lo exige; no es una clave).
  - `FRED_API_KEY`: gratuita, en https://fredaccount.stlouisfed.org/apikeys

Guárdalos en `~/.config/analisis-acciones/.env`:

```
SEC_USER_AGENT=Nombre Apellido correo@ejemplo.com
FRED_API_KEY=tu_clave
```

## Instalación

Desde Claude Code:

```
/plugin marketplace add TU-USUARIO/analisis-acciones
/plugin install analisis-acciones@analisis-acciones
```

Durante el desarrollo:

```
claude --plugin-dir ./analisis-acciones
```

Al instalarlo, indica la carpeta de tu repositorio del diario (`journal_dir`).

## Uso

| Comando | Qué hace |
|---|---|
| `/analizar TICKER` | Análisis completo |
| `/analizar TICKER rapido` | Versión más barata, para filtrar |
| `/resolver-diario` | Resuelve las predicciones vencidas |

Cada análisis se guarda en `<journal_dir>/runs/<TICKER>/<fecha>/` con un `resumen.md` legible y un `verdict.json`.

## Estructura

```
.claude-plugin/        manifiesto del plugin y del marketplace
skills/                skill orquestador, scripts, referencias, esquemas y tests
agents/                los cinco agentes
commands/              /analizar, /resolver-diario, /macro-semanal
hooks/                 bloqueos de herramientas y validación
SPEC.md                especificación completa
```

## Estado

En construcción. Orden de desarrollo en la sección A15 de `SPEC.md`.
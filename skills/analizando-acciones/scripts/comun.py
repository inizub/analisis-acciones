"""Utilidades comunes: rutas, configuración, secretos, E/S JSON y formato de cifras.

Todas las cifras del plugin usan el formato:
    {valor, unidad, moneda, fuente_url, fecha_dato, fecha_obtencion}
o, si faltan:
    {desconocido: true, causa}
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import yaml

DIR_SCRIPTS = Path(__file__).resolve().parent
DIR_SKILL = DIR_SCRIPTS.parent
DIR_ASSETS = DIR_SKILL / "assets"
DIR_SCHEMAS = DIR_ASSETS / "schemas"
RUTA_CONFIG = DIR_ASSETS / "config.yaml"
RUTA_ENV = Path.home() / ".config" / "analisis-acciones" / ".env"

CAUSAS_DESCONOCIDO = ("source_down", "rate_limited", "not_covered", "stale")


class ErrorDatos(Exception):
    """Error al obtener datos de una fuente. `causa` es una de CAUSAS_DESCONOCIDO."""

    def __init__(self, mensaje: str, causa: str = "source_down"):
        if causa not in CAUSAS_DESCONOCIDO:
            raise ValueError(f"Causa no válida: {causa}")
        super().__init__(mensaje)
        self.causa = causa


def cargar_config(ruta: Path | None = None) -> dict:
    with open(ruta or RUTA_CONFIG, encoding="utf-8") as f:
        return yaml.safe_load(f)


def cargar_env() -> None:
    """Carga ~/.config/analisis-acciones/.env sin sobrescribir variables ya definidas."""
    from dotenv import load_dotenv

    if RUTA_ENV.exists():
        load_dotenv(RUTA_ENV, override=False, encoding="utf-8-sig")


def variable_requerida(nombre: str) -> str:
    cargar_env()
    valor = os.environ.get(nombre, "").strip()
    if not valor:
        raise ErrorDatos(
            f"Falta la variable {nombre}. Defínela en {RUTA_ENV}.", causa="source_down"
        )
    return valor


def user_agent_sec() -> str:
    """SEC_USER_AGENT transliterado a ASCII (las cabeceras HTTP no admiten, p. ej., 'ñ')."""
    import unicodedata

    ua = variable_requerida("SEC_USER_AGENT")
    ascii_ua = unicodedata.normalize("NFKD", ua).encode("ascii", "ignore").decode("ascii")
    ascii_ua = " ".join(ascii_ua.split())
    if "@" not in ascii_ua:
        raise ErrorDatos("SEC_USER_AGENT debe contener nombre y email", causa="source_down")
    return ascii_ua


def dir_datos_plugin() -> Path:
    """Directorio persistente de datos. ${CLAUDE_PLUGIN_DATA} o, en desarrollo, ~/.cache/analisis-acciones."""
    base = os.environ.get("CLAUDE_PLUGIN_DATA")
    ruta = Path(base) if base else Path.home() / ".cache" / "analisis-acciones"
    ruta.mkdir(parents=True, exist_ok=True)
    return ruta


def ahora_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def hoy_iso() -> str:
    return date.today().isoformat()


def cifra(
    valor: float | int,
    unidad: str,
    moneda: str | None,
    fuente_url: str,
    fecha_dato: str,
    fecha_obtencion: str | None = None,
    **extra: Any,
) -> dict:
    """Cifra con trazabilidad. `extra` admite campos opcionales (concepto, forma, presentado, nota)."""
    if valor is None:
        raise ValueError("Una cifra necesita valor; usa desconocido() si falta.")
    d = {
        "valor": valor,
        "unidad": unidad,
        "moneda": moneda,
        "fuente_url": fuente_url,
        "fecha_dato": fecha_dato,
        "fecha_obtencion": fecha_obtencion or ahora_iso(),
    }
    d.update({k: v for k, v in extra.items() if v is not None})
    return d


def desconocido(causa: str, detalle: str | None = None) -> dict:
    if causa not in CAUSAS_DESCONOCIDO:
        raise ValueError(f"Causa no válida: {causa}")
    d: dict[str, Any] = {"desconocido": True, "causa": causa}
    if detalle:
        d["detalle"] = detalle
    return d


def es_desconocido(x: Any) -> bool:
    return isinstance(x, dict) and x.get("desconocido") is True


def leer_json(ruta: str | Path) -> Any:
    with open(ruta, encoding="utf-8") as f:
        return json.load(f)


def volcar_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=False, default=_serializar)


def escribir_json(ruta: str | Path, obj: Any) -> Path:
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    tmp = ruta.with_suffix(ruta.suffix + ".tmp")
    tmp.write_text(volcar_json(obj) + "\n", encoding="utf-8")
    tmp.replace(ruta)
    return ruta


def sha256_archivo(ruta: str | Path) -> str:
    return "sha256:" + hashlib.sha256(Path(ruta).read_bytes()).hexdigest()


def sha256_texto(texto: str) -> str:
    return "sha256:" + hashlib.sha256(texto.encode("utf-8")).hexdigest()


def _serializar(o: Any) -> Any:
    if isinstance(o, (date, datetime)):
        return o.isoformat()
    try:
        import numpy as np

        if isinstance(o, np.integer):
            return int(o)
        if isinstance(o, np.floating):
            return None if np.isnan(o) else float(o)
        if isinstance(o, np.ndarray):
            return o.tolist()
    except ImportError:  # pragma: no cover
        pass
    raise TypeError(f"No serializable: {type(o)}")


def salir_con_error(mensaje: str, codigo: int = 1) -> None:
    print(json.dumps({"error": mensaje}, ensure_ascii=False), file=sys.stderr)
    sys.exit(codigo)


def asegurar_path() -> None:
    """Permite `import comun` y `from datos import ...` al ejecutar un script de una subcarpeta."""
    if str(DIR_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(DIR_SCRIPTS))

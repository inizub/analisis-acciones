"""Caché en disco con TTL por fuente, limitador de peticiones (token bucket) y backoff exponencial.

Uso CLI:
    python cache.py info
    python cache.py limpiar [--fuente precios] [--solo-caducados]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Iterable, TypeVar

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import comun  # noqa: E402

T = TypeVar("T")


class CacheDisco:
    """Caché clave-valor en disco. Cada entrada guarda su marca de tiempo; el TTL depende de la fuente."""

    def __init__(
        self,
        directorio: str | Path | None = None,
        ttl_horas: dict[str, float] | None = None,
        reloj: Callable[[], float] = time.time,
    ):
        self.dir = Path(directorio) if directorio else comun.dir_datos_plugin() / "cache"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.ttl_horas = ttl_horas if ttl_horas is not None else comun.cargar_config()["cache_ttl_horas"]
        self.reloj = reloj

    def _ttl_seg(self, fuente: str) -> float:
        if fuente not in self.ttl_horas:
            raise KeyError(f"Fuente sin TTL configurado: {fuente}")
        return float(self.ttl_horas[fuente]) * 3600

    def _rutas(self, fuente: str, clave: str) -> tuple[Path, Path]:
        h = hashlib.sha256(clave.encode("utf-8")).hexdigest()[:32]
        base = self.dir / fuente
        base.mkdir(parents=True, exist_ok=True)
        return base / f"{h}.meta.json", base / f"{h}.dat"

    def _leer_meta(self, meta: Path) -> dict | None:
        try:
            return json.loads(meta.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return None

    def vigente(self, fuente: str, clave: str) -> bool:
        meta, dat = self._rutas(fuente, clave)
        m = self._leer_meta(meta)
        return bool(m and dat.exists() and self.reloj() - m["ts"] <= self._ttl_seg(fuente))

    def obtener_bytes(self, fuente: str, clave: str, permitir_caducado: bool = False) -> bytes | None:
        meta, dat = self._rutas(fuente, clave)
        m = self._leer_meta(meta)
        if not m or not dat.exists():
            return None
        if not permitir_caducado and self.reloj() - m["ts"] > self._ttl_seg(fuente):
            return None
        return dat.read_bytes()

    def guardar_bytes(self, fuente: str, clave: str, datos: bytes) -> None:
        meta, dat = self._rutas(fuente, clave)
        self._ttl_seg(fuente)  # valida la fuente
        tmp = dat.with_suffix(".tmp")
        tmp.write_bytes(datos)
        tmp.replace(dat)
        meta.write_text(json.dumps({"ts": self.reloj(), "clave": clave}), encoding="utf-8")

    def obtener(self, fuente: str, clave: str, permitir_caducado: bool = False) -> Any | None:
        b = self.obtener_bytes(fuente, clave, permitir_caducado)
        return None if b is None else json.loads(b.decode("utf-8"))

    def guardar(self, fuente: str, clave: str, valor: Any) -> None:
        self.guardar_bytes(fuente, clave, json.dumps(valor, ensure_ascii=False).encode("utf-8"))

    def fecha_guardado(self, fuente: str, clave: str) -> float | None:
        m = self._leer_meta(self._rutas(fuente, clave)[0])
        return m["ts"] if m else None

    def obtener_o_calcular(
        self, fuente: str, clave: str, calcular: Callable[[], Any], usar_caducado_si_falla: bool = True
    ) -> tuple[Any, dict]:
        """Devuelve (valor, info). Si la fuente falla y hay una copia caducada, la usa y lo indica en info."""
        v = self.obtener(fuente, clave)
        if v is not None:
            return v, {"origen": "cache", "ts": self.fecha_guardado(fuente, clave)}
        try:
            v = calcular()
        except comun.ErrorDatos:
            if usar_caducado_si_falla:
                viejo = self.obtener(fuente, clave, permitir_caducado=True)
                if viejo is not None:
                    return viejo, {"origen": "cache_caducada", "ts": self.fecha_guardado(fuente, clave)}
            raise
        self.guardar(fuente, clave, v)
        return v, {"origen": "red", "ts": self.reloj()}

    def info(self) -> dict:
        res = {}
        for sub in sorted(p for p in self.dir.iterdir() if p.is_dir()):
            metas = list(sub.glob("*.meta.json"))
            tam = sum(p.stat().st_size for p in sub.glob("*.dat"))
            res[sub.name] = {"entradas": len(metas), "bytes": tam}
        return res

    def limpiar(self, fuente: str | None = None, solo_caducados: bool = False) -> int:
        n = 0
        subs = [self.dir / fuente] if fuente else [p for p in self.dir.iterdir() if p.is_dir()]
        for sub in subs:
            if not sub.exists():
                continue
            for meta in sub.glob("*.meta.json"):
                m = self._leer_meta(meta)
                if solo_caducados and m and sub.name in self.ttl_horas:
                    if self.reloj() - m["ts"] <= self._ttl_seg(sub.name):
                        continue
                meta.unlink(missing_ok=True)
                meta.with_name(meta.name.replace(".meta.json", ".dat")).unlink(missing_ok=True)
                n += 1
        return n


class TokenBucket:
    """Limitador de tasa: como máximo `tasa` peticiones por segundo, con ráfaga de `capacidad`."""

    def __init__(
        self,
        tasa: float,
        capacidad: float | None = None,
        reloj: Callable[[], float] = time.monotonic,
        dormir: Callable[[float], None] = time.sleep,
    ):
        if tasa <= 0:
            raise ValueError("La tasa debe ser positiva")
        self.tasa = float(tasa)
        self.capacidad = float(capacidad if capacidad is not None else tasa)
        self.tokens = self.capacidad
        self.reloj = reloj
        self.dormir = dormir
        self.ultimo = reloj()
        self._lock = threading.Lock()

    def adquirir(self) -> float:
        """Bloquea hasta disponer de un token. Devuelve el tiempo esperado (s)."""
        esperado = 0.0
        with self._lock:
            while True:
                t = self.reloj()
                self.tokens = min(self.capacidad, self.tokens + (t - self.ultimo) * self.tasa)
                self.ultimo = t
                if self.tokens >= 1:
                    self.tokens -= 1
                    return esperado
                falta = (1 - self.tokens) / self.tasa
                self.dormir(falta)
                esperado += falta


def con_backoff(
    funcion: Callable[[], T],
    reintentos: int = 5,
    espera_base: float = 2.0,
    excepciones: Iterable[type[BaseException]] = (Exception,),
    dormir: Callable[[float], None] = time.sleep,
    al_reintentar: Callable[[int, BaseException, float], None] | None = None,
) -> T:
    """Ejecuta `funcion` con reintentos y espera exponencial (base, 2·base, 4·base…). Relanza el último error."""
    excepciones = tuple(excepciones)
    for intento in range(reintentos + 1):
        try:
            return funcion()
        except excepciones as e:  # type: ignore[misc]
            if intento == reintentos:
                raise
            espera = espera_base * (2**intento)
            if al_reintentar:
                al_reintentar(intento + 1, e, espera)
            dormir(espera)
    raise RuntimeError("inalcanzable")  # pragma: no cover


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Gestión de la caché de datos del plugin.")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("info", help="Entradas y tamaño por fuente")
    lp = sub.add_parser("limpiar", help="Borra entradas")
    lp.add_argument("--fuente")
    lp.add_argument("--solo-caducados", action="store_true")
    a = p.parse_args(argv)
    c = CacheDisco()
    if a.cmd == "info":
        print(comun.volcar_json({"directorio": str(c.dir), "fuentes": c.info()}))
    else:
        print(comun.volcar_json({"borradas": c.limpiar(a.fuente, a.solo_caducados)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())

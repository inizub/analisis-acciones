"""Utilidades del motor: validación de entradas, trayectorias y descuento."""
from __future__ import annotations

import math
from typing import Sequence


class ErrorMotor(ValueError):
    """Entradas inválidas para un modelo de valoración."""


def exigir(condicion: bool, mensaje: str) -> None:
    if not condicion:
        raise ErrorMotor(mensaje)


def finito(x: float, nombre: str) -> float:
    exigir(x is not None and math.isfinite(x), f"{nombre} debe ser un número finito (recibido {x!r})")
    return float(x)


def serie_anual(valor: float | Sequence[float], n: int, nombre: str) -> list[float]:
    """Convierte un escalar o una lista en n valores. Una lista más corta se completa con su último valor."""
    if isinstance(valor, (int, float)):
        return [finito(valor, nombre)] * n
    v = [finito(x, nombre) for x in valor]
    exigir(len(v) >= 1, f"{nombre} vacío")
    return (v + [v[-1]] * n)[:n]


def trayectoria(inicial: float, final: float, n: int, anios_convergencia: int | None = None) -> list[float]:
    """n valores que van linealmente de `inicial` (excluido) a `final` en `anios_convergencia` años y luego se mantienen."""
    a = n if anios_convergencia is None else max(1, min(anios_convergencia, n))
    return [inicial + (final - inicial) * min(t, a) / a for t in range(1, n + 1)]


def crecimiento_con_desvanecimiento(g_alto: float, g_terminal: float, n: int = 10, anios_altos: int = 5) -> list[float]:
    """g_alto durante `anios_altos` años y descenso lineal hasta g_terminal en el año n."""
    resto = n - anios_altos
    exigir(resto >= 0, "anios_altos no puede superar n")
    return [g_alto] * anios_altos + [g_alto + (g_terminal - g_alto) * k / resto for k in range(1, resto + 1)]



def por_accion(valor_patrimonio: float, acciones: float) -> float:
    exigir(acciones > 0, "acciones debe ser positivo")
    return valor_patrimonio / acciones

"""Camada de hardware da portaria."""
from __future__ import annotations

from .base import Hardware


def get_hardware(cfg, modo: str | None = None) -> Hardware:
    """Cria o hardware real (Raspberry Pi) ou simulado conforme HARDWARE_MODO."""
    modo = modo or cfg["HARDWARE_MODO"]
    if modo == "real":
        from .real import RealHardware
        return RealHardware(cfg)
    from .mock import MockHardware
    return MockHardware(cols=cfg["DISPLAY_COLS"], rows=cfg["DISPLAY_ROWS"])

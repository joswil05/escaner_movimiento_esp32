"""Cálculos simples sobre ventanas de amplitud CSI (fase 0: solo para visualizar)."""

from __future__ import annotations

import numpy as np


def normalize_per_packet(amps: np.ndarray) -> np.ndarray:
    """Divide cada paquete (fila) por su amplitud media, para quitar el efecto del AGC."""
    mean = amps.mean(axis=1, keepdims=True)
    return amps / np.where(mean > 0, mean, 1.0)


def motion_index(amps: np.ndarray) -> float:
    """Desviación estándar temporal media sobre subportadoras, con amplitud normalizada.

    `amps` tiene forma (paquetes, subportadoras). Valores bajos = ambiente quieto.
    """
    if amps.shape[0] < 2:
        return 0.0
    return float(normalize_per_packet(amps).std(axis=0).mean())

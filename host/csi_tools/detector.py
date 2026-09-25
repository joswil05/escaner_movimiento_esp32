"""Detector de movimiento en tiempo real (fase 2, referencia para el port a C).

Recibe un paquete a la vez (amplitud, RSSI, timestamp). Cada `hop` paquetes calcula las features
de la última ventana y actualiza el estado:

  score = feature elegida (V por defecto, o C)
  Calibración: las primeras `calib_windows` ventanas fijan la línea base (mediana y MAD del score).
  QUIETO -> MOVIMIENTO: `n_on` ventanas seguidas con score > umbral_on
  MOVIMIENTO -> QUIETO: `n_off` ventanas seguidas con score < umbral_off
  umbral_on  = base + max(k_on  * sigma, (ratio_on  - 1) * base)
  umbral_off = base + max(k_off * sigma, (ratio_off - 1) * base)
  Mientras está QUIETO y el score queda por debajo de umbral_off (claramente tranquilo), base y sigma
  se actualizan lentamente (promedio exponencial con `alpha`): así siguen cambios lentos del ambiente
  sin "aprender" movimientos moderados que no llegaron a disparar el detector.
"""

from __future__ import annotations

import collections
from dataclasses import dataclass, field

import numpy as np

from .dsp import WindowFeatures, window_features

QUIET, MOTION, CALIBRATING = "QUIETO", "MOVIMIENTO", "CALIBRANDO"


@dataclass
class DetectorConfig:
    window: int = 100          # paquetes por ventana (~1 s a 100 Hz)
    hop: int = 20              # paquetes entre decisiones (~0.2 s)
    feature: str = "variance"  # "variance" (V) o "decorrelation" (C)
    calib_windows: int = 25    # ~5 s de calibración inicial (el ambiente debe estar quieto)
    k_on: float = 6.0
    k_off: float = 3.0
    ratio_on: float = 1.6      # el umbral nunca queda a menos de 1.6x la línea base
    ratio_off: float = 1.3
    n_on: int = 2              # ~0.4 s por encima para declarar movimiento
    n_off: int = 5             # ~1 s por debajo para volver a quieto
    alpha: float = 0.003       # adaptación de la línea base (constante de tiempo ~70 s)
    min_sigma: float = 1e-4


@dataclass
class Decision:
    t: float                   # hora del último paquete de la ventana (la que se pase a update)
    state: str
    score: float
    threshold_on: float
    threshold_off: float
    features: WindowFeatures


@dataclass
class MotionDetector:
    config: DetectorConfig = field(default_factory=DetectorConfig)

    def __post_init__(self):
        cfg = self.config
        self._amps: collections.deque = collections.deque(maxlen=cfg.window)
        self._rssi: collections.deque = collections.deque(maxlen=cfg.window)
        self._ts: collections.deque = collections.deque(maxlen=cfg.window)
        self._since_hop = 0
        self.recalibrate()

    def recalibrate(self) -> None:
        self.state = CALIBRATING
        self._calib: list[float] = []
        self.base = 0.0
        self.sigma = 0.0
        self._above = 0
        self._below = 0

    @property
    def thresholds(self) -> tuple[float, float]:
        c = self.config
        on = self.base + max(c.k_on * self.sigma, (c.ratio_on - 1.0) * self.base)
        off = self.base + max(c.k_off * self.sigma, (c.ratio_off - 1.0) * self.base)
        return on, off

    def update(self, amp: np.ndarray, rssi: float, ts_us: int, t: float = 0.0) -> Decision | None:
        """Agrega un paquete. Devuelve una Decision cada `hop` paquetes (con la ventana llena)."""
        self._amps.append(amp)
        self._rssi.append(rssi)
        self._ts.append(ts_us)
        self._since_hop += 1
        if len(self._amps) < self.config.window or self._since_hop < self.config.hop:
            return None
        self._since_hop = 0
        feats = window_features(np.array(self._amps), np.array(self._rssi), np.array(self._ts))
        score = float(getattr(feats, self.config.feature))
        self.step(score)
        on, off = self.thresholds
        return Decision(t, self.state, score, on, off, feats)

    def step(self, score: float) -> None:
        """Avanza la máquina de estados con el score de una ventana nueva."""
        c = self.config
        if self.state == CALIBRATING:
            self._calib.append(score)
            if len(self._calib) >= c.calib_windows:
                v = np.array(self._calib)
                self.base = float(np.median(v))
                self.sigma = max(float(1.4826 * np.median(np.abs(v - self.base))), c.min_sigma)
                self.state = QUIET
            return

        on, off = self.thresholds
        if self.state == QUIET:
            self._above = self._above + 1 if score > on else 0
            if self._above >= c.n_on:
                self.state, self._below = MOTION, 0
            elif score <= off:
                # Solo se aprende de ventanas claramente tranquilas
                dev = abs(score - self.base)
                self.base += c.alpha * (score - self.base)
                # E|x - media| = 0.798 sigma en ruido gaussiano -> sigma ~ 1.2533 * |dev|
                self.sigma = max(self.sigma + c.alpha * (1.2533 * dev - self.sigma), c.min_sigma)
        else:
            self._below = self._below + 1 if score < off else 0
            if self._below >= c.n_off:
                self.state, self._above = QUIET, 0

"""Procesamiento de referencia: preprocesado y features por ventana (fase 2).

Todo está escrito para portarse tal cual a C (componente `csi_dsp`, fase 3): solo operaciones
simples sobre una ventana de W paquetes x S subportadoras, sin estado oculto.

Pipeline por ventana (W paquetes, por defecto 100 = ~1 s):
  1. Amplitud normalizada por paquete (divide por la media del paquete: quita el AGC).
  2. Filtro Hampel temporal por subportadora (mediana de 2k+1 muestras; reemplaza atípicos).
  3. Features (ver `WindowFeatures`).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

HAMPEL_HALF = 3        # ventana de 7 muestras
HAMPEL_NSIGMA = 3.0
MAD_SCALE = 1.4826     # MAD -> desviación estándar para ruido gaussiano
BANDS_HZ = ((1.0, 3.0), (3.0, 10.0), (10.0, 40.0))


@dataclass
class WindowFeatures:
    variance: float        # V: desviación estándar temporal media sobre subportadoras
    decorrelation: float   # C: 1 - correlación media entre paquetes consecutivos
    band_1_3: float        # energía relativa en 1-3 Hz (movimiento lento: brazos, caminar)
    band_3_10: float       # 3-10 Hz (movimiento rápido)
    band_10_40: float      # 10-40 Hz (mayormente ruido)
    rssi_mean: float
    rssi_std: float
    rate_hz: float         # paquetes por segundo dentro de la ventana

    def as_array(self) -> np.ndarray:
        return np.array(list(asdict(self).values()), dtype=np.float32)

    @staticmethod
    def names() -> list[str]:
        return list(WindowFeatures.__dataclass_fields__)


def normalize_per_packet(amps: np.ndarray) -> np.ndarray:
    """Divide cada paquete (fila) por su amplitud media."""
    mean = amps.mean(axis=1, keepdims=True)
    return amps / np.where(mean > 0, mean, 1.0)


def hampel(x: np.ndarray, half: int = HAMPEL_HALF, nsigma: float = HAMPEL_NSIGMA) -> np.ndarray:
    """Filtro Hampel sobre el eje 0 (tiempo), independiente por columna.

    En los bordes la ventana se recorta. Devuelve una copia.
    """
    n = x.shape[0]
    out = x.copy()
    for i in range(n):
        lo, hi = max(0, i - half), min(n, i + half + 1)
        seg = x[lo:hi]
        med = np.median(seg, axis=0)
        mad = MAD_SCALE * np.median(np.abs(seg - med), axis=0)
        bad = np.abs(x[i] - med) > nsigma * mad
        out[i, bad] = med[bad]
    return out


def preprocess(amps: np.ndarray) -> np.ndarray:
    return hampel(normalize_per_packet(amps.astype(np.float32)))


def variance_feature(x: np.ndarray) -> float:
    return float(x.std(axis=0).mean()) if x.shape[0] > 1 else 0.0


def decorrelation_feature(x: np.ndarray) -> float:
    """1 - correlación de Pearson media entre paquetes consecutivos (a lo largo de las subportadoras)."""
    if x.shape[0] < 2:
        return 0.0
    a = x[:-1] - x[:-1].mean(axis=1, keepdims=True)
    b = x[1:] - x[1:].mean(axis=1, keepdims=True)
    den = np.sqrt((a * a).sum(axis=1) * (b * b).sum(axis=1))
    corr = np.where(den > 0, (a * b).sum(axis=1) / np.where(den > 0, den, 1.0), 1.0)
    return float(1.0 - corr.mean())


def band_energies(x: np.ndarray, fs: float) -> tuple[float, ...]:
    """Energía por banda del espectro temporal, promediada sobre subportadoras, relativa a la total."""
    n = x.shape[0]
    if n < 8 or fs <= 0:
        return tuple(0.0 for _ in BANDS_HZ)
    d = x - x.mean(axis=0)
    spec = np.abs(np.fft.rfft(d, axis=0)) ** 2
    power = spec.mean(axis=1)
    freqs = np.fft.rfftfreq(n, d=1.0 / fs)
    total = power[1:].sum()
    if total <= 0:
        return tuple(0.0 for _ in BANDS_HZ)
    return tuple(float(power[(freqs >= lo) & (freqs < hi)].sum() / total) for lo, hi in BANDS_HZ)


def window_features(amps: np.ndarray, rssi: np.ndarray, ts_us: np.ndarray) -> WindowFeatures:
    """Features de una ventana. `amps` (W, S) crudas, `rssi` (W,), `ts_us` (W,) reloj de la ESP32."""
    x = preprocess(amps)
    dt = (np.diff(ts_us.astype(np.int64)) % 2**32) / 1e6
    span = float(dt.sum())
    rate = (len(ts_us) - 1) / span if span > 0 else 0.0
    b1, b2, b3 = band_energies(x, rate)
    return WindowFeatures(
        variance=variance_feature(x),
        decorrelation=decorrelation_feature(x),
        band_1_3=b1, band_3_10=b2, band_10_40=b3,
        rssi_mean=float(np.mean(rssi)), rssi_std=float(np.std(rssi)),
        rate_hz=rate,
    )

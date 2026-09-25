"""Parser del formato de texto CSI_DATA / CSI_STATS (compatible con los ejemplos de esp-csi)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# Columnas previas al arreglo de CSI en el formato de la ESP32 clásica.
CSI_FIELDS = (
    "id", "mac", "rssi", "rate", "sig_mode", "mcs", "bandwidth", "smoothing", "not_sounding",
    "aggregation", "stbc", "fec_coding", "sgi", "noise_floor", "ampdu_cnt", "channel",
    "secondary_channel", "local_timestamp", "ant", "sig_len", "rx_state", "len", "first_word",
)

# LLTF en ESP32: 64 subportadoras en orden 0..31, -32..-1.
# Útiles: -26..-1 (índices 38..63) y 1..26 (índices 1..26). Se descartan DC y guardas.
LLTF_USEFUL = np.r_[38:64, 1:27]
LLTF_SUBCARRIER_NUMBERS = np.r_[-26:0, 1:27]


@dataclass
class CsiPacket:
    id: int
    mac: str
    rssi: int
    rate: int
    sig_mode: int
    mcs: int
    bandwidth: int
    noise_floor: int
    channel: int
    local_timestamp: int  # microsegundos, reloj de la ESP32 (se desborda cada ~71 min)
    first_word_invalid: bool
    raw: np.ndarray        # int8/int16 tal como llegan: pares (imaginario, real)

    @property
    def csi(self) -> np.ndarray:
        """CSI complejo por subportadora (64 para LLTF)."""
        data = self.raw.astype(np.float32)
        if self.first_word_invalid:
            data[:4] = 0.0
        imag = data[0::2]
        real = data[1::2]
        return real + 1j * imag

    @property
    def amplitude(self) -> np.ndarray:
        """Amplitud de las 52 subportadoras útiles de LLTF, ordenadas de -26 a +26."""
        amp = np.abs(self.csi)
        if amp.size < 64:
            raise ValueError(f"CSI demasiado corto: {amp.size} subportadoras")
        return amp[LLTF_USEFUL]


@dataclass
class CsiStats:
    uptime_ms: int
    received_1s: int
    dropped_total: int
    rssi: int


def parse_line(line: str) -> CsiPacket | CsiStats | None:
    """Convierte una línea del serial. Devuelve None si no es CSI/estadística o está incompleta."""
    line = line.strip()
    if line.startswith("CSI_STATS,"):
        parts = line.split(",")
        if len(parts) != 5:
            return None
        try:
            return CsiStats(*(int(p) for p in parts[1:]))
        except ValueError:
            return None

    if not line.startswith("CSI_DATA,"):
        return None
    start = line.find('"[')
    end = line.rfind(']"')
    if start < 0 or end < start:
        return None

    head = line[len("CSI_DATA,"):start].rstrip(",").split(",")
    if len(head) != len(CSI_FIELDS):
        return None
    f = dict(zip(CSI_FIELDS, head))
    try:
        raw = np.array(line[start + 2:end].split(","), dtype=np.int16)
        if raw.size != int(f["len"]) or raw.size % 2:
            return None  # línea cortada o corrupta
        return CsiPacket(
            id=int(f["id"]),
            mac=f["mac"],
            rssi=int(f["rssi"]),
            rate=int(f["rate"]),
            sig_mode=int(f["sig_mode"]),
            mcs=int(f["mcs"]),
            bandwidth=int(f["bandwidth"]),
            noise_floor=int(f["noise_floor"]),
            channel=int(f["channel"]),
            local_timestamp=int(f["local_timestamp"]),
            first_word_invalid=bool(int(f["first_word"])),
            raw=raw,
        )
    except ValueError:
        return None

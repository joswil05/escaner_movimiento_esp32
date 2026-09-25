"""Protocolo binario del firmware `rx` (ver firmware/components/csi_proto/include/csi_proto.h).

`StreamDecoder` recibe bytes crudos del puerto serial y devuelve objetos:
  - CsiPacket, CsiStats, TxInfo  (tramas binarias válidas)
  - str                          (texto: logs, mensajes de arranque)
También entiende las líneas de texto CSI_DATA/CSI_STATS del firmware de la fase 0,
así el mismo visor sirve para los dos firmwares.
"""

from __future__ import annotations

import ipaddress
import struct
from dataclasses import dataclass

import numpy as np

from .esp_text import CsiPacket, CsiStats, parse_line

MAGIC = b"\x1a\xc5"
VERSION = 1
HEADER = struct.Struct("<HBBH")          # magic, version, type, len
MAX_PAYLOAD = 1024

T_CSI, T_STATS, T_LOG, T_TX_INFO, T_DETECT = 1, 2, 3, 4, 5
CMD_RECALIBRATE = b"R"

CSI_HDR = struct.Struct("<IIHIbbBBBBBBBB6sH")      # csi_frame_csi_t (32 bytes)
STATS = struct.Struct("<IHHIIbBBBI")               # csi_frame_stats_t (24 bytes)
BEACON = struct.Struct("<IHHIIII16s")              # csi_tx_beacon_t (40 bytes)
TX_INFO = struct.Struct("<6s" + BEACON.format[1:])  # csi_frame_tx_info_t
DETECT = struct.Struct("<IBBH3f8f")                # csi_frame_detect_t (52 bytes)
ESP_STATES = {0: "CALIBRANDO", 1: "QUIETO", 2: "MOVIMIENTO"}

SOURCES = {0: "router", 1: "tx"}


@dataclass
class TxInfo:
    mac: str
    seq: int
    rate_hz: int
    uptime_ms: int
    ip: str
    send_fail: int
    fw_version: str


@dataclass
class EspDecision:
    """Decisión del detector que corre dentro de la ESP32 (csi_dsp)."""
    uptime_ms: int
    state: str
    feature: str
    proc_us: int
    score: float
    threshold_on: float
    threshold_off: float
    features: tuple


def crc16(data: bytes) -> int:
    """CRC-16/CCITT-FALSE, igual que csi_proto_crc16()."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def build_frame(ftype: int, payload: bytes) -> bytes:
    """Arma una trama (para tests y simuladores)."""
    body = struct.pack("<BBH", VERSION, ftype, len(payload)) + payload
    return MAGIC + body + struct.pack("<H", crc16(body))


def _mac(b: bytes) -> str:
    return ":".join(f"{x:02x}" for x in b)


def decode_payload(ftype: int, payload: bytes):
    if ftype == T_CSI and len(payload) >= CSI_HDR.size:
        (rx_count, tx_seq, rx_seq, local_ts, rssi, noise_floor, rate, sig_mode, mcs, cwb, _stbc,
         channel, _secondary, fwi, mac, csi_len) = CSI_HDR.unpack_from(payload)
        raw = np.frombuffer(payload, dtype=np.int8, count=csi_len, offset=CSI_HDR.size)
        if raw.size != csi_len or csi_len % 2:
            return None
        return CsiPacket(id=rx_count, mac=_mac(mac), rssi=rssi, rate=rate, sig_mode=sig_mode, mcs=mcs,
                         bandwidth=cwb, noise_floor=noise_floor, channel=channel, local_timestamp=local_ts,
                         first_word_invalid=bool(fwi), raw=raw.astype(np.int16), tx_seq=tx_seq, rx_seq=rx_seq)
    if ftype == T_STATS and len(payload) >= STATS.size:
        uptime, rx_s, _r, dropped, tx_lost, rssi, source, channel, _r2, heap = STATS.unpack_from(payload)
        return CsiStats(uptime, rx_s, dropped, rssi, tx_lost, SOURCES.get(source, "?"), channel, heap)
    if ftype == T_TX_INFO and len(payload) >= TX_INFO.size:
        mac, _magic, _ver, rate_hz, seq, uptime, ip, fail, fw = TX_INFO.unpack_from(payload)
        return TxInfo(_mac(mac), seq, rate_hz, uptime, str(ipaddress.IPv4Address(struct.pack("<I", ip))),
                      fail, fw.split(b"\0", 1)[0].decode("ascii", "replace"))
    if ftype == T_DETECT and len(payload) >= DETECT.size:
        v = DETECT.unpack_from(payload)
        return EspDecision(v[0], ESP_STATES.get(v[1], "?"), "decorrelation" if v[2] else "variance", v[3],
                           v[4], v[5], v[6], tuple(v[7:]))
    if ftype == T_LOG:
        return payload.decode("utf-8", "replace")
    return None


class StreamDecoder:
    """Separa tramas binarias y líneas de texto de un flujo de bytes."""

    MAX_TEXT = 4096

    def __init__(self):
        self.buf = bytearray()
        self.crc_errors = 0

    def feed(self, data: bytes) -> list:
        self.buf += data
        out: list = []
        while True:
            idx = self.buf.find(MAGIC)
            text_end = len(self.buf) if idx < 0 else idx
            self._take_text(text_end, out, flush=idx >= 0)
            if idx < 0:
                return out
            # self.buf ahora empieza con el magic
            if len(self.buf) < HEADER.size:
                return out
            _magic, version, ftype, length = HEADER.unpack_from(self.buf)
            if version != VERSION or length > MAX_PAYLOAD:
                del self.buf[:1]  # falso magic: seguir buscando
                continue
            total = HEADER.size + length + 2
            if len(self.buf) < total:
                return out
            body = bytes(self.buf[2:HEADER.size + length])
            (crc,) = struct.unpack_from("<H", self.buf, HEADER.size + length)
            if crc != crc16(body):
                self.crc_errors += 1
                del self.buf[:1]
                continue
            item = decode_payload(ftype, body[4:])
            del self.buf[:total]
            if item is not None:
                out.append(item)

    def _take_text(self, end: int, out: list, flush: bool) -> None:
        """Extrae líneas completas de buf[:end]; si `flush`, también el resto (lo corta una trama)."""
        chunk = bytes(self.buf[:end])
        lines = chunk.split(b"\n")
        rest = lines.pop()
        if flush and rest:
            lines.append(rest)
            rest = b""
        for raw in lines:
            line = raw.decode("ascii", "replace").strip()
            if not line or sum(not (32 <= ord(c) < 127) for c in line) > len(line) // 10:
                continue  # vacía o basura binaria (arranque de la ROM, trama corrupta)
            line = "".join(c for c in line if 32 <= ord(c) < 127)
            parsed = parse_line(line)
            out.append(parsed if parsed is not None else line)
        if len(rest) > self.MAX_TEXT:
            rest = b""  # basura binaria sin fin de línea
        del self.buf[:end]
        self.buf[0:0] = rest

import struct
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from csi_tools.esp_text import CsiPacket, CsiStats  # noqa: E402
from csi_tools.proto import (BEACON, CSI_HDR, STATS, T_CSI, T_LOG, T_STATS, T_TX_INFO, StreamDecoder,  # noqa: E402
                             TxInfo, build_frame, crc16)
from csi_tools.recording import RecordingWriter, load_labels, read_items  # noqa: E402

REPO = Path(__file__).resolve().parents[2]


def csi_frame(rx_count=5, tx_seq=42, csi=None):
    csi = np.arange(128, dtype=np.int8) if csi is None else np.asarray(csi, dtype=np.int8)
    hdr = CSI_HDR.pack(rx_count, tx_seq, 77, 123456, -48, -95, 11, 1, 0, 0, 0, 1, 0, 1,
                       bytes.fromhex("f42dc96b26c0"), csi.size)
    return build_frame(T_CSI, hdr + csi.tobytes())


def test_crc_known_value():
    assert crc16(b"123456789") == 0x29B1  # valor de referencia de CRC-16/CCITT-FALSE


def test_decode_mixed_stream_split_in_chunks():
    stats = build_frame(T_STATS, STATS.pack(1000, 99, 0, 1, 2, -50, 1, 1, 0, 200000))
    beacon = BEACON.pack(0x54495343, 1, 100, 700, 7000, struct.unpack("<I", bytes([192, 168, 1, 50]))[0], 3,
                         b"tx-1.0.0")
    info = build_frame(T_TX_INFO, bytes.fromhex("f42dc96b26c0") + beacon)
    stream = (b"\x00\xffets Jun  8 2016 00:22:57\r\nboot:0x13\r\n" + csi_frame() + b"texto suelto\n"
              + build_frame(T_LOG, b"I (100) csi_rx: hola") + stats + info)
    dec = StreamDecoder()
    items = []
    for i in range(0, len(stream), 7):  # llegar en pedazos pequeños no debe romper nada
        items += dec.feed(stream[i:i + 7])

    pkts = [x for x in items if isinstance(x, CsiPacket)]
    assert len(pkts) == 1
    p = pkts[0]
    assert (p.id, p.tx_seq, p.rx_seq, p.rssi, p.channel, p.mac) == (5, 42, 77, -48, 1, "f4:2d:c9:6b:26:c0")
    assert p.first_word_invalid and p.raw.size == 128
    assert p.amplitude.shape == (51,)
    st = [x for x in items if isinstance(x, CsiStats)][0]
    assert (st.received_1s, st.tx_lost_total, st.source, st.free_heap) == (99, 2, "tx", 200000)
    tx = [x for x in items if isinstance(x, TxInfo)][0]
    assert (tx.ip, tx.seq, tx.fw_version) == ("192.168.1.50", 700, "tx-1.0.0")
    texts = [x for x in items if isinstance(x, str)]
    assert "I (100) csi_rx: hola" in texts and "texto suelto" in texts
    assert dec.crc_errors == 0


def test_corrupted_frame_is_skipped_and_stream_resyncs():
    bad = bytearray(csi_frame(rx_count=1))
    bad[40] ^= 0xFF
    dec = StreamDecoder()
    items = dec.feed(bytes(bad) + csi_frame(rx_count=2))
    pkts = [x for x in items if isinstance(x, CsiPacket)]
    assert [p.id for p in pkts] == [2]
    assert dec.crc_errors >= 1


def test_phase0_text_lines_still_work():
    sys.path.insert(0, str(Path(__file__).parent))
    from test_esp_text import make_line
    items = StreamDecoder().feed((make_line([1] * 128) + "\r\nCSI_STATS,1,2,3,-4\r\n").encode())
    assert isinstance(items[0], CsiPacket) and isinstance(items[1], CsiStats)


def test_recording_roundtrip(tmp_path):
    w = RecordingWriter(tmp_path / "sesion", meta={"fuente": "tx"})
    w.write(10.0, csi_frame(rx_count=1)[:20])
    w.write(10.5, csi_frame(rx_count=1)[20:] + csi_frame(rx_count=2))
    w.add_event(10.2, "scenario", "S1")
    w.close()
    items = list(read_items(tmp_path / "sesion.csirec"))
    assert [(t, x.id) for t, x in items if isinstance(x, CsiPacket)] == [(10.5, 1), (10.5, 2)]
    labels = load_labels(tmp_path / "sesion.csirec")
    assert labels["events"] == [{"t": 10.2, "type": "scenario", "value": "S1"}] and labels["meta"]["fuente"] == "tx"


C_PROGRAM = r"""
#include <stdio.h>
#include <string.h>
#include "csi_proto.h"
int main(void) {
    _Static_assert(sizeof(csi_frame_csi_t) == 32, "csi");
    _Static_assert(sizeof(csi_frame_stats_t) == 24, "stats");
    _Static_assert(sizeof(csi_tx_beacon_t) == 40, "beacon");
    csi_frame_csi_t h = {0};
    h.rx_count = 9; h.tx_seq = 1234; h.rx_seq = 55; h.rssi = -60; h.channel = 6; h.csi_len = 128;
    int8_t csi[128];
    for (int i = 0; i < 128; i++) csi[i] = (int8_t)(i - 64);
    uint8_t out[512];
    size_t n = csi_proto_build(CSI_FRAME_CSI, &h, sizeof(h), csi, sizeof(csi), out, sizeof(out));
    fwrite(out, 1, n, stdout);
    return 0;
}
"""


def test_c_encoder_matches_python_decoder(tmp_path):
    comp = REPO / "firmware" / "components" / "csi_proto"
    src = tmp_path / "t.c"
    src.write_text(C_PROGRAM)
    exe = tmp_path / "t"
    try:
        subprocess.run(["gcc", "-std=c11", "-Wall", "-Werror", "-I", str(comp / "include"), str(src),
                        str(comp / "csi_proto.c"), "-o", str(exe)], check=True, capture_output=True)
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        pytest.skip(f"sin compilador C: {exc}")
    frame = subprocess.run([str(exe)], check=True, capture_output=True).stdout
    items = StreamDecoder().feed(frame)
    assert len(items) == 1
    p = items[0]
    assert (p.id, p.tx_seq, p.rx_seq, p.rssi, p.channel) == (9, 1234, 55, -60, 6)
    assert p.raw[0] == -64 and p.raw[127] == 63

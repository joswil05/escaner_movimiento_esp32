import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from csi_tools.esp_text import CsiPacket, CsiStats, parse_line  # noqa: E402
from csi_tools.features import motion_index  # noqa: E402


def make_line(values, pkt_id=7, first_word=0):
    head = f"CSI_DATA,{pkt_id},98:77:e7:2d:f8:74,-45,11,1,0,0,1,0,0,0,0,0,-95,0,1,0,523412,0,52,0,{len(values)},{first_word}"
    return head + ',"[' + ",".join(str(v) for v in values) + ']"'


def test_parse_csi_line():
    values = [0] * 128
    values[4], values[5] = 3, 4  # subportadora +2: imag=3, real=4 -> amplitud 5
    values[76], values[77] = 6, 8  # índice 38 = subportadora -26 -> amplitud 10
    pkt = parse_line(make_line(values))
    assert isinstance(pkt, CsiPacket)
    assert pkt.id == 7 and pkt.rssi == -45 and pkt.channel == 1
    assert pkt.csi[2] == 4 + 3j
    amp = pkt.amplitude
    assert amp.shape == (51,)
    assert amp[0] == 10.0   # primera fila: -26
    assert amp[26] == 5.0   # después de las 26 negativas viene la +2 (la +1 se descarta)


def test_first_word_invalid_is_zeroed():
    values = [9] * 128
    pkt = parse_line(make_line(values, first_word=1))
    assert pkt.csi[0] == 0 and pkt.csi[1] == 0 and pkt.csi[2] == 9 + 9j


def test_rejects_truncated_and_foreign_lines():
    assert parse_line(make_line([1] * 128)[:-40]) is None
    assert parse_line("I (316) csi_router: Conectando...") is None
    assert parse_line(make_line([1] * 127)) is None  # largo impar


def test_parse_stats():
    stats = parse_line("CSI_STATS,12000,98,0,-47")
    assert stats == CsiStats(12000, 98, 0, -47)


def test_motion_index_grows_with_variation():
    rng = np.random.default_rng(0)
    still = 10 + rng.normal(0, 0.05, size=(100, 51))
    moving = 10 + rng.normal(0, 2.0, size=(100, 51))
    assert motion_index(still) < motion_index(moving)
    # Un cambio de ganancia global (AGC) no debe parecer movimiento
    agc = still * np.linspace(1, 3, 100)[:, None]
    assert motion_index(agc) < 0.02

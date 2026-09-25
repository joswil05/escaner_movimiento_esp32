"""Compara el detector en C (firmware/components/csi_dsp) con la referencia en Python."""

import struct
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from csi_tools.detector import CALIBRATING, MOTION, QUIET, DetectorConfig, MotionDetector  # noqa: E402
from csi_tools.dsp import WindowFeatures  # noqa: E402
from csi_tools.esp_text import CsiPacket  # noqa: E402
from csi_tools.recording import read_items  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
COMP = REPO / "firmware" / "components" / "csi_dsp"
SAMPLE = REPO / "data" / "samples" / "fase0_prueba1.csv"
STATES = {0: CALIBRATING, 1: QUIET, 2: MOTION}
NSC = 51


@pytest.fixture(scope="module")
def runner(tmp_path_factory):
    exe = tmp_path_factory.mktemp("csi_dsp") / "runner"
    cmd = ["gcc", "-std=c99", "-O2", "-Wall", "-Wextra", "-Werror", "-I", str(COMP / "include"),
           str(COMP / "csi_dsp.c"), str(COMP / "test" / "host_runner.c"), "-o", str(exe), "-lm"]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        pytest.skip(f"sin compilador C: {exc}")
    return exe


def synthetic_packets(rng):
    """Calma, movimiento, calma y saltos de ganancia, como CsiPacket crudos."""
    base = rng.uniform(5, 30, 64)
    pkts, ts = [], 0
    plan = [(800, 0.02, 1.0), (400, 0.25, 1.0), (500, 0.02, 1.0), (300, 0.02, 1.8), (400, 0.3, 0.7), (600, 0.02, 1.0)]
    for n, noise, gain in plan:
        for _ in range(n):
            amp = base * gain * (1 + rng.normal(0, noise, 64))
            ph = rng.uniform(0, 2 * np.pi, 64)
            raw = np.empty(128, np.int16)
            raw[0::2] = np.clip(np.round(amp * np.sin(ph)), -127, 127)
            raw[1::2] = np.clip(np.round(amp * np.cos(ph)), -127, 127)
            ts = (ts + int(rng.normal(10_000, 800))) % 2**32
            pkts.append(CsiPacket(len(pkts), "", -50 + int(rng.integers(-2, 3)), 11, 1, 0, 0, -95, 1, ts, True, raw))
    return pkts


def run_c(runner, tmp_path, pkts, feature):
    inp, out = tmp_path / "in.bin", tmp_path / "out.bin"
    with open(inp, "wb") as f:
        f.write(struct.pack("<ii", len(pkts), feature))
        for p in pkts:
            f.write(p.raw.astype(np.int8).tobytes())
            f.write(struct.pack("<BbI", int(p.first_word_invalid), p.rssi, p.local_timestamp % 2**32))
    subprocess.run([str(runner), str(inp), str(out)], check=True)
    data = out.read_bytes()
    amps_bytes = len(pkts) * NSC * 4
    dec_bytes, amps = data[:-amps_bytes], np.frombuffer(data[-amps_bytes:], dtype=np.float32).reshape(-1, NSC)
    rec = struct.Struct("<ii3f8f")
    decisions = [rec.unpack_from(dec_bytes, off) for off in range(0, len(dec_bytes), rec.size)]
    return decisions, amps


def run_py(pkts, feature):
    det = MotionDetector(DetectorConfig(feature=feature))
    out = []
    for i, p in enumerate(pkts):
        d = det.update(p.amplitude, p.rssi, p.local_timestamp)
        if d:
            out.append((i, d))
    return out


def compare(c_dec, py_dec):
    assert len(c_dec) == len(py_dec) and len(c_dec) > 10
    mismatched = 0
    for c, (i, d) in zip(c_dec, py_dec):
        assert c[0] == i
        if STATES[c[1]] != d.state:
            mismatched += 1
        np.testing.assert_allclose(c[2:5], [d.score, d.threshold_on, d.threshold_off], rtol=2e-3, atol=1e-5)
        np.testing.assert_allclose(c[5:], d.features.as_array(), rtol=5e-3, atol=2e-4,
                                   err_msg=f"features en el paquete {i}: {WindowFeatures.names()}")
    # Un score justo en el borde de un umbral puede caer distinto por redondeo: se tolera
    # un mínimo de diferencias, nunca más del 1 %.
    assert mismatched <= max(1, len(c_dec) // 100)


@pytest.mark.parametrize("feature", [0, 1])
def test_c_matches_python_synthetic(runner, tmp_path, feature):
    pkts = synthetic_packets(np.random.default_rng(10 + feature))
    c_dec, c_amps = run_c(runner, tmp_path, pkts, feature)
    np.testing.assert_allclose(c_amps, np.array([p.amplitude for p in pkts]), rtol=1e-6, atol=1e-5)
    name = "variance" if feature == 0 else "decorrelation"
    compare(c_dec, run_py(pkts, name))
    assert any(c[1] == 2 for c in c_dec), "el caso sintético debe incluir movimiento detectado"


@pytest.mark.skipif(not SAMPLE.exists(), reason="sin la grabación de ejemplo")
def test_c_matches_python_real_recording(runner, tmp_path):
    pkts = [x for _, x in read_items(SAMPLE) if isinstance(x, CsiPacket)][:4000]
    c_dec, _ = run_c(runner, tmp_path, pkts, 0)
    compare(c_dec, run_py(pkts, "variance"))

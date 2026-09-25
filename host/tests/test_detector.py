import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps"))
from csi_tools.detector import CALIBRATING, MOTION, QUIET, DetectorConfig, MotionDetector  # noqa: E402
from csi_tools.dsp import decorrelation_feature, hampel, window_features  # noqa: E402

FS = 100


def synthetic(seconds, moving, rng, base, gain=1.0):
    """Amplitudes (N, 51): ruido pequeño en calma, grande en movimiento; `gain` simula el AGC."""
    n = int(seconds * FS)
    noise = 0.25 if moving else 0.02
    amps = base * (1 + rng.normal(0, noise, size=(n, base.size)))
    return np.abs(amps) * gain


def feed(det, amps, t0=0.0):
    out = []
    for i, a in enumerate(amps):
        t = t0 + i / FS
        d = det.update(a, -50, int(t * 1e6), t)
        if d:
            out.append(d)
    return out


def test_hampel_removes_spike_keeps_signal():
    x = np.ones((20, 3))
    x[:, 1] = np.arange(20)          # rampa: no se toca
    x[10, 0] = 50                    # pico aislado: se reemplaza
    y = hampel(x)
    assert y[10, 0] == 1.0
    assert np.array_equal(y[:, 1], x[:, 1])


def test_features_are_scale_invariant_and_respond_to_motion():
    rng = np.random.default_rng(0)
    base = rng.uniform(5, 30, 51)
    ts = (np.arange(100) * 10_000).astype(np.int64)
    quiet = synthetic(1, False, rng, base)
    f_quiet = window_features(quiet, np.full(100, -50), ts)
    f_scaled = window_features(quiet * 3.7, np.full(100, -50), ts)
    f_move = window_features(synthetic(1, True, rng, base), np.full(100, -50), ts)
    assert abs(f_quiet.variance - f_scaled.variance) < 1e-5
    assert f_move.variance > 5 * f_quiet.variance
    assert f_move.decorrelation > 5 * f_quiet.decorrelation
    assert abs(f_quiet.rate_hz - 100) < 0.5


def test_decorrelation_zero_for_identical_packets():
    x = np.tile(np.linspace(1, 2, 51), (10, 1))
    assert decorrelation_feature(x) < 1e-6


def test_detector_quiet_motion_quiet():
    rng = np.random.default_rng(1)
    base = rng.uniform(5, 30, 51)
    det = MotionDetector(DetectorConfig())
    seq = np.vstack([synthetic(10, False, rng, base), synthetic(5, True, rng, base),
                     synthetic(8, False, rng, base)])
    out = feed(det, seq)
    assert out[0].state == CALIBRATING
    states = {round(d.t, 1): d.state for d in out}
    in_motion = [t for t, s in states.items() if s == MOTION]
    assert in_motion, "no detectó el movimiento"
    assert 10.0 <= min(in_motion) <= 11.0          # latencia < 1 s
    # La ventana de 1 s arrastra el movimiento hasta t=16 y luego hacen falta n_off=5 ventanas (1 s)
    assert max(in_motion) <= 17.2
    assert out[-1].state == QUIET
    assert not [t for t in in_motion if t < 10.0], "falsa alarma antes del movimiento"


def test_agc_jumps_do_not_trigger():
    rng = np.random.default_rng(2)
    base = rng.uniform(5, 30, 51)
    det = MotionDetector(DetectorConfig())
    parts = [synthetic(3, False, rng, base, gain=g) for g in (1.0, 1.8, 0.6, 1.3, 2.2, 1.0, 0.8, 1.5)]
    out = feed(det, np.vstack(parts))
    assert all(d.state != MOTION for d in out)


def test_baseline_follows_slow_drift_but_not_motion():
    rng = np.random.default_rng(3)
    base = rng.uniform(5, 30, 51)
    det = MotionDetector(DetectorConfig())
    feed(det, synthetic(10, False, rng, base))
    b0 = det.base
    # El ruido de fondo sube lentamente (cambio del ambiente): la base lo sigue sin disparar
    for i, noise in enumerate(np.linspace(0.02, 0.035, 40)):
        amps = np.abs(base * (1 + rng.normal(0, noise, size=(FS * 3, base.size))))
        out = feed(det, amps)
        assert all(d.state != MOTION for d in out), f"falsa alarma con ruido {noise:.3f}"
    assert det.base > b0 * 1.3


def test_evaluate_on_labeled_recording(tmp_path):
    from csi_tools.proto import CSI_HDR, T_CSI, build_frame
    from csi_tools.recording import RecordingWriter
    import evaluate as ev

    rng = np.random.default_rng(4)
    base64 = rng.uniform(5, 30, 64)
    w = RecordingWriter(tmp_path / "rec")
    plan = [(0, 12, False), (12, 16, True), (16, 26, False), (26, 30, True), (30, 40, False)]
    i = 0
    for a, b, moving in plan:
        for k in range(int((b - a) * FS)):
            t = 1000.0 + a + k / FS
            amp = base64 * (1 + rng.normal(0, 0.25 if moving else 0.02, 64))
            ph = rng.uniform(0, 2 * np.pi, 64)
            c = np.empty(128, np.int8)
            c[0::2] = np.clip(np.round(amp * np.sin(ph)), -127, 127)
            c[1::2] = np.clip(np.round(amp * np.cos(ph)), -127, 127)
            hdr = CSI_HDR.pack(i, i, i % 4096, int((t - 1000) * 1e6), -50, -95, 11, 1, 0, 0, 0, 1, 0, 1, bytes(6), 128)
            w.write(t, build_frame(T_CSI, hdr + c.tobytes()))
            i += 1
    w.add_event(1000.0, "scenario", "S0")
    for a, b, moving in plan:
        if moving:
            w.add_event(1000.0 + a, "motion_start")
            w.add_event(1000.0 + b, "motion_end")
    w.close()

    packets = ev.load_packets(tmp_path / "rec.csirec")
    events = ev.load_labels(tmp_path / "rec.csirec")["events"]
    track = ev.feature_track(packets, DetectorConfig())
    r = ev.evaluate("rec", track, events, DetectorConfig())
    assert (r.events, r.detected, r.false_alarms) == (2, 2, 0)
    assert max(r.latencies) < 1.0

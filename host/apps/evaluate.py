"""Evalúa el detector de movimiento sobre grabaciones etiquetadas.

Uso:
    python apps/evaluate.py ../data/e1_tx.csirec ../data/e3_vacio_10min.csirec
    python apps/evaluate.py ../data/*.csirec --feature decorrelation
    python apps/evaluate.py ../data/*.csirec --sweep          # prueba varias combinaciones de umbrales
    python apps/evaluate.py ../data/e1_tx.csirec --source esp # evalúa lo que decidió la ESP32 (firmware rx)

Verdad de referencia (del .json de etiquetas):
  - Un "movimiento" va de una marca `Espacio` (inicio) a la siguiente (fin).
  - Tiempo tranquilo: escenarios S0 (vacío) y S4 (quieto) fuera de movimientos marcados.
Métricas:
  - Detección por evento: % de movimientos marcados en los que el detector dijo MOVIMIENTO
    (entre el inicio y 1 s después del fin), y latencia desde el inicio de la marca.
  - Falsas alarmas: pasos a MOVIMIENTO en tiempo tranquilo, por hora (con 2 s de margen
    alrededor de cada movimiento marcado, porque la tecla nunca se pulsa en el instante exacto).
"""

from __future__ import annotations

import argparse
import itertools
import sys
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from csi_tools.detector import CALIBRATING, MOTION, DetectorConfig, MotionDetector  # noqa: E402
from csi_tools.esp_text import CsiPacket  # noqa: E402
from csi_tools.proto import EspDecision  # noqa: E402
from csi_tools.recording import load_labels, read_items  # noqa: E402

MARGIN_S = 2.0
QUIET_SCENARIOS = ("S0", "S4")


@dataclass
class Result:
    name: str
    events: int
    detected: int
    latencies: list[float]
    quiet_s: float
    false_alarms: int
    motion_s_share: float  # fracción del tiempo total en MOVIMIENTO

    @property
    def detection_rate(self) -> float:
        return self.detected / self.events if self.events else float("nan")

    @property
    def fa_per_hour(self) -> float:
        return self.false_alarms / self.quiet_s * 3600 if self.quiet_s > 0 else float("nan")


def load_packets(path: Path) -> list[tuple[float, CsiPacket, np.ndarray]]:
    out = []
    for t, item in read_items(path):
        if isinstance(item, CsiPacket):
            out.append((t, item, item.amplitude))
    return out


def motion_intervals(events: list[dict]) -> list[tuple[float, float]]:
    out, start = [], None
    for ev in sorted(events, key=lambda e: e["t"]):
        if ev["type"] == "motion_start":
            start = ev["t"]
        elif ev["type"] == "motion_end" and start is not None:
            out.append((start, ev["t"]))
            start = None
    return out


def scenario_at(events: list[dict], t: float) -> str:
    sc = "—"
    for ev in sorted(events, key=lambda e: e["t"]):
        if ev["t"] > t:
            break
        if ev["type"] == "scenario":
            sc = ev["value"]
    return sc


def feature_track(packets, cfg: DetectorConfig):
    """Features de cada ventana (dependen solo de window/hop, no de los umbrales)."""
    det = MotionDetector(cfg)
    track = []
    for t, pkt, amp in packets:
        d = det.update(amp, pkt.rssi, pkt.local_timestamp, t)
        if d:
            track.append((d.t, d.features))
    return track


def simulate(track, cfg: DetectorConfig):
    """Corre la máquina de estados del detector sobre features ya calculadas."""
    det = MotionDetector(cfg)
    out = []
    for t, feats in track:
        det.step(float(getattr(feats, cfg.feature)))
        out.append((t, det.state))
    return out


def esp_decisions(path: Path) -> list[tuple[float, str]]:
    """Decisiones que tomó el detector de la ESP32, grabadas como tramas DETECT."""
    return [(t, item.state) for t, item in read_items(path) if isinstance(item, EspDecision)]


def evaluate(name: str, track, events: list[dict], cfg: DetectorConfig, decisions=None) -> Result:
    """`decisions` = lista (t, estado) ya calculada (ESP32); si falta, se simula el detector de la PC."""
    if decisions is None:
        decisions = simulate(track, cfg)
    decisions = [(t, st) for t, st in decisions if st != CALIBRATING]
    intervals = motion_intervals(events)
    times = np.array([t for t, _ in decisions])
    moving = np.array([st == MOTION for _, st in decisions], dtype=bool)

    detected, lat = 0, []
    for a, b in intervals:
        hit = np.where(moving & (times >= a) & (times <= b + 1.0))[0]
        if hit.size:
            detected += 1
            lat.append(float(times[hit[0]] - a))

    def near_motion(t: float) -> bool:
        return any(a - MARGIN_S <= t <= b + MARGIN_S for a, b in intervals)

    quiet = np.array([scenario_at(events, t) in QUIET_SCENARIOS and not near_motion(t) for t in times])
    hop_s = float(np.median(np.diff(times))) if len(times) > 1 else 0.0
    starts = np.where(moving[1:] & ~moving[:-1])[0] + 1
    fa = int(sum(quiet[i] for i in starts))
    return Result(name, len(intervals), detected, lat, float(quiet.sum() * hop_s), fa,
                  float(moving.mean()) if len(moving) else 0.0)


def timeline(decisions) -> str:
    if not decisions:
        return ""
    t0 = decisions[0][0]
    secs: dict[int, set] = {}
    for t, st in decisions:
        secs.setdefault(int(t - t0), set()).add(st)
    return "".join("#" if MOTION in secs.get(i, ()) else "c" if CALIBRATING in secs.get(i, ()) else "."
                   for i in range(max(secs) + 1))


def summarize(results: list[Result]) -> tuple[float, float, float]:
    ev = sum(r.events for r in results)
    det = sum(r.detected for r in results)
    lat = [x for r in results for x in r.latencies]
    quiet = sum(r.quiet_s for r in results)
    fa = sum(r.false_alarms for r in results)
    return (det / ev if ev else float("nan"), fa / quiet * 3600 if quiet else float("nan"),
            float(np.median(lat)) if lat else float("nan"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--feature", default="variance", choices=["variance", "decorrelation"])
    parser.add_argument("--sweep", action="store_true", help="probar una grilla de umbrales y ordenar por resultado")
    parser.add_argument("--source", choices=["pc", "esp"], default="pc",
                        help="pc: simular el detector de Python; esp: usar las decisiones grabadas de la ESP32")
    args = parser.parse_args()

    data = []
    for f in args.files:
        packets = load_packets(f)
        events = load_labels(f)["events"]
        if not packets:
            print(f"{f.name}: sin paquetes CSI, se omite")
            continue
        if not events:
            print(f"{f.name}: sin etiquetas (.json); solo se muestra la línea de tiempo")
        esp = esp_decisions(f) if args.source == "esp" else None
        if args.source == "esp" and not esp:
            print(f"{f.name}: no tiene decisiones de la ESP32 (grabado con otro firmware), se omite")
            continue
        data.append((f.name, feature_track(packets, DetectorConfig()) if esp is None else None, events, esp))

    base_cfg = DetectorConfig(feature=args.feature)
    if not args.sweep:
        results = []
        for name, track, events, esp in data:
            if not events:
                print(f"{name}: línea de tiempo (1 carácter = 1 s; # movimiento, c calibrando, . quieto)")
                print("  " + timeline(esp if esp is not None else simulate(track, base_cfg)))
                continue
            r = evaluate(name, track, events, base_cfg, esp)
            results.append(r)
            lat = f"{np.median(r.latencies):.2f} s" if r.latencies else "—"
            print(f"{name}: movimientos detectados {r.detected}/{r.events}, latencia mediana {lat}, "
                  f"falsas alarmas {r.false_alarms} en {r.quiet_s / 60:.1f} min tranquilos "
                  f"({r.fa_per_hour:.1f}/h), tiempo en MOVIMIENTO {100 * r.motion_s_share:.0f} %")
        if not results:
            return 0
        rate, fah, lat = summarize(results)
        who = "ESP32" if args.source == "esp" else args.feature
        print(f"\nTOTAL ({who}): detección {100 * rate:.0f} %, falsas alarmas {fah:.1f}/h, "
              f"latencia mediana {lat:.2f} s")
        return 0

    if args.source == "esp":
        parser.error("--sweep solo funciona con --source pc (los umbrales de la ESP32 ya están aplicados)")
    grid = itertools.product([4.0, 6.0, 8.0], [1.3, 1.6, 2.0], [1, 2, 3], ["variance", "decorrelation"])
    rows = []
    for k_on, ratio_on, n_on, feat in grid:
        cfg = replace(base_cfg, k_on=k_on, ratio_on=ratio_on, n_on=n_on, feature=feat)
        rate, fah, lat = summarize([evaluate(n, tr, e, cfg) for n, tr, e, _ in data])
        rows.append((rate, fah, lat, feat, k_on, ratio_on, n_on))
    # Primero: detectar casi todo; luego menos falsas alarmas; luego menor latencia
    rows.sort(key=lambda r: (-(round(r[0], 2) if r[0] == r[0] else -1), r[1] if r[1] == r[1] else 1e9, r[2]))
    print(f"{'detección':>9} {'FA/h':>6} {'latencia':>8}  feature        k_on ratio_on n_on")
    for rate, fah, lat, feat, k_on, ratio_on, n_on in rows[:15]:
        print(f"{100 * rate:8.0f}% {fah:6.1f} {lat:7.2f}s  {feat:<14} {k_on:4.1f} {ratio_on:8.1f} {n_on:4d}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Estadísticas de una o varias grabaciones: calidad del enlace y separación quieto/movimiento.

Uso:
    python apps/link_stats.py ../data/s01.csirec ../data/fase0_prueba1.csv

Calidad del enlace: tasa de paquetes, regularidad (intervalos entre paquetes medidos con el reloj
de la ESP32), pérdidas en el aire (huecos en la secuencia del TX), descartes en el receptor y RSSI.
Si la grabación tiene etiquetas (.json), también el índice de movimiento por escenario y
con/sin movimiento marcado.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from csi_tools.esp_text import CsiPacket, CsiStats  # noqa: E402
from csi_tools.features import motion_index  # noqa: E402
from csi_tools.recording import load_labels, read_items  # noqa: E402

WINDOW = 100  # paquetes por ventana del índice de movimiento (~1 s)


def label_timeline(events: list[dict], times: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Para cada instante: escenario vigente y si había un movimiento marcado."""
    scenario = np.array(["—"] * len(times), dtype=object)
    moving = np.zeros(len(times), dtype=bool)
    for ev in sorted(events, key=lambda e: e["t"]):
        after = times >= ev["t"]
        if ev["type"] == "scenario":
            scenario[after] = ev["value"]
        elif ev["type"] == "motion_start":
            moving[after] = True
        elif ev["type"] == "motion_end":
            moving[after] = False
    return scenario, moving


def analyze(path: Path) -> None:
    pkts: list[tuple[float, CsiPacket]] = []
    stats: list[CsiStats] = []
    for t, item in read_items(path):
        if isinstance(item, CsiPacket):
            pkts.append((t, item))
        elif isinstance(item, CsiStats):
            stats.append(item)
    print(f"\n=== {path.name} ===")
    if len(pkts) < 2:
        print("  (sin paquetes CSI)")
        return

    t = np.array([p[0] for p in pkts])
    dur = t[-1] - t[0]
    ts = np.array([p[1].local_timestamp for p in pkts], dtype=np.int64)
    dt_ms = ((np.diff(ts) % 2**32) / 1000.0)
    rssi = np.array([p[1].rssi for p in pkts])
    print(f"  Duración {dur:.1f} s, {len(pkts)} paquetes, {len(pkts) / dur:.1f} paquetes/s")
    print(f"  Intervalo entre paquetes (ms): mediana {np.median(dt_ms):.1f}, p5 {np.percentile(dt_ms, 5):.1f}, "
          f"p95 {np.percentile(dt_ms, 95):.1f}, máx {dt_ms.max():.0f}; "
          f"desvío {np.std(dt_ms):.2f} ms")
    print(f"  RSSI {rssi.mean():.1f} ± {rssi.std():.1f} dBm")

    tx_seq = np.array([p[1].tx_seq for p in pkts], dtype=np.int64)
    if (tx_seq >= 0).all() and tx_seq.max() > 0:
        expected = tx_seq[-1] - tx_seq[0] + 1
        print(f"  Transmisor: {expected - len(set(tx_seq))} de {expected} beacons perdidos en el camino "
              f"({100 * (1 - len(set(tx_seq)) / expected):.2f} %)")
    if stats:
        print(f"  Descartados en el receptor (cola llena): {stats[-1].dropped_total}")

    amps = np.array([p[1].amplitude for p in pkts], dtype=np.float32)
    n_win = len(amps) // WINDOW
    if n_win == 0:
        return
    mi = np.array([motion_index(amps[i * WINDOW:(i + 1) * WINDOW]) for i in range(n_win)])
    t_win = t[[min((i + 1) * WINDOW - 1, len(t) - 1) for i in range(n_win)]]
    print(f"  Índice de movimiento: p10 {np.percentile(mi, 10):.3f}, mediana {np.median(mi):.3f}, "
          f"p90 {np.percentile(mi, 90):.3f}")

    events = load_labels(path)["events"]
    if not events:
        return
    scenario, moving = label_timeline(events, t_win)
    print("  Por escenario (índice de movimiento, mediana [p10–p90], ventanas de ~1 s):")
    for sc in dict.fromkeys(scenario):
        for mv in (False, True):
            sel = (scenario == sc) & (moving == mv)
            if sel.sum():
                v = mi[sel]
                tag = "con movimiento marcado" if mv else "sin movimiento marcado"
                print(f"    {sc:>3} {tag:<23} {np.median(v):.3f} [{np.percentile(v, 10):.3f}–"
                      f"{np.percentile(v, 90):.3f}]  n={sel.sum()}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("files", nargs="+", type=Path)
    args = parser.parse_args()
    for f in args.files:
        analyze(f)
    return 0


if __name__ == "__main__":
    sys.exit(main())

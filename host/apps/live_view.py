"""Visor en vivo del CSI que envía la ESP32 por serial (fase 0).

Uso:
    python apps/live_view.py --port COM3                       # ver en vivo
    python apps/live_view.py --port COM3 --record sesion.csv   # ver y grabar
    python apps/live_view.py --replay sesion.csv               # reproducir una grabación

Al abrir el puerto reinicia la placa y escribe en la terminal sus mensajes de arranque
(MAC, router, IP) y las líneas CSI_STATS; las líneas de CSI solo van a las gráficas.

Muestra:
  - Mapa de calor: amplitud normalizada de las 52 subportadoras en los últimos segundos.
  - Índice de movimiento: sube cuando alguien se mueve entre la placa y el router.
  - Paquetes por segundo y RSSI.
"""

from __future__ import annotations

import argparse
import collections
import csv
import sys
import threading
import time
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from pyqtgraph.Qt import QtCore, QtWidgets

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from csi_tools.esp_text import LLTF_SUBCARRIER_NUMBERS, CsiPacket, CsiStats, parse_line  # noqa: E402
from csi_tools.features import motion_index, normalize_per_packet  # noqa: E402

HEATMAP_PACKETS = 600   # ~6 s a 100 Hz
MOTION_WINDOW = 100     # ~1 s
HISTORY_SECONDS = 60


class Source:
    """Lee líneas del serial o de una grabación en un hilo y guarda los paquetes parseados."""

    def __init__(self, port: str | None, baud: int, replay: Path | None, record: Path | None,
                 reset: bool = True):
        self.echo = replay is None  # en vivo: mostrar en la terminal todo lo que no es CSI
        self.reset = reset
        # (hora de llegada, paquete, amplitud de las 52 subportadoras) — la amplitud se calcula una vez
        self.packets: collections.deque[tuple[float, CsiPacket, np.ndarray]] = collections.deque(maxlen=HEATMAP_PACKETS)
        self.arrivals: collections.deque[float] = collections.deque(maxlen=2000)
        self.stats: CsiStats | None = None
        self.total = 0
        self.bad_lines = 0
        self.backlog = 0  # bytes esperando en el puerto: si crece, la PC va atrasada
        self.lock = threading.Lock()
        self.running = True
        self.error: str | None = None
        self._record_file = None
        self._writer = None
        if record:
            record.parent.mkdir(parents=True, exist_ok=True)
            self._record_file = open(record, "w", newline="", encoding="utf-8")
            self._writer = csv.writer(self._record_file)
            self._writer.writerow(["pc_time", "line"])
        target = self._read_replay if replay else self._read_serial
        self.thread = threading.Thread(target=target, args=(replay or (port, baud),), daemon=True)
        self.thread.start()

    def _handle(self, line: str, t: float) -> None:
        item = parse_line(line)
        if isinstance(item, CsiPacket):
            try:
                amp = item.amplitude
            except ValueError:
                self.bad_lines += 1
                return
            with self.lock:
                self.packets.append((t, item, amp))
                self.arrivals.append(t)
                self.total += 1
        elif isinstance(item, CsiStats):
            self.stats = item
            if self.echo:
                print(line, flush=True)
        elif line.startswith("CSI_DATA"):
            self.bad_lines += 1
        elif self.echo and line:
            print(line, flush=True)  # mensajes de arranque de la ESP32 (MAC, router, IP...)
        if self._writer and item is not None:
            self._writer.writerow([f"{t:.6f}", line])

    def _read_serial(self, args) -> None:
        import serial  # pyserial

        port, baud = args
        try:
            with serial.Serial(port, baud, timeout=0.5) as ser:
                if self.reset:
                    # Igual que el botón EN: RTS reinicia la placa, DTR alto deja GPIO0 libre
                    # (arranca el firmware normal, no el modo descarga).
                    try:
                        ser.dtr = False
                        ser.rts = True
                        time.sleep(0.1)
                        ser.rts = False
                    except OSError:
                        pass  # puertos sin líneas de control
                # Leer en bloques: readline() lee byte a byte y no alcanza a ~65 KB/s en Windows
                pending = b""
                while self.running:
                    chunk = ser.read(max(1, ser.in_waiting))
                    if not chunk:
                        continue
                    self.backlog = ser.in_waiting
                    t = time.time()
                    lines = (pending + chunk).split(b"\n")
                    pending = lines.pop()
                    for raw in lines:
                        self._handle(raw.decode("ascii", errors="replace").strip(), t)
        except Exception as exc:  # puerto ocupado, desconectado, etc.
            self.error = str(exc)

    def _read_replay(self, path: Path) -> None:
        with open(path, newline="", encoding="utf-8") as f:
            rows = list(csv.reader(f))[1:]
        if not rows:
            self.error = "La grabación está vacía"
            return
        t0_file = float(rows[0][0])
        t0 = time.time()
        for pc_time, line in rows:
            if not self.running:
                return
            delay = (float(pc_time) - t0_file) - (time.time() - t0)
            if delay > 0:
                time.sleep(delay)
            self._handle(line, time.time())
        self.error = "Fin de la grabación"

    def snapshot(self):
        with self.lock:
            return list(self.packets), list(self.arrivals)

    def close(self) -> None:
        self.running = False
        if self._record_file:
            self._record_file.close()


class Viewer(QtWidgets.QMainWindow):
    def __init__(self, source: Source, title: str):
        super().__init__()
        self.source = source
        self.setWindowTitle(f"Visor CSI — {title}")
        self.resize(1100, 800)
        pg.setConfigOptions(antialias=True)

        central = pg.GraphicsLayoutWidget()
        self.setCentralWidget(central)
        self.status = QtWidgets.QLabel("Esperando datos...")
        self.statusBar().addWidget(self.status)

        # 1) Mapa de calor subportadora x tiempo
        self.heat_plot = central.addPlot(row=0, col=0, title="Amplitud normalizada por subportadora")
        self.heat_plot.setLabel("left", "Subportadora")
        self.heat_plot.setLabel("bottom", "Paquetes (el más reciente a la derecha)")
        self.heat_img = pg.ImageItem()
        self.heat_img.setColorMap(pg.colormap.get("viridis"))
        self.heat_plot.addItem(self.heat_img)
        # Eje Y en números de subportadora (-26..+26); se aplica después de cada setImage
        self.heat_rect = QtCore.QRectF(0, LLTF_SUBCARRIER_NUMBERS[0], HEATMAP_PACKETS, len(LLTF_SUBCARRIER_NUMBERS))

        # 2) Índice de movimiento
        self.motion_plot = central.addPlot(row=1, col=0, title="Índice de movimiento (ventana de ~1 s)")
        self.motion_plot.setLabel("bottom", "Segundos atrás")
        self.motion_curve = self.motion_plot.plot(pen=pg.mkPen("#f5a623", width=2))
        self.motion_hist: collections.deque[tuple[float, float]] = collections.deque()

        # 3) Tasa de paquetes y RSSI
        self.rate_plot = central.addPlot(row=2, col=0, title="Paquetes por segundo (amarillo) y RSSI dBm (celeste)")
        self.rate_plot.setLabel("bottom", "Segundos atrás")
        self.rate_curve = self.rate_plot.plot(pen=pg.mkPen("#e8e33a", width=2))
        self.rssi_curve = self.rate_plot.plot(pen=pg.mkPen("#4ab8f0", width=2))
        self.rate_hist: collections.deque[tuple[float, float, float]] = collections.deque()

        central.ci.layout.setRowStretchFactor(0, 3)
        central.ci.layout.setRowStretchFactor(1, 2)
        central.ci.layout.setRowStretchFactor(2, 2)

        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.refresh)
        self.timer.start(50)

    def refresh(self) -> None:
        packets, arrivals = self.source.snapshot()
        now = time.time()
        if self.source.error:
            self.status.setText(f"⚠ {self.source.error}")
        if not packets:
            return

        amps = np.array([a for _, _, a in packets], dtype=np.float32)
        heat = np.zeros((HEATMAP_PACKETS, amps.shape[1]), dtype=np.float32)
        heat[-len(amps):] = normalize_per_packet(amps)
        self.heat_img.setImage(heat, autoLevels=False, levels=(0.0, 2.0))
        self.heat_img.setRect(self.heat_rect)

        mi = motion_index(amps[-MOTION_WINDOW:])
        rate = sum(1 for t in arrivals if now - t <= 1.0)
        rssi = packets[-1][1].rssi
        self.motion_hist.append((now, mi))
        self.rate_hist.append((now, rate, rssi))
        while self.motion_hist and now - self.motion_hist[0][0] > HISTORY_SECONDS:
            self.motion_hist.popleft()
        while self.rate_hist and now - self.rate_hist[0][0] > HISTORY_SECONDS:
            self.rate_hist.popleft()

        mh = np.array(self.motion_hist)
        self.motion_curve.setData(mh[:, 0] - now, mh[:, 1])
        rh = np.array(self.rate_hist)
        self.rate_curve.setData(rh[:, 0] - now, rh[:, 1])
        self.rssi_curve.setData(rh[:, 0] - now, rh[:, 2])

        last = packets[-1][1]
        stats = self.source.stats
        dev = f" | ESP32: {stats.received_1s} paq/s, descartados {stats.dropped_total}" if stats else ""
        err = f" | ⚠ {self.source.error}" if self.source.error else ""
        lag = f" | ⚠ PC atrasada: {self.source.backlog} bytes en espera" if self.source.backlog > 20000 else ""
        self.status.setText(
            f"{rate} paq/s | RSSI {rssi} dBm | canal {last.channel} | índice {mi:.3f} | "
            f"total {self.source.total} | líneas malas {self.source.bad_lines}{dev}{lag}{err}"
        )

    def closeEvent(self, event) -> None:
        self.source.close()
        super().closeEvent(event)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", help="Puerto serial, por ejemplo COM3 o /dev/ttyUSB0")
    parser.add_argument("--baud", type=int, default=921600)
    parser.add_argument("--record", type=Path, help="Guardar las líneas recibidas en este CSV")
    parser.add_argument("--replay", type=Path, help="Reproducir un CSV grabado en lugar de leer el serial")
    parser.add_argument("--no-reset", action="store_true", help="No reiniciar la placa al abrir el puerto")
    args = parser.parse_args()
    if not args.port and not args.replay:
        parser.error("indica --port o --replay")

    app = QtWidgets.QApplication(sys.argv)
    source = Source(args.port, args.baud, args.replay, args.record, reset=not args.no_reset)
    viewer = Viewer(source, str(args.replay or args.port))
    viewer.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

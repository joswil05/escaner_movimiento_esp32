"""Visor en vivo del CSI que envía la ESP32 por serial.

Entiende los dos firmwares: `rx` (tramas binarias, fase 1) y `csi_router_test` (texto, fase 0).

Uso:
    python apps/live_view.py --port COM5                          # ver en vivo
    python apps/live_view.py --port COM5 --record ../data/s01     # ver, grabar y etiquetar
    python apps/live_view.py --replay ../data/s01.csirec          # reproducir (también .csv de la fase 0)

Al abrir el puerto reinicia la placa y escribe en la terminal sus mensajes (MAC, router, IP)
y las estadísticas; los paquetes de CSI solo van a las gráficas.

Teclas (con la ventana del visor activa):
    0..6      escenario actual: S0 vacío, S1 caminar entre placas, S2 caminar fuera de la línea,
              S3 brazos/sentado moviéndose, S4 quieto, S5 perturbación (ventilador, puerta, mascota),
              S6 mover un mueble
    Espacio   empieza / termina un movimiento
    N         escribir una nota
Las marcas se guardan en el .json junto a la grabación y aparecen como líneas en la gráfica.
"""

from __future__ import annotations

import argparse
import collections
import faulthandler
import sys
import threading
import time
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from pyqtgraph.Qt import QtCore, QtWidgets

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from csi_tools.esp_text import LLTF_SUBCARRIER_NUMBERS, CsiPacket, CsiStats  # noqa: E402
from csi_tools.detector import CALIBRATING, MOTION, Decision, DetectorConfig, MotionDetector  # noqa: E402
from csi_tools.dsp import normalize_per_packet  # noqa: E402
from csi_tools.proto import CMD_RECALIBRATE, EspDecision, StreamDecoder, TxInfo  # noqa: E402
from csi_tools.recording import RecordingWriter, load_labels, read_blocks  # noqa: E402

HEATMAP_PACKETS = 600   # ~6 s a 100 Hz
HISTORY_SECONDS = 60

SCENARIOS = {
    "0": "S0 vacío", "1": "S1 caminar entre placas", "2": "S2 caminar fuera de la línea",
    "3": "S3 brazos / sentado moviéndose", "4": "S4 quieto", "5": "S5 perturbación", "6": "S6 mover mueble",
}
EVENT_TEXT = {"motion_start": "mov. inicio", "motion_end": "mov. fin"}
LABEL_POS = {"scenario": 0.92, "motion_start": 0.75, "motion_end": 0.75, "note": 0.55}
EVENT_COLORS = {"scenario": "#8e7cc3", "motion_start": "#e06666", "motion_end": "#6aa84f", "note": "#999999"}


class Source:
    """Lee el serial (o una grabación) en un hilo, decodifica y guarda lo necesario para dibujar."""

    def __init__(self, port: str | None, baud: int, replay: Path | None, record: Path | None,
                 reset: bool = True):
        self.echo = replay is None  # en vivo: mostrar en la terminal todo lo que no es CSI
        self.reset = reset
        # (hora de llegada, paquete, amplitud de las subportadoras útiles) — la amplitud se calcula una vez
        self.packets: collections.deque[tuple[float, CsiPacket, np.ndarray]] = collections.deque(maxlen=HEATMAP_PACKETS)
        self.arrivals: collections.deque[float] = collections.deque(maxlen=2000)
        self.stats: CsiStats | None = None
        self.tx_info: TxInfo | None = None
        self.esp: EspDecision | None = None   # última decisión del detector de la ESP32 (firmware rx)
        self._serial = None
        self.total = 0
        self.bad_lines = 0
        self.backlog = 0  # bytes esperando en el puerto: si crece, la PC va atrasada
        self.decoder = StreamDecoder()
        self.detector = MotionDetector(DetectorConfig())
        self.decisions: collections.deque[Decision] = collections.deque(maxlen=HISTORY_SECONDS * 10)
        self.lock = threading.Lock()
        self.running = True
        self.error: str | None = None
        self.writer = RecordingWriter(record, meta={"port": port, "baud": baud}) if record else None
        self.events: list[dict] = list(load_labels(replay)["events"]) if replay else []
        self.time_offset = 0.0  # en replay: hora de la grabación -> hora actual
        target = self._read_replay if replay else self._read_serial
        self.thread = threading.Thread(target=target, args=(replay or (port, baud),), daemon=True)
        self.thread.start()

    def _feed(self, data: bytes, t: float) -> None:
        for item in self.decoder.feed(data):
            if isinstance(item, CsiPacket):
                try:
                    amp = item.amplitude
                except ValueError:
                    self.bad_lines += 1
                    continue
                decision = self.detector.update(amp, item.rssi, item.local_timestamp, t)
                with self.lock:
                    self.packets.append((t, item, amp))
                    self.arrivals.append(t)
                    self.total += 1
                    if decision:
                        self.decisions.append(decision)
            elif isinstance(item, CsiStats):
                self.stats = item
                if self.echo:
                    lost = f", perdidos en el aire {item.tx_lost_total}" if item.source == "tx" else ""
                    print(f"[stats] {item.received_1s} paq/s, descartados {item.dropped_total}{lost}, "
                          f"RSSI {item.rssi} dBm" + (f", memoria libre {item.free_heap // 1024} KB" if item.free_heap else ""),
                          flush=True)
            elif isinstance(item, TxInfo):
                self.tx_info = item
            elif isinstance(item, EspDecision):
                self.esp = item
            elif isinstance(item, str):
                if item.startswith("CSI_DATA"):
                    self.bad_lines += 1
                elif self.echo:
                    print(item, flush=True)  # mensajes de la ESP32 (MAC, router, IP...)

    def _read_serial(self, args) -> None:
        import serial  # pyserial

        port, baud = args
        try:
            with serial.Serial(port, baud, timeout=0.5) as ser:
                self._serial = ser
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
                while self.running:
                    chunk = ser.read(max(1, ser.in_waiting))
                    if not chunk:
                        continue
                    self.backlog = ser.in_waiting
                    t = time.time()
                    if self.writer:
                        self.writer.write(t, chunk)
                    self._feed(chunk, t)
        except Exception as exc:  # puerto ocupado, desconectado, etc.
            self.error = str(exc)
            print(f"⚠ Error leyendo {port}: {exc}", flush=True)

    def _read_replay(self, path: Path) -> None:
        t0 = None
        start = time.time()
        try:
            for t_file, data in read_blocks(path):
                if not self.running:
                    return
                if t0 is None:
                    t0 = t_file
                    self.time_offset = start - t0
                delay = (t_file - t0) - (time.time() - start)
                if delay > 0:
                    time.sleep(delay)
                self._feed(data, time.time())
        except Exception as exc:
            self.error = str(exc)
            return
        self.error = "Fin de la grabación"

    def add_event(self, kind: str, value=None) -> None:
        t = time.time()
        self.events.append({"t": t, "type": kind, "value": value})
        if self.writer:
            self.writer.add_event(t, kind, value)

    def snapshot(self):
        with self.lock:
            return list(self.packets), list(self.arrivals), list(self.decisions)

    def recalibrate(self) -> None:
        """Recalibra el detector de la PC y, si hay placa conectada, también el de la ESP32."""
        with self.lock:
            self.detector.recalibrate()
        if self._serial is not None:
            try:
                self._serial.write(CMD_RECALIBRATE)
            except Exception as exc:
                print(f"⚠ No se pudo enviar el comando a la placa: {exc}", flush=True)

    def close(self) -> None:
        self.running = False
        # Esperar a que el hilo lector termine su última lectura antes de cerrar la grabación
        if self.thread.is_alive() and threading.current_thread() is not self.thread:
            self.thread.join(timeout=1.5)
        if self.writer:
            self.writer.close()


class Viewer(QtWidgets.QMainWindow):
    def __init__(self, source: Source, title: str):
        super().__init__()
        self.source = source
        self.recording = source.writer is not None
        self.setWindowTitle(f"Visor CSI — {title}")
        self.resize(1100, 850)
        pg.setConfigOptions(antialias=True)

        central = pg.GraphicsLayoutWidget()
        self.setCentralWidget(central)
        self.status = QtWidgets.QLabel("Esperando datos...")
        self.statusBar().addWidget(self.status)

        self.label_bar = QtWidgets.QLabel()
        self.label_bar.setStyleSheet("padding: 4px; font-size: 13px;")
        self.state_label = QtWidgets.QLabel()
        self.state_label.setMinimumWidth(190)
        self.state_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.esp_label = QtWidgets.QLabel()
        self.esp_label.setMinimumWidth(190)
        self.esp_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        dock = QtWidgets.QToolBar()
        dock.addWidget(self.state_label)
        # En una QToolBar se muestra/oculta la acción que envuelve al widget, no el widget
        self.esp_action = dock.addWidget(self.esp_label)
        self.esp_action.setVisible(False)
        dock.addWidget(self.label_bar)
        dock.setMovable(False)
        self.addToolBar(QtCore.Qt.ToolBarArea.TopToolBarArea, dock)
        self.scenario = "—"
        self.moving = False

        # 1) Mapa de calor subportadora x tiempo
        self.heat_plot = central.addPlot(row=0, col=0, title="Amplitud normalizada por subportadora (51 útiles)")
        self.heat_plot.setLabel("left", "Subportadora")
        self.heat_plot.setLabel("bottom", "Paquetes (el más reciente a la derecha)")
        self.heat_img = pg.ImageItem()
        self.heat_img.setColorMap(pg.colormap.get("viridis"))
        self.heat_plot.addItem(self.heat_img)
        # Una fila por subportadora útil; el eje Y se rotula con su número real (-26..-1, +2..+26)
        self.heat_rect = QtCore.QRectF(0, 0, HEATMAP_PACKETS, len(LLTF_SUBCARRIER_NUMBERS))
        ticks = [(i + 0.5, str(n)) for i, n in enumerate(LLTF_SUBCARRIER_NUMBERS) if n in (-26, -20, -10, -1, 10, 20, 26)]
        self.heat_plot.getAxis("left").setTicks([ticks])

        # 2) Índice de movimiento, con las marcas de etiquetas
        self.motion_plot = central.addPlot(
            row=1, col=0, title="Detector: índice de movimiento (naranja), umbral de activación (rojo) y de liberación (verde)")
        self.motion_plot.setLabel("bottom", "Segundos atrás")
        self.motion_curve = self.motion_plot.plot(pen=pg.mkPen("#f5a623", width=2))
        self.on_curve = self.motion_plot.plot(pen=pg.mkPen("#e06666", width=1, style=QtCore.Qt.PenStyle.DashLine))
        self.off_curve = self.motion_plot.plot(pen=pg.mkPen("#6aa84f", width=1, style=QtCore.Qt.PenStyle.DashLine))
        self.motion_bands: list = []
        self.event_lines: list[pg.InfiniteLine] = []

        # 3) Tasa de paquetes y RSSI
        self.rate_plot = central.addPlot(row=2, col=0, title="Paquetes por segundo (amarillo) y RSSI dBm (celeste)")
        self.rate_plot.setLabel("bottom", "Segundos atrás")
        self.rate_curve = self.rate_plot.plot(pen=pg.mkPen("#e8e33a", width=2))
        self.rssi_curve = self.rate_plot.plot(pen=pg.mkPen("#4ab8f0", width=2))
        self.rate_hist: collections.deque[tuple[float, float, float]] = collections.deque()

        central.ci.layout.setRowStretchFactor(0, 3)
        central.ci.layout.setRowStretchFactor(1, 2)
        central.ci.layout.setRowStretchFactor(2, 2)

        self.update_label_bar()
        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.refresh)
        self.timer.start(50)

    # ---------- etiquetas ----------

    def update_label_bar(self) -> None:
        rec = "● GRABANDO" if self.recording else "sin grabar"
        mov = "  |  MOVIMIENTO en curso" if self.moving else ""
        self.label_bar.setText(f"{rec}  |  Escenario: {self.scenario}{mov}  |  "
                               "Teclas: 0-6 escenario · Espacio inicio/fin de movimiento · N nota · "
                               "R recalibrar (quédate quieto)")

    def keyPressEvent(self, event) -> None:
        key = event.text().lower()
        if key in SCENARIOS:
            self.scenario = SCENARIOS[key]
            self.source.add_event("scenario", self.scenario.split()[0])
        elif key == " ":
            self.moving = not self.moving
            self.source.add_event("motion_start" if self.moving else "motion_end")
        elif key == "r":
            self.source.recalibrate()
            self.source.add_event("note", "recalibrado")
        elif key == "n":
            text, ok = QtWidgets.QInputDialog.getText(self, "Nota", "Nota para esta grabación:")
            if ok and text:
                self.source.add_event("note", text)
        else:
            super().keyPressEvent(event)
            return
        self.update_label_bar()

    def draw_events(self, now: float) -> None:
        for line in self.event_lines:
            self.motion_plot.removeItem(line)
        self.event_lines = []
        offset = self.source.time_offset
        for ev in self.source.events:
            x = ev["t"] + offset - now
            if -HISTORY_SECONDS <= x <= 0:
                label = EVENT_TEXT.get(ev["type"]) or str(ev["value"])
                line = pg.InfiniteLine(pos=x, angle=90, pen=pg.mkPen(EVENT_COLORS.get(ev["type"], "#999"), width=1),
                                       label=label, labelOpts={"position": LABEL_POS.get(ev["type"], 0.6),
                                                               "color": "#cccccc"})
                self.motion_plot.addItem(line)
                self.event_lines.append(line)

    # ---------- detector ----------

    STATE_STYLE = {
        MOTION: ("● MOVIMIENTO", "#ffffff", "#c0392b"),
        CALIBRATING: ("CALIBRANDO…", "#000000", "#f1c40f"),
    }

    def draw_detector(self, decisions: list[Decision], now: float) -> float:
        """Dibuja score y umbrales, sombrea los tramos en MOVIMIENTO y actualiza el cartel de estado."""
        for band in self.motion_bands:
            self.motion_plot.removeItem(band)
        self.motion_bands = []
        if not decisions:
            self.state_label.setText("esperando datos")
            return 0.0
        t = np.array([d.t for d in decisions]) - now
        score = np.array([d.score for d in decisions])
        calibrated = np.array([d.state != CALIBRATING for d in decisions])
        self.motion_curve.setData(t, score)
        on = np.array([d.threshold_on for d in decisions])
        off = np.array([d.threshold_off for d in decisions])
        self.on_curve.setData(t[calibrated], on[calibrated])
        self.off_curve.setData(t[calibrated], off[calibrated])

        moving = np.array([d.state == MOTION for d in decisions])
        start = None
        for i, m in enumerate(np.append(moving, False)):
            if m and start is None:
                start = t[i]
            elif not m and start is not None:
                band = pg.LinearRegionItem(values=(start, t[i - 1]), brush=(224, 102, 102, 50), movable=False,
                                           pen=pg.mkPen(None))
                self.motion_plot.addItem(band)
                self.motion_bands.append(band)
                start = None

        self.set_badge(self.state_label, "PC", decisions[-1].state)
        esp = self.source.esp
        if esp is not None:
            self.esp_action.setVisible(True)
            self.set_badge(self.esp_label, "ESP32", esp.state)
            self.esp_label.setToolTip(f"índice {esp.score:.3f}, umbral {esp.threshold_on:.3f}, "
                                      f"cálculo {esp.proc_us / 1000:.1f} ms")
        return float(score[-1])

    def set_badge(self, label: QtWidgets.QLabel, who: str, state: str) -> None:
        text, fg, bg = self.STATE_STYLE.get(state, ("QUIETO", "#ffffff", "#27ae60"))
        label.setText(f"{who}: {text}")
        label.setStyleSheet(f"color: {fg}; background: {bg}; font-weight: bold; font-size: 14px; "
                            "padding: 4px 10px; border-radius: 4px; margin-right: 6px;")

    # ---------- refresco ----------

    def refresh(self) -> None:
        try:
            self._refresh()
        except Exception as exc:  # un error al dibujar no debe cerrar el visor
            import traceback
            traceback.print_exc()
            self.status.setText(f"⚠ Error al dibujar: {exc}")

    def _refresh(self) -> None:
        packets, arrivals, decisions = self.source.snapshot()
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

        rate = sum(1 for t in arrivals if now - t <= 1.0)
        rssi = packets[-1][1].rssi
        self.rate_hist.append((now, rate, rssi))
        while self.rate_hist and now - self.rate_hist[0][0] > HISTORY_SECONDS:
            self.rate_hist.popleft()

        mi = self.draw_detector(decisions, now)
        rh = np.array(self.rate_hist)
        self.rate_curve.setData(rh[:, 0] - now, rh[:, 1])
        self.rssi_curve.setData(rh[:, 0] - now, rh[:, 2])
        self.draw_events(now)

        last = packets[-1][1]
        st = self.source.stats
        parts = [f"{rate} paq/s", f"RSSI {rssi} dBm", f"canal {last.channel}", f"índice {mi:.3f}",
                 f"total {self.source.total}"]
        if st:
            parts.append(f"ESP32: {st.received_1s} paq/s, descartados {st.dropped_total}")
            if st.source == "tx":
                parts.append(f"perdidos en el aire {st.tx_lost_total}")
        esp = self.source.esp
        if esp:
            parts.append(f"detector ESP32: índice {esp.score:.3f}, {esp.proc_us / 1000:.1f} ms")
        tx = self.source.tx_info
        if tx:
            parts.append(f"TX {tx.ip} ({tx.fw_version})")
        errors = self.source.bad_lines + self.source.decoder.crc_errors
        if errors:
            parts.append(f"tramas malas {errors}")
        if self.source.backlog > 20000:
            parts.append(f"⚠ PC atrasada: {self.source.backlog} bytes en espera")
        if self.source.error:
            parts.append(f"⚠ {self.source.error}")
        self.status.setText(" | ".join(parts))

    def closeEvent(self, event) -> None:
        self.source.close()
        super().closeEvent(event)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", help="Puerto serial, por ejemplo COM5 o /dev/ttyUSB0")
    parser.add_argument("--baud", type=int, default=921600)
    parser.add_argument("--record", type=Path,
                        help="Grabar en este archivo (se crean <nombre>.csirec con los datos y <nombre>.json con las etiquetas)")
    parser.add_argument("--replay", type=Path, help="Reproducir una grabación (.csirec o .csv de la fase 0)")
    parser.add_argument("--no-reset", action="store_true", help="No reiniciar la placa al abrir el puerto")
    args = parser.parse_args()
    if not args.port and not args.replay:
        parser.error("indica --port o --replay")
    if args.record and args.replay:
        parser.error("--record solo funciona en vivo (con --port)")

    faulthandler.enable()  # si el proceso se cae sin mensaje, deja un rastro en la terminal
    app = QtWidgets.QApplication(sys.argv)
    source = Source(args.port, args.baud, args.replay, args.record, reset=not args.no_reset)
    viewer = Viewer(source, str(args.replay or args.port))
    viewer.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

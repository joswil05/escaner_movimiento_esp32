"""Grabaciones: flujo crudo del serial con marcas de tiempo (.csirec) + etiquetas (.json).

.csirec = b"CSIREC1\\n" y luego bloques: <f64 hora_pc><u32 largo><bytes>.
Guardar los bytes crudos permite reprocesar todo si cambia el decodificador.
Las grabaciones de texto de la fase 0 (.csv) también se pueden leer.
"""

from __future__ import annotations

import csv
import json
import struct
import time
from pathlib import Path
from typing import Iterator

from .proto import StreamDecoder

MAGIC = b"CSIREC1\n"
BLOCK = struct.Struct("<dI")


class RecordingWriter:
    def __init__(self, path: Path, meta: dict | None = None):
        self.path = path.with_suffix(".csirec")
        self.label_path = path.with_suffix(".json")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._f = open(self.path, "wb")
        self._f.write(MAGIC)
        self.labels = {"version": 1, "created": time.strftime("%Y-%m-%d %H:%M:%S"), "meta": meta or {},
                       "events": []}
        self._save_labels()

    def write(self, t: float, data: bytes) -> None:
        self._f.write(BLOCK.pack(t, len(data)))
        self._f.write(data)

    def add_event(self, t: float, kind: str, value=None) -> None:
        self.labels["events"].append({"t": round(t, 3), "type": kind, "value": value})
        self._save_labels()

    def _save_labels(self) -> None:
        self.label_path.write_text(json.dumps(self.labels, indent=1, ensure_ascii=False), encoding="utf-8")

    def close(self) -> None:
        if not self._f.closed:
            self._f.close()
            self._save_labels()


def read_blocks(path: Path) -> Iterator[tuple[float, bytes]]:
    """Bloques (hora_pc, bytes) de una grabación .csirec, o (hora_pc, línea) de un .csv de la fase 0."""
    path = Path(path)
    if path.suffix == ".csv":
        with open(path, newline="", encoding="utf-8") as f:
            for row in list(csv.reader(f))[1:]:
                yield float(row[0]), (row[1] + "\n").encode("ascii", "replace")
        return
    with open(path, "rb") as f:
        if f.read(len(MAGIC)) != MAGIC:
            raise ValueError(f"{path} no es una grabación .csirec")
        while True:
            head = f.read(BLOCK.size)
            if len(head) < BLOCK.size:
                return
            t, n = BLOCK.unpack(head)
            yield t, f.read(n)


def read_items(path: Path) -> Iterator[tuple[float, object]]:
    """Objetos decodificados (CsiPacket, CsiStats, TxInfo, str) con la hora de llegada a la PC."""
    dec = StreamDecoder()
    for t, data in read_blocks(path):
        for item in dec.feed(data):
            yield t, item


def load_labels(path: Path) -> dict:
    p = Path(path).with_suffix(".json")
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"events": []}

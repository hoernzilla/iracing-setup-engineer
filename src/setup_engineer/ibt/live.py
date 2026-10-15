"""Live-Zugriff auf iRacing über Shared Memory (nur Windows).

Gleicher Header wie die .ibt-Datei, aber mit bis zu 4 rotierenden
Datenpuffern. Wir lesen immer den Puffer mit dem höchsten Tick und prüfen
danach, ob er während des Lesens überschrieben wurde.

Noch ungetestet gegen ein laufendes iRacing – wird verifiziert, sobald
Live-Tests auf dem Windows-Rechner möglich sind.
"""

from __future__ import annotations

import mmap
import sys
import time
from functools import cached_property
from typing import Any

import numpy as np

from .format import HEADER_SIZE, VAR_HEADER_SIZE, Header, VarHeader, record_dtype
from .session_info import decode_session_info, parse_session_info

MEMMAP_NAME = "Local\\IRSDKMemMapFileName"
MEMMAP_SIZE = 1164 * 1024  # Größe, die auch pyirsdk verwendet
STATUS_CONNECTED = 1


class LiveSession:
    def __init__(self) -> None:
        if sys.platform != "win32":
            raise OSError("Live-Telemetrie ist nur unter Windows mit laufendem iRacing verfügbar")
        self._mm = mmap.mmap(-1, MEMMAP_SIZE, tagname=MEMMAP_NAME, access=mmap.ACCESS_READ)
        self._session_update = -1
        self._session_cache: dict[str, Any] = {}

    def close(self) -> None:
        self._mm.close()

    def __enter__(self) -> "LiveSession":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @property
    def header(self) -> Header:
        return Header.unpack(self._mm[:HEADER_SIZE])

    @property
    def connected(self) -> bool:
        return bool(self.header.status & STATUS_CONNECTED)

    @cached_property
    def var_headers(self) -> list[VarHeader]:
        h = self.header
        raw = self._mm[h.var_header_offset : h.var_header_offset + h.num_vars * VAR_HEADER_SIZE]
        return [VarHeader.unpack(raw, i * VAR_HEADER_SIZE) for i in range(h.num_vars)]

    @property
    def session_info(self) -> dict[str, Any]:
        h = self.header
        if h.session_info_update != self._session_update:
            raw = self._mm[h.session_info_offset : h.session_info_offset + h.session_info_len]
            self._session_cache = parse_session_info(decode_session_info(raw))
            self._session_update = h.session_info_update
        return self._session_cache

    def latest(self) -> np.void | None:
        """Neuesten vollständigen Datensatz lesen (oder None, wenn nicht verbunden)."""
        for _ in range(3):
            h = self.header
            if not h.status & STATUS_CONNECTED:
                return None
            bufs = h.var_bufs[: h.num_buf]
            buf = max(bufs, key=lambda b: b.tick_count)
            raw = bytes(self._mm[buf.buf_offset : buf.buf_offset + h.buf_len])
            # Prüfen, ob der Puffer während des Lesens überschrieben wurde
            again = Header.unpack(self._mm[:HEADER_SIZE])
            same = next(b for b in again.var_bufs if b.buf_offset == buf.buf_offset)
            if same.tick_count == buf.tick_count:
                return np.frombuffer(raw, dtype=record_dtype(self.var_headers, h.buf_len))[0]
            time.sleep(0.001)
        return None

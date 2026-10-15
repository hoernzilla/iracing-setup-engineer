"""Lesen von iRacing-.ibt-Telemetriedateien."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import cached_property
from pathlib import Path
from typing import Any

import numpy as np

from .format import (
    DISK_SUBHEADER_SIZE,
    HEADER_SIZE,
    VAR_HEADER_SIZE,
    DiskSubHeader,
    Header,
    VarHeader,
    record_dtype,
)
from .session_info import decode_session_info, parse_session_info


class IbtError(ValueError):
    """Datei ist keine gültige IBT-Datei oder beschädigt."""


@dataclass
class IbtFile:
    """Eine geöffnete .ibt-Datei.

    Die Datensätze werden per Memory-Map gelesen, d. h. auch große Dateien
    (eine Stunde ≈ 200 MB) werden nicht komplett in den Speicher geladen.
    """

    path: Path
    header: Header
    disk: DiskSubHeader
    var_headers: dict[str, VarHeader]
    session_info_text: str
    records: np.ndarray = field(repr=False)
    warnings: list[str] = field(default_factory=list)

    # ------------------------------------------------------------------ öffnen
    @classmethod
    def open(cls, path: str | os.PathLike[str]) -> "IbtFile":
        path = Path(path)
        size = path.stat().st_size
        if size < HEADER_SIZE + DISK_SUBHEADER_SIZE:
            raise IbtError(f"{path.name}: Datei zu klein ({size} Byte)")

        with open(path, "rb") as fh:
            head = fh.read(HEADER_SIZE + DISK_SUBHEADER_SIZE)
            header = Header.unpack(head)
            disk = DiskSubHeader.unpack(head)
            _validate_header(header, size, path.name)

            fh.seek(header.var_header_offset)
            raw_vars = fh.read(header.num_vars * VAR_HEADER_SIZE)
            fh.seek(header.session_info_offset)
            raw_info = fh.read(header.session_info_len)

        var_list = [VarHeader.unpack(raw_vars, i * VAR_HEADER_SIZE) for i in range(header.num_vars)]
        warnings: list[str] = []

        # Doppelte Namen kommen bei manchen Builds vor -> eindeutig machen
        seen: dict[str, int] = {}
        unique: list[VarHeader] = []
        for vh in var_list:
            if vh.name in seen:
                seen[vh.name] += 1
                warnings.append(f"Kanal {vh.name} doppelt vorhanden, zweites Vorkommen ignoriert")
                continue
            seen[vh.name] = 1
            unique.append(vh)

        data_offset = header.var_bufs[0].buf_offset
        available = (size - data_offset) // header.buf_len
        count = disk.session_record_count
        if count <= 0 or count > available:
            if count > available:
                warnings.append(
                    f"Subheader meldet {count} Datensätze, Datei enthält nur {available} (abgebrochene Aufnahme?)"
                )
            count = available

        dtype = record_dtype(unique, header.buf_len)
        records = np.memmap(path, dtype=dtype, mode="r", offset=data_offset, shape=(count,))

        return cls(
            path=path,
            header=header,
            disk=disk,
            var_headers={vh.name: vh for vh in unique},
            session_info_text=decode_session_info(raw_info),
            records=records,
            warnings=warnings,
        )

    # ------------------------------------------------------------- Metadaten
    @cached_property
    def session_info(self) -> dict[str, Any]:
        return parse_session_info(self.session_info_text)

    @property
    def tick_rate(self) -> int:
        return self.header.tick_rate or 60

    @property
    def record_count(self) -> int:
        return int(self.records.shape[0])

    @property
    def duration_s(self) -> float:
        return self.record_count / self.tick_rate

    @property
    def start_date(self) -> datetime:
        return datetime.fromtimestamp(self.disk.session_start_date, tz=timezone.utc)

    @property
    def car_name(self) -> str:
        di = self.session_info.get("DriverInfo", {}) or {}
        idx = di.get("DriverCarIdx")
        for d in di.get("Drivers", []) or []:
            if d.get("CarIdx") == idx:
                return str(d.get("CarScreenName") or d.get("CarPath") or "?")
        return "?"

    @property
    def car_path(self) -> str:
        di = self.session_info.get("DriverInfo", {}) or {}
        idx = di.get("DriverCarIdx")
        for d in di.get("Drivers", []) or []:
            if d.get("CarIdx") == idx:
                return str(d.get("CarPath") or "?")
        return "?"

    @property
    def track_name(self) -> str:
        wi = self.session_info.get("WeekendInfo", {}) or {}
        name = wi.get("TrackDisplayName") or wi.get("TrackName") or "?"
        cfg = wi.get("TrackConfigName")
        return f"{name} – {cfg}" if cfg else str(name)

    @property
    def track_length_m(self) -> float | None:
        wi = self.session_info.get("WeekendInfo", {}) or {}
        raw = str(wi.get("TrackLength", ""))
        try:
            value = float(raw.split()[0])
        except (ValueError, IndexError):
            return None
        return value * 1609.344 if "mi" in raw else value * 1000.0

    # --------------------------------------------------------------- Kanäle
    def has(self, name: str) -> bool:
        return name in self.var_headers

    def channel(self, name: str, *, dtype: Any = np.float64) -> np.ndarray:
        """Kanal als Array.

        Skalare Kanäle -> Länge = Anzahl Datensätze.
        Array-Kanäle (z. B. die 360-Hz-Federungskanäle *_ST mit 6 Werten pro
        60-Hz-Datensatz) -> 2D-Array (Datensätze, count).
        """
        if name not in self.var_headers:
            raise KeyError(f"Kanal {name!r} nicht vorhanden")
        arr = np.asarray(self.records[name])
        return arr.astype(dtype, copy=True) if dtype is not None else arr.copy()

    def channel_hi_res(self, name: str) -> np.ndarray:
        """Array-Kanal zeitlich ausgerollt (z. B. 60 Hz × 6 -> 360 Hz)."""
        arr = self.channel(name)
        return arr.reshape(-1) if arr.ndim == 2 else arr

    def get(self, name: str, default: float = np.nan) -> np.ndarray:
        """Kanal als 1D-Array (60 Hz) oder Array voller `default`, falls er fehlt.

        Hochaufgelöste Kanäle (in echten IBT-Dateien z. B. YawRate, LatAccel,
        *shockVel mit 6 Werten pro Datensatz) werden pro Datensatz gemittelt.
        """
        if self.has(name):
            arr = self.channel(name)
            return arr.mean(axis=1) if arr.ndim == 2 else arr
        return np.full(self.record_count, default, dtype=np.float64)

    def is_hi_res(self, name: str) -> bool:
        return self.has(name) and self.var_headers[name].count > 1

    def channel_names(self) -> list[str]:
        return list(self.var_headers)


def _validate_header(h: Header, size: int, name: str) -> None:
    problems = []
    if h.ver not in (1, 2):
        problems.append(f"unbekannte Version {h.ver}")
    if not (0 < h.num_vars < 10_000):
        problems.append(f"unplausible Kanalanzahl {h.num_vars}")
    if not (0 < h.buf_len < 1_000_000):
        problems.append(f"unplausible Datensatzlänge {h.buf_len}")
    if h.var_header_offset + h.num_vars * VAR_HEADER_SIZE > size:
        problems.append("Kanal-Header außerhalb der Datei")
    if h.session_info_offset + h.session_info_len > size:
        problems.append("Session-Info außerhalb der Datei")
    if not (0 < h.var_bufs[0].buf_offset <= size):
        problems.append("Datenbereich außerhalb der Datei")
    if problems:
        raise IbtError(f"{name}: keine gültige IBT-Datei ({'; '.join(problems)})")

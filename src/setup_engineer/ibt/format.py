"""Binäres Layout des iRacing-Telemetrieformats (irsdk_defines.h).

Live-Shared-Memory und .ibt-Datei teilen sich denselben Header; die .ibt-Datei
hat zusätzlich einen Disk-Subheader und speichert alle Datensätze hintereinander.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

import numpy as np

# irsdk_header: 10 int + 2 int Padding + 4 x irsdk_varBuf(4 int) = 112 Byte
HEADER_STRUCT = struct.Struct("<10i2i16i")
HEADER_SIZE = HEADER_STRUCT.size  # 112

# irsdk_diskSubHeader: time_t (int64), double, double, int, int = 32 Byte
DISK_SUBHEADER_STRUCT = struct.Struct("<qddii")
DISK_SUBHEADER_SIZE = DISK_SUBHEADER_STRUCT.size  # 32

# irsdk_varHeader: int type, int offset, int count, bool countAsTime, char pad[3],
#                  char name[32], char desc[64], char unit[32] = 144 Byte
VAR_HEADER_STRUCT = struct.Struct("<iii?3x32s64s32s")
VAR_HEADER_SIZE = VAR_HEADER_STRUCT.size  # 144

MAX_BUFS = 4

# irsdk_VarType -> numpy-Datentyp
VAR_TYPES: dict[int, np.dtype] = {
    0: np.dtype("<i1"),  # char
    1: np.dtype("?"),  # bool
    2: np.dtype("<i4"),  # int
    3: np.dtype("<u4"),  # bitField
    4: np.dtype("<f4"),  # float
    5: np.dtype("<f8"),  # double
}

VAR_TYPE_NAMES = {0: "char", 1: "bool", 2: "int", 3: "bitfield", 4: "float", 5: "double"}

# irsdk_TrkLoc
TRK_NOT_IN_WORLD = -1
TRK_OFF_TRACK = 0
TRK_IN_PIT_STALL = 1
TRK_APPROACHING_PITS = 2
TRK_ON_TRACK = 3


@dataclass(frozen=True)
class VarBuf:
    tick_count: int
    buf_offset: int


@dataclass(frozen=True)
class Header:
    ver: int
    status: int
    tick_rate: int
    session_info_update: int
    session_info_len: int
    session_info_offset: int
    num_vars: int
    var_header_offset: int
    num_buf: int
    buf_len: int
    var_bufs: tuple[VarBuf, ...]

    @classmethod
    def unpack(cls, raw: bytes | memoryview) -> "Header":
        v = HEADER_STRUCT.unpack_from(raw, 0)
        bufs = tuple(VarBuf(v[12 + 4 * i], v[13 + 4 * i]) for i in range(MAX_BUFS))
        return cls(*v[:10], var_bufs=bufs)

    def pack(self) -> bytes:
        flat: list[int] = list(
            (
                self.ver,
                self.status,
                self.tick_rate,
                self.session_info_update,
                self.session_info_len,
                self.session_info_offset,
                self.num_vars,
                self.var_header_offset,
                self.num_buf,
                self.buf_len,
                0,
                0,
            )
        )
        for b in self.var_bufs:
            flat += [b.tick_count, b.buf_offset, 0, 0]
        return HEADER_STRUCT.pack(*flat)


@dataclass(frozen=True)
class DiskSubHeader:
    session_start_date: int  # Unix-Zeit
    session_start_time: float
    session_end_time: float
    session_lap_count: int
    session_record_count: int

    @classmethod
    def unpack(cls, raw: bytes | memoryview) -> "DiskSubHeader":
        return cls(*DISK_SUBHEADER_STRUCT.unpack_from(raw, HEADER_SIZE))

    def pack(self) -> bytes:
        return DISK_SUBHEADER_STRUCT.pack(
            self.session_start_date,
            self.session_start_time,
            self.session_end_time,
            self.session_lap_count,
            self.session_record_count,
        )


def _cstr(raw: bytes) -> str:
    return raw.split(b"\x00", 1)[0].decode("latin-1").strip()


@dataclass(frozen=True)
class VarHeader:
    type: int
    offset: int
    count: int
    count_as_time: bool
    name: str
    desc: str
    unit: str

    @property
    def dtype(self) -> np.dtype:
        return VAR_TYPES[self.type]

    @property
    def type_name(self) -> str:
        return VAR_TYPE_NAMES.get(self.type, f"?{self.type}")

    @classmethod
    def unpack(cls, raw: bytes | memoryview, offset: int) -> "VarHeader":
        t, off, cnt, cat, name, desc, unit = VAR_HEADER_STRUCT.unpack_from(raw, offset)
        return cls(t, off, cnt, cat, _cstr(name), _cstr(desc), _cstr(unit))

    def pack(self) -> bytes:
        return VAR_HEADER_STRUCT.pack(
            self.type,
            self.offset,
            self.count,
            self.count_as_time,
            self.name.encode("latin-1")[:32],
            self.desc.encode("latin-1")[:64],
            self.unit.encode("latin-1")[:32],
        )


def record_dtype(var_headers: list[VarHeader], buf_len: int) -> np.dtype:
    """Strukturierter numpy-Typ für einen kompletten Datensatz (Zeile)."""
    names, formats, offsets = [], [], []
    for vh in var_headers:
        names.append(vh.name)
        formats.append(vh.dtype if vh.count == 1 else (vh.dtype, (vh.count,)))
        offsets.append(vh.offset)
    return np.dtype({"names": names, "formats": formats, "offsets": offsets, "itemsize": buf_len})

"""Synthetische IBT-Dateien für Tests und Demos.

Simuliert ein Auto auf einem einfachen Kurs mit bekannten, eingebauten
Eigenschaften, damit die Diagnose gegen eine bekannte Wahrheit geprüft
werden kann:

* Kurve 2 untersteuert im Scheitel/Ausgang konstant  -> erwartet "Auto"
* Kurve 3 untersteuert nur, wenn zu schnell angefahren -> erwartet "Fahrer"
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .ibt.format import (
    DISK_SUBHEADER_SIZE,
    HEADER_SIZE,
    VAR_HEADER_SIZE,
    DiskSubHeader,
    Header,
    VarBuf,
    VarHeader,
)

TICK = 60


@dataclass
class Segment:
    length_m: float
    radius_m: float | None = None  # None = Gerade
    direction: int = 1  # +1 links, -1 rechts


DEFAULT_TRACK = [
    Segment(600),
    Segment(90, 60, -1),  # T1 langsame Rechts
    Segment(350),
    Segment(160, 120, 1),  # T2 mittelschnelle Links (Auto untersteuert)
    Segment(400),
    Segment(120, 80, -1),  # T3 Rechts (Fahrer-abhängig)
    Segment(500),
    Segment(220, 200, 1),  # T4 schnelle Links
    Segment(300),
]


@dataclass
class SynthConfig:
    laps: int = 8
    seed: int = 1
    track: list[Segment] = field(default_factory=lambda: list(DEFAULT_TRACK))
    lat_g: float = 1.8
    vmax: float = 75.0
    accel: float = 6.0
    decel: float = 14.0
    steer_gain: float = 18.0  # rad Lenkrad pro 1/m
    car_understeer_t2: float = 0.25  # +25 % Lenkung in T2 ab Scheitel
    driver_understeer_t3: float = 0.08  # Lenküberschuss pro m/s zu viel Eingangstempo in T3
    lap_speed_jitter: float = 0.012
    spring_front: str = "180 N/mm"
    bump_gap_mm: float = 12.0
    hi_res: bool = True
    tricky_name: bool = True  # Sonderzeichen im Fahrernamen (YAML-Robustheit)
    # A-B-A im Auto: Runde -> Front-Stabi-Wert ab Rundenmitte (None = immer 1)
    arb_schedule: dict[int, float] | None = None
    arb_understeer_per_step: float = 0.05  # +5 % Lenküberschuss je Stufe härter
    arb_time_per_step: float = 0.004  # Tempoverlust je Stufe (relativ)


def _curvature(cfg: SynthConfig, ds: float) -> tuple[np.ndarray, np.ndarray]:
    kappa, seg_id = [], []
    for i, seg in enumerate(cfg.track):
        n = int(round(seg.length_m / ds))
        k = 0.0 if seg.radius_m is None else seg.direction / seg.radius_m
        kappa += [k] * n
        seg_id += [i] * n
    # Übergangsbögen wie auf echten Strecken (Krümmung baut sich über ~60 m auf)
    w = int(60 / ds)
    arr = np.array(kappa)
    padded = np.concatenate((arr[-w:], arr, arr[:w]))
    smooth = np.convolve(padded, np.ones(w) / w, mode="same")[w:-w]
    return smooth, np.array(seg_id)


def _speed_profile(kappa: np.ndarray, ds: float, cfg: SynthConfig, scale: float) -> np.ndarray:
    g = 9.81
    vlim = np.minimum(np.sqrt(cfg.lat_g * g * scale / np.maximum(np.abs(kappa), 1e-6)), cfg.vmax)
    v = vlim.copy()
    n = v.size
    for _ in range(2):  # zirkulär: zweimal durchlaufen
        for i in range(1, 2 * n):
            j, p = i % n, (i - 1) % n
            v[j] = min(v[j], np.sqrt(v[p] ** 2 + 2 * cfg.accel * ds))
        for i in range(2 * n - 2, -1, -1):
            j, q = i % n, (i + 1) % n
            v[j] = min(v[j], np.sqrt(v[q] ** 2 + 2 * cfg.decel * ds))
    return v


def generate(cfg: SynthConfig = SynthConfig()) -> tuple[dict[str, np.ndarray], str, int]:
    rng = np.random.default_rng(cfg.seed)
    ds = 0.5
    kappa, seg_id = _curvature(cfg, ds)
    n_pts = kappa.size
    length = n_pts * ds
    s_grid = np.arange(n_pts) * ds

    # Kurvenindizes für die eingebauten Effekte
    corner_ids = [i for i, seg in enumerate(cfg.track) if seg.radius_m]
    t2, t3 = corner_ids[1], corner_ids[2]
    t2_mask = seg_id == t2
    t2_idx = np.flatnonzero(t2_mask)
    t2_after_apex = np.zeros(n_pts, bool)
    t2_after_apex[t2_idx[len(t2_idx) // 3 :]] = True

    rows: dict[str, list[np.ndarray]] = {}
    lap_times = []
    fuel = 60.0
    t_total = 0.0

    def push(name: str, arr: np.ndarray) -> None:
        rows.setdefault(name, []).append(arr)

    arb_now = 1.0
    for lap in range(cfg.laps + 2):  # + Outlap + unvollständige letzte Runde
        arb_prev = arb_now
        if cfg.arb_schedule and lap in cfg.arb_schedule:
            arb_now = float(cfg.arb_schedule[lap])
        scale = 1.0 + rng.normal(0, cfg.lap_speed_jitter) - cfg.arb_time_per_step * (arb_now - 1)
        v_s = _speed_profile(kappa, ds, cfg, scale)
        # Fahrer fährt T3 mal zu schnell an (Lap-abhängig)
        t3_over = rng.uniform(0.0, 3.0)  # m/s zu viel Eingangstempo
        t3_mask = seg_id == t3
        v_s = v_s.copy()
        v_s[t3_mask] = np.minimum(v_s[t3_mask] + t3_over, cfg.vmax)
        # Überfahren kostet: schiebt das Auto, kommt es langsamer aus der Kurve
        after = np.flatnonzero(seg_id == t3 + 1)[: int(250 / ds)]
        v_s[after] = np.maximum(v_s[after] - 2.0 * t3_over, 10.0)

        # Zeit entlang der Strecke
        dt_s = ds / np.maximum(v_s, 1.0)
        t_s = np.concatenate(([0.0], np.cumsum(dt_s[:-1])))
        lap_time = float(t_s[-1] + dt_s[-1])
        n_t = int(np.floor(lap_time * TICK))
        if lap == cfg.laps + 1:
            n_t = n_t // 2  # Aufnahme endet mitten in der Runde
        tt = np.arange(n_t) / TICK
        s = np.interp(tt, t_s, s_grid)
        v = np.interp(s, s_grid, v_s)
        k = np.interp(s, s_grid, kappa)
        idx = np.minimum((s / ds).astype(int), n_pts - 1)

        # Lenkung = neutral × (1 + Untersteuern) + Rauschen
        us = np.zeros(n_t)
        us[t2_after_apex[idx]] += cfg.car_understeer_t2
        us[(seg_id[idx] == t3)] += cfg.driver_understeer_t3 * t3_over
        # Front-Stabi: ab Rundenmitte neuer Wert (Umstell-Runde enthält beide Werte)
        arb = np.where(np.arange(n_t) < n_t // 2, arb_prev, arb_now)
        us += cfg.arb_understeer_per_step * (arb - 1) * (np.abs(k) > 1 / 400)
        steer = cfg.steer_gain * k * (1 + us) + rng.normal(0, 0.004, n_t)

        dvdt = np.gradient(v, 1 / TICK)
        brake = np.clip(-dvdt / cfg.decel, 0, 1)
        brake[brake < 0.03] = 0
        throttle = np.where(dvdt > 0.2, 1.0, np.where(brake > 0, 0.0, 0.35))
        lat = k * v**2
        aero = (v / cfg.vmax) ** 2

        push("SessionTime", t_total + tt)
        push("Lap", np.full(n_t, lap, dtype=np.int32))
        push("LapDistPct", (s / length).astype(np.float32))
        push("LapDist", s.astype(np.float32))
        push("Speed", v.astype(np.float32))
        push("YawRate", (k * v).astype(np.float32))
        push("LatAccel", lat.astype(np.float32))
        push("LongAccel", dvdt.astype(np.float32))
        push("SteeringWheelAngle", steer.astype(np.float32))
        push("Brake", brake.astype(np.float32))
        push("Throttle", throttle.astype(np.float32))
        push("Gear", np.clip((v / 15).astype(int) + 1, 1, 6).astype(np.int32))
        push("RPM", (3000 + (v % 15) * 400).astype(np.float32))
        push("OnPitRoad", np.full(n_t, lap == 0, dtype=bool))
        push("PlayerTrackSurface", np.full(n_t, 3, dtype=np.int32))
        push("FuelLevel", (fuel - tt * 0.03).astype(np.float32))
        push("TrackTempCrew", np.full(n_t, 31.0 + lap * 0.1, dtype=np.float32))
        push("AirTemp", np.full(n_t, 22.0, dtype=np.float32))
        push("BrakeABSactive", (brake > 0.9) & (rng.random(n_t) < 0.5))
        push("dcAntiRollFront", arb.astype(np.float32))
        push("LapLastLapTime", np.full(n_t, lap_times[-1] if lap_times else 0.0, dtype=np.float32))
        for w, base in (("LF", 0.055), ("RF", 0.055), ("LR", 0.075), ("RR", 0.075)):
            front = w[1] == "F"
            rh = base - aero * (0.045 if front else 0.05) + rng.normal(0, 0.0008, n_t)
            push(f"{w}rideHeight", rh.astype(np.float32))
            defl = 0.004 + aero * 0.009 + np.abs(lat) * 0.0004 + rng.normal(0, 0.0005, n_t)
            vel = np.gradient(defl, 1 / TICK)
            if cfg.hi_res:
                # Wie in echten IBT-Dateien: 6 Werte (360 Hz) pro Datensatz unter dem normalen Namen
                push(f"{w}shockDefl", (np.repeat(defl[:, None], 6, axis=1)).astype(np.float32))
                hi = np.repeat(vel[:, None], 6, axis=1) + rng.normal(0, 0.02, (n_t, 6))
                push(f"{w}shockVel", hi.astype(np.float32))
            else:
                push(f"{w}shockDefl", defl.astype(np.float32))
                push(f"{w}shockVel", vel.astype(np.float32))
        fuel -= lap_time * 0.03
        t_total += n_t / TICK
        lap_times.append(lap_time)

    data = {k_: np.concatenate(v_) for k_, v_ in rows.items()}
    name = "Max Müller: \"Tester\" #1" if cfg.tricky_name else "Max Mueller"
    yaml_text = f"""---
WeekendInfo:
 TrackName: synth_ring
 TrackDisplayName: Synth Ring
 TrackConfigName: GP
 TrackLength: {length / 1000:.2f} km
DriverInfo:
 DriverCarIdx: 0
 Drivers:
 - CarIdx: 0
   UserName: {name}
   CarScreenName: Synth GT3
   CarPath: synthgt3
CarSetup:
 UpdateCount: 3
 TiresAero:
  LeftFront:
   StartingPressure: 152.0 kPa
   LastHotPressure: 168.0 kPa
 Chassis:
  LeftFront:
   CornerWeight: 3010 N
   RideHeight: 55.0 mm
   SpringRate: {cfg.spring_front}
   BumpRubberGap: {cfg.bump_gap_mm:.1f} mm
   Camber: -3.8 deg
  RightFront:
   SpringRate: {cfg.spring_front}
   BumpRubberGap: {cfg.bump_gap_mm:.1f} mm
   Camber: -3.6 deg
  LeftRear:
   SpringRate: 150 N/mm
   BumpRubberGap: 30.0 mm
  RightRear:
   SpringRate: 150 N/mm
   BumpRubberGap: 30.0 mm
  Front:
   ArbAdj: 1
  InCarDials:
   BrakePressureBias: 54.5%
   AbsSetting: 4 (ABS)
   TractionControlSetting: 3 (TC)
...
"""
    return data, yaml_text, len(lap_times)


def write_ibt(path: str | Path, data: dict[str, np.ndarray], session_yaml: str, lap_count: int = 0) -> Path:
    path = Path(path)
    names = list(data)
    n = len(next(iter(data.values())))
    var_headers, offset = [], 0
    type_map = {np.dtype("bool"): 1, np.dtype("int32"): 2, np.dtype("float32"): 4, np.dtype("float64"): 5}
    for name in names:
        arr = data[name]
        t = type_map[arr.dtype]
        count = 1 if arr.ndim == 1 else arr.shape[1]
        var_headers.append(VarHeader(t, offset, count, False, name, f"synthetisch: {name}", ""))
        offset += arr.dtype.itemsize * count
    buf_len = offset

    info = session_yaml.encode("latin-1", errors="replace") + b"\x00"
    var_off = HEADER_SIZE + DISK_SUBHEADER_SIZE
    info_off = var_off + len(names) * VAR_HEADER_SIZE
    data_off = info_off + len(info)

    header = Header(
        ver=2, status=1, tick_rate=TICK, session_info_update=0, session_info_len=len(info),
        session_info_offset=info_off, num_vars=len(names), var_header_offset=var_off,
        num_buf=1, buf_len=buf_len,
        var_bufs=(VarBuf(n, data_off), VarBuf(0, 0), VarBuf(0, 0), VarBuf(0, 0)),
    )
    t = data.get("SessionTime", np.zeros(1))
    disk = DiskSubHeader(1_760_000_000, float(t[0]), float(t[-1]), lap_count, n)

    rec = bytearray(buf_len * n)
    view = np.frombuffer(rec, dtype=np.uint8).reshape(n, buf_len)
    for vh, name in zip(var_headers, names):
        arr = np.ascontiguousarray(data[name]).reshape(n, -1)
        raw = arr.view(np.uint8).reshape(n, -1)
        view[:, vh.offset : vh.offset + raw.shape[1]] = raw

    with open(path, "wb") as fh:
        fh.write(header.pack())
        fh.write(disk.pack())
        for vh in var_headers:
            fh.write(vh.pack())
        fh.write(info)
        fh.write(bytes(rec))
    return path


def make_file(path: str | Path, cfg: SynthConfig = SynthConfig()) -> Path:
    data, yaml_text, laps = generate(cfg)
    return write_ibt(path, data, yaml_text, laps)

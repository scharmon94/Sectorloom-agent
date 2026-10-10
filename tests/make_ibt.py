"""
Writes a synthetic but structurally real .ibt file.

It exists so the Python parser and the browser parser can be handed the
exact same bytes and their answers compared. The driving is invented; the
file layout is not.
"""
import math
import os
import struct
import sys

import numpy as np

HZ = 60
TRACK_LEN = 3200.0          # metres
LAPS = int(os.environ.get("IBT_LAPS", "9"))
# The knobs below are read from the environment so one script can make
# several different-looking sessions. The site needs them now that it
# ships no example laps: a screenshot of three identical sessions looks
# exactly as synthetic as it is.
PIT_AFTER = int(os.environ.get("IBT_PIT", "4"))   # stint boundary
OFF_LAP = int(os.environ.get("IBT_OFF", "2"))     # a dirty lap
SEED = int(os.environ.get("IBT_SEED", "7"))       # the driving noise
T_TRACK = os.environ.get("IBT_TTRACK", "94.00")
T_AIR = os.environ.get("IBT_TAIR", "77.00")
HUMID = os.environ.get("IBT_HUMID", "46")
SKIES = os.environ.get("IBT_SKIES", "Partly Cloudy")
USAGE = os.environ.get("IBT_USAGE", "moderate usage")
LAT0, LON0 = 37.2, -78.4

# name, type code, numpy dtype
CHANNELS = [
    ("SessionTime",        5, "<f8"),
    ("Lap",                2, "<i4"),
    ("LapDistPct",         4, "<f4"),
    ("Speed",              4, "<f4"),
    ("Throttle",           4, "<f4"),
    ("Brake",              4, "<f4"),
    ("SteeringWheelAngle", 4, "<f4"),
    ("Gear",               2, "<i4"),
    ("RPM",                4, "<f4"),
    ("Lat",                5, "<f8"),
    ("Lon",                5, "<f8"),
    ("LatAccel",           4, "<f4"),
    ("OnPitRoad",          1, "<u1"),
    ("PlayerTrackSurface", 2, "<i4"),
    ("FuelLevel",          4, "<f4"),
    ("TrackTempCrew",      4, "<f4"),
    ("AirTemp",            4, "<f4"),
    ("RelativeHumidity",   4, "<f4"),
    ("WindVel",            4, "<f4"),
    ("TrackWetness",       2, "<i4"),
    ("Precipitation",      4, "<f4"),
    # added with the web app's seventh update, so parity covers the
    # channels the fuel and tyre widgets are built on
    ("LongAccel",          4, "<f4"),
    ("LFspeed",            4, "<f4"),
    ("RFspeed",            4, "<f4"),
    ("LRspeed",            4, "<f4"),
    ("RRspeed",            4, "<f4"),
    # car attitude, the aids, and the tyre readings
    ("Yaw",                4, "<f4"),
    ("YawRate",            4, "<f4"),
    ("VelocityX",          4, "<f4"),
    ("VelocityY",          4, "<f4"),
    ("SessionNum",         2, "<i4"),
    ("BrakeABSactive",     1, "<u1"),
    ("dcTractionControl",  4, "<f4"),
    ("LFwearL",         4, "<f4"),
    ("LFwearM",         4, "<f4"),
    ("LFwearR",         4, "<f4"),
    ("RFwearL",         4, "<f4"),
    ("RFwearM",         4, "<f4"),
    ("RFwearR",         4, "<f4"),
    ("LRwearL",         4, "<f4"),
    ("LRwearM",         4, "<f4"),
    ("LRwearR",         4, "<f4"),
    ("RRwearL",         4, "<f4"),
    ("RRwearM",         4, "<f4"),
    ("RRwearR",         4, "<f4"),
    ("LFtempCL",        4, "<f4"),
    ("LFtempCM",        4, "<f4"),
    ("LFtempCR",        4, "<f4"),
    ("RFtempCL",        4, "<f4"),
    ("RFtempCM",        4, "<f4"),
    ("RFtempCR",        4, "<f4"),
    ("LRtempCL",        4, "<f4"),
    ("LRtempCM",        4, "<f4"),
    ("LRtempCR",        4, "<f4"),
    ("RRtempCL",        4, "<f4"),
    ("RRtempCM",        4, "<f4"),
    ("RRtempCR",        4, "<f4"),
]

WIDTH = {0: 1, 1: 1, 2: 4, 3: 4, 4: 4, 5: 8}

YAML = f"""---
WeekendInfo:
 TrackName: synthetic_park
 TrackID: 999
 TrackDisplayName: Synthetic Park
 TrackConfigName: Club
 TrackCity: Farmville
 TrackCountry: USA
 TrackLength: 3.20 km
 TrackNumTurns: 9
 TrackType: road course
 TrackSurfaceTemp: {T_TRACK} F
 TrackAirTemp: {T_AIR} F
 TrackRelativeHumidity: {HUMID} %
 TrackWindVel: 8.50 mph
 TrackWindDir: SW
 TrackSkies: {SKIES}
 TrackFogLevel: 0 %
 TrackPrecipitation: 0 %
 TrackCleanup: 1
 TrackDynamicTrackState: Dynamic
 TrackUsage: {USAGE}
 TrackAltitude: 410 ft
 TrackPitSpeedLimit: 60.00 kph
 SubSessionID: 70001234
 SeriesID: 0
 EventType: Practice
 Official: 0
 WeekendOptions:
  TimeOfDay: 2:30 pm
  IsFixedSetup: 0
DriverInfo:
 DriverCarIdx: 0
 Drivers:
 - CarIdx: 0
   UserName: Test Driver
   CarScreenName: Synthetic GT3
   CarID: 77
   CarClassShortName: GT3
   CarNumber: "94"
   TeamName: ""
   IRating: 2140
   LicLevel: 13
   LicSubLevel: 321
   LicString: B 3.21
SessionInfo:
 Sessions:
 - SessionNum: 0
   SessionType: Practice
SplitTimeInfo:
 Sectors:
 - SectorNum: 0
   SectorStartPct: 0.000000
 - SectorNum: 1
   SectorStartPct: 0.340000
 - SectorNum: 2
   SectorStartPct: 0.670000
CarSetup:
 UpdateCount: 7
 Tires:
  LeftFront:
   ColdPressure: 24.0 psi
   Camber: -3.4 deg
  RightFront:
   ColdPressure: 24.0 psi
   Camber: -3.4 deg
 Chassis:
  Front:
   ArbSize: Medium
   ToeIn: -0.06 in
  Rear:
   WingSetting: 7
...
"""


def tyre_row(lap):
    """iRacing only refreshes these when a tyre comes off the car, so they
    hold flat and then step at the stop."""
    fresh = lap <= PIT_AFTER
    wear = [1.00, 1.00, 1.00] if fresh else [0.88, 0.81, 0.92]
    temp = [76.0, 78.0, 74.0] if fresh else [92.0, 99.0, 88.0]
    out = []
    for ci in range(4):
        out.extend(max(0.0, wear[pi] - ci * 0.014) for pi in range(3))
    for ci in range(4):
        out.extend(temp[pi] + ci * 3 for pi in range(3))
    return tuple(out)


def build_channels():
    """A lap of plausible driving, repeated with a little variation."""
    rows = []
    t = 300.0
    fuel = 42.0
    rng = np.random.default_rng(SEED)

    for lap in range(LAPS):
        wobble = 1.0 + 0.012 * rng.standard_normal()
        n_lap = int(HZ * (74.0 * wobble))
        for i in range(n_lap):
            p = i / n_lap
            # three slow corners per lap
            corner = math.sin(p * 2 * math.pi * 3)
            base = 46.0 + 16.0 * corner
            speed = max(12.0, base * wobble)
            if lap == OFF_LAP and 0.40 < p < 0.46:
                speed *= 0.80
            accel = 16.0 * math.cos(p * 2 * math.pi * 3)
            thr = max(0.0, min(1.0, 0.55 + accel / 20))
            brk = max(0.0, min(1.0, -accel / 18))
            if thr > 0.05:
                brk = 0.0
            pit = 1 if (lap == PIT_AFTER and p > 0.95) else 0
            if lap == PIT_AFTER + 1 and p < 0.05:
                pit = 1
            if pit:
                speed = min(speed, 18.0)

            ang = p * 2 * math.pi
            r = 420 + 90 * math.sin(3 * ang + 0.4)
            x, y = r * math.cos(ang), 0.72 * r * math.sin(ang)

            gear = max(1, min(6, int(speed / 11) + 1))
            surface = 0 if (lap == OFF_LAP and 0.41 < p < 0.45) else 3
            fuel -= thr * 0.0016

            # a wheel locking under heavy braking and the rears lighting
            # up out of the slow corners, so the slip trace has something
            # real in it on both sides of the comparison
            lock = (brk - 0.8) * 0.5 if brk > 0.8 else 0.0
            spin = 0.06 if (thr > 0.8 and gear <= 3) else 0.0
            # a couple of degrees of body slip through the corners
            slip_rad = max(-0.07, min(0.07, corner * 0.05))

            rows.append((
                t, lap, p, speed, thr, brk,
                math.atan(corner) * 2.6 + 0.02 * math.sin(t * 6),
                gear, 4200 + speed * 55,
                LAT0 + y / 110540, LON0 + x / (111320 * math.cos(math.radians(LAT0))),
                speed * speed * 0.0006 * corner,
                pit, surface, max(0.0, fuel),
                34.5, 25.0, 0.46, 2.4, 1, 0.0,
                accel,
                speed * (1 - lock), speed * (1 - lock * 0.85),
                speed * (1 + spin), speed * (1 + spin * 0.9),
                math.atan2(y, x),                      # Yaw
                speed * 0.0006 * corner,               # YawRate
                speed * math.cos(slip_rad), speed * math.sin(slip_rad),
                0,                                     # SessionNum
                1 if brk > 0.9 else 0,                 # BrakeABSactive
                4.0,                                   # dcTractionControl
            ) + tyre_row(lap))
            t += 1.0 / HZ

    return rows


def write_ibt(path: str) -> None:
    rows = build_channels()
    n = len(rows)

    # byte offset of each channel inside one record
    offsets = {}
    cursor = 0
    for name, code, _ in CHANNELS:
        offsets[name] = cursor
        cursor += WIDTH[code]
    buf_len = cursor

    var_off = 144
    info_off = var_off + len(CHANNELS) * 144
    info_bytes = YAML.encode("latin-1")
    data_off = info_off + len(info_bytes)

    header = bytearray(144)
    struct.pack_into("<i", header, 0, 2)              # version
    struct.pack_into("<i", header, 4, 1)              # status
    struct.pack_into("<i", header, 8, HZ)             # tick rate
    struct.pack_into("<i", header, 16, len(info_bytes))
    struct.pack_into("<i", header, 20, info_off)
    struct.pack_into("<i", header, 24, len(CHANNELS))
    struct.pack_into("<i", header, 28, var_off)
    struct.pack_into("<i", header, 36, buf_len)
    struct.pack_into("<i", header, 52, data_off)
    struct.pack_into("<i", header, 140, n)            # record count

    var_block = bytearray()
    for name, code, _ in CHANNELS:
        entry = bytearray(144)
        struct.pack_into("<i", entry, 0, code)
        struct.pack_into("<i", entry, 4, offsets[name])
        struct.pack_into("<i", entry, 8, 1)           # count
        entry[16:16 + len(name)] = name.encode("ascii")
        var_block += entry

    body = bytearray(n * buf_len)
    for r, row in enumerate(rows):
        base = r * buf_len
        for (name, code, dtype), value in zip(CHANNELS, row):
            off = base + offsets[name]
            raw = np.array([value], dtype=dtype).tobytes()
            body[off:off + len(raw)] = raw

    with open(path, "wb") as fh:
        fh.write(header)
        fh.write(var_block)
        fh.write(info_bytes)
        fh.write(body)

    print(f"wrote {path}: {n} samples, {len(header)+len(var_block)+len(info_bytes)+len(body)} bytes, "
          f"record {buf_len} bytes")


if __name__ == "__main__":
    write_ibt(sys.argv[1] if len(sys.argv) > 1 else "synthetic.ibt")

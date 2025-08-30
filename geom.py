"""
Geometry & scoring helpers for runway assignment from a single snapshot.
This module is import-only (no top-level execution).
"""
from __future__ import annotations

from typing import TypedDict, Optional, List, Dict, Any, Tuple
import math

# -------------------- Types --------------------
class RunwayDir(TypedDict):
    """One landing direction for a runway (e.g., '33L')."""
    id: str                 # '33L', '34R', etc.
    lat_thr: float          # threshold latitude (deg)
    lon_thr: float          # threshold longitude (deg)
    course_deg: float       # landing course (deg true, 0..360)
    elev_ft: float          # runway threshold elevation (feet)

class AircraftState(TypedDict):
    """Minimal fields from your parsed state vector needed here."""
    callsign: str
    lat: float
    lon: float
    track_deg: float        # true track in degrees (0..360)
    velocity_mps: float     # ground speed (m/s)
    geo_alt: Optional[float]
    baro_alt: Optional[float]

class ScoreParams(TypedDict, total=False):
    track_gate_deg: float      # default 20
    xtrack_gate_nm: float      # default 0.3
    w_track: float             # default 0.5
    w_xtrack: float            # default 0.5
    use_distance: bool         # default False
    d_peak_nm: float           # default 8
    d_span_nm: float           # default 8
    w_dist: float              # default 0.1 (only if use_distance)

DEFAULT_PARAMS: ScoreParams = {
    "track_gate_deg": 20.0,
    "w_track": 0.45,
    "w_xtrack": 0.45,
    "use_distance": True,    # enable distance nudge to help disambiguate 33 vs 34
    "d_peak_nm": 4.0,        # short final peak (typical 3–6 NM); tune as needed
    "d_span_nm": 6.0,        # fades by ±6 NM
    "w_dist": 0.10,          # light weight; increase to 0.20 if needed
}

# -------------------- Angle & small math helpers --------------------
NM_PER_M = 1.0 / 1852.0
R_EARTH_M = 6_371_000.0

def wrap_180(deg: float) -> float:
    """Wrap any angle (deg) to (-180, +180]."""
    x = (deg + 180.0) % 360.0 - 180.0
    return -180.0 if x == 180.0 else x

def ang_diff_deg(a: float, b: float) -> float:
    """Smallest absolute angular difference (deg) between headings a and b."""
    return abs(wrap_180(a - b))

def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial great-circle bearing from point1 -> point2 (deg true, 0..360)."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dlam = math.radians(lon2 - lon1)
    y = math.sin(dlam) * math.cos(phi2)
    x = math.cos(phi1)*math.sin(phi2) - math.sin(phi1)*math.cos(phi2)*math.cos(dlam)
    th = math.degrees(math.atan2(y, x))
    th = (th + 360.0) % 360.0
    return th

def haversine_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in nautical miles."""
    R_nm = 3440.065
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = phi2 - phi1
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi/2.0)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlam/2.0)**2
    return 2.0 * R_nm * math.asin(math.sqrt(a))

# -------------------- Local ENU & runway vectors --------------------

def en_from_threshold(lat: float, lon: float, lat_thr: float, lon_thr: float) -> Tuple[float, float]:
    """Convert (lat,lon) -> local East/North meters relative to a threshold."""
    phi0 = math.radians(lat_thr)
    dphi = math.radians(lat - lat_thr)
    dlam = math.radians(lon - lon_thr)
    north_m = dphi * R_EARTH_M
    east_m  = dlam * math.cos(phi0) * R_EARTH_M
    return east_m, north_m

def runway_unit_vectors(course_deg: float) -> Tuple[Tuple[float,float], Tuple[float,float]]:
    """
    Return (a, r) unit vectors for the runway:
      a = along-centerline (toward landing direction)
      r = right-lateral (perpendicular, pointing to the RIGHT of 'a')
    In EN coordinates: heading 0° = +North, 90° = +East.
    """
    th = math.radians(course_deg)
    # Along (east, north)
    a_e = math.sin(th)
    a_n = math.cos(th)
    # Right lateral (rotate along by -90°): (cosθ, -sinθ)
    r_e = math.cos(th)
    r_n = -math.sin(th)
    return (a_e, a_n), (r_e, r_n)

# -------------------- Core geometry & scoring --------------------

def cross_along_nm(ac_lat: float, ac_lon: float, rw: RunwayDir) -> Tuple[float, float, float]:
    """
    Compute cross-track (NM), along-track (NM), and straight-line distance (NM)
    from runway threshold to the aircraft, using local ENU + runway unit vectors.
    cross-track sign is positive to the RIGHT of the runway direction.
    """
    east_m, north_m = en_from_threshold(ac_lat, ac_lon, rw["lat_thr"], rw["lon_thr"])
    (a_e, a_n), (r_e, r_n) = runway_unit_vectors(rw["course_deg"])
    # Dot products
    s_m = east_m * a_e + north_m * a_n     # along
    x_m = east_m * r_e + north_m * r_n     # cross (signed)
    d_m = math.hypot(east_m, north_m)      # straight-line
    return x_m * NM_PER_M, s_m * NM_PER_M, d_m * NM_PER_M


def runway_fit_score(ac: AircraftState, rw: RunwayDir, params: ScoreParams = DEFAULT_PARAMS) -> Tuple[bool, float, Dict[str, float]]:
    """
    Returns: (passes_hard_gates, score_in_0_1, debug_terms)
      - Hard gates: Δtrack <= track_gate_deg, |xtrack| <= xtrack_gate_nm
      - Score ∈ [0,1]: combines track alignment and cross-track tightness
    """
    dtrack = ang_diff_deg(ac["track_deg"], rw["course_deg"])  # Δtrack
    x_nm, s_nm, d_nm = cross_along_nm(ac["lat"], ac["lon"], rw)

    # Hard gates
    if dtrack > params["track_gate_deg"]:
        return False, 0.0, {"dtrack": dtrack, "x_nm": x_nm, "d_nm": d_nm}
    if abs(x_nm) > params["xtrack_gate_nm"]:
        return False, 0.0, {"dtrack": dtrack, "x_nm": x_nm, "d_nm": d_nm}

    # Normalized terms (clipped 0..1)
    T = max(0.0, 1.0 - dtrack / params["track_gate_deg"])  # track fit
    X = max(0.0, 1.0 - abs(x_nm) / params["xtrack_gate_nm"])  # cross-track fit

    score = params["w_track"] * T + params["w_xtrack"] * X

    if params.get("use_distance", False):
        D_peak = params.get("d_peak_nm", 8.0)
        D_span = max(1e-6, params.get("d_span_nm", 8.0))
        D = max(0.0, 1.0 - abs(d_nm - D_peak) / D_span)
        score = (1.0 - params["w_dist"]) * score + params["w_dist"] * D

    return True, float(min(1.0, max(0.0, score))), {
        "dtrack": dtrack, "x_nm": x_nm, "s_nm": s_nm, "d_nm": d_nm,
        "T": T, "X": X
    }


def confidence_from_terms(dtrack_deg: float, x_nm: float) -> str:
    ad = abs(dtrack_deg)
    ax = abs(x_nm)
    if ad <= 10.0 and ax <= 0.20:
        return "high"
    if ad <= 20.0 and ax <= 0.40:
        return "medium"
    return "low"

def assign_runway_for_aircraft(ac: AircraftState, runways: List[RunwayDir], params: ScoreParams = DEFAULT_PARAMS) -> Dict[str, Any]:
    """
    Evaluate all runway directions and return the best assignment.
    Returns a dict with:
      {
        'callsign': ...,
        'best_id': '33L' | None,
        'best_score': float,
        'debug': { runway_id: { 'pass': bool, 'score': float, 'dtrack':..., 'x_nm':..., 'd_nm':... }, ... }
      }
    If no runway passes hard gates: best_id = None, best_score = 0.
    """
    results: Dict[str, Dict[str, float]] = {}
    best_id: Optional[str] = None
    best_score = 0.0
    best_tiebreak = (float("inf"), float("inf"), float("inf"))  # |x|, Δtrack, d

    for rw in runways:
        passed, score, dbg = runway_fit_score(ac, rw, params)
        results[rw["id"]] = {"pass": float(passed), "score": score, **dbg}
        if not passed:
            continue
        # tie-breaker: smaller |x|, then smaller Δtrack, then smaller d
        tiebreak = (abs(dbg["x_nm"]), dbg["dtrack"], dbg["d_nm"])
        if (score > best_score) or (math.isclose(score, best_score) and tiebreak < best_tiebreak):
            best_id = rw["id"]
            best_score = score
            best_tiebreak = tiebreak

    return {
        "callsign": ac.get("callsign", ""),
        "best_id": best_id,
        "best_score": best_score,
        "debug": results,
    }


def assign_runways(aircraft: List[AircraftState], runways: List[RunwayDir], params: ScoreParams = DEFAULT_PARAMS) -> List[Dict[str, Any]]:
    """Vectorized convenience: run assignment for many aircraft."""
    out = []
    for ac in aircraft:
        out.append(assign_runway_for_aircraft(ac, runways, params))
    return out


# -------------------- ICN runway table (fill with authoritative coords if needed) --------------------
# These thresholds/courses are approximate (good enough for classification). Replace with AIP values if available.
RUNWAYS: List[RunwayDir] = [
    {"id":"33L", "lat_thr": 37.4542, "lon_thr":126.4608, "course_deg":333.0, "elev_ft": 23.0},
    {"id":"33R", "lat_thr": 37.4540, "lon_thr":126.4437, "course_deg":333.0, "elev_ft": 23.0},
    {"id":"34L", "lat_thr": 37.4762, "lon_thr":126.4155, "course_deg":340.0, "elev_ft": 23.0},
    {"id":"34R", "lat_thr": 37.4728, "lon_thr":126.4317, "course_deg":340.0, "elev_ft": 23.0},
    {"id":"15L", "lat_thr": 37.4818, "lon_thr":126.4363, "course_deg":153.0, "elev_ft": 23.0},
    {"id":"15R", "lat_thr": 37.4802, "lon_thr":126.4500, "course_deg":153.0, "elev_ft": 23.0},
    {"id":"16L", "lat_thr": 37.4728, "lon_thr":126.4417, "course_deg":160.0, "elev_ft": 23.0},
    {"id":"16R", "lat_thr": 37.4789, "lon_thr":126.4149, "course_deg":160.0, "elev_ft": 23.0},
]
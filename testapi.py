"""
ICN Arrival Sequencer — snapshot runner (testapi.py)
- Fetch a bbox snapshot (fixed URL, no auth)
- Parse & filter to airborne, descending targets near ICN
- Assign most-likely runway (both directions considered) using geom.py
- Print a per-aircraft summary with score & confidence
"""
from __future__ import annotations

from typing import Any, Dict, List
import requests

# Minimal scoring params to avoid KeyError in geom
PARAMS = {
    "track_gate_deg": 20.0,
    "xtrack_gate_nm": 0.3,
    "w_track": 0.5,
    "w_xtrack": 0.5,
    "use_distance": False,
}

from geom import (
    RUNWAYS,
    assign_runway_for_aircraft,
    haversine_nm,            # used for threshold-distance filter
)

# ---- OpenSky bbox fetch (fixed URL, kept simple) ----
# ~60 NM radius around ICN. Adjust these numbers if needed; keep format the same.
open_sky_base = (
    "https://opensky-network.org/api/states/all?"
    "lamin=36.46333&lomin=125.180146&lamax=38.46333&lomax=127.699854"
)

# ---------- Fetch & parse ----------

def get_plane_data() -> Dict[str, Any]:
    """Fetch raw JSON from OpenSky using the fixed URL."""
    resp = requests.get(open_sky_base, timeout=15)
    resp.raise_for_status()
    return resp.json()


def parse_states(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Turn OpenSky list-of-lists into friendly dicts, safely."""
    rows: List[Dict[str, Any]] = []
    for st in data.get("states", []) or []:
        if not isinstance(st, (list, tuple)) or len(st) < 17:
            continue
        row = {
            "icao24": st[0],
            "callsign": (st[1] or "").strip(),
            "origin_country": st[2],
            "time_position": st[3],
            "last_contact": st[4],
            "lon": st[5],
            "lat": st[6],
            "baro_alt": st[7],
            "on_ground": st[8],
            "velocity_mps": st[9],
            "track_deg": st[10],
            "vertical_rate_mps": st[11],
            "geo_alt": st[13],
            "squawk": st[14],
            "position_source": st[16],
        }
        if row["lat"] is None or row["lon"] is None:
            continue
        rows.append(row)
    return rows

# ---------- Filters ----------

def filter_airborne(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    # airborne & moving a bit
    return [r for r in rows if not r.get("on_ground") and (r.get("velocity_mps") or 0) > 10]


def filter_descending(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [r for r in rows if r.get("vertical_rate_mps") is not None and r["vertical_rate_mps"] < 0]


def filter_within_nm_any_threshold(rows: List[Dict[str, Any]], max_nm: float) -> List[Dict[str, Any]]:
    # Keep if within max_nm of the nearest ICN runway threshold
    out = []
    for r in rows:
        dmin = float("inf")
        for rw in RUNWAYS:
            d = haversine_nm(rw["lat_thr"], rw["lon_thr"], r["lat"], r["lon"])
            if d < dmin:
                dmin = d
        if dmin <= max_nm:
            r["dist_nm"] = dmin
            out.append(r)
    return out

# ---------- Confidence bucketing ----------

def confidence_from_terms(dtrack_deg: float, x_nm: float) -> str:
    ad = abs(dtrack_deg)
    ax = abs(x_nm)
    if ad <= 10.0 and ax <= 0.20:
        return "high"
    if ad <= 20.0 and ax <= 0.40:
        return "medium"
    return "low"

# ---------- Main ----------
if __name__ == "__main__":
    try:
        raw = get_plane_data()
    except requests.HTTPError as e:
        print("HTTP error:", e)
        print(getattr(e.response, "text", ""))
        raise

    rows = parse_states(raw)
    rows = filter_airborne(rows)
    rows = filter_descending(rows)
    rows = filter_within_nm_any_threshold(rows, max_nm=10.0)

    print(f"Descending aircraft within 10 NM of any ICN runway threshold: {len(rows)}")

    # Sort by nearest to any threshold, then print assignment per aircraft
    rows_sorted = sorted(rows, key=lambda x: x.get("dist_nm", 999.0))

    for r in rows_sorted:
        # Prepare AircraftState for the assigner
        ac = {
            "callsign": r.get("callsign", ""),
            "lat": r["lat"],
            "lon": r["lon"],
            "track_deg": r["track_deg"],
            "velocity_mps": r.get("velocity_mps") or 0.0,
            "geo_alt": r.get("geo_alt"),
            "baro_alt": r.get("baro_alt"),
        }
        assign = assign_runway_for_aircraft(ac, RUNWAYS, PARAMS)
        best = assign["best_id"]
        score = assign["best_score"]

        # Pull debug terms for the chosen runway (Δtrack, x_nm, d_nm)
        if best is not None and best in assign["debug"] and assign["debug"][best].get("pass", 0) == 1:
            dbg = assign["debug"][best]
            conf = confidence_from_terms(dbg.get("dtrack", 999.0), dbg.get("x_nm", 999.0))
            dtrack = dbg.get("dtrack", float("nan"))
            x_nm = dbg.get("x_nm", float("nan"))
            d_nm = dbg.get("d_nm", float("nan"))
        else:
            conf = "unknown"
            dtrack = float("nan")
            x_nm = float("nan")
            d_nm = r.get("dist_nm", float("nan"))

        gs_kts = (r.get("velocity_mps") or 0) * 1.94384
        alt_m = r.get("geo_alt") if r.get("geo_alt") is not None else r.get("baro_alt")
        ident = (r.get("callsign") or r.get("icao24") or "").strip()

        extra = ""
        print(
            f"{ident:>8}  d={d_nm:>4.1f}NM  hdg={r['track_deg']:6.1f}°  alt={alt_m:>6}m  "
            f"→  {(best or '—'):>3}  score={score:0.2f}  conf={conf:>6}  "
            f"(Δtrack={dtrack:>5.1f}°, xtrack={x_nm:>4.2f}NM)" + extra
        )

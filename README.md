# airport_runway
Predicts which Incheon Intl (RKSI) runway an aircraft is likely to land on by comparing a live(ish) state snapshot to published final-approach geometry.

# ICN Arrival Sequencer — Runway Prediction Prototype

Predicts which **Incheon International Airport (RKSI)** runway an aircraft is most likely to land on using **ADS-B state data** and published approach geometry.

⚠️ **Disclaimer:** This is a **research/academic prototype**. Not for operational or safety-critical use.

---

## ✈️ Project Overview

This project ingests aircraft state vectors (position, track, altitude, velocity) from the [OpenSky Network API](https://opensky-network.org), then compares them against all possible RKSI runway approaches.  

We designed a simple **4-step scoring logic**:

1. **Heading check** — Compare aircraft true track with each runway’s inbound course. If the difference ≤ 20°, keep candidate.
2. **Cross-track distance** — Compute lateral offset to the runway centerline. If ≤ 0.3 NM, keep candidate.
3. **Score calculation** — Combine heading alignment and cross-track error into a likelihood score.
4. **Runway selection** — Pick the runway with the highest score.


---

## ⚙️ Installation

1. Clone this repo:
   ```bash
   git clone https://github.com/darrenkim05/icn-arrival-sequencer.git
   cd icn-arrival-sequencer

2.	Install dependencies:

pip install -r requirements.txt


## Usage:

Run the main script
python testapi.py

## Example output

Descending aircraft within 10 NM of any ICN runway threshold: 3
  KAL123  d= 5.4NM  hdg= 152.8°  alt= 1210m  →  15L  score=0.84  conf=  high  (Δtrack=  1.2°, xtrack=0.08NM)
  AAR807  d= 7.1NM  hdg= 331.1°  alt= 1460m  →  33R  score=0.77  conf=medium  (Δtrack=  8.5°, xtrack=0.26NM)
  TNA889  d= 9.8NM  hdg= 153.5°  alt= 2100m  →   —   score=0.42  conf=unknown (Δtrack=   nan°, xtrack= nanNM)

	•	d = distance to nearest threshold (NM)
	•	hdg = aircraft true track (degrees)
	•	alt = altitude (meters)
	•	→ = predicted runway ID
	•	score = likelihood score
	•	conf = heuristic confidence (high/medium/low)



## Current Accuracy
	•	On sample data, prediction accuracy is ~65%.
	•	Main limitation: RKSI has parallel runways (15L/15R, 33L/33R) that are very close together, making geometry-only prediction difficult.
	•	ATC vectoring and late runway changes also reduce predictability.


## Roadmap / Improvements
Ideas for Version 2:
	•	Add wind-based prior (use METAR to weight runway usage).
	•	Use altitude error vs 3° glide slope at current distance.
	•	Add localizer deviation scoring (angular likelihood instead of hard cutoff).
	•	Apply temporal smoothing (α-β or Kalman filter).
	•	Introduce an “uncertain” category for closely scored parallels.



## Acknowledgments
	•	OpenSky Network for the public ADS-B API
	•	ICAO charts for published Instrument Approach Procedures (IAPs)
	•	Built as a student aerospace engineering project (with some ChatGPT-assisted coding)

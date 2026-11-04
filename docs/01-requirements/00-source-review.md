# Source Document Review — Rolling Clearance System (RCS)

**Status: ORIGINAL DOCUMENT NOT AVAILABLE — baseline reconstructed from the Master Prompt.**
Date of review: 2026-11-04

## 1. What was searched

| Location | Result |
|---|---|
| Workspace `c:\Users\muchi\Downloads\Soko-Mind-main` | Contains only the unrelated *Soko Mind* farming app (React/Vite/Gemini). No RCS material. |
| `C:\Users\muchi\Downloads` (file names containing *rolling*, *clearance*, *weigh*, *kifaru*, *portos*, *proposal*) | No matches. |
| Untitled WhatsApp PDFs/DOCX in Downloads | Course reports (transmission lines, cellphone detector), textbooks, a CV. Not RCS. |
| April-2026 photographs in Downloads | Complex-analysis coursework and personal photos. Not RCS handwritten notes. |
| Session uploads | None. |

**Action required from the project owner:** place the original *Rolling Clearance System* proposal and scans of the handwritten notes in
`kifaru-portos/docs/01-requirements/source/` (any format). The traceability matrix has a `Source` column that currently cites
"Master Prompt §x"; when the originals arrive every row will be re-cited to a page/paragraph of the original and the
Preserve / Enhance / Replace / New disposition will be re-validated.

## 2. Reconstructed baseline — the original RCS concept

The Master Prompt (§2, §3 Modules 1–2, §16 "Preserve the original weighing and rolling-clearance concept") describes the
original idea with enough detail to reconstruct it. The original Rolling Clearance System is understood to be:

1. **Weigh-in-motion (WIM) lane** on the Northern Corridor approach to the Mariakani weighbridge (and later Port of Mombasa gates)
   that measures axle loads and gross vehicle mass (GVM) while the truck is moving.
2. **Automatic truck identification** at the lane (ANPR camera and/or RFID tag) so the measurement is tied to a registered vehicle.
3. **A three-colour clearance decision** — GREEN (continue without stopping), AMBER (go to static scale for verification),
   RED (suspected overload / non-compliance, inspection).
4. **The static weighbridge remains the legal reference**; the rolling lane only *pre-screens* so that compliant trucks are not stopped.
5. **A digital weighing ticket / record** for every event so that the stop-or-go decision is auditable.
6. **Reduction of queues, idling and fuel wastage** at Mariakani as the primary benefit.

Items that the Master Prompt marks as *new* for KIFARU PORTOS (and therefore were not in the original) are: predictive queue
intelligence, backhaul marketplace, digital cargo passport, predictive cargo release, small-cargo-owner platform, environmental
intelligence, multi-agent AI, digital twin, and the full live-cloud platform.

## 3. Disposition summary

| Disposition | Meaning | Examples |
|---|---|---|
| **Preserve** | Original concept kept as-is because it is the core value and legally correct | WIM pre-screen; static scale as legal reference; GREEN/AMBER/RED |
| **Enhance** | Original concept kept but made rigorous | Add measurement-uncertainty and sensor-health gating to the decision; evidence record; identity confidence; conservative margins |
| **Replace** | Original approach superseded by a technically necessary one | HX711-class 80 SPS load-cell ADC → 24-bit simultaneous-sampling delta-sigma ADC at 5–10 kHz/channel; single sensor → multi-sensor fusion |
| **New** | Introduced by KIFARU PORTOS | Modules 3–9, cloud platform, digital twin, stakeholder apps |

## 4. Open questions for the owner (to be answered from the original document)

1. Which weighbridge(s) did the original target — Mariakani only, or also Athi River / Gilgil / Webuye?
2. Did the original specify a sensor technology (piezo-quartz, piezo-polymer, bending plate, load cell)?
3. Did the original propose any lane geometry (number of sensor rows, spacing, lane length)?
4. Was there a stated target accuracy or vehicle speed range?
5. Which regulator interactions (KeNHA, KRA, NTSA) did the original envisage?
6. Did the handwritten notes contain circuit sketches or firmware pseudocode that should be preserved verbatim?

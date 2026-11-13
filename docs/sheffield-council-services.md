# Sheffield City Council: problem-reporting services

Source: https://www.sheffield.gov.uk/all-services and the linked report pages. Fetched 13 Nov 2026.
Purpose: understand how each problem is reported today, to design a unified multimodal (text + image) agent front door (Public Services track).

## Verification status

- **Verified** = stated on the council page I read.
- **Not stated** = the page does not say. It may still be true of the live form.
- The online forms (`forms.sheffield.gov.uk`) are JavaScript-rendered. A fetch of the street light form returned only the password and account scaffolding, so **field lists, map/location widgets and photo upload on the forms themselves are unverified** except where noted. Open each form in a browser before relying on any of this.
- URL paths are inconsistent on the council site (`/pollution-nuisance/` vs `/pollution-and-nuisance/`). Some links may be stale redirects.

## Cross-cutting findings

| Aspect | Finding |
|---|---|
| Channels | Online form (primary), phone `0114 273 4567`, general "Ask us a question" form, post/visit (Howden House, 1 Union Street, S1 2SH). Social media and WhatsApp channel exist for comms, not shown as report routes. |
| Form platform | All problem reports go to `forms.sheffield.gov.uk/site/portal/form/<name>`. Over 100 forms across the site (My Account page). One shared portal means one integration pattern. |
| Reference numbers | Form portal issues a reference when a form is saved; "Resume existing" needs reference + password. Individual service pages mostly do not mention references. |
| Tracking | **My Account** tracks online form enquiries with updates at each stage. Optional: offered when submitting a form, or via Register (email verification). It does not replace separate accounts for Council Tax, council housing, parking permits, school places, planning. |
| Accessibility | SignLive BSL interpreting 24/7. A site banner currently advises phoning for urgent matters (Microsoft outage). |
| Photo upload | Only confirmed for **abandoned vehicles** (optional). Not stated for potholes, street lights, missed bins, fly-tipping, noise. |
| Location capture | Not stated on any service page. Free-text description (fly-tipping asks location, date, time, description, quantity). |
| Who actually fixes it | Split across bodies, so the user must know who owns the problem (see "Routing" below). |

### Routing: ownership split (strong case for an agent)

| Problem | Owner |
|---|---|
| Adopted roads and pavements | Council, repaired by **Amey** under the Streets Ahead contract |
| A631 Tinsley Viaduct Lower Deck, A616 Stocksbridge Bypass, motorways | **National Highways** |
| Private roads, car parks | Not council-maintained |
| Missed bins | Council waste services; delays published by **Veolia** |
| Untaxed/SORN vehicle on public road | **DVLA** (`gov.uk/report-untaxed-vehicle`) |
| Obstructing vehicle | **South Yorkshire Police** |
| Burnt-out/suspicious vehicle | Police, 101 |
| Genuinely abandoned vehicle | Council form |
| Domestic noise (private household) | Neighbour first, then writing, then **MESH** mediation, then council action |
| Noise from commercial premises, council tenants | Council directly |
| Fly-tipping on own land | Paid removal via Environmental Services (`0114 203 7411`) |

## Top services for the demo

Ranked by fit to a text + image agent: high volume, visually evidenced, clear triage rules.

### 1. Potholes and road/pavement defects
- **Form:** `/site/portal/form/report_pothole_crack`, linked from `/roads-pavements/report-problems/report-road-problems`. Phone: 0114 273 4567.
- **Categories on the hub page:** pothole or crack; road/pavement surface; hedges, plants, grass; drainage/blocked drain; missing or damaged road markings or cat's eyes; damaged or missing kerbs; manholes and stopcock covers; general and dangerous litter. Also damaged speed bumps.
- **Triage rules (verified):** Category 1 (immediate safety risk) made safe within 24 hours, permanent repair usually within 28 days. Category 2 (no immediate risk) fixed through planned maintenance, no timescale. Priority by size, depth, road usage, risk to drivers/cyclists/pedestrians. No numeric depth thresholds published.
- **Inspection cadence:** A/B roads monthly, link roads every 3 months, residential streets annually (from a search summary of the council page; not re-read directly). Resident reports fill the gaps.
- **Not stated:** photo upload, location method, required fields, update notifications.
- **Agent value:** image classification (pothole vs crack vs kerb vs drain), severity estimate to suggest Category 1/2, ownership check (adopted vs private vs National Highways), correct form selection.

### 2. Street lighting and street furniture
- **Form:** `/site/portal/form/report_street_light`. Phone: 0114 273 4567.
- **Covers:** street lights and electrics, lamp posts, temporary barriers around lights, unauthorised attachments (flags, banners). Offensive flags: removal attempted within 24 hours. Graffiti or safety-risk attachments prioritised.
- **Related:** traffic lights, crossings, road signs (`/roads-pavements/report-problems/faults-traffic-lights-crossings-road-signs`); bridges, subways, retaining walls (`/roads-pavements/faults-bridges-subways-retaining-walls`); highway debris/spillages (`/roads-pavements/report-problems/report-highway-debris`).
- **Not stated:** lamp column number capture, photo upload, timescales for ordinary faults. LED lights are centrally monitored, so some faults are detected without a report.
- **Agent value:** read column number from a photo (OCR), distinguish lighting fault from other furniture, escalate safety risks.

### 3. Fly-tipping and litter
- **Form:** `/site/form/auto/report_fly_tipping` (also seen as `/site/portal/form/report_fly_tipping`). Page: `/pollution-nuisance/fly-tipping-and-litter/report-fly-tipping-public-land`. Online or by phone (no number given on that page).
- **Info requested (verified):** location, date, time, description, quantity of waste. Safety advice: do not touch or move waste, it may be hazardous or evidence.
- **Scope:** highway, roads, lanes, verges, public rights of way. Own land goes to paid removal.
- **Enforcement:** investigated if evidence of origin exists. Costs may be recoverable through the courts.
- **Not stated:** photo upload, anonymity, response timescale. A separate "Hot Spot areas" mapping project (`haveyoursay.sheffield.gov.uk`) accepts photo uploads via a pop-up, but it is a different tool.
- **Agent value:** image to extract waste type, quantity estimate, hazard flags (asbestos, needles), and any identifying evidence. Strong visual use case.

### 4. Missed bin collection
- **Route:** `wasteservices.sheffield.gov.uk` (linked from `/bins-waste-recycling/about-your-bins/report-missed-collection`).
- **Eligibility (verified):** check Veolia service alerts first. Report only if the bin was not emptied **and** no tag or sticker was left. If a tag was left, the page explains the cause.
- **SLA (verified):** council returns within 1 working day to empty the bin, or contacts you within 1 working day to explain why.
- **Related:** replacement bin (`/bins-waste-recycling/about-your-bins/request-new-replacement-bin`), bulky waste, green/garden waste. Damaged or missing bin routing is not stated.
- **Not stated:** photo upload, reference number.
- **Agent value:** pre-flight eligibility (alerts, tag present from a photo of the bin), address lookup, route to correct form (missed vs replacement vs bulky).

### 5. Abandoned or untaxed vehicles
- **Form:** `/site/portal/form/report_abandoned_vehicle`. Page: `/pollution-and-nuisance/vehicles/abandoned-untaxed-vehicles`.
- **Photo:** optional upload (**only service where upload is confirmed**). Asks for make, model, plate, colour, location.
- **Eligibility rules (verified):** taxed vehicles generally not abandoned. Under about 3 weeks usually not abandoned. Indicators: broken or missing windows, missing plates, flat or missing tyres, significant damage, unroadworthy appearance. Untaxed/SORN goes to DVLA. Obstruction goes to police. Burnt-out goes to police 101.
- **Process after report:** inspection, letter to last keeper (10 days), removal and 10-day storage, £250 fixed penalty plus fees, destruction if unpaid. Court: up to £2,500 and/or 3 months.
- **Agent value:** best-defined decision tree of all services. Photo gives plate OCR, tyre/window condition, and the agent can route to DVLA, police or council.

### 6. Noise nuisance
- **Form:** `/site/portal/form/report_noise`. Page: `/pollution-nuisance/noise-pollution/report-noise-nuisance`.
- **Rules (verified):** **anonymous complaints not accepted.** Private households: talk to the neighbour, write, then MESH mediation, then formal action. Commercial premises and council tenants: report directly. "No immediate response available."
- **Evidence:** downloadable noise log (Word), returned by post or email. Neighbour questionnaire to corroborate. Audio/video upload not mentioned.
- **After submission:** case officer named, kept informed. No reference number or timescale stated.
- **Agent value:** multimodal evidence (audio clips, diary), structured log generation, advising the pre-escalation steps. Lower demo priority: slow process, identity required.

### 7. Graffiti and fly-posting
- **Pages:** `/pollution-nuisance/report-graffiti`, `/pollution-nuisance/report-fly-posting`. Hub: `/pollution-and-nuisance/graffiti-fly-posters`.
- **Not read:** the two report pages themselves (hub gave only links). Details unknown.
- **Agent value:** image classification; public vs private property determines owner.

### 8. Parking issues
- **Hub:** `/parking`. Incorrectly parked vehicle reporting is listed under `/parking/car-parks`, with no separate URL or method found.
- **Fines:** pay (`/parking/fines/pay-parking-bus-lane-moving-traffic-or-caz-fine`) and appeal (`/clean-air-zone-sheffield/charges-and-refunds/appeal-parking-bus-lane-moving-traffic-or-clean-air-zone-fine`). Appeal submission method not stated.
- **Also:** permits, Blue Badge, dropped kerbs/disabled bays/bay suspensions (`/parking/request-adjustments`).
- **Agent value:** appeals are an evidence-heavy (photo of signage/bay, PCN OCR) multimodal case. Permits and Blue Badge use separate accounts, so poor fit for a unified front door.

### 9. Complaints about the council itself
- **Route:** `/your-city-council/feedback-complaints`, then "Make a complaint about a Council service" (`.../complaints-procedure/make-complaint-about-council-service`). Separate route for Members' Code of Conduct breaches.
- **Not read:** stages, timescales, Ombudsman escalation, exclusions. The complaints procedure page was not fetched.
- **Agent value:** the "complaints" half of the brief. Agent can detect when a report is really a service complaint (e.g. repeated missed collection) and route it.

## Out of scope for this demo (reporting exists but different model)

- **Housing repairs:** `/council-housing/repairs`, with disrepair claims advice (`/council-housing/repairs/help-and-advice-repairs-and-disrepair-claims`). Not read. Tenant-specific, needs authentication.
- **Public health pest control, social care, Council Tax, benefits:** separate accounts, sensitive data.
- **Street trees:** `/roads-pavements/street-trees`. Not read.
- **Planning enforcement:** under `/planning-development`. Not read.

## Implications for the unified agent

1. **Single front door fits the platform.** Every report maps to one form on one portal plus one phone line. An agent can emit a structured payload per form.
2. **Triage is the real value, not form-filling.** Ownership (Amey, Veolia, DVLA, police, National Highways, MESH) and eligibility rules (bin tag, vehicle age, noise anonymity) are scattered across pages.
3. **Image modality has most leverage on:** potholes, fly-tipping, abandoned vehicles, street light column numbers, graffiti, bin tags. Text modality: noise, complaints, appeals. Audio is a candidate for noise evidence.
4. **No public API found.** Not checked exhaustively. Assume form submission is browser-only, so a hackathon demo should generate the completed form payload and a pre-filled summary rather than submit to live council forms. Do not submit test reports to production forms.
5. **Gaps to confirm in a browser** before design lock: actual field lists, whether location uses a map or address lookup, upload limits, whether login is required to submit, and reference/update behaviour.
6. **Privacy:** noise requires identity. Photos of vehicles, plates and people are personal data. Local inference (judging criterion) is a good fit.

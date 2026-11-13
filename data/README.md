# Data

Place local datasets here. Raw data files are git-ignored (see `.gitignore`); only this file and small samples are committed.

## Files

- **`sheffield_issues_only.json`** - 11 Sheffield-specific issues (filtered by coordinates)
- **`sheffield_fixmystreet_issues.json`** - All 1,000 issues in the "sheffield" jurisdiction
- **`fixmystreet_services_list.txt`** - 2,594 available service types on FixMyStreet
- **`usage.jsonl`** - Access log of the dummy council site at `/mock/`, written by the app (`src/app/usage.py`). Submit events include the problem's location (`location`, `lat`, `lon`, `geo_source`). Not committed.
- **`mock_submissions.jsonl`** - Mock-form submissions made by the form agents (`src/app/council_form.py`), without reporter details. Coordinates in `le_gis` ("lat,lon"); `geo_source` is set when they were geocoded from typed text. Shown at `/dashboard`. Not committed.
- **`reports.jsonl`** - Reports filed by the chat agent's `file_report` tool (`src/app/tools.py`). `geo` holds `lat`, `lon`, the matched address and the lookup `source`, or `null` if the location couldn't be found. Not committed.

## Sheffield Issues Data Schema

### Issue Fields

| Field | Type | Description |
|-------|------|-------------|
| `service_request_id` | Integer | Unique identifier for this issue |
| `service_code` | String | Machine-readable code for the service type |
| `service_name` | String | Human-readable name (e.g., "Potholes", "Flytipping", "Graffiti") |
| `title` | String | Short title of the issue |
| `description` | String | Full description: service name + details |
| `detail` | String | Detailed description of the issue |
| `status` | String | `"open"` or `"closed"` |
| `lat` | String | Latitude (WGS84) |
| `long` | String | Longitude (WGS84) |
| `requested_datetime` | String | ISO 8601: when reported |
| `updated_datetime` | String | ISO 8601: last update |
| `agency_sent_datetime` | String | ISO 8601: when sent to agency |
| `agency_responsible` | Object | `{recipient: ["Council Name"]}` |
| `interface_used` | String | How reported ("Android", "desktop", "iPhone") |
| `media_url` | String | Optional URL to attached photo |
| `requestor_name` | String | Reporter name (if public) |

### Example Issue

```json
{
  "service_request_id": 10366216,
  "service_code": "Flytipping",
  "service_name": "Flytipping",
  "title": "Flytipping",
  "description": "Flytipping: Flytipping up gennel General litter on both Adkins Drive and Road.",
  "detail": "Flytipping up gennel General litter on both Adkins Drive and Road.",
  "status": "open",
  "lat": "53.414745",
  "long": "-1.485263",
  "requested_datetime": "2026-11-13T10:26:58+00:00",
  "updated_datetime": "2026-11-13T10:27:00+00:00",
  "agency_sent_datetime": "2026-11-13T10:27:00+00:00",
  "agency_responsible": {"recipient": ["Sheffield City Council"]},
  "interface_used": "Android"
}
```

## Top Issue Types in Sheffield (11 issues)

1. **Flytipping** (3) - Illegal waste dumping
2. **Potholes** (1) - Road damage
3. **Graffiti** (1) - Vandalism
4. **Pavements/footpaths** (1) - Maintenance
5. **Rubbish/Recycling** (1) - Bin management
6. **Roads/highways** (1) - Road issues
7. **Other** (2) - Miscellaneous (parked car, property leak)

## Provenance

| File | Source | URL | Licence | Date retrieved |
|------|--------|-----|---------|----------------|
| sheffield_issues_only.json | FixMyStreet Open311 API | https://www.fixmystreet.com/open311/v2/requests.json?jurisdiction_id=sheffield | Public Domain | 2026-11-13 |
| sheffield_fixmystreet_issues.json | FixMyStreet Open311 API | https://www.fixmystreet.com/open311/v2/requests.json?jurisdiction_id=sheffield | Public Domain | 2026-11-13 |
| fixmystreet_services_list.txt | FixMyStreet Open311 API | https://www.fixmystreet.com/open311/v2/services.json?jurisdiction_id=fixmystreet | Public Domain | 2026-11-13 |

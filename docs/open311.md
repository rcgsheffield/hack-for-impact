# Open311 API Specification

The **Open311 API** is a standard for handling civic issues (potholes, broken lights, graffiti, etc.) reported by citizens to local councils. It provides a unified interface for discovering services and querying/posting citizen reports.

**Reference**: [Open311.org](http://www.open311.org/)  
**FixMyStreet Implementation**: https://www.fixmystreet.com/open311/

---

## Core Concepts

- **Jurisdiction**: A local authority or council (e.g., "sheffield", "fixmystreet")
- **Service**: A type of civic issue the council handles (e.g., "Pothole", "Graffiti", "Flytipping")
- **Service Request**: A citizen report of an issue (e.g., "Pothole at Main St")
- **Service Code**: Machine-readable unique identifier for a service type
- **Service Request ID**: Unique identifier for a specific citizen report

---

## API Endpoints

### 1. Get Services

Retrieve all available service types for a jurisdiction.

**Endpoint:**
```
GET /open311/v2/services.json
```

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `jurisdiction_id` | String | Yes | The jurisdiction code (e.g., "sheffield", "fixmystreet") |

**Example Request:**
```bash
curl "https://www.fixmystreet.com/open311/v2/services.json?jurisdiction_id=sheffield"
```

**Example Response:**
```json
{
  "services": [
    {
      "type": "realtime",
      "metadata": "false",
      "service_code": "Pothole",
      "service_name": "Pothole or other road damage",
      "description": "Report a pothole or other damage to the road surface"
    },
    {
      "type": "realtime",
      "metadata": "false",
      "service_code": "Flytipping",
      "service_name": "Flytipping",
      "description": "Report illegal waste dumping"
    }
  ]
}
```

**Response Fields:**
| Field | Type | Description |
|-------|------|-------------|
| `service_code` | String | Machine-readable unique identifier |
| `service_name` | String | Human-readable name |
| `description` | String | Description of what this service covers |
| `type` | String | "realtime" (immediate response expected) or "batch" (delayed) |
| `metadata` | String | "true" or "false" - whether extended metadata available |

---

### 2. Get Service Requests

Retrieve citizen reports of issues for a jurisdiction.

**Endpoint:**
```
GET /open311/v2/requests.json
```

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `jurisdiction_id` | String | Yes | The jurisdiction code |
| `service_request_id` | String | No | Get a specific request by ID |
| `service_code` | String | No | Filter by service type (e.g., "Pothole") |
| `status` | String | No | "open" or "closed" |
| `updated_after` | String | No | ISO 8601 timestamp filter |
| `limit` | Integer | No | Max results per page (default 1000) |
| `offset` | Integer | No | Pagination offset |

**Example Request (all open issues):**
```bash
curl "https://www.fixmystreet.com/open311/v2/requests.json?jurisdiction_id=sheffield&status=open"
```

**Example Request (specific service type):**
```bash
curl "https://www.fixmystreet.com/open311/v2/requests.json?jurisdiction_id=sheffield&service_code=Pothole"
```

**Example Response:**
```json
{
  "service_requests": [
    {
      "service_request_id": 10366216,
      "service_code": "Flytipping",
      "service_name": "Flytipping",
      "title": "Flytipping up gennel",
      "description": "Flytipping: General litter on both Adkins Drive and Road.",
      "detail": "Flytipping up gennel General litter on both Adkins Drive and Road.",
      "status": "open",
      "lat": "53.414745",
      "long": "-1.485263",
      "requested_datetime": "2026-11-13T10:26:58+00:00",
      "updated_datetime": "2026-11-13T10:27:00+00:00",
      "agency_sent_datetime": "2026-11-13T10:27:00+00:00",
      "agency_responsible": {
        "recipient": ["Sheffield City Council"]
      },
      "interface_used": "Android",
      "media_url": "https://www.fixmystreet.com/photo/10366216.0.full.jpeg?token"
    }
  ]
}
```

**Response Fields:**
| Field | Type | Description |
|-------|------|-------------|
| `service_request_id` | Integer | Unique identifier for this report |
| `service_code` | String | Service type code (matches service_code from Services endpoint) |
| `service_name` | String | Human-readable service name |
| `title` | String | Short title of the issue |
| `description` | String | Full description |
| `detail` | String | Detailed description |
| `status` | String | "open" or "closed" |
| `lat` | String | Latitude (WGS84) |
| `long` | String | Longitude (WGS84) |
| `requested_datetime` | String | ISO 8601 - when reported |
| `updated_datetime` | String | ISO 8601 - last update |
| `agency_sent_datetime` | String | ISO 8601 - when sent to responsible agency |
| `agency_responsible` | Object | `{recipient: ["Council Name"]}` |
| `interface_used` | String | How reported ("web", "mobile", "phone", etc.) |
| `media_url` | String | URL to attached photo (optional) |
| `requestor_name` | String | Reporter name (if public) |

---

### 3. Get Single Service Request

Retrieve details for a specific issue.

**Endpoint:**
```
GET /open311/v2/requests.json?service_request_id={id}
```

**Example Request:**
```bash
curl "https://www.fixmystreet.com/open311/v2/requests.json?jurisdiction_id=sheffield&service_request_id=10366216"
```

---

### 4. Create Service Request (POST)

Post a new citizen report to the system.

**Endpoint:**
```
POST /open311/v2/requests.json
```

**Required Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `jurisdiction_id` | String | The jurisdiction |
| `service_code` | String | Service type code |
| `lat` | Float | Latitude |
| `long` | Float | Longitude |
| `address_string` | String | OR use lat/long |

**Optional Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `title` | String | Short title |
| `description` | String | Full description |
| `name` | String | Reporter name |
| `phone` | String | Reporter phone |
| `email` | String | Reporter email |
| `media` | File | Photo attachment |

**Example Request:**
```bash
curl -X POST "https://www.fixmystreet.com/open311/v2/requests.json" \
  -F "jurisdiction_id=sheffield" \
  -F "service_code=Pothole" \
  -F "lat=53.3827" \
  -F "long=-1.4701" \
  -F "title=Large pothole on Main Street" \
  -F "description=Pothole about 30cm wide blocking lane" \
  -F "name=John Smith" \
  -F "email=john@example.com" \
  -F "media=@photo.jpg"
```

**Example Response:**
```json
{
  "service_requests": [
    {
      "service_request_id": 10366999,
      "service_code": "Pothole",
      "service_name": "Pothole or other road damage",
      "status": "open",
      "requested_datetime": "2026-11-13T10:50:00+00:00"
    }
  ]
}
```

---

## Implementation Guide: Mocking a Council Endpoint

To create a mock council endpoint, implement these endpoints:

### Minimal Mock Implementation

**1. Services Endpoint**
```python
@app.get("/open311/v2/services.json")
def get_services(jurisdiction_id: str):
    services = [
        {
            "type": "realtime",
            "metadata": "false",
            "service_code": "pothole",
            "service_name": "Pothole or other road damage",
            "description": "Report a pothole"
        },
        {
            "type": "realtime",
            "metadata": "false",
            "service_code": "graffiti",
            "service_name": "Graffiti",
            "description": "Report graffiti or vandalism"
        }
    ]
    return {"services": services}
```

**2. Requests Endpoint (GET)**
```python
@app.get("/open311/v2/requests.json")
def get_requests(
    jurisdiction_id: str,
    service_code: str = None,
    status: str = None,
    limit: int = 1000,
    offset: int = 0
):
    # Load or generate mock issues
    issues = load_issues_from_db()
    
    # Filter
    if service_code:
        issues = [i for i in issues if i["service_code"] == service_code]
    if status:
        issues = [i for i in issues if i["status"] == status]
    
    # Paginate
    issues = issues[offset:offset+limit]
    
    return {"service_requests": issues}
```

**3. Requests Endpoint (POST)**
```python
@app.post("/open311/v2/requests.json")
def create_request(
    jurisdiction_id: str,
    service_code: str,
    lat: float,
    long: float,
    title: str = None,
    description: str = None,
    name: str = None,
    email: str = None
):
    # Create new issue
    new_id = generate_id()
    issue = {
        "service_request_id": new_id,
        "service_code": service_code,
        "status": "open",
        "lat": str(lat),
        "long": str(long),
        "title": title,
        "description": description,
        "requested_datetime": datetime.utcnow().isoformat() + "Z",
        "updated_datetime": datetime.utcnow().isoformat() + "Z",
        "agency_responsible": {"recipient": ["Your Council"]}
    }
    
    # Save to database
    save_issue(issue)
    
    return {"service_requests": [issue]}
```

---

## Data Types & Formats

### Coordinates
- Format: WGS84 (EPSG:4326)
- Latitude: -90 to +90 (North is positive)
- Longitude: -180 to +180 (East is positive)

### Timestamps
- Format: ISO 8601 with timezone
- Examples: `2026-11-13T10:26:58+00:00`, `2026-11-13T10:26:58Z`
- Always include timezone

### Status
- `"open"` - Issue is open/unresolved
- `"closed"` - Issue is resolved

### Service Type
- `"realtime"` - Immediate acknowledgement expected
- `"batch"` - Batch processing (no immediate response)

---

## Example Jurisdictions

| ID | Description |
|----|-------------|
| `fixmystreet` | All FixMyStreet (UK-wide aggregated) |
| `sheffield` | Sheffield City Council area |
| `bristol` | Bristol City Council area |
| `london` | London boroughs aggregated |

---

## Error Handling

All endpoints return HTTP status codes:
- `200` - Success
- `400` - Bad request (missing parameters)
- `401` - Unauthorized
- `404` - Not found
- `500` - Server error

Error response format:
```json
{
  "errors": [
    {
      "code": "MISSING_PARAMETER",
      "description": "jurisdiction_id is required"
    }
  ]
}
```

---

## Rate Limiting & Pagination

- **Default limit**: 1000 results per request
- **Max limit**: 10000 results per request
- Use `offset` parameter for pagination
- Pagination example: `/requests.json?jurisdiction_id=sheffield&limit=100&offset=200`

---

## References

- **Official Open311 Spec**: http://www.open311.org/
- **FixMyStreet Implementation**: https://www.fixmystreet.com/open311/
- **Test Endpoint**: https://www.fixmystreet.com/open311/v2/services.json

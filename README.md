# 🩺 AI Receptionist for Md Primary Care INC.

A modular virtual receptionist voice and EHR integration backend built with **Python 3.12**, **FastAPI**, **Pydantic v2**, and **Retell AI**, featuring real **eClinicalWorks (eCW) SMART Backend Services** patient retrieval and search via FHIR R4.

**Live Backend:** `https://ai-voice-agent-jlez.onrender.com`

---

## 📋 Features & Endpoints

| Endpoint | Method | Purpose |
| :--- | :--- | :--- |
| `GET /api/patients/search` | `GET` | **eCW Name & DOB Search**: Targeted patient search by `first_name`, `last_name`, and `dob` (YYYY-MM-DD) via official US Core parameters. |
| `GET /api/patients` | `GET` | **eCW Patient Directory (Paginated)**: Retrieves accessible patient records from eCW with continuation tokens. Requires API key or Bearer token authorization. |
| `GET /api/patients/{patient_id}` | `GET` | **eCW Patient Demographics by ID**: Retrieves authorized patient demographic details by FHIR ID. |
| `/.well-known/jwks.json` | `GET`, `HEAD` | **RFC 7517 JWKS Endpoint**: Public RSA signing key (`alg: RS384`, `kid`) for eCW OAuth authorization server. |
| `/api/auth/ecw-status` | `GET` | **eCW Auth Diagnostics**: Public metadata, readiness, and registration status for SMART Backend Services. |
| `/health` | `GET` | Server health check and system uptime. |
| `/` | `GET` | Clinic greeting, hours, phone, and supported service intents. |
| `/api/appointments/availability` | `POST` | Check appointment slot availability for Dr. Chintan Shah. |
| `/api/appointments/book` | `POST` | Book appointment with conflict prevention (`409 Conflict`). |
| `/api/appointments/reschedule` | `POST` | Reschedule existing booking with state transition. |
| `/api/appointments/cancel` | `POST` | Cancel confirmed appointment and release slot. |
| `/api/medications/refill` | `POST` | Log prescription refill requests for physician authorization. |
| `/api/knowledge/answer` | `POST` | Verified clinic FAQ answering (hours, location, insurance, provider). |
| `/api/messages` | `POST` | Record caller messages for clinic physicians and nursing staff. |
| `/api/retell/webhook` | `POST` | Unified Retell AI voice tool webhook adapter. |
| `/api/retell/tools/{tool_name}` | `POST` | Dedicated named endpoints for Retell AI custom functions. |

---

## 🔍 Patient API Details

### API One: `GET /api/patients/search`
Targeted search for receptionist workflows using verified eCW US Core search parameters:
- **Query Parameters**:
  - `first_name` (string, required): Patient legal given name.
  - `last_name` (string, required): Patient legal family name.
  - `dob` (string, required): Patient date of birth in `YYYY-MM-DD` format.
- **Upstream Query**:
  ```http
  GET {ECW_FHIR_BASE_URL}/Patient?given=Alex&family=Smith&birthdate=1985-06-15
  ```
- **Response Structure**:
  - `match_status`: `"no_match"`, `"single_match"`, or `"multiple_matches"`.
  - `match_count`: Number of matched records.
  - `patients`: Array of minimal demographic summaries (`patient_id`, `first_name`, `last_name`, `full_name`, `date_of_birth`, `active`).
  - `identity_verification_required`: `true` (enforcing secondary identification protocol before disclosing PHI).
  - `notice`: Clinical instruction for receptionist safety.

### API Two: `GET /api/patients`
Paginated patient directory from actual eCW environment:
- **Authorization**: Protected via `X-Api-Key` or `Authorization: Bearer <key>`. Public unrestricted access is blocked.
- **Query Parameters**:
  - `page_size` (int, default: 20, max: 100): Number of records per page.
  - `page_token` (string, optional): Next-page continuation link/token from previous response.
- **Population Search Policy**:
  - eCW practice policies strictly mandate search filters (e.g., name, birthdate, identifier). If an unindexed population query is rejected by eCW, this endpoint returns a clear `400 Bad Request` explaining the practice restriction rather than silently returning an incomplete list.

---

## 🔐 eClinicalWorks SMART Backend Services Integration

The eCW integration in `app/services/ecw_client.py` connects to eClinicalWorks using the **SMART on FHIR Backend Services Specification (RFC 7523 / OAuth 2.0 Client Credentials Grant)**.

### Architecture Highlights
- **Cryptographic Signing (RS384)**: Generates client assertions signed with an asymmetric RSA private key, matching the public key published at `/.well-known/jwks.json`.
- **Token Lifecycle Management**: Caches access tokens in-memory and reuses them until expiration (with a 30-second buffer). In the event of an unexpected 401 response, the client automatically requests a fresh token and retries the request once.
- **Receptionist Minimal Demographics**: Extracts only necessary demographic information (`patient_id`, `first_name`, `last_name`, `full_name`, `date_of_birth`, `active`).
- **Clinical Privacy Shield**: Strictly suppresses and withholds sensitive clinical records (no conditions, diagnoses, medications, clinical notes, or lab results).
- **Strict Anti-Mocking Rule**: Live requests **never** substitute mock or synthetic records when eCW returns an error or is unconfigured. Instead, the exact blocker is identified.

### Standardized Error Codes

| Status Code | Reason | Cause / Blocker |
| :--- | :--- | :--- |
| `200 OK` | Retrieved successfully | Authorized patient demographics returned. |
| `400 Bad Request` | Invalid query / Restriction | Blank name, invalid date format, or eCW population query restriction without search filters. |
| `401 Unauthorized` | Authentication failure | Missing `ECW_CLIENT_ID`, invalid client assertion, or rejected token. |
| `403 Forbidden` | Access denied | Insufficient permissions (`system/Patient.read`) or practice tenant has not activated the app. |
| `404 Not Found` | Patient not found | Requested `patient_id` does not exist in the practice EHR. |
| `429 Too Many Requests` | Rate limit | eClinicalWorks server rate limit reached. |
| `502 Bad Gateway` | Upstream EHR failure | eCW server returned 500/502/504 or malformed non-FHIR response. |
| `503 Service Unavailable` | Service unavailable | Unconfigured `ECW_FHIR_BASE_URL`, connection timeout, or eCW outage. |

---

## 🛠️ Configuration (.env)

Configuration is managed via environment variables (see `.env.example`). **Never commit `.env` or expose private keys.**

```bash
# eClinicalWorks SMART Backend Services
ECW_ENABLED=true
ECW_ENV="sandbox"
ECW_CLIENT_ID="b_ZpwoiCe2LZ-R42ue4waq0IUEWxQVe_AYSJD4K5xVs"
ECW_KEY_ID="ecw-key-1"

# In production (Render Secrets), paste the multi-line PEM string:
ECW_PRIVATE_KEY=""
# In local development, falls back to keys/private_key.pem:
ECW_PRIVATE_KEY_PATH="keys/private_key.pem"
ECW_PUBLIC_KEY_PATH="keys/public_key.pem"

# Official eCW Endpoints
ECW_TOKEN_URL="https://staging-oauthserver.ecwcloud.com/oauth/oauth2/token"
ECW_FHIR_BASE_URL="https://staging-fhir.ecwcloud.com/fhir/r4/FFBJCD"
ECW_SCOPES="system/Patient.read"
ECW_ASSERTION_EXPIRY_SECONDS=300
```

---

## 🧪 Testing Against an Authorized eCW Sandbox Patient

### Step 1: Obtain Sandbox Credentials from eCW
1. Log in to the [eClinicalWorks Open Developer Portal](https://fhir.eclinicalworks.com/ecwopendev/).
2. Under **Registered Apps**, register or select your **Backend Provider App**.
3. Set your App's **JWKS URL** to:
   ```
   https://ai-voice-agent-jlez.onrender.com/.well-known/jwks.json
   ```
4. Copy your assigned **Client ID** into `ECW_CLIENT_ID`.
5. Ensure scopes include `system/Patient.read` (or `system/Patient.rs`).
6. Ensure your app has been linked to the sandbox practice tenant (`FFBJCD` or your assigned practice ID).

### Step 2: Run Automated Tests
Execute the comprehensive test suite in PowerShell:
```powershell
.\.venv\Scripts\pytest.exe -v
```
All 69 automated tests execute across all 13 required scenarios:
- Exact first-name, last-name, and DOB search
- No matching patient, single matching patient, multiple matching patients
- Invalid DOB format and future DOB rejection
- Missing required query parameters (422)
- Upstream authentication failure (401), permission failure (403), upstream failure (502)
- Patient list pagination and terminal page handling
- Unsupported population-wide search policy handling
- Prevention of mock-data fallback

### Step 3: Verify Live Retrieval in Swagger UI (`/docs`)
1. Start your local server:
   ```powershell
   .\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
   ```
2. Open your browser to:
   👉 **[http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)** (or `https://ai-voice-agent-jlez.onrender.com/docs`)
3. Test **`GET /api/patients/search`**:
   - Expand `GET /api/patients/search`.
   - Click **Try it out**.
   - Enter `first_name`, `last_name`, and `dob` (e.g. `Alex`, `Smith`, `1985-06-15`).
   - Click **Execute**.
4. Test **`GET /api/patients`** (List):
   - Click **Authorize** at top of Swagger and enter your `X-Api-Key` or Bearer token.
   - Expand `GET /api/patients`.
   - Click **Try it out** and **Execute**.

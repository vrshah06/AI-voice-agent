# 🩺 AI Receptionist for Md Primary Care INC.

A modular virtual receptionist voice and EHR integration backend built with **Python 3.12**, **FastAPI**, **Pydantic v2**, and **Retell AI**, featuring real **eClinicalWorks (eCW) SMART Backend Services** patient retrieval via FHIR R4.

**Live Backend:** `https://ai-voice-agent-jlez.onrender.com`

---

## 📋 Features & Endpoints

| Endpoint | Method | Purpose |
| :--- | :--- | :--- |
| `GET /api/patients/{patient_id}` | `GET` | **Real eCW Patient Demographics**: Retrieves authorized patient by FHIR ID from eClinicalWorks EHR. |
| `GET /api/patients` | `GET` | **eCW Patient Search**: Search patients using supported US Core FHIR parameters (`family`, `given`, `birthdate`, `identifier`, `gender`). |
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

## 🔐 eClinicalWorks SMART Backend Services Integration

The eCW integration in `app/services/ecw_client.py` connects to eClinicalWorks using the **SMART on FHIR Backend Services Specification (RFC 7523 / OAuth 2.0 Client Credentials Grant)**.

### Architecture Highlights
- **Cryptographic Signing (RS384)**: Generates client assertions signed with an asymmetric RSA private key, matching the public key published at `/.well-known/jwks.json`.
- **Token Lifecycle Management**: Caches access tokens in-memory and reuses them until expiration (with a 30-second buffer). In the event of an unexpected 401 response, the client automatically requests a fresh token and retries the request once.
- **Receptionist Minimal Demographics**: Extracts only necessary demographic information:
  - `patient_id`
  - `full_name`, `first_name`, `last_name`
  - `date_of_birth`
  - `gender`
  - `phone`, `email`
  - `address` (`line`, `city`, `state`, `postal_code`)
  - `preferred_language`
  - `active`
- **Clinical Privacy Shield**: Strictly suppresses and withholds sensitive clinical records (no conditions, diagnoses, medications, clinical notes, or lab results).
- **Strict Anti-Mocking Rule**: Live requests **never** substitute mock or synthetic records when eCW returns an error or is unconfigured. Instead, the exact blocker is identified.

### Standardized Error Codes

| Status Code | Reason | Cause / Blocker |
| :--- | :--- | :--- |
| `200 OK` | Retrieved successfully | Authorized patient demographics returned. |
| `400 Bad Request` | Invalid query | Blank patient ID or missing search parameters. |
| `401 Unauthorized` | Authentication failure | Missing `ECW_CLIENT_ID`, invalid client assertion, or rejected token. |
| `403 Forbidden` | Access denied | Insufficient permissions (`system/Patient.read`) or practice tenant has not activated the app. |
| `404 Not Found` | Patient not found | Requested `patient_id` does not exist in the practice EHR. |
| `502 Bad Gateway` | Upstream EHR failure | eCW server returned 500/502/504 or malformed non-FHIR response. |
| `503 Service Unavailable` | Service unavailable | Unconfigured `ECW_FHIR_BASE_URL`, connection timeout, or eCW outage. |

---

## 🛠️ Configuration (.env)

Configuration is managed via environment variables (see `.env.example`). **Never commit `.env` or expose private keys.**

```bash
# eClinicalWorks SMART Backend Services
ECW_ENABLED=true
ECW_ENV="sandbox"
ECW_CLIENT_ID="your-ecw-client-id-here"
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
All tests use isolated mock HTTP fixtures to validate token generation, expiration retries, demographic parsing, search, and all HTTP error codes (200, 401, 403, 404, 502, 503).

### Step 3: Verify Live Retrieval in Swagger UI (`/docs`)
1. Start your local server:
   ```powershell
   .\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
   ```
2. Open your browser to:
   👉 **[http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)** (or `https://ai-voice-agent-jlez.onrender.com/docs`)
3. Navigate to the **eCW Patient Demographics** section:
   - Click **`GET /api/patients/{patient_id}`**.
   - Click **Try it out**.
   - Enter a known sandbox patient ID (e.g., `12345` or your practice's test patient ID).
   - Click **Execute**.
4. Observe the response:
   - If properly authenticated: Returns `200 OK` with patient demographics.
   - If `ECW_CLIENT_ID` is unconfigured: Returns `401 Unauthorized` with a clear explanation of the blocker.
   - If the patient does not exist: Returns `404 Not Found`.
   - If practice activation is pending: Returns `403 Forbidden`.

---

## 📂 Project Architecture

```
AI Voice Agent/
├── app/
│   ├── main.py                     # FastAPI app, routers, and structured exception handlers
│   ├── core/
│   │   ├── config.py               # Pydantic Settings & environment variables
│   │   ├── jwks.py                 # RFC 7517 JWKS & RS384 client assertion signer
│   │   └── security.py             # Retell & webhook API key verification
│   ├── models/
│   │   ├── common.py               # Date validators and shared schemas
│   │   ├── patient.py              # Receptionist demographics & search schemas
│   │   ├── appointments.py         # Availability, Booking, Reschedule, Cancel schemas
│   │   ├── medications.py          # Refill request schemas
│   │   ├── knowledge.py            # Clinic knowledge query schemas
│   │   ├── messages.py             # Caller message schemas
│   │   └── retell.py               # Retell webhook & tool schemas
│   ├── services/
│   │   ├── ecw_client.py           # Reusable eCW SMART FHIR client & error mapper
│   │   ├── patient_service.py      # Retell AI voice session state
│   │   ├── appointment_service.py  # In-memory scheduling & conflict prevention
│   │   ├── refill_service.py       # Refill requests & prescriber review flags
│   │   ├── knowledge_service.py    # Approved clinic facts
│   │   └── message_service.py      # Clinic staff message recording
│   └── api/
│       ├── health.py               # GET /health & GET /
│       ├── patients.py             # GET /api/patients/{id} & GET /api/patients (Search)
│       ├── auth.py                 # GET /.well-known/jwks.json & GET /api/auth/ecw-status
│       ├── appointments.py         # POST /api/appointments/*
│       ├── medications.py          # POST /api/medications/refill
│       ├── knowledge.py            # POST /api/knowledge/answer
│       ├── messages.py             # POST /api/messages
│       └── retell.py               # POST /api/retell/* (Retell AI voice adapter)
├── keys/
│   ├── private_key.pem             # RSA Private Key for RS384 assertions (local dev)
│   └── public_key.pem              # RSA Public Key published in JWKS
├── retell/
│   ├── agent_prompt.md             # System prompt for Retell voice agent
│   ├── tools_schema.json           # Retell Custom Function definitions
│   └── sample_payloads.json        # Example payloads
├── scripts/
│   └── sync_retell_flow.py         # One-click Retell agent synchronizer
├── tests/
│   ├── conftest.py                 # Pytest fixtures
│   ├── test_ecw_client.py          # EcwClient unit tests (auth, retry, errors, demographics)
│   ├── test_patient.py             # GET /api/patients/{id} & search integration tests
│   ├── test_ecw_auth.py            # JWKS & client assertion cryptographic tests
│   ├── test_appointments.py        # Appointment scheduling tests
│   ├── test_medications.py         # Refill tests
│   ├── test_knowledge.py           # Knowledge base tests
│   ├── test_messages.py            # Messaging tests
│   ├── test_health.py              # Health check tests
│   └── test_retell.py              # Retell AI adapter tests
├── .env.example
├── .env
├── requirements.txt
└── README.md
```

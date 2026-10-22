# 🩺 AI Receptionist for Md Primary Care INC.

A modular virtual receptionist voice backend built with **Python 3.12**, **FastAPI**, **Pydantic v2**, and **Retell AI**.

> **⚠️ CLINICAL PROTOTYPE DISCLAIMER**  
> This system is an **engineering prototype** utilizing purely synthetic demo data. It is **NOT** connected to live Electronic Health Record (EHR) systems, real pharmacy networks, or 911 emergency services. Patient identity is marked `identity_verified: false`, appointments are simulated, and all medication refill requests require mandatory clinician review.

---

## 📋 Features & Endpoints

| Endpoint | Method | Purpose |
| :--- | :--- | :--- |
| `/health` | `GET` | Health check, server uptime, and demo mode verification. |
| `/` | `GET` | Clinic greeting, hours, phone, and supported service intents. |
| `/api/patient/identify` | `POST` | Collects patient name & DOB. Returns synthetic chart ID with `identity_verified: false`. |
| `/api/appointments/availability` | `POST` | Queries demo slots (`09:00`, `11:00`, `14:30`) for Dr. Chintan Shah. Rejects past dates. |
| `/api/appointments/book` | `POST` | Validates slots, books simulated appointment, and prevents duplicate bookings (`409 Conflict`). |
| `/api/appointments/reschedule` | `POST` | Validates existing booking, releases previous slot, and reserves new slot. |
| `/api/appointments/cancel` | `POST` | Cancels confirmed appointment and returns the time slot to available inventory. |
| `/api/medications/refill` | `POST` | Logs prescription refill with `requires_prescriber_approval: true`. |
| `/api/knowledge/answer` | `POST` | Answers questions on hours, location, insurance, and doctor using approved facts without hallucination. |
| `/api/messages` | `POST` | Records caller messages for Dr. Chintan Shah, nursing, or clinic staff with tracking reference. |
| `/api/retell/webhook` | `POST` | Unified Retell AI tool webhook adapter (handles wrapped and flat formats). |
| `/api/retell/tools/{tool_name}` | `POST` | Dedicated named tool endpoints for Retell custom functions. |
| `/.well-known/jwks.json` | `GET` | Standards-compliant RFC 7517 JWKS endpoint (RS384) for eCW Developer Portal verification. |
| `/api/auth/ecw-status` | `GET` | Health, metadata, and configuration status for eCW SMART on FHIR backend service. |


---

## 📂 Project Architecture

```
AI Voice Agent/
├── app/
│   ├── main.py                     # FastAPI application & custom exception handlers
│   ├── core/
│   │   ├── config.py               # Pydantic Settings & environment variables
│   │   └── security.py             # X-Api-Key & Bearer token verification
│   ├── models/
│   │   ├── common.py               # Shared base models & date validators
│   │   ├── patient.py              # Patient identification schemas
│   │   ├── appointments.py         # Availability, Booking, Reschedule, Cancel schemas
│   │   ├── medications.py          # Refill request schemas
│   │   ├── knowledge.py            # Clinic knowledge query schemas
│   │   ├── messages.py             # Take message schemas
│   │   └── retell.py               # Retell webhook & adapter schemas
│   ├── services/
│   │   ├── patient_service.py      # In-memory synthetic patient profiles
│   │   ├── appointment_service.py  # In-memory scheduling, conflict prevention, reschedule & cancel
│   │   ├── refill_service.py       # In-memory refill requests & safety guardrails
│   │   ├── knowledge_service.py    # Approved clinic facts without hallucination
│   │   └── message_service.py      # In-memory caller messages
│   └── api/
│       ├── health.py               # GET /health & GET /
│       ├── patient.py              # POST /api/patient/identify
│       ├── appointments.py         # POST /api/appointments/*
│       ├── medications.py          # POST /api/medications/refill
│       ├── knowledge.py            # POST /api/knowledge/answer
│       ├── messages.py             # POST /api/messages
│       └── retell.py               # POST /api/retell/* (Voice agent adapter)
├── retell/
│   ├── agent_prompt.md             # Complete system prompt for Retell voice agent
│   ├── tools_schema.json           # All 8 Retell Custom Function definitions
│   └── sample_payloads.json        # Example request/response payloads for all 8 tools
├── scripts/
│   └── sync_retell_flow.py         # Automatic one-click sync of tools & prompts to Retell API
├── tests/
│   ├── conftest.py                 # Pytest fixtures & in-memory state resets
│   ├── test_health.py
│   ├── test_patient.py
│   ├── test_appointments.py
│   ├── test_medications.py
│   ├── test_knowledge.py
│   ├── test_messages.py
│   └── test_retell.py
├── .env.example
├── .env
├── requirements.txt
└── README.md
```

---

## 🚀 Windows PowerShell Setup & Local Testing

From the project root (`c:\Users\shahb\Documents\AI Voice Agent`) in PowerShell:

### 1. Run Automated Test Suite
```powershell
.\.venv\Scripts\pytest.exe -v
```
*(All 39 automated tests will execute and validate scheduling, conflict handling, rescheduling, cancellation, knowledge queries, messages, and Retell tool adapters.)*

### 2. Start the FastAPI Local Server
```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### 3. Open Interactive Swagger UI
Open your browser to:
👉 **[http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)**

---

## 🎙️ Retell AI Integration & Automatic Sync

### Step 1: Start your HTTPS Tunnel
In a PowerShell window:
```powershell
ngrok http 8000
```
Copy your forwarding URL (e.g. `https://omen-reassign-plausible.ngrok-free.dev`).

### Step 2: One-Click Sync to Retell AI
Run our synchronization script to automatically push all 8 tools, clinic prompts, and webhook configurations directly into your Retell agent:
```powershell
.\.venv\Scripts\python.exe scripts/sync_retell_flow.py
```
*(You can also pass a custom tunnel URL: `python scripts/sync_retell_flow.py https://your-tunnel.ngrok-free.dev`)*

The script automatically:
1. Configures all **8 Custom Tools** (`identify_patient`, `check_appointment_availability`, `book_appointment`, `reschedule_appointment`, `cancel_appointment`, `request_medication_refill`, `answer_clinic_question`, `take_message`).
2. Configures webhook headers (`X-Api-Key: demo-clinic-secret-key-12345`).
3. Updates `node_greeting`:
   > *"Thank you for calling Md Primary Care INC. I am the AI voice receptionist. How may I help you today?"*
4. Updates all node instructions with doctor **Dr. Chintan Shah** and phone **5612086041**.
5. Injects anti-hallucination rules into the Global Agent Prompt.

### Step 3: Test a Voice Call
1. In the [Retell Dashboard](https://app.retellai.com), click **Test Audio** or **Web Call Simulator**.
2. Speak to your AI Receptionist:
   - *"Hi, I want to book an appointment with Dr. Shah on October 26th."*
   - *"Can I reschedule my appointment to October 28th at 11:00 AM?"*
   - *"What are your clinic hours and address?"*
   - *"I'd like to leave a message for Dr. Shah."*
3. Watch live requests reach your local FastAPI server in your terminal window in real-time!

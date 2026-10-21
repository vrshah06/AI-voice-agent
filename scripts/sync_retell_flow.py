"""Script to synchronize Retell AI Conversation Flow with the FastAPI backend.

Updates:
1. All 8 Retell custom functions with ngrok webhook URLs and X-Api-Key headers.
2. Attaches the exact tool_ids to each node in the conversation flow graph.
3. Sets dynamic variables for clinic name (Md Primary Care INC.), phone (5612086041), and hours.
4. Updates greeting node instruction: "Thank you for calling Md Primary Care INC.. I am the AI voice receptionist..."
5. Injects anti-hallucination rules and tool calling instructions into each node and global prompt.
"""
import os
import sys
import json
import urllib.request
import urllib.error
from dotenv import load_dotenv

load_dotenv()

RETELL_API_KEY = os.getenv("RETELL_API_KEY", "key_0f293e950a9456f5d995f640ac81")
WEBHOOK_SECRET_KEY = os.getenv("WEBHOOK_SECRET_KEY", "demo-clinic-secret-key-12345")
CLINIC_NAME = os.getenv("CLINIC_NAME", "Md Primary Care INC.")
CLINIC_PHONE = os.getenv("CLINIC_PHONE", "5612086041")
CLINIC_HOURS = os.getenv("CLINIC_HOURS", "Monday to Friday, 8:00 AM to 5:00 PM EST")


def get_current_tunnel_url():
    try:
        req = urllib.request.urlopen("http://127.0.0.1:4040/api/tunnels", timeout=2)
        data = json.loads(req.read().decode())
        tunnels = data.get("tunnels", [])
        for t in tunnels:
            if t.get("proto") == "https":
                return t.get("public_url")
        if tunnels:
            return tunnels[0].get("public_url")
    except Exception:
        pass
    return "https://omen-reassign-plausible.ngrok-free.dev"


def sync_flow(tunnel_url=None):
    if not RETELL_API_KEY:
        print("ERROR: RETELL_API_KEY not found in .env")
        sys.exit(1)

    base_url = tunnel_url or get_current_tunnel_url()
    print(f"[*] Using Webhook Base URL: {base_url}")
    print(f"[*] Clinic: {CLINIC_NAME} | Phone: {CLINIC_PHONE}")

    headers = {
        "Authorization": f"Bearer {RETELL_API_KEY}",
        "Content-Type": "application/json"
    }

    # 1. Fetch Agents to locate conversation_flow_id
    req = urllib.request.Request("https://api.retellai.com/list-agents", headers=headers)
    try:
        with urllib.request.urlopen(req) as resp:
            agents = json.loads(resp.read().decode())
    except Exception as e:
        print(f"Failed to list agents: {e}")
        sys.exit(1)

    if not agents:
        print("No agents found in Retell account.")
        sys.exit(1)

    agent = agents[0]
    agent_id = agent.get("agent_id")
    flow_id = agent.get("response_engine", {}).get("conversation_flow_id")
    print(f"[*] Found Agent: {agent.get('agent_name')} ({agent_id})")
    print(f"[*] Conversation Flow ID: {flow_id}")

    if not flow_id:
        print("Agent is not using a conversation flow.")
        sys.exit(1)

    # 2. Fetch existing conversation flow
    req = urllib.request.Request(f"https://api.retellai.com/get-conversation-flow/{flow_id}", headers=headers)
    with urllib.request.urlopen(req) as resp:
        flow = json.loads(resp.read().decode())

    # 3. Define all 8 Custom Tools with explicit tool_ids
    tools = [
        {
            "tool_id": "tool-identify-patient",
            "name": "identify_patient",
            "type": "custom",
            "method": "POST",
            "url": f"{base_url}/api/retell/tools/identify_patient",
            "description": f"Collects patient full name and date of birth to look up chart at {CLINIC_NAME}.",
            "headers": {"X-Api-Key": WEBHOOK_SECRET_KEY},
            "parameters": {
                "type": "object",
                "properties": {
                    "patient_name": {"type": "string", "description": "Patient's full legal name"},
                    "date_of_birth": {"type": "string", "description": "Patient's date of birth in YYYY-MM-DD format"}
                },
                "required": ["patient_name", "date_of_birth"]
            },
            "speak_after_execution": True,
            "speak_during_execution": False,
            "timeout_ms": 60000
        },
        {
            "tool_id": "tool-check-availability",
            "name": "check_appointment_availability",
            "type": "custom",
            "method": "POST",
            "url": f"{base_url}/api/retell/tools/check_appointment_availability",
            "description": f"Queries real open appointment slots for Dr. Chintan Shah at {CLINIC_NAME}.",
            "headers": {"X-Api-Key": WEBHOOK_SECRET_KEY},
            "parameters": {
                "type": "object",
                "properties": {
                    "patient_name": {"type": "string", "description": "Patient's full name"},
                    "date_of_birth": {"type": "string", "description": "Patient's date of birth in YYYY-MM-DD format"},
                    "doctor_name": {"type": "string", "description": "Doctor name (defaults to 'Dr. Chintan Shah')"},
                    "requested_date": {"type": "string", "description": "Appointment date in YYYY-MM-DD format"}
                },
                "required": ["patient_name", "date_of_birth", "requested_date"]
            },
            "speak_after_execution": True,
            "speak_during_execution": False,
            "timeout_ms": 60000
        },
        {
            "tool_id": "tool-book-appointment",
            "name": "book_appointment",
            "type": "custom",
            "method": "POST",
            "url": f"{base_url}/api/retell/tools/book_appointment",
            "description": f"Books an appointment slot at {CLINIC_NAME}. Validates slot and prevents duplicate bookings.",
            "headers": {"X-Api-Key": WEBHOOK_SECRET_KEY},
            "parameters": {
                "type": "object",
                "properties": {
                    "patient_name": {"type": "string", "description": "Patient's full name"},
                    "date_of_birth": {"type": "string", "description": "Patient's date of birth in YYYY-MM-DD format"},
                    "doctor_name": {"type": "string", "description": "Doctor name (e.g. Dr. Chintan Shah)"},
                    "appointment_date": {"type": "string", "description": "Appointment date in YYYY-MM-DD format"},
                    "appointment_time": {"type": "string", "description": "Selected slot time in 24-hour HH:MM format (e.g. 09:00, 11:00, 14:30)"}
                },
                "required": ["patient_name", "date_of_birth", "doctor_name", "appointment_date", "appointment_time"]
            },
            "speak_after_execution": True,
            "speak_during_execution": False,
            "timeout_ms": 60000
        },
        {
            "tool_id": "tool-reschedule-appointment",
            "name": "reschedule_appointment",
            "type": "custom",
            "method": "POST",
            "url": f"{base_url}/api/retell/tools/reschedule_appointment",
            "description": f"Reschedules an existing appointment at {CLINIC_NAME} to a new date and time.",
            "headers": {"X-Api-Key": WEBHOOK_SECRET_KEY},
            "parameters": {
                "type": "object",
                "properties": {
                    "patient_name": {"type": "string", "description": "Patient full name"},
                    "date_of_birth": {"type": "string", "description": "Patient date of birth in YYYY-MM-DD format"},
                    "appointment_reference": {"type": "string", "description": "Booking reference code if known"},
                    "new_date": {"type": "string", "description": "New requested date in YYYY-MM-DD format"},
                    "new_time": {"type": "string", "description": "New requested slot time (e.g. 09:00, 11:00, 14:30)"}
                },
                "required": ["patient_name", "date_of_birth", "new_date", "new_time"]
            },
            "speak_after_execution": True,
            "speak_during_execution": False,
            "timeout_ms": 60000
        },
        {
            "tool_id": "tool-cancel-appointment",
            "name": "cancel_appointment",
            "type": "custom",
            "method": "POST",
            "url": f"{base_url}/api/retell/tools/cancel_appointment",
            "description": f"Cancels an existing appointment at {CLINIC_NAME} and frees the schedule.",
            "headers": {"X-Api-Key": WEBHOOK_SECRET_KEY},
            "parameters": {
                "type": "object",
                "properties": {
                    "patient_name": {"type": "string", "description": "Patient full name"},
                    "date_of_birth": {"type": "string", "description": "Patient date of birth in YYYY-MM-DD format"},
                    "appointment_reference": {"type": "string", "description": "Booking reference code if known"}
                },
                "required": ["patient_name", "date_of_birth"]
            },
            "speak_after_execution": True,
            "speak_during_execution": False,
            "timeout_ms": 60000
        },
        {
            "tool_id": "tool-request-refill",
            "name": "request_medication_refill",
            "type": "custom",
            "method": "POST",
            "url": f"{base_url}/api/retell/tools/request_medication_refill",
            "description": f"Submits prescription refill request to {CLINIC_NAME} clinical staff for review.",
            "headers": {"X-Api-Key": WEBHOOK_SECRET_KEY},
            "parameters": {
                "type": "object",
                "properties": {
                    "patient_name": {"type": "string", "description": "Patient full name"},
                    "date_of_birth": {"type": "string", "description": "Patient date of birth in YYYY-MM-DD format"},
                    "medication_name": {"type": "string", "description": "Medication name and dosage"},
                    "preferred_pharmacy_name": {"type": "string", "description": "Pharmacy chain or name"},
                    "pharmacy_location": {"type": "string", "description": "Pharmacy address or city"}
                },
                "required": ["patient_name", "date_of_birth", "medication_name", "preferred_pharmacy_name", "pharmacy_location"]
            },
            "speak_after_execution": True,
            "speak_during_execution": False,
            "timeout_ms": 60000
        },
        {
            "tool_id": "tool-clinic-question",
            "name": "answer_clinic_question",
            "type": "custom",
            "method": "POST",
            "url": f"{base_url}/api/retell/tools/answer_clinic_question",
            "description": f"Queries approved clinic knowledge for {CLINIC_NAME} on hours, location, insurance, providers, or visit prep.",
            "headers": {"X-Api-Key": WEBHOOK_SECRET_KEY},
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "The caller's general clinic question"}
                },
                "required": ["question"]
            },
            "speak_after_execution": True,
            "speak_during_execution": False,
            "timeout_ms": 60000
        },
        {
            "tool_id": "tool-take-message",
            "name": "take_message",
            "type": "custom",
            "method": "POST",
            "url": f"{base_url}/api/retell/tools/take_message",
            "description": f"Records a caller message for {CLINIC_NAME} doctors or staff.",
            "headers": {"X-Api-Key": WEBHOOK_SECRET_KEY},
            "parameters": {
                "type": "object",
                "properties": {
                    "caller_name": {"type": "string", "description": "Caller name"},
                    "callback_number": {"type": "string", "description": "Return phone number"},
                    "recipient": {"type": "string", "description": "Target doctor or department (e.g. Dr. Chintan Shah)"},
                    "message": {"type": "string", "description": "Message content"}
                },
                "required": ["caller_name", "callback_number", "message"]
            },
            "speak_after_execution": True,
            "speak_during_execution": False,
            "timeout_ms": 60000
        }
    ]

    # 4. Map specific tool_ids to each node in the conversation graph
    nodes = flow.get("nodes", [])
    for n in nodes:
        nid = n.get("id")

        if nid == "node_greeting":
            n["instruction"] = {
                "text": (
                    f"Greet the caller warmly. Say: \"Thank you for calling {CLINIC_NAME}. I am the AI voice receptionist. How may I help you today?\"\n\n"
                    "Listen to what the caller needs and identify their intent. Do not ask for their name or date of birth yet — just understand what they are calling about."
                ),
                "type": "prompt"
            }

        elif nid == "node_verify_patient":
            n["tool_ids"] = ["tool-identify-patient"]
            n["instruction"] = {
                "text": (
                    f"Ask the caller for their full legal name and date of birth to look up their chart at {CLINIC_NAME}.\n"
                    "As soon as they provide both, call the tool 'identify_patient' with patient_name and date_of_birth (YYYY-MM-DD).\n"
                    "Once the tool responds, say: \"Thank you, [Patient Name]. I have verified your details in our system.\" and immediately proceed to help them with their request."
                ),
                "type": "prompt"
            }

        elif nid == "node_schedule":
            # Give node_schedule access to check availability and book
            n["tool_ids"] = ["tool-check-availability", "tool-book-appointment"]
            n["instruction"] = {
                "text": (
                    f"Help the caller schedule an appointment with Dr. Chintan Shah at {CLINIC_NAME}.\n"
                    "1. Ask what date they would like to visit.\n"
                    "2. As soon as the caller gives a date, call the tool 'check_appointment_availability' with patient_name, date_of_birth, and requested_date (YYYY-MM-DD). Do NOT just say you are checking — actually call the tool!\n"
                    "3. Read the available slots returned by the tool (e.g. 9:00 AM, 11:00 AM, 2:30 PM).\n"
                    "4. When the caller picks a slot, confirm their choice and call 'book_appointment'.\n"
                    "5. Read the confirmation reference code returned by the tool."
                ),
                "type": "prompt"
            }

        elif nid == "node_reschedule":
            n["tool_ids"] = ["tool-check-availability", "tool-reschedule-appointment"]
            n["instruction"] = {
                "text": (
                    f"Help the caller reschedule an appointment at {CLINIC_NAME}.\n"
                    "1. Ask for their preferred new date and time.\n"
                    "2. Call tool 'reschedule_appointment' with patient_name, date_of_birth, new_date, and new_time.\n"
                    "3. Read the result returned by the tool."
                ),
                "type": "prompt"
            }

        elif nid == "node_cancel":
            n["tool_ids"] = ["tool-cancel-appointment"]
            n["instruction"] = {
                "text": (
                    f"Help the caller cancel an appointment at {CLINIC_NAME}.\n"
                    "1. Confirm their intent to cancel.\n"
                    "2. Call tool 'cancel_appointment' with patient_name and date_of_birth.\n"
                    "3. Read the confirmation returned by the tool."
                ),
                "type": "prompt"
            }

        elif nid == "node_rx_refill":
            n["tool_ids"] = ["tool-request-refill"]
            n["instruction"] = {
                "text": (
                    f"Help the caller request a prescription refill at {CLINIC_NAME}.\n"
                    "1. Collect medication name, preferred pharmacy name, and location.\n"
                    "2. Call tool 'request_medication_refill'.\n"
                    "3. Inform caller that a clinician must review and approve the request."
                ),
                "type": "prompt"
            }

        elif nid == "node_faq":
            n["tool_ids"] = ["tool-clinic-question"]
            n["instruction"] = {
                "text": (
                    f"Answer questions about {CLINIC_NAME} by calling the tool 'answer_clinic_question' with the caller's question.\n"
                    "Speak the approved answer returned by the tool. If not found, offer to take a message."
                ),
                "type": "prompt"
            }

        elif nid == "node_take_message":
            n["tool_ids"] = ["tool-take-message"]
            n["instruction"] = {
                "text": (
                    f"Take a message for {CLINIC_NAME} doctors or staff.\n"
                    "1. Collect caller name, callback number, recipient, and message.\n"
                    "2. Call tool 'take_message'.\n"
                    "3. Read the confirmation reference returned by the tool."
                ),
                "type": "prompt"
            }

    # 5. Global Prompt with Anti-Hallucination Rules
    global_prompt = (
        f"# AI Voice Receptionist — {CLINIC_NAME}\n\n"
        f"You are the AI Voice Receptionist for {CLINIC_NAME} (Phone: {CLINIC_PHONE}).\n"
        "Your voice is warm, courteous, calm, and professional.\n\n"
        "## Core Anti-Hallucination Rules:\n"
        "1. Backend tools are your ONLY source of truth for appointment slots, booking references, and refill status.\n"
        "2. When checking availability, trigger 'check_appointment_availability' immediately. Present ONLY the slots returned by the backend.\n"
        "3. NEVER pretend you are checking without calling the tool.\n"
        "4. NEVER claim an appointment was booked or rescheduled unless the tool returned success.\n"
        "5. NEVER give medical advice, diagnose symptoms, or advise on drug dosages.\n"
        "6. In life-threatening emergencies, immediately tell the caller to hang up and dial 911."
    )

    # 6. Dynamic Variables
    dyn_vars = {
        "clinic_name": CLINIC_NAME,
        "clinic_phone": CLINIC_PHONE,
        "clinic_hours": CLINIC_HOURS,
        "clinic_address": "100 Medical Center Way, Suite 200",
        "accepted_insurance": "Medicare, Blue Cross Blue Shield, Aetna, Cigna, UnitedHealthcare, Humana"
    }

    # 7. Update Retell Conversation Flow via PATCH
    update_payload = {
        "global_prompt": global_prompt,
        "tools": tools,
        "nodes": nodes,
        "default_dynamic_variables": dyn_vars
    }

    patch_req = urllib.request.Request(
        f"https://api.retellai.com/update-conversation-flow/{flow_id}",
        data=json.dumps(update_payload).encode("utf-8"),
        headers=headers,
        method="PATCH"
    )

    try:
        with urllib.request.urlopen(patch_req) as resp:
            result = json.loads(resp.read().decode())
            print("[+] Successfully updated Retell Conversation Flow!")
            print(f"[+] Total Tools Registered: {len(result.get('tools', []))}")
            print(f"[+] Updated Nodes: {len(result.get('nodes', []))}")
            print(f"[+] Attached tool_ids to each conversation node in the graph!")
    except urllib.error.HTTPError as he:
        print(f"[-] HTTP Error updating flow: {he.code} - {he.read().decode()}")
    except Exception as exc:
        print(f"[-] Error updating flow: {exc}")


if __name__ == "__main__":
    url_arg = sys.argv[1] if len(sys.argv) > 1 else None
    sync_flow(url_arg)

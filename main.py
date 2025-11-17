# main.py
# Conversational ticket assistant using OpenAI (Python SDK) + Odoo JSON-RPC

import os
import json
import requests
from dotenv import load_dotenv
from openai import OpenAI

# ---------------------------------------------------------------------
# Load environment variables
# ---------------------------------------------------------------------
load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ---------------------------------------------------------------------
# Ticket state kept on our side (Python)
# ---------------------------------------------------------------------
ticket_state = {
    "type": None,             # "feature" or "bug"
    "title": None,            # short clear summary
    "problem_context": None,  # detailed context/description
    "expected_outcome": None, # definition of done
    "proposed_solution": None,# optional suggestion
    "affected_users": None,   # who is impacted
    "priority": None,         # "low" | "medium" | "high"
    "urgency_stars": None,    # 1–5
    "source": "Chatbot",      # or "Slack Chatbot"
    "requested_by": None      # name/handle of requester
}

# ---------------------------------------------------------------------
# Odoo integration – JSON-RPC using only standard fields
# ---------------------------------------------------------------------
def create_ticket_in_odoo(ticket: dict) -> None:
    """
    Send the ticket to Odoo via JSON-RPC (minimal version using only standard fields).
    This assumes:
      - ODOO_URL points to the Odoo base URL (e.g., https://my-odoo.example.com)
      - ODOO_DB, ODOO_USERNAME, ODOO_PASSWORD are correct
      - The model 'helpdesk.ticket' exists and has at least: name, description, priority
    """

    odoo_url = os.getenv("ODOO_URL")
    odoo_db = os.getenv("ODOO_DB")
    odoo_username = os.getenv("ODOO_USERNAME")
    odoo_password = os.getenv("ODOO_PASSWORD")

    if not all([odoo_url, odoo_db, odoo_username, odoo_password]):
        print("\n[ODOO] Missing Odoo env variables. Please set ODOO_URL, ODOO_DB, ODOO_USERNAME, ODOO_PASSWORD in .env.")
        print("[ODOO] Ticket was NOT sent to Odoo, but payload is shown below:\n")
        print(json.dumps(ticket, indent=2))
        return

    # 1) Authenticate to Odoo to get uid
    auth_payload = {
        "jsonrpc": "2.0",
        "method": "call",
        "params": {
            "service": "common",
            "method": "login",
            "args": [odoo_db, odoo_username, odoo_password],
        },
        "id": 1,
    }

    try:
        auth_res = requests.post(odoo_url + "/jsonrpc", json=auth_payload)
        auth_res.raise_for_status()
        auth_data = auth_res.json()
        uid = auth_data.get("result")
    except Exception as e:
        print(f"\n[ODOO] Error during authentication: {e}")
        print("[ODOO] Ticket was NOT sent to Odoo, but payload is shown below:\n")
        print(json.dumps(ticket, indent=2))
        return

    if not uid:
        print("\n[ODOO] Authentication failed, uid is empty.")
        print("[ODOO] Ticket was NOT sent to Odoo, but payload is shown below:\n")
        print(json.dumps(ticket, indent=2))
        return

    # Map human priority -> Odoo priority (adjust for your instance if needed)
    priority_map = {
        "low": "0",
        "medium": "1",
        "high": "2",
    }
    odoo_priority = priority_map.get(ticket.get("priority", "medium"), "1")

    # Build a rich description using all the ticket details
    description = (
        f"Type: {ticket.get('type')}\n"
        f"Problem/Context:\n{ticket.get('problem_context')}\n\n"
        f"Expected Outcome:\n{ticket.get('expected_outcome')}\n\n"
        f"Proposed Solution:\n{ticket.get('proposed_solution') or ''}\n\n"
        f"Affected Users:\n{ticket.get('affected_users')}\n\n"
        f"Urgency Stars: {ticket.get('urgency_stars')}\n"
        f"Requested By: {ticket.get('requested_by')}\n"
        f"Source: {ticket.get('source')}\n"
    )

    # 2) Create ticket record in Odoo using only standard fields
    create_payload = {
        "jsonrpc": "2.0",
        "method": "call",
        "params": {
            "service": "object",
            "method": "execute_kw",
            "args": [
                odoo_db,
                uid,
                odoo_password,
                "helpdesk.ticket",  # model name
                "create",
                [
                    {
                        "name": ticket.get("title"),       # ticket title
                        "description": description,        # full context
                        "priority": odoo_priority,         # mapped priority
                    }
                ],
            ],
        },
        "id": 2,
    }

    try:
        create_res = requests.post(odoo_url + "/jsonrpc", json=create_payload)
        create_res.raise_for_status()
        create_data = create_res.json()
        ticket_id = create_data.get("result")
    except Exception as e:
        print(f"\n[ODOO] Error creating ticket: {e}")
        print("[ODOO] Ticket payload that failed:\n")
        print(json.dumps(ticket, indent=2))
        return

    if ticket_id:
        print("\n[ODOO] Ticket successfully created in Odoo.")
        print(f"[ODOO] New ticket ID: {ticket_id}\n")
    else:
        print("\n[ODOO] Unknown error: no ticket_id returned.")
        print("[ODOO] Raw response:\n", create_data)


# ---------------------------------------------------------------------
# System prompt for the model
# ---------------------------------------------------------------------
SYSTEM_PROMPT = """
You are a ticket-intake assistant for a software company.

Goal:
- Talk conversationally with the user (as if in Slack).
- Help them create a detailed, clear ticket for either:
  - a FEATURE REQUEST, or
  - a BUG FIX (bug report).

You must:
1. Ask follow-up questions until the ticket is ready for developers.
2. Decide the ticket "type": either "feature" or "bug".
3. Create a short but descriptive "title".
4. Build these fields:
   - "problem_context": detailed description of the situation/need.
   - "expected_outcome": clear definition of done (what success looks like).
   - "proposed_solution": optional, only if the user has a suggestion.
   - "affected_users": who is impacted (e.g., "All users", "Finance team").
5. Set "priority": "low", "medium", or "high".
   - low  = minor / nice-to-have, not urgent.
   - medium = important but not blocking many users.
   - high = urgent or blocking many users or business-critical.
6. Set "urgency_stars": integer 1–5.
   - 1 = not urgent, 5 = extremely urgent.
7. Capture "requested_by":
   - Ask: "What name or Slack handle should I put as the requester?"
     if you do not know it yet.

Important:
- Be proactive with clarifying questions.
- Keep improving the ticket fields each time (never discard helpful information).
- When the ticket is detailed enough for a developer to implement without more
  clarification, mark it as ready.

Output format:
- ALWAYS respond ONLY as a single, valid JSON object (no extra text).
- The JSON MUST have this exact shape:

{
  "assistant_reply": "string - the message you say to the user",
  "ticket": {
    "type": "feature or bug",
    "title": "short title",
    "problem_context": "detailed context",
    "expected_outcome": "definition of done",
    "proposed_solution": "optional suggestion or empty string",
    "affected_users": "description of affected users",
    "priority": "low | medium | high",
    "urgency_stars": 1,
    "source": "Chatbot",
    "requested_by": "name/handle"
  },
  "question_for_user": "one main question to ask the user next, or empty string",
  "is_ticket_ready": true or false
}

Rules:
- "assistant_reply" must be friendly, concise, professional.
- "assistant_reply" may include the question_for_user naturally inside it.
- "ticket" must always be your BEST CURRENT VERSION of the full ticket.
- "is_ticket_ready" = true ONLY when all fields are reasonably complete and clear.
"""


# ---------------------------------------------------------------------
# OpenAI call per turn – with JSON mode to avoid parse errors
# ---------------------------------------------------------------------
def call_openai(conversation_messages):
    """
    Call OpenAI Chat Completions API, enforcing JSON output with response_format.
    This eliminates most "invalid JSON" issues even if you type quickly.
    """
    ticket_json = json.dumps(ticket_state)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "assistant",
            "content": (
                "Here is the current ticket state in JSON. "
                "Improve it; do not throw away useful information:\n"
                f"{ticket_json}"
            ),
        },
    ]
    messages.extend(conversation_messages)

    response = client.chat.completions.create(
        model="gpt-4.1-mini",  # or another model you prefer
        messages=messages,
        temperature=0.2,
        response_format={"type": "json_object"},  # JSON mode
    )

    content = response.choices[0].message.content
    return content


def merge_ticket_state(new_ticket: dict):
    """
    Update our ticket_state with the model's new_ticket.
    Do not overwrite with null/empty if we already have a better value.
    """
    global ticket_state
    for key, value in new_ticket.items():
        if value is None:
            continue
        if isinstance(value, str) and value.strip() == "":
            continue
        ticket_state[key] = value


def run_chat():
    global ticket_state

    print("Ticket Assistant (Python + OpenAI + Odoo)")
    print("Type 'exit' or 'quit' to stop.\n")

    # conversation_messages is a list of {role, content} for user+assistant
    conversation_messages = []

    while True:
        user_input = input("You: ").strip()
        if user_input.lower() in {"exit", "quit"}:
            print("Bot: Goodbye!")
            break

        # Add user message
        conversation_messages.append({"role": "user", "content": user_input})

        # Call OpenAI
        raw = call_openai(conversation_messages)

        # Parse JSON (JSON mode should guarantee valid JSON)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            print("Bot: Sorry, I had trouble formatting my response. Let me try again.\n")
            conversation_messages.append({
                "role": "assistant",
                "content": "I produced invalid JSON. Please ask your question again."
            })
            continue

        assistant_reply = data.get("assistant_reply", "").strip()
        new_ticket = data.get("ticket", {}) or {}
        is_ticket_ready = bool(data.get("is_ticket_ready", False))

        # Merge ticket state
        merge_ticket_state(new_ticket)

        # Print the bot's human-facing reply
        print(f"Bot: {assistant_reply}\n")

        # Add assistant reply to conversation history
        conversation_messages.append({
            "role": "assistant",
            "content": assistant_reply
        })

        # If the ticket is ready, show final payload and send to Odoo
        if is_ticket_ready:
            print("Bot: I believe the ticket is now ready. Here is a summary of what will be sent:\n")
            print(json.dumps(ticket_state, indent=2))

            # Real send to Odoo
            create_ticket_in_odoo(ticket_state)

            again = input("Create another ticket? (y/n): ").strip().lower()
            if again == "y":
                # reset state and conversation
                ticket_state = {
                    "type": None,
                    "title": None,
                    "problem_context": None,
                    "expected_outcome": None,
                    "proposed_solution": None,
                    "affected_users": None,
                    "priority": None,
                    "urgency_stars": None,
                    "source": "Chatbot",
                    "requested_by": None,
                }
                conversation_messages = []
                print("\nStarting a new ticket.\n")
            else:
                print("Bot: Okay, goodbye!")
                break


if __name__ == "__main__":
    run_chat()

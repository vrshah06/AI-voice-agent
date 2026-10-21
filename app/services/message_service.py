"""In-memory service managing caller messages for clinic staff."""
import random
import string
from typing import Dict, List
from app.models.messages import TakeMessageRequest, TakeMessageResponse


class MessageService:
    """Manages recording and tracking messages left by callers."""

    def __init__(self) -> None:
        self._messages: List[Dict[str, str]] = []

    def take_message(self, request: TakeMessageRequest) -> TakeMessageResponse:
        """Store a caller message in memory and return confirmation."""
        random_suffix = "".join(random.choices(string.digits, k=5))
        msg_id = f"MSG-DEMO-{random_suffix}"

        record = {
            "message_id": msg_id,
            "caller_name": request.caller_name,
            "callback_number": request.callback_number,
            "recipient": request.recipient or "Clinic Staff",
            "message": request.message,
            "urgency": request.urgency or "routine",
        }
        self._messages.append(record)

        recipient_text = request.recipient or "our clinic team"
        message_text = (
            f"Thank you, {request.caller_name}. I have recorded your message for {recipient_text}. "
            f"We will return your call at {request.callback_number}. Your message confirmation reference is {msg_id}."
        )

        return TakeMessageResponse(
            status="recorded",
            message_id=msg_id,
            caller_name=request.caller_name,
            callback_number=request.callback_number,
            recipient=request.recipient or "Clinic Staff",
            message=message_text,
        )

    def reset(self) -> None:
        """Reset state for clean automated testing."""
        self._messages.clear()


message_service = MessageService()

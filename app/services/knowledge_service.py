"""Service providing authoritative clinic knowledge base answers without hallucination."""
from typing import Dict, Optional, Tuple
from app.core.config import settings
from app.models.knowledge import ClinicKnowledgeRequest, ClinicKnowledgeResponse


class KnowledgeService:
    """Answers patient questions using strictly approved clinic policies and facts."""

    def __init__(self) -> None:
        self.clinic_facts = {
            "hours": (
                f"{settings.CLINIC_NAME} is open {settings.CLINIC_HOURS}. "
                "We are closed on Saturdays, Sundays, and major holidays."
            ),
            "location": (
                f"{settings.CLINIC_NAME} is located at 100 Medical Center Way, Suite 200. "
                "Convenient patient parking is available directly in front of the building."
            ),
            "phone": (
                f"You can reach {settings.CLINIC_NAME} directly at {settings.CLINIC_PHONE} during business hours."
            ),
            "doctors": (
                f"Our primary care team at {settings.CLINIC_NAME} includes Dr. Chintan Shah, "
                "specializing in comprehensive internal medicine, preventive health, and chronic disease care."
            ),
            "insurance": (
                f"{settings.CLINIC_NAME} accepts Medicare and major commercial insurance plans including "
                "Blue Cross Blue Shield, Aetna, Cigna, UnitedHealthcare, and Humana. "
                "Please bring your insurance card to your visit for verification."
            ),
            "services": (
                f"{settings.CLINIC_NAME} provides comprehensive primary care services including annual physical exams, "
                "preventive screenings, management of chronic conditions (such as diabetes, hypertension, and asthma), "
                "acute sick visits, and prescription management."
            ),
            "preparation": (
                "For your appointment, please bring a valid government photo ID, your active insurance card, "
                "and a complete list or bottles of your current medications and supplements."
            ),
            "emergency": (
                "If you or someone with you is experiencing a life-threatening medical emergency (such as severe chest pain, "
                "difficulty breathing, or sudden numbness/weakness), please hang up and call 911 immediately or proceed to the nearest emergency room."
            ),
        }

    def _match_topic(self, query: str) -> Tuple[Optional[str], Optional[str]]:
        """Matches query keywords against approved clinic knowledge topics."""
        q = query.lower()

        if any(w in q for w in ["hour", "open", "close", "time", "weekend", "operating hours"]):
            return "hours", self.clinic_facts["hours"]
        if any(w in q for w in ["location", "address", "where", "parking", "directions", "suite", "building"]):
            return "location", self.clinic_facts["location"]
        if any(w in q for w in ["phone", "call", "telephone", "contact number"]):
            return "phone", self.clinic_facts["phone"]
        if any(w in q for w in ["doctor", "provider", "physician", "chintan", "shah", "staff"]):
            return "doctors", self.clinic_facts["doctors"]
        if any(w in q for w in ["insurance", "medicare", "coverage", "copay", "aetna", "cigna", "bcbs", "blue cross"]):
            return "insurance", self.clinic_facts["insurance"]
        if any(w in q for w in ["service", "treatment", "checkup", "physical", "annual", "screening", "care", "sick"]):
            return "services", self.clinic_facts["services"]
        if any(w in q for w in ["what to bring", "what should i bring", "documents", "bring with me", "prepare for visit", "preparation", "what do i need to bring"]):
            return "preparation", self.clinic_facts["preparation"]
        if any(w in q for w in ["emergency", "911", "urgent", "chest pain", "dying", "er"]):
            return "emergency", self.clinic_facts["emergency"]

        return None, None

    def answer_question(self, request: ClinicKnowledgeRequest) -> ClinicKnowledgeResponse:
        """Answer a question using approved clinic policies, or return answer_found=False."""
        topic, answer = self._match_topic(request.question)

        if answer:
            return ClinicKnowledgeResponse(
                answer_found=True,
                topic=topic,
                answer=answer,
                source=f"{settings.CLINIC_NAME} Official Policies",
                escalate_to_staff=False,
                message=answer,
            )

        # Truthful refusal when answer is not in approved knowledge base
        fallback_msg = (
            f"I don't have approved information regarding '{request.question}' in my clinic directory. "
            f"I would be glad to connect you with our front desk staff at {settings.CLINIC_PHONE} or take a message for you."
        )
        return ClinicKnowledgeResponse(
            answer_found=False,
            topic=None,
            answer=fallback_msg,
            source=f"{settings.CLINIC_NAME} Directory",
            escalate_to_staff=True,
            message=fallback_msg,
        )


knowledge_service = KnowledgeService()

from typing import Literal, Optional
from pydantic import BaseModel, Field


class QRScanEvent(BaseModel):
    employee_code: str = Field(..., min_length=1)
    employee_name: str = Field(..., min_length=1)
    role_type: Literal["Employee", "Intern"] = "Employee"
    department: str = "Corporate & Tax"
    action: Literal["CHECK_IN", "CHECK_OUT"]
    scanned_at: Optional[str] = None


class AcademyFormSubmission(BaseModel):
    khmer_name: str = ""
    latin_name: str = ""
    email: str = ""
    phone: str = ""
    course_title: str = "Double Your Productivity With AI"
    payment_method: str = "ABA KHQR"
    price_usd: float = 0.0


class SurveyFormSubmission(BaseModel):
    respondent_name: str = ""
    organization: str = "Independent"
    chamber: str = "Independent"
    event_name: str = "General Firm Survey"
    department: str = "Academy"
    rating: float = 0.0
    requested_topic: str = "General Legal"
    feedback: str = ""


class ClientOpsSubmission(BaseModel):
    client_name: str = ""
    email: str = ""
    phone: str = ""
    practice_area: str = "Corporate & Tax"
    urgency: str = "Standard"

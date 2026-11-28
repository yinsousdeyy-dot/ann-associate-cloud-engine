from typing import Literal, Optional

from pydantic import BaseModel, Field

# Upper bound for a single Academy fee. Anything larger is quarantined as a probable data-entry error.
MAX_PRICE_USD = 10000.0

SHORT = 120
LONG = 1000


class QRScanEvent(BaseModel):
    employee_code: str = Field(..., min_length=1, max_length=32)
    employee_name: str = Field(..., min_length=1, max_length=SHORT)
    role_type: Literal["Employee", "Intern"] = "Employee"
    department: str = Field("Corporate & Tax", max_length=SHORT)
    action: Literal["CHECK_IN", "CHECK_OUT"]
    scanned_at: Optional[str] = Field(None, max_length=64)


class AcademyFormSubmission(BaseModel):
    khmer_name: str = Field("", max_length=SHORT)
    latin_name: str = Field("", max_length=SHORT)
    email: str = Field("", max_length=254)
    phone: str = Field("", max_length=32)
    course_title: str = Field("Double Your Productivity With AI", max_length=200)
    payment_method: str = Field("ABA KHQR", max_length=60)
    price_usd: float = 0.0


class SurveyFormSubmission(BaseModel):
    respondent_name: str = Field("", max_length=SHORT)
    organization: str = Field("Independent", max_length=160)
    chamber: str = Field("Independent", max_length=60)
    event_name: str = Field("General Firm Survey", max_length=200)
    department: str = Field("Academy", max_length=SHORT)
    rating: float = 0.0
    requested_topic: str = Field("General Legal", max_length=100)
    feedback: str = Field("", max_length=LONG)


class ClientOpsSubmission(BaseModel):
    client_name: str = Field("", max_length=160)
    email: str = Field("", max_length=254)
    phone: str = Field("", max_length=32)
    practice_area: str = Field("Corporate & Tax", max_length=100)
    urgency: str = Field("Standard", max_length=40)

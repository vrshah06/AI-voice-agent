"""Common models, schemas, and validation utilities."""
from datetime import date
from typing import Any, Optional
from pydantic import BaseModel, Field, field_validator
from app.core.config import settings


class BaseDemoResponse(BaseModel):
    """Base response model including demo disclaimer flags."""
    is_demo_data: bool = Field(
        default=True,
        description="Indicates that all returned data is synthetic and simulated for demonstration."
    )
    disclaimer: str = Field(
        default_factory=lambda: settings.DISCLAIMER,
        description="Legal and clinical prototype disclaimer."
    )


def validate_date_not_in_past(v: date) -> date:
    """Helper validator to ensure dates are today or in the future."""
    today = date.today()
    if v < today:
        raise ValueError(f"Requested date ({v.isoformat()}) cannot be in the past. Today is {today.isoformat()}.")
    return v


def validate_dob_not_future(v: date) -> date:
    """Helper validator to ensure date of birth is in the past."""
    today = date.today()
    if v >= today:
        raise ValueError(f"Date of birth ({v.isoformat()}) must be in the past.")
    # Also check reasonable age
    if today.year - v.year > 125:
        raise ValueError(f"Date of birth ({v.isoformat()}) is out of reasonable range (>125 years).")
    return v

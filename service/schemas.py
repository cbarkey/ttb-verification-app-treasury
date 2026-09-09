"""Request/response models for the API.

The verification result itself is passed through as the dict from
`VerificationResult.to_dict()` rather than re-declared here — one schema to keep
in step instead of two. These models cover the API envelope around it.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from ttbverify.models import Commodity


class DeclaredFields(BaseModel):
    """The application values an agent types in, minus the images."""

    serial_number: str = Field(min_length=1)
    brand_name: str = Field(min_length=1)
    class_type: str = Field(min_length=1)
    commodity: Commodity

    ttb_id: str | None = None
    permit_number: str | None = None
    fanciful_name: str | None = None
    alcohol_content: str | None = None
    net_contents: str | None = None
    applicant_name: str | None = None
    applicant_address: str | None = None
    origin: str | None = None

    model_config = {"use_enum_values": True}


class ImageMeta(BaseModel):
    index: int
    role: str | None
    width: int
    height: int
    url: str


class VerifyResponse(BaseModel):
    session_id: str
    result: dict[str, Any]
    images: list[ImageMeta]


class DecisionRequest(BaseModel):
    check_id: str
    decision: Literal["accept", "reject"]


class DecisionResponse(BaseModel):
    decisions: dict[str, str]
    unresolved_review_ids: list[str]
    can_finalize: bool


class FinalizeRequest(BaseModel):
    action: Literal["approve", "reject", "request_image"]


class FinalizeResponse(BaseModel):
    session_id: str
    action: str
    decisions: dict[str, str]


class SessionResponse(BaseModel):
    session_id: str
    result: dict[str, Any]
    images: list[ImageMeta]
    decisions: dict[str, str]
    unresolved_review_ids: list[str]
    can_finalize: bool
    finalized: str | None


class HealthResponse(BaseModel):
    status: str
    ocr: str
    ocr_engine: str
    active_sessions: int

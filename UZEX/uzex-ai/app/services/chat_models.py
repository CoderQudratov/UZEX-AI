"""Pydantic schemas for the Phase 5 Chat API."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    message: str = Field(
        ...,
        min_length=1,
        max_length=4096,
        description="User query in Uzbek (Latin/Cyrillic) or Russian.",
    )


class ChatEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_version: str = Field(..., description="Cryptographic signature of the dataset version")
    tables: list[str] = Field(default_factory=list, description="Referenced warehouse tables")
    filters: list[dict[str, Any]] = Field(default_factory=list, description="Applied query filters")
    source_count: int = Field(0, ge=0, description="Matching transactions or records in the source")


class ChatResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["VERIFIED", "NOT_FOUND", "AMBIGUOUS", "UNSUPPORTED", "ERROR"] = Field(
        ..., description="Execution status"
    )
    language: Literal["uz", "ru", "unsupported"] = Field(
        ..., description="Detected and matched language"
    )
    script: Literal["latin", "cyrillic", "unknown"] = Field(..., description="Detected script")
    answer: str = Field(..., description="Deterministic formatted answer or safe clarification")
    evidence: ChatEvidence | None = Field(
        default=None, description="Audited dataset evidence when executed against warehouse"
    )
    latency_ms: float = Field(0.0, ge=0.0, description="End-to-end request processing time in ms")

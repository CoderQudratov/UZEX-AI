"""Transport errors are separate from future evidence/agent result statuses."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class ErrorCode(StrEnum):
    INVALID_REQUEST = "INVALID_REQUEST"
    ROUTE_NOT_FOUND = "ROUTE_NOT_FOUND"
    METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"
    HTTP_ERROR = "HTTP_ERROR"
    ERROR = "ERROR"


class ErrorDetail(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    code: ErrorCode
    message: str


class ErrorEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    error: ErrorDetail

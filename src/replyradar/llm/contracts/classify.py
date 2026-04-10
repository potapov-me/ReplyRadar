from pydantic import BaseModel, Field


class ClassifyResponse(BaseModel):
    is_signal: bool
    confidence: float = Field(ge=0.0, le=1.0)
    signal_types: list[str] = Field(default_factory=list)

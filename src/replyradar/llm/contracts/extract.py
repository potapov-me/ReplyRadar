from pydantic import BaseModel, Field


class CommitmentItem(BaseModel):
    author: str
    target: str
    text: str
    due_hint: str | None = None


class PendingReplyItem(BaseModel):
    reason: str
    urgency: str = Field(pattern=r"^(high|medium|low)$")


class CommunicationRiskItem(BaseModel):
    type: str
    confidence: float = Field(ge=0.0, le=1.0)
    explanation: str


class ExtractResponse(BaseModel):
    commitments: list[CommitmentItem] = Field(default_factory=list)
    pending_replies: list[PendingReplyItem] = Field(default_factory=list)
    communication_risks: list[CommunicationRiskItem] = Field(default_factory=list)

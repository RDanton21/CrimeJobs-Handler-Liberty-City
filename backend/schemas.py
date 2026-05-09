from datetime import datetime

from pydantic import BaseModel, ConfigDict

from .models import MissionStatus, RelationType


class CrewBase(BaseModel):
    name: str
    story_background: str = ""
    discord_channel_id: str = ""
    color_hex: str = "#b91c1c"


class CrewCreate(CrewBase):
    pass


class CrewUpdate(BaseModel):
    name: str | None = None
    story_background: str | None = None
    discord_channel_id: str | None = None
    color_hex: str | None = None


class CrewOut(CrewBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime


class CrewRelationBase(BaseModel):
    crew_a_id: int
    crew_b_id: int
    relation_type: RelationType = RelationType.NEUTRAL
    notes: str = ""


class CrewRelationOut(CrewRelationBase):
    model_config = ConfigDict(from_attributes=True)
    id: int


class MissionGenerateRequest(BaseModel):
    crew_id: int
    provider: str | None = None
    model: str | None = None
    extra_instructions: str = ""


class MissionRewriteRequest(BaseModel):
    crew_id: int
    raw_input: str
    provider: str | None = None
    model: str | None = None
    extra_instructions: str = ""


class MissionUpdate(BaseModel):
    content_final: str | None = None
    image_path: str | None = None


class MissionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    crew_id: int
    ai_provider: str
    ai_model: str
    content_generated: str
    content_final: str
    image_path: str
    discord_message_id: str
    discord_channel_id: str
    status: MissionStatus
    created_at: datetime
    sent_at: datetime | None
    reacted_at: datetime | None
    archived_at: datetime | None


class StatusOverrideRequest(BaseModel):
    status: MissionStatus


class SettingsUpdate(BaseModel):
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    default_provider: str | None = None
    default_claude_model: str | None = None
    default_openai_model: str | None = None

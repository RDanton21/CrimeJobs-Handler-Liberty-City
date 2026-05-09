from datetime import datetime

from pydantic import BaseModel, ConfigDict

from .models import MissionStatus, RelationType


class CrewBase(BaseModel):
    name: str
    story_background: str = ""
    discord_channel_id: str = ""
    info_channel_id: str = ""
    district: str = ""
    color_hex: str = "#b91c1c"


class CrewCreate(CrewBase):
    pass


class CrewUpdate(BaseModel):
    name: str | None = None
    story_background: str | None = None
    discord_channel_id: str | None = None
    info_channel_id: str | None = None
    district: str | None = None
    color_hex: str | None = None


class CrewOut(CrewBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    last_mission_status: MissionStatus | None = None
    last_mission_at: datetime | None = None


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
    append_text: str = ""
    deadline_minutes: int | None = None
    scheduled_send_at: datetime | None = None


class MissionRewriteRequest(BaseModel):
    crew_id: int
    raw_input: str
    provider: str | None = None
    model: str | None = None
    extra_instructions: str = ""
    append_text: str = ""
    deadline_minutes: int | None = None
    scheduled_send_at: datetime | None = None


class MissionManualRequest(BaseModel):
    crew_id: int
    content: str
    deadline_minutes: int | None = None
    scheduled_send_at: datetime | None = None


class BulkSendRequest(BaseModel):
    crew_ids: list[int]
    content: str
    deadline_minutes: int | None = None
    scheduled_send_at: datetime | None = None


class MissionUpdate(BaseModel):
    content_final: str | None = None
    image_path: str | None = None
    scheduled_send_at: datetime | None = None
    clear_scheduled_send_at: bool = False


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
    deadline_at: datetime | None
    scheduled_send_at: datetime | None = None
    archived_boss_info: str = ""


class StatusOverrideRequest(BaseModel):
    status: MissionStatus


class ExpiryMessageCreate(BaseModel):
    text: str


class ExpiryMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    text: str
    created_at: datetime


class ReactionMessageCreate(BaseModel):
    text: str


class ReactionMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    text: str
    created_at: datetime


class SystemPromptCreate(BaseModel):
    name: str
    text: str


class SystemPromptUpdate(BaseModel):
    name: str | None = None
    text: str | None = None


class SystemPromptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    text: str
    is_active: bool
    created_at: datetime


class SettingsUpdate(BaseModel):
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    default_provider: str | None = None
    default_claude_model: str | None = None
    default_openai_model: str | None = None
    system_prompt: str | None = None

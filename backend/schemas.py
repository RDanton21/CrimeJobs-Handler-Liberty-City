from datetime import datetime

from pydantic import BaseModel, ConfigDict

from .models import MissionStatus, RelationType


class CrewBase(BaseModel):
    name: str
    story_background: str = ""
    crime_business: str = ""
    crime_business_channel_id: str = ""
    discord_channel_id: str = ""
    info_channel_id: str = ""
    district: str = ""
    color_hex: str = "#b91c1c"


class CrewCreate(CrewBase):
    pass


class CrewUpdate(BaseModel):
    name: str | None = None
    story_background: str | None = None
    crime_business: str | None = None
    crime_business_channel_id: str | None = None
    discord_channel_id: str | None = None
    info_channel_id: str | None = None
    district: str | None = None
    color_hex: str | None = None


class CrimeBusinessSendRequest(BaseModel):
    provider: str | None = None
    model: str | None = None


class CrewEnrichRequest(BaseModel):
    """KI-Enrichment: nimmt Basis-Infos (Name, Stadtteil, optional Hint)
    und laesst die KI Story + Business + Farbe + Rivalitaeten vorschlagen.
    Wird sowohl fuer neue Crews (Variante A: Wizard) als auch fuer leere
    Felder existierender Crews (Variante B: Enrich-Button) genutzt."""
    hint: str = ""
    provider: str | None = None
    model: str | None = None


class CrewEnrichRelationSuggestion(BaseModel):
    crew_id: int
    crew_name: str = ""  # wird vom Backend gefuellt fuer die UI
    relation_type: str = "rival"  # rival, hostile, allied, business, neutral
    notes: str = ""


class CrewEnrichPreviewResponse(BaseModel):
    """Antwort auf Preview-Aufruf. Der User reviewt und bestaetigt via /apply."""
    ok: bool = True
    ai_provider: str = ""
    ai_model: str = ""
    story_background: str = ""
    crime_business: str = ""
    color_hex: str = "#b91c1c"
    rivalries: list[CrewEnrichRelationSuggestion] = []
    allies: list[CrewEnrichRelationSuggestion] = []
    raw: str = ""  # Debug-Ausgabe der KI (falls JSON-Parsing fehlschlaegt)


class CrewEnrichApplyRequest(BaseModel):
    """User hat Preview reviewt und bestaetigt einzelne Felder zur Uebernahme.
    Alle Felder sind optional — nur die uebergebenen werden angewendet."""
    story_background: str | None = None
    crime_business: str | None = None
    color_hex: str | None = None
    apply_rivalries: list[CrewEnrichRelationSuggestion] = []
    apply_allies: list[CrewEnrichRelationSuggestion] = []


class CrimeBusinessPostRequest(BaseModel):
    """Postet einen (ggf. editierten) Briefing-Text an den
    crime_business_channel_id der Crew. Kein KI-Aufruf — der Text wurde
    vorher per /preview generiert und vom User ggf. angepasst."""
    content: str


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


class MissionSuggestionsRequest(BaseModel):
    provider: str | None = None
    model: str | None = None


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

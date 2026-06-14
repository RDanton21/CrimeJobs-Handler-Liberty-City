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
    bonus_points: int = 0


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
    bonus_points: int | None = None  # absolute Setzung — für Reset auf 0


class BonusAdjustRequest(BaseModel):
    """Inkrementelle Bonus-Vergabe. Positiv = Bonus, negativ = Strafe."""
    points: int


class CrimeBusinessSendRequest(BaseModel):
    provider: str | None = None
    model: str | None = None


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


class RankingPostRequest(BaseModel):
    channel_id: str
    since: datetime | None = None
    crime_only: bool = True
    top_n: int = 21  # 21 Crime-Crews als Standard
    title: str = "🏆 Crew-Ranking — Liberty City"
    show_district_aggregate: bool = True
    intro: str = ""  # optionaler Begleittext über dem Embed
    mode: str = "full"  # 'full' = Podest + Rest 4–N, 'top3' = nur Top 3 inline
    replace_previous: bool = True  # vorheriges Embed im Channel löschen vorm neuen Post


class MissionUpdate(BaseModel):
    content_final: str | None = None
    image_path: str | None = None
    scheduled_send_at: datetime | None = None
    clear_scheduled_send_at: bool = False
    personnel_brief: str | None = None


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
    personnel_brief: str = ""
    personnel_updated_at: datetime | None = None
    personnel_discord_message_id: str = ""


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


class Top3TitlePoolCreate(BaseModel):
    text: str


class Top3TitlePoolOut(BaseModel):
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
    ranking_daily_enabled: str | None = None
    ranking_daily_channel_id: str | None = None
    ranking_daily_time: str | None = None
    ranking_daily_range: str | None = None
    ranking_daily_crime_only: str | None = None
    ranking_daily_show_districts: str | None = None
    ranking_daily_title: str | None = None
    ranking_daily_intro: str | None = None
    ranking_top3_enabled: str | None = None
    ranking_top3_channel_id: str | None = None
    ranking_top3_time: str | None = None
    ranking_top3_range: str | None = None
    ranking_top3_crime_only: str | None = None
    ranking_top3_title: str | None = None
    ranking_top3_intro: str | None = None
    personnel_admin_channel_id: str | None = None

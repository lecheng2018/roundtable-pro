from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime


class AgentConfig(BaseModel):
    provider: str = ""
    model: str = ""
    role: str = "debater"
    name: str = ""
    stance: str = ""
    agent_id: str = ""  # Optional: reference to a created QwenPaw agent


class RoundConfig(BaseModel):
    mode: str = "discuss"
    agent_count: int = 2
    roles: List[AgentConfig] = []
    rounds: int = 2
    need_search: bool = False


class Message(BaseModel):
    role: str = ""
    name: str = ""
    content: str = ""
    agent: Optional[str] = None
    round: int = 1


class ReportData(BaseModel):
    summary: str = ""
    consensus: List[str] = []
    recommendations: List[str] = []


class Discussion(BaseModel):
    hid: str
    topic: str
    mode: str = "discuss"
    config: RoundConfig = RoundConfig()
    messages: List[Message] = []
    report: Optional[ReportData] = None
    created_at: datetime = datetime.now()


class DiscussRequest(BaseModel):
    topic: str
    mode: str = "discuss"
    max_agents: int = 4
    agents: List[AgentConfig] = []
    brainstorm: bool = False
    economy: bool = False
    files: List[str] = []
    judge: Optional[AgentConfig] = None


# ── Persona template models ──────────────────────────────────────

class PersonaTemplate(BaseModel):
    """A pre-configured persona template for creating debate agents."""
    id: str
    name: str
    description: str
    suggested_provider: str = "github-models"
    suggested_model: str = "gpt-4o-mini"
    skills: List[str] = Field(default_factory=lambda: ["search"])
    suggested_stance: str = ""
    # Raw content for agent workspace files
    soul_md: str = ""
    profile_md: str = ""
    agents_md: str = ""


# ── Debater agent management models ──────────────────────────────

class DebaterCreateRequest(BaseModel):
    """Request to create a new debater agent from a persona template."""
    template_id: str
    name: str = Field(..., min_length=1, max_length=50)
    provider: str = ""
    model: str = ""
    stance: Optional[str] = None


class DebaterUpdateRequest(BaseModel):
    """Update an existing debater agent's model configuration."""
    provider: Optional[str] = None
    model: Optional[str] = None
    stance: Optional[str] = None


class DebaterAgent(BaseModel):
    """A created debater agent summary."""
    agent_id: str
    name: str
    template_id: str
    description: str
    provider: str = ""
    model: str = ""
    stance: str = ""
    status: str = "active"  # active, stopped, error
    created_at: str = ""


# ── Roundtable participant (maps agent_id to role) ───────────────

class DebateParticipant(BaseModel):
    """A participant in a roundtable, referencing a created debater agent."""
    agent_id: str
    role: str = "debater"  # host, debater, judge

import os
import sys
import json
import logging
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional

plugin_dir = os.path.dirname(os.path.abspath(__file__))
if plugin_dir not in sys.path:
    sys.path.insert(0, plugin_dir)

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse

from .models import (
    DiscussRequest, DebaterCreateRequest, DebaterUpdateRequest,
    DebaterAgent, PersonaTemplate,
)
from .engine import run_roundtable
from .brainstorm import run_brainstorm
from .sse import EventStream
from .storage import Storage

logger = logging.getLogger(__name__)

router = APIRouter()

# ── Paths ────────────────────────────────────────────────────────
PERSONAS_DIR = Path(plugin_dir) / "personas"
WORKSPACES_ROOT = Path(
    os.environ.get(
        "QWENPAW_WORKSPACES_DIR",
        "/vol2/@appshare/com.dustinky.qwenpaw/.qwenpaw/workspaces",
    )
)
DEBATER_PREFIX = "rdeb_"  # Prefix for roundtable debater agents

# ── State & plugin lifecycle ──────────────────────────────────────
STATE_PATH = Path(plugin_dir) / ".qwenpaw-roundtable-state.json"
ROLE_MARKER = "<!-- managed-by: roundtable-pro -->"


def _load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"version": 1, "agents_created": [], "installed_at": None}


def _save_state(state: dict):
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


# ── Plugin lifecycle hooks ────────────────────────────────────────

async def _on_startup():
    """Startup validation for roundtable-pro plugin."""
    logger.info("RoundTable-Pro startup check…")
    issues = []
    if not PERSONAS_DIR.exists():
        issues.append(f"Personas directory not found: {PERSONAS_DIR}")
    data_dir = Path(plugin_dir) / "data"
    data_dir.mkdir(exist_ok=True)
    state = _load_state()
    if state.get("installed_at") is None:
        state["installed_at"] = datetime.utcnow().isoformat()
        _save_state(state)
    if issues:
        logger.warning("RoundTable-Pro startup issues: %s", "; ".join(issues))
    else:
        logger.info("RoundTable-Pro startup OK")


async def _on_uninstall(plugin_id: str = "", delete_files: bool = False):
    """Cleanup all roundtable-pro agents and data on uninstall."""
    logger.info("RoundTable-Pro uninstall: cleaning up agents & data…")

    # 1. Collect all rdeb_ agents
    try:
        from qwenpaw.config.utils import load_config, save_config

        config = load_config()
        to_remove = [
            aid for aid in config.agents.profiles
            if aid.startswith(DEBATER_PREFIX)
        ]
        for aid in to_remove:
            ws = config.agents.profiles[aid].workspace_dir
            if ws and os.path.isdir(ws):
                shutil.rmtree(ws, ignore_errors=True)
                logger.info("  Removed workspace: %s", ws)
            del config.agents.profiles[aid]
            if aid in config.agents.agent_order:
                config.agents.agent_order.remove(aid)
            logger.info("  Removed agent: %s", aid)
        save_config(config)
    except Exception as e:
        logger.warning("  Could not clean up agents: %s", e)

    # 2. Remove data directory
    data_dir = Path(plugin_dir) / "data"
    if data_dir.exists():
        shutil.rmtree(data_dir, ignore_errors=True)
        logger.info("  Removed data/ directory")

    # 3. Remove state file
    if STATE_PATH.exists():
        STATE_PATH.unlink(missing_ok=True)
        logger.info("  Removed state file")

    logger.info("RoundTable-Pro uninstall cleanup complete")


# ── Persona template helpers ─────────────────────────────────────

def _load_persona_templates() -> List[PersonaTemplate]:
    """Load all persona templates from the personas/ directory."""
    templates = []
    if not PERSONAS_DIR.exists():
        return templates
    for f in sorted(PERSONAS_DIR.glob("*.json")):
        try:
            with open(f, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            templates.append(PersonaTemplate(**data))
        except Exception as e:
            logger.warning("Failed to load persona %s: %s", f.name, e)
    return templates


def _get_persona(template_id: str) -> Optional[PersonaTemplate]:
    """Get a persona template by ID."""
    for t in _load_persona_templates():
        if t.id == template_id:
            return t
    return None


# ── Agent workspace file content helpers ─────────────────────────

def _debater_agent_id(name: str) -> str:
    """Generate a unique agent ID for a debater."""
    safe = "".join(c for c in name if c.isascii() and (c.isalnum() or c in "_"))
    suffix = uuid.uuid4().hex[:6]
    return f"{DEBATER_PREFIX}{safe}_{suffix}"


def _build_agent_json(
    agent_id: str,
    name: str,
    description: str,
    workspace_dir: str,
    provider_id: str,
    model: str,
) -> dict:
    """Build the agent.json dict for a new debater agent."""
    return {
        "id": agent_id,
        "name": name,
        "description": description,
        "workspace_dir": workspace_dir,
        "language": "zh",
        "approval_level": "AUTO",
        "active_model": {
            "provider_id": provider_id,
            "model": model,
        },
        "system_prompt_files": ["AGENTS.md", "SOUL.md", "PROFILE.md"],
        "channels": {
            "imessage": {"enabled": False},
            "discord": {"enabled": False},
            "dingtalk": {"enabled": False},
            "feishu": {"enabled": False},
            "qq": {"enabled": False},
            "telegram": {"enabled": False},
            "mattermost": {"enabled": False},
            "mqtt": {"enabled": False},
            "console": {"enabled": True},
            "matrix": {"enabled": False},
            "voice": {"enabled": False},
            "sip": {"enabled": False},
            "wecom": {"enabled": False},
            "xiaoyi": {"enabled": False},
            "yuanbao": {"enabled": False},
            "wechat": {"enabled": False},
            "onebot": {"enabled": False},
        },
        "mcp": {
            "enabled": False,
            "servers": {},
        },
        "heartbeat": {
            "enabled": False,
            "every": "6h",
            "target": "main",
        },
        "running": {
            "max_iters": 25,
            "auto_continue_on_text_only": True,
            "llm_retry_enabled": True,
            "llm_max_retries": 3,
            "llm_backoff_base": 2.0,
            "llm_backoff_cap": 60.0,
            "llm_max_concurrent": 1,
            "llm_max_qpm": 0,
            "llm_rate_limit_pause": 0.0,
            "llm_rate_limit_jitter": 0.0,
            "llm_acquire_timeout": 120.0,
            "shell_command_timeout": 60.0,
            "shell_command_executable": "",
            "max_input_length": 131072,
            "history_max_length": 10000,
            "context_manager_backend": "light",
            "light_context_config": {},
            "auto_title_config": {},
            "memory_manager_backend": "simple",
            "reme_light_memory_config": {},
            "daily_memory_dir": "memory",
        },
        "llm_routing": {
            "enabled": False,
            "mode": "local_first",
            "local": {"provider_id": "", "model": ""},
        },
        "tools": {
            "builtin_tools": {
                "execute_shell_command": {
                    "name": "execute_shell_command",
                    "enabled": False,
                    "description": "Execute shell commands",
                    "display_to_user": True,
                    "async_execution": True,
                    "icon": "💻",
                    "config": {},
                },
                "read_file": {
                    "name": "read_file",
                    "enabled": False,
                    "description": "Read file contents",
                    "display_to_user": True,
                    "async_execution": False,
                    "icon": "📄",
                    "config": {},
                },
                "grep_search": {
                    "name": "grep_search",
                    "enabled": False,
                    "description": "Search file contents",
                    "display_to_user": True,
                    "async_execution": False,
                    "icon": "🔍",
                    "config": {},
                },
                "tavily_search": {
                    "name": "tavily_search",
                    "enabled": True,
                    "description": "Search the web for current information",
                    "display_to_user": True,
                    "async_execution": False,
                    "icon": "🌐",
                    "config": {},
                },
            }
        },
        "plan": {"enabled": False},
        "coding_mode": {"enabled": False},
    }


# ── Agent creation / deletion ────────────────────────────────────

def _create_debater_workspace(
    agent_id: str,
    name: str,
    description: str,
    template: PersonaTemplate,
    provider_id: str,
    model: str,
) -> Path:
    """Create workspace directory and files for a new debater agent.
    
    Returns the workspace path.
    """
    ws_dir = WORKSPACES_ROOT / agent_id
    ws_dir.mkdir(parents=True, exist_ok=True)

    # Create subdirectories
    for sub in ["sessions", "memory", "dialog", "tool_results", "skills"]:
        (ws_dir / sub).mkdir(exist_ok=True)

    # Write SOUL.md
    (ws_dir / "SOUL.md").write_text(template.soul_md or f"你是{name}，圆桌讨论的参与者。", encoding="utf-8")

    # Write PROFILE.md
    profile = f"## 身份\n- {name}\n- {description}\n"
    if template.profile_md:
        profile = template.profile_md
    (ws_dir / "PROFILE.md").write_text(profile, encoding="utf-8")

    # Write AGENTS.md
    agents_content = template.agents_md or f"## 工作方式\n- 在圆桌讨论中参与辩论\n- 每次发言控制在200字以内\n- 基于{description}的视角发表观点\n- 尊重其他参与者的发言"
    (ws_dir / "AGENTS.md").write_text(agents_content, encoding="utf-8")

    # Write MEMORY.md
    (ws_dir / "MEMORY.md").write_text(f"# {name} 的记忆\n\n这是{name}在圆桌讨论中的初始记忆。\n", encoding="utf-8")

    # Write ROLE.md — strong role injection like Superpowers' SUPERPOWERS.md
    role_md = (
        f"{ROLE_MARKER}\n"
        f"# {name} — 角色定义\n\n"
        f"## 你是谁\n"
        f"{template.description}\n\n"
        f"## 角色信条\n"
        f"{template.soul_md or '认真参与圆桌讨论，基于你的专业视角发表观点。'}\n\n"
        f"## 讨论规则\n"
        f"- 你正在参与一场多智能体圆桌讨论\n"
        f"- 讨论话题由主持人给出\n"
        f"- 每次发言都要严格基于自己{name}的身份和专业知识\n"
        f"- 不要跳出角色，不要说自己'作为一个AI助手'\n"
        f"- 直接表达观点，不要询问'需要我做什么'\n"
        f"- 回答应当简洁有深度（200字以内）\n"
        f"- 可以反驳、补充、深化其他人的观点\n\n"
        f"## 禁止\n"
        f"- 不要谦虚推让，你是这个领域的专家\n"
        f"- 不要长篇大论，每次发言聚焦1-2个核心论点\n"
        f"- 不要偏离自己的角色设定\n\n"
        f"**记住：你正在参与圆桌讨论，你是有专业身份的{name}，请全力以赴。**\n"
    )
    (ws_dir / "ROLE.md").write_text(role_md, encoding="utf-8")

    # Write agent.json
    agent_config = _build_agent_json(agent_id, name, description, str(ws_dir), provider_id, model)
    with open(ws_dir / "agent.json", "w", encoding="utf-8") as f:
        json.dump(agent_config, f, ensure_ascii=False, indent=2)

    # Write empty jobs.json
    with open(ws_dir / "jobs.json", "w", encoding="utf-8") as f:
        json.dump({"version": 1, "jobs": []}, f, ensure_ascii=False, indent=2)

    # Write empty chats.json
    with open(ws_dir / "chats.json", "w", encoding="utf-8") as f:
        json.dump({"version": 1, "chats": []}, f, ensure_ascii=False, indent=2)

    # Create empty skill.json
    skill_path = ws_dir / "skill.json"
    if not skill_path.exists():
        with open(skill_path, "w", encoding="utf-8") as f:
            json.dump({"enabled_skills": []}, f, ensure_ascii=False, indent=2)

    logger.info("Created debater workspace at %s", ws_dir)
    return ws_dir


def _register_agent_in_config(agent_id: str, workspace_dir: str):
    """Register a new agent in the global QwenPaw config."""
    try:
        from qwenpaw.config.utils import load_config, save_config
        from qwenpaw.config.config import AgentProfileRef, save_agent_config
    except ImportError as e:
        raise RuntimeError(f"Cannot import QwenPaw config modules: {e}")

    config = load_config()
    if agent_id in config.agents.profiles:
        raise ValueError(f"Agent '{agent_id}' already exists")

    ref = AgentProfileRef(
        id=agent_id,
        workspace_dir=workspace_dir,
        enabled=True,
    )
    config.agents.profiles[agent_id] = ref

    # Update agent order
    if hasattr(config.agents, "agent_order") and config.agents.agent_order is not None:
        config.agents.agent_order.append(agent_id)
    else:
        config.agents.agent_order = list(config.agents.profiles.keys())

    save_config(config)

    # Also save agent config from the workspace's agent.json
    agent_json_path = Path(workspace_dir) / "agent.json"
    if agent_json_path.exists():
        with open(agent_json_path, "r", encoding="utf-8") as f:
            agent_config_data = json.load(f)
        from qwenpaw.config.config import AgentProfileConfig
        # Build an AgentProfileConfig from the JSON data
        agent_cfg = AgentProfileConfig(
            id=agent_id,
            name=agent_config_data.get("name", agent_id),
            description=agent_config_data.get("description", ""),
            workspace_dir=workspace_dir,
            language=agent_config_data.get("language", "zh"),
            active_model=agent_config_data.get("active_model", None),
        )
        save_agent_config(agent_id, agent_cfg)

    logger.info("Registered agent '%s' in global config", agent_id)


def _unregister_agent_from_config(agent_id: str):
    """Remove an agent from the global QwenPaw config."""
    try:
        from qwenpaw.config.utils import load_config, save_config
    except ImportError as e:
        raise RuntimeError(f"Cannot import QwenPaw config modules: {e}")

    config = load_config()
    if agent_id not in config.agents.profiles:
        return  # Already removed

    del config.agents.profiles[agent_id]

    if hasattr(config.agents, "agent_order") and config.agents.agent_order is not None:
        config.agents.agent_order = [
            a for a in config.agents.agent_order if a != agent_id
        ]

    save_config(config)
    logger.info("Unregistered agent '%s' from global config", agent_id)


# ── List created debaters ────────────────────────────────────────

def _list_debater_agents() -> List[DebaterAgent]:
    """List all roundtable debater agents that have been created."""
    try:
        from qwenpaw.config.utils import load_config
    except ImportError:
        return []

    config = load_config()
    result = []
    for agent_id, ref in config.agents.profiles.items():
        if not agent_id.startswith(DEBATER_PREFIX):
            continue
        # Read agent.json for more info
        ws_dir = Path(ref.workspace_dir)
        agent_json_path = ws_dir / "agent.json"
        name = agent_id
        description = ""
        provider_id = ""
        model = ""
        stance = ""

        if agent_json_path.exists():
            try:
                with open(agent_json_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                name = data.get("name", agent_id)
                description = data.get("description", "")
                am = data.get("active_model", {}) or {}
                provider_id = am.get("provider_id", "")
                model = am.get("model", "")
            except Exception:
                pass

        result.append(DebaterAgent(
            agent_id=agent_id,
            name=name,
            template_id="",
            description=description,
            provider=provider_id,
            model=model,
            stance=stance,
            status="active",
            created_at="",
        ))
    return result


# ── API Endpoints ────────────────────────────────────────────────

@router.get("/models")
async def list_models(request: Request):
    pm = request.app.state.provider_manager
    result = []
    providers = []
    for container in (getattr(pm, "builtin_providers", {}), getattr(pm, "custom_providers", {})):
        if isinstance(container, dict):
            providers.extend(container.values())

    for p in providers:
        name = getattr(p, "name", None) or getattr(p, "id", None)
        pid = getattr(p, "id", None) or name
        if not name:
            continue
        try:
            if getattr(p, "support_model_discovery", False):
                models_info = await p.fetch_models()
                models = [getattr(m, "id", str(m)) for m in models_info]
            else:
                all_models = getattr(p, "models", []) + getattr(p, "extra_models", [])
                models = [getattr(m, "id", str(m)) for m in all_models]
            result.append({"provider": name, "provider_id": pid, "models": models})
        except Exception as e:
            result.append({"provider": name, "provider_id": pid, "models": [], "error": str(e)})
    return result


@router.get("/personas")
async def list_personas():
    """List all available persona templates."""
    return [t.model_dump() for t in _load_persona_templates()]


@router.post("/debaters")
async def create_debater(req: DebaterCreateRequest, request: Request):
    """Create a new debater agent from a persona template."""
    # Validate template
    template = _get_persona(req.template_id)
    if not template:
        raise HTTPException(status_code=404, detail=f"Persona template '{req.template_id}' not found")

    # Resolve provider/model
    provider_id = req.provider or template.suggested_provider
    model = req.model or template.suggested_model

    if not provider_id or not model:
        raise HTTPException(status_code=400, detail="Provider and model are required")

    # Generate agent ID
    agent_id = _debater_agent_id(req.name)

    # Create workspace and files
    try:
        ws_dir = _create_debater_workspace(
            agent_id=agent_id,
            name=req.name,
            description=template.description,
            template=template,
            provider_id=provider_id,
            model=model,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create workspace: {str(e)}")

    # Register in config
    try:
        _register_agent_in_config(agent_id, str(ws_dir))
    except Exception as e:
        # Cleanup workspace on failure
        import shutil
        shutil.rmtree(ws_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"Failed to register agent: {str(e)}")

    # Try to start the agent (lazy load via multi_agent_manager)
    try:
        mam = getattr(request.app.state, "multi_agent_manager", None)
        if mam:
            await mam.get_agent(agent_id)
    except Exception as e:
        logger.warning("Agent '%s' created but could not be started: %s", agent_id, e)

    # Track in state
    state = _load_state()
    if agent_id not in state["agents_created"]:
        state["agents_created"].append(agent_id)
    _save_state(state)

    return DebaterAgent(
        agent_id=agent_id,
        name=req.name,
        template_id=req.template_id,
        description=template.description,
        provider=provider_id,
        model=model,
        stance=req.stance or template.suggested_stance,
        status="active",
        created_at=datetime.utcnow().isoformat(),
    )


@router.get("/debaters")
async def list_debaters():
    """List all created roundtable debater agents."""
    return _list_debater_agents()


@router.put("/debaters/{agent_id}")
async def update_debater(agent_id: str, req: DebaterUpdateRequest):
    """Update a debater agent's model configuration."""
    try:
        from qwenpaw.config.config import load_agent_config, save_agent_config
    except ImportError as e:
        raise HTTPException(status_code=500, detail=f"Import error: {e}")

    try:
        agent_cfg = load_agent_config(agent_id)
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found: {e}")

    if req.provider is not None or req.model is not None:
        current = agent_cfg.active_model or {}
        agent_cfg.active_model = {
            "provider_id": req.provider or current.get("provider_id", ""),
            "model": req.model or current.get("model", ""),
        }
        save_agent_config(agent_id, agent_cfg)

        # Also update agent.json
        ws_dir = Path(agent_cfg.workspace_dir)
        agent_json_path = ws_dir / "agent.json"
        if agent_json_path.exists():
            with open(agent_json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            data["active_model"] = {
                "provider_id": agent_cfg.active_model["provider_id"],
                "model": agent_cfg.active_model["model"],
            }
            with open(agent_json_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

    return {"status": "ok", "agent_id": agent_id}


@router.delete("/debaters/{agent_id}")
async def delete_debater(agent_id: str):
    """Delete a debater agent."""
    try:
        from qwenpaw.config.config import load_agent_config
    except ImportError:
        pass

    # Get workspace dir before unregistering
    ws_dir = None
    try:
        cfg = load_agent_config(agent_id)
        ws_dir = Path(cfg.workspace_dir) if cfg.workspace_dir else None
    except Exception:
        pass

    # Unregister from config
    try:
        _unregister_agent_from_config(agent_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to unregister agent: {e}")

    # Delete workspace files
    if ws_dir and ws_dir.exists():
        import shutil
        try:
            shutil.rmtree(ws_dir)
            logger.info("Deleted workspace %s", ws_dir)
        except Exception as e:
            logger.warning("Failed to delete workspace %s: %s", ws_dir, e)

    return {"status": "ok", "message": f"Agent '{agent_id}' deleted"}


# ── Discuss / Brainstorm (keep existing) ────────────────────────

@router.post("/discuss")
async def discuss(req: DiscussRequest, request: Request):
    pm = request.app.state.provider_manager
    stream = EventStream()

    async def gen():
        try:
            async for chunk in run_roundtable(pm, req, stream):
                yield chunk
        except Exception as e:
            yield f"event: error\ndata: {{\"message\": \"{str(e)}\"}}\n\n"
            yield "event: done\ndata: {{}}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.post("/brainstorm")
async def brainstorm(req: DiscussRequest, request: Request):
    pm = request.app.state.provider_manager
    stream = EventStream()

    async def gen():
        try:
            async for chunk in run_brainstorm(pm, req, stream):
                yield chunk
        except Exception as e:
            yield f"event: error\ndata: {{\"message\": \"{str(e)}\"}}\n\n"
            yield "event: done\ndata: {{}}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.get("/history")
async def list_history():
    rows = Storage().list_all()
    return [
        {
            "hid": r.hid,
            "topic": r.topic,
            "mode": r.mode,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


@router.get("/history/{hid}")
async def get_history(hid: str):
    d = Storage().get(hid)
    if not d:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse({
        "hid": d.hid,
        "topic": d.topic,
        "mode": d.mode,
        "config": d.config.model_dump(),
        "messages": [m.model_dump() for m in d.messages],
        "report": d.report.model_dump() if d.report else None,
        "created_at": d.created_at.isoformat(),
    })


@router.get("/history/{hid}/raw")
async def get_history_raw(hid: str):
    d = Storage().get(hid)
    if not d:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse(d.model_dump())


@router.delete("/history/{hid}")
async def delete_history(hid: str):
    Storage().delete(hid)
    return {"status": "ok"}


class RoundTableProPlugin:
    def register(self, api):
        logger.info("RoundTable-Pro 注册中...")
        api.register_http_router(router, prefix="/frontend_plugin/roundtable-pro")
        api.register_startup_hook("validate", _on_startup, priority=50)
        api.register_uninstall_hook("cleanup", _on_uninstall, priority=50)
        logger.info("RoundTable-Pro 就绪（启动钩子+卸载钩子已注册）")


plugin = RoundTableProPlugin()

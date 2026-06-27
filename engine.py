import uuid
import json
import re
import asyncio
from typing import AsyncGenerator, Optional

from .models import DiscussRequest, RoundConfig, AgentConfig, Message, ReportData, Discussion
from .config import DEFAULT_HOST, DEFAULT_JUDGE, HOST_PROMPT, JUDGE_PROMPT, DEBATER_PROMPT_TEMPLATE
from .storage import Storage
from .sse import EventStream


# ── Agent communication via QwenPaw's inter-agent API ─────────

async def call_agent(
    agent_id: str,
    text: str,
    session_id: Optional[str] = None,
    timeout: int = 120,
) -> str:
    """Send a message to a QwenPaw agent and get its response.
    
    Uses the same mechanism as chat_with_agent tool — makes an HTTP
    call to the QwenPaw server's /api/agent/process endpoint.
    """
    try:
        from qwenpaw.agents.tools.agent_management import (
            build_agent_chat_request,
            collect_final_agent_chat_response,
            agent_exists,
            extract_agent_text_content,
        )
    except ImportError as e:
        return f"[Agent communication unavailable: {e}]"

    # Check agent exists
    exists = await asyncio.to_thread(agent_exists, agent_id, None)
    if not exists:
        return f"[Agent '{agent_id}' not found]"

    # Build and send the chat request
    try:
        final_session_id, request_payload, _ = build_agent_chat_request(
            to_agent=agent_id,
            text=text,
            session_id=session_id,
            from_agent=None,
        )
    except Exception as e:
        return f"[Failed to build request: {e}]"

    try:
        response_data = await asyncio.to_thread(
            collect_final_agent_chat_response,
            None,
            request_payload,
            agent_id,
            timeout,
        )
    except Exception as e:
        return f"[Agent '{agent_id}' response failed: {e}]"

    if not response_data:
        return "(No response received)"

    # Use QwenPaw's built-in extractor for agent response
    # The response data structure is: {"output": [{"content": [{"type": "text", "text": "..."}]}]}
    try:
        text = extract_agent_text_content(response_data)
        if text:
            return text
        # Fallback: try direct content field
        content = response_data.get("content", "")
        if isinstance(content, list):
            texts = []
            for block in content:
                if isinstance(block, dict):
                    t = block.get("text", block.get("content", ""))
                    if t:
                        texts.append(t)
            return "\n".join(texts)
        return str(content)
    except Exception as e:
        return str(response_data)


async def call_model(provider_manager, agent: AgentConfig, messages: list, temperature: float = 0.7) -> str:
    """Call a model via QwenPaw's Provider API.
    
    Used as fallback when no agent_id is provided.
    """
    provider = provider_manager.get_provider(agent.provider)
    if provider is None:
        raise ValueError(f"Provider '{agent.provider}' not found")
    chat_model = provider.get_chat_model_instance(agent.model)
    result = await chat_model(
        messages=messages,
        temperature=temperature,
    )
    # Handle async generator responses (providers always stream)
    if hasattr(result, "__aiter__"):
        text_parts = []
        async for chunk in result:
            if hasattr(chunk, "content") and chunk.content:
                for block in chunk.content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text_parts.append(block["text"])
        return "".join(text_parts)
    # Handle direct response
    if hasattr(result, "content") and result.content:
        if isinstance(result.content, list):
            texts = []
            for block in result.content:
                if isinstance(block, dict) and block.get("type") == "text":
                    texts.append(block["text"])
            return "".join(texts)
        return str(result.content)
    return str(result)


async def get_agent_response(
    provider_manager,
    agent: AgentConfig,
    messages: list,
    session_id: Optional[str] = None,
    temperature: float = 0.7,
) -> str:
    """Get a response from either a QwenPaw agent or direct model call.
    
    If agent.agent_id is set, uses inter-agent communication.
    Otherwise falls back to direct model call via Provider API.
    """
    if agent.agent_id:
        # Build the message text from the messages list
        text_parts = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if isinstance(content, list):
                content = " ".join(
                    c.get("text", "") for c in content if isinstance(c, dict)
                )
            text_parts.append(f"[{role}]\n{content}")
        text = "\n\n".join(text_parts)
        return await call_agent(agent.agent_id, text, session_id=session_id, timeout=120)
    else:
        return await call_model(provider_manager, agent, messages, temperature=temperature)


async def host_config(provider_manager, topic: str, mode: str, max_agents: int) -> RoundConfig:
    messages = [
        {"role": "system", "content": HOST_PROMPT},
        {"role": "user", "content": f"话题：{topic}\n模式：{mode}\n最多辩手数：{max_agents}\n\n请分析这个话题并给出配置。注意：必须包含provider和model字段，使用可用的provider ID（如github-models、deepseek等）。"}
    ]
    text = await call_model(provider_manager, DEFAULT_HOST, messages, temperature=0.3)
    text = _extract_json(text)
    cfg = json.loads(text)
    roles = []
    for i, r in enumerate(cfg.get("roles", [])):
        roles.append(AgentConfig(
            provider=r.get("provider", DEFAULT_HOST.provider),
            model=r.get("model", DEFAULT_HOST.model),
            role="debater",
            name=r.get("name", f"辩手{i+1}"),
            stance=r.get("stance", "")
        ))
    return RoundConfig(
        mode=cfg.get("mode", mode),
        agent_count=len(roles),
        roles=roles,
        rounds=min(cfg.get("rounds", 2), 4),
        need_search=cfg.get("need_search", False)
    )


def _extract_json(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"```(?:json)?\s*", "", text)
        text = text.rstrip("`")
    return text.strip()


async def run_roundtable(provider_manager, req: DiscussRequest, stream: EventStream):
    hid = str(uuid.uuid4())[:8]
    
    # Build config from provided agents or auto-generate
    if req.agents and len(req.agents) > 0:
        config = RoundConfig(
            mode=req.mode,
            agent_count=len(req.agents),
            roles=req.agents,
            rounds=3,
            need_search=False
        )
    else:
        config = await host_config(provider_manager, req.topic, req.mode, req.max_agents)

    discussion = Discussion(
        hid=hid, topic=req.topic, mode=config.mode,
        config=config, messages=[]
    )

    async for chunk in stream.emit("config", {
        "hid": hid,
        "mode": config.mode,
        "agents": [{"name": a.name, "role": a.role, "stance": a.stance} for a in config.roles]
    }):
        yield chunk

    # Session tracking per agent for multi-round context
    agent_sessions = {}
    for a in config.roles:
        if a.agent_id:
            agent_sessions[a.name] = {"agent_id": a.agent_id, "session_id": None}

    history_text = ""
    for round_idx in range(1, config.rounds + 1):
        # Host generates follow-up question (round 2+)
        question = ""
        if round_idx > 1:
            q_messages = [
                {"role": "system", "content": "你是主持人。基于历史发言，生成 1 个追问问题，要求下一轮的辩手必须回应。只输出问题。"},
                {"role": "user", "content": f"本轮讨论的历史发言：\n{history_text}\n\n请生成一个追问问题。"}
            ]
            try:
                question = await call_model(provider_manager, DEFAULT_HOST, q_messages, temperature=0.3)
            except Exception as e:
                question = f"请进一步阐述你们的观点。"

        for agent in config.roles:
            if agent.role != "debater":
                continue
            name = agent.name
            stance = agent.stance

            # Build the prompt for this debater
            msg = question if question else ""
            prompt = DEBATER_PROMPT_TEMPLATE.format(name=name, stance=stance, topic=req.topic)
            if msg:
                prompt += f"\n\n主持人追问：{msg}"

            debate_messages = [{"role": "system", "content": prompt}]
            if history_text:
                debate_messages.append({"role": "user", "content": f"前面已有发言：\n{history_text}\n\n请基于前面的讨论，继续发表你的观点。"})
            else:
                debate_messages.append({"role": "user", "content": f"请开始你的发言，谈谈对[{req.topic}]的看法。"})

            try:
                session_id = agent_sessions.get(name, {}).get("session_id") if agent.agent_id else None
                text = await get_agent_response(
                    provider_manager, agent, debate_messages,
                    session_id=session_id, temperature=0.7
                )
                # Track session for real agents
                if agent.agent_id and name in agent_sessions:
                    # Session ID is set by the first call; subsequent calls reuse it
                    pass
            except Exception as e:
                text = f"[{name} 发言失败：{str(e)}]"

            m = Message(role="debater", name=name, content=text, agent=agent.provider or agent.agent_id, round=round_idx)
            discussion.messages.append(m)
            history_text += f"\n{name}（第{round_idx}轮）：{text}"

            async for chunk in stream.emit("message", {
                "round": round_idx,
                "name": name,
                "role": "debater",
                "content": text,
                "agent": agent.provider or agent.agent_id,
                "done": False
            }):
                yield chunk

    # Judge summary
    try:
        judge_agent = req.judge or (req.agents[0] if req.agents else DEFAULT_JUDGE)
        judge_messages = [
            {"role": "system", "content": JUDGE_PROMPT},
            {"role": "user", "content": f"请对以下讨论进行总结和评判。\n\n讨论话题：{req.topic}\n\n完整记录：\n{history_text}"}
        ]
        judge_text = await get_agent_response(
            provider_manager, judge_agent, judge_messages,
            temperature=0.3
        )
        judge_text = _extract_json(judge_text)
        report_data = json.loads(judge_text)
    except Exception as e:
        report_data = {
            "summary": f"总结生成失败：{str(e)}",
            "consensus": [],
            "recommendations": []
        }

    report = ReportData(**report_data)
    discussion.report = report

    async for chunk in stream.emit("report", {
        "summary": report.summary,
        "consensus": report.consensus,
        "recommendations": report.recommendations,
    }):
        yield chunk

    # Save to storage
    try:
        Storage().save(discussion)
    except Exception as e:
        pass

    async for chunk in stream.emit("done", {"hid": hid}):
        yield chunk

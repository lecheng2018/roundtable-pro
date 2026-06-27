import uuid
from .models import DiscussRequest, AgentConfig, Message, RoundConfig, Discussion
from .config import DEFAULT_HOST, HOST_PROMPT
from .storage import Storage
from .sse import EventStream
from .engine import call_model, _extract_json


BRAINSTORM_PROMPT = """你叫{name}，是一名头脑风暴参与者。
讨论话题：{topic}

请围绕话题自由发散，提出有价值的观点和创意。要求：
1. 从不同角度思考
2. 字数适量（100-200字）
3. 鼓励大胆、创新的想法
4. 可以回应或补充前面的发言"""


async def run_brainstorm(provider_manager, req: DiscussRequest, stream: EventStream):
    hid = str(uuid.uuid4())[:8]

    if req.agents and len(req.agents) > 0:
        config = RoundConfig(
            mode="brainstorm",
            agent_count=len(req.agents),
            roles=req.agents,
            rounds=3,
            need_search=False
        )
    else:
        config = await host_config(provider_manager, req.topic, req.mode, req.max_agents)
        config.mode = "brainstorm"

    discussion = Discussion(
        hid=hid, topic=req.topic, mode="brainstorm",
        config=config, messages=[]
    )

    async for chunk in stream.emit("config", {
        "hid": hid,
        "mode": "brainstorm",
        "agents": [{"name": a.name, "role": a.role, "stance": a.stance} for a in config.roles]
    }):
        yield chunk

    history_text = ""
    for round_idx in range(1, config.rounds + 1):
        for agent in config.roles:
            if agent.role not in ("debater", "brainstormer"):
                continue
            name = agent.name

            prompt = BRAINSTORM_PROMPT.format(name=name, topic=req.topic)
            msgs = [{"role": "system", "content": prompt}]
            if history_text:
                msgs.append({"role": "user", "content": f"前面已有发言：\n{history_text}\n\n请补充你的独特见解。"})
            else:
                msgs.append({"role": "user", "content": f"请围绕话题[{req.topic}]自由发散，提出有价值的观点和创意。"})

            try:
                text = await call_model(provider_manager, agent, msgs, temperature=0.8)
            except Exception as e:
                text = f"[{name} 发言失败：{str(e)}]"

            m = Message(role="brainstormer", name=name, content=text, agent=agent.provider, round=round_idx)
            discussion.messages.append(m)
            history_text += f"\n{name}：{text}"

            async for chunk in stream.emit("message", {
                "round": round_idx,
                "name": name,
                "role": "brainstormer",
                "content": text,
                "agent": agent.provider,
                "done": False
            }):
                yield chunk

    Storage().save(discussion)
    async for chunk in stream.emit("done", {"hid": hid}):
        yield chunk
from .models import AgentConfig

DEFAULT_HOST = AgentConfig(provider="github-models", model="gpt-4o-mini", role="host", name="主持人", stance="中立客观")
DEFAULT_JUDGE = AgentConfig(provider="github-models", model="gpt-4o-mini", role="judge", name="裁判", stance="中立公正")

ROLE_TEMPLATES = {
    "host": "主持人：引导讨论，提出追问，控制节奏",
    "debater": "辩手：从不同立场论证观点",
    "judge": "裁判：总结共识，给出建议",
}

HOST_PROMPT = """你是圆桌讨论的主持人。你的职责是：
1. 分析话题，确定讨论模式（辩论/头脑风暴）
2. 为每位辩手分配角色和立场
3. 控制讨论轮次（1-4轮）
4. 判断是否需要搜索外部信息

输出格式（纯 JSON，不要 markdown 包裹）：
{
  "mode": "discuss" 或 "brainstorm",
  "roles": [
    {"provider": "github-models", "model": "gpt-4o-mini", "name": "辩手A", "stance": "支持立场"},
    {"provider": "deepseek", "model": "deepseek-chat", "name": "辩手B", "stance": "反对立场"}
  ],
  "rounds": 2,
  "need_search": false
}"""

JUDGE_PROMPT = """你是圆桌讨论的裁判。你的职责是：
1. 总结各辩手的核心观点
2. 找出共识和分歧
3. 给出建设性建议

输出格式（纯 JSON，不要 markdown 包裹）：
{
  "summary": "讨论总结",
  "consensus": ["共识1", "共识2"],
  "recommendations": ["建议1", "建议2"]
}"""

DEBATER_PROMPT_TEMPLATE = """你叫{name}，立场是：{stance}。
讨论话题：{topic}

请发表你的观点。要求：
1. 观点明确，有理有据
2. 字数适中（150-300字）
3. 可以引用常识或经验
4. 如果前面有发言，请回应并补充"""

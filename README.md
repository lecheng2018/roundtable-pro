# Roundtable Pro 🪑

> **QwenPaw 插件** — 多智能体圆桌讨论，让你的 AI 们围坐一桌碰撞观点。

![QwenPaw](https://img.shields.io/badge/QwenPaw-Plugin-ff7f16)
![License](https://img.shields.io/badge/license-MIT-blue)

---

## 特性

- 🎙️ **标准讨论模式** — 多轮辩论，主持人引导，裁判总结
- 💡 **头脑风暴模式** — 自由发散，创意碰撞
- 🤖 **真实 Agent 参与** — 从人设模板一键创建 QwenPaw agent，通过智能体通信参与讨论
- 🧠 **内置 8 种人设** — 数据科学家、风险官、产品经理、JS 全栈、Python 极客、运维老手、杠精、乐观派
- 🌓 **双主题 UI** — 自动跟随 QwenPaw 控制台亮色/暗色主题
- 📋 **历史记录** — 讨论记录持久化，支持查看和删除
- 🔌 **即装即用** — 热重载，无需重启 QwenPaw

## 快速开始

### 安装

```bash
# 进入 QwenPaw plugins 目录
cd /path/to/qwenpaw/plugins

# 克隆仓库
git clone https://github.com/lecheng2018/roundtable-pro.git
```

重启 QwenPaw 或在控制台重载插件列表，侧边栏出现 🪑 **圆桌 Pro** 即安装成功。

### 使用

1. **创建辩手**：在人设列表选择一个模板 → 填写 agent_id → 创建
2. **勾选参与者**：从已创建的辩手中勾选本次讨论的人选
3. **设置参数**：选择模式（标准/头脑风暴）、轮数、是否启用裁判总结
4. **开始讨论**：输入话题，点击「开始讨论」

## 架构

```
frontend/index.html     ← 单页 Web UI（原生 JS + 现代 CSS）
main.py                 ← FastAPI 路由注册 + HTTP 接口
engine.py               ← 标准讨论引擎 + 模型调用封装
brainstorm.py           ← 头脑风暴引擎
config.py               ← 默认配置和提示词
models.py               ← 数据模型定义
storage.py              ← JSON 文件持久化
sse.py                  ← SSE 流式推送
personas/               ← 人设模板（JSON）
data/                   ← 讨论记录存储
```

## API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET  | `/models` | 获取可用 Provider 和模型列表 |
| GET  | `/personas` | 获取人设模板列表 |
| POST | `/debaters` | 创建辩手 agent |
| GET  | `/debaters` | 列出所有辩手 |
| PUT  | `/debaters/{agent_id}` | 更新辩手配置 |
| DELETE | `/debaters/{agent_id}` | 删除辩手 |
| POST | `/discuss` | 发起标准讨论（SSE 流式） |
| POST | `/brainstorm` | 发起头脑风暴（SSE 流式） |
| GET  | `/history` | 历史记录列表 |
| GET  | `/history/{hid}` | 历史记录详情 |
| DELETE | `/history/{hid}` | 删除历史记录 |

## 讨论流程

### 标准模式
```
主持人开场 → 辩手依次发言（第1轮）
           → 主持人追问
           → 辩手依次发言（第2轮）
           → ...（多轮迭代）
           → 裁判总结（JSON 报告）
```

### 头脑风暴模式
```
参与者自由发散 → 每轮补充新观点 → 多轮迭代 → 完成
```

## 人设模板

| 名称 | 角色 | 适用场景 |
|------|------|----------|
| 🧪 数据科学家 | 数据驱动、统计思维 | 需要数据分析的讨论 |
| ⚠️ 风险官 | 风险评估、稳健决策 | 风险评估、方案评审 |
| 👤 产品经理 | 用户视角、需求导向 | 产品设计、功能讨论 |
| 🎨 JS 全栈 | 技术实现、工程视角 | 技术选型、架构讨论 |
| 🐍 Python 极客 | Python 生态、最佳实践 | Python 相关技术讨论 |
| 🔧 运维老手 | 运维经验、可靠性 | 部署运维、稳定性 |
| 🤔 杠精 | 质疑一切、找漏洞 | 压力测试、找方案缺陷 |
| 🎯 乐观派 | 积极视角、寻找机会 | 创意发散、寻找突破 |

## 开发

```bash
# 插件路径
/path/to/qwenpaw/plugins/roundtable-pro/

# 修改后端 Python 文件后立即生效（热重载）
# 修改前端需关闭侧边栏重新打开
```

### 依赖

- QwenPaw >= v1.x
- Python ≥ 3.10
- 无需额外 npm 或构建工具

## License

MIT

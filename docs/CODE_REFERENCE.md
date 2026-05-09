# Paixueji 完整代码逻辑参考文档

> 本文档基于对项目全部源代码的通读，目标是在不查看源码的情况下回答所有代码逻辑问题。
> 文档按"从外到内、从静到动"组织：先静态架构，再动态流程。

---

## 目录

1. [系统核心概念与术语](#1-系统核心概念与术语)
2. [整体架构图](#2-整体架构图)
3. [HTTP API 层（paixueji_app.py）](#3-http-api-层)
4. [会话状态容器（PaixuejiAssistant）](#4-会话状态容器)
5. [对象解析系统](#5-对象解析系统)
6. [桥接激活状态机（核心）](#6-桥接激活状态机)
7. [LangGraph 工作流](#7-langgraph-工作流)
8. [意图分类与路由](#8-意图分类与路由)
9. [流式生成器层](#9-流式生成器层)
10. [属性与类别探索管道](#10-属性与类别探索管道)
11. [知识库与数据加载](#11-知识库与数据加载)
12. [Prompt 模板库](#12-prompt-模板库)
13. [Trace 与自我进化系统](#13-trace-与自我进化系统)
14. [Schema 与数据结构](#14-schema-与数据结构)
15. [配置与常量](#15-配置与常量)
16. [完整执行流程 walkthrough](#16-完整执行流程-walkthrough)
17. [边缘情况与回退矩阵](#17-边缘情况与回退矩阵)

---

## 1. 系统核心概念与术语

### 1.1 核心使命
面向 3-8 岁儿童的**对象探索对话教育系统**。系统围绕一个"对象"与儿童展开多轮问答，通过教学支架（scaffolding）引导观察、思考和表达。

### 1.2 对象的四层映射
| 层级 | 含义 | 示例 |
|------|------|------|
| `surface_object_name` | 儿童实际说的词 | "kitty" |
| `visible_object_name` | 对外展示用的词 | "kitty" |
| `anchor_object_name` | 内部知识库中的标准对象 | "cat" |
| `anchor_status` | 解析状态 | exact_supported / anchored_high / anchored_medium / unresolved |

**关键理解**：surface 与 anchor 不一致时（如孩子说 "kitty" 但知识库是 "cat"），系统启动**桥接激活**流程。

### 1.3 桥接相位（Bridge Phase）
4 个状态构成状态机：`none` → `pre_anchor` → `activation` → `anchor_general`

- `none`：未涉及桥接
- `pre_anchor`：孩子仍在用 surface 词，系统在旁铺垫
- `activation`：正式引导孩子向 anchor 概念移动（最多 4 轮）
- `anchor_general`：孩子已接受 anchor，进入正常对话

### 1.3 三种对话通道（Lane）
| 通道 | 触发条件 | 特点 |
|------|----------|------|
| 普通聊天（Ordinary Chat） | 默认 | 意图驱动，13 种意图分类 |
| 属性探索（Attribute Lane） | 答对 2 次后 + 主题分类 | 聚焦单一物理维度/子属性 |
| 类别探索（Category Lane） | 答对 2 次后 + 主题分类 | 更宽泛的领域探索 |

### 1.4 13 种交际意图
儿童的每句话被分类为以下意图，每种对应专门的响应策略：

| 意图 | 代码标识 | 典型触发 |
|------|----------|----------|
| 好奇心 | `CURIOSITY` | "为什么/是什么/怎么样" |
| 澄清-不知道 | `CLARIFYING_IDK` | "我不知道" |
| 澄清-错误 | `CLARIFYING_WRONG` | 给出错误答案 |
| 澄清-约束 | `CLARIFYING_CONSTRAINT` | 部分正确但受限的答案 |
| 正确回答 | `CORRECT_ANSWER` | 答对了 |
| 知识分享 | `INFORMATIVE` | 孩子主动分享知识 |
| 玩耍 | `PLAY` | 搞怪、想象、游戏 |
| 情绪表达 | `EMOTIONAL` | 表达感受 |
| 回避 | `AVOIDANCE` | 拒绝参与 |
| 边界试探 | `BOUNDARY` | 试探危险行为 |
| 行动指令 | `ACTION` | 命令 AI 做事（含 A/B/C/D 子类型） |
| 社交询问 | `SOCIAL` | 问关于 AI 的问题 |
| 社交回应 | `SOCIAL_ACKNOWLEDGMENT` | 社交性回应 |
| 概念混淆 | `CONCEPT_CONFUSION` | 概念混乱 |

### 1.5 两步串行生成
多数意图响应采用"先回应、后提问"的串行生成：
1. `generate_intent_response_stream` —— 生成对儿童的回应文本（无问题）
2. `ask_followup_question_stream` —— 生成下一个跟进问题

### 1.6 关键阈值与常量
| 常量 | 值 | 含义 |
|------|-----|------|
| `GUIDE_MODE_THRESHOLD` | 2 | 累计答对几次后触发主题分类 |
| `MAX_BRIDGE_ACTIVATION_TURNS` | 4 | 桥接激活最多几轮 |
| `MAX_BRIDGE_ATTEMPTS` | 2 | 桥接尝试最多几次 |
| `MAX_PRE_ANCHOR_SUPPORT_TURNS` | 2 | 预锚定支持最多几轮 |
| `SLOW_LLM_CALL_THRESHOLD` | 5.0s | LLM 调用慢于此时告警 |
| `CATEGORY_ACTIVITY_READY_TURN_THRESHOLD` | 2 | 类别活动就绪阈值 |

---

## 2. 整体架构图

```
┌─────────────────────────────────────────────────────────────────────┐
│                         HTTP / Flask 层                              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐ │
│  │  /api/start │  │/api/continue│  │/api/reset   │  │/api/sessions│ │
│  └─────────────┘  └──────┬──────┘  └─────────────┘  └─────────────┘ │
│                          │                                          │
│  ┌───────────────────────┴───────────────────────────────────────┐  │
│  │              continue_conversation (核心枢纽, ~1000+ 行)       │  │
│  │  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐             │  │
│  │  │ Category    │ │ Attribute   │ │ Bridge      │             │  │
│  │  │ Lane        │ │ Lane        │ │ Activation  │             │  │
│  │  └─────────────┘ └─────────────┘ └──────┬──────┘             │  │
│  │                                         │                      │  │
│  │  ┌──────────────────────────────────────┴──────────────────┐  │  │
│  │  │              普通图执行（LangGraph）                      │  │  │
│  │  └─────────────────────────────────────────────────────────┘  │  │
│  └───────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      LangGraph 工作流层                               │
│                                                                     │
│   START ──► [router:route_from_start]                               │
│                  │                                                  │
│     ┌────────────┴────────────┐                                     │
│     ▼                         ▼                                     │
│ generate_intro          analyze_input                               │
│     │                         │                                     │
│     │              router:route_from_analyze_input                  │
│     │                         │                                     │
│     │     ┌─────┬─────┬─────┬─┴─────┬─────┬─────┐                  │
│     │     ▼     ▼     ▼     ▼       ▼     ▼     ▼                  │
│     │  13个意图节点 + classify_theme + give_answer_idk              │
│     │     │     │     │     │       │     │     │                  │
│     └─────┴─────┴─────┴─────┴───────┴─────┴─────┘                  │
│                              │                                      │
│                              ▼                                      │
│                         generate_question                           │
│                              │                                      │
│                              ▼                                      │
│                           finalize                                  │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      流式生成器层（Stream/）                          │
│  ┌────────────────────┐  ┌────────────────────┐  ┌──────────────┐  │
│  │response_generators │  │question_generators │  │  validation  │  │
│  │  - intent responses│  │  - intro question  │  │  - classify  │  │
│  │  - bridge responses│  │  - followup        │  │  - validate  │  │
│  │  - attribute/cat   │  │  - attribute intro │  │  - mapping   │  │
│  └────────────────────┘  └────────────────────┘  └──────────────┘  │
│  ┌────────────────────┐  ┌────────────────────┐                    │
│  │     fun_fact       │  │      utils         │                    │
│  │  - 2-step pipeline │  │  - msg conversion  │                    │
│  │  - safety checks   │  │  - hook selection  │                    │
│  └────────────────────┘  └────────────────────┘                    │
└─────────────────────────────────────────────────────────────────────┘
```

### 2.1 五层职责边界

| 层级 | 职责 | 是否持有状态 | 是否调用 LLM |
|------|------|-------------|-------------|
| HTTP 传输层 | 请求/响应、SSE 封装、会话查找 | 是（sessions 字典） | 间接 |
| 状态管理层 | 状态容器、配置加载、年龄 prompt | 是（PaixuejiAssistant） | 否 |
| 图编排层 | 工作流节点、条件路由、执行追踪 | 否（纯函数） | 间接 |
| 流式生成层 | 所有 LLM 流式生成器 | 否 | 是 |
| 知识/策略层 | YAML 加载、桥接策略、主题分类 | 否 | 部分 |

---

## 3. HTTP API 层

### 3.1 端点清单

| 端点 | 方法 | 作用 |
|------|------|------|
| `/` | GET | 静态前端页面 |
| `/api/health` | GET | 健康检查 |
| `/api/objects` | GET | 列出所有支持的对象（从 YAML 加载） |
| `/api/start` | POST | 开始新对话 |
| `/api/continue` | POST | 继续对话（核心） |
| `/api/reset` | POST | 删除会话 |
| `/api/sessions` | GET | 列出所有活跃会话 |
| `/api/lookup-concepts` | POST | 查询对象+年龄对应的概念 |
| `/api/force-switch` | POST | 强制切换话题 |
| `/api/exchanges/<session_id>` | GET | 提取交换三元组 |
| `/api/manual-critique` | POST | 提交人工反馈 |

### 3.2 `/api/start` 流程

```
接收: {session_id, object_name, age}
  │
  ▼
创建 PaixuejiAssistant 实例
  │
  ▼
对象解析: resolve_object_input(raw_object_name, age, client, config)
  │
  ├─► exact_supported: YAML 中有完全匹配
  ├─► anchored_high: LLM 推断高置信度锚定
  ├─► anchored_medium: 中置信度锚定
  └─► unresolved: 未解析
  │
  ▼
应用解析结果到 assistant
  │
  ▼
根据解析状态设置 intro_mode:
  ├─ anchor_status != "exact_supported" + 有锚点 → "anchor_confirmation"
  ├─ anchor_status == "unresolved" → "unknown_object"
  └─ 否则 → 普通 introduction
  │
  ▼
加载维度数据 (load_dimension_data)
加载对象上下文 (load_object_context_from_yaml)
  │
  ▼
选择 hook_type（年龄加权随机采样）
构建知识上下文 (knowledge_context)
  │
  ▼
调用 ask_introduction_question_stream → SSE 流返回
```

### 3.3 `/api/continue` 流程（核心枢纽）

这是系统最复杂的部分。`continue_conversation` 函数内部按**优先级**判断走哪条通道：

```
接收: {session_id, child_input}
  │
  ▼
获取 session → assistant
获取或创建事件循环 (asyncio.new_event_loop)
  │
  ▼
【通道优先级判断】（按顺序，互斥）

1. category_lane_active == True?
   ├─ 是 → 走 Category Lane 完整处理
   │        (classify_category_reply → evaluate_readiness → generate)
   └─ 否 → 继续

2. attribute_lane_active == True?
   ├─ 是 → 走 Attribute Lane 完整处理
   │        (classify_intent → generate_attribute_activation_response
   │         → 检测 [ACTIVITY_READY] 标记 → 验证 → generate)
   └─ 否 → 继续

3. bridge_phase == "none" AND 有锚点 AND activation_reopen_signal?
   ├─ 是 → 走 Bridge Activation Reopen
   │        (生成桥接重开响应，进入 activation 相位)
   └─ 否 → 继续

4. bridge_phase == "activation"?
   ├─ 是 → 走 Bridge Activation Continuation
   │        (验证上一问 → 验证答案 → 判定 handoff →
   │         或继续 activation 或 handoff 到 anchor_general)
   └─ 否 → 继续

5. bridge_phase == "pre_anchor"?
   ├─ 是 → 走 Pre-Anchor Gate
   │        (classify_pre_anchor_reply → 判定:
   │         ├─ 澄清请求 → 桥接支持响应
   │         ├─ IDK → 桥接支持响应
   │         ├─ 拒绝 → 消耗一次 bridge_attempt，若未超限则重试
   │         └─ 跟随桥接 → 进入 activation 相位)
   └─ 否 → 继续

6. 【默认】普通图执行
   └─► 构建 initial_state → stream_graph_execution → SSE 返回
```

### 3.4 SSE 流格式

每个 SSE event 有 `event:` 字段（chunk / complete / error）和 `data:` 字段：
- `chunk` 事件携带 `StreamChunk` JSON
- `complete` 事件携带 `{"success": true}`
- `error` 事件携带错误详情

`StreamChunk` 有 60+ 字段，核心字段：
- `response`: 文本内容
- `finish`: 是否是最后一 chunk
- `response_type`: 响应类型（introduction / curiosity / bridge_retry 等）
- `intent_type`: 意图类型
- `bridge_debug`: 桥接调试信息
- `nodes_executed`: 节点执行追踪

---

## 4. 会话状态容器（PaixuejiAssistant）

### 4.1 类职责
`PaixuejiAssistant` 是系统的**状态黑洞**——持有会话的所有状态。每个会话一个实例，存于全局 `sessions` 字典中。

### 4.2 核心字段分类

**对象解析字段**：
- `object_name`: 当前活跃对象
- `surface_object_name`: 孩子说的词
- `anchor_object_name`: 知识库标准对象
- `anchor_status`: 解析状态
- `anchor_relation`: 关系类型（food_for, used_with, part_of 等）
- `anchor_confidence_band`: 置信度区间

**桥接字段**：
- `bridge_phase`: 当前相位（none/pre_anchor/activation/anchor_general）
- `bridge_attempt_count`: 已尝试次数（最大 MAX_BRIDGE_ATTEMPTS=2）
- `bridge_profile`: BridgeProfile 实例
- `pre_anchor_support_count`: 预锚定支持轮数
- `activation_turn_count`: 激活轮数计数
- `activation_handoff_ready`: 是否准备好 handoff
- `activation_last_question`: 上一问文本
- `activation_last_question_kb_item`: 上一问对应的 KB 条目

**计数器与标志**：
- `correct_answer_count`: 累计答对次数
- `consecutive_struggle_count`: 连续困惑计数（IDK/Wrong 递增，其他清零）
- `conversation_history`: OpenAI 格式的消息列表

**管道状态**：
- `attribute_lane_active`: 属性通道是否激活
- `attribute_pipeline_enabled`: 属性管道是否启用
- `category_lane_active`: 类别通道是否激活
- `category_pipeline_enabled`: 类别管道是否启用

**IB PYP 主题字段**：
- `ibpyp_theme_name`: 主题名称
- `key_concept`: 关键概念
- `chat_phase_complete`: 聊天阶段是否完成

**知识库字段**：
- `physical_dimensions`: 物理维度字典
- `engagement_dimensions`: 参与维度字典
- `used_kb_item`: 已使用的 KB 条目

### 4.3 关键方法

| 方法 | 作用 |
|------|------|
| `apply_resolution(resolution)` | 将 ObjectResolutionResult 应用到自身 |
| `activate_anchor_topic(anchor_name)` | 激活锚点对象，加载维度数据 |
| `begin_bridge_activation()` | 初始化桥接激活状态 |
| `commit_bridge_activation()` | 提交桥接激活，进入 anchor_general |
| `clear_bridge_activation()` | 清除桥接状态 |
| `load_dimension_data(object_name)` | 从 YAML 加载维度数据 |
| `load_object_context_from_yaml(object_name)` | 加载对象上下文 |
| `suppress_anchor(anchor_name)` | 抑制某个锚点（避免反复尝试） |
| `set_last_bridge_debug(debug)` | 设置最近的桥接调试信息 |

---

## 5. 对象解析系统（object_resolver.py）

### 5.1 解析流程

```
resolve_object_input(raw_name, age, client, config)
  │
  ▼
Step 1: 精确匹配
  └─► 在 YAML 对象列表中查找完全匹配
      ├─ 命中 → ObjectResolutionResult(status="exact_supported")
      └─ 未命中 → 继续
  │
  ▼
Step 2: LLM 回退推断
  └─► _model_fallback()
      构建候选短名单（YAML 中所有对象）
      调用 LLM 判断 raw_name 最可能对应哪个对象
      LLM 返回: {anchor_object_name, relation, confidence}
      ├─ confidence >= 0.8 → "anchored_high"
      ├─ confidence >= 0.5 → "anchored_medium"
      └─ 否则 → "unresolved"
  │
  ▼
Step 3: 关系修复
  └─► 如果 relation 不在 SUPPORTED_RELATIONS 中 → 规范化为 "related_to"
  │
  ▼
Step 4: 桥接 profile 构建
  └─► 如果 anchor_status 不是 exact_supported → infer_bridge_profile()
      调用 LLM 生成桥接策略（桥接意图、好问题角度、避免角度、回拉规则）
```

### 5.2 ObjectResolutionResult

```
surface_object_name: str      # 原始输入
visible_object_name: str      # 展示用
anchor_object_name: str       # 锚定对象（可能为 None）
status: str                   # exact_supported / anchored_high / anchored_medium / unresolved
relation: str                 # 关系类型
confidence: float             # 置信度
bridge_profile: BridgeProfile # 桥接策略
resolution_debug: dict        # 调试信息
```

### 5.3 锚定确认解析
`parse_anchor_confirmation(child_input, surface, anchor)` → `"accept"` / `"reject"` / `"unclear"`

使用 LLM 判断孩子是否确认接受锚定对象。

---

## 6. 桥接激活状态机（核心）

这是系统最复杂的子系统，涉及 6 个模块：
- `bridge_profile.py` —— 桥接策略推断
- `bridge_context.py` —— 桥接上下文构建
- `bridge_debug.py` —— 调试信息构建
- `bridge_activation_policy.py` —— 激活策略（问题匹配、答案检测）
- `pre_anchor_policy.py` —— 预锚定回复分类
- `stream/response_generators.py` —— 桥接响应生成

### 6.1 BridgeProfile（桥接策略）

当 surface ≠ anchor 时，系统需要一个"如何从 A 聊到 B"的策略。`infer_bridge_profile()` 调用 LLM 生成：

```
bridge_intent: str           # 桥接意图（如 "引导从 kitty 认识到 cat 是家养宠物"）
good_question_angles: tuple  # 好的提问角度
avoid_angles: tuple          # 应避免的提问角度
steer_back_rule: str         # 如果孩子偏离，如何拉回
focus_cues: tuple            # 焦点提示词
```

### 6.2 预锚定阶段（pre_anchor）

当对象解析得到 anchored_high/medium 状态后，系统不会立即桥接，而是先进入 `pre_anchor` 阶段：

**判定逻辑**：
```
如果 bridge_phase == "pre_anchor":
  1. 用 classify_pre_anchor_reply() 分类孩子的回复
     ├─ "clarification_request" → 需要澄清，不消耗尝试次数
     ├─ "idk_or_stuck" → 孩子卡住了，提供支架，不消耗尝试次数
     ├─ "negative_or_refusal" → 明确拒绝，消耗一次 bridge_attempt
     ├─ "in_lane_follow" → 孩子跟随了桥接方向！→ 进入 activation 阶段
     ├─ "anchor_related_but_off_lane" → 相关但偏离 → 引导回正轨
     └─ "true_miss" → 完全没接 → 消耗一次 bridge_attempt

  2. 如果 consume_bridge_attempt 且 attempt_count < MAX_BRIDGE_ATTEMPTS:
     → 构建 BridgeContext，重试桥接

  3. 如果尝试次数耗尽:
     → 标记为 unresolved，走 surface_only 模式
```

### 6.3 激活阶段（activation）

进入 activation 后，系统开始**正式引导孩子接受 anchor 概念**。这是最严密的验证链条：

**每轮 activation 的执行流程**：
```
1. 验证上一问（如果存在）:
   a. match_activation_question_to_kb_deterministic()
      ──► 用 token 重叠启发式判断上一问是否基于 KB 条目
   b. 如果 matched → handoff_ready = True

2. 检测孩子的答案:
   a. detect_activation_answer_heuristic()
      ──► 判断孩子是 yes/no/pivot/还是实质性回答
   b. classify_activation_reopen_signal()
      ──► 判断孩子的回答是否触及 anchor 侧内容（用于 reopen 判定）

3. 判定 handoff:
   如果同时满足:
   - 上一问是 KB 支撑的 (handoff_ready)
   - 孩子回答了上一问
   - 连续性锚点保持
   - 未超过 MAX_BRIDGE_ACTIVATION_TURNS
   → 执行 handoff：bridge_phase → "anchor_general"

4. 如果未 handoff 且未超轮数:
   → 继续 activation：生成下一个桥接问题

5. 如果超过最大轮数:
   → 标记 unresolved，回退到普通对话
```

**handoff_ready 的完整判定条件**（分散在代码中）：
- `activation_last_question_kb_item` 不为 None（上一问匹配到 KB）
- 孩子回答了上一问（非空、非 pivot）
- 连续性锚点未被打破
- 当前轮数 <= MAX_BRIDGE_ACTIVATION_TURNS

### 6.4 BridgeContext 构建

根据 BridgeProfile 和尝试次数构建 prompt 上下文：
- 第 1 次尝试："Start from the surface object, then bridge through..."
- 第 2 次+："Acknowledge briefly, then make one final bridge..."

### 6.5 桥接可见性检测

`detect_bridge_visibility(response_text, surface, anchor, relation, bridge_profile)` → `(bool, reason)`

检测 AI 的响应是否**暴露了桥接关系**（即是否让孩子察觉到 "kitty → cat" 的转换）。如果 anchor 词出现在 surface 词之外的位置，或者匹配了 focus_cues，则判定为"可见"。

---

## 7. LangGraph 工作流

### 7.1 状态定义（PaixuejiState TypedDict）

约 30 个字段，核心字段：
- `messages`: 对话历史
- `content`: 当前用户输入
- `age`, `age_prompt`: 年龄相关信息
- `object_name`, `surface_object_name`, `anchor_object_name`: 对象信息
- `anchor_status`, `anchor_relation`, `anchor_confidence_band`: 解析状态
- `bridge_phase`, `bridge_attempt_count`: 桥接状态
- `correct_answer_count`, `consecutive_struggle_count`: 计数器
- `intent_type`, `new_object_name`, `detected_object_name`: 分析输出
- `physical_dimensions`, `engagement_dimensions`: KB 数据
- `fun_fact`, `fun_fact_hook`, `fun_fact_question`: 趣闻状态
- `nodes_executed`: 执行追踪

### 7.2 节点列表

| 节点 | 职责 |
|------|------|
| `router:route_from_start` | 判断是开场（introduction）还是聊天 |
| `generate_intro` | 生成开场（已废弃，开场走 HTTP 层） |
| `analyze_input` | 分析输入：意图分类 |
| `router:route_from_analyze_input` | 根据意图+计数器路由到目标节点 |
| `curiosity` | 好奇心意图处理 |
| `clarifying_idk` | 不知道意图处理 |
| `clarifying_wrong` | 错误答案意图处理 |
| `clarifying_constraint` | 约束答案意图处理 |
| `give_answer_idk` | 深度困惑直接给答案 |
| `correct_answer` | 正确回答处理 |
| `informative` | 知识分享处理 |
| `play` | 玩耍意图处理 |
| `emotional` | 情绪表达处理 |
| `avoidance` | 回避处理 |
| `boundary` | 边界试探处理 |
| `action` | 行动指令处理 |
| `social` | 社交询问处理 |
| `social_acknowledgment` | 社交回应处理 |
| `concept_confusion` | 概念混淆处理 |
| `classify_theme` | 主题分类（答对阈值触发） |
| `finalize` | 收尾：组装 StreamChunk |

### 7.3 路由逻辑

**START → 路由**：
- 如果 `response_type == "introduction"` → `generate_intro`
- 否则 → `analyze_input`

**analyze_input 之后的路由**：
```
if consecutive_struggle_count >= 2:
  → give_answer_idk（连续困惑，直接给答案）

elif intent_type == "CORRECT_ANSWER" and correct_answer_count >= GUIDE_MODE_THRESHOLD:
  → classify_theme（答对阈值，触发主题分类）

else:
  → 根据 intent_type 路由到对应节点
```

### 7.4 节点执行追踪

每个节点被 `@trace_node` 或 `@trace_router` 装饰器包装，自动记录：
- `node`: 节点名称
- `time_ms`: 执行耗时
- `changes`: 状态变更
- `state_before`: 执行前状态
- `phase`: "response" 或 "question"

---

## 8. 意图分类与路由

### 8.1 classify_intent()（stream/validation.py）

```
输入: messages, age, object_name, last_model_response, config, client
  │
  ▼
构建 USER_INTENT_PROMPT（包含 13 种意图的定义和示例）
  │
  ▼
调用 LLM (gemini-2.0-flash-lite, temp=0.1, max_tokens=60)
  │
  ▼
解析 LLM 输出（正则提取）:
  INTENT: <意图名>
  NEW_OBJECT: <对象名或 null>
  REASONING: <推理>
  ACTION_SUBTYPE: <A/B/C/D>  (仅 ACTION 意图)
  │
  ▼
验证意图名是否在有效集合中
标准化为全大写
  │
  ▼
返回: {intent_type, new_object_name, reasoning, action_subtype}
```

### 8.2 意图节点的统一处理模式

所有意图节点遵循相同模式：
1. 从 state 中提取相关字段
2. 调用 `generate_intent_response_stream()` 生成回应
3. 调用 `ask_followup_question_stream()` 生成跟进问题
4. 合并回应 + 问题
5. 更新 state（correct_answer_count 等）

### 8.3 ACTION 意图的子类型

| 子类型 | 含义 |
|--------|------|
| A | 要求 AI 执行动作（"你跳一下"） |
| B | 要求做某事的变体 |
| C | 角色扮演请求 |
| D | 其他行动指令 |

---

## 9. 流式生成器层

### 9.1 response_generators.py

| 生成器 | 用途 |
|--------|------|
| `generate_intent_response_stream` | 通用意图回应生成 |
| `generate_bridge_activation_response_stream` | 桥接激活阶段回应 |
| `generate_bridge_retry_response_stream` | 桥接重试回应 |
| `generate_topic_switch_response_stream` | 话题切换回应 |
| `generate_attribute_activation_response_stream` | 属性通道回应 |
| `generate_category_activation_response_stream` | 类别通道回应 |

**统一接口**：所有生成器都接收 `messages, config, client` + 特定参数，返回 `AsyncGenerator[(text_chunk, token_usage, full_response, decision_info), None]`

### 9.2 question_generators.py

| 生成器 | 用途 |
|--------|------|
| `ask_introduction_question_stream` | 开场问题（支持多种 intro_mode） |
| `ask_followup_question_stream` | 跟进问题 |
| `ask_attribute_intro_stream` | 属性介绍问题 |
| `ask_category_intro_stream` | 类别介绍问题 |

### 9.3 消息准备流程

所有生成器共享相同的消息准备流程：
```
原始 messages
  │
  ▼
clean_messages_for_api() ──► 只保留 role 和 content
  │
  ▼
convert_messages_to_gemini_format() ──► (system_instruction, contents)
  │
  ▼
构建 GenerateContentConfig(temperature, max_output_tokens, system_instruction)
  │
  ▼
调用 client.aio.models.generate_content_stream()
  │
  ▼
逐 chunk yield 文本
```

### 9.4 validation.py

| 函数 | 用途 |
|------|------|
| `classify_intent()` | 13 意图分类 |
| `classify_pre_anchor_semantic_reply()` | 预锚定语义分类 |
| `validate_bridge_activation_kb_question()` | 验证桥接问题是否有 KB 支撑 |
| `map_response_to_kb_item()` | 将响应映射到 KB 条目（调试用） |

---

## 10. 属性与类别探索管道

### 10.1 Attribute Lane（attribute_activity.py）

**入口**：答对 2 次后，`classify_theme` 节点触发主题分类，根据主题选择是否走属性管道。

**流程**：
```
1. select_attribute_profile()
   ├─ infer_domain(object_name) → 推断领域
   ├─ get_candidate_sub_attributes(domain, age) → 获取候选子属性
   └─ LLM 选择最合适的属性 → AttributeProfile

2. start_attribute_session(profile) → DiscoverySessionState

3. 每轮对话:
   ├─ 生成 attribute_intro（介绍该属性）
   ├─ 孩子回应后 classify_intent()
   ├─ generate_attribute_activation_response_stream()
   │   使用 ATTRIBUTE_SOFT_GUIDE（三种技巧：
   │   Salience, Frame Weaving, Natural Bridge）
   └─ 检测 [ACTIVITY_READY] 标记
       ├─ 收集完整响应
       ├─ 检测标记
       ├─ 提取理由
       ├─ 验证引号是否出现在儿童历史消息中
       └─ 判定 activity_ready
```

### 10.2 Category Lane（category_activity.py）

**流程**：
```
1. build_category_profile(domain, object_name) → CategoryProfile

2. start_category_session(profile) → CategorySessionState

3. 每轮对话:
   ├─ classify_category_reply()
   │   ├─ uncertainty → scaffold_category
   │   ├─ constraint_avoidance → low_pressure_repair
   │   ├─ activity_command → acknowledge_keep_category
   │   ├─ curiosity → answer_and_reconnect
   │   ├─ category_drift → accept_comparison_keep_category
   │   └─ aligned → continue_category_lane
   │
   └─ evaluate_category_activity_readiness()
       ├─ 2 轮参与后 → activity_ready = True
       └─ 否则 → 继续
```

---

## 11. 知识库与数据加载

### 11.1 数据结构

**exploration_categories.yaml** 定义：
- 6 个物理维度：appearance, senses, structure, function, context, change
- 5 个参与维度：emotions, relationship, reasoning, imagination, narrative
- 14 个领域（domain）的特定子属性
- 3 个年龄层级：T0(3-4), T1(4-6), T2(6-8)

**对象 YAML**（如 food/apples.yaml）：
```
entity_id, entity_name, entity_name_cn
primary_theme, secondary_themes
primary_key_concepts
tier_guidance:
  T0: {appearance: [...], senses: [...], ...}
  T1: {...}
  T2: {...}
```

### 11.2 加载流程

```
load_dimension_data(object_name)
  │
  ▼
读取 mappings_dev20_0318/<domain>/<object>.yaml
  │
  ▼
根据年龄选择对应 tier
  │
  ▼
填充 physical_dimensions 和 engagement_dimensions
```

### 11.3 趣闻系统（stream/fun_fact.py）

两步流水线（当前未接入主工作流）：
1. **Grounding**：用 Google Search 获取事实
2. **Structuring**：将事实结构化为 JSON（hook, question, facts）

缓存 3-5 个趣闻每对象，每会话随机选一个。
4 层安全：Gemini 内置安全 → 严格安全设置 → is_safe_for_kids 检查 → 流式安全。

---

## 12. Prompt 模板库

### 12.1 核心 Prompt

| Prompt 键 | 用途 | 主要变量 |
|-----------|------|----------|
| `SYSTEM_PROMPT` | 系统角色定义 | 无 |
| `SENSORY_SAFETY_RULES` | 安全约束（注入到所有 prompt） | 无 |
| `CHARACTER_PROFILE` | AI 角色设定 | 无 |
| `introduction_prompt` | 开场问题生成 | object_name, age, age_prompt, hook_type_section, knowledge_context, sensory_safety_rules |
| `user_intent_prompt` | 意图分类 | object_name, last_model_response, child_answer |
| `{intent}_intent_prompt` | 各意图响应（13 个） | child_answer, object_name, age, age_prompt |
| `followup_question_prompt` | 跟进问题生成 | object_name, age, age_prompt, knowledge_context |
| `bridge_profile_prompt` | 桥接策略推断 | surface_object_name, anchor_object_name, relation |
| `BRIDGE_ACTIVATION_RESPONSE_PROMPT` | 桥接激活响应 | bridge_context, surface_object_name, anchor_object_name |
| `ATTRIBUTE_SOFT_GUIDE` | 属性引导技巧 | attribute_label, activity_target |
| `attribute_selection_prompt` | 属性选择 | object_name, age, domain, supported_attributes |
| `theme_classification_prompt` | IB PYP 主题分类 | object_name, age, correct_answer_count |

### 12.2 Prompt 加载方式

```python
prompts = paixueji_prompts.get_prompts()
# get_prompts() 从模块全局变量收集所有 _PROMPT 结尾的字符串
```

---

## 13. Trace 与自我进化系统

### 13.1 数据流

```
人工批评 (manual-critique API)
  │
  ▼
build_human_feedback_report() → 保存 markdown
  │
  ▼
assemble_trace_object() → TraceObject
  ├─ input_state: 输入状态快照
  ├─ execution_path: 节点执行路径
  ├─ culprits: LLM 归因（哪个组件负责）
  ├─ critique: 人类批评
  └─ exchange: 交换上下文
  │
  ▼
save_trace_object() → traces/*.json
  │
  ▼
run_optimization(culprit_name)
  ├─ load_traces_for_culprit() → 所有相关 trace
  ├─ optimize_prompt_llm() → 高推理模型生成优化建议
  ├─ generate_preview_response() → 用新 prompt 重跑失败输入
  └─ save_optimization() → optimizations/pending/*.json
```

### 13.2 Culprit 归因

`identify_culprit_llm()` 使用 gemini-2.5-pro 分析：
- 交换内容
- 执行路径
- 验证/导航结果
- 人类批评

输出：哪个节点/prompt 最可能为失败负责，置信度，推理。

### 13.3 优化原则

- **反硬编码**：必须提取一般性失败模式，不能禁止特定内容
- **保留占位符**：所有 `{{placeholder}}` 必须保留
- **添加指导而非禁止**：说"做什么"而不是"不做什么"
- **人工审核**：优化结果保存到 pending，不自动应用

---

## 14. Schema 与数据结构

### 14.1 StreamChunk（SSE 数据包）

60+ 字段，分为几类：
- **基础**：response, session_finished, duration, token_usage, finish, sequence_number
- **会话**：session_id, request_id
- **对象/桥接**：new_object_name, anchor_status, bridge_phase, bridge_attempt_count, ...
- **意图**：intent_type, classification_status
- **趣闻**：fun_fact, fun_fact_hook
- **主题**：ibpyp_theme, key_concept
- **管道**：attribute_lane_active, category_lane_active, activity_ready
- **调试**：nodes_executed, bridge_debug, resolution_debug, used_kb_item

### 14.2 BridgeDebugInfo

30+ 字段，覆盖桥接全生命周期：
- 解析状态：surface_object_name, anchor_object_name, anchor_status
- Profile 状态：bridge_profile, bridge_profile_status
- 尝试计数：bridge_attempt_count_before/after
- 决策：decision, decision_reason, response_type
- 可见性：bridge_visible_in_response, bridge_visibility_reason
- 激活：activation_turn_count, activation_handoff_ready, activation_last_question
- 过渡：activation_transition（嵌套 6 个子模型）

### 14.3 ActivationTransitionDebugInfo

嵌套 6 个子模型：
1. `before_state` —— 激活前状态（9 个字段）
2. `question_validation` —— 问题验证（9 个字段）
3. `answer_validation` —— 答案验证（6 个字段）
4. `outcome` —— 结果（4 个字段）
5. `turn_interpretation` —— 轮次解释（3 个字段）
6. `continuity` —— 连续性（4 个字段）

---

## 15. 配置与常量

### 15.1 config.json 结构

```json
{
  "model_name": "gemini-2.0-flash-lite",
  "high_reasoning_model": "gemini-2.5-pro",
  "temperature": 0.3,
  "max_tokens": 2000,
  "project": "...",
  "location": "...",
  "grounding_model": "..."
}
```

### 15.2 运行时模型覆盖白名单

只允许覆盖为：
- `gemini-3.1-flash-lite-preview`
- `gemini-2.0-flash-lite`

### 15.3 关键常量汇总

| 常量 | 值 | 文件 |
|------|-----|------|
| `GUIDE_MODE_THRESHOLD` | 2 | graph.py |
| `MAX_BRIDGE_ACTIVATION_TURNS` | 4 | paixueji_app.py |
| `MAX_BRIDGE_ATTEMPTS` | 2 | paixueji_app.py |
| `MAX_PRE_ANCHOR_SUPPORT_TURNS` | 2 | paixueji_app.py |
| `SLOW_LLM_CALL_THRESHOLD` | 5.0 | stream/utils.py |
| `CATEGORY_ACTIVITY_READY_TURN_THRESHOLD` | 2 | category_activity.py |
| `HIGH_IMAGINATION_HOOKS` | {"想象导向", "情绪投射", ...} | stream/utils.py |

---

## 16. 完整执行流程 Walkthrough

### 16.1 开场流程（/api/start）

```
POST /api/start
{session_id: "uuid", object_name: "kitty", age: 5}

1. 创建 PaixuejiAssistant(session_id, object_name, age)

2. 对象解析:
   resolve_object_input("kitty", 5, client, config)
   └─► 未精确匹配 → LLM 推断
       └─► anchor="cat", relation="related_to", confidence=0.9
   └─► status="anchored_high"

3. 应用解析:
   assistant.apply_resolution(result)
   surface_object_name="kitty"
   anchor_object_name="cat"
   anchor_status="anchored_high"
   bridge_profile=BridgeProfile(...)

4. 设置 intro_mode:
   anchor_status != "exact_supported" → "anchor_confirmation"

5. 加载维度数据:
   load_dimension_data("cat") → 从 YAML 加载

6. 选择 hook_type:
   select_hook_type(age=5, messages=[], hook_types)
   └─► 年龄加权随机采样
   └─► 例如选中 "细节发现"

7. 生成开场:
   ask_introduction_question_stream(
     intro_mode="anchor_confirmation",
     surface_object_name="kitty",
     anchor_object_name="cat",
     ...
   )
   └─► 使用 anchor_confirmation_intro_prompt
   └─► "你提到了 kitty！你知道吗，有时候人们也叫它 cat...
        你觉得 cat 喜欢做什么呢？"

8. SSE 流返回客户端
   StreamChunk(response_type="introduction", ...)

9. 更新对话历史
   assistant.conversation_history += [user_msg, assistant_msg]
```

### 16.2 普通聊天流程（/api/continue）

```
POST /api/continue
{session_id: "uuid", child_input: "它会抓老鼠！"}

1. 获取 assistant

2. 检查通道优先级（均不满足）→ 走普通图执行

3. 构建 initial_state:
   - messages = conversation_history + [当前输入]
   - 所有 assistant 字段复制到 state
   - correct_answer_count = 0
   - intro_mode = None

4. 图执行 stream_graph_execution(initial_state):

   a. router:route_from_start
      └─► response_type != "introduction" → analyze_input

   b. analyze_input:
      └─► classify_intent()
          LLM 输出: "INTENT: INFORMATIVE\nNEW_OBJECT: null\nREASONING: ..."
      └─► intent_type = "INFORMATIVE"
      └─► 更新 state.intent_type

   c. router:route_from_analyze_input:
      └─► consecutive_struggle_count < 2
      └─► intent_type == "INFORMATIVE"
      └─► 路由到 "informative" 节点

   d. informative 节点:
      └─► generate_intent_response_stream()
          使用 informative_intent_prompt
          "哇，你知道 cat 会抓老鼠呢！这真的很厉害..."
      └─► ask_followup_question_stream()
          "那你知道 cat 是怎么发现老鼠的吗？"
      └─► 合并: response = 回应 + 问题

   e. finalize:
      └─► 组装 StreamChunk
      └─► 设置 finish=True

5. SSE 流返回

6. 更新对话历史
   conversation_history += [user_msg, assistant_msg]
```

### 16.3 桥接激活完整流程

```
场景: 孩子说 "kitty"，系统锚定到 "cat"

--- 第 1 轮（开场）---
系统: "你提到了 kitty！有时候人们也叫它 cat...
      你觉得 cat 喜欢做什么呢？"

孩子: "它喜欢在沙发上睡觉。"

--- 预锚定判定 ---
classify_pre_anchor_reply("它喜欢在沙发上睡觉")
  └─► normalize → "it likes to sleep on the sofa"
  └─► 不匹配 _CLARIFICATION_PATTERNS
  └─► 不匹配 _IDK_PATTERNS
  └─► 不匹配 _NEGATIVE_OR_REFUSAL_PATTERNS
  └─► classify_pre_anchor_semantic_reply()
      LLM 分析: "孩子回答了关于 cat 的行为，
                  虽然用词是 'it' 但内容涉及 cat"
      └─► reply_type = "followed", bridge_followed = True

判定: in_lane_follow
  → bridge_phase = "activation"
  → 进入激活阶段

--- 激活阶段 第 1 轮 ---
生成桥接激活响应:
generate_bridge_activation_response_stream(
  bridge_context=...,
  activation_turn_count=1
)
系统: "对呀！cat 真的很喜欢舒服的地方。
      那你知道 cat 为什么喜欢抓老鼠吗？"

--- 激活验证（后台）---
match_activation_question_to_kb_deterministic(
  "那你知道 cat 为什么喜欢抓老鼠吗？"
)
  └─► tokenize question → {"cat", "why", "like", "catch", "mouse"}
  └─► 匹配 engagement_dimensions["reasoning"]["instincts"]
  └─► score >= 4 → matched=True, handoff_ready=True

--- 激活阶段 第 2 轮 ---
孩子: "因为老鼠会偷吃！"

detect_activation_answer_heuristic("因为老鼠会偷吃！", previous_question)
  └─► 非 yes/no/pivot
  └─► answered_previous_question = None (inconclusive)

handoff 判定:
  - handoff_ready = True (上一问匹配 KB)
  - 但 answered_previous_question 不明确
  - 连续性锚点: "cat" 仍被讨论
  - turn_count = 2 <= MAX_BRIDGE_ACTIVATION_TURNS (4)
  → 未 handoff，继续激活

系统生成下一问...

--- 激活阶段 第 3 轮 ---
孩子: "cat 好厉害！"

classify_activation_reopen_signal("cat 好厉害！", "cat", ...)
  └─► 孩子主动使用 "cat" 一词
  └─► 信号: True (孩子已接受 anchor)

detect_activation_answer_heuristic("cat 好厉害！", ...)
  └─► 实质性回应

handoff 判定:
  - 多条件满足
  → handoff_ready = True
  → bridge_phase = "anchor_general"
  → commit_bridge_activation()

系统: "对呀！cat 真的很厉害呢！
      那你还知道 cat 会做什么厉害的事情吗？"

--- 现在对象正式切换为 "cat" ---
后续所有对话以 "cat" 为对象
物理维度和参与维度已加载
```

### 16.4 正确回答阈值流程

```
孩子连续答对 2 次后:

--- 第 2 次正确回答 ---
correct_answer 节点:
  └─► correct_answer_count += 1 → 现在 = 2
  └─► correct_answer_count >= GUIDE_MODE_THRESHOLD (2)
  └─► router 路由到 classify_theme

classify_theme 节点:
  └─► theme_classification_prompt
      LLM 分类到 IB PYP 主题
      例如: "Who We Are" / "How the World Works"
  └─► 设置 ibpyp_theme_name, key_concept
  └─► 根据主题决定是否启用 attribute_lane 或 category_lane

--- 后续对话 ---
如果 attribute_lane_active = True:
  → 走属性探索通道
  → 聚焦单一维度（如 appearance/color）
  → 使用 [ACTIVITY_READY] 标记判定活动就绪

如果 category_lane_active = True:
  → 走类别探索通道
  → 更宽泛的领域讨论
  → 2 轮参与后 activity_ready
```

---

## 17. 边缘情况与回退矩阵

### 17.1 对象解析失败

| 场景 | 处理 |
|------|------|
| 完全匹配 | exact_supported，正常流程 |
| LLM 推断高置信度 | anchored_high，预锚定确认 |
| LLM 推断中置信度 | anchored_medium，预锚定确认 |
| LLM 推断失败 | unresolved，unknown_object 开场 |
| 锚定确认拒绝 | suppress_anchor，unresolved，surface_only 模式 |
| 桥接尝试耗尽 | unresolved，surface_only 模式 |

### 17.2 连续困惑处理

| consecutive_struggle_count | 行为 |
|---------------------------|------|
| 0-1 | 正常意图路由 |
| >= 2 | 强制路由到 give_answer_idk，直接给出完整答案 |

计数器规则：IDK 或 Wrong 意图 → +1；其他意图 → 清零。

### 17.3 意图分类失败

| 场景 | 处理 |
|------|------|
| LLM 返回无效意图名 | 回退到 "CLARIFYING" |
| LLM 输出格式异常 | 正则匹配失败，回退默认值 |
| 属性管道中的分类 | 结果转小写使用（与普通路径不一致） |

### 17.4 LLM 调用失败

| 场景 | 处理 |
|------|------|
| 速率限制 | raise_if_rate_limited() → 抛出异常 |
| 其他异常 | 记录日志，yield 已生成的部分内容 |
| 流清理 | finally 块中 del stream |

### 17.5 话题切换

| 场景 | 处理 |
|------|------|
| 孩子提到新对象（NEW_OBJECT） | ACTION/AVOIDANCE 意图中允许切换 |
| 强制切换（/api/force-switch） | 重新解析对象，重置维度数据 |
| 桥接过程中的切换 | 清理桥接状态，重置计数器 |

---

## 附录：模块文件索引

| 文件 | 核心职责 |
|------|----------|
| `paixueji_app.py` | Flask HTTP 层、SSE 流、会话管理、6 条通道的调度枢纽 |
| `graph.py` | LangGraph 工作流定义、节点实现、路由逻辑 |
| `paixueji_assistant.py` | 会话状态容器、状态管理方法 |
| `object_resolver.py` | 对象解析、LLM 回退、桥接 profile 推断 |
| `paixueji_prompts.py` | 所有 prompt 模板库 |
| `schema.py` | Pydantic 数据模型（StreamChunk、BridgeDebugInfo 等） |
| `stream/response_generators.py` | 所有意图的回应生成器 |
| `stream/question_generators.py` | 开场、跟进、属性/类别问题生成器 |
| `stream/validation.py` | 意图分类、预锚定分类、桥接验证 |
| `stream/utils.py` | 消息清理、格式转换、hook 类型选择 |
| `stream/fun_fact.py` | 趣闻两步流水线（ grounding + structuring） |
| `bridge_profile.py` | 桥接策略推断 |
| `bridge_context.py` | 桥接上下文构建 |
| `bridge_debug.py` | 桥接调试信息组装 |
| `bridge_activation_policy.py` | 激活阶段策略（问题匹配、答案检测、reopen 信号） |
| `pre_anchor_policy.py` | 预锚定回复分类（规则 + 语义） |
| `attribute_activity.py` | 属性探索管道（profile 选择、session 状态） |
| `category_activity.py` | 类别探索管道（回复分类、就绪判定） |
| `theme_classifier.py` | IB PYP 主题分类 |
| `trace_assembler.py` | TraceObject 组装、culprit 归因 |
| `trace_schema.py` | Trace/Optimization 数据模型 |
| `prompt_optimizer.py` | 自动 prompt 优化流水线 |
| `kb_context.py` | 知识库上下文构建 |
| `graph_lookup.py` | 图查询、概念查找 |
| `resolution_debug.py` | 解析过程调试 |
| `model_json.py` | JSON 提取与恢复 |

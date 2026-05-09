# Paixueji 代码库架构（基于代码阅读）

> 本文档基于对核心代码的直接阅读，非文档推导。所有结论标注 [CONFIRMED]（代码中有明确证据）或 [INFERRED]（合理推测）。

---

## 1. 系统核心行为

面向 3-8 岁儿童的**对象探索对话教育系统**。系统围绕一个"对象"（如苹果、恐龙）与儿童展开多轮问答式对话，通过教学支架（scaffolding）引导儿童观察、思考和表达。

### 1.1 意图驱动的响应路由 [CONFIRMED]

儿童的每句话被分类为 **13 种交际意图**，每种对应专门的响应策略和 prompt 模板：

- `CURIOSITY` — 好奇心（为什么/是什么/怎么样）
- `CLARIFYING_IDK` — 澄清-不知道
- `CLARIFYING_WRONG` — 澄清-错误
- `CLARIFYING_CONSTRAINT` — 澄清-约束
- `CORRECT_ANSWER` — 正确回答
- `INFORMATIVE` — 知识分享
- `PLAY` — 玩耍
- `EMOTIONAL` — 情绪表达
- `AVOIDANCE` — 回避
- `BOUNDARY` — 边界试探
- `ACTION` — 行动指令（含 A/B/C/D 子类型）
- `SOCIAL` — 社交询问
- `SOCIAL_ACKNOWLEDGMENT` — 社交回应
- `CONCEPT_CONFUSION` — 概念混淆

### 1.2 对象解析与锚定链 [CONFIRMED]

系统不是简单匹配儿童说的词，而是通过多层解析建立映射：

| 层级 | 含义 |
|------|------|
| `surface_object_name` | 儿童实际说的词 |
| `visible_object_name` | 对外展示用的词 |
| `anchor_object_name` | 内部知识库中的标准对象 |
| `anchor_status` | 完全匹配 / 高置信度锚定 / 中置信度锚定 / 未解析 |

### 1.3 语义桥接与激活机制 [CONFIRMED]

当表层对象与锚点对象不一致时（如儿童说 "kitty" 但知识库中是 "cat"），系统启动一个最多 **4 轮**的"激活对话"。系统用知识库支撑的问题引导儿童，目标是让儿童自然接受标准对象概念，然后"交接"（handoff）到普通对话模式。

桥接相位（bridge_phase）有 4 个状态：`none` → `pre_anchor` → `activation` → `anchor_general`。

### 1.4 双阶段对话流程 [CONFIRMED]

1. **开场阶段**：系统用趣味问题引入对象
2. **聊天阶段**：基于意图分类进行普通多轮对话
3. **引导模式切换**：当儿童累计答对 **2 次**（`GUIDE_MODE_THRESHOLD`）后，触发 IB PYP 主题分类，进入更高阶的引导模式

### 1.5 两步串行生成 [CONFIRMED]

多数意图响应采用"先回应、后提问"的串行生成：
1. 调用 `generate_intent_response_stream` 生成对儿童的回应文本（无问题）
2. 调用 `ask_followup_question_stream` 生成下一个跟进问题

这增加了 LLM 调用次数，但使输出结构更可控。

### 1.6 自我进化机制 [CONFIRMED]

系统收集失败对话的完整 trace（执行路径 + 人类评审意见），由 LLM 分析失败模式并生成 prompt 优化建议，保存到 `optimizations/pending/` 供人工确认后应用。

### 1.7 趣闻 grounding [INFERRED]

代码中存在基于 Google Search 的趣闻生成功能（`stream/fun_fact.py`，两步流水线：搜索 + JSON 结构化），但当前图工作流定义中未将其接入开场路径，处于"代码存在但未激活"状态。

---

## 2. 主要交互点

### 2.1 HTTP API + SSE 流式响应 [CONFIRMED]

所有交互通过 HTTP 端点进行，响应以 Server-Sent Events 格式流式返回。每个文本块都携带丰富的元数据（意图类型、桥接状态、调试信息等）。

| 端点 | 方法 | 作用 |
|------|------|------|
| `/` | GET | 静态前端页面 |
| `/api/health` | GET | 健康检查 |
| `/api/objects` | GET | 列出所有支持的对象（从 YAML 加载） |
| `/api/start` | POST | 开始新对话 |
| `/api/continue` | POST | 继续对话 |

### 2.2 会话式状态管理 [CONFIRMED]

会话状态保存在**内存字典**中（服务器重启即丢失）。每个会话持有一个完整的状态容器，包含：
- 对话历史（OpenAI 格式 message list）
- 对象解析结果
- 桥接相位与计数器
- 维度覆盖状态
- 答对计数、连续困惑计数
- 属性/类别管道状态
- IB PYP 主题分类结果

### 2.3 配置驱动的模型选择 [CONFIRMED]

- 通过 `config.json` 指定 Vertex AI 项目和位置
- 使用 Gemini 模型家族
- 支持运行时模型覆盖（白名单限制为 `gemini-3.1-flash-lite-preview` 和 `gemini-2.0-flash-lite`）

---

## 3. 状态/数据主要流转路径

### 3.1 开场路径 [CONFIRMED]

```
外部请求 → HTTP 入口层 → 状态容器初始化
  → 对象解析（表层→锚点）→ 知识库维度数据加载
  → 构建初始状态字典 → 图执行引擎
  → SSE 流返回客户端 → 更新对话历史
```

### 3.2 继续对话路径 [CONFIRMED]

```
外部请求 → HTTP 入口层 → 获取状态容器
  → 判断活跃通道（按优先级）:
      1. 类别管道 (category_lane_active)
      2. 属性管道 (attribute_lane_active)
      3. 桥接激活 reopen (bridge_phase == "none" + 有锚点 + reopen 信号)
      4. 桥接激活 continuation (bridge_phase == "activation")
      5. 普通图执行
  → 对应生成器执行 → SSE 流返回 → 更新对话历史
```

### 3.3 图内执行路径（普通对话）[CONFIRMED]

```
START → [路由: response_type == "introduction" ?]
  → generate_intro → finalize → END   (开场路径)
  → analyze_input → [路由: intent_type + 计数器状态]
      → 13 个意图节点之一
          → finalize → END
```

图编排层是**星型拓扑**：分析 → 路由 → 意图节点 → 收尾。无复杂循环或并行。

### 3.4 关键状态字段的跨层流转 [CONFIRMED]

| 字段 | 产生位置 | 消费位置 |
|------|----------|----------|
| `intent_type` | 分析输入节点（`classify_intent`） | 路由节点、响应节点选择 |
| `correct_answer_count` | 正确回答节点递增 | 路由节点判断阈值 |
| `consecutive_struggle_count` | 分析输入节点维护（IDK/Wrong 递增，其他清零） | 路由节点判断是否直接给答案 |
| `bridge_phase` | 对象解析、桥接激活 handoff | HTTP 层路径选择、图内 KB 上下文注入 |
| `action_subtype` | 分析输入节点（A/B/C/D） | ACTION 意图节点分支 |

### 3.5 调试信息并行流转 [CONFIRMED]

每个转折点都产生大量调试信息（桥接调试、解析调试、属性调试、类别调试、激活过渡调试），随每个 SSE chunk 流回客户端，同时写入结构化日志。

---

## 4. 模块边界与分层

### 4.1 五层架构 [CONFIRMED]

| 层级 | 职责 | 边界 |
|------|------|------|
| HTTP 传输层 | 请求/响应、SSE 封装、会话查找 | 不直接调用 LLM |
| 状态管理层 | 状态容器、配置加载、年龄 prompt | 无 LLM 调用逻辑 |
| 图编排层 | 工作流节点、条件路由、执行追踪 | 调用生成器但不持有状态 |
| 流式生成层 | 所有 LLM 流式生成器 | 纯生成逻辑，不持有会话状态 |
| 知识/策略层 | YAML 加载、桥接策略、主题分类 | 文件 I/O + 纯规则 + 部分 LLM |

### 4.2 跨层耦合点 [CONFIRMED]

- **状态容器 vs 图状态字典**：字段冗余（对象名、锚点状态等在两者中同时存在），同步是手动的
- **流式生成层 → 图状态**：通过注入的 `stream_callback` 回调函数反向写入 chunk

### 4.3 三条独立管道 [CONFIRMED]

与主图执行并列的三条独立路径：

1. **属性探索管道**（`attribute_activity.py`）：自洽状态机，有独立的意图分类、响应生成、`[ACTIVITY_READY]` 活动就绪判定
2. **类别探索管道**（`category_activity.py`）：基于领域推断构建，类似属性管道
3. **桥接激活管道**：虽在 HTTP 层内联实现，但逻辑上独立于普通图执行

---

## 5. 最脆弱/最难改动的部分

### 5.1 对话继续逻辑的庞大嵌套生成器 [CONFIRMED]

`continue_conversation` 超过 **1000 行**，内部包含 6 条互斥路径，每条都是一个内联 `async def` 生成器：

- 类别管道完整处理
- 属性管道完整处理（含 `[ACTIVITY_READY]` 标记验证：收集全文 → 检测标记 → 提取理由 → 验证引号是否出现在儿童历史消息中 → 判定活动就绪）
- 桥接激活 reopen 逻辑
- 桥接激活 continuation 逻辑（含 handoff 判定）
- 预锚定处理逻辑
- 普通图执行路径

**脆弱点**：
- 多层嵌套异步生成器 + `async_gen_to_sync` 转换器
- 大量重复代码：几乎每个分支都手工构建几乎相同的 `StreamChunk`
- 硬编码阈值（`MAX_BRIDGE_ACTIVATION_TURNS = 4`，`MAX_PRE_ANCHOR_SUPPORT_TURNS = 2`）分散在多处

### 5.2 桥接激活状态机 [CONFIRMED]

4 个相位（`none` / `pre_anchor` / `activation` / `anchor_general`）的状态转换逻辑**分散在三处**：
- HTTP 入口层（reopen 判断、continuation 执行、handoff 提交）
- 状态容器（`begin_bridge_activation`、`commit_bridge_activation`、`clear_bridge_activation`）
- 图编排层（开场节点的 `intro_mode` 判断）

`handoff_ready` 判定依赖 5 个以上条件的组合：上一问是否 KB 支撑、是否 handoff-ready、儿童是否回答了上一问、连续性锚点是否保持、是否超过最大轮数。

### 5.3 意图分类的重复与不一致 [CONFIRMED]

- 图分析节点做一次 `classify_intent`（返回 13 种**大写**意图）
- 属性管道在 HTTP 层又独立做一次 `classify_intent`（结果转**小写**使用）
- `action_subtype`（A/B/C/D）只在图分析节点中设置，属性管道中完全未使用
- 修改意图集合需要在至少两处同步

### 5.4 激活过渡调试信息的复杂构建 [CONFIRMED]

围绕桥接激活有一整套调试信息构建系统，使用 6 个辅助函数 + 1 个主构建函数，涉及 **30+ 个字段**：
- 激活前状态捕获（9 个字段）
- 问题验证状态（9 个字段）
- 答案验证状态（6 个字段）
- 结果状态（4 个字段）
- 轮次解释状态（3 个字段）
- 连续性状态（4 个字段）

任何新增字段或修改判定逻辑都需要同步修改整套构建代码。

### 5.5 全局事件循环的线程安全复杂性 [CONFIRMED]

HTTP 层创建守护线程运行全局事件循环 `_ASYNC_LOOP`，所有异步 LLM 调用通过 `asyncio.run_coroutine_threadsafe(..., _ASYNC_LOOP).result(timeout=10)` 执行。

**脆弱点**：
- "同步 Flask 路由中跑异步代码"的反模式
- 每个异步调用都需要线程安全提交
- 硬编码 10 秒超时
- 生成器消费需要 `async_gen_to_sync` 转换

### 5.6 Prompt 模板与代码的紧耦合 [CONFIRMED]

大量业务规则直接编码在 prompt 模板字符串中：
- 意图定义和分类规则
- 桥接策略和激活策略
- 安全约束（`SENSORY_SAFETY_RULES`）
- 年龄适配指南
- 问题风格示例

系统行为高度依赖 LLM 对 prompt 的理解。`prompt_optimizer` 虽然存在，但优化结果需要人工审核，自我进化流程尚未闭环。

### 5.7 趣闻功能的悬浮状态 [CONFIRMED]

`node_generate_fun_fact` 在图编排层中定义但**未被接入主工作流**（`build_paixueji_graph` 中未 `add_node`）。代码存在但当前未激活。

---

## 附录：关键设计决策

1. **Bridge 模式是核心创新**：不是简单映射同义词，而是设计了一套完整的"通过对话引导儿童接受标准概念"的状态机。

2. **LangGraph 使用相对浅层**：星型路由结构，未利用循环、并行或持久化。价值在于标准化节点执行和追踪框架。

3. **Prompt 驱动的业务逻辑**：大量规则直接编码在 prompt 中而非代码逻辑中，使得系统行为高度依赖 LLM 理解。

4. **过度工程化的调试信息**：每个转折点都生成大量调试字段，在 `StreamChunk` 中占据大量空间，主要供内部 trace 分析使用。

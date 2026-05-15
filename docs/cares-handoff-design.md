# CARES Handoff 算法设计方案 v2

> **版本**: 2.1  
> **日期**: 2026-05-15  
> **Phase 0 状态**: ✅ 已实现 (2026-05-14)  
> **Phase 1 状态**: ✅ 已实现 (2026-05-15)  
> **Phase 2 状态**: 🔄 待实现  
> **Phase 3 状态**: 🔄 待实现  
> **核心原则**: 聊天机器人是手段，挖掘兴趣、推出科教活动是目的。所有设计必须服务于"推什么活动、何时推、为什么推"这三个问题。

---

## 1. 我们要解决什么

### 1.1 当前系统的核心缺陷

现有属性管道的 handoff 逻辑：

```python
if turn_count >= 3 and quote_validation_passes:
    accept_activity_ready()
```

**问题**：
- `turn_count >= 3` 是代理指标，不衡量真实兴趣深度
- `quote_validation` 是形式检查，经常被格式问题误杀
- 模型对"聊够了"没有标准，过早或过晚输出 `[ACTIVITY_READY]`
- **最关键的是**：系统不记录"小孩对什么感兴趣"，只做轮数计数
- **attribute pipeline 没有结构化问题来源**：模型只有 `attribute_label`（如 "body color"）和 `activity_target` 两个字符串作为引导，没有任何探索角度或覆盖追踪。多轮后必然用换词方式重复同一问题，导致小孩感到被 quiz

### 1.2 根本原因

当前系统把 handoff 当成"聊天够久了就可以切"，而不是"聊出了足够深的兴趣信号，可以推荐一个匹配的活动了"。

更深层的根本问题：attribute pipeline 给模型的输入只有 `attribute_label` + `activity_target` + `ANTI-PATTERNS`。模型不知道这个属性有哪些可探索的方向、哪些已经问过、下一轮该用什么角度。多轮后模型的"创造力枯竭"被误当成"兴趣挖掘完成"，触发 `[ACTIVITY_READY]` 只是因为它没话说了。

因此我们需要两层基础设施：
1. **对话角度覆盖层**：确保每轮都有新鲜的问题角度，防止模型重复
2. **兴趣档案层**：跨轮次、跨属性地记录真实兴趣强度，做 handoff 决策

---

## 2. 核心架构：兴趣挖掘 → 活动匹配

```
                    ┌─────────────────┐
  每轮对话 ──────▶│  更新当前属性  │
                    │  兴趣档案       │
                    └──────┬────────────┘
                             │
              ┌─────────────────┬─────────────────┬─────────────────┐
              ▼              ▼              ▼
        ┌─────────┐   ┌─────────┐   ┌─────────┐
        │ 切换    │   │ 计算全局  │   │ 评估活动  │
        │ 检测    │   │ 兴趣排名  │   │ 可用性    │
        └────┬────┘   └────┬────┘   └────┬────┘
             │             │             │
             └─────────────────────────────┘
                           │
                           ▼
                    ┌─────────────────┐
                    │   决策引擎    │
                    │  (5种输出)   │
                    └──────┬────────┘
                           │
        ┌────────────────┬────────────────┬────────────────┬────────────────┬────────────────┐
        ▼              ▼              ▼              ▼              ▼
   ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐
   │ CONTINUE │    │CONTINUE│    │HANDOFF │    │REENGAGE│    │ EXIT   │
   │(继续聊) │    │_SWITCH │    │_NOW    │    │(换策略)│    │_LANE   │
   └─────────┘    │(切属性)│    │(推活动)│    └─────────┘    │(退出) │
                    └─────────┘    └─────────┘                └─────────┘
```

### 2.1 五种决策输出的 UX 含义

| 决策 | 触发条件 | 用户体验 |
|------|---------|---------|
| **CONTINUE** | 当前属性兴趣分 < 60，且无切换信号 | 系统继续探索当前属性，问更深入的问题 |
| **CONTINUE_SWITCH** | topic_switch_detector 确认切换，或 fallback 兴趣计数 >= 2 | 系统自然地转到新属性，"你刚才提到形状，那它是什么形状呢？" |
| **HANDOFF_NOW** | 有属性达到兴趣阈值 60，且有匹配活动 | 系统自然引入活动，并输出 `[ACTIVITY_READY]` |
| **REENGAGE** | 连续挣扎 >= 3 轮，或当前属性兴趣分 < 20 | 系统逐级降低难度：简化问题 → 换角度 → 换维度 → 换对象 |
| **EXIT_LANE** | 会话超过 8 轮，但无任何属性达到 40 分 | 系统不强行推活动，而是退回自由对话模式，"我们今天聊了很多有趣的东西，你还想聊什么？" |

---

## 2.2 对话角度覆盖系统

> **核心问题**：attribute pipeline 中，模型只有 `attribute_label`（如 "body color"）作为引导。多轮后必然换词重复同一问题——"它是什么颜色的？"→"你喜欢这个颜色吗？"→"它还像什么颜色？"→没话说了。模型的"创造力枯竭"被系统误当成"兴趣挖掘完成"。
>
> **解决原则**：不依赖模型的自由发挥来避免重复，而是给它一个明确的"角度菜单"和"已覆盖清单"。

### 2.2.1 为什么不用 KB YAML

attribute pipeline 当前**完全不使用**知识库 YAML 中的 `topics`、`value` 或任何结构化内容。`stream_attribute_activity` 调用 `generate_attribute_activation_response_stream` 时传入 `knowledge_context=""`（空字符串）。`AttributeProfile` 中只有 `attribute_id`、`label`、`activity_target`——没有任何问题模板或事实数据。

因此角度系统必须是**自包含的**：不新增外部依赖，不额外调用 LLM 生成角度，在 pipeline 内部解决。

### 2.2.2 维度级探索角度池

按 dimension 类型（`attribute_id.split(".")[0]`）预定义通用角度。角度是**认知/对话方向**，不是具体的问题模板。模型在方向内自由生成具体措辞。

```python
# stream/exploration_angles.py

EXPLORATION_ANGLES = {
    "physical": [
        {
            "angle_id": "observation",
            "description": "Ask the child to observe and describe the attribute with their own words",
            "response_hint": "Share one concrete sensory fact about the {attribute_label}",
            "question_hint": "Ask what the child notices or sees about the {attribute_label}",
            "example": "What color do you see on the {object_name}?",
        },
        {
            "angle_id": "comparison",
            "description": "Compare this attribute with something familiar to the child",
            "response_hint": "Share a surprising comparison or contrast about the {attribute_label}",
            "question_hint": "Ask the child to compare the {attribute_label} with something they know",
            "example": "Is it more like a banana or a grape in color?",
        },
        {
            "angle_id": "preference",
            "description": "Invite the child to express a personal preference or opinion",
            "response_hint": "Validate that there is no wrong answer",
            "question_hint": "Ask which version of the {attribute_label} they like better",
            "example": "Do you like red apples or green apples better?",
        },
        {
            "angle_id": "association",
            "description": "Connect the attribute to the child's everyday life or other objects",
            "response_hint": "Mention one everyday object that shares this attribute",
            "question_hint": "Ask where else the child has seen this {attribute_label}",
            "example": "What else around you has this same color?",
        },
        {
            "angle_id": "causal",
            "description": "Explore why or how the attribute came to be (age-appropriate)",
            "response_hint": "Give a simple, concrete explanation",
            "question_hint": "Ask why the {object_name} has this {attribute_label}",
            "example": "Why do you think apples turn red when they grow?",
        },
    ],
    "engagement": [
        {
            "angle_id": "emotional",
            "description": "Ask about feelings and emotional reactions",
            "response_hint": "Acknowledge the child's feeling as valid",
            "question_hint": "Ask how the {object_name} makes them feel",
            "example": "Does the red apple make you feel happy or excited?",
        },
        {
            "angle_id": "memory",
            "description": "Connect to personal memories and experiences",
            "response_hint": "Share a brief, relatable memory",
            "question_hint": "Ask if the {object_name} reminds them of something",
            "example": "Does this apple remind you of anything you've eaten before?",
        },
        {
            "angle_id": "imagination",
            "description": "Invite playful imagination and pretend",
            "response_hint": "Play along with the child's imagination",
            "question_hint": "Ask a playful 'what if' about the {attribute_label}",
            "example": "If this apple could change color, what color would you pick?",
        },
        {
            "angle_id": "social",
            "description": "Connect to relationships and social context",
            "response_hint": "Mention how people or animals relate to this",
            "question_hint": "Ask who else might like or use this {attribute_label}",
            "example": "Who do you know that likes red apples?",
        },
    ],
}
```

**关键设计**：`example` 中的 `{attribute_label}` 和 `{object_name}` 运行时会动态填充。同一个 `observation` 角度框架：
- color → "What color do you see on the apple?"
- taste → "What taste do you notice when you think about the apple?"
- texture → "How do you think the apple feels?"

### 2.2.3 运行时覆盖追踪

```python
@dataclass
class AngleCoverageRecord:
    angle_id: str
    turn_index: int
    question_text: str
    response_text: str

# 在 DiscoverySessionState 中新增
@dataclass
class DiscoverySessionState:
    # ... existing fields ...
    explored_angle_ids: list[str] = field(default_factory=list)
    angle_records: list[AngleCoverageRecord] = field(default_factory=list)

    def record_angle(self, turn_index: int, angle_id: str, 
                     question_text: str, response_text: str):
        self.explored_angle_ids.append(angle_id)
        self.angle_records.append(AngleCoverageRecord(
            angle_id=angle_id, turn_index=turn_index,
            question_text=question_text, response_text=response_text,
        ))

    def select_next_angle(self, dimension: str, intent_type: str, 
                          interest_score: float = 0) -> dict:
        pool = EXPLORATION_ANGLES.get(
            "physical" if dimension in PHYSICAL_DIMENSIONS else "engagement", 
            []
        )
        
        # 1. 优先未使用的角度
        unused = [a for a in pool if a["angle_id"] not in self.explored_angle_ids]
        if unused:
            # 根据 interest_score 解锁深度
            if interest_score < 30:
                simple = [a for a in unused if a["angle_id"] in ("observation", "comparison")]
                return simple[0] if simple else unused[0]
            elif interest_score < 55:
                medium = [a for a in unused if a["angle_id"] != "causal"]
                return medium[0] if medium else unused[0]
            return unused[0]
        
        # 2. 全部用过了：循环，跳过最近用过的
        for angle in pool:
            if angle["angle_id"] != self.explored_angle_ids[-1]:
                return angle
        return pool[0]
```

### 2.2.4 Prompt 注入

将角度覆盖信息注入 `ATTRIBUTE_RESPONSE_GUIDE`。措辞是 **"try using"** 而非强制——模型有自由度，但有了明确指引。

```jinja2
[CONVERSATION COVERAGE]
Attribute: {attribute_label}
Turns explored: {turn_count}
Angles already used: {used_angles}

[NEXT SUGGESTED ANGLE: {next_angle_id}]
{next_angle_description}

For this turn, try using the {next_angle_id} angle:
- Your RESPONSE should: {next_angle_response_hint}
- Your FOLLOW-UP QUESTION should: {next_angle_question_hint}
- Example of a good question: "{next_angle_example}"

Already-used angles (try something different if possible):
{used_angles_with_examples}

ANTI-PATTERNS — NEVER produce these:
- "What {attribute_label} is it?" — quiz
- Re-phrasing a question from an already-used angle
- "What else can you tell me about it?" — too vague
```

### 2.2.5 与 CARES 兴趣评分的整合

角度系统不是独立的，它是 CARES 的**执行层**：

| Interest Score | 解锁角度 | 含义 |
|----------------|---------|------|
| < 30 | observation, comparison | 小孩还在适应，只给低认知负荷的角度 |
| 30-55 | + preference, association | 有一定参与，可以问个人化的角度 |
| >= 55 | + causal (物理) / imagination (情感) | 深度参与，解锁需要思考的角度 |

这意味着：
- **低分不会导致重复**——即使只解锁2个角度，覆盖追踪确保这两个角度不会连续重复
- **高分自然推进深度**—— causal 角度只在小孩充分参与后才解锁，此时问题深度匹配认知投入
- **handoff 更可靠**——5个角度全部覆盖后，interest score 通常已超过 60

### 2.2.6 UX 走查：聊苹果的 appearance.color

假设生成了5个角度，interest score 逐步积累：

| Turn | 小孩输入 | Intent | Score | 选中角度 | 系统回应 + 问题 |
|------|---------|--------|-------|---------|----------------|
| 1 | "红色" | CORRECT_ANSWER | 35 | `observation` | "对！苹果有红红的皮。你看到的是亮红色还是暗红色？" |
| 2 | "亮红色" | CORRECT_ANSWER | 42 | `comparison` | "亮红色就像小灯笼一样！它和草莓的颜色一样吗？" |
| 3 | "一样" | CORRECT_ANSWER | 48 | `preference` | "那你更喜欢红红的苹果还是绿绿的苹果？" |
| 4 | "红色的" | CORRECT_ANSWER | 55 | `association` | "红色的苹果让我想到秋天的枫叶。你还在哪里见过红色？" |
| 5 | "我的书包" | INFORMATIVE | 68 | `causal` | "你的书包也是红色的！你知道苹果为什么是红色的吗？因为它里面有一种..." |

5 轮对话，5 个不同角度，没有一个重复问题。第 5 轮 interest score 达到 68，CARES 自然触发 HANDOFF_NOW。

---

## 3. 跨属性兴趣档案

### 3.1 数据结构

每个被探索过的属性都有一个持久档案，**切换属性时不重置，只标记为非当前**。

```python
@dataclass
class AttributeInterestRecord:
    attribute_id: str           # 例如 "appearance.color"
    
    # 基础探索数据
    turns_explored: int = 0
    first_turn_index: int = 0
    last_turn_index: int = 0
    is_current: bool = False
    
    # 主动性信号（最重要）
    child_initiated_count: int = 0   # 小孩主动提起/问起
    child_returned_count: int = 0    # 离开后主动回来
    
    # 参与质量
    intent_history: list[str] = field(default_factory=list)
    elaboration_turns: int = 0       # INFORMATIVE/CURIOSITY/EMOTIONAL 次数
    question_count: int = 0          # 小孩问了几个关于此属性的问题
    emotional_count: int = 0         # EMOTIONAL 次数
    
    # 负面信号
    struggle_count: int = 0          # 此属性上的 IDK/WRONG
    avoidance_count: int = 0         # AVOIDANCE/BOUNDARY/ACTION(B/C)
    
    # 角度覆盖（第2.2章）
    explored_angle_ids: list[str] = field(default_factory=list)
    angle_records: list[AngleCoverageRecord] = field(default_factory=list)
```

**Key insight**: `child_returned_count` 是最强的兴趣信号。一个小孩离开颜色去聊形状，然后又主动回到颜色 —— 这比任何算法都更明确地说明"颜色是他真正的兴趣"。

### 3.2 每轮更新逻辑

```python
def on_attribute_turn(
    assistant,
    child_input: str,
    intent_type: str,
    action_subtype: str | None,
    switch_result,
    turn_index: int,
) -> None:
    current_attr = assistant.attribute_state.profile.attribute_id
    records = assistant.attribute_interest_records

    # Get or create record
    if current_attr not in records:
        records[current_attr] = AttributeInterestRecord(attribute_id=current_attr)

    record = records[current_attr]

    # Initialize on first exploration
    if record.turns_explored == 0:
        record.first_turn_index = turn_index

    # Detect "return": previously explored and not currently active
    # (must check BEFORE incrementing turns_explored)
    if record.turns_explored > 0 and not record.is_current:
        record.child_returned_count += 1

    # Basic data
    record.turns_explored += 1
    record.last_turn_index = turn_index
    record.intent_history.append(intent_type)
    record.is_current = True

    # Proactive: topic switch detector says child initiated this attribute
    if (
        switch_result.should_switch
        and switch_result.target_attribute_id == current_attr
    ):
        record.child_initiated_count += 1

    # Engagement quality
    if intent_type in ("INFORMATIVE", "CURIOSITY", "EMOTIONAL"):
        record.elaboration_turns += 1
    if any(marker in child_input for marker in ("?", "吗", "什么", "呢")):
        record.question_count += 1
    if intent_type == "EMOTIONAL":
        record.emotional_count += 1

    # Negative signals
    if intent_type in ("CLARIFYING_IDK", "CLARIFYING_WRONG"):
        record.struggle_count += 1
    if intent_type in ("AVOIDANCE", "BOUNDARY"):
        record.avoidance_count += 1
    if intent_type == "ACTION" and action_subtype in ("B", "C"):
        record.avoidance_count += 1

    # Sync angle coverage from DiscoverySessionState
    record.explored_angle_ids = list(assistant.attribute_state.explored_angle_ids)
    record.angle_records = list(assistant.attribute_state.angle_records)

    # Mark all other attributes as not current
    for attr_id, other_record in records.items():
        if attr_id != current_attr:
            other_record.is_current = False
```

### 3.3 兴趣分计算公式

```python
def compute_attribute_interest_score(record: AttributeInterestRecord) -> float:
    if record.turns_explored == 0:
        return 0.0
    
    # 基础参与度 (0-50)
    positive = sum(1 for it in record.intent_history 
                   if it in ("CORRECT_ANSWER", "INFORMATIVE", "CURIOSITY", "PLAY", "EMOTIONAL"))
    base = (positive / record.turns_explored) * 50
    
    # 主动性 (0-30)
    initiation = min(record.child_initiated_count * 8 + record.child_returned_count * 15, 30)
    
    # 深度 (0-25)
    depth = min(
        record.elaboration_turns * 4 + record.question_count * 6 + record.emotional_count * 5,
        25
    )
    
    # 负面惩罚
    penalty = min(record.struggle_count * 8 + record.avoidance_count * 12, 35)
    
    return max(0.0, base + initiation + depth - penalty)
```

**关键性质**：这是唯一的 handoff 门槛。不设轮数硬性约束，因为高质量的单轮对话可以自然达标。

### 3.4 打分示例

| 场景 | turns | initiated | returned | elaboration | questions | emotional | score |
|------|-------|-----------|----------|-------------|-----------|-----------|-------|
| 聊颜色3轮，全 CORRECT_ANSWER | 3 | 0 | 0 | 0 | 0 | 0 | 50 |
| 同上 + 主动问了一个问题 | 3 | 0 | 0 | 0 | 1 | 0 | 56 |
| 颜色→形状→**主动回颜色** | 2 | 1 | 1 | 1 | 0 | 1 | **83** |
| 形状2轮，全挣扎 | 2 | 0 | 0 | 0 | 0 | 0 | 34 |
| 颜色2轮，深度探索 | 2 | 0 | 0 | 2 | 1 | 0 | 71 |

---

## 4. 决策引擎

### 4.1 常量

```python
MIN_INTEREST_FOR_HANDOFF = 60       # 属性兴趣分 ≥ 此值才可推送活动
MAX_SESSION_TURNS = 8               # 整个会话（跨所有属性）最多 8 轮
EXIT_LANE_INTEREST = 40             # 退出时，最佳属性至少要有这个分数才值得记忆，否则当没探索过
```

**注意**：没有 `MIN_TURNS_PER_ATTRIBUTE`。轮数不是门槛，兴趣分才是。但 `MIN_INTEREST_FOR_HANDOFF = 60` 让单轮很难达标（1 轮 EMOTIONAL = 55，不够 60）。

### 4.2 决策逻辑

```python
class HandoffDecision(Enum):
    CONTINUE = "continue"                    # 继续探索当前属性
    CONTINUE_SWITCH = "continue_switch"      # 切到另一个属性
    HANDOFF_NOW = "handoff_now"              # 立即推送活动
    REENGAGE = "reengage"                    # 挣扎恢复策略
    EXIT_LANE = "exit_lane"                  # 退出属性探索，回到自由对话

def evaluate_handoff(assistant, switch_result) -> tuple[HandoffDecision, str, dict]:
    records = assistant.attribute_interest_records
    total_turns = sum(r.turns_explored for r in records.values())

    # 计算所有属性兴趣分
    scored = [
        (aid, compute_attribute_interest_score(r))
        for aid, r in records.items()
    ]
    scored.sort(key=lambda x: x[1], reverse=True)

    best_attr, best_score = scored[0] if scored else (None, 0)
    current_attr = assistant.attribute_state.profile.attribute_id
    current_record = records.get(current_attr)
    current_score = compute_attribute_interest_score(current_record) if current_record else 0

    # ┌──────────────────────────────────────────────────────────────┐
    # │ 1. 严重 disengagement → REENGAGE                             │
    # └──────────────────────────────────────────────────────────────┘
    if assistant.consecutive_struggle_count >= 3:
        return HandoffDecision.REENGAGE, "struggle_streak_3", {}

    if total_turns >= 2 and current_score < 20:
        return HandoffDecision.REENGAGE, "critical_disengagement", {}

    # ┌──────────────────────────────────────────────────────────────┐
    # │ 2. 明确的切换信号 → CONTINUE_SWITCH                          │
    # └──────────────────────────────────────────────────────────────┘
    if switch_result.should_switch and switch_result.target_attribute_id:
        target = switch_result.target_attribute_id
        if any(aid == target for aid, _ in scored):
            return HandoffDecision.CONTINUE_SWITCH, f"detector:{target}", {
                "target_attribute": target,
                "reason": "child_showed_clear_interest",
            }

    # ┌──────────────────────────────────────────────────────────────┐
    # │ 3. 有属性达标 → HANDOFF_NOW                                  │
    # └──────────────────────────────────────────────────────────────┘
    # NOTE: Phase 1 使用现有的 get_activity_for_attribute 作为占位符。
    # Phase 2 将替换为 select_best_activity（Tag Block schema 对齐版）。
    if best_score >= MIN_INTEREST_FOR_HANDOFF:
        activity = get_activity_for_attribute(best_attr, assistant.age or 6)

        if activity:
            # 最佳属性就是当前属性：直接推
            if best_attr == current_attr:
                return HandoffDecision.HANDOFF_NOW, f"current_best:{best_score:.0f}", {
                    "target_attribute": best_attr,
                    "activity": activity,
                    "readiness_score": best_score,
                }

            # 最佳属性 ≠ 当前属性
            if current_score >= 50:
                # 当前属性也还行：推当前的（保持对话流畅）
                current_activity = get_activity_for_attribute(current_attr, assistant.age or 6)
                if current_activity:
                    return HandoffDecision.HANDOFF_NOW, f"current_good:{current_score:.0f}", {
                        "target_attribute": current_attr,
                        "activity": current_activity,
                        "readiness_score": current_score,
                        "note": f"global_best_is_{best_attr}_but_current_is_good_enough",
                    }

            # 当前不够好，推全局最佳
            return HandoffDecision.HANDOFF_NOW, f"global_best:{best_attr}:{best_score:.0f}", {
                "target_attribute": best_attr,
                "activity": activity,
                "readiness_score": best_score,
                "current_attribute": current_attr,
                "bridge_context": f"child_previously_explored_{best_attr}_with_score_{best_score:.0f}",
            }
    
    # ┌──────────────────────────────────────────────────────────────┐
    # │ 4. 会话超时但无属性达标 → EXIT_LANE          │
    # └──────────────────────────────────────────────────────────────┘
    if total_turns >= MAX_SESSION_TURNS:
        if best_score >= EXIT_LANE_INTEREST:
            # 至少还有个值得记忆的属性，会话结束时可以提供给下次
            return HandoffDecision.EXIT_LANE, f"timeout_with_memory:{best_attr}:{best_score:.0f}", {
                "best_attribute": best_attr,
                "best_score": best_score,
                "reason": "session_long_but_interest_detected"
            }
        else:
            return HandoffDecision.EXIT_LANE, "timeout_no_interest", {
                "reason": "session_long_no_meaningful_interest"
            }
    
    # ┌──────────────────────────────────────────────────────────────┐
    # │ 5. 正常继续                                    │
    # └──────────────────────────────────────────────────────────────┘
    return HandoffDecision.CONTINUE, f"building:{current_score:.0f}", {
        "current_attribute": current_attr,
        "current_score": current_score,
        "best_attribute": best_attr,
        "best_score": best_score,
    }
```

### 4.3 决策走查

| 场景 | 当前分 | 全局最佳 | 活动匹配 | 决策 | UX |
|------|---------|---------|----------|------|-----|
| 颜色83分，当前=颜色 | 83 | 83 | 有 | HANDOFF_NOW 推颜色活动 | 完美 |
| 颜色83分，当前=形状(45) | 45 | 83 | 有 | HANDOFF_NOW 推颜色活动 | 模型说"你好像很喜欢颜色，来做个颜色游戏吧" |
| 颜色65分，形状60分，当前=形状 | 60 | 65 | 有 | 形状≥50? Yes → 推形状活动 | 保持流畅 |
| 颜色48分，形状45分，总8轮 | 45 | 48 | — | EXIT_LANE | 系统说"我们今天聊了很多，你还想聊什么？" |
| 形状30分，挣扎3轮 | 30 | 0 | — | REENGAGE | 系统尝试更简单的问题 |

---

## 5. 活动选择策略

### 5.0 核心原则

1. **Catalog 驱动**：只探索 catalog 中有活动支撑的属性（observation_angle），保证每轮对话都在"可落地"轨道上。不聊 catalog 无法 handoff 的属性。
2. **Tag Block 原生标签**：用 `mechanic` + `game_style` 替代 CARES 的 `activity_type`，兴趣分映射到认知深度偏好，而非固定的类型枚举。
3. **三层架构**：Eligibility（硬过滤）→ Angle/Attribute 匹配 → Scoring & Ranking（兴趣 + 连贯性 + progression）。

### 5.1 Catalog 驱动的属性探索

**旧问题**：先探索属性再匹配活动 → 聊了半天"气味"发现 catalog 里根本没有 smell 的活动 → 只能 EXIT_LANE。

**新流程**：Photo → 提取属性 → **扫描 catalog** → 哪些 angles 有 eligible 活动？→ **只在这些 angles 里选择探索** → 保证能 handoff。

```python
def get_explorable_angles(entity_info, extracted_properties, child_tier) -> set[str]:
    """扫描 catalog，返回当前 photo + tier 下能支撑 handoff 的所有 observation_angle"""
    eligible = [a for a in ACTIVITY_CATALOG
                if _is_eligible(a, child_tier, entity_info, extracted_properties)]
    
    angles = set()
    for a in eligible:
        angles.add(a.observation_angle)
        angles.update(a.bridge_prerequisites_primary)
    return angles
```

**Topic Switch 过滤**：如果孩子提到一个不在 `available_angles` 中的属性，系统不跟随切换，而是 gentle pivot 回有活动支撑的属性。

### 5.2 数据模型对齐（CARES ↔ Tag Block）

**删除 `activity_type`**，改用 Tag Block 原生标签：

```python
@dataclass(frozen=True)
class ActivityDefinition:
    # === 保留字段 ===
    activity_id: str
    name: str
    launch_prompt: str
    description: str = ""
    estimated_duration_minutes: int = 5
    materials_needed: tuple[str, ...] = ()
    
    # === 新增：直接用 Tag Block 标签 ===
    observation_angle: str            # color, shape, pattern, behavior, emotion, state...
    mechanic: str                     # collect, compare, sort, observe, voice, narrate, build, care, test
    game_style: str                   # field_experiment, voice_stage, mystery_trail, creation
    
    # === 新增：Eligibility 硬门槛 ===
    entity_binding: str               # bound | parameterized | agnostic
    entity_class: tuple[str, ...] = ()
    entity_class_filter: tuple[str, ...] = ()
    tier_range_span: tuple[str, ...] = ()      # ["T0", "T1", "T2"]
    tier_support: dict[str, bool] = field(default_factory=dict)
    
    # === 新增：Coherence 信号 ===
    bridge_prerequisites_primary: tuple[str, ...] = ()
    bridge_prerequisites_secondary: tuple[str, ...] = ()
    entity_role: str = "subject"      # subject | exemplar | catalyst | reference
    
    # === 新增：Progression（为未来预留）===
    topic_axis: str = ""              # form | function | causation | change | connection | perspective | responsibility
    difficulty_level: int = 1         # 1 | 2 | 3
```

**`_ATTRIBUTE_TO_ANGLE` 映射表**：将 CARES 内部属性 ID 映射到 Tag Block 的 observation_angle vocabulary。

```python
_ATTRIBUTE_TO_ANGLE = {
    "appearance.color": "color",
    "appearance.shape": "shape",
    "appearance.pattern": "pattern",
    "appearance.size": "size",
    "function.behavior": "behavior",
    "function.use": "function",
    "emotion.state": "emotion",
    "quantity.count": "quantity",
    # ...
}
```

### 5.3 Interest Score → Activity Profile 映射

兴趣分映射的是**孩子能承受的认知深度**，直接映射到 `mechanic` 和 `game_style`：

```python
@dataclass
class ActivityProfile:
    preferred_mechanics: list[str]
    acceptable_mechanics: list[str]
    preferred_game_styles: list[str]
    acceptable_game_styles: list[str]
    preferred_difficulty_level: int

def _interest_to_profile(interest_score: float) -> ActivityProfile:
    if interest_score >= 80:
        # 深度探索：主动搜集、比较、测试、构建
        return ActivityProfile(
            preferred_mechanics=["collect", "compare", "test", "build"],
            acceptable_mechanics=["sort", "voice", "care"],
            preferred_game_styles=["field_experiment", "creation", "mystery_trail"],
            acceptable_game_styles=["voice_stage"],
            preferred_difficulty_level=3,
        )
    elif interest_score >= 60:
        # 中度探索：比较、分类、表达
        return ActivityProfile(
            preferred_mechanics=["compare", "collect", "sort", "voice"],
            acceptable_mechanics=["observe", "narrate"],
            preferred_game_styles=["field_experiment", "voice_stage"],
            acceptable_game_styles=["mystery_trail"],
            preferred_difficulty_level=2,
        )
    else:
        # 轻度：观察、简单表达（<60 实际上不会触发 handoff）
        return ActivityProfile(
            preferred_mechanics=["observe", "voice"],
            acceptable_mechanics=["narrate"],
            preferred_game_styles=["voice_stage", "field_experiment"],
            acceptable_game_styles=[],
            preferred_difficulty_level=1,
        )
```

### 5.4 三层选择流程

```python
def select_best_activity(
    attribute_id: str,           # 来自 CARES，如 "appearance.color"
    interest_score: float,       # 来自 CARES，0-100
    age: int,                    # 来自 CARES
    conversation_context: dict,  # dominant_angle, secondary_angles, entity, entity_class, extracted_properties
    progression_state: dict = None,
) -> ActivityDefinition | None:
    
    child_tier = _age_to_tier(age)  # <=4 -> T0, <=6 -> T1, else T2
    
    # === Layer 1: Eligibility（硬过滤）===
    eligible = [a for a in ACTIVITY_CATALOG
                if _is_eligible(a, child_tier, conversation_context)]
    if not eligible:
        return None
    
    # === Layer 2: Angle/Attribute 匹配 ===
    target_angles = _attribute_to_angles(attribute_id)
    matched = [a for a in eligible if a.observation_angle in target_angles]
    if not matched:
        # 尝试 bridge_prerequisites 重叠
        matched = [a for a in eligible
                   if set(a.bridge_prerequisites_primary) & set(target_angles)]
    candidates = matched if matched else eligible  # 如果都没有，回退到全部 eligible
    
    # === Layer 3: Scoring & Ranking ===
    def score(activity):
        s = 0
        profile = _interest_to_profile(interest_score)
        
        # A. Interest-Profile Match (0-40)
        if activity.mechanic in profile.preferred_mechanics:
            s += 25
        elif activity.mechanic in profile.acceptable_mechanics:
            s += 12
        else:
            s += 5
        
        if activity.game_style in profile.preferred_game_styles:
            s += 15
        elif activity.game_style in profile.acceptable_game_styles:
            s += 7
        
        # difficulty_level 匹配 (0-8)
        diff = abs(activity.difficulty_level - profile.preferred_difficulty_level)
        if diff == 0:
            s += 8
        elif diff == 1:
            s += 4
        
        # B. Conversation Coherence (0-30)
        if activity.observation_angle == conversation_context.dominant_angle:
            s += 15
        elif activity.observation_angle in conversation_context.secondary_angles:
            s += 7
        
        overlap = len(set(activity.bridge_prerequisites_primary) & set(conversation_context.angles))
        s += min(overlap * 5, 10)
        
        if (activity.entity_role == "subject" and conversation_context.entity_depth == "deep") or \
           (activity.entity_role == "exemplar" and conversation_context.entity_depth == "property_focused"):
            s += 5
        
        # C. Progression Fit (0-20)
        if progression_state:
            target_axis = progression_state.get("target_axis")
            target_rung = progression_state.get("target_rung")
            if (activity.topic_axis == target_axis and 
                activity.difficulty_level == target_rung):
                s += 20
            elif (activity.topic_axis == target_axis and
                  abs(activity.difficulty_level - target_rung) <= 1):
                s += 15
            elif _is_sibling_axis(activity.topic_axis, target_axis):
                s += 8
        
        # D. Practical Fit (0-10)
        max_duration = 5 if age <= 4 else 10 if age <= 6 else 15
        duration = getattr(activity, 'estimated_duration_minutes', 5)
        if duration <= max_duration:
            s += 4
        elif duration <= max_duration * 1.5:
            s += 2
        
        materials = getattr(activity, 'materials_needed', [])
        if not materials:
            s += 3
        elif len(materials) <= 2:
            s += 1
        
        if activity.activity_id not in conversation_context.recent_activities:
            s += 3
        
        return s
    
    best = max(candidates, key=score)
    if score(best) < MIN_SCORE_FOR_HANDOFF:
        return None
    return best
```

### 5.5 降级链（Fallback Chain）

```
1. 精确匹配: observation_angle == attribute_id, difficulty 匹配 interest_score
2. 同 dimension 泛化: observation_angle 属于 attribute_id 的 dimension
3. Bridge prerequisite 匹配: primary prerequisites 与 conversation angles 重叠
4. 完全 agnostic: 任何安全可观察的活动
5. None → CARES 回到 CONTINUE 或 REENGAGE（不强行 handoff）
```

### 5.6 与 Progression 的对接

**核心原则**：Progression 是"建议方向"，不是"强制命令"。

| 场景 | 处理方式 |
|------|---------|
| 兴趣方向和 progression target 一致 | 完美。选 matching axis + rung 的活动，给最高 progression bonus。 |
| 兴趣方向和 progression target 不同，但 interest_score ≥ 70 | 优先兴趣方向。尝试选 observation_angle=兴趣方向 AND topic_axis=progression_target.axis 的活动。如果没有，选兴趣方向的活动，progression bonus 降低。 |
| 兴趣方向和 progression target 不同，且 interest_score < 70 | 考虑 CONTINUE_SWITCH 到 progression target 对应的属性，或 sibling-jump。 |

**L3 Ceiling / L1 Overload**：如果 progression state 显示当前 axis 已达 L3 ceiling 或 L1 persistent overload，selector 优先考虑 sibling axis 的活动（见 Tag Block 的 sibling graph）。


---

## 6. REENGAGE 三级升级策略

```python
def reengage_strategy(assistant, attempt_number: int) -> tuple[str, str]:
    current_attr = assistant.current_attribute_id
    current_record = assistant.attribute_interest_records.get(current_attr)
    
    # Level 1: 当前属性只聊了1-2轮，可能是问题太难
    if attempt_number == 1 and current_record and current_record.turns_explored <= 2:
        return "simplify", (
            "[SYSTEM] The child is struggling. Ask a much simpler, more concrete question. "
            "Use sensory language (look, touch, point). Avoid abstract questions."
        )
    
    # Level 2: 尝试同 dimension 的另一个 sub-attribute
    if attempt_number == 2:
        other_attrs = _get_unexplored_subattributes(
            assistant.object_name, current_attr, assistant.age
        )
        if other_attrs:
            return "switch_subattribute", (
                f"[SYSTEM] The child is not engaging with {current_attr}. "
                f"Try exploring a different aspect: {other_attrs[0]}. "
                "Make it feel like a natural shift, not a correction."
            )
    
    # Level 3: 尝试另一个 dimension（如 appearance → emotions）
    if attempt_number == 3:
        other_dims = _get_unexplored_dimensions(
            assistant.object_name, assistant.attribute_interest_records
        )
        if other_dims:
            return "switch_dimension", (
                f"[SYSTEM] Switch to a completely different angle: {other_dims[0]}. "
                "Use a personal or emotional hook to re-engage."
            )
    
    # Level 4: 放弃当前对象
    return "change_object", (
        "[SYSTEM] The child is consistently disengaged with this object. "
        "Gently suggest exploring something else. Do NOT force the current topic."
    )
```

**用户体验**：
- 第1次挣扎："不知道" → 系统问"你能看到橙色吗？"（更简单）
- 第2次挣扎："嗯" → 系统问"它摸起来怎么样？"（换角度）
- 第3次挣扎："不想聊这个" → 系统问"你觉得它开心吗？"（换维度）
- 第4次挣扎："那我们来看看别的吧！"（换对象）

---

## 7. Prompt 注入改动

### 7.1 角度覆盖注入（第 2.2 章）

`ATTRIBUTE_RESPONSE_GUIDE` 基础结构改为角度感知版本，`_build_angle_aware_guide()` 运行时动态构建：

```python
def _build_angle_aware_guide(
    attribute_label: str,
    activity_target: str,
    sensory_safety_rules: str,
    selected_angle: dict,
    explored_angle_ids: list[str],
    turn_count: int,
    current_score: float = 0.0,
    total_turns: int = 0,
    explored_attributes: list[str] | None = None,
    decision: "HandoffDecision | None" = None,
    decision_meta: dict | None = None,
) -> str:
    # ... angle lookup and formatting ...

    explored_attrs_str = ", ".join(explored_attributes) if explored_attributes else "(none yet)"

    # Build decision-specific instructions
    if decision == HandoffDecision.HANDOFF_NOW:
        target_attr = (decision_meta or {}).get("target_attribute", attribute_label)
        activity = (decision_meta or {}).get("activity")
        activity_name = getattr(activity, "name", "an activity") if activity else "an activity"
        readiness = (decision_meta or {}).get("readiness_score", current_score)
        decision_block = f"""HANDOFF MODE: ACTIVE
Target attribute: {target_attr}
Activity: {activity_name}
Child interest score for this attribute: {readiness:.0f}/100

Your next message should:
1. Naturally bridge from the current conversation to the activity
2. Introduce the activity by name
3. End with [ACTIVITY_READY]"""
    elif decision == HandoffDecision.EXIT_LANE:
        decision_block = """EXIT MODE: ACTIVE
The session has been long. Wrap up naturally without pushing an activity.
Suggest free exploration or ask what the child wants to talk about next."""
    elif decision == HandoffDecision.REENGAGE:
        decision_block = """REENGAGE MODE: ACTIVE
The child is struggling. Ask a much simpler, more concrete question.
Use sensory language (look, touch, point). Avoid abstract questions."""
    else:
        decision_block = """HANDOFF MODE: INACTIVE
Continue exploring the current attribute. Do NOT output [ACTIVITY_READY]."""

    return f"""{sensory_safety_rules}

[CONVERSATION COVERAGE]
Attribute: {attribute_label}
Turns explored: {turn_count}
Angles already used: {used_angles}

---

[SYSTEM CONTEXT]
Current attribute: {attribute_label}
Current interest score: {current_score:.0f}/100
Session turns: {total_turns}
Explored attributes: {explored_attrs_str}

{decision_block}

---

[NEXT SUGGESTED ANGLE: {angle_id}]
{description}

For this turn, try using the {angle_id} angle:
- Your RESPONSE should: {response_hint}
- Your FOLLOW-UP QUESTION should: {question_hint}
- Example of a good question: "{example}"

Already-used angles (try something different if possible):
{used_angles_block}

ANTI-PATTERNS -- NEVER produce these:
- "What {attribute_label} is it?" -- quiz
- "Do you know what {attribute_label} it has?" -- quiz with wrapper
- "What else can you tell me about it?" -- too vague
- "Let us look at its {attribute_label}!" -- forced redirect
- "That is nice, but..." then question about {attribute_label} -- ignoring child
- "Great! Now we can start an activity!" -- mechanical announcement
- Adding [ACTIVITY_READY] after just one shallow exchange -- premature handoff
- Switching topics on a single casual mention -- too sensitive
- Re-phrasing a question from an already-used angle
"""
```

**关键设计**：`[CONVERSATION COVERAGE]` 放在 `[SYSTEM CONTEXT]` 之前，让模型**先看到角度约束**，再看到 handoff/exit/reengage 指令。角度措辞使用 "try using" 而非强制，模型有自由度，但有了明确的防重复指引。

---

## 8. 实施计划

### Phase 0: 对话角度覆盖系统 ✅ IMPLEMENTED (2026-05-14)

- [x] 实现 `stream/exploration_angles.py`（维度级角度池定义）
- [x] 在 `DiscoverySessionState` 中新增 `explored_angle_ids` 和 `angle_records`
- [x] 实现 `select_next_angle` 角度选择逻辑
- [x] 在 `stream_attribute_activity` 中接入角度选择 + 记录
- [x] 更新 `ATTRIBUTE_RESPONSE_GUIDE` 为角度感知版本
- [x] 单元测试：模拟 5 轮同属性对话，验证角度不重复

**Commit:** `12ebc15` on `main`

#### Phase 0 实现详情

**新增文件：**
- `stream/exploration_angles.py` — 角度池定义 + `select_next_angle()` 选择逻辑
- `tests/test_exploration_angles.py` — 9 个单元测试，覆盖角度选择、覆盖率追踪、兴趣分解锁

**修改文件：**
- `stream/__init__.py` — 导出 `EXPLORATION_ANGLES`、`AngleCoverageRecord`、`select_next_angle`
- `attribute_activity.py` — `DiscoverySessionState` 新增 `explored_angle_ids`、`angle_records`、`current_angle_id`；新增 `record_angle()` 方法
- `paixueji_app.py` — 新增 `_build_angle_aware_guide()` 辅助函数；每轮响应前调用角度选择；每轮结束后记录角度使用
- `tests/test_attribute_activity_pipeline.py` — 新增 4 个测试，验证角度字段初始化和 `record_angle()` 行为

**当前行为（Phase 0）：**

| 维度 | 行为 |
|------|------|
| 角度选择 | 每轮属性管道响应前，从 `profile.attribute_id.split(".")[0]` 提取 dimension，调用 `select_next_angle()` |
| 池映射 | `appearance/senses/structure/function/context/change` → physical 池（5 个角度）；其余 → engagement 池（4 个角度） |
| 兴趣分 | `paixueji_app.py` 中硬编码为 `0`（Phase 0）。Phase 1 接入真实评分 |
| `interest_score=0` 时 | 优先 `observation` → `comparison`，用完后再按池顺序使用 `preference` → `association` → `causal` |
| 循环 | 全部用完后循环，跳过最近用过的角度。保证不会连续重复 |
| Prompt 注入 | 每轮动态构建角度感知 prompt，替换静态 `ATTRIBUTE_RESPONSE_GUIDE`。包含：对话覆盖信息、下一个角度描述、response/question hint、示例问题、已用角度列表、反模式 |
| 角度记录 | `combined_response` 构建后，调用 `state.record_angle(turn_index, angle_id, question_text, response_text)`，追加到 `explored_angle_ids` 和 `angle_records` |
| 调试可见性 | `to_debug_dict()` 包含 `explored_angle_ids`、`angle_records`（dict 列表）、`current_angle_id` |

**预期儿童端体验：**
- 第 1 轮：观察角度（"你看到什么颜色？"）
- 第 2 轮：比较角度（"它更像香蕉还是葡萄的颜色？"）
- 第 3 轮：偏好角度（"你喜欢红苹果还是绿苹果？"）
- 第 4 轮：联想角度（"你身边还有什么东西是这种颜色？"）
- 第 5 轮：因果角度（"你知道苹果为什么是红色的吗？"）
- 情感维度序列：emotional → memory → imagination → social
- 同一角度不会连续使用，每轮都给模型新的认知方向

**已知限制 / 下一步：**
- `turn_count >= 3` 和 `quote_validation` 检查仍存在于 `paixueji_app.py` —— Phase 3 按设计文档第 9 节移除（保留为安全网，CARES 决策优先）
- `evaluate_handoff` 使用 `get_activity_for_attribute` 作为占位符 —— Phase 2 替换为 `select_best_activity`

### Phase 1: 核心评分系统 ✅ IMPLEMENTED (2026-05-15)

- [x] 实现 `AttributeInterestRecord` dataclass（`stream/cares_handoff.py`）
- [x] 实现 `compute_attribute_interest_score`（基础参与度 0-50 + 主动性 0-30 + 深度 0-25 - 负面惩罚 0-35）
- [x] 实现 `on_attribute_turn` 更新逻辑（创建/更新记录、检测返回、同步角度、标记当前）
- [x] 实现 `HandoffDecision` enum + `evaluate_handoff` 决策引擎（5 种输出）
- [x] 从 `stream/__init__.py` 导出所有 CARES 符号
- [x] `PaixuejiAssistant` 新增 `attribute_interest_records` 字段（跨属性持久化）
- [x] 在 `stream_attribute_activity` 中接入完整 CARES 评估（每轮更新 → 计算分数 → 评估决策 → 注入 prompt）
- [x] 更新 `_build_angle_aware_guide` 注入 `[SYSTEM CONTEXT]` 和决策块
- [x] 单元测试：`tests/test_cares_handoff.py` — 28 个测试覆盖评分公式、每轮更新、决策引擎全部分支
- [x] 验证：`tests/test_attribute_activity_pipeline.py` — 验证 assistant 初始化时兴趣记录为空

**Commit range:** `b8f8a9f..68056e8` on `main`

#### Phase 1 实现详情

**新增文件：**
- `stream/cares_handoff.py` — `AttributeInterestRecord` + `compute_attribute_interest_score()` + `on_attribute_turn()` + `HandoffDecision` + `evaluate_handoff()`
- `tests/test_cares_handoff.py` — 28 个单元测试（1 个 dataclass 默认测试 + 11 个评分测试 + 10 个更新逻辑测试 + 7 个决策引擎测试）

**修改文件：**
- `stream/__init__.py` — 导出 `AttributeInterestRecord`、`compute_attribute_interest_score`、`on_attribute_turn`、`HandoffDecision`、`evaluate_handoff`、常量
- `paixueji_assistant.py` — 新增 `attribute_interest_records: dict[str, AttributeInterestRecord]`（`clear_attribute_lane` 不重置）
- `paixueji_app.py` — 每轮调用 `on_attribute_turn` → `compute_attribute_interest_score` → `evaluate_handoff`；`_build_angle_aware_guide` 新增 `current_score`、`total_turns`、`explored_attributes`、`decision`、`decision_meta` 参数；跟随生成器用 `"---\\n\\n[SYSTEM CONTEXT]"` 分割剥离决策上下文

**当前行为（Phase 1）：**

| 维度 | 行为 |
|------|------|
| 兴趣评分 | 每轮结束后更新 `AttributeInterestRecord`，实时计算 `current_interest_score` |
| 角度解锁 | `select_next_angle` 接收真实 `interest_score`（替代硬编码 `0`），按分数解锁深度角度 |
| Handoff 决策 | `evaluate_handoff` 每轮评估 5 种决策，优先处理挣扎/临界 disengagement |
| Prompt 注入 | `[SYSTEM CONTEXT]` 显示当前分数、总轮数、已探索属性、决策模式 |
| 决策模式 | HANDOFF_NOW → 引导输出 `[ACTIVITY_READY]`；EXIT_LANE → 建议自由探索；REENGAGE → 简化问题；默认 → 继续探索 |
| 跨属性追踪 | `attribute_interest_records` 在属性切换时保留，支持返回检测和全局最佳排名 |
| 活动匹配 | 使用现有 `get_activity_for_attribute`（Phase 2 升级为 `select_best_activity`） |

### Phase 2: 活动选择（1-2 天）

- [ ] 实现 `select_best_activity`（Tag Block schema 对齐版，三层架构：Eligibility → Angle/Attribute 匹配 → Scoring & Ranking）
- [ ] 确认活动团队新增字段时间表（`mechanic`、`game_style`、`observation_angle` 等）
- [ ] 添加 dimension-level 泛化保底活动
- [ ] 单元测试：验证活动排序逻辑
- [ ] 将 `evaluate_handoff` 中的 `get_activity_for_attribute` 替换为 `select_best_activity`

### Phase 3: 清理遗留门槛（1 天）

- [ ] 移除 `turn_count >= 3` 硬性检查（保留为可选安全网，CARES 决策优先）
- [ ] 移除 `quote_validation` 硬性检查
- [ ] 端到端整合测试：多属性切换、兴趣累积、handoff 时机

---

## 9. 与现有系统的关键改动

| 组件 | 改动 | 说明 |
|------|------|------|
| `stream/exploration_angles.py` | **新增 (Phase 0)** | 维度级探索角度池（物理5个 + 情感4个） |
| `stream/cares_handoff.py` | **新增 (Phase 1)** | `AttributeInterestRecord` + `compute_attribute_interest_score` + `on_attribute_turn` + `HandoffDecision` + `evaluate_handoff` |
| `attribute_activity.py` | 新增 `explored_angle_ids`/`angle_records` (Phase 0) | 角度覆盖追踪 |
| `paixueji_assistant.py` | 新增 `attribute_interest_records` (Phase 1) | 存储所有被探索过的属性档案，`clear_attribute_lane` 不重置 |
| `paixueji_app.py` | 接入角度选择 (Phase 0) + CARES 评估 (Phase 1) | 每轮选择下一个角度、更新兴趣档案、评估 handoff、注入 prompt |
| `paixueji_app.py` | `_build_angle_aware_guide` 注入 `[SYSTEM CONTEXT]` (Phase 1) | 显示当前分数、决策模式、handoff/exit/reengage 指令 |
| `paixueji_app.py` | `turn_count >= 3` 和 quote 验证 (Phase 3 TODO) | 仍作为安全网存在，CARES 决策优先 |
| `activities/__init__.py` | 待 Phase 2 | 删除 `activity_type`，新增 Tag Block 字段（`mechanic`, `game_style`, `observation_angle` 等） |
| `switch_attribute_topic()` | 待 Phase 3 | 切换时将旧属性加入新属性 fallbacks，支持 drift 回来检测 |

---

## 10. 决策汇总

| 议题 | 决策 | 备注 |
|------|------|------|
| 对话角度覆盖系统 | ✅ 必须实现 | 防止多轮重复，保证 CARES 输入质量 |
| 是否新增检测器 | ❌ 不新增 | 全部使用现有信号（intent, topic_switch_detector） |
| 轮数是否作为硬性门槛 | ❌ 不作为硬性门槛 | 轮数不限制 handoff，只影响探索分 |
| 跨属性记忆 | ✅ 必须保留 | 切换时不重置档案，全局排名选最佳 |
| 活动选择策略 | ✅ 必须明确 | 兴趣分决定活动类型偏好 |
| 强制 handoff | ❌ 移除 | 超时后 EXIT_LANE，回到自由对话 |
| quote validation | ❌ 移除 | 改用兴趣分门槛 |
| 模型 `[ACTIVITY_READY]` 输出权 | ✅ 保留 | 算法决定"是否允许"，模型决定"如何过渡" |
| 活动库必需字段 | mechanic | 必须新增，用于兴趣-活动匹配 |
| 活动库必需字段 | game_style | 必须新增，用于兴趣-活动匹配 |
| 活动库必需字段 | observation_angle | 必须新增，用于属性匹配 |
| 活动库必需字段 | entity_binding | 必须新增，用于 eligibility |
| 活动库必需字段 | entity_class_filter | 必须新增，用于 eligibility |
| 活动库必需字段 | tier_support | 必须新增，用于 eligibility |
| 活动库必需字段 | bridge_prerequisites | 推荐新增，用于 coherence |
| 活动库必需字段 | prerequisite_concepts | 推荐新增，v2 暂不使用 |
| 每个 dimension 泛化活动 | ✅ 必须提供 | 避免具体属性无匹配时投降 |

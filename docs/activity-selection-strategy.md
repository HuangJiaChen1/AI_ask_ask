# Activity Selection Strategy

> **版本**: 1.0
> **日期**: 2026-05-14
> **状态**: 设计确定，待实现
> **定位**: 与 `cares-handoff-design.md`（兴趣档案 + 决策引擎）和 `activity-matching-design-report.md`（Pipeline + 动态切换）解耦，专注解决"给定一个兴趣方向和分数，如何选择最佳活动"。

---

## 1. 我们在解决什么问题

当 CARES 决策引擎输出 `HANDOFF_NOW` 时，系统需要从一个活动库（Activity Catalog）中选出**最匹配当前对话上下文和孩子兴趣**的活动。

### 1.1 旧方案的核心问题

| 问题 | 现象 | 后果 |
|------|------|------|
| **先聊再找** | 系统先选一个属性探索，聊完后才去看 catalog 里有没有对应活动 | 聊了半天没有匹配活动，只能 EXIT_LANE |
| **activity_type 是占位符** | CARES 定义的 `observe/compare/classify/create/experiment/story` 没有与活动团队的标签对齐 | 两套标签系统，无法对接 |
| **排序过于简单** | 仅按 `target_attribute` + `activity_type` + `age` 排序 | 忽略了对话连贯性、progression 目标、活动元数据 |

### 1.2 新方案的核心原则

1. **Catalog 驱动**：只探索 catalog 能支撑 handoff 的属性，不聊 dead end
2. **Tag Block 原生标签**：直接使用活动团队定义的 `mechanic` + `game_style` + `observation_angle`，不做二次抽象
3. **三层筛选**：Eligibility（硬过滤）→ Angle 匹配 → Scoring & Ranking（兴趣 + 连贯性 + progression）

---

## 2. 输入与输出

### 2.1 输入

| 字段 | 来源 | 说明 |
|------|------|------|
| `attribute_id` | CARES 兴趣档案 | 当前最佳属性，如 `"appearance.color"` |
| `interest_score` | CARES `compute_attribute_interest_score()` | 0-100 的兴趣分 |
| `age` | Session 状态 | 用于 tier 映射 |
| `conversation_context` | 对话历史 + Photo 理解层 | `dominant_angle`, `secondary_angles`, `entity`, `entity_class`, `extracted_properties`, `recent_activities` |
| `progression_state` | Progression Service（可选） | `target_axis`, `target_rung`，V2 接入 |

### 2.2 输出

```python
@dataclass
class SelectionResult:
    activity: ActivityDefinition | None   # 选中的活动；None 表示不 handoff
    selector_score: float                 # 最终得分，用于阈值判断
    decision: str                         # "matched" | "fallback" | "none"
    fallback_reason: str | None           # 降级原因，用于 observability
```

---

## 3. Catalog 驱动的属性探索

### 3.1 核心机制

**旧流程**：Photo → 提取属性 → 选属性探索 → 聊多轮 → 用属性找活动 → 可能没有！

**新流程**：Photo → 提取属性 → **扫描 catalog** → 得到 `available_angles` → **只在 available_angles 里选属性探索** → 保证能 handoff

```python
def get_explorable_angles(entity_info, extracted_properties, child_tier) -> set[str]:
    """扫描 catalog，返回当前 photo + tier 下能支撑 handoff 的所有 observation_angle"""
    eligible = [
        a for a in ACTIVITY_CATALOG
        if _is_eligible(a, child_tier, entity_info, extracted_properties)
    ]
    angles = set()
    for a in eligible:
        angles.add(a.observation_angle)
        angles.update(a.bridge_prerequisites_primary)
    return angles
```

### 3.2 对话题选择的影响

`select_attribute_profile()`（在 `attribute_activity.py` 中）需要修改为：

1. 调用 `get_explorable_angles()` 得到 catalog 支持的 angles
2. 从 Photo 提取的属性中，**过滤**掉不在 `available_angles` 中的属性
3. 在剩余属性中选择 primary + fallback

**边界情况**：
- `available_angles` 为空 → 不进入属性探索模式，直接自由对话或 agnostic 活动
- 孩子提到不在 `available_angles` 中的属性 → topic_switch_detector 拒绝切换，系统 gentle pivot 回 available angles

### 3.3 与现有系统的对接

| 现有模块 | 改动 | 说明 |
|---------|------|------|
| `attribute_activity.py:select_attribute_profile()` | 新增 catalog 预扫描 | 在选 primary/fallback 前过滤掉 catalog 不支持的属性 |
| `stream/topic_switch_detector.py` | 新增 angle 可用性验证 | `detect_topic_switch()` 验证 target_attribute_id 对应的 angle 是否在 `available_angles` 中 |
| `paixueji_app.py` | `/api/start` 时预计算 `available_angles` | 存入 session state，供后续 topic switch 使用 |

---

## 4. 数据模型

### 4.1 ActivityDefinition（与 Tag Block 对齐）

**删除 `activity_type`**，改用 Tag Block 原生标签：

```python
@dataclass(frozen=True)
class ActivityDefinition:
    # === 基础字段 ===
    activity_id: str
    name: str
    launch_prompt: str
    description: str = ""
    estimated_duration_minutes: int = 5
    materials_needed: tuple[str, ...] = ()

    # === Tag Block 核心标签 ===
    observation_angle: str            # color, shape, pattern, behavior, emotion, state, function, quantity...
    mechanic: str                     # collect, compare, sort, observe, voice, narrate, build, care, test
    game_style: str                   # field_experiment, voice_stage, mystery_trail, creation

    # === Eligibility 硬门槛 ===
    entity_binding: str               # bound | parameterized | agnostic
    entity_class: tuple[str, ...] = ()
    entity_class_filter: tuple[str, ...] = ()
    tier_range_span: tuple[str, ...] = ()      # ["T0", "T1", "T2"]
    tier_support: dict[str, bool] = field(default_factory=dict)

    # === Coherence 信号 ===
    bridge_prerequisites_primary: tuple[str, ...] = ()
    bridge_prerequisites_secondary: tuple[str, ...] = ()
    entity_role: str = "subject"      # subject | exemplar | catalyst | reference

    # === Progression（V2 预留）===
    topic_axis: str = ""              # form | function | causation | change | connection | perspective | responsibility
    difficulty_level: int = 1         # 1 | 2 | 3
```

### 4.2 `_ATTRIBUTE_TO_ANGLE` 映射表

将 CARES 内部属性 ID 映射到 Tag Block 的 observation_angle：

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
    # 未来扩展...
}
```

**注意**：这个映射是系统维护的，不是活动团队维护的。当 `exploration_categories.yaml` 新增属性时，需要同步更新此映射。

---

## 5. Interest Score → Activity Profile 映射

兴趣分映射的是**孩子能承受的认知深度**，直接映射到 `mechanic` 和 `game_style` 偏好：

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

**映射设计 rationale**：
- 高分孩子表现出主动性和深度 → 给 `collect`（主动搜集）、`compare`（比较）、`test`（测试）这类需要孩子主导的 mechanic
- 中分孩子能参与但还需要引导 → 给 `compare`、`sort`、`voice` 这类有结构但不过于开放的 mechanic
- 低分孩子需要低压力入口 → `observe`（被动观察）、`voice`（表达感受）是最自然的起点

---

## 6. 三层选择流程

```
输入: attribute_id, interest_score, age, conversation_context, progression_state
                              │
                              ▼
                    ┌─────────────────────┐
                    │  Layer 1: Eligibility │  ── 硬过滤，binary pass/fail
                    │  - catalog active     │
                    │  - tier in span + support │
                    │  - entity_binding 匹配    │
                    │  - property resolution    │
                    │  - safety check           │
                    └──────────┬──────────┘
                               │
                    ┌─────────────────────┐
                    │  eligible_candidates │
                    └──────────┬──────────┘
                               │
                    ┌─────────────────────┐
                    │  Layer 2: Angle Match │  ── 属性/角度匹配
                    │  - observation_angle  │
                    │  - bridge_prerequisites│
                    └──────────┬──────────┘
                               │
                    ┌─────────────────────┐
                    │  matched_candidates │  （若为空，回退到 eligible）
                    └──────────┬──────────┘
                               │
                    ┌─────────────────────┐
                    │ Layer 3: Scoring     │  ── 连续打分，选最高分
                    │  A. Interest-Profile │     (0-40)
                    │  B. Coherence        │     (0-30)
                    │  C. Progression Fit  │     (0-20)
                    │  D. Practical Fit    │     (0-10)
                    └──────────┬──────────┘
                               │
                    ┌─────────────────────┐
                    │  score >= threshold? │
                    └──────────┬──────────┘
                        Yes /   \ No
                            /     \
                    ┌──────┐   ┌──────────────┐
                    │ return │   │ return None  │
                    │ activity│   │ (不 handoff) │
                    └──────┘   └──────────────┘
```

### 6.1 Layer 1: Eligibility

```python
def _is_eligible(activity: ActivityDefinition, child_tier: str,
                 entity_info: dict, extracted_properties: dict) -> bool:
    # 1. Catalog active
    if not getattr(activity, 'catalog_active', True):
        return False

    # 2. Tier hard gate
    if child_tier not in activity.tier_range_span:
        return False
    if not activity.tier_support.get(child_tier, False):
        return False

    # 3. Entity binding
    if activity.entity_binding == "bound":
        if activity.entity_class_filter:
            if not _entity_matches_filter(entity_info, activity.entity_class_filter):
                return False
    elif activity.entity_binding == "parameterized":
        required = _extract_required_properties(activity)
        for prop in required:
            if prop not in extracted_properties:
                return False
    elif activity.entity_binding == "agnostic":
        pass  # always eligible

    # 4. Safety
    if not _safety_check(activity, entity_info):
        return False

    return True
```

### 6.2 Layer 2: Angle/Attribute 匹配

```python
def _attribute_to_angles(attribute_id: str) -> list[str]:
    """将 CARES 属性 ID 映射到 Tag Block observation_angle"""
    angle = _ATTRIBUTE_TO_ANGLE.get(attribute_id)
    if angle:
        return [angle]
    # dimension-level fallback
    dimension = attribute_id.split(".")[0] if "." in attribute_id else attribute_id
    return _DIMENSION_TO_ANGLES.get(dimension, [])

def get_angle_matched_candidates(eligible, attribute_id, conversation_angles):
    target_angles = _attribute_to_angles(attribute_id)

    # 精确 angle 匹配
    exact = [a for a in eligible if a.observation_angle in target_angles]
    if exact:
        return exact

    # Bridge prerequisites 重叠
    bridge_matched = []
    for a in eligible:
        overlap = set(a.bridge_prerequisites_primary) & set(target_angles)
        if overlap:
            bridge_matched.append(a)
    if bridge_matched:
        return bridge_matched

    # 回退到全部 eligible
    return eligible
```

### 6.3 Layer 3: Scoring

```python
def score_activity(activity, interest_score, age, conversation, progression=None):
    s = 0
    profile = _interest_to_profile(interest_score)

    # ── A. Interest-Profile Match (0-40) ──
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

    # ── B. Conversation Coherence (0-30) ──
    if activity.observation_angle == conversation.dominant_angle:
        s += 15
    elif activity.observation_angle in conversation.secondary_angles:
        s += 7

    overlap = len(set(activity.bridge_prerequisites_primary) & set(conversation.angles))
    s += min(overlap * 5, 10)

    if (activity.entity_role == "subject" and conversation.entity_depth == "deep") or \
       (activity.entity_role == "exemplar" and conversation.entity_depth == "property_focused"):
        s += 5

    # ── C. Progression Fit (0-20) ──
    if progression:
        target_axis = progression.get("target_axis")
        target_rung = progression.get("target_rung")
        if target_axis and target_rung:
            if activity.topic_axis == target_axis and activity.difficulty_level == target_rung:
                s += 20
            elif activity.topic_axis == target_axis and abs(activity.difficulty_level - target_rung) <= 1:
                s += 15
            elif _is_sibling_axis(activity.topic_axis, target_axis):
                s += 8

    # ── D. Practical Fit (0-10) ──
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

    if activity.activity_id not in conversation.recent_activities:
        s += 3

    return s
```

**总分 = 100**。`MIN_SCORE_FOR_HANDOFF = 60`，与 `MIN_INTEREST_FOR_HANDOFF` 一致。

---

## 7. 降级链（Fallback Chain）

```
1. 精确匹配
   observation_angle == attribute_id 映射的 angle
   AND difficulty_level 匹配 interest_score 推断的难度

2. 同 dimension 泛化
   observation_angle 属于 attribute_id 的 dimension
   （如 "appearance.color" → 所有 appearance 相关 angles）

3. Bridge prerequisite 匹配
   活动的 bridge_prerequisites.primary 与 conversation angles 有重叠

4. 完全 agnostic
   entity_binding="agnostic" 的活动，不依赖具体属性

5. 无匹配 → 不 handoff
   返回 None，CARES 回到 CONTINUE 或 REENGAGE
```

每层降级都应记录 `fallback_reason`，用于调试和后续优化。

---

## 8. 与 Progression 的对接

### 8.1 核心原则

**Progression 是"建议方向"，不是"强制命令"。** 当前兴趣永远优先于 progression target。

| 场景 | 处理方式 |
|------|---------|
| **兴趣和 progression 一致** | 完美。选 matching axis + rung 的活动，给最高 progression bonus (20)。 |
| **兴趣和 progression 不同，interest_score ≥ 70** | 优先兴趣方向。尝试选 `observation_angle=兴趣方向 AND topic_axis=progression_target.axis` 的活动。如果没有，选兴趣方向的活动，progression bonus 降低。 |
| **兴趣和 progression 不同，interest_score < 70** | 考虑 `CONTINUE_SWITCH` 到 progression target 对应的属性。或选择 sibling-axis 活动作为过渡。 |

### 8.2 L3 Ceiling / L1 Overload

如果 progression state 显示：
- **L3 ceiling**：当前 axis 已达稳定 L3 → selector 优先考虑 sibling axis 的活动（见 Tag Block sibling graph），conceptually adjacent + recently less explored
- **L1 persistent overload**：连续在 L1 挣扎 → 选择 predicted engagement 更高、support need 更低的 axis，恢复信心

### 8.3 无 Progression State 时的行为

V1 没有 progression service 时：
- `progression_state` 为 `None`
- Layer 3 的 C 项（Progression Fit）得 0 分
- 选择完全由兴趣分 + 连贯性 + 实用度驱动
- 这是预期行为，不降级体验

---

## 9. 完整 Trace：橘猫 → 橘色探索

### 9.1 初始状态

```
Photo: 橘猫躺在沙发上
Child age: 5岁 → child_tier = "T1"

Photo Detection:
  entity: "cat"
  entity_class: ["cat", "domestic_pet", "mammal", "animal"]
  extracted_properties:
    - color = "orange"
    - pattern = "striped"
```

**Catalog 预扫描**：
- `color` → `color_scout` (parameterized, wide) ✓
- `pattern` → `pattern_hunt` (parameterized, needs patterned_thing) ✓
- `shape` → 无活动 ✗
- `texture` → 无活动 ✗

`available_angles = {"color", "pattern"}`

**话题选择**：系统只从 `available_angles` 里选 primary/fallback，最终选 `color` 为主话题，`pattern` 为 fallback。

### 9.2 对话与兴趣分

| Turn | 孩子 | Intent | 档案更新 |
|------|------|--------|----------|
| 1 | "橘色的！像橘子一样！" | INFORMATIVE | color: turns=1, elaboration=1 |
| 2 | "橘色的皮球！还有橘色的花！" | INFORMATIVE | color: turns=2, elaboration=2 |
| 3 | "为什么橘猫是橘色的呀？" | CURIOSITY (主动!) | color: turns=3, elaboration=3, initiated=1, question=1 |
| 4 | "想！我想找橘色的玩具！" | EMOTIONAL + PLAY | color: turns=4, elaboration=4, emotional=1 |

**Interest score = 83**（计算过程见 `cares-handoff-design.md` Section 3.3），触发 `HANDOFF_NOW`。

### 9.3 活动选择

**输入**：
- `attribute_id` = "appearance.color"
- `interest_score` = 83
- `age` = 5 → "T1"
- `conversation_context`: entity="cat", dominant_angle="color", secondary_angles=["pattern"], recent_activities=[]

**Layer 1: Eligibility**

| 活动 | 检查 | 结果 |
|------|------|------|
| A `color_scout` | parameterized, needs `{matched_color}` → extracted `color=orange` ✓ | **ELIGIBLE** |
| B `lion_voice` | bound, filter=[big_cat], cat ∉ big_cat | ✗ |
| C `pattern_hunt` | parameterized, needs `{matched_pattern}` → extracted `pattern=striped` ✓ | **ELIGIBLE** |
| D `cat_story` | bound, entity="cat" ✓, 但假设 tier_support[T1]=false | ✗ |
| E `shape_sort` | parameterized, needs `{matched_shape}` → 无 shape | ✗ |
| F `appearance_detective` | agnostic, always ✓ | **ELIGIBLE** |

Eligible: A, C, F

**Layer 2: Angle Match**

`attribute_id = "appearance.color"` → `_attribute_to_angles` → `["color"]`

- A: observation_angle="color" → **EXACT MATCH**
- C: angle="pattern" → 不匹配；bridge_prerequisites=["pattern", "texture"] → 无 overlap with ["color"]
- F: angle="state" → 不匹配；bridge_prerequisites=[] → 无 overlap

Matched: A

**Layer 3: Scoring**（仅 A）

- `interest_score=83` → profile: preferred_mechanics=["collect","compare","test","build"], preferred_game_styles=["field_experiment","creation","mystery_trail"], preferred_difficulty_level=3
- A.mechanic="collect" → preferred → 25
- A.game_style="field_experiment" → preferred → 15
- A.difficulty_level=2, preferred=3 → diff=1 → 4
- coherence: angle="color"==dominant="color" → 15; bridge=["color"]∩["color"]=1 → 5; entity_role="exemplar", entity_depth="property_focused" → 5
- progression: None → 0
- practical: duration=8≤10 → 4; materials=[] → 3; not recent → 3

**Total = 79**，超过阈值 60。

**选中 `color_scout`**。

### 9.4 Runtime 渲染

```yaml
activity_signature:
  focal_attribute: "{matched_color}"
  preview_prompt: "You noticed the {color} of the {entity}. Let's go find more {color} things together."
  role_pivot_note: "The {entity} was our subject during the chat; now it becomes an example of {color}."
```

渲染后：
> "你注意到这只猫咪是橘色的。刚才我们在聊猫咪，现在它变成了'橘色'的一个例子。我们去找找看，还有哪些东西也是橘色的吧！"

`[ACTIVITY_READY]`

---

## 10. 决策汇总

| 议题 | 决策 | 备注 |
|------|------|------|
| Catalog 驱动属性选择 | ✅ 采用 | 先扫描 catalog 得到 `available_angles`，再选属性探索 |
| `activity_type` 保留 | ❌ 删除 | 用 `mechanic` + `game_style` 替代 |
| Eligibility 层 | ✅ 采用 Tag Block 规则 | entity_binding, tier_support, entity_class_filter, property resolution |
| Coherence 层 | ✅ 采用 | observation_angle + bridge_prerequisites + entity_role |
| Progression bonus | ✅ 预留（V2） | 0-20 分，optional，不强制 |
| 评分阈值 | MIN_SCORE_FOR_HANDOFF = 60 | 与 interest_score 门槛一致 |
| 降级链 | 5 层 fallback | 精确 → dimension → bridge → agnostic → None |
| 与现有代码冲突时 | 以本文档为准 | `cares-handoff-design.md` Section 5 和 `activity-matching-design-report.md` Section 2.2 需同步更新 |

---

## 11. 实施计划

### Phase 1: 核心重构（1-2 周）

- [ ] 更新 `ActivityDefinition` dataclass（删除 `activity_type`，新增 Tag Block 字段）
- [ ] 实现 `_interest_to_profile()` 和评分公式
- [ ] 实现三层 selector：`filter_eligible()` → `match_angles()` → `score_and_rank()`
- [ ] 实现 `_ATTRIBUTE_TO_ANGLE` 映射表
- [ ] 更新 mock 活动 YAML，使用新字段
- [ ] 单元测试：10 种场景的 eligibility + scoring

### Phase 2: Catalog 驱动集成（1 周）

- [ ] 在 `select_attribute_profile()` 中接入 `get_explorable_angles()`
- [ ] 在 `detect_topic_switch()` 中接入 angle 可用性验证
- [ ] 在 `/api/start` 中预计算 `available_angles` 并存入 session state
- [ ] 橘猫 trace 端到端验证

### Phase 3: Progression 对接（V2）

- [ ] 接入 `progression_state` 作为 Layer 3 bonus
- [ ] 实现 sibling-axis routing
- [ ] 根据运行数据调整各 score 权重

---

## 12. 与现有文档的冲突处理

| 现有文档 | 冲突内容 | 处理方式 |
|---------|---------|----------|
| `cares-handoff-design.md` Section 5 | 使用 `activity_type` 和简单排序 | **已更新**为本文档方案 |
| `cares-handoff-design.md` Section 9 | `activity_type` 字段声明 | **已更新**为 `mechanic` + `game_style` |
| `activity-matching-design-report.md` Section 2.2 | 三层筛选（Entity → Tier → 避免重复） | **已更新**为四层筛选（+ Catalog 可用性） |
| `activity-matching-design-report.md` Section 8 | 橘猫案例中列出所有属性 | **已更新**为仅列出 catalog 支持的属性 |

# 活动筛选及匹配算法 + CARES 评分与 Handoff 逻辑

---

## 一、活动筛选及匹配算法设计

### 1.1 整体架构：双层筛选

活动匹配采用「代码硬门槛 + AI 语义判断」双层架构：

- **Layer 1（`_is_eligible`）**：代码层硬门槛过滤，挡掉明显不合适的活动
- **Layer 2（`discover_talkable_activities`）**：AI 语义匹配，从候选中选出最佳活动并打标签

---

### 1.2 Layer 1：硬门槛过滤

从活动目录 `_load_catalog()` 加载全部活动后，依次检查以下门槛：

| 门槛 | 说明 |
|------|------|
| `catalog_active` | 活动是否已上架 |
| `tier_range_span` + `tier_support` | 孩子年龄段（T0≤4岁 / T1≤6岁 / T2>6岁）是否在支持范围内且标记可用 |
| `entity_binding` | 活动与对象的绑定类型：
| &nbsp;&nbsp;· `bound` | 绑定特定实体，对象名必须完全匹配（如「企鹅观察」只能用于企鹅） |
| &nbsp;&nbsp;· `parameterized` | 需要特定类型实体但具体不限；Layer 1 放行，由 Layer 2 AI 判断 |
| &nbsp;&nbsp;· `agnostic` | 不绑定任何实体，通用活动 |
| `entity_class_filter` | 当活动有 `entity_class_filter` 时，检查对象的 `entity_class` 是否有交集 |

经过 Layer 1 后得到 `eligible_activities`，进入 Layer 2。

---

### 1.3 Layer 2：AI 语义匹配

AI 看到的每个活动被精简为三个字段：

- `activity_id`
- `observation_angle`（观察角度，如 color / pattern / texture）
- `focal_attribute`（核心属性，如 body_color / polka_dots）

AI 的任务：判断「该对象在此观察角度下，是否明显具备该核心属性」。

---

### 1.4 三类标签的判定逻辑与后续行为

| 标签 | AI 判定标准 | 代码示例 |
|------|-----------|---------|
| **ready** | 对象明显具备该属性 | `orange cat` + `(angle=color, focal=body_color)` → 猫显然有颜色 |
| **verifiable** | 对象可能具备，但需孩子先确认 | `cat` + `(angle=pattern, focal=polka_dots)` → 可能有斑点，先问 |
| **weak** | 对象明显不具备 | `apple` + `(angle=origin, focal=time_period)` → 苹果没有时间段 |

#### ready 的后续逻辑

- `primary_category = "ready"`
- `verification_queue = []`（无需验证）
- 系统直接将该活动设为主活动，进入正常属性探索流程

#### verifiable 的后续逻辑

- `primary_category = "verifiable"`
- AI 在返回中生成 `verification_queue`，每项包含：
  - `property`：待验证的属性名（如 `has_polka_dots`）
  - `question`：验证问题（如 "Does it have polka dots?"）
  - `for_activity`：该验证服务于哪个活动

验证队列进入 `DiscoverySessionState.verification_queue`，由 `VerificationItem` 表示，初始状态为 `pending`。

每轮孩子回答后，系统调用 `classify_verification()` 分析孩子输入，更新验证项状态。

#### `classify_verification` 的双路径实现

**路径 A：Keyword Fast Path（针对简单明确回答）**

- 检测到否认关键词（no / not / never / doesn't 等）且无确认词 → 直接判 `deny`
- 检测到确认关键词（yes / yeah / sure / has / does 等）且输入 ≤6 个词、无否认词 → 直接判 `confirm`
- 优势：无需调用 LLM，延迟低

**路径 B：LLM Fallback（针对复杂或模糊回答）**

- 关键词路径无法判断时，调用 LLM 做三分类（confirm / deny / unclear）
- temperature=0，max_output_tokens=128，成本可控

#### 验证项状态流转

```
pending ──→ confirmed  → 该属性解锁，对应活动可用
      ├──→ rejected   → 该属性不成立，对应活动作废（handoff 时被拦截）
      └──→ unclear    →  pending_turns += 1，继续 pending
```

当 `pending_turns >= 2`（`check_probe_needed` 触发），系统进入 **PROBE 模式**，不再旁敲侧击，而是温和但直接地问验证问题。

#### weak 的后续逻辑

- 直接排除，不会进入 `primary` 或 `secondary`
- 但会记录在 `all_activity_categories` 中，供调试和人工评审参考

---

### 1.5 匹配结果的数据结构

`ActivityDiscoveryResult` 包含：

| 字段 | 说明 |
|------|------|
| `primary_activity_id` + `primary_category` | 最佳匹配及其标签（ready / verifiable / weak） |
| `secondary_activity_ids` | 备选活动（同样通过 ready / verifiable 筛选） |
| `verification_queue` | 待验证属性列表（verifiable 时非空） |
| `all_activity_categories` | 所有 eligible 活动的分类映射，供调试和人工选择 |
| `proceed` | 是否可继续（primary 为 ready 或 verifiable 时 true） |

---

## 二、CARES 评分系统与 Handoff 判断逻辑

### 2.1 兴趣记录的数据结构

每轮对话后，系统更新当前属性的 `AttributeInterestRecord`：

| 字段 | 含义 |
|------|------|
| `turns_explored` | 该属性已探索的轮数 |
| `first_turn_index` / `last_turn_index` | 首次 / 末次探索的位置 |
| `child_initiated_count` | 孩子主动发起该话题的次数 |
| `child_returned_count` | 孩子离开后又回到该话题的次数 |
| `intent_history` | 每轮孩子的意图类型列表 |
| `elaboration_turns` | 孩子展开回答的轮数（INFORMATIVE / CURIOSITY / EMOTIONAL） |
| `question_count` | 孩子主动提问的次数（通过 `?` / `吗` / `什么` / `呢` 检测） |
| `emotional_count` | 孩子表达情绪的轮数 |
| `struggle_count` | 孩子表现困难的轮数（CLARIFYING_IDK / CLARIFYING_WRONG） |
| `avoidance_count` | 孩子回避或越界的轮数（AVOIDANCE / BOUNDARY / ACTION subtype B/C） |
| `explored_angle_ids` / `angle_records` | 已覆盖的观察角度 |

---

### 2.2 兴趣评分公式

`compute_attribute_interest_score_breakdown`：

**总分 = base + initiation + depth + streak - penalty**，范围 0-100。

#### base（基础分，最高 60）

```
积极意图数 / 总轮数 × 60
```

积极意图：CORRECT_ANSWER, INFORMATIVE, CURIOSITY, PLAY, EMOTIONAL

#### initiation（主动性分，最高 30）

```
min(child_initiated_count × 8 + child_returned_count × 15, 30)
```

主动发起得 8 分/次，离开后回归得 15 分/次。

#### depth（深度分，最高 25）

```
min(elaboration_turns × 4 + question_count × 6 + emotional_count × 5, 25)
```

展开回答 4 分/轮，主动提问 6 分/次，情绪表达 5 分/次。

#### streak（连续奖励，最高 20）

```
min(turns_explored × 5, 20)
```

每多探索一轮加 5 分，封顶 20。让连续积极参与的孩子更快获得正向反馈。

#### penalty（惩罚，最高 35）

```
min(struggle_count × 4 + avoidance_count × 12, 35)
```

表现困难扣 4 分/次，回避 / 越界 / 不合理要求扣 12 分/次。

---

### 2.3 Handoff 判断的六道关卡

`evaluate_handoff` 按严格优先级顺序执行，一旦命中某条立即返回。

#### Gate 1：严重脱节 → REENGAGE

- **条件 A**：`consecutive_struggle_count >= 3`（连续 3 轮表现困难）
- **条件 B**：`total_turns >= 2` 且当前属性兴趣分 `< 20`

两者满足其一即触发。系统判断孩子已明显跟不上或没兴趣，需要换种方式重新吸引。

#### Gate 2：明确切换信号 → CONTINUE_SWITCH

- **条件**：`switch_result.should_switch = true` 且 `target_attribute_id` 在已探索属性中有记录

孩子明确表达了对另一个属性的兴趣（由话题切换检测器触发）。系统顺着孩子的兴趣切换。

#### Gate 3：兴趣达标且主活动就绪 → HANDOFF_NOW / PROBE / CONTINUE

- **前提**：`best_score >= MIN_INTEREST_FOR_HANDOFF`（50 分）且 `primary_activity` 不为空

进入 Gate 3 后，还要过 **Gate 3b：验证队列检查**：

```
if primary_activity 相关验证项有 rejected:
    → 退回 CONTINUE（"primary_property_rejected"）
    原因：孩子已否认该活动需要的属性，不能强行推进

elif 验证队列中有 pending:
    → PROBE（"properties_pending_verification"）
    原因：兴趣够了但还有属性没确认，先探测

else:
    → HANDOFF_NOW（"primary_activity:<分数>"）
    正式进入新活动
```

#### Gate 4：会话超时 → EXIT_LANE

- **前提**：`total_turns >= MAX_SESSION_TURNS`（8 轮）

分支：
- 若 `best_score >= EXIT_LANE_INTEREST`（40 分）：`timeout_with_memory` — 友好收尾，记住孩子感兴趣的方向
- 若 `best_score < 40`：`timeout_no_interest` — 直接结束，不再强行推进

#### Gate 5：默认 → CONTINUE

以上条件均不满足，继续当前话题积累兴趣分。

---

### 2.4 六种 HandoffDecision 的后续行为

| 决策 | 触发条件 | 后续行为 |
|------|---------|---------|
| `CONTINUE` | 默认 / 验证被拒退回 | `_build_continue_guide` 生成引导，选下一个观察角度继续探索 |
| `CONTINUE_SWITCH` | 孩子明确想换话题 | 切换到 `target_attribute`，继承已有兴趣记录 |
| `HANDOFF_NOW` | 兴趣≥50 + 主活动就绪 + 验证通过 | `_build_handoff_guide` 生成交接引导，正式进入新活动 |
| `REENGAGE` | 连续困难 / 严重低分 | `_build_reengage_guide` 生成重新吸引引导，选简单角度 |
| `EXIT_LANE` | 超过 8 轮仍未达标 | `_build_exit_guide` 生成收尾引导，结束或记住兴趣方向 |
| `PROBE` | 兴趣够但有 pending 验证 | `_build_probe_verification_context` 生成直接但温和的验证问题 |

---

### 2.5 关键阈值汇总

| 阈值 | 值 | 含义 |
|------|-----|------|
| `MIN_INTEREST_FOR_HANDOFF` | 50 | 进入交接的最低兴趣分 |
| `EXIT_LANE_INTEREST` | 40 | 超时退出时，友好收尾的最低分 |
| `MAX_SESSION_TURNS` | 8 | 单属性探索的最大轮数 |
| `max_pending_turns`（PROBE） | 2 | 验证项 pending 超过 2 轮触发 PROBE |

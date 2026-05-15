# Activity Matching 设计方案报告

> **版本**: 1.0  
> **日期**: 2026-05-11  
> **状态**: 产品方向已确定，技术方案已确认  
> **背景**: 本报告汇总了产品经理（PM）与开发团队关于"如何在对话中推出活动"的多轮讨论结论。阅读本报告即等同于参与了全部讨论。

---

## 1. 我们在解决什么问题

Paixueji 是一个面向 3-8 岁儿童的对话式教育产品。孩子发送一张照片（如一只橘猫），系统与孩子进行多轮对话，最终"推出一个活动"（Activity）——例如"我们来玩颜色探索吧"。

### 1.1 核心矛盾

**矛盾**: "先定方向" vs "自由聊天"

| 模式 | 描述 | 优点 | 缺点 |
|------|------|------|------|
| **Pipeline 先行**（原有模式） | 系统先决定"聊颜色"，然后一直引导孩子聊颜色，最后推出颜色活动 | 对话有方向感，模型知道该问什么 | 一旦锁定方向，可能错过孩子真正的兴趣 |
| **自由聊天** | 不预设方向，让孩子自由发挥，事后根据对话历史选活动 | 更自然，跟着孩子兴趣走 | 模型可能变成"哦真的吗"式闲聊，没有引导性 |

**决策结论**: 不选自由聊天（太发散），保留 Pipeline 框架，但在 Pipeline 内部增加"中途切换话题"的弹性。

---

## 2. 已确定的产品方向

### 2.1 保留 Pipeline 框架

- 不推翻现有代码的 Pipeline/Lane 架构
- 对话开始时仍然需要选定一个主方向（Lane）
- 现有 Lane 类型：
  - `attribute_lane`（属性话题：颜色、形状、大小等）
  - `category_lane`（分类话题：动物家族、比较等）
  - `general_chat` / `bound`（实体话题：围绕物体本身）
  - `bridge`（桥接话题：类比、迁移）

### 2.2 Pipeline 对应"话题"，话题下有多个活动

- 每个 Lane 进入时，确定一个**主话题**（如"颜色"）
- 同时准备**1-2 个备选话题**（如"形状"、"大小"）
- 每个话题对应**1 个活动**
- 因此一个 Lane 内部有 **2-3 个候选活动**

**为什么需要多个活动？**
- 场景 A：孩子不喜欢推荐的活动，要求换一个
- 场景 B：孩子非常投入，玩完一个后可以继续玩同话题的下一个
- 场景 C：孩子在对话中自然转移了兴趣（从颜色聊到形状），系统可以顺势推出形状活动

### 2.3 中途动态切换（核心决策）

**决策**: 不做"预先选好主话题后硬聊到底"，而是做"中途根据对话内容动态切换到备选话题"。

**具体机制**:
1. 对话开始时，系统选定：主话题 = 颜色，备选话题 = [形状, 大小]
2. 系统把这个信息告诉模型（通过 prompt）
3. 模型主要引导孩子聊颜色
4. 如果孩子自然提到了形状（"它好圆啊"），模型可以顺着聊形状
5. 后续的问题围绕形状生成，最终推出"形状探索"活动

**注意**:
- 这个切换不是"代码自动检测关键词并切 Lane"，而是"通过 prompt 告诉模型有哪些备选方向，由专用检测器判断孩子的兴趣是否已转移"。现有代码架构不支持 Lane 级别的自动切换。
- **切换是双向的**: 从 primary 切到 fallback 后，旧的 primary 会变成新的 fallback，模型可以在后续轮次中再次切回来。不限制切换次数。

### 2.4 话题难度进阶

**原则**: 话题选择不是随机的，要考虑孩子的年龄（Tier）。

| Tier | 年龄 | 适合的话题类型 | 例子 |
|------|------|---------------|------|
| Tier 1 | 3-4 岁 | 表象属性 | 颜色、形状、大小 |
| Tier 2 | 5-6 岁 | 功能/行为 | 猫怎么抓老鼠、为什么爬树 |
| Tier 3 | 7-8 岁 | 变化/逻辑/比较 | 猫和老虎有什么共同点、小猫怎么长大 |

**话题选择的四层筛选**:
1. **Catalog 能支撑什么**（新增）: 扫描活动库，哪些 observation_angle 有 eligible 活动。只保留 catalog 能 handoff 的属性。
2. **Entity 能聊什么**: 分析照片中的物体有哪些可聊的属性（橘猫 → 颜色、形状、声音、行为）。
3. **Tier 适合聊什么**: 3-4 岁优先选表象属性，7-8 岁可以选逻辑属性。
4. **避免重复**: 上一轮聊过的话题，本轮适当降级优先级。

**注意**：Layer 1（Catalog 可用性）是新增的最外层过滤。如果一个属性（如"气味"）在 catalog 中没有对应活动，即使 Photo 能检测到、Tier 适合聊，也不会进入候选池。这保证了最终推出的活动一定有 catalog 支撑。

---

## 3. 技术约束（代码现状）

### 3.1 Lane 是启动时一次性选定的

- Lane 只在 `/api/start` 时激活，之后整个 Session 锁定在该 Lane
- 代码路径: `paixueji_app.py:650-731`
- 两个 Lane 互斥: `start_attribute_lane()` 会自动 `clear_category_lane()`

### 3.2 Lane 内切换是可行的，跨 Lane 切换不可行

**可行的（Lane 内）**:
- 在 `attribute_lane` 内部，从"颜色"切换到"形状"
- 实现方式: 更新 `attribute_profile` 中的 `attribute_id` 和 `activity_target`
- 不需要改路由层

**不可行的（跨 Lane）**:
- 从 `attribute_lane` 切换到 `category_lane`
- 需要重构 `continue_conversation()` 的级联 if-else 路由结构
- 会导致状态丢失（turn_count、activity_ready 重置）

### 3.3 "动态切换"的实现方式

实际实现采用**独立的切换检测器**，将"检测"与"生成"解耦：

```
检测层（在响应生成之前运行）:
  detect_topic_switch(
    conversation_history,   # 最近 12 条消息
    primary,                # 当前主话题 AttributeProfile
    fallbacks,              # 备选话题列表
    child_input,            # 孩子最新消息
  )
  → 调用轻量级 LLM 判断孩子是否明显转向备选话题
  → 输出 JSON: {should_switch, target_attribute_id, reason}
  → 代码验证 target_attribute_id 确实在 fallbacks 中
  → 若有效，调用 assistant.switch_attribute_topic() 更新话题

生成层（检测完成后运行）:
  响应生成器看到的已经是更新后的话题
  → 不需要模型自己输出切换标记
  → 后续问题基于新属性生成
```

**为什么不用 `[SWITCH_TO]` 标记了？**
原方案让模型在生成回复时自行判断并附加标记，存在两个问题：
1. 模型可能漏加、错加或幻觉标记
2. 切换判断和响应生成耦合在一起，难以调试

新方案将切换判断交给专门的检测器，在生成器启动前完成决策，生成器只需专注于生成优质回复。

**Prompt 指令冲突解决**：`FOLLOWUP_QUESTION_PROMPT` 原本硬编码 "Stay on the same detail, same attribute"，与后续注入的切换指令冲突。修复方式为将 "same attribute" 改为注入式变量 `{focus_topic}`，由调用方根据当前状态注入实际话题（如 `"the 'shape' attribute"`）。这消除了指令冲突的源头。

---

## 4. 已确定的决策

以下问题已与 PM 确认，按决策执行。

### 4.1 切换的触发条件

**决策**: 采用 **C. 模型自主判断**（由专用检测器执行）。

不依赖模型在生成回复时自行附加 `[SWITCH_TO]` 标记。而是由一个独立的轻量级 LLM 调用（`detect_topic_switch`）专门负责判断孩子的兴趣转移。检测器在响应生成之前运行，与意图分类并行执行。

**切换判断的 concrete criteria**（检测器 prompt 中明确要求 ONLY switch when ONE of these is true）：
- 孩子用 3+ 个词描述备选话题（如 "SO BIG! Bigger than my dog!"）
- 孩子用备选话题做了比较
- 孩子直接问了一个关于备选话题的问题
- 孩子在连续 2+ 轮中回到备选话题

**新增负例过滤**（检测器 prompt 中明确排除）：
- 孩子在主要讨论当前话题时顺带提到备选属性（如 "It's red and very big" — 颜色是附带提及，孩子明显在聊大小）
- 单个颜色/形状词 without elaboration or comparison（如 "It's red."）
- 助手提到了备选话题，孩子只是回应助手的提及，没有主动表现出兴趣
- 孩子在同一句话里提到备选话题后又回到了当前话题

| 选项 | 状态 | 原因 |
|------|------|------|
| A. 关键词触发 | ❌ 不采用 | 过于敏感，容易误切 |
| B. 连续提及触发 | ❌ 不采用 | 增加轮数，孩子可能等不及 |
| C. 模型自主判断（专用检测器） | ✅ **采用** | 最自然，检测器与生成解耦，可控且可调试 |
| D. 显式询问 | ❌ 不采用 | 打断对话节奏 |

### 4.2 跨 Lane 话题的处理

**决策**: 采用 **C. 允许在 Lane 内小幅漂移**。

在 attribute_lane 的 prompt 中明确：可以简要回应跨 Lane 的问题（1 句话），但不要深入，尽快回到当前属性话题。V1 不做跨 Lane 切换（选项 D 为 V2 预留）。

### 4.3 话题难度进阶的具体映射

**决策**: 采用**固定映射**。

Tier 和话题类型的映射由 `exploration_categories.yaml` 中的 `tiers` 字段决定，V1 不做动态调整。V2 再考虑基于孩子表现做可配置映射。

### 4.4 每个话题的活动数量

**决策**: V1 采用 **2 个活动**（主活动 + 1 个备选）。

跑通核心流程后再扩展到 3 个（主 + 2 备选）。

### 4.5 Activity Catalog 的对接方式

**说明**: 活动库（Activity Catalog）由**内容团队**独立建设和维护，不是我们团队负责。我们的职责是：
1. 定义活动库需要遵循的 Schema（`tag_block.schema.json`）
2. 提供接入接口，让系统能从活动库中读取并匹配活动
3. 在活动库就绪前，用最小化的 mock 数据验证流程

**需要确认的问题**:
- 内容团队预计什么时候能提供第一批活动定义？
- 活动库的交付格式是 YAML 还是 JSON？
- 我们是否需要先提供 Schema 给内容团队，他们再按 Schema 生产内容？

### 4.6 推出活动的轮数预期

**决策**: **不做强制轮数上限**。

- 现有: 2-4 轮推出活动
- 有切换后: 可能 3-6 轮（切换花掉 1-2 轮）

活动推出由模型的 `[ACTIVITY_READY]` 判断驱动，保留现有的 quote validation 安全机制（`REASON` 中必须包含孩子原话引用）。

**新增保护**：接受 `[ACTIVITY_READY]` 前检查 `turn_count >= 3`，防止仅 1 轮浅层对话后就过早触发活动就绪。若轮数不足，拒绝并记录 `insufficient_turns`。

---

## 5. 技术实现思路（待确认后细化）

### 5.1 需要新建的模块

```
activities/
├── _schema/
│   └── tag_block.schema.json      # 活动定义 Schema（我们定义）
├── catalog/                        # 活动库（内容团队提供）
│   ├── <activity_family_1>.yaml   # 例如：颜色相关活动家族
│   ├── <activity_family_2>.yaml   # 例如：形状相关活动家族
│   └── ...                        # 更多活动家族
└── __init__.py
```

**注意**: `catalog/` 目录下的活动 YAML 由**内容团队**提供，不是我们编写。我们的工作是定义 Schema 和接入逻辑。

### 5.2 需要修改的现有模块

| 模块 | 修改内容 |
|------|---------|
| `paixueji_app.py` | `/api/start` 时，从"选单一属性"改为"选主属性 + 备选属性列表"；`/api/continue` 时支持 `[ACTIVITY_READY]` 轮数保护、并行意图分类 + 话题切换检测、切换在生成器之前应用 |
| `attribute_activity.py` | `AttributeProfile` 增加 `fallback_attributes` 字段 |
| `stream/topic_switch_detector.py` | **新增** — `detect_topic_switch()` 专用检测器，与意图分类并行运行，输出 JSON 切换决策 |
| `stream/question_generators.py` | `ask_attribute_intro_stream` 支持备选话题的 prompt；`ask_followup_question_stream` 新增 `focus_topic` 参数消除 prompt 指令冲突 |
| `stream/response_generators.py` | `generate_attribute_activation_response_stream` 新增 `multi_topic_guide` 参数；不再处理 `[SWITCH_TO]` 标记，仅负责响应生成 |
| `paixueji_prompts.py` | `ATTRIBUTE_MULTI_TOPIC_GUIDE` 简化为 `ATTRIBUTE_RESPONSE_GUIDE`；`FOLLOWUP_QUESTION_PROMPT` 改为注入式 `{focus_topic}` |

### 5.3 实现顺序（建议）

**Phase 1: MVP（验证核心流程）**
- 设计 `tag_block.schema.json`（活动定义 Schema）
- 用最小化 mock 数据验证匹配流程（mock 数据仅用于测试，不代表真实活动）
- 修改 `attribute_lane`，支持"主属性 + 1 个备选属性"
- 通过 prompt 让模型判断切换
- 不测跨 Lane 切换

**Phase 2: 丰富性**
- 扩展到 3 个备选属性
- 增加话题难度进阶逻辑
- 增加"孩子拒绝 → 换活动"的交互

**Phase 3: 智能化**
- 跨 Lane 切换（需要重构路由层）
- 基于历史表现的动态话题推荐
- 家长端的 Progression 展示

---

## 6. 决策汇总表

| 议题 | 决策 | 备注 |
|------|------|------|
| 是否保留 Pipeline | ✅ 保留 | 不大改现有架构 |
| 是否做自由聊天 | ❌ 不做 | 太发散，孩子需要引导 |
| 话题匹配几个活动 | 2 个（V1） | 主活动 + 1 个备选活动 |
| 话题选择策略 | 四层筛选 | Catalog → Entity → Tier → 避免重复 |
| 是否有备选 | ✅ 有 | 在 Lane 内部，不是跨 Lane |
| 备选是预先选好还是动态 | 动态切换 | 通过专用检测器 `detect_topic_switch()` 判断 |
| 切换触发条件 | 检测器自主判断 | 与意图分类并行运行，JSON 输出，代码验证后执行 |
| 切换是否双向 | ✅ 是 | primary ↔ fallback 可来回切换，无次数限制 |
| 跨 Lane 切换 | ❌ V1 不做 | Lane 内小幅漂移后拉回 |
| 话题难度进阶 | ✅ 做 | 基于 Tier 的固定映射 |
| 轮数上限 | ❌ 不做 | 由模型 `[ACTIVITY_READY]` 自主判断，保留 quote validation |

---

## 7. 下一步行动

1. **开发准备**: 开始设计 `activities/_schema/tag_block.schema.json`
2. **内容准备**: 开发团队先写 3 个示例活动 YAML（颜色、形状、大小）用于验证流程
3. **技术实现**: 按实现计划推进开发（`attribute_activity.py` 扩展、`paixueji_prompts.py` 多话题 prompt、`paixueji_app.py` 切换检测）
4. **技术验证**: 在一个分支上验证"prompt 层切换"的可行性（模型是否能准确判断切换时机）

---

---

## 8. 完整案例：橘猫照片的对话流程

以下案例完整展示了系统如何处理一次真实的互动。通过这个案例，你可以直观地理解"中途动态切换"是怎么工作的。

### 8.1 输入信息

| 字段 | 值 |
|------|-----|
| 照片 | 一只橘猫坐在沙发上 |
| 孩子年龄 | 5 岁（Tier 2） |
| 历史记录 | 上一轮聊过"颜色"话题（需要避免重复） |
| 当前 Lane | `attribute_lane`（属性话题 Lane） |

### 8.2 话题选择的四层筛选

**第一层：Catalog 能支撑什么（新增过滤层）**
- 扫描活动库，橘猫 photo 下 eligible 的活动对应的 observation_angle：
  - `color` → `color_scout` (parameterized, wide) ✓
  - `pattern` → `pattern_hunt` (parameterized, needs patterned_thing) ✓
  - `shape` → 无活动 ✗
  - `texture` → 无活动 ✗
  - `sound` → 无活动 ✗
- 过滤后可用 angles：`{color, pattern}`

**第二层：Entity 能聊什么（在 Catalog 可用范围内）**
- Photo 检测到的属性：颜色=橘色、花纹=条纹
- 与可用 angles 取交集：
  - 颜色（橘色）✓ — 在 available_angles 中
  - 花纹/条纹 ✓ — 在 available_angles 中
- 候选属性池：[颜色, 花纹]

**第二层：Tier 适合聊什么**
- 孩子 5 岁（Tier 2），适合聊：
  - 表象属性（颜色、形状、大小）✓
  - 功能/行为（怎么抓老鼠、为什么爬树）✓
- Tier 2 可以聊比 Tier 1 更深一点的内容

**第三层：避免重复**
- 上一轮已经聊过"颜色"
- 颜色降级，优先级降低

**最终选择**（V1 为主 + 1 个备选）：
- 主话题：**花纹**（因为颜色刚聊过，且花纹是唯一 remaining 的 catalog 可用属性）
- 备选话题：**颜色**（旧的 primary 变成 fallback，支持双向切换）

### 8.3 对话流程

---

**Round 1：开场（系统提问）**

> **系统**: "哇，好可爱的猫咪呀！你仔细看看，它身上有什么特别的图案吗？"

**系统内部状态**：
- 主话题 = 花纹（pattern）
- 当前活动目标 = `pattern_hunt`（来自活动库）
- 备选话题 = [颜色]
- Prompt 里告诉模型：主要引导花纹，备选是颜色

---

**Round 2：孩子回复**

> **孩子**: "有条纹！像斑马一样！"

**系统处理**：
- 孩子的回复明确在聊"花纹/图案"（条纹、斑马）
- 匹配主话题 ✅
- 不触发切换
- 继续引导花纹话题

> **系统**: "对呀，条纹好特别！那你知道还有什么动物也有条纹吗？"

---

**Round 3：孩子回复（关键转折）**

> **孩子**: "老虎也有条纹！但是橘色更好看，我最喜欢橘色了！"

**系统处理**：
- 孩子前半句还在聊花纹（老虎也有条纹）
- 但后半句明显转移到了"颜色"（橘色更好看、最喜欢橘色）
- 这是**备选话题**！且表达了强烈偏好

**检测器判断**（在响应生成之前运行）：
- `detect_topic_switch()` 接收：当前话题=花纹，备选=[颜色]，历史对话，孩子输入
- 检测器分析：孩子用了"最喜欢"这种强烈表达，且明确提到了备选话题（橘色），符合切换条件
- 检测器输出：`{"should_switch": true, "target_attribute_id": "appearance.color", "reason": "child expressed strong preference for color"}`
- 代码验证 "appearance.color" 确实在 fallbacks 中，调用 `assistant.switch_attribute_topic("appearance.color")`
- **同时**：代码验证 "color" 对应的 observation_angle 在 `available_angles` 中（catalog 驱动过滤）

> **系统**: "哇，你最喜欢橘色呀！那你知道这只猫咪的橘色像什么水果吗？"

**系统内部状态更新**：
- 检测器判定切换到 "appearance.color"
- 主话题从"花纹"切换为"颜色"
- 当前活动目标从"pattern_hunt"切换为"color_scout"
- 备选话题更新为：[花纹]（旧的 primary 变成新的 fallback）
- 响应生成器在切换**之后**运行，因此直接围绕"颜色"生成回复

---

**Round 4：孩子回复**

> **孩子**: "像橘子！橘子和猫咪都是橘色的！"

**系统处理**：
- 孩子在聊"颜色"，匹配当前主话题 ✅
- 孩子有创造性回答（联系橘子和猫咪），表现出深度参与
- 继续引导，准备推出活动

> **系统**: "太棒了！你观察得真好。那我们来玩一个游戏吧——我们去找找看，家里还有哪些东西也是橘色的！"

**系统内部状态**：
- 对话轮数达到阈值（4 轮）
- 孩子持续在聊颜色话题，且表现出深度兴趣
- **推出活动**：`color_scout`（颜色探索活动）

---

### 8.4 如果没有中途切换会怎样？

**对比场景**：假设系统不做动态切换，硬聊花纹到底

> **孩子**: "老虎也有条纹！但是橘色更好看，我最喜欢橘色了！"
> **系统（硬拉回）**: "对呀，老虎也有条纹！那我们回来看看猫咪，它的条纹是直直的还是弯弯的？"

**问题**：
- 孩子明显对"颜色"更感兴趣（"最喜欢橘色"），但系统强行拉回到"花纹"
- 孩子可能觉得"你没有听我说话"
- 后续轮数可能增加（孩子继续提颜色，系统继续拉回）
- 最终推出的 `pattern_hunt` 不是孩子真正想玩的

### 8.5 如果孩子在 Round 3 聊到了 catalog 不支持的属性

**假设**：

> **孩子**: "它摸起来好软啊！毛茸茸的！"

**系统处理（Catalog 驱动过滤）**：

> **系统**: "是啊，软软的！那你再仔细看看，它身上的条纹是什么颜色的呢？"

**分析**：
- 孩子提到了"触感/ texture"，但 texture 不在 `available_angles` 中（catalog 没有 texture 相关活动）
- `detect_topic_switch()` 检测到 "texture" 不在 fallbacks 中，**拒绝切换**
- 系统简要回应了触感（1 句话），然后 gentle pivot 回有 catalog 支撑的属性（花纹的颜色）
- 没有切换话题，活动目标保持 `pattern_hunt`

---

### 8.6 案例总结

| 阶段 | 发生了什么 | 说明 |
|------|-----------|------|
| 开场 | 系统选"花纹"为主话题 | 因为颜色刚聊过需要避免重复；且花纹是 catalog 可用属性 |
| Round 1-2 | 正常聊花纹 | 孩子配合，不触发切换 |
| Round 3 | 孩子表达对颜色的强烈偏好 | 这是备选话题，检测器判定可以切换 |
| Round 3 | 检测器输出切换决策 | `detect_topic_switch()` 运行，验证 target 在 fallbacks 中且 angle 可用 |
| Round 4 | 顺着颜色聊 | 话题已切换，后续围绕颜色展开 |
| 结束 | 推出"color_scout"活动 | 活动匹配孩子的实际兴趣，且 catalog 确认可支撑 |

**关键点**：
1. 切换由**专用检测器**判断，不是关键词硬匹配，也不是模型自己标记
2. 切换只在**Lane 内部**发生（花纹 → 颜色，都在 attribute_lane）
3. 切换后**活动目标同步更新**，最终推出的活动匹配孩子的兴趣
4. **Catalog 驱动**：系统不会切换到 catalog 不支持的属性（如 texture），避免聊出 dead end

---

---

## 9. 实现记录

> **实现日期**: 2026-05-11（初始实现），2026-05-12（topic switch detector 重构），2026-05-13（fallback mapping + matched activity 客户端暴露）  
> **实现分支**: `worktree-activity-matching`（已合并至 `main`），后续 detector 重构和 activity matching 优化直接在 `main` 上进行  
> **测试状态**: 669 项测试全部通过（665 passed, 4 skipped）

本节记录本 PRD 中各项决策的实际实现情况，包括代码位置、实现方式和与 PRD 的差异。

### 9.1 已实现内容

#### 9.1.1 Activity Catalog（活动库）

**PRD 对应**: 第 5.1 节、第 4.5 节  
**实现状态**: ✅ 已完成

| 文件 | 说明 |
|------|------|
| `activities/_schema/tag_block.schema.json` | 活动定义 JSON Schema（8 个字段，含 required 校验） |
| `activities/catalog/color_exploration.yaml` | Mock 活动：颜色探索 |
| `activities/catalog/shape_exploration.yaml` | Mock 活动：形状探索 |
| `activities/catalog/size_exploration.yaml` | Mock 活动：大小探索 |
| `activities/__init__.py` | Catalog loader + matcher：`ActivityDefinition` dataclass、`_load_catalog()`、`get_activity_for_attribute()`、`list_activities_for_attribute()`；**新增** `_SUB_ATTRIBUTE_TO_GENERIC` 回退映射 + `_resolve_generic_attribute_id()` |

**实现细节**:
- 使用 `yaml.safe_load()` 加载 YAML，LRU cache 避免重复 IO
- `_age_to_tier()` 本地定义（复制自 `stream/exploration_loader`），避免跨模块依赖
- `get_activity_for_attribute()` 按 `target_attribute` + `tier` 双条件匹配
- **新增回退映射**：`get_activity_for_attribute()` 精确匹配失败后，尝试将 domain-specific ID（如 `appearance.body_color`）解析为 generic ID（`appearance.color`）再次匹配；`list_activities_for_attribute()` 同样支持回退
- `_SUB_ATTRIBUTE_TO_GENERIC` 当前覆盖 7 个 sub-attribute（`body_color`→`color`, `flower_color`→`color`, `body_size`→`size` 等），仅映射到有 mock 活动的 generic 属性
- 回退成功时记录 `[ACTIVITY_MATCH] fallback mapping ...` info 日志
- 异常处理：YAML 格式错误时跳过该文件并记录 warning，不中断整个加载流程

#### 9.1.2 主话题 + 备选话题（Primary + Fallback）

**PRD 对应**: 第 2.2 节、第 4.4 节  
**实现状态**: ✅ 已完成

| 文件 | 修改内容 |
|------|---------|
| `attribute_activity.py` | `AttributeProfile` 新增 `fallback_attributes: tuple[AttributeProfile, ...]`；`DiscoverySessionState` 新增 `fallback_profiles`、`switched_to`、`switch_reason`；`_build_fallback_attribute_block()` 辅助函数 |
| `attribute_activity.py:select_attribute_profile()` | 同时请求 Gemini 选出 `attribute_id`（主话题）和 `fallback_attribute_id`（备选话题）；构造嵌入了 fallback 的 `AttributeProfile` 返回 |
| `paixueji_prompts.py` | `ATTRIBUTE_SELECTION_PROMPT` 更新为同时要求 primary 和 fallback attribute_id |
| `attribute_activity.py:start_attribute_session()` | 将 `profile.fallback_attributes` 写入 `DiscoverySessionState.fallback_profiles` |

**实现细节**:
- 单候选属性时直接返回，不附加 fallback
- fallback 必须与 primary 不同；若 Gemini 返回相同 ID，自动选择第一个非 primary 候选
- `max_output_tokens` 从 120 提升至 180，容纳额外 JSON 字段

#### 9.1.3 动态话题切换（`detect_topic_switch` 检测器）

**PRD 对应**: 第 2.3 节、第 3.3 节、第 4.1 节  
**实现状态**: ✅ 已完成（2026-05-12 重构为检测器驱动）

| 文件 | 修改内容 |
|------|---------|
| `stream/topic_switch_detector.py` | **新增** — `detect_topic_switch()`：专用轻量级 LLM 检测器，与意图分类并行运行，输出 JSON 切换决策 |
| `paixueji_assistant.py` | `switch_attribute_topic(target_attribute_id)`：双向切换逻辑——选中的 fallback 成为新 primary，旧 primary 进入新 fallback 列表；重置 `activity_ready` 标志 |
| `stream/__init__.py` | 导出 `detect_topic_switch` |

**实现细节**:
- **检测器架构**：独立的 `detect_topic_switch()` 函数，将"切换判断"与"响应生成"完全解耦
- **并行执行**：在 `paixueji_app.py:1317-1353` 中，`classify_intent()` 和 `detect_topic_switch()` 通过 `asyncio.run_coroutine_threadsafe()` 并行提交到全局事件循环，各有一个 10 秒超时
- **检测器输入**：当前 primary `AttributeProfile`、`fallback_attributes` tuple、最近 12 条对话历史、孩子最新消息
- **检测器输出**：`(should_switch: bool, target_attribute_id: str|None, reason: str)`
- **目标验证**：返回 `True` 前验证 `target_attribute_id` 确实存在于 fallbacks 中，防止幻觉目标
- **安全降级**：JSON 解析错误、异常或无效目标时返回 `(False, None, "error: ...")`，对话不受影响
- **检测器 prompt**：包含 4 条 concrete criteria（3+ words / 比较 / 提问 / 连续 2+ 轮）+ 4 条 negative examples（附带提及 / 单字描述 / 被动回应 / 同一消息内回归）
- **参数**：`temperature=0.1`，`max_output_tokens=150`，轻量快速
- 切换无次数限制，可来回切换
- 切换后 `fallback_profiles` 同步更新，保持状态一致性
- 切换后 `activity_ready` 和 `attribute_activity_ready` 均重置为 `False`
- **移除的旧代码**：`detect_switch_marker()`（正则检测 `[SWITCH_TO:xxx]` 标记）已从 `stream/response_generators.py` 中移除

#### 9.1.4 Prompt 模板

**PRD 对应**: 第 3.3 节、第 4.1 节  
**实现状态**: ✅ 已完成（2026-05-12 简化）

| 文件 | 修改内容 |
|------|---------|
| `paixueji_prompts.py` | `ATTRIBUTE_MULTI_TOPIC_GUIDE` 简化为 `ATTRIBUTE_RESPONSE_GUIDE`，移除 `[SWITCH_TO]` 规则和三种技巧，保留 exploration direction、activity goal、`[ACTIVITY_READY]` 信号和 anti-patterns |
| `paixueji_prompts.py` | `FOLLOWUP_QUESTION_PROMPT` 注入式改造："same attribute" 改为 `{focus_topic}`，由调用方传入当前话题，消除与多话题引导的指令冲突 |

**实现细节**:
- `ATTRIBUTE_RESPONSE_GUIDE`（`paixueji_prompts.py:560-580`）结构：
  - `{sensory_safety_rules}`
  - `EXPLORATION DIRECTION: {attribute_label}`
  - `ACTIVITY GOAL: {activity_target}`
  - `TRANSITION SIGNAL for [ACTIVITY_READY]`（3 行格式）
  - `ANTI-PATTERNS`（8 项，含 "Switching topics on a single casual mention — too sensitive"）
- 移除内容：primary/fallback topic block、`[SWITCH_TO]` 规则、SALIENCE/FRAME WEAVING/NATURAL BRIDGE 技巧
- `FOLLOWUP_QUESTION_PROMPT` 运行时通过 `.format()` 填入 `focus_topic`（如 `"the 'shape' attribute"` 或 `"same attribute or same detail"`）
- 响应生成器通过 `multi_topic_guide` 参数接收 guide，但会剥离 `TRANSITION SIGNAL for [ACTIVITY_READY]:` 之后的部分，防止响应生成器输出 `[ACTIVITY_READY]`

#### 9.1.5 `/api/continue` 集成

**PRD 对应**: 第 3.3 节  
**实现状态**: ✅ 已完成（2026-05-12 重构为检测器前置）

| 文件 | 修改内容 |
|------|---------|
| `paixueji_app.py` | 在 `stream_attribute_activity()` 的 continue 路径中：`turn_count += 1` 后，并行运行 `classify_intent()` 和 `detect_topic_switch()`；若检测器判定切换，在生成器**启动前**调用 `assistant.switch_attribute_topic()`；然后构造 `soft_guide`；`generate_attribute_activation_response_stream` 传入 `multi_topic_guide=soft_guide`；`ask_followup_question_stream` 传入 `focus_topic` 和 `attribute_soft_guide=soft_guide`；`[ACTIVITY_READY]` 增加 `turn_count >= 3` 轮数保护 |

**实现细节**:
- **检测前置**：切换检测在 `stream_attribute_activity()` 定义/调用之前完成（`paixueji_app.py:1355-1370`），生成器直接看到已更新的话题
- `soft_guide` 构造在 response generator 之前，使响应生成器和跟进问题生成器共享同一套话题指引
- response generator 通过 `multi_topic_guide` 参数接收 guide，但已不负责输出 `[SWITCH_TO]`
- 跟进问题生成器通过 `focus_topic` 参数接收当前话题（如 `"the 'shape' attribute"`），不再与切换指令冲突
- `_strip_activity_markers(full_response)` 安全网：在响应返回给孩子前剥离任何泄露的 `[ACTIVITY_READY]` / `REASON:` 标记
- `[ACTIVITY_READY]` 校验新增 `turn_count >= 3` 门槛，防止过早触发
- `[ACTIVITY_READY]` 被拒绝时（`insufficient_turns` / `no_evidence_quotes` / `evidence_not_in_transcript`），`_displayable_followup()` 剥离 marker 和 REASON 行后保留 follow-up question 文本，确保对话可以继续
- 新增 `logger.info("[ATTRIBUTE_SWITCH] ...")` 和 `logger.warning("[ATTRIBUTE_SWITCH] ...")` 便于生产排障
- 新增 `logger.info("[TOPIC_SWITCH] ...")` 和 `logger.warning("[TOPIC_SWITCH] ...")` 用于检测器诊断

#### 9.1.6 `/api/start` 集成

**PRD 对应**: 第 2.2 节  
**实现状态**: ✅ 已完成

| 文件 | 修改内容 |
|------|---------|
| `paixueji_app.py` | 在 `start_attribute_lane()` 之后，调用 `get_activity_for_attribute()` 为主话题和每个 fallback 话题匹配活动；匹配成功的 `ActivityDefinition` 保存到 `assistant.attribute_matched_activity`（包含 `activity_id`, `name`, `launch_prompt`） |

**实现细节**:
- 主话题匹配成功后，将 `activity_id` / `name` / `launch_prompt` 写入 `assistant.attribute_matched_activity`
- fallback 话题仅记录日志，不保存 matched activity（因为当前只展示主话题的活动）
- 匹配失败时 `assistant.attribute_matched_activity = None`

#### 9.1.7 Stream 元数据暴露

**PRD 对应**: —（新增）  
**实现状态**: ✅ 已完成

| 文件 | 修改内容 |
|------|---------|
| `paixueji_app.py` | `_assistant_stream_fields()` 新增 `switch_state` 字典，包含：`attribute_switched_to`、`attribute_switch_reason`、`attribute_fallback_count`、`attribute_turn_count`；额外暴露 `attribute_fallback_labels` 和 `attribute_activity_ready_rejected_reason` |

#### 9.1.9 活动信息客户端暴露（Chat-to-Activity 闭环）

**PRD 对应**: —（隐含需求，V1 未单独成节）  
**实现状态**: ✅ 已完成（2026-05-13）

| 文件 | 修改内容 |
|------|---------|
| `paixueji_assistant.py` | `__init__` / `start_attribute_lane()` / `clear_attribute_lane()` 中管理 `attribute_matched_activity` 字段；`attribute_activity_target()` 将 matched activity 的 `activity_id` / `name` / `launch_prompt` 暴露给客户端 |
| `paixueji_app.py` | 切换话题成功后（`switch_attribute_topic`），重新调用 `get_activity_for_attribute()` 为**新话题**匹配活动并更新 `assistant.attribute_matched_activity` |

**实现细节**:
- `attribute_activity_target()` 返回格式新增三个字段（仅在 matched activity 存在时出现）：
  - `activity_id`: 如 `"color_exploration_v1"`
  - `activity_name`: 如 `"Color Explorer"`
  - `launch_prompt`: 活动的启动文案
- 该字典通过 `_assistant_stream_fields()` → `StreamChunk` → SSE 流返回客户端
- 话题切换后自动重新匹配活动，确保客户端最终拿到的是**孩子实际聊的话题**对应的活动

#### 9.1.8 单元测试

**PRD 对应**: 第 7 节  
**实现状态**: ✅ 已完成

| 文件 | 测试内容 |
|------|---------|
| `tests/test_activity_catalog.py` | 9 个测试：颜色/形状/大小匹配、无匹配返回 None、Tier 过滤、**fallback mapping（5 个）**：`body_color`→`color`、`flower_color`→`color`、`body_size`→`size`、无映射返回 None、`list_activities` 回退 |
| `tests/test_topic_switch_detector.py` | **5 个测试**：happy path（should_switch=True + 有效目标）、no-switch path、无效目标拒绝、Markdown-fenced JSON 解析、畸形 JSON 安全降级 |
| `tests/test_attribute_switching.py` | **5 个测试**：切换到 fallback、无效目标拒绝、focus_topic 参数存在、检测器前置切换、**matched activity 暴露（2 个）**：`attribute_activity_target` 包含 `activity_id`/`activity_name`/`launch_prompt`、`clear_attribute_lane` 清除 `attribute_matched_activity` |
| ~~`tests/test_switch_marker.py`~~ | ~~3 个测试~~ — **已移除**（标记检测机制已废弃） |

### 9.2 与 PRD 的差异

| PRD 内容 | 实现差异 | 原因 |
|---------|---------|------|
| 第 5.1 节提到 `_index.yaml` 注册表 | 未实现 | V1 仅 3 个 mock 活动，直接遍历 YAML 足够快；待活动库规模扩大后再实现 |
| 第 4.4 节提到 V1 用 2 个活动（主 + 1 备选） | 实现支持任意数量 fallback | `fallback_attributes` 为 `tuple`，不限于 1 个；当前 Gemini prompt 要求选 1 个 fallback |
| 第 3.3 节提到 "prompt 层切换" 需技术验证 | 已实现并验证 | 通过单元测试和完整测试套件验证（669 passed） |
| 第 4.6 节提到轮数预期 3-6 轮 | 未做强制限制 | 完全由模型 `[ACTIVITY_READY]` 自主判断，保留现有 quote validation |
| PRD: marker-based `[SWITCH_TO]` switching | 替换为 standalone `detect_topic_switch` 检测器 | 更好的关注点分离，减少幻觉标记，支持并行执行，更易调试 |
| PRD 未明确 domain-specific → generic 属性映射 | 补充 `_SUB_ATTRIBUTE_TO_GENERIC` 回退映射 | `exploration_categories.yaml` 使用 domain-specific ID（`appearance.body_color`），而活动库使用 generic ID（`appearance.color`），两者命名空间未对齐；回退映射填补了这一 gap |
| PRD 未明确 matched activity 如何暴露给客户端 | 补充 `attribute_matched_activity` + `attribute_activity_target()` 暴露 | 设计文档描述"推出大小探索活动"但未说明活动信息如何传递；通过 SSE stream metadata 暴露 `activity_id`/`activity_name`/`launch_prompt` 完成闭环 |

### 9.3 未实现（V2 预留）

| PRD 内容 | 状态 | 备注 |
|---------|------|------|
| 扩展到 3 个备选属性 | ❌ V2 | 当前 prompt 只要求选 1 个 fallback，代码结构已支持任意数量 |
| 跨 Lane 切换 | ❌ V2 | 需要重构 `continue_conversation()` 路由层，V1 仅在 Lane 内小幅漂移 |
| 孩子拒绝 → 换活动 | ❌ V2 | 需要新增意图分类 + 活动重选逻辑 |
| 基于历史表现的动态话题推荐 | ❌ V2 | 需要会话历史分析和偏好学习 |
| 家长端 Progression 展示 | ❌ V2 | 前端需求，非后端实现范围 |

### 9.4 关键代码路径速查

```
启动时选主+备选:
  paixueji_app.py:start_conversation()
    → attribute_activity.py:select_attribute_profile()
      → paixueji_prompts.py:ATTRIBUTE_SELECTION_PROMPT
    → paixueji_app.py:start_attribute_lane()
      → paixueji_assistant.py:start_attribute_lane()
    → paixueji_app.py:get_activity_for_attribute() [ACTIVITY_MATCH 日志]
      → 匹配成功: assistant.attribute_matched_activity = {activity_id, name, launch_prompt}
      → 匹配失败: assistant.attribute_matched_activity = None

继续对话时检测切换:
  paixueji_app.py:continue_conversation()
    → classify_intent() + detect_topic_switch() 并行运行
      → assistant.switch_attribute_topic() (若检测器判定切换)
      → 重新匹配活动: get_activity_for_attribute(新话题) → 更新 assistant.attribute_matched_activity
    → stream_attribute_activity()
      → 构造 soft_guide（基于当前已切换的话题）
      → generate_attribute_activation_response_stream(multi_topic_guide=soft_guide)
        → 不处理 [SWITCH_TO]，仅生成响应
      → ask_followup_question_stream(focus_topic="the '形状' attribute", attribute_soft_guide=soft_guide)
        → 不处理 [SWITCH_TO]，仅生成跟进问题
      → [ACTIVITY_READY] 校验: turn_count >= 3 + quote validation
        → 拒绝时: marker/REASON 被 _displayable_followup() 剥离，follow-up question 保留继续对话
        → 接受时: assistant.attribute_activity_ready = True，进入活动推出流程

Stream 元数据:
  paixueji_app.py:_assistant_stream_fields()
    → switch_state {attribute_switched_to, attribute_switch_reason, ...}
    → activity_target {
         attribute_id, attribute_label, activity_target,
         activity_id, activity_name, launch_prompt   ← 新增（matched activity 存在时）
       }
```

---

*本报告由开发团队与 PM 的多轮讨论整理而成。如有疑问，请对照第 4 节的未确定问题逐项确认。*

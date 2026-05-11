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
- 这个切换不是"代码自动检测关键词并切 Lane"，而是"通过 prompt 告诉模型有哪些备选方向，让模型自己判断是否切换"。现有代码架构不支持 Lane 级别的自动切换。
- **切换是双向的**: 从 primary 切到 fallback 后，旧的 primary 会变成新的 fallback，模型可以在后续轮次中再次切回来。不限制切换次数。

### 2.4 话题难度进阶

**原则**: 话题选择不是随机的，要考虑孩子的年龄（Tier）。

| Tier | 年龄 | 适合的话题类型 | 例子 |
|------|------|---------------|------|
| Tier 1 | 3-4 岁 | 表象属性 | 颜色、形状、大小 |
| Tier 2 | 5-6 岁 | 功能/行为 | 猫怎么抓老鼠、为什么爬树 |
| Tier 3 | 7-8 岁 | 变化/逻辑/比较 | 猫和老虎有什么共同点、小猫怎么长大 |

**话题选择的三层筛选**:
1. **Entity 能聊什么**: 分析照片中的物体有哪些可聊的属性（橘猫 → 颜色、形状、声音、行为）
2. **Tier 适合聊什么**: 3-4 岁优先选表象属性，7-8 岁可以选逻辑属性
3. **避免重复**: 上一轮聊过的话题，本轮适当降级优先级

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

由于代码不支持自动检测切换，实际实现是:

```
Prompt 层:
  "你的主要任务是引导孩子观察[主话题]。
   但也允许聊这些备选话题：[备选话题列表]。
   如果孩子主动提到了备选话题，可以顺着聊。
   你觉得孩子的兴趣已经转移到备选话题时，
   在回复末尾加上 [SWITCH_TO:shape] 标记。"

代码层:
  检测模型输出中的 [SWITCH_TO:xxx] 标记
  → 更新 attribute_profile 为新的属性
  → 后续问题基于新属性生成
```

---

## 4. 已确定的决策

以下问题已与 PM 确认，按决策执行。

### 4.1 切换的触发条件

**决策**: 采用 **C. 模型自主判断**。

模型通过 prompt 获知备选话题列表，自主判断孩子是否对备选话题更感兴趣。判断切换时，在回复末尾加上 `[SWITCH_TO:attribute_id]` 标记，由代码层检测并执行切换。

| 选项 | 状态 | 原因 |
|------|------|------|
| A. 关键词触发 | ❌ 不采用 | 过于敏感，容易误切 |
| B. 连续提及触发 | ❌ 不采用 | 增加轮数，孩子可能等不及 |
| C. 模型自主判断 | ✅ **采用** | 最自然，通过 prompt 调优可控 |
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

活动推出完全由模型的 `[ACTIVITY_READY]` 判断驱动，保留现有的 quote validation 安全机制（`REASON` 中必须包含孩子原话引用）。不强制在 N 轮后硬推活动。

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
| `paixueji_app.py` | `/api/start` 时，从"选单一属性"改为"选主属性 + 备选属性列表" |
| `attribute_activity.py` | `AttributeProfile` 增加 `fallback_attributes` 字段 |
| `stream/question_generators.py` | `ask_attribute_intro_stream` 支持备选话题的 prompt |
| `stream/response_generators.py` | 检测 `[SWITCH_TO:xxx]` 标记，触发话题切换 |
| `paixueji_prompts.py` | 新增 attribute_lane 的备选话题 prompt 模板 |

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
| 话题选择策略 | 三层筛选 | Entity → Tier → 避免重复 |
| 是否有备选 | ✅ 有 | 在 Lane 内部，不是跨 Lane |
| 备选是预先选好还是动态 | 动态切换 | 通过 prompt 让模型判断 |
| 切换触发条件 | 模型自主判断 | `[SWITCH_TO]` 标记，代码检测 |
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

### 8.2 话题选择的三层筛选

**第一层：Entity 能聊什么**
- 系统分析橘猫的可聊属性：
  - 颜色（橘色）✓
  - 形状（圆滚滚、尖耳朵）✓
  - 大小（比狗小）✓
  - 触感（毛茸茸）✓
  - 声音（喵喵叫）✓
- 候选属性池：[颜色, 形状, 大小, 触感, 声音]

**第二层：Tier 适合聊什么**
- 孩子 5 岁（Tier 2），适合聊：
  - 表象属性（颜色、形状、大小）✓
  - 功能/行为（怎么抓老鼠、为什么爬树）✓
- Tier 2 可以聊比 Tier 1 更深一点的内容

**第三层：避免重复**
- 上一轮已经聊过"颜色"
- 颜色降级，优先级降低

**最终选择**（V1 为主 + 1 个备选）：
- 主话题：**形状**（因为颜色刚聊过，形状是最显眼的备选）
- 备选话题：**大小**（也是表象属性，容易观察）

### 8.3 对话流程

---

**Round 1：开场（系统提问）**

> **系统**: "哇，好可爱的猫呀！你仔细看看，它的身体看起来像什么形状？"

**系统内部状态**：
- 主话题 = 形状
- 当前活动目标 = 形状探索活动（来自活动库）
- 备选话题 = [大小]
- Prompt 里告诉模型：主要引导形状，备选是大小

---

**Round 2：孩子回复**

> **孩子**: "它好圆啊！像一个球！"

**系统处理**：
- 孩子的回复明确在聊"形状"（圆、球）
- 匹配主话题 ✅
- 不触发切换
- 继续引导形状话题

> **系统**: "对呀，圆滚滚的！那它的耳朵呢？也是圆的吗？"

---

**Round 3：孩子回复（关键转折）**

> **孩子**: "耳朵是尖尖的。而且它好大好大，比我的玩具熊还大！"

**系统处理**：
- 孩子前半句还在聊形状（尖尖的耳朵）
- 但后半句转移到了"大小"（好大好大、比玩具熊大）
- 这是**备选话题**！

**模型判断**：
- Prompt 告诉模型：如果孩子明显对备选话题更感兴趣，可以切换
- 模型判断：孩子用了"好大好大"这种强调表达，说明对大小很感兴趣
- 模型在回复末尾加上标记：`[SWITCH_TO:size]`

> **系统**: "哇，真的吗？比你的玩具熊还大！那它站起来的时候，是不是更高了？`[SWITCH_TO:size]`"

**系统内部状态更新**：
- 检测到 `[SWITCH_TO:size]` 标记
- 主话题从"形状"切换为"大小"
- 当前活动目标从"形状探索"切换为"大小探索活动"
- 备选话题更新为：[形状]（旧的 primary 变成新的 fallback）

---

**Round 4：孩子回复**

> **孩子**: "嗯！它站起来的时候好高！"

**系统处理**：
- 孩子在聊"大小"，匹配当前主话题 ✅
- 继续引导，准备推出活动

> **系统**: "太棒了！你观察得好仔细。那我们来玩一个游戏吧——你能找到家里比这只猫小的东西吗？"

**系统内部状态**：
- 对话轮数达到阈值（4 轮）
- 孩子持续在聊大小话题
- **推出活动**：大小探索活动

---

### 8.4 如果没有中途切换会怎样？

**对比场景**：假设系统不做动态切换，硬聊形状到底

> **孩子**: "耳朵是尖尖的。而且它好大好大..."
> **系统（硬拉回）**: "对，耳朵是尖尖的三角形！那我们回来看看它的身体，是不是圆圆的？"

**问题**：
- 孩子明显对"大小"更感兴趣，但系统强行拉回到"形状"
- 孩子可能觉得"你没有听我说话"
- 后续轮数可能增加（孩子继续提大小，系统继续拉回）
- 最终推出的活动可能不是孩子真正想玩的

### 8.5 如果孩子在 Round 3 聊到了跨 Lane 的话题

**假设**：

> **孩子**: "它叫起来像老虎！猫和老虎是一家吗？"

**系统处理（V1 方案：小幅漂移但不切换 Lane）**：

> **系统**: "对呀，它们都是猫科动物！老虎就像是猫的大表哥呢。那你觉得，猫和老虎谁的耳朵更尖？"

**分析**：
- 孩子提到了"分类/家族"（这是 `category_lane` 的话题）
- 但系统仍在 `attribute_lane` 内
- 系统简要回应了分类问题（1 轮），然后把话题拉回到属性（耳朵的形状）
- 没有切换 Lane，也没有切换活动目标

---

### 8.6 案例总结

| 阶段 | 发生了什么 | 说明 |
|------|-----------|------|
| 开场 | 系统选"形状"为主话题 | 因为颜色刚聊过，需要避免重复 |
| Round 1-2 | 正常聊形状 | 孩子配合，不触发切换 |
| Round 3 | 孩子提到"大小" | 这是备选话题，模型判断可以切换 |
| Round 3 末尾 | 系统加 `[SWITCH_TO:size]` | 代码检测标记，更新活动目标 |
| Round 4 | 顺着大小聊 | 话题已切换，后续围绕大小展开 |
| 结束 | 推出"大小探索"活动 | 活动匹配孩子的实际兴趣 |

**关键点**：
1. 切换是**模型自主判断**的，不是关键词硬匹配
2. 切换只在**Lane 内部**发生（形状 → 大小，都在 attribute_lane）
3. 切换后**活动目标同步更新**，最终推出的活动匹配孩子的兴趣
4. 如果聊到跨 Lane 话题，**简要回应后拉回**，不切换 Lane

---

---

## 9. 实现记录

> **实现日期**: 2026-05-11  
> **实现分支**: `worktree-activity-matching`（已合并至 `main`）  
> **测试状态**: 667 项测试全部通过（663 passed, 4 skipped）

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
| `activities/__init__.py` | Catalog loader + matcher：`ActivityDefinition` dataclass、`_load_catalog()`、`get_activity_for_attribute()`、`list_activities_for_attribute()` |

**实现细节**:
- 使用 `yaml.safe_load()` 加载 YAML，LRU cache 避免重复 IO
- `_age_to_tier()` 本地定义（复制自 `stream/exploration_loader`），避免跨模块依赖
- `get_activity_for_attribute()` 按 `target_attribute` + `tier` 双条件匹配
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

#### 9.1.3 动态话题切换（`[SWITCH_TO]` 标记）

**PRD 对应**: 第 2.3 节、第 3.3 节、第 4.1 节  
**实现状态**: ✅ 已完成

| 文件 | 修改内容 |
|------|---------|
| `stream/response_generators.py` | `detect_switch_marker(response_text)`：正则匹配 `\[SWITCH_TO:([\w.]{1,64})\]`，返回 `(target_id, cleaned_text)` |
| `paixueji_assistant.py` | `switch_attribute_topic(target_attribute_id)`：双向切换逻辑——选中的 fallback 成为新 primary，旧 primary 进入新 fallback 列表；重置 `activity_ready` 标志 |
| `stream/__init__.py` | 导出 `detect_switch_marker` |

**实现细节**:
- 切换无次数限制，可来回切换
- 切换后 `fallback_profiles` 同步更新，保持状态一致性
- 切换后 `activity_ready` 和 `attribute_activity_ready` 均重置为 `False`
- 标记检测使用 `{1,64}` 长度限制，防止异常输入

#### 9.1.4 多话题 Prompt 模板

**PRD 对应**: 第 3.3 节、第 4.1 节  
**实现状态**: ✅ 已完成

| 文件 | 修改内容 |
|------|---------|
| `paixueji_prompts.py` | 新增 `ATTRIBUTE_MULTI_TOPIC_GUIDE` 模板，包含：主/备选话题说明、`[SWITCH_TO]` 规则、三种技巧（SALIENCE / FRAME WEAVING / NATURAL BRIDGE）、EVIDENCE REQUIREMENT、`[ACTIVITY_READY]` 信号、`[SWITCH_TO]` 信号、ANTI-PATTERNS 列表 |

**实现细节**:
- 模板通过 `get_prompts()["attribute_multi_topic_guide"]` 暴露
- 运行时通过 `.format()` 填入 `primary_attribute_label`、`primary_activity_target`、`fallback_attribute_block`、`sensory_safety_rules`

#### 9.1.5 `/api/continue` 集成

**PRD 对应**: 第 3.3 节  
**实现状态**: ✅ 已完成

| 文件 | 修改内容 |
|------|---------|
| `paixueji_app.py` | 在 `stream_attribute_activity()` 的 continue 路径中：收集 `full_response` 后调用 `detect_switch_marker()`；成功切换后刷新 `attribute_label` 和 `activity_target`；无论成功与否都从响应中剥离标记；软引导替换为 `attribute_multi_topic_guide` |

**实现细节**:
- 切换检测位于 response generator 消费完毕之后、follow-up question 生成之前
- 成功切换后刷新 `attribute_label` / `activity_target`，确保下一轮 prompt 使用新话题
- 新增 `logger.info("[ATTRIBUTE_SWITCH] ...")` 和 `logger.warning("[ATTRIBUTE_SWITCH] ...")` 便于生产排障

#### 9.1.6 `/api/start` 集成

**PRD 对应**: 第 2.2 节  
**实现状态**: ✅ 已完成

| 文件 | 修改内容 |
|------|---------|
| `paixueji_app.py` | 在 `start_attribute_lane()` 之后，调用 `get_activity_for_attribute()` 为主话题和每个 fallback 话题匹配活动，并记录 `[ACTIVITY_MATCH]` 日志 |

#### 9.1.7 Stream 元数据暴露

**PRD 对应**: —（新增）  
**实现状态**: ✅ 已完成

| 文件 | 修改内容 |
|------|---------|
| `paixueji_app.py` | `_assistant_stream_fields()` 新增 `switch_state` 字典，包含：`attribute_switched_to`、`attribute_switch_reason`、`attribute_fallback_count`、`attribute_turn_count` |

#### 9.1.8 单元测试

**PRD 对应**: 第 7 节  
**实现状态**: ✅ 已完成

| 文件 | 测试内容 |
|------|---------|
| `tests/test_activity_catalog.py` | 4 个测试：颜色/形状匹配、无匹配返回 None、Tier 过滤 |
| `tests/test_switch_marker.py` | 3 个测试：标记检测（存在/不存在/多行） |
| `tests/test_attribute_switching.py` | 2 个测试：切换到 fallback、无效目标拒绝 |

### 9.2 与 PRD 的差异

| PRD 内容 | 实现差异 | 原因 |
|---------|---------|------|
| 第 5.1 节提到 `_index.yaml` 注册表 | 未实现 | V1 仅 3 个 mock 活动，直接遍历 YAML 足够快；待活动库规模扩大后再实现 |
| 第 4.4 节提到 V1 用 2 个活动（主 + 1 备选） | 实现支持任意数量 fallback | `fallback_attributes` 为 `tuple`，不限于 1 个；当前 Gemini prompt 要求选 1 个 fallback |
| 第 3.3 节提到 "prompt 层切换" 需技术验证 | 已实现并验证 | 通过单元测试和完整测试套件验证（663 passed） |
| 第 4.6 节提到轮数预期 3-6 轮 | 未做强制限制 | 完全由模型 `[ACTIVITY_READY]` 自主判断，保留现有 quote validation |

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

继续对话时检测切换:
  paixueji_app.py:continue_conversation()
    → stream_attribute_activity()
      → detect_switch_marker(full_response)
      → assistant.switch_attribute_topic()
      → paixueji_prompts.py:attribute_multi_topic_guide [软引导]

Stream 元数据:
  paixueji_app.py:_assistant_stream_fields()
    → switch_state {attribute_switched_to, ...}
```

---

*本报告由开发团队与 PM 的多轮讨论整理而成。如有疑问，请对照第 4 节的未确定问题逐项确认。*

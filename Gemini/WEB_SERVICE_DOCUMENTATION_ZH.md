# 儿童学习助手 - Web 服务文档

## 概述

儿童学习助手为幼儿（3-8岁）提供**网页界面**和 **REST API**，用于互动式教育对话。该系统使用 AI 提出适合年龄的问题，鼓励孩子对日常物品产生好奇心和学习兴趣。

## 我们提供什么

### 1. 🌐 网页界面（交互式演示）

**网址：** `http://localhost:5001`

一个美观、用户友好的 Web 应用程序，功能包括：
- ✅ 启动任何物品的学习会话
- ✅ 适龄提问（3-8岁）
- ✅ 基于类别的提示（食物、动物、植物）
- ✅ 与 AI 实时对话
- ✅ 进度跟踪（掌握系统）
- ✅ 视觉反馈和动画

**特点：**
- 响应式设计（支持移动端和桌面端）
- 无需登录
- 基于会话的对话
- 显示正确答案数量的进度条
- 达成掌握时的庆祝动画

### 2. 📡 REST API

**基础网址：** `http://localhost:5001/api`

用于构建自定义应用程序的 RESTful API：
- ✅ 启动新的学习会话
- ✅ 继续对话
- ✅ 检索对话历史
- ✅ 管理会话（列出、重置、删除）
- ✅ 健康监控

**身份验证：** 无需（开发模式）

## 快速开始

### 启动服务器

```bash
# 导航到项目目录
cd C:\Users\123\PycharmProjects\AI_ask_ask\Gemini

# 启动服务器
python app.py
```

**输出：**
```
============================================================
Child Learning Assistant - Flask Web Service (Gemini)
============================================================

🌐 Web Interface:
  http://localhost:5001

📡 API Endpoints:
  POST   /api/classify   - 将物品分类到类别
  POST   /api/start      - 启动新对话
  POST   /api/continue   - 继续对话
  GET    /api/history/<session_id> - 获取历史记录
  POST   /api/reset      - 重置会话
  GET    /api/sessions   - 列出活动会话
  GET    /api/health     - 健康检查

============================================================
🚀 Server starting on http://localhost:5001
   Open your browser and visit the URL above!
============================================================
```

### 访问网页界面

1. 打开浏览器
2. 导航到 `http://localhost:5001`
3. 填写表单：
   - **物品名称：** 例如 "香蕉"
   - **孩子年龄：** 3-8岁（可选）
   - **二级类别：** 例如 "fresh_ingredients"（可选）
   - **三级类别：** 例如 "水果"（可选）
4. 点击 "开始学习！"
5. 与 AI 助手聊天

## 网页界面指南

### 启动会话

**步骤 1：填写表单**

![表单字段]
- **物品名称**（必填）：要学习的物品
  - **自动分类：** 当您从此字段按 Tab 键离开时，AI 会自动推荐类别！
  - 显示："💡 我们认为'苹果'属于'新鲜食材'类别"
  - 您可以接受建议或输入自己的类别
- **年龄**（可选）：孩子的年龄（3-8岁），用于适龄提问
  - 3-4岁："什么"问题（颜色、形状、声音）
  - 5-6岁："什么"和"怎么"问题（过程、行为）
  - 7-8岁："什么"、"怎么"和"为什么"问题（推理、原因）
- **二级类别**（可选）：从可用类别中选择
  - 食物：`fresh_ingredients`（新鲜食材）、`processed_foods`（加工食品）、`beverages_drinks`（饮料）
  - 动物：`vertebrates`（脊椎动物）、`invertebrates`（无脊椎动物）、`human_raised_animals`（人工饲养动物）
  - 植物：`ornamental_plants`（观赏植物）、`useful_plants`（实用植物）、`wild_natural_plants`（野生植物）
  - **注意：** 如果您接受 AI 建议，此字段会自动填充
- **三级类别**（可选）：仅用于显示

**步骤 2：聊天**
- AI 会询问关于物品的问题
- 在输入框中输入答案
- 按回车键或点击"发送"
- AI 提供反馈并询问后续问题

**步骤 3：掌握主题**
- 正确回答 4 个问题即可达成掌握
- 进度条显示您的进展
- 达成掌握时播放庆祝动画！

### 功能

**进度跟踪**
- 可视化进度条（0/4 到 4/4）
- 正确答案显示绿色对勾 ✅
- 错误答案显示红色叉 ❌

**智能提示系统**
- 说"我不知道"可获得提示
- 第一个提示：提出一个不同的、更简单的问题，答案相同
- 第二个提示：提出一个更简单的问题
- 回答提示后：**重新连接回原始问题**
- 第三次"我不知道"：揭示答案
- **示例流程：**
  1. "为什么洋葱有很多层？" → "我不知道"
  2. 提示："为什么我们要煮洋葱？" → "因为很好吃"
  3. 重新连接："对！那些层储存了所有的味道。那么你认为层层怎么帮助洋葱？"
  4. 孩子回答原始问题 ✅

**掌握成就**
- 4 个正确答案触发掌握
- 出现庆祝横幅
- 会话自动结束
- 可以立即开始新会话

## API 参考

### 基本信息

- **基础网址：** `http://localhost:5001/api`
- **Content-Type：** `application/json`
- **响应格式：** JSON

### 端点

#### 1. 健康检查

**GET /api/health**

检查服务是否正在运行。

**响应：**
```json
{
  "status": "healthy",
  "service": "Child Learning Assistant (Gemini)",
  "version": "1.0"
}
```

---

#### 2. 物品分类

**POST /api/classify**

使用 AI 自动将物品分类到二级类别。

**请求体：**
```json
{
  "object_name": "苹果"  // 必填：要分类的物品
}
```

**响应（成功）：**
```json
{
  "success": true,
  "object_name": "苹果",
  "recommended_category": "fresh_ingredients",
  "category_display": "Fresh Ingredients",
  "level1_category": "Foods"
}
```

**响应（无法分类）：**
```json
{
  "success": true,
  "object_name": "电脑",
  "recommended_category": null,
  "message": "Could not classify object into any category"
}
```

**使用场景：**
- 自动向用户推荐类别
- 预填充表单中的类别字段
- 验证物品-类别关系
- **注意：** 最终类别选择始终由用户决定；这只是一个建议

**支持的类别：**
- 食物：`fresh_ingredients`、`processed_foods`、`beverages_drinks`
- 动物：`vertebrates`、`invertebrates`、`human_raised_animals`
- 植物：`ornamental_plants`、`useful_plants`、`wild_natural_plants`

---

#### 3. 启动对话

**POST /api/start**

启动关于某个物品的新学习会话。

**请求体：**
```json
{
  "object_name": "香蕉",         // 必填：要学习的物品
  "category": "水果",            // 必填：用于显示的类别名称
  "age": 6,                      // 可选：孩子的年龄（3-8）
  "level2_category": "fresh_ingredients",  // 可选：二级类别
  "level3_category": "水果"       // 可选：三级类别（仅用于显示）
}
```

**响应：**
```json
{
  "success": true,
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "response": "🍌 哇！香蕉太神奇了！你认为为什么香蕉会成串生长？",
  "object": "香蕉",
  "category": "水果"
}
```

**重要提示：**
- 保存 `session_id` 以继续对话
- `level1_category` 会从 `level2_category` 自动检测
- 年龄决定问题的复杂度

---

#### 4. 继续对话

**POST /api/continue**

用孩子的回答继续现有对话。

**请求体：**
```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",  // 必填
  "child_response": "它们在树上一起生长"                   // 必填
}
```

**响应：**
```json
{
  "success": true,
  "response": "✅ 对！太棒了！香蕉确实会成串生长！这叫做一'手'香蕉！🍌 你认为它们为什么要成串生长而不是单独生长？",
  "audio_output": "对！太棒了！香蕉确实会成串生长！这叫做一'手'香蕉！你认为它们为什么要成串生长而不是单独生长？",
  "mastery_achieved": false,
  "correct_count": 1,
  "is_correct": true,
  "is_neutral": false
}
```

**响应字段：**
- `response`：带表情符号的完整响应（用于显示）
- `audio_output`：不带表情符号的清洁文本（用于文本转语音）
- `mastery_achieved`：如果孩子正确回答了 4 个问题则为 true
- `correct_count`：到目前为止的正确答案数量
- `is_correct`：此答案是否正确
- `is_neutral`：提示/揭示时为 true（无表情符号前缀）

**掌握响应：**
当 `mastery_achieved: true` 时，会话会自动删除。

---

#### 5. 获取对话历史

**GET /api/history/:session_id**

检索会话的完整对话历史。

**示例：**
```
GET /api/history/550e8400-e29b-41d4-a716-446655440000
```

**响应：**
```json
{
  "success": true,
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "object": "香蕉",
  "category": "水果",
  "history": [
    {
      "role": "system",
      "content": "你是一个有趣的学习伙伴..."
    },
    {
      "role": "user",
      "content": "孩子想了解：香蕉..."
    },
    {
      "role": "assistant",
      "content": "🍌 哇！香蕉太神奇了！..."
    },
    {
      "role": "user",
      "content": "它们在树上一起生长"
    },
    {
      "role": "assistant",
      "content": "对！太棒了！香蕉确实会成串生长..."
    }
  ]
}
```

---

#### 6. 重置会话

**POST /api/reset**

删除会话以释放资源。

**请求体：**
```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

**响应：**
```json
{
  "success": true,
  "message": "Session reset successfully"
}
```

---

#### 7. 列出会话

**GET /api/sessions**

列出所有活动会话（用于监控/调试）。

**响应：**
```json
{
  "success": true,
  "active_sessions": 3,
  "sessions": [
    {
      "session_id": "550e8400-e29b-41d4-a716-446655440000",
      "object": "香蕉",
      "category": "水果"
    },
    {
      "session_id": "660e8400-e29b-41d4-a716-446655440001",
      "object": "狗",
      "category": "哺乳动物"
    }
  ]
}
```

---

## 错误处理

### 错误响应格式

```json
{
  "success": false,
  "error": "描述问题的错误消息"
}
```

### 常见错误代码

- **400 Bad Request：** 缺少必需参数或输入无效
- **404 Not Found：** 会话未找到或已过期
- **500 Internal Server Error：** 服务器端错误（检查日志）

### 错误示例

**缺少参数：**
```json
{
  "success": false,
  "error": "Both object_name and category are required"
}
```

**无效会话：**
```json
{
  "success": false,
  "error": "Invalid or expired session_id"
}
```

---

## 高级功能

### 适龄提问

系统会根据年龄自动调整问题复杂度：

**3-4岁：** 简单的"什么"问题
```
"香蕉是什么颜色？"
"它是什么形状？"
```

**5-6岁：** "什么"和"怎么"问题
```
"香蕉是怎么长出来的？"
"当你剥皮时会发生什么？"
```

**7-8岁：** "什么"、"怎么"和"为什么"问题
```
"为什么香蕉会变黄？"
"为什么它们会成串生长？"
```

### 基于类别的提示

类别影响提出的问题类型：

**fresh_ingredients（新鲜食材）：**
- 关注农场/花园起源
- 自然气味和质地
- 健康营养

**vertebrates（脊椎动物）：**
- 强调脊柱和骨骼
- 运动能力
- 温血/冷血

**ornamental_plants（观赏植物）：**
- 关注美丽（花朵、颜色）
- 在花盆/花园中生长
- 让人快乐

### 掌握系统

**工作原理：**
1. 系统跟踪正确答案
2. 阈值：4 个正确答案
3. 达到阈值时：
   - 响应中 `mastery_achieved: true`
   - 显示庆祝消息
   - 会话自动删除
4. 用户可以开始新会话

**进度跟踪：**
- 每个 `/api/continue` 响应都包含 `correct_count`
- 网页界面显示进度条
- 正确/错误答案的视觉反馈

---

## 技术细节与最近改进

### 状态机架构

系统使用智能状态机进行对话流程：

**状态：**
- `INITIAL_QUESTION`：提出第一个问题
- `AWAITING_ANSWER`：等待孩子的回答
- `GIVING_HINT_1`：第一个提示（更简单的问题）
- `GIVING_HINT_2`：第二个提示（更更简单的问题）
- `RECONNECTING`：将提示答案桥接回原始问题
- `REVEALING_ANSWER`：3 次"我不知道"后揭示答案
- `CELEBRATING`：积极强化，然后下一个问题
- `MASTERY_ACHIEVED`：达到 4 个正确答案

**关键特性：**
- **级联转换：** 状态自动级联（例如，如果孩子说"我不知道"，`CELEBRATING` → `AWAITING_ANSWER` → `GIVING_HINT_1`）
- **问题跟踪：** 在提示前保存原始问题以进行重新连接
- **会话持久化：** 所有状态都保存到数据库中，跨请求保持

### 数据库架构

**会话表字段：**
- `id`：唯一会话标识符
- `current_object`：正在学习的物品
- `current_category`：类别名称
- `conversation_history`：完整消息历史（JSON）
- `state`：当前状态机状态
- `stuck_count`："我不知道"响应的数量
- `question_count`：到目前为止提出的问题
- `correct_count`：正确答案（用于掌握跟踪）
- `current_main_question`：当前正在询问的问题
- `expected_answer`：当前问题的预期答案
- `question_before_hint`：原始问题（提示前）
- `answer_before_hint`：原始问题的预期答案
- `last_modified`：时间戳

**为什么这些字段很重要：**
- `current_main_question` 和 `expected_answer`：启用提示生成
- `question_before_hint` 和 `answer_before_hint`：启用提示重新连接
- 所有字段跨请求持久化，实现无缝多轮对话

### 响应令牌处理

**Gemini 模型在生成可见输出之前使用内部"推理令牌"**。为了防止截断：

- **标准响应：** `max_tokens=2000`
- **提示：** `max_tokens=2000`（之前是 1000，导致截断）
- **揭示：** `max_tokens=2000`
- **重新连接：** `max_tokens=2000`
- **分类：** `max_tokens=200`（简单任务）

这确保了完整的响应，不会在句子中间截断。

### 最近的 Bug 修复（2025年12月）

**1. 提示重新连接系统**
- **问题：** 回答提示问题后，系统会提出一个新问题，而不是返回原始问题
- **修复：** 添加了 `RECONNECTING` 状态，将提示答案桥接回原始问题
- **结果：** 教学上合理 - 孩子现在完成原始学习目标

**2. 会话持久化**
- **问题：** `current_main_question` 和 `expected_answer` 未保存到数据库
- **修复：** 在数据库架构中添加字段 + 保存/加载逻辑
- **结果：** 提示在 Web 请求中正确工作

**3. 状态级联**
- **问题：** 从 `CELEBRATING` 状态说"我不知道"会触发 JSON 解析错误
- **修复：** 移动了 `CELEBRATING` 和 `RECONNECTING` 以正确级联
- **结果：** 从任何状态到提示的平滑转换

**4. 响应截断**
- **问题：** 由于 max_tokens 限制，提示在句子中间被截断
- **修复：** 将 `max_tokens` 从 1000 增加到 2000
- **结果：** 完整、连贯的响应

**5. None 处理**
- **问题：** 当 `current_main_question` 为 None 时出现 TypeError（安全字符串切片）
- **修复：** 添加了 null 检查和后备值
- **结果：** 健壮的错误处理

---

## 开发指南

### 项目结构

```
Gemini/
├── app.py                    # Flask 服务器 + API + Web 界面
├── child_learning_assistant.py  # 核心 AI 逻辑
├── prompts.py                # 硬编码提示
├── database.py               # 会话存储
├── age_prompts.json          # 基于年龄的提示
├── category_prompts.json     # 基于类别的提示
├── object_classifier.py      # AI 物品分类器
├── static/
│   ├── index.html            # Web 界面
│   └── app.js                # JavaScript 前端
└── sessions.db               # SQLite 数据库（自动创建）
```

### 生产环境运行

**用于生产部署：**

1. **禁用调试模式：**
   ```python
   app.run(debug=False, host='0.0.0.0', port=5001)
   ```

2. **使用生产服务器：**
   ```bash
   pip install gunicorn
   gunicorn -w 4 -b 0.0.0.0:5001 app:app
   ```

3. **添加身份验证**（如果需要）

4. **设置 HTTPS**（如果需要）

5. **为特定域配置 CORS**

### 自定义

**添加新类别：**
编辑 `category_prompts.json`：
```json
{
  "level2_categories": {
    "your_new_category": {
      "prompt": "您的自定义提示...",
      "parent": "level1_category"
    }
  }
}
```

**修改提示：**
编辑 `prompts.py` 以更改：
- 系统个性
- 问题风格
- 提示策略
- 庆祝消息

**更改掌握阈值：**
在 `child_learning_assistant.py` 中：
```python
self.mastery_threshold = 4  # 更改为所需数量
```

---

## 故障排除

### 服务器无法启动

**错误：** `Address already in use`

**解决方案：** 端口 5001 已被占用
```bash
# 查找使用端口 5001 的进程
netstat -ano | findstr :5001

# 终止进程或在 app.py 中更改端口
app.run(debug=True, host='0.0.0.0', port=5002)
```

### Web 界面无法加载

**检查：**
1. 服务器正在运行（`python app.py`）
2. 访问正确的 URL（`http://localhost:5001`）
3. `static/` 文件夹存在且包含 `index.html` 和 `app.js`

### API 返回 500 错误

**检查：**
1. 服务器日志中的错误消息
2. `config.json` 有有效的 API 密钥
3. 数据库可写（`sessions.db`）

### 会话未持久化

**检查：**
1. `sessions.db` 文件存在且可写
2. 服务器日志中没有数据库错误
3. 会话 ID 被正确存储和传递

---

## 支持

如有问题或疑问：
1. 检查服务器日志中的错误消息
2. 验证所有必需文件是否存在
3. 确保在 `config.json` 中配置了 API 密钥
4. 查看本文档

## 摘要

✅ **我们提供什么：**
- 用于互动学习的美观 Web 界面
- 用于自定义集成的 REST API
- **AI 驱动的物品分类**（自动类别建议）
- 适龄提问（3-8 岁）
- 基于类别的提示
- **智能提示系统与重新连接**（教学上合理）
- 具有完整状态持久化的会话管理
- 进度跟踪和掌握系统

✅ **您可以做什么：**
- 直接使用带自动分类的 Web 界面
- 使用 API 构建自定义应用程序
- 与移动应用集成
- 创建教育平台
- 监控和管理会话
- 自定义提示和类别

✅ **我们需要什么：**
- `config.json` 中的 Gemini API 密钥
- Python 3.7+ 和所需包
- 端口 5001 可用（或自定义）

✅ **最近的改进：**
- 提示重新连接系统（2025年12月）
- 用于问题跟踪的会话持久化
- 状态级联修复
- 响应截断修复
- 自动物品分类

就是这样！您已准备好使用儿童学习助手！🎉

# 暴露属性管道 Handoff 决策与 Verification 状态到前端

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在前端 debug panel 和 report 中暴露属性管道的 CARES handoff 决策（continue/probe/handoff_now 等）以及 verification queue 状态摘要（verified/pending/rejected 计数）。

**Architecture:** 数据已存在于 SSE 的 `attribute_debug` 嵌套对象中，只需前端渲染 + report 的 turn summary 补充。零后端 schema 改动，零 SSE 协议改动。

**Tech Stack:** Flask + vanilla JS + markdown report generation

---

## File Structure

| File | Responsibility |
|------|---------------|
| `static/index.html` | Debug panel DOM：新增 3 个 `span` 元素用于展示 CARES Decision、CARES Reason、Verification Summary |
| `static/app.js` | Debug panel 渲染逻辑：`updateDebugPanel()` 中读取 `attributeDebug.cares_handoff_decision`、`cares_handoff_reason`、`state.verification_queue` 并写入 DOM |
| `paixueji_app.py` | Report Markdown 生成：`_render_turn_summary()` 和 `_build_report_diagnostics_appendix()` 中追加 verification queue 摘要和 CARES 信息 |
| `tests/test_hf_report_viewer.py` | 回归测试：验证 report Markdown 输出包含新增的 CARES Decision 和 Verification Summary 行 |

---

### Task 1: 前端 HTML — 添加 Debug DOM 元素

**Files:**
- Modify: `static/index.html:254`

在 "Attribute Debug" 区域的 Marker Reason 下方、Switch State 上方，插入 3 行 DOM：

- [ ] **Step 1: 插入 DOM 元素**

```html
                <div style="font-size: 0.85em; color: #64748b;">CARES Decision: <span id="debugCaresDecision">-</span></div>
                <div style="font-size: 0.85em; color: #64748b;">CARES Reason: <span id="debugCaresReason">-</span></div>
                <div style="font-size: 0.85em; color: #64748b;">Verification: <span id="debugVerificationSummary">-</span></div>
```

插入位置为 `debugActivityMarkerReason` 的 `</div>` 之后、`</div>`（Attribute Debug 区域闭合）之前。

- [ ] **Step 2: 验证 DOM 存在**

Run:
```bash
python -c "print('debugCaresDecision' in open('static/index.html', encoding='utf-8').read())"
```

Expected: `True`

Run:
```bash
python -c "print('debugVerificationSummary' in open('static/index.html', encoding='utf-8').read())"
```

Expected: `True`

- [ ] **Step 3: Commit**

```bash
git add static/index.html
git commit -m "feat: add CARES decision and verification debug DOM elements"
```

---

### Task 2: 前端 JS — updateDebugPanel 渲染新字段

**Files:**
- Modify: `static/app.js:1394-1398`

- [ ] **Step 1: 插入渲染逻辑**

在 `setText('debugActivityMarkerReason', attributeDebug.activity_marker_reason);` 之后、`setText('debugSwitchedTo', currentAttributeSwitchedTo || '-');` 之前，插入：

```javascript
    setText('debugCaresDecision', attributeDebug.cares_handoff_decision || '-');
    setText('debugCaresReason', attributeDebug.cares_handoff_reason || '-');
    const vq = (attributeDebug.state || {}).verification_queue || [];
    if (vq.length > 0) {
        const verified = vq.filter(v => v.status === 'verified').length;
        const pending = vq.filter(v => v.status === 'pending').length;
        const rejected = vq.filter(v => v.status === 'rejected').length;
        setText('debugVerificationSummary', `${verified}✓ / ${pending}⏳ / ${rejected}✗`);
    } else {
        setText('debugVerificationSummary', '-');
    }
```

- [ ] **Step 2: 验证代码存在**

Run:
```bash
python -c "js = open('static/app.js', encoding='utf-8').read(); print('debugCaresDecision' in js and 'verification_queue' in js)"
```

Expected: `True`

- [ ] **Step 3: Commit**

```bash
git add static/app.js
git commit -m "feat: render CARES decision and verification summary in debug panel"
```

---

### Task 3: Report Turn Summary — 添加 Verification Queue 摘要

**Files:**
- Modify: `paixueji_app.py:4885-4886`
- Test: `tests/test_hf_report_viewer.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_hf_report_viewer.py` 末尾添加：

```python
def test_render_turn_summary_includes_cares_and_verification():
    from paixueji_app import _render_turn_summary

    attribute_debug = {
        "cares_handoff_decision": "continue",
        "cares_handoff_reason": "building:45",
        "interest_score_current": 45.0,
        "interest_score_best": 68.0,
        "state": {
            "verification_queue": [
                {"property": "颜色", "status": "verified", "question": "它是什么颜色？"},
                {"property": "形状", "status": "pending", "question": "它是什么形状？"},
                {"property": "大小", "status": "rejected", "question": "它有多大？"},
            ]
        },
    }

    result = _render_turn_summary(
        bridge_debug=None,
        attribute_debug=attribute_debug,
        category_debug=None,
    )

    assert "CARES Decision: `continue`" in result
    assert "CARES Reason: `building:45`" in result
    assert "Interest Score (current): `45.0`" in result
    assert "Interest Score (best): `68.0`" in result
    assert "Verification Queue: `1✓ / 1⏳ / 1✗`" in result
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_hf_report_viewer.py::test_render_turn_summary_includes_cares_and_verification -v`

Expected: `AssertionError` — `"Verification Queue: \`1✓ / 1⏳ / 1✗\`` not in result`

- [ ] **Step 3: 实现修改**

在 `paixueji_app.py` 的 `_render_turn_summary` 函数中，在 `interest_score_best` 行（4885行）之后、
`if category_debug:` 之前，插入：

```python
        verification_queue = (attribute_debug.get("state") or {}).get("verification_queue", [])
        if verification_queue:
            pending = sum(1 for v in verification_queue if v.get("status") == "pending")
            verified = sum(1 for v in verification_queue if v.get("status") == "verified")
            rejected = sum(1 for v in verification_queue if v.get("status") == "rejected")
            lines.append(f"- Verification Queue: `{verified}✓ / {pending}⏳ / {rejected}✗`\n")
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_hf_report_viewer.py::test_render_turn_summary_includes_cares_and_verification -v`

Expected: `PASSED`

- [ ] **Step 5: Commit**

```bash
git add paixueji_app.py tests/test_hf_report_viewer.py
git commit -m "feat: include verification queue summary in report turn summary"
```

---

### Task 4: Report Diagnostics Appendix — 添加 CARES + Verification

**Files:**
- Modify: `paixueji_app.py:5021-5039`
- Test: `tests/test_hf_report_viewer.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_hf_report_viewer.py` 末尾添加：

```python
def test_diagnostics_appendix_includes_cares_and_verification():
    from paixueji_app import _build_report_diagnostics_appendix

    attribute_debug = {
        "cares_handoff_decision": "handoff_now",
        "cares_handoff_reason": "primary_activity:72",
        "interest_score_current": 72.0,
        "interest_score_best": 72.0,
        "state": {
            "verification_queue": [
                {"property": "颜色", "status": "verified"},
                {"property": "形状", "status": "verified"},
                {"property": "触感", "status": "pending"},
            ]
        },
    }

    result = _build_report_diagnostics_appendix(
        exchange_index=1,
        source_label="attribute_activity",
        response_type="attribute_activity",
        bridge_debug={"decision": "attribute_activity"},
        attribute_debug=attribute_debug,
        category_debug=None,
        attribute_interest_records=None,
    )

    assert "**CARES Decision:** handoff_now" in result
    assert "**CARES Reason:** primary_activity:72" in result
    assert "**Interest Score (current):** 72.0" in result
    assert "**Interest Score (best):** 72.0" in result
    assert "**Verification Queue:** 2✓ / 1⏳ / 0✗" in result
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_hf_report_viewer.py::test_diagnostics_appendix_includes_cares_and_verification -v`

Expected: `AssertionError` — 找不到 CARES Decision 和 Verification Queue 行

- [ ] **Step 3: 实现修改**

在 `paixueji_app.py` 的 `_build_report_diagnostics_appendix` 函数中，在 attribute_summary 循环（5030行）之后、category_summary 循环（5031行）之前，插入：

```python
    cares_decision = attribute_debug.get("cares_handoff_decision")
    cares_reason = attribute_debug.get("cares_handoff_reason")
    interest_current = attribute_debug.get("interest_score_current")
    interest_best = attribute_debug.get("interest_score_best")
    if cares_decision:
        lines.append(f"**CARES Decision:** {cares_decision}\n")
    if cares_reason:
        lines.append(f"**CARES Reason:** {cares_reason}\n")
    if interest_current is not None:
        lines.append(f"**Interest Score (current):** {interest_current:.1f}\n")
    if interest_best is not None:
        lines.append(f"**Interest Score (best):** {interest_best:.1f}\n")
    verification_queue = (attribute_debug.get("state") or {}).get("verification_queue", [])
    if verification_queue:
        pending = sum(1 for v in verification_queue if v.get("status") == "pending")
        verified = sum(1 for v in verification_queue if v.get("status") == "verified")
        rejected = sum(1 for v in verification_queue if v.get("status") == "rejected")
        lines.append(f"**Verification Queue:** {verified}✓ / {pending}⏳ / {rejected}✗\n")
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_hf_report_viewer.py::test_diagnostics_appendix_includes_cares_and_verification -v`

Expected: `PASSED`

- [ ] **Step 5: Commit**

```bash
git add paixueji_app.py tests/test_hf_report_viewer.py
git commit -m "feat: include CARES decision and verification summary in report diagnostics appendix"
```

---

### Task 5: 端到端验证

- [ ] **Step 1: 运行完整测试套件**

Run: `pytest tests/ -v`

Expected: 所有测试通过（包括新增的两个 + 所有现有测试）

- [ ] **Step 2: 启动应用验证前端渲染**

Run: `python paixueji_app.py`

在浏览器中打开 `http://localhost:5000`，发起一个属性管道对话。观察 debug panel 的 "Attribute Debug" 区域，确认：
- CARES Decision 显示具体值（如 `continue`、`probe`、`handoff_now`）
- CARES Reason 显示理由（如 `building:45`）
- Verification 显示计数（如 `1✓ / 2⏳ / 0✗`）

- [ ] **Step 3: 验证 report 生成**

完成一轮对话后提交 critique，下载 report markdown。确认：
- Turn Summary 中包含 `Verification Queue: X✓ / Y⏳ / Z✗`
- Diagnostics Appendix 中包含 `**CARES Decision:**` 和 `**Verification Queue:**`

- [ ] **Step 4: Commit**

```bash
git commit --allow-empty -m "test: verify end-to-end exposure of handoff decisions and verification status"
```

---

## Self-Review

### 1. Spec Coverage

| 需求 | 覆盖任务 |
|------|---------|
| 前端能看到 HANDOFF_NOW/PROBE/CONTINUE | Task 1 + Task 2 (`debugCaresDecision`) |
| 前端能确认 verify 状态 | Task 1 + Task 2 (`debugVerificationSummary`) |
| report 中能看到 CARES decision | Task 3 + Task 4 |
| report 中能看到 verification 状态 | Task 3 + Task 4 |

无遗漏。

### 2. Placeholder Scan

- 无 "TBD" / "TODO" / "implement later"
- 无 "Add appropriate error handling"
- 所有代码块包含完整可运行的代码
- 所有命令包含预期输出

### 3. Type Consistency

- `attribute_debug` 字段名一致：`cares_handoff_decision`、`cares_handoff_reason`、`state.verification_queue`
- report 中的 markdown 格式一致：turn summary 用 `- Label: \`value\``，appendix 用 `**Label:** value`
- 前端 summary 格式一致：`{verified}✓ / {pending}⏳ / {rejected}✗`

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-05-22-expose-handoff-verify-to-frontend.md`.**

**Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**

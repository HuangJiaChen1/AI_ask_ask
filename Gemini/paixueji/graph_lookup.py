from __future__ import annotations

import os
import random
from functools import lru_cache
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple


_THEME_ID_TO_NAME: dict = {
    "how_world_works":  "How the World Works",
    "sharing_planet":   "Sharing the Planet",
    "who_we_are":       "Who We Are",
    "how_we_express":   "How We Express Ourselves",
    "how_we_organize":  "How We Organize Ourselves",
    "where_place_time": "Where We Are in Place and Time",
}

_MODALITY_DISPLAY: dict = {
    "visual":       "Visual",
    "tactile":      "Touch",
    "kinesthetic":  "Movement",
    "auditory":     "Sound",
    "structural":   "Structure",
    "spatial":      "Space",
    "relational":   "Relational",
    "temporal":     "Time",
    "emotional":    "Feeling",
    "evaluative":   "Values",
}


def _age_to_tier(age: int) -> str:
    """Convert child age (3-8) to YAML tier key T0-T3."""
    if age <= 3:
        return "T0"
    if age == 4:
        return "T1"
    if age <= 6:
        return "T2"
    return "T3"


def _format_concept_anchors(concept: Dict[str, Any], object_name: str) -> str:
    """
    Format a YAML concept's topic_anchors into a structured prompt block.

    Input concept dict shape:
        {concept_id: str, topic_anchors: {modality: [{attribute, value}, ...]}}

    Output example:
        CONCEPT FOCUS: change
        OBSERVATION ANCHORS FOR SUNFLOWER:
        - Visual: Green bud opens into a big face.; Flower head dries and turns brown.
        - Movement: Small sprout grows taller each week.
    """
    concept_id = concept.get("concept_id", "")
    anchors = concept.get("topic_anchors") or {}
    lines = [
        f"CONCEPT FOCUS: {concept_id}",
        f"OBSERVATION ANCHORS FOR {object_name.upper()}:",
    ]
    for modality, entries in anchors.items():
        if not entries:
            continue
        display = _MODALITY_DISPLAY.get(modality, modality.capitalize())
        values = "; ".join(
            e.get("value", "") for e in entries if isinstance(e, dict) and e.get("value")
        )
        if values:
            lines.append(f"- {display}: {values}")
    if len(lines) == 2:
        # No anchors at all — add a generic fallback line
        lines.append(f"- Explore what {object_name} does and how it works.")
    return "\n".join(lines)


# 相对于当前文件定位 mappings_dev20，
DEFAULT_MAPPINGS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "mappings_dev20"
)


@dataclass(frozen=True)
class _TierConceptMatch:
    entity_id: str
    entity_name: str
    entity_name_cn: str
    tier_key: str
    concept_id: str
    relevance: float
    concept_data: Dict[str, Any]


def _norm(s: str) -> str:
    return (s or "").strip().lower()


def _collect_yaml_files(base_dir: str) -> List[str]:
    paths: List[str] = []
    for root, _dirs, files in os.walk(base_dir):
        for fn in files:
            low = fn.lower()
            if low.endswith(".yaml") or low.endswith(".yml"):
                paths.append(os.path.join(root, fn))
    paths.sort()
    return paths


def _load_yaml(text: str) -> Any:
    """
    依赖 PyYAML（yaml.safe_load）。若环境未安装，则抛出 ImportError。
    """
    import yaml  # type: ignore

    return yaml.safe_load(text)


def _load_entities_from_mappings_folder(base_dir: str) -> List[Dict[str, Any]]:
    """
    遍历 base_dir 下所有 yaml/yml 文件，加载并合并成 entities 列表。
    约定：每个 YAML 文件顶层是一个 list，元素为 dict（entity）。
    """
    entities: List[Dict[str, Any]] = []
    yaml_files = _collect_yaml_files(base_dir)
    if not yaml_files:
        return []

    for p in yaml_files:
        try:
            with open(p, "r", encoding="utf-8") as f:
                txt = f.read()
        except OSError:
            continue

        try:
            data = _load_yaml(txt)
        except ImportError as e:
            raise ImportError(
                "当前 Python 环境未安装 PyYAML，无法解析 .yaml/.yml。请先安装：pip install pyyaml"
            ) from e
        except Exception:
            continue

        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    entities.append(item)

    return entities


def _entity_matches_query(entity: Dict[str, Any], query: str) -> bool:
    q = _norm(query)
    if not q:
        return False

    hay = [
        entity.get("entity_id", ""),
        entity.get("entity_name", ""),
        entity.get("entity_name_cn", ""),
    ]
    return any(q == _norm(v) for v in hay)


def _iter_tier_concepts(
    entity: Dict[str, Any], only_tier_key: Optional[str] = None
) -> Iterable[Tuple[str, Dict[str, Any]]]:
    tg = entity.get("tier_guidance") or {}
    if not isinstance(tg, dict):
        return

    for tier_key, tier_data in tg.items():
        if only_tier_key is not None and str(tier_key) != str(only_tier_key):
            continue
        if not isinstance(tier_data, dict):
            continue
        concepts = tier_data.get("available_concepts") or []
        if not isinstance(concepts, list):
            continue
        for c in concepts:
            if isinstance(c, dict):
                yield str(tier_key), c


def _best_tier_concepts_for_entity_at_tier(
    entity: Dict[str, Any], tier_key_filter: str
) -> List[_TierConceptMatch]:
    candidates: List[_TierConceptMatch] = []

    for tier_key, c in _iter_tier_concepts(entity, only_tier_key=tier_key_filter):
        concept_id = c.get("concept_id")
        if not concept_id:
            continue

        rel = c.get("relevance", 0)
        try:
            rel_f = float(rel or 0)
        except (TypeError, ValueError):
            rel_f = 0.0

        candidates.append(
            _TierConceptMatch(
                entity_id=str(entity.get("entity_id", "") or ""),
                entity_name=str(entity.get("entity_name", "") or ""),
                entity_name_cn=str(entity.get("entity_name_cn", "") or ""),
                tier_key=tier_key,
                concept_id=str(concept_id),
                relevance=rel_f,
                concept_data=dict(c),
            )
        )

    if not candidates:
        return []

    max_rel = max(c.relevance for c in candidates)
    return [c for c in candidates if c.relevance == max_rel]


def _normalize_age_tier_to_key(age_tier: str) -> Optional[str]:
    """
    将用户输入的 Age Tier 映射到 YAML 里的 tier_key：
    - T0/T1/T2/T3
    - 0/1/2/3
    - tier_0..tier_3
    """
    s = _norm(age_tier)
    if not s:
        return None

    if s in {"t0", "0"}:
        return "tier_0"
    if s in {"t1", "1"}:
        return "tier_1"
    if s in {"t2", "2"}:
        return "tier_2"
    if s in {"t3", "3"}:
        return "tier_3"
    if s in {"tier_0", "tier_1", "tier_2", "tier_3"}:
        return s
    return None


def _search_best_matches_from_entities(
    entities: List[Dict[str, Any]], query: str, tier_key: str
) -> List[_TierConceptMatch]:
    if not entities:
        return []

    matched = [e for e in entities if isinstance(e, dict) and _entity_matches_query(e, query)]
    if not matched:
        return []

    results: List[_TierConceptMatch] = []
    for e in matched:
        results.extend(_best_tier_concepts_for_entity_at_tier(e, tier_key))
    return results


@lru_cache(maxsize=1)
def _cached_entities(base_dir: str) -> List[Dict[str, Any]]:
    # 读取并缓存 mappings_dev20 下所有 YAML 的实体数据
    return _load_entities_from_mappings_folder(base_dir)


def lookup_top_available_concepts(query: str, age_tier: str) -> Dict[str, Any]:
    """
    输入：
    - query：entity_id / 英文名 / 中文名（子串匹配，不区分大小写）
    - age_tier：T0/T1/T2/T3 或 0/1/2/3（或 tier_0..tier_3）

    输出：
    - 包含以下内容的 dict：
        {
            "success": true/false,
            "entity": {
                "entity_id": "...",
                "entity_name": "...",
                "entity_name_cn": "..."
            },
            "themes": {
                "theme_id1": {...},
                "theme_id2": {...}
            },
            "available_concepts": [...]
        }
    - 未检索到则返回 {"success": false, "error": "..."}
    """
    tier_key = _normalize_age_tier_to_key(age_tier)
    if tier_key is None:
        return {
            "success": False,
            "error": "Age Tier 无效：请使用 T0/T1/T2/T3 或 0/1/2/3（或 tier_0..tier_3）"
        }

    entities = _cached_entities(DEFAULT_MAPPINGS_DIR)
    if not entities:
        return {"success": False, "error": "未找到实体数据"}

    # 先得到“每个命中 Entity 在指定 Tier 下的最大 rel”（可能多个概念并列最大）
    results = _search_best_matches_from_entities(entities, query, tier_key)
    if not results:
        return {"success": False, "error": "未找到匹配的概念"}

    # 获取匹配到的实体
    matched_entity_ids = list({r.entity_id for r in results})
    matched_entity = None
    for e in entities:
        if e.get("entity_id") in matched_entity_ids:
            matched_entity = e
            break

    if not matched_entity:
        return {"success": False, "error": "未找到匹配的实体"}

    # 整理 themes（按 theme_id）
    themes: Dict[str, Any] = {}
    primary_theme = matched_entity.get("primary_theme")
    if primary_theme and isinstance(primary_theme, dict):
        theme_id = primary_theme.get("theme_id")
        if theme_id:
            themes[theme_id] = {
                "type": "primary",
                **primary_theme
            }
    
    secondary_themes = matched_entity.get("secondary_themes", [])
    if isinstance(secondary_themes, list):
        for theme in secondary_themes:
            if isinstance(theme, dict):
                theme_id = theme.get("theme_id")
                if theme_id:
                    themes[theme_id] = {
                        "type": "secondary",
                        **theme
                    }

    # 再取这些结果中的“全局最大 rel”，返回对应 Available Concepts（可能多个）
    max_rel = max(r.relevance for r in results)
    top_objects = [r.concept_data for r in results if r.relevance == max_rel]

    # 去重（按 concept_id）并保持稳定顺序
    seen = set()
    deduped_concepts: List[Dict[str, Any]] = []
    for obj in top_objects:
        cid = obj.get("concept_id")
        key = str(cid) if cid is not None else repr(obj)
        if key in seen:
            continue
        seen.add(key)
        deduped_concepts.append(obj)

    return {
        "success": True,
        "entity": {
            "entity_id": matched_entity.get("entity_id", ""),
            "entity_name": matched_entity.get("entity_name", ""),
            "entity_name_cn": matched_entity.get("entity_name_cn", "")
        },
        "themes": themes,
        "available_concepts": deduped_concepts
    }


# def format_concepts_output(result: Dict[str, Any]) -> str:
#     """
#     将 lookup_top_available_concepts 返回的结果格式化为便于阅读的键值对输出
    
#     输入：
#     - result: lookup_top_available_concepts 函数返回的结果
    
#     输出：
#     - 格式化后的字符串，便于阅读的键值对格式
#     """
#     if not result.get("success"):
#         return f"错误: {result.get('error', '未知错误')}"
    
#     output_lines = []
    
#     # 添加实体信息
#     output_lines.append("=" * 80)
#     output_lines.append("实体信息 (Entity Info)")
#     output_lines.append("=" * 80)
#     entity = result.get("entity", {})
#     output_lines.append(f"entity_id: {entity.get('entity_id', '')}")
#     output_lines.append(f"entity_name: {entity.get('entity_name', '')}")
#     output_lines.append(f"entity_name_cn: {entity.get('entity_name_cn', '')}")
#     output_lines.append("")
    
#     # 添加主题信息（所有主题）
#     output_lines.append("=" * 80)
#     output_lines.append("主题信息 (Themes Info)")
#     output_lines.append("=" * 80)
#     themes = result.get("themes", {})
#     for theme_id, theme_data in themes.items():
#         output_lines.append(f"\n[Theme: {theme_id}]")
#         for key, value in sorted(theme_data.items()):
#             if key == "theme_id":
#                 continue
#             output_lines.append(f"  {key}: {value}")
#     output_lines.append("")
    
#     # 添加概念信息
#     output_lines.append("=" * 80)
#     output_lines.append("可用概念 (Available Concepts)")
#     output_lines.append("=" * 80)
#     concepts = result.get("available_concepts", [])
#     for i, concept in enumerate(concepts, 1):
#         output_lines.append(f"\n[Concept {i}]")
#         for key, value in sorted(concept.items()):
#             output_lines.append(f"  {key}: {value}")
    
#     return "\n".join(output_lines)


# def random_theme_and_concepts_output(result: Dict[str, Any]) -> str:
#     """
#     1. 提取并排列输出一个或多个全局最大 rel 的 Available Concepts
#     2. 随机选择一个 theme_id 并输出该 theme 的全部内容
#     3. 输出格式为便于阅读的键值对
    
#     输入：
#     - result: lookup_top_available_concepts 函数返回的结果
    
#     输出：
#     - 格式化后的字符串
#     """
#     if not result.get("success"):
#         return f"错误: {result.get('error', '未知错误')}"
    
#     output_lines = []
    
#     # 第1部分：提取并排列输出 Available Concepts
#     output_lines.append("=" * 80)
#     output_lines.append("📊 可用概念 (Available Concepts)")
#     output_lines.append("=" * 80)
#     concepts = result.get("available_concepts", [])
#     for i, concept in enumerate(concepts, 1):
#         output_lines.append(f"\n[概念 {i}]")
#         output_lines.append(f"  concept_id: {concept.get('concept_id', '')}")
#         output_lines.append(f"  relevance: {concept.get('relevance', 0)}")
#         topic_anchors = concept.get('topic_anchors', {})
#         if topic_anchors:
#             output_lines.append("  topic_anchors:")
#             for anchor_type, anchors in sorted(topic_anchors.items()):
#                 output_lines.append(f"    {anchor_type}:")
#                 if isinstance(anchors, list):
#                     for anchor in anchors:
#                         if isinstance(anchor, dict):
#                             for attr, val in sorted(anchor.items()):
#                                 output_lines.append(f"      {attr}: {val}")
#                 elif isinstance(anchors, dict):
#                     for attr, val in sorted(anchors.items()):
#                         output_lines.append(f"      {attr}: {val}")
    
#     # 第2部分：随机选择一个 theme 并输出
#     output_lines.append("\n" + "=" * 80)
#     output_lines.append("🎲 随机选择的主题 (Random Theme)")
#     output_lines.append("=" * 80)
#     themes = result.get("themes", {})
#     theme_ids = list(themes.keys())
    
#     if theme_ids:
#         random_theme_id = random.choice(theme_ids)
#         theme_data = themes[random_theme_id]
        
#         output_lines.append(f"\n[主题: {random_theme_id}]")
#         for key, value in sorted(theme_data.items()):
#             output_lines.append(f"  {key}: {value}")
#     else:
#         output_lines.append("\n  (无主题信息)")
    
#     return "\n".join(output_lines)


def classify_object_yaml(object_name: str, age: int) -> Dict[str, Any]:
    """
    Unified YAML-based object classifier. Replaces both:
    - the removed object-level LLM theme classifier
    - classify_object_sync + get_category_prompt  (LLM category classifier)

    Returns a dict with all downstream-needed fields:
        theme_id, theme_name, theme_reasoning,
        key_concept, bridge_question, category_prompt, success
    When success=False, all fields are present with fallback values.
    """
    _fallback: Dict[str, Any] = {
        "success": False,
        "error": f"No YAML mapping found for '{object_name}'",
        "theme_id": "how_world_works",
        "theme_name": "How the World Works",
        "theme_reasoning": "",
        "key_concept": "function",
        "bridge_question": f"I wonder how {object_name} works. What do you think?",
        "category_prompt": (
            f"CONCEPT FOCUS: function\n"
            f"OBSERVATION ANCHORS FOR {object_name.upper()}:\n"
            f"- Explore what {object_name} does and how it works."
        ),
    }

    age_tier = _age_to_tier(age)
    lookup = lookup_top_available_concepts(object_name, age_tier)

    if not lookup.get("success"):
        return _fallback

    # --- Theme ---
    themes = lookup.get("themes") or {}
    primary_theme_id = next(
        (tid for tid, td in themes.items() if td.get("type") == "primary"), None
    )
    if not primary_theme_id:
        return _fallback

    theme_name = _THEME_ID_TO_NAME.get(primary_theme_id, primary_theme_id)
    theme_data = themes.get(primary_theme_id, {})
    theme_reasoning = str(theme_data.get("reasoning", "") or "")

    # --- Concept: first item = highest relevance (tiebreak = list order) ---
    concepts = lookup.get("available_concepts") or []
    if not concepts:
        return _fallback
    concept = concepts[0]
    key_concept = str(concept.get("concept_id", "function"))

    # --- Derived fields ---
    bridge_question = (
        f"I wonder about the {key_concept} of {object_name}. What do you think?"
    )
    category_prompt = _format_concept_anchors(concept, object_name)

    return {
        "success": True,
        "theme_id": primary_theme_id,
        "theme_name": theme_name,
        "theme_reasoning": theme_reasoning,
        "key_concept": key_concept,
        "bridge_question": bridge_question,
        "category_prompt": category_prompt,
    }


__all__ = [
    "lookup_top_available_concepts",
    "classify_object_yaml",
]

from __future__ import annotations

import os
from functools import lru_cache
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple


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
    return any(q in _norm(v) for v in hay)


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


def lookup_top_available_concepts(query: str, age_tier: str) -> List[Dict[str, Any]]:
    """
    输入：
    - query：entity_id / 英文名 / 中文名（子串匹配，不区分大小写）
    - age_tier：T0/T1/T2/T3 或 0/1/2/3（或 tier_0..tier_3）

    输出：
    - 一个或多个“全局最大 rel”的 tier_concept_id 对应的 Available Concepts（原始 dict 列表）
    - 未检索到则返回 []
    """
    tier_key = _normalize_age_tier_to_key(age_tier)
    if tier_key is None:
        raise ValueError("Age Tier 无效：请使用 T0/T1/T2/T3 或 0/1/2/3（或 tier_0..tier_3）")

    entities = _cached_entities(DEFAULT_MAPPINGS_DIR)
    if not entities:
        return []

    # 先得到“每个命中 Entity 在指定 Tier 下的最大 rel”（可能多个概念并列最大）
    results = _search_best_matches_from_entities(entities, query, tier_key)
    if not results:
        return []

    # 再取这些结果中的“全局最大 rel”，返回对应 Available Concepts（可能多个）
    max_rel = max(r.relevance for r in results)
    top_objects = [r.concept_data for r in results if r.relevance == max_rel]

    # 去重（按 concept_id）并保持稳定顺序
    seen = set()
    deduped: List[Dict[str, Any]] = []
    for obj in top_objects:
        cid = obj.get("concept_id")
        key = str(cid) if cid is not None else repr(obj)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(obj)

    return deduped


__all__ = ["lookup_top_available_concepts"]


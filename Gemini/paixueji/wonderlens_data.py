"""
WonderLens Data Loader Module.

This module provides structured access to the educational content from
wonderlens-entity-topic-data/ YAML files, enabling pathway-based conversations
with age-tiered content.
"""
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any
import yaml
from functools import lru_cache


def safe_print(message):
    """Print message with fallback for encoding errors."""
    try:
        print(message)
    except UnicodeEncodeError:
        print(message.encode('ascii', 'replace').decode('ascii'))


@dataclass
class TopicOption:
    """Represents a single topic option within a pathway step."""
    topic_id: str
    attribute: str
    is_default: bool
    question: str
    question_type: str
    expected_answers: List[str]
    correct_feedback: str
    hint: str
    trigger_keywords: List[str] = field(default_factory=list)


@dataclass
class PathwayStep:
    """Represents a single round/step in a pathway."""
    round: int
    topic_options: List[TopicOption]

    def get_default_option(self) -> Optional[TopicOption]:
        """Get the default topic option for this step."""
        for opt in self.topic_options:
            if opt.is_default:
                return opt
        return self.topic_options[0] if self.topic_options else None

    def find_option_by_keyword(self, text: str) -> Optional[TopicOption]:
        """Find a topic option matching trigger keywords in the given text."""
        text_lower = text.lower()
        for opt in self.topic_options:
            if opt.trigger_keywords:
                for keyword in opt.trigger_keywords:
                    if keyword.lower() in text_lower:
                        return opt
        return None


@dataclass
class TopicConfig:
    """Configuration for topic handling within a pathway."""
    primary_topic: str
    secondary_topics: List[str]
    topic_switch_allowed: bool
    max_switches_per_session: int = 2


@dataclass
class ActivitySuggestion:
    """Suggested activity for a pathway."""
    type: str
    name: str
    topic_match: float


@dataclass
class PathwayData:
    """Complete pathway data structure."""
    id: str
    object_id: str
    object_name: str
    age_tier: int
    default_rounds: int
    max_rounds: int
    topic_config: TopicConfig
    initial_response_template: str
    steps: List[PathwayStep]
    activity_suggestions: List[ActivitySuggestion] = field(default_factory=list)


@dataclass
class AttributeByTier:
    """Tier-specific attribute data."""
    explorable: List[str]
    keywords: Dict[str, List[str]]


@dataclass
class ExplorableAttribute:
    """An explorable attribute of an object."""
    attribute: str
    visibility: str
    interest_level: str
    related_topics: List[str]
    surprise_factor: str = "low"


@dataclass
class SurprisePoint:
    """A surprise/interesting fact about an object."""
    point: str
    related_topic: str
    surprise_level: str


@dataclass
class InteractionPoint:
    """An interaction activity for an object."""
    action: str
    type: str


@dataclass
class ObjectData:
    """Complete object data structure."""
    id: str
    name: str
    category: str
    subcategory: str
    common_scenes: List[str]
    is_imaginative: bool
    explorable_attributes: List[ExplorableAttribute]
    attributes_by_tier: Dict[str, AttributeByTier]
    surprise_points: List[SurprisePoint]
    interaction_points: List[InteractionPoint]


@dataclass
class TopicMapping:
    """Mapping between entity and topic."""
    entity_id: str
    topic_id: str
    relevance: float


class WonderlensData:
    """
    Main class for loading and providing access to WonderLens educational data.

    Provides:
    - Object data lookup and validation
    - Pathway retrieval based on object and age
    - Entity-topic mappings
    """

    def __init__(self, data_dir: str = None):
        """
        Initialize the data loader.

        Args:
            data_dir: Path to wonderlens-entity-topic-data directory.
                     Defaults to relative path from this module.
        """
        if data_dir is None:
            # Default to sibling directory
            module_dir = os.path.dirname(os.path.abspath(__file__))
            data_dir = os.path.join(module_dir, "wonderlens-entity-topic-data")

        self.data_dir = data_dir
        self._objects: Dict[str, ObjectData] = {}
        self._pathways: Dict[str, PathwayData] = {}
        self._topic_mappings: Dict[str, List[TopicMapping]] = {}
        self._name_to_id: Dict[str, str] = {}  # Case-insensitive name lookup

        self._load_all_data()

    def _load_yaml(self, filename: str) -> dict:
        """Load a YAML file from the data directory."""
        filepath = os.path.join(self.data_dir, filename)
        if not os.path.exists(filepath):
            safe_print(f"[WONDERLENS] Warning: {filename} not found at {filepath}")
            return {}

        with open(filepath, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f) or {}

    def _load_all_data(self):
        """Load all YAML data files."""
        self._load_objects()
        self._load_pathways()
        self._load_topic_mappings()
        safe_print(f"[WONDERLENS] Loaded {len(self._objects)} objects, "
                   f"{len(self._pathways)} pathways, "
                   f"{len(self._topic_mappings)} entity mappings")

    def _load_objects(self):
        """Load objects.yaml into structured data."""
        data = self._load_yaml("objects.yaml")
        objects_list = data.get("objects", [])

        for obj in objects_list:
            # Parse explorable attributes
            explorable_attrs = []
            for attr in obj.get("explorable_attributes", []):
                explorable_attrs.append(ExplorableAttribute(
                    attribute=attr.get("attribute", ""),
                    visibility=attr.get("visibility", "medium"),
                    interest_level=attr.get("interest_level", "medium"),
                    related_topics=attr.get("related_topics", []),
                    surprise_factor=attr.get("surprise_factor", "low")
                ))

            # Parse attributes by tier
            attrs_by_tier = {}
            for tier_key, tier_data in obj.get("attributes_by_tier", {}).items():
                attrs_by_tier[tier_key] = AttributeByTier(
                    explorable=tier_data.get("explorable", []),
                    keywords=tier_data.get("keywords", {})
                )

            # Parse surprise points
            surprise_pts = []
            for sp in obj.get("surprise_points", []):
                surprise_pts.append(SurprisePoint(
                    point=sp.get("point", ""),
                    related_topic=sp.get("related_topic", ""),
                    surprise_level=sp.get("surprise_level", "medium")
                ))

            # Parse interaction points
            interaction_pts = []
            for ip in obj.get("interaction_points", []):
                interaction_pts.append(InteractionPoint(
                    action=ip.get("action", ""),
                    type=ip.get("type", "")
                ))

            object_data = ObjectData(
                id=obj.get("id", ""),
                name=obj.get("name", ""),
                category=obj.get("category", ""),
                subcategory=obj.get("subcategory", ""),
                common_scenes=obj.get("common_scenes", []),
                is_imaginative=obj.get("is_imaginative", False),
                explorable_attributes=explorable_attrs,
                attributes_by_tier=attrs_by_tier,
                surprise_points=surprise_pts,
                interaction_points=interaction_pts
            )

            self._objects[object_data.id] = object_data
            # Build case-insensitive name lookup
            self._name_to_id[object_data.name.lower()] = object_data.id

    def _load_pathways(self):
        """Load pathways.yaml into structured data."""
        data = self._load_yaml("pathways.yaml")
        pathways_list = data.get("pathways", [])

        for pw in pathways_list:
            # Parse steps
            steps = []
            for step in pw.get("steps", []):
                topic_options = []
                for opt in step.get("topic_options", []):
                    topic_options.append(TopicOption(
                        topic_id=opt.get("topic_id", ""),
                        attribute=opt.get("attribute", ""),
                        is_default=opt.get("is_default", False),
                        question=opt.get("question", ""),
                        question_type=opt.get("question_type", "open"),
                        expected_answers=opt.get("expected_answers", []),
                        correct_feedback=opt.get("correct_feedback", ""),
                        hint=opt.get("hint", ""),
                        trigger_keywords=opt.get("trigger_keywords", [])
                    ))
                steps.append(PathwayStep(
                    round=step.get("round", 0),
                    topic_options=topic_options
                ))

            # Parse topic config
            tc = pw.get("topic_config", {})
            topic_config = TopicConfig(
                primary_topic=tc.get("primary_topic", ""),
                secondary_topics=tc.get("secondary_topics", []),
                topic_switch_allowed=tc.get("topic_switch_allowed", True),
                max_switches_per_session=tc.get("max_switches_per_session", 2)
            )

            # Parse activity suggestions
            activities = []
            for act in pw.get("activity_suggestions", []):
                activities.append(ActivitySuggestion(
                    type=act.get("type", ""),
                    name=act.get("name", ""),
                    topic_match=act.get("topic_match", 0.0)
                ))

            pathway_data = PathwayData(
                id=pw.get("id", ""),
                object_id=pw.get("object_id", ""),
                object_name=pw.get("object_name", ""),
                age_tier=pw.get("age_tier", 1),
                default_rounds=pw.get("default_rounds", 4),
                max_rounds=pw.get("max_rounds", 5),
                topic_config=topic_config,
                initial_response_template=pw.get("initial_response_template", ""),
                steps=steps,
                activity_suggestions=activities
            )

            self._pathways[pathway_data.id] = pathway_data

    def _load_topic_mappings(self):
        """Load entity_topic_mappings.yaml into structured data."""
        data = self._load_yaml("entity_topic_mappings.yaml")
        mappings_list = data.get("mappings", [])

        for mapping in mappings_list:
            tm = TopicMapping(
                entity_id=mapping.get("entity_id", ""),
                topic_id=mapping.get("topic_id", ""),
                relevance=mapping.get("relevance", 0.0)
            )

            if tm.entity_id not in self._topic_mappings:
                self._topic_mappings[tm.entity_id] = []
            self._topic_mappings[tm.entity_id].append(tm)

    @property
    def objects(self) -> Dict[str, ObjectData]:
        """Get all loaded objects."""
        return self._objects

    @property
    def pathways(self) -> Dict[str, PathwayData]:
        """Get all loaded pathways."""
        return self._pathways

    @property
    def topic_mappings(self) -> Dict[str, List[TopicMapping]]:
        """Get all topic mappings grouped by entity_id."""
        return self._topic_mappings

    def validate_and_map_object(self, name: str) -> Tuple[bool, str, Optional[ObjectData]]:
        """
        Validate an object name and return its data.

        Performs case-insensitive matching on object names.

        Args:
            name: User-provided object name (e.g., "Dog", "dog", "Doggy")

        Returns:
            Tuple of (is_valid, entity_id, ObjectData or None)
        """
        name_lower = name.lower().strip()

        # Direct match on name
        if name_lower in self._name_to_id:
            entity_id = self._name_to_id[name_lower]
            return (True, entity_id, self._objects[entity_id])

        # Try partial match (e.g., "Doggy" contains "dog")
        for stored_name, entity_id in self._name_to_id.items():
            if stored_name in name_lower or name_lower in stored_name:
                return (True, entity_id, self._objects[entity_id])

        return (False, "", None)

    def get_object_by_id(self, entity_id: str) -> Optional[ObjectData]:
        """Get object data by entity ID."""
        return self._objects.get(entity_id)

    def get_object_by_name(self, name: str) -> Optional[ObjectData]:
        """Get object data by name (case-insensitive)."""
        _, _, obj = self.validate_and_map_object(name)
        return obj

    @staticmethod
    def age_to_tier(age: int) -> int:
        """
        Convert age to tier number.

        Age mapping:
        - 3-4 years: tier 1 (basic)
        - 5-6 years: tier 2 (intermediate)
        - 7-8 years: tier 3 (advanced)

        Args:
            age: Child's age in years

        Returns:
            Tier number (1, 2, or 3)
        """
        if age <= 4:
            return 1
        elif age <= 6:
            return 2
        else:
            return 3

    def get_best_pathway(self, entity_id: str, age_tier: int) -> Optional[PathwayData]:
        """
        Get the best matching pathway for an object and age tier.

        Selection logic:
        1. Look for exact tier match for the object
        2. Fall back to lower tier if exact not available
        3. Return None if no pathway exists

        Args:
            entity_id: Object entity ID (e.g., "animal_dog")
            age_tier: Target tier (1, 2, or 3)

        Returns:
            PathwayData or None if no matching pathway found
        """
        # Find all pathways for this object
        matching_pathways = []
        for pw_id, pw in self._pathways.items():
            if pw.object_id == entity_id:
                matching_pathways.append(pw)

        if not matching_pathways:
            return None

        # Sort by tier (descending so we check higher tiers first)
        matching_pathways.sort(key=lambda p: p.age_tier, reverse=True)

        # Look for exact match
        for pw in matching_pathways:
            if pw.age_tier == age_tier:
                return pw

        # Fall back to highest tier that's <= requested tier
        for pw in matching_pathways:
            if pw.age_tier <= age_tier:
                return pw

        # Last resort: return any available pathway
        return matching_pathways[0] if matching_pathways else None

    def get_pathway_for_object_and_age(
        self,
        object_name: str,
        age: int
    ) -> Tuple[bool, Optional[PathwayData], str]:
        """
        Convenience method to get a pathway given an object name and age.

        Args:
            object_name: User-provided object name
            age: Child's age

        Returns:
            Tuple of (success, PathwayData or None, error message)
        """
        # Validate object
        is_valid, entity_id, obj_data = self.validate_and_map_object(object_name)
        if not is_valid:
            return (False, None, f"Object '{object_name}' not found in database")

        # Get tier
        tier = self.age_to_tier(age)

        # Get pathway
        pathway = self.get_best_pathway(entity_id, tier)
        if not pathway:
            return (False, None, f"No pathway found for '{object_name}' at tier {tier}")

        return (True, pathway, "")

    def get_topics_for_entity(self, entity_id: str) -> List[TopicMapping]:
        """Get all topic mappings for an entity, sorted by relevance."""
        mappings = self._topic_mappings.get(entity_id, [])
        return sorted(mappings, key=lambda m: m.relevance, reverse=True)

    def list_all_object_names(self) -> List[str]:
        """Get list of all valid object names."""
        return [obj.name for obj in self._objects.values()]


# Singleton instance for easy access
_wonderlens_data_instance: Optional[WonderlensData] = None


def get_wonderlens_data() -> WonderlensData:
    """Get or create the singleton WonderlensData instance."""
    global _wonderlens_data_instance
    if _wonderlens_data_instance is None:
        _wonderlens_data_instance = WonderlensData()
    return _wonderlens_data_instance


def reload_wonderlens_data() -> WonderlensData:
    """Force reload of all WonderLens data."""
    global _wonderlens_data_instance
    _wonderlens_data_instance = WonderlensData()
    return _wonderlens_data_instance

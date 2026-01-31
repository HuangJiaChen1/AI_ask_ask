# WonderLens Knowledge Graph Data Files

This folder contains the structured data files that power WonderLens's educational conversation system. These YAML files define what the AI knows about objects, how topics connect, and how conversations should flow for different age groups.

## File Overview

| File | Purpose | Size |
|------|---------|------|
| `objects.yaml` | Object definitions with attributes | 28 objects, 7 categories |
| `topic_hierarchy.yaml` | 3-level topic taxonomy | 3 super-domains, 9 categories, 30+ topics |
| `topic_frameworks.yaml` | Learning frameworks per topic | 40 frameworks across 6 domains |
| `entity_topic_mappings.yaml` | Object-to-topic relationships | 80 mappings |
| `pathways.yaml` | Conversation flow scripts | 52 pathways |

## How They Work Together

### Organizational Structure Note

The files use complementary but different organizational approaches:

| File | Structure | Purpose |
|------|-----------|---------|
| `topic_hierarchy.yaml` | 3-level tree (super-domain → category → topic) | Navigation and topic discovery |
| `topic_frameworks.yaml` | Flat 6-domain grouping | Learning approach definitions |
| `objects.yaml` | 7 categories matching real-world objects | Object recognition and attributes |
| `pathways.yaml` | 6 sections matching frameworks | Conversation scripts |

The **topic_hierarchy** provides a browsable tree for finding related topics, while **topic_frameworks** groups topics by learning domain for consistent pedagogical approaches.

```
┌─────────────────────────────────────────────────────────────┐
│                     User snaps a photo                       │
└─────────────────────────┬───────────────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────────┐
│  1. Vision identifies object → objects.yaml                  │
│     (e.g., "dog" with attributes: color, size, breed)        │
└─────────────────────────┬───────────────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────────┐
│  2. Find relevant topics → entity_topic_mappings.yaml        │
│     (dog → animal_appearance, animal_behavior, animal_senses)│
└─────────────────────────┬───────────────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────────┐
│  3. Select pathway by age tier → pathways.yaml               │
│     (age 4 → pathway_dog_appearance_tier1)                   │
└─────────────────────────┬───────────────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────────┐
│  4. Guide conversation through rounds with questions,        │
│     expected answers, feedback, and activity suggestions     │
└─────────────────────────────────────────────────────────────┘
```

---

## File Details

### 1. objects.yaml

Defines all recognizable objects with their visual and educational attributes.

```yaml
objects:
  - id: animal_dog
    name: Dog
    category: animals
    subcategory: mammals
    attributes:
      visual:
        - color
        - size
        - breed_appearance
      behavioral:
        - movement
        - sound
        - social_behavior
      educational:
        - senses
        - communication
        - domestication
    tier_appropriate:
      tier1: [color, size, sound]           # Ages 3-4
      tier2: [senses, movement, breeds]      # Ages 5-6
      tier3: [communication, domestication]  # Ages 7-8
```

**Usage:** When vision identifies an object, look up its `id` to get available attributes and age-appropriate topics.

---

### 2. topic_hierarchy.yaml

Organizes all educational topics into a 3-level taxonomy with super-domains, categories, and specific topics.

```yaml
topics:
  # Level 1: Super-domains (3 total)
  - id: nature
    name: Nature Exploration
    level: 1
    children:
      # Level 2: Categories
      - id: animal
        name: Animal
        level: 2
        children:
          # Level 3: Specific Topics
          - id: animal_appearance
            name: Animal Appearance
            level: 3
            keywords: ["color", "size", "shape", "fur", "skin"]
          - id: animal_behavior
            name: Animal Behavior
            level: 3
            keywords: ["sound", "movement", "habits"]
```

**Structure:**

| Level | Name | Contents |
|-------|------|----------|
| 1 | Super-domains | `nature`, `daily_life`, `imagination` |
| 2 | Categories | `animal`, `plant`, `nature_phenomenon`, `food`, `daily_object`, `transport`, `prehistoric`, `mythology`, `technology_future` |
| 3 | Topics | 30+ specific topics like `animal_appearance`, `pollination`, `traffic_safety` |

**Usage:** Navigate the hierarchy to find related topics or suggest topic switches during conversation.

---

### 3. topic_frameworks.yaml

Defines the learning approach for each topic with guiding questions and tier-specific focus areas. Now organized across 6 domains with 40 total frameworks.

```yaml
frameworks:
  - topic_id: animal_senses
    name: Animal Senses
    domain: animals
    learning_objectives:
      - Learn how animals perceive the world
      - Compare animal senses to human senses
      - Understand sensory adaptations
    exploration_dimensions:
      - dimension_id: sight
        name: Sight
        question_pattern: "How does {object} see the world?"
        tier_focus:
          tier1: Eyes location and size
          tier2: What they can see
          tier3: Special vision abilities
      - dimension_id: smell
        name: Smell
        question_pattern: "How does {object} use its nose?"
        tier_focus:
          tier1: Sniffing behavior
          tier2: What smells they detect
          tier3: Sensitivity comparisons
```

**Framework Coverage by Domain (6 domains, 40 total):**

| Domain | Frameworks | Topics Covered |
|--------|------------|----------------|
| Animals | 8 | appearance, behavior, senses, lifecycle, habitat, adaptation, breathing, communication |
| Plants | 7 | appearance, parts, lifecycle, pollination, behavior, ecosystem, seasons |
| Food | 6 | fruit appearance, vegetable appearance, food senses, processing, plant growth, animal products |
| Vehicles | 8 | vehicle parts, sounds, safety, flight principles, physics, technology, programming, robotics |
| Natural Phenomena | 6 | weather, water cycle, celestial bodies, moon phases, solar system, light phenomena |
| Imagination | 5 | mythology, prehistoric, nature connection, critical thinking, robot function |

**Usage:** Use framework questions as fallbacks when pathways don't cover a child's question, maintaining age-appropriate inquiry style.

---

### 4. entity_topic_mappings.yaml

Maps each object to its relevant topics with relevance scores.

```yaml
mappings:
  - object_id: animal_dog
    topics:
      - topic_id: animal_appearance
        relevance: 1.0
        default_for_tiers: [1]
      - topic_id: animal_senses
        relevance: 0.9
        default_for_tiers: [2]
      - topic_id: animal_behavior
        relevance: 0.85
        default_for_tiers: [3]
```

**Usage:** After identifying an object, retrieve its topic mappings to determine which pathway to load based on the child's age tier.

---

### 5. pathways.yaml

The conversation scripts that guide educational dialogue. This is the largest and most detailed file.

```yaml
pathways:
  - id: pathway_dog_appearance_tier1
    object_id: animal_dog
    object_name: Dog
    age_tier: 1                    # Ages 3-4
    default_rounds: 4
    max_rounds: 5
    
    topic_config:
      primary_topic: animal_appearance
      secondary_topics: ["animal_behavior"]
      topic_switch_allowed: true
    
    initial_response_template: "Wow! You found a dog! What a fluffy friend!"
    
    steps:
      - round: 1
        topic_options:
          - topic_id: animal_appearance
            attribute: color
            is_default: true
            question: "What color is this doggy? Is it brown, white, or black?"
            question_type: choice
            expected_answers: ["brown", "white", "black", "golden", "spotted"]
            correct_feedback: "Yes! You're right! This doggy has such pretty fur!"
            hint: "Look at the doggy's fur. What color do you see?"
            
          - topic_id: animal_behavior
            attribute: movement
            is_default: false
            trigger_keywords: ["running", "jumping", "moving"]
            question: "What is the doggy doing? Running or sitting?"
            question_type: choice
            expected_answers: ["running", "sitting", "walking"]
            correct_feedback: "Dogs love to run and play!"
            hint: "Watch the doggy. Is it moving or staying still?"
      
      # ... rounds 2-4 ...
    
    activity_suggestions:
      - type: sound_game
        name: "Animal Sounds Guessing Game"
        topic_match: 0.9
```

**Key Pathway Elements:**

| Element | Purpose |
|---------|---------|
| `age_tier` | 1 (3-4yo), 2 (5-6yo), 3 (7-8yo) |
| `topic_options` | Multiple question paths per round |
| `is_default` | Used when no triggers match |
| `trigger_keywords` | Activate alternative questions based on child's response |
| `question_type` | choice, descriptive, observation, counting, reason, imitation, etc. |
| `expected_answers` | For answer validation |
| `correct_feedback` | Positive reinforcement with educational content |
| `hint` | Scaffolding when child is stuck |

---

## Age Tier Guidelines

| Tier | Ages | Focus | Question Types |
|------|------|-------|----------------|
| 1 | 3-4 | Sensory observation, naming, basic attributes | choice, observation, counting, imitation |
| 2 | 5-6 | Comparisons, simple reasoning, processes | reason, comparison, prediction, knowledge |
| 3 | 7-8 | Systems thinking, cause-effect, connections | hypothesis, reflection, sequence, analysis |

---

## Pathway Coverage

### By Category (52 total pathways)

| Category | Objects | Pathways |
|----------|---------|----------|
| Animals | Dog, Butterfly, Fish, Bird | 10 |
| Plants | Flower, Tree, Apple, Sunflower | 10 |
| Food | Banana, Carrot, Bread, Milk | 8 |
| Vehicles | Car, Airplane, Boat, Bicycle | 8 |
| Natural Phenomena | Sun, Moon, Rain, Rainbow | 8 |
| Imaginative | Dinosaur, Unicorn, Robot, Fairy | 8 |

### Pathway Naming Convention

```
pathway_{object}_{topic}_{tier}

Examples:
- pathway_dog_appearance_tier1
- pathway_butterfly_composite_tier2
- pathway_fish_breathing_tier3
```

---

## Integration Example (Python)

```python
import yaml

# Load all data files
with open('objects.yaml') as f:
    objects = yaml.safe_load(f)['objects']
    
with open('entity_topic_mappings.yaml') as f:
    mappings = yaml.safe_load(f)['mappings']
    
with open('pathways.yaml') as f:
    pathways = yaml.safe_load(f)['pathways']

def get_pathway(object_id: str, age: int) -> dict:
    """Get appropriate pathway for object and child's age."""
    
    # Determine tier from age
    tier = 1 if age <= 4 else (2 if age <= 6 else 3)
    
    # Find object's topic mappings
    obj_mapping = next(m for m in mappings if m['object_id'] == object_id)
    
    # Get default topic for this tier
    default_topic = next(
        t['topic_id'] for t in obj_mapping['topics'] 
        if tier in t.get('default_for_tiers', [])
    )
    
    # Find matching pathway
    pathway_id = f"pathway_{object_id.split('_')[1]}_{default_topic.split('_')[1]}_tier{tier}"
    
    return next((p for p in pathways if p['id'] == pathway_id), None)

# Example usage
pathway = get_pathway('animal_dog', age=4)
print(pathway['initial_response_template'])
# Output: "Wow! You found a dog! What a fluffy friend!"
```

---

## Extending the Data

### Adding a New Object

1. Add object definition to `objects.yaml`
2. Add topic mappings to `entity_topic_mappings.yaml`
3. Create pathways for each tier in `pathways.yaml`

### Adding a New Pathway

Follow this template:

```yaml
- id: pathway_{object}_{topic}_tier{N}
  object_id: {category}_{object}
  object_name: {Object Name}
  age_tier: {1|2|3}
  default_rounds: 4
  max_rounds: 5
  topic_config:
    primary_topic: {topic_id}
    secondary_topics: []
    topic_switch_allowed: true
  initial_response_template: "{Engaging opening message}"
  steps:
    - round: 1
      topic_options:
        - topic_id: {topic}
          attribute: {attribute}
          is_default: true
          question: "{Age-appropriate question}"
          question_type: {type}
          expected_answers: [...]
          correct_feedback: "{Educational positive feedback}"
          hint: "{Scaffolding hint}"
  activity_suggestions:
    - type: {activity_type}
      name: "{Activity Name}"
      topic_match: {0.0-1.0}
```

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-01-31 | Initial release with 52 pathways across 6 categories |

## The Fluffy Expedition

### A. Basic Info

| Field | Value |
|-------|-------|
| Activity Name | The Fluffy Expedition |
| Activity Category | Collection/Tracking Exploration (Out-of-Device) |
| Recommended Tier | T0 (ages 2-4) |
| Core IB Key Concepts | Connection, Form |
| Related Concepts | Discovery, Sensory Awareness, Nature, Texture |
| ATL Skills Focus | Research Skills (observation, data collection), Communication Skills (describing, naming) |
| Experience Pillar | Adventure |
| Game Style | quest_collector |

### B. Activity Overview

**1. Brief Description**

After the child photographs a dandelion, the AI gasps at all those tiny white parachutes and wonders where they might fly. The child becomes a "Fluffy Expedition Explorer"  -  venturing out to find 3 things nearby that feel fluffy, fuzzy, or soft. Each discovery invites touch: how does it feel? Is it silky? Puffy? Fuzzy like a cloud? After collecting all three, the child gives each find a character name (like "Cloud Puff" or "Fuzzy Friend") and tells a tiny story about the fluffy friends meeting each other. Softness connects everything!

**2. Educational Purpose (KUD)**

- **K (Know):** Learn that dandelion seeds are fluffy and float away like tiny parachutes. Learn that "soft" comes in many forms  -  fuzzy, silky, puffy, woolly. Learn that touching things tells you about their texture. Learn the names for different kinds of softness.
- **U (Understand):** Understand that many different things share the quality of softness  -  a dandelion seed, moss, a petal, and a caterpillar can all feel fluffy even though they look nothing alike. That is Connection  -  finding how different things are linked together through something they share.
- **D (Do):** Practice exploring textures through touch  -  feeling for softness in the environment. Practice comparing how different things feel (fuzzier vs. silkier vs. puffier). Practice giving creative names to found objects and building a simple story from them.

**3. Design Highlight**

The quest_collector synthesis transforms a texture scavenger hunt into character creation and storytelling. Each fluffy find earns a texture-inspired name the child invents  -  "Cloud Puff," "Fuzzy Friend," "Silky Petal." The final story moment  -  "What do your fluffy friends do when they meet?"  -  lets even a 2-year-old become a storyteller, weaving their three named characters into a tiny narrative. The dandelion itself is the first fluffy friend, anchoring the expedition in something the child already touched and wondered about.

**4. Typical Scenario**

Child photographs a dandelion -> AI marvels at the fluffy seeds -> child becomes a "Fluffy Expedition Explorer" -> finds and touches 3 fluffy/fuzzy/soft things -> names each one as a character -> tells a tiny story about the fluffy friends meeting -> celebrates with a Fluffy Expedition Explorer badge.

**5. Runtime Asset Notes**

- Optional support asset: `fluffy_expedition_icon_set_01`. Use it only for empty slots, hint markers, and the story path; accepted finds are represented by child photos.
- If unavailable, use generic rounded empty slots and text labels; the AI must not claim that a specific icon is visible.

### C. Interaction Flow

> Recommended Tier: T0 (ages 2-4)

#### Step 1: Transition Bridge

**AI says:** [delighted gasp] "Ooh! Look at all those tiny fluffy parachutes! Where do you think they're going to fly to?"

**Child responses:**

1. (Ideal) "Up!" / "To the sky!" / "Far away!" / child blows on the dandelion
2. (Unexpected) "It's a flower!" / "White!" / "I want to pick it!"
3. (No response) Child looks at the dandelion photo quietly.

**AI follow-up:**

1. [amazed] "Up to the sky! Tiny fluffy flyers! I wonder  -  is the dandelion the only soft thing here?"
2. [warm, accepting] "It IS a flower! A fluffy one! All those soft little seeds. Would you like to find more fluffy things?"
3. [wait 2s] [soft, playful] "So fluffy! Like tiny clouds. Touch the screen  -  can you feel how soft it looks?"

**Screen:** Dandelion photo centered with seeds gently floating upward in a slow drift animation; warm sparkle highlights on the seed head and a soft wonder chime.

#### Step 2: Rule Introduction + Demo

**AI says:** [excited, playful] "You are a Fluffy Expedition Explorer! Would you like to find 3 soft, fluffy things? Touch them and tell me how they feel!"

**Child responses:**

1. (Ideal) "Yeah!" / "I want to find fluffy!" / child starts looking around
2. (Unexpected) "What's fluffy?" / "Like what?"
3. (No response) Child looks around slowly.

**AI follow-up:**

1. [cheering] "Go go, Explorer! I bet something soft and fluffy is hiding nearby  -  would you like to start looking?"
2. [helpful, warm] "Fluffy means soft! Like clouds. Like the dandelion. Would you like to touch things and feel for softness?"
3. [wait 2s] [encouraging] "I wonder if something soft is waiting right near you! Would you like to touch something and see if it feels fluffy?"

**Screen:** Mission card with "Fluffy Expedition Explorer" badge (dandelion icon with floating seeds), 4 slots (first filled with dandelion photo, 3 empty with cloud-puff placeholders), and a "Find 3!" counter.

#### Step 3: Multi-Round Interaction

**Round 1  -  First Fluffy Find:**

*(Child touches/finds something soft nearby  -  e.g., moss, a fuzzy leaf, soft grass, a feather)*

**AI says:** [excited discovery] "Ooh! You found something! How does it feel?"

**Child responses:**

1. (Ideal) "Soft!" / "Fuzzy!" / "Like a cloud!" / child describes the texture
2. (Unexpected) "It's green!" / "I found it!" / doesn't describe texture
3. (No response) Child holds the soft thing quietly.

**AI follow-up:**

1. [delighted] "So soft! Like the dandelion! Your first fluffy treasure! 2 more to find!"
2. [warm, scaffolding] "You found it! Now touch it gently. Is it fuzzy? Or silky? Or puffy like a cloud?"
3. [wait 2s] [warm] "Touch it softly. How does it feel on your fingers? Fuzzy? Smooth? That's your first fluffy treasure!"

**Screen:** Photo slides into slot 2 with a card-slide-in animation and a shutter click sound; progress tracker updates to "1 of 3 found."

**Round 2  -  Second Fluffy Find:**

*(Child finds another soft/fuzzy/fluffy thing  -  e.g., a soft petal, woolly caterpillar, plush toy left outside)*

**AI says:** [curious] "Another one! Does this one feel the same as the first?"

**Child responses:**

1. (Ideal) "Softer!" / "This one is fuzzier!" / "It's different!" / child compares
2. (Unexpected) "It's pretty!" / "I like this one!" / doesn't compare
3. (No response) Child touches the new find silently.

**AI follow-up:**

1. [amazed] "Fuzzier! So soft comes in different ways! 1 more fluffy treasure to find!"
2. [warm, guiding] "So pretty! Now feel both  -  is this one softer? Or fuzzier? Softness can feel different!"
3. [wait 2s] [gentle] "Touch it and then touch your first find. Which one is fuzzier? Every soft thing feels a little different!"

**Screen:** Photo slides into slot 3 with a celebration-burst animation and a shutter click; progress tracker updates to "2 of 3 found."

**Round 3  -  Third Fluffy Find:**

*(Child finds the last fluffy/soft thing  -  e.g., a fluffy seed head, soft moss, a downy feather)*

**AI says:** [thrilled] "The last fluffy treasure! Would you like to give this one a fun name?"

**Child responses:**

1. (Ideal) "Cloud Puff!" / "Fuzzy!" / "Softie!" / child invents a name
2. (Unexpected) "It's soft!" / "I found it!" / doesn't name it
3. (No response) Child holds the find with a smile.

**AI follow-up:**

1. [celebrating] "[Name]! I love that! All 3 fluffy treasures found! You did it!"
2. [warm, scaffolding] "So soft! What would you call this fluffy friend? Maybe Puffy? Or Cloudy? What name do you like?"
3. [wait 2s] [playful] "This fluffy friend needs a name! Something soft and fun. What about Cloud Puff? Or you pick!"

**Screen:** Photo slides into slot 4 with a celebration-burst animation and a mission-complete fanfare; progress tracker shows "3 of 3 found!"

**STUCK BRANCH:** "Would you like to reach out and touch something nearby? I wonder if it feels soft or fuzzy!"

#### Step 4: Celebration (Synthesis)

**AI says:** [amazed, storytelling voice] "Look at all your fluffy treasures! Each one feels different  -  fuzzy, silky, puffy! Would you like to give each one a texture name?"

**Child responses:**

1. (Ideal) "Cloud Puff!" / "Fuzzy Friend!" / child names the finds
2. (Unexpected) "They're all soft!" / "I like them!" / doesn't name
3. (No response) Child looks at the collection quietly.

**AI follow-up:**

1. [delighted, narrating] "Cloud Puff, Fuzzy Friend, and [Name 3]! Three fluffy friends! What happens when they all meet?"
2. [warm, scaffolding] "All soft! Maybe this fuzzy one is Fuzzy Friend? And this silky one is Silky Star? Would you like to pick names?"
3. [wait 2s] [gentle, playful] "How about Cloud Puff for the puffy one? And Fuzzy Friend for the fuzzy one? Now  -  what do they do when they meet?"

**Child tells a tiny story** (or AI scaffolds): "They play!" / "They have a soft party!" / "They cuddle!"

**AI response to story:** [celebrating] "A fluffy party! Cloud Puff and Fuzzy Friend and [Name 3] all cuddle together. The softest story ever!"

**Screen:** All 4 photos displayed in a circle (dandelion in center) with soft wispy lines connecting them; character name tags beneath each find; a storybook frame with floating seed animations and a "Fluffy Friends" banner.

**AI says:** [proud, ceremonial] "You are officially a Fluffy Expedition Explorer! You found softness in so many places!"

**Child responses:**

1. (Ideal) "Yay!" / "I'm an explorer!" / "More fluffy!"
2. (Unexpected) "Can we find rough things?" / "I like this soft one best."
3. (No response) Child smiles or claps while looking at the collection.

**AI follow-up:**

1. [celebration] "The best Fluffy Expedition Explorer! You found softness everywhere!"
2. [warm, extending] "Rough things can be a new expedition. Today your soft treasures made a fluffy team."
3. [wait 2s] [gentle] "What a wonderful expedition. You touched so many soft treasures."

**Screen:** Badge spinning into center labeled "Fluffy Expedition Explorer" with dandelion and floating-seed motif; collection photos as small insets; "Connection" in soft pastel lettering; seed-puff confetti drifting down.

#### Step 5: Closing + IB Concepts

**AI says:** [warm, proud] "Fluffy Expedition Explorer, you did something amazing! You found soft treasures all connected by fluffiness  -  a dandelion, and all your fluffy friends. That's Connection  -  finding how different things are linked together! Softness connects them all!"

**Child responses:**

1. (Ideal) "Soft is everywhere!" / "I want more!" / "Fluffy!"
2. (Unexpected) "I want rough things!" / "Bye dandelion!"
3. (No response) Child waves or smiles at the screen.

**AI follow-up:**

1. [warm] "Softness IS everywhere! Next time, feel for more. Bye bye, Fluffy Explorer!"
2. [warm, clear] "Rough things can be next. Today you found the soft connection. Bye bye, Fluffy Explorer!"
3. [wait 2s] [gentle] "You were a wonderful explorer today. Bye bye, Fluffy Explorer!"

**Screen:** Badge centered with "Fluffy Expedition Explorer" title and dandelion motif; collection photos as small insets around the badge; "Connection" in soft cloud-colored lettering; dandelion seeds float gently across the screen as a closing animation.

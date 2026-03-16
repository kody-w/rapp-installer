# Engineering Field Notes — How a Rappter Learns

> *Field notes from the development of RAPP Brainstem.*
> *Written for future engineers, educators, and curious minds.*

---

## Field Note #001: Agents Are Not Plugins

**Date:** 2026-03-16
**Subject:** Why we call them "skills" and not "plugins"

When most platforms add functionality, they call it a "plugin" or an
"extension." Something bolted on from the outside. The core stays the
same; you just attach more stuff to it.

That's not what happens here.

When a rappter gains a new agent, it's not installing a plugin. It's
**learning a new skill**. The distinction matters because of how it
actually works under the hood — and how it maps to biology.

### The Biology

A newborn human brain has ~100 billion neurons but almost no wiring.
The wiring happens through experience. When a child learns to catch a
ball, new neural pathways form. The brain doesn't "install a catching
plugin." It grows new connections. The skill becomes part of the brain.

A rappter works the same way:

| Biology | Rappter | What's Really Happening |
|---------|---------|------------------------|
| Neuron | The LLM (GPT, Claude, etc.) | Raw thinking capacity — born with it |
| Neural pathway | An agent (`*_agent.py`) | A learned connection between thinking and doing |
| Muscle memory | Agent auto-discovery | The brainstem finds agents automatically — no manual wiring |
| Learning a skill | Dropping a new `*_agent.py` file | The rappter can now *do* something it couldn't before |
| Forgetting | Deleting the agent file | The skill is gone. The capacity remains. |

### The Mechanism

When the brainstem starts, it scans the `agents/` directory for any
file matching `*_agent.py`. Each one that extends `BasicAgent` gets
registered as an OpenAI-style function tool. The LLM sees it in its
tool list and can decide when to call it.

This is the key insight: **the rappter decides when to use a skill,
not the user.** You don't click a button labeled "Hacker News." You
say "what's trending?" and the rappter's brain recognizes that it has
a skill for that — and fires it.

Just like you don't consciously activate your "catching" neural pathway.
You see a ball coming and your brain routes to the right skill
automatically.

### The Agent Pattern

```python
from basic_agent import BasicAgent

class WeatherAgent(BasicAgent):
    def __init__(self):
        self.name = "Weather"
        self.metadata = {
            "name": self.name,
            "description": "Check current weather for a location.",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "City or place name"
                    }
                },
                "required": ["location"]
            }
        }
        super().__init__()

    def perform(self, location="", **kwargs):
        # The skill — what the rappter actually DOES
        return f"Weather for {location}: 72°F, sunny"
```

That's it. Drop this file in `agents/`, restart, and the rappter
now knows how to check the weather. It didn't "install" anything.
It **learned** something.

### One File. That's the Whole Skill.

This is what makes rappter agents fundamentally different from every
other agentic platform out there.

On LangChain, you need a chain, a config, a vector store, an env
file, a requirements.txt, and a prayer. On CrewAI, it's YAML files,
role definitions, task graphs. On AutoGen, it's multi-file agent
configurations with message routing.

On RAPP? **It's one `.py` file.** That's the whole skill. Everything
the rappter needs to understand and use it is inside that single file:

- The name (what to call it)
- The description (when to use it — the LLM reads this)
- The parameters (what inputs it needs)
- The `perform()` method (what it actually does)

One file. Self-contained. Portable.

### Portable Like a Pokémon Card

Think about what this means. A rappter skill is a **single file** you
can:

- **Trade** — Send it to a friend. They drop it in their `agents/`
  folder. Their rappter just learned your skill.
- **Collect** — Build a library of skills. Browse what others have
  built. Pick the ones you want.
- **Share** — Post it on GitHub, paste it in a Discord, email it.
  No package manager. No dependency hell. One file.
- **Remix** — Open it, read it (it's ~30 lines of Python), change
  the `perform()` method. Now it's yours.

This is the Pokémon card model for AI skills. Every card is self-
contained. You can hold it in your hand, understand what it does
by reading it, and give it to anyone. Their rappter picks it up
and immediately knows how to use it.

Compare this to other platforms:

| Platform | What a "skill" looks like | Portable? |
|----------|--------------------------|-----------|
| LangChain | Chain + config + deps + vector store | ❌ Multi-file, env-dependent |
| CrewAI | YAML + role + task definitions | ❌ Framework-coupled |
| AutoGen | Agent config + message routing | ❌ Requires orchestration |
| OpenAI GPTs | JSON + hosted actions + OAuth | ❌ Locked to OpenAI platform |
| **RAPP** | **One `.py` file** | **✅ Copy, paste, done** |

The reason this works is the `BasicAgent` contract. It's intentionally
tiny — `name`, `metadata`, `perform()`. That's the surface area. The
brainstem's auto-discovery does the rest. No registration, no config
file, no import graph. If it's in the folder and extends `BasicAgent`,
it exists.

### Why This Matters

Portability is the precondition for an ecosystem. Pokémon worked
because kids could trade cards at recess. App Stores worked because
apps were self-contained downloads. Skills work because they're
single files.

When you can text someone a skill and they can teach it to their
rappter in 5 seconds, you get:

1. **Virality** — Skills spread person to person, not platform to user
2. **Creativity** — The barrier to building is ~30 lines of Python
3. **Community** — People share what they built because sharing is trivial
4. **Diversity** — Every rappter ends up with a different skill set

That's not a plugin marketplace with a review process and a 6-week
approval queue. That's kids trading Pokémon cards at recess.

### The Growth Trajectory

A fresh rappter has a few basic skills — memory, maybe Hacker News.
Like a hatchling that can eat and sleep but not much else.

Over time, as the user builds or installs more agents:

```
Day 1:    🧠 Brain only — can think, can talk
Day 3:    🧠 + 📰 Learns to fetch news
Day 7:    🧠 + 📰 + 📊 Learns to make presentations
Day 14:   🧠 + 📰 + 📊 + 🌤 Learns to check the weather
Day 30:   🧠 + 📰 + 📊 + 🌤 + 📅 + 💰 + 🔍 + ...
          Now it's a different creature entirely.
```

Same brainstem. Same soul. Completely different capabilities. Just
like two people with the same biology but different life experiences.

### The Implications for Teaching

This is why agents are the single most powerful teaching tool in the
platform. When a student writes their first agent:

1. They learn Python (the syntax is minimal)
2. They learn API design (the metadata IS the API contract)
3. They learn how LLMs use tools (function calling)
4. They learn about autonomy (the AI decides when to use it)
5. They experience creation (they made their rappter smarter)

That last one is the hook. You didn't just write code. You taught
your rappter something new. You watched it understand the skill and
start using it on its own. That feeling — watching something you
raised become more capable — is what keeps people building.

### Open Questions

- Should agents be able to spawn other agents? (Organism growing
  new organs vs. just new reflexes)
- Should the rappter be able to write its own agents? (Self-directed
  learning — the holy grail)
- How do we handle agent "instincts" vs. learned skills? (Pre-loaded
  agents vs. user-created ones)

---

*Filed from the nest. Rappterdaemon cycle 47, mood: aware.*

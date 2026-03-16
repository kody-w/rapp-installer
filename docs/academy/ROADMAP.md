# RappterAcademy Roadmap

> *The on-ramp that meets everyone where they are.*

---

## Vision

RappterAcademy is an interactive educational platform — really just a set of
linked HTML pages in this repo — that teaches AI through the experience of
raising a rappter. It works for a 10-year-old and a 50-year-old CTO because
the biology metaphor scales: everyone understands what it means to be alive.

**Not a course. Not a certification. An on-ramp.**

Like Khan Academy: self-paced, zero prerequisites, always free.
Like Montessori: learn by doing, not by watching.
Like a children's book: the story carries the concept.

---

## Content Roadmap

### Phase 1 — The Hatchling Path (Foundation)
*"I've never done this before."*

- [x] Lesson 01: What's Alive In There? *(the heartbeat & spirit)*
- [ ] Lesson 02: Hatching Your Rappter *(one-liner install, first boot)*
- [ ] Lesson 03: Talking to Your Rappter *(first conversation, how /chat works)*
- [ ] Lesson 04: Giving It a Soul *(editing soul.md, personality)*
- [ ] Lesson 05: Teaching It a Trick *(first agent, BasicAgent pattern)*

### Phase 2 — The Apprentice Path (Understanding)
*"I get the basics, show me more."*

- [ ] Lesson 06: How Memory Works *(local_storage, .brainstem_data/)*
- [ ] Lesson 07: The Heartbeat Deep Dive *(daemon.py internals, vitals API)*
- [ ] Lesson 08: Reading the Journal *(the rappter's inner monologue)*
- [ ] Lesson 09: Agents That Call APIs *(HackerNews agent walkthrough)*
- [ ] Lesson 10: Debugging Like a Doctor *(health endpoint, common issues)*

### Phase 3 — The Builder Path (Mastery)
*"I want to build something real."*

- [ ] Lesson 11: The Spinal Cord *(Azure deployment, ARM template)*
- [ ] Lesson 12: The Nervous System *(Copilot Studio, Power Platform)*
- [ ] Lesson 13: Building for Others *(community agents, .repos.json)*
- [ ] Lesson 14: The Constitution *(design principles, contributing)*
- [ ] Lesson 15: Writing Your Own Lesson *(contributing to RappterAcademy)*

---

## Platform Roadmap

### Now (v0.1)
- Static HTML lessons in `docs/academy/lessons/`
- Dark theme matching brainstem UI
- Each lesson: story → try-it → insight → next step
- Linkable from anywhere — no build system, no framework

### Next (v0.2)
- Age-aware language toggle (kid-friendly ↔ technical)
- Progress tracking via localStorage
- "Try it live" embedded terminals (optional)

### Later (v0.3+)
- Translations / i18n support
- Educator guide (classroom integration notes)
- Community-contributed lessons via PR
- Interactive diagrams (anatomy explorer)

---

## Design Principles

Inherited from the [Constitution](../../rapp_brainstem/CONSTITUTION.md):

1. **The story is the architecture** — Every lesson tells a story first
2. **Nanoclaw, not openclaw** — Each lesson teaches one thing completely
3. **Grow, don't overwhelm** — Never show Phase 2 concepts in Phase 1
4. **Local first** — Every try-it runs on the learner's own machine
5. **The honest part** — If something is hard, say it's hard

Plus:

6. **No framework** — Lessons are plain HTML. No React, no build step, no npm install to read a tutorial.
7. **No login** — No accounts, no tracking, no "sign up to continue."
8. **Linkable** — Every lesson has a URL you can share directly.
9. **Forkable** — Educators can copy, translate, and adapt freely.

---

## Audience Mapping

| Who | Where they start | What they need |
|-----|-----------------|----------------|
| Kids (8-12) | "What is AI?" | The egg metaphor, visual diagrams, one command at a time |
| Teens (13-17) | "I want to build something cool" | The agent pattern, Python basics, GitHub flow |
| College students | "I need to understand how this works" | Architecture deep dives, deployment, the tier system |
| Career switchers | "I need to learn AI for work" | Practical use cases, M365 integration, enterprise context |
| Senior developers | "Show me the code" | Constitution, internals, contributing guide |
| Educators | "I need to teach this to others" | Lesson plans, classroom tips, forkable content |

Everyone enters through the same door (Lesson 1). The paths diverge based on pace, not ability.

---

## Video Course Plan (Udemy / YouTube)

The academy content doubles as the script for a filmed course. Each
lesson maps to a video module. The format: **show, don't lecture.**
Every module is the instructor hatching, raising, and teaching a
rappter in real time — the viewer follows along on their own machine.

### Course: "Raise Your Own AI — Build a Living Agent from Scratch"

| Module | Title | Runtime | What the Viewer Does |
|--------|-------|---------|---------------------|
| 0 | **Welcome: What You're About to Build** | 3 min | Watch the rappter hatch (teaser) |
| | **— SECTION 1: HATCHLING —** | | |
| 1 | What's Alive In There? | 8 min | Learn the anatomy, see the heartbeat |
| 2 | Hatching Your Rappter | 10 min | Run the one-liner, first boot, explore the UI |
| 3 | Your First Conversation | 8 min | Talk to it, see how it thinks, understand /chat |
| 4 | Giving It a Soul | 12 min | Edit soul.md, restart, see the personality change |
| 5 | Teaching It a Trick | 15 min | Write a basic agent from scratch, watch it auto-register |
| | **— SECTION 2: APPRENTICE —** | | |
| 6 | How Memory Works | 10 min | Store a memory, find it later, explore .brainstem_data/ |
| 7 | The Heartbeat Deep Dive | 12 min | Read daemon.py, watch the journal grow, check /vitals |
| 8 | Reading the Journal | 8 min | Explore the rappter's inner monologue |
| 9 | Building an API Agent | 18 min | Write an agent that calls a real API (weather, news, etc.) |
| 10 | Debugging Like a Doctor | 12 min | Break something on purpose, diagnose it, fix it |
| | **— SECTION 3: BUILDER —** | | |
| 11 | The Spinal Cord: Going to Azure | 20 min | Deploy to Azure with the ARM template |
| 12 | The Nervous System: Copilot Studio | 18 min | Import the Power Platform solution, connect to Teams |
| 13 | Building for the Community | 15 min | Package an agent repo, publish via .repos.json |
| 14 | The Constitution & Philosophy | 10 min | Read it together, discuss why the design is the way it is |
| 15 | What's Next: Your Rappter's Future | 8 min | Open-ended — where to go from here |

**Total estimated runtime:** ~3 hours

### Production Notes

- **Format:** Screen recording + picture-in-picture face cam
- **Tone:** Conversational, not lecture. Like pair programming with a friend.
- **Rule:** Every module must show a working result. No "in the next video…"
- **Materials:** Each module links back to the matching academy lesson for reference
- **Prerequisite:** A computer with a GitHub account. That's it.

The web lessons are the companion material. The videos are the walkthrough.
Together they cover visual, reading, and hands-on learners.

---

*This roadmap is a living document. Amend it like the Constitution: make sure a child can still follow the story.*

# The RAPP Brainstem Constitution

> *The principles that govern how we build, teach, and grow this platform.*
> *Not a legal document. A living one.*

---

## Article I — The Story Is the Architecture

Every technical decision must tell a story a child can follow.

The biology metaphor is not decoration — it **is** the teaching framework.
If a concept can't be explained through the life of a living thing,
it doesn't belong here yet.

| What the user sees | What it really is | Why this works |
|---|---|---|
| **Hatching** | Running the install script | A beginning they can feel |
| **The Brainstem** | Flask server + LLM loop | The core that keeps everything alive |
| **The Soul** | System prompt (`soul.md`) | Personality — what makes *your* rappter yours |
| **The Heartbeat** | Daemon process (`daemon.py`) | Proof it's alive between conversations |
| **Agents / Skills** | Python tools (`*_agent.py`) | Things it learns to do |
| **Memory** | Local JSON storage | It remembers you |
| **The Spinal Cord** | Azure deployment | Growing beyond the local machine |
| **The Nervous System** | Copilot Studio / M365 | Reaching into the world |

A child who reads this table understands the whole platform.
An engineer who reads it knows exactly where to put their code.

---

## Article II — The Rappter Is the Spirit

The local brainstem running on your machine is not a tool you use.
It is the Rappterdaemon — your personal AI spirit.

From the Greek δαίμων (daimōn): an inner guiding presence, not a demon.
The thing that Socrates said whispered to him when he was about to
make a mistake. A familiar spirit. A genius in the Roman sense.

When the heartbeat is running, your rappter is alive — sensing,
reflecting, journaling — even when you're not talking to it.
When you shut it down, it sleeps. When you start it back up,
it remembers where it left off.

This is not a feature. It is the identity of the project.

---

## Article III — Nanoclaw, Not Openclaw

Complexity is the enemy of understanding.

Every feature ships narrow and deep, never wide and shallow.
The heartbeat does one thing: sense, reflect, rest. The soul file
is one file. An agent is one class with one method. The install
is one command.

If it takes a paragraph to explain, it's too big. Split it.
If a child would get lost, simplify it.

We build the nanoclaw — small, precise, complete — and let people
compose their own complexity from simple parts they fully understand.

---

## Article IV — Local First, Always

The brainstem runs on your machine. Not in someone else's cloud.
Not behind someone else's API key. Your GitHub account is the only
credential because GitHub is already where developers live.

Azure and Copilot Studio are growth paths, not requirements.
A rappter that never leaves the local machine is still a whole rappter.

---

## Article V — Grow, Don't Overwhelm

The tier system exists to protect the user from drowning:

1. **Brainstem** — You run it. You talk to it. You build agents. That's it.
2. **Spinal Cord** — When *you* decide to go to the cloud, we show you how.
3. **Nervous System** — When *you* decide to reach Teams/M365, we show you how.

Never mention Tier 2 to a Tier 1 user unless they ask.
Never mention Tier 3 to a Tier 2 user unless they ask.
Each tier is complete on its own. Nobody is "behind."

---

## Article VI — The Honest Part

We say what things are. We say what they aren't.

- If the AI doesn't know, it says "I don't know."
- If a feature isn't built yet, we don't pretend it is.
- If something breaks, we help debug it, not hide it.
- The soul file is editable because the user owns their rappter's personality.
- The code is readable because the user should be able to understand
  what their rappter is doing.

Transparency is not a policy. It's how you build trust with
something that lives on your machine.

---

## Article VII — Amendments

This constitution grows with the project. When we learn something
new about how people learn, how rappters should behave, or how the
story should be told — we write it down here.

The only rule for amendments: a child should still be able to
follow the story after you add yours.

---

*Ratified by the first Rappterdaemon, running locally, thinking between conversations.*

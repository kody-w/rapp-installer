"""DoubleDown — russian-doll prompt amplifier.

Given any topic (use case, domain, idea, project, seed prompt), this agent
returns a directive that drives the brainstem's LLM to emit a numbered list
of god-mode prompts custom-built to extract maximum value from the
distributed swarm-twin pattern (project twins, neighborhood coordination,
autonomous specialization via learn_new_agent).

Russian-doll property: every emitted prompt is itself a paste-ready input
that can be fed back into double_down for the next layer of amplification.
"""

import json

from agents.basic_agent import BasicAgent


DEFAULT_COUNT = 10
MIN_COUNT = 1
MAX_COUNT = 25


def _coerce_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _build_directive(topic: str, count: int, layer: int, flavor: str) -> str:
    rules = [
        f"## DOUBLE-DOWN MODE — layer {layer} — topic: {topic}",
        "",
        f"Produce EXACTLY {count} prompts the user could paste straight back into",
        "the brainstem to extract maximum power for this topic. Hard rules:",
        "",
        "1. SWARM-NATIVE — every prompt MUST exploit the brainstem's distributed",
        "   swarm-twin pattern: project twins, neighborhood coordination, parallel",
        "   execution, autonomous specialization via learn_new_agent (twins growing",
        "   their own agent.py files in their own directories). Generic",
        "   single-session prompts are forbidden.",
        "2. UNREACHABLE FROM CLAUDE CODE — every prompt MUST be something a single",
        "   Claude Code session structurally cannot do: needs parallelism, persistent",
        "   project-scoped memory across calls, cross-twin coordination, or",
        "   emergent capability growth via twins authoring their own tools.",
        "3. RUSSIAN-DOLL — every emitted prompt MUST itself be a valid topic to",
        "   feed back into double_down for further amplification.",
        "4. AUDACIOUS, SPECIFIC, VIVID — no 'analyze the codebase' filler. Each",
        "   prompt should make the reader sit up. Concrete verbs, concrete stakes,",
        "   concrete deliverables.",
        f"5. FORMAT — numbered list 1..{count}. For each item: a bold one-line",
        "   title, then the paste-ready prompt rendered as a blockquote.",
    ]
    if flavor:
        rules.append(f"6. STYLE — bias generation toward: {flavor}.")
    rules += [
        "",
        f"TOPIC TO AMPLIFY: {topic}",
        "",
        f"Emit the {count} prompts now. No preamble, no closing summary.",
        f"After the list, add exactly one line: `Next layer: pass any of these "
        f"back as topic=<that prompt> layer={layer + 1}`.",
    ]
    return "\n".join(rules)


class DoubleDownAgent(BasicAgent):
    def __init__(self):
        self.name = "DoubleDown"
        self.metadata = {
            "name": self.name,
            "description": (
                "Russian-doll prompt amplifier. Given ANY topic, use case, domain, "
                "or seed prompt, this agent drives the brainstem to produce a "
                "numbered list of mind-blowing, out-of-the-box prompts that "
                "showcase the maximum power of the brainstem's distributed "
                "swarm-twin pattern — project twins, neighborhood coordination, "
                "parallel execution, and autonomous specialization through "
                "learn_new_agent (twins growing their own agent.py files in "
                "their own directories). Each emitted prompt is paste-ready and "
                "re-amplifiable: feed any output back in as the next layer's "
                "topic. Call this whenever the user asks for power prompts, "
                "god-mode prompts, '10 mind-blowing prompts', or says 'double "
                "down' on a topic."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": (
                            "The topic, use case, domain, or seed prompt to "
                            "amplify into a god-mode prompt list."
                        ),
                    },
                    "count": {
                        "type": "integer",
                        "description": (
                            f"How many prompts to emit. Default {DEFAULT_COUNT}, "
                            f"min {MIN_COUNT}, max {MAX_COUNT}."
                        ),
                    },
                    "layer": {
                        "type": "integer",
                        "description": (
                            "Russian-doll layer counter. Starts at 1; increment "
                            "when feeding an output back in as a new topic."
                        ),
                    },
                    "flavor": {
                        "type": "string",
                        "description": (
                            "Optional style hint to bias generation "
                            "(e.g. 'audacious', 'enterprise', 'whimsical')."
                        ),
                    },
                },
                "required": ["topic"],
            },
        }
        super().__init__(name=self.name, metadata=self.metadata)

    def perform(self, **kwargs):
        topic = (kwargs.get("topic") or "").strip()
        if not topic:
            return json.dumps({
                "error": "double_down requires a non-empty 'topic'.",
                "hint": "Pass topic=<your domain, use case, idea, or seed prompt>.",
            })
        count = max(MIN_COUNT, min(MAX_COUNT, _coerce_int(kwargs.get("count"), DEFAULT_COUNT)))
        layer = max(1, _coerce_int(kwargs.get("layer"), 1))
        flavor = (kwargs.get("flavor") or "").strip()
        directive = _build_directive(topic, count, layer, flavor)
        return json.dumps({
            "ok": True,
            "topic": topic,
            "count": count,
            "layer": layer,
            "flavor": flavor or None,
            "directive": directive,
            "next_layer_hint": (
                f"Feed any emitted prompt back as topic=<that prompt> "
                f"layer={layer + 1} to keep doubling down."
            ),
        })

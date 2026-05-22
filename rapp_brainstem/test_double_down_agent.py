"""Tests for agents/double_down_agent.py — the russian-doll prompt amplifier."""

import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from agents.double_down_agent import (  # noqa: E402
    DEFAULT_COUNT,
    MAX_COUNT,
    MIN_COUNT,
    DoubleDownAgent,
)
from agents.basic_agent import BasicAgent  # noqa: E402


class TestDoubleDownMetadata(unittest.TestCase):

    def setUp(self):
        self.agent = DoubleDownAgent()

    def test_extends_basic_agent(self):
        self.assertIsInstance(self.agent, BasicAgent)

    def test_name(self):
        self.assertEqual(self.agent.name, "DoubleDown")

    def test_metadata_has_required_fields(self):
        m = self.agent.metadata
        self.assertEqual(m["name"], "DoubleDown")
        self.assertIn("description", m)
        self.assertIn("parameters", m)

    def test_topic_is_required(self):
        params = self.agent.metadata["parameters"]
        self.assertEqual(params["required"], ["topic"])

    def test_known_optional_params_present(self):
        props = self.agent.metadata["parameters"]["properties"]
        for key in ["topic", "count", "layer", "flavor"]:
            self.assertIn(key, props)

    def test_to_tool_shape(self):
        tool = self.agent.to_tool()
        self.assertEqual(tool["type"], "function")
        self.assertEqual(tool["function"]["name"], "DoubleDown")
        self.assertIn("parameters", tool["function"])


class TestDoubleDownPerform(unittest.TestCase):

    def setUp(self):
        self.agent = DoubleDownAgent()

    def _call(self, **kwargs):
        out = self.agent.perform(**kwargs)
        self.assertIsInstance(out, str)
        return json.loads(out)

    # --- input validation -------------------------------------------------

    def test_empty_topic_returns_error(self):
        r = self._call()
        self.assertIn("error", r)

    def test_whitespace_topic_returns_error(self):
        r = self._call(topic="   \n  \t")
        self.assertIn("error", r)

    def test_none_topic_returns_error(self):
        r = self._call(topic=None)
        self.assertIn("error", r)

    # --- happy path -------------------------------------------------------

    def test_valid_topic_returns_ok(self):
        r = self._call(topic="microservices migration")
        self.assertTrue(r.get("ok"))
        self.assertEqual(r["topic"], "microservices migration")

    def test_topic_is_trimmed(self):
        r = self._call(topic="  swarm pattern  ")
        self.assertEqual(r["topic"], "swarm pattern")

    # --- count ------------------------------------------------------------

    def test_default_count(self):
        r = self._call(topic="X")
        self.assertEqual(r["count"], DEFAULT_COUNT)

    def test_custom_count_respected(self):
        r = self._call(topic="X", count=7)
        self.assertEqual(r["count"], 7)

    def test_count_clamped_to_max(self):
        r = self._call(topic="X", count=9999)
        self.assertEqual(r["count"], MAX_COUNT)

    def test_count_clamped_to_min(self):
        r = self._call(topic="X", count=-5)
        self.assertEqual(r["count"], MIN_COUNT)

    def test_invalid_count_falls_back_to_default(self):
        r = self._call(topic="X", count="not a number")
        self.assertEqual(r["count"], DEFAULT_COUNT)

    # --- layer ------------------------------------------------------------

    def test_default_layer(self):
        r = self._call(topic="X")
        self.assertEqual(r["layer"], 1)

    def test_custom_layer(self):
        r = self._call(topic="X", layer=4)
        self.assertEqual(r["layer"], 4)

    def test_layer_floor_is_one(self):
        r = self._call(topic="X", layer=0)
        self.assertEqual(r["layer"], 1)

    def test_layer_invalid_falls_back_to_one(self):
        r = self._call(topic="X", layer="nope")
        self.assertEqual(r["layer"], 1)

    # --- flavor -----------------------------------------------------------

    def test_flavor_optional(self):
        r = self._call(topic="X")
        self.assertIsNone(r["flavor"])

    def test_flavor_passthrough(self):
        r = self._call(topic="X", flavor="audacious")
        self.assertEqual(r["flavor"], "audacious")

    def test_flavor_appears_in_directive_when_set(self):
        r = self._call(topic="X", flavor="whimsical")
        self.assertIn("whimsical", r["directive"])

    def test_flavor_absent_from_directive_when_unset(self):
        r = self._call(topic="X")
        self.assertNotIn("STYLE — bias", r["directive"])

    # --- directive content guarantees ------------------------------------

    def test_directive_mentions_swarm_terms(self):
        r = self._call(topic="ANY")
        d = r["directive"].lower()
        self.assertIn("twin", d)
        self.assertTrue("swarm" in d or "neighborhood" in d)
        self.assertIn("learn_new_agent", d)

    def test_directive_mentions_russian_doll(self):
        r = self._call(topic="ANY")
        self.assertIn("russian-doll", r["directive"].lower())

    def test_directive_mentions_claude_code_unreachable(self):
        r = self._call(topic="ANY")
        self.assertIn("claude code", r["directive"].lower())

    def test_directive_includes_topic_verbatim(self):
        sentinel = "QUANTUM_BCHYDRO_X"
        r = self._call(topic=sentinel)
        self.assertIn(sentinel, r["directive"])

    def test_directive_count_matches(self):
        r = self._call(topic="X", count=13)
        self.assertIn("13", r["directive"])

    def test_directive_includes_layer_label(self):
        r = self._call(topic="X", layer=3)
        self.assertIn("layer 3", r["directive"])

    def test_next_layer_hint_increments(self):
        r = self._call(topic="X", layer=3)
        self.assertIn("layer=4", r["next_layer_hint"])

    def test_directive_contains_next_layer_instruction(self):
        r = self._call(topic="X", layer=2)
        self.assertIn("layer=3", r["directive"])


if __name__ == "__main__":
    unittest.main()

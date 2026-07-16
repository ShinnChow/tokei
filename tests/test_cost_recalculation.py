import unittest

from test_codex_limits import USAGE


class CostRecalculationTests(unittest.TestCase):
    def test_gemini_thoughts_are_priced_as_output(self):
        name = "Gemini 3.5 Flash"
        model = {
            "name": name,
            "in": 100,
            "out": 20,
            "cached": 30,
            "thoughts": 40,
            "cost": 0.0,
        }
        result = {"gemini": {"ranges": {"today": {"models": [model], "cost": 0.0}}}}

        USAGE._recalc_costs(result)

        price = USAGE._raw_price(USAGE._pricing_id(name))
        expected = (
            100 * price["in"]
            + 30 * price["cache_read"]
            + 60 * price["out"]
        ) / 1_000_000
        self.assertGreater(expected, 0)
        self.assertAlmostEqual(model["cost"], expected, places=6)
        self.assertAlmostEqual(result["gemini"]["ranges"]["today"]["cost"], expected, places=6)

    def test_authoritative_tool_costs_are_preserved(self):
        for tool in ("claude", "pi", "hermes", "opencode", "openclaw"):
            model = {
                "name": "GPT-5.5",
                "in": 100,
                "out": 20,
                "cr": 30,
                "cw": 4,
                "cost": 42.0,
            }
            result = {tool: {"ranges": {"today": {"models": [model], "cost": 42.0}}}}

            USAGE._recalc_costs(result)

            self.assertEqual(model["cost"], 42.0, tool)
            self.assertEqual(result[tool]["ranges"]["today"]["cost"], 42.0, tool)


if __name__ == "__main__":
    unittest.main()

import unittest

from backend.services.capabilities import detect_source_capabilities


class CapabilityTests(unittest.TestCase):
    def test_detects_actions_from_structure_not_variable_names(self):
        source = '''
def agent(obs):
    crop = "WHEAT" if obs["day"] < 5 else "CARROT"
    action = ["BUY_LAND"] if obs["farms"][obs["player"]]["money"] > 5000 else []
    return {"farmer": ["PASS"], "hands": [], "market": action}
'''
        result = {item["id"]: item["detected"] for item in detect_source_capabilities(source)}
        self.assertTrue(result["core"])
        self.assertTrue(result["crop_mix"])
        self.assertTrue(result["season"])
        self.assertTrue(result["expansion"])

    def test_does_not_claim_unsupported_livestock(self):
        result = {item["id"]: item["detected"] for item in detect_source_capabilities("def agent(obs): return {}")}
        self.assertFalse(result["animals"])


if __name__ == "__main__":
    unittest.main()

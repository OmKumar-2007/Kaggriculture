import unittest
from pathlib import Path

from backend.services.validator import AgentValidationError, inspect_agent_source, validate_agent_source


ROOT = Path(__file__).resolve().parents[1]


class ValidatorTests(unittest.TestCase):
    def test_accepts_tracked_contestant_starter(self):
        source = (ROOT / "contestant_starter" / "agent.py").read_text(encoding="utf-8")
        report = validate_agent_source(source)
        self.assertTrue(report.valid)

    def test_reports_syntax_line(self):
        report = inspect_agent_source("def agent(obs)\n    return {}\n")
        self.assertFalse(report.valid)
        self.assertIn("line 1", report.errors[0])

    def test_requires_agent_function(self):
        with self.assertRaisesRegex(AgentValidationError, "function not found"):
            validate_agent_source("def helper(obs):\n    return {}\n")

    def test_rejects_dangerous_import(self):
        source = "import subprocess\n\ndef agent(obs):\n    return {'farmer': ['PASS'], 'hands': [], 'market': []}\n"
        with self.assertRaisesRegex(AgentValidationError, "subprocess"):
            validate_agent_source(source)

    def test_warns_for_dynamic_action_shape(self):
        source = "def agent(obs):\n    action = {}\n    return action\n"
        report = validate_agent_source(source)
        self.assertTrue(report.valid)
        self.assertTrue(report.warnings)


if __name__ == "__main__":
    unittest.main()

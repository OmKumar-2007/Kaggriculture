"""Static validation for single-file Harvest Protocol agents."""

from __future__ import annotations

import ast
from dataclasses import asdict, dataclass, field


MAX_AGENT_BYTES = 100_000
FORBIDDEN_MODULES = {
    "ctypes", "http", "importlib", "multiprocessing", "os", "pathlib",
    "requests", "shutil", "socket", "subprocess", "threading", "urllib",
}
FORBIDDEN_CALLS = {"breakpoint", "compile", "eval", "exec", "input", "open", "__import__"}
REQUIRED_ACTION_KEYS = {"farmer", "hands", "market"}


class AgentValidationError(ValueError):
    """Raised when contestant source cannot be accepted."""


@dataclass
class ValidationReport:
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _qualified_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _qualified_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def inspect_agent_source(source: str) -> ValidationReport:
    errors: list[str] = []
    warnings: list[str] = []

    if len(source.encode("utf-8")) > MAX_AGENT_BYTES:
        errors.append(f"Agent exceeds the {MAX_AGENT_BYTES // 1000} KB size limit.")

    try:
        tree = ast.parse(source, filename="agent.py")
    except SyntaxError as exc:
        location = f"line {exc.lineno}"
        if exc.offset:
            location += f", column {exc.offset}"
        return ValidationReport(False, [f"SyntaxError at {location}: {exc.msg}"], warnings)

    agents = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "agent"]
    async_agents = [node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "agent"]
    if not agents:
        if async_agents:
            errors.append("agent(obs) must be a normal function, not async.")
        else:
            errors.append("agent(obs) function not found.")
    elif len(agents[0].args.args) != 1:
        errors.append("agent must accept exactly one argument: agent(obs).")

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in FORBIDDEN_MODULES:
                    errors.append(f"Line {node.lineno}: import '{alias.name}' is not allowed.")
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if root in FORBIDDEN_MODULES:
                errors.append(f"Line {node.lineno}: import from '{node.module}' is not allowed.")
        elif isinstance(node, ast.Call):
            name = _qualified_name(node.func)
            root = name.split(".")[0]
            if name in FORBIDDEN_CALLS or root in FORBIDDEN_MODULES:
                errors.append(f"Line {node.lineno}: call '{name}' is not allowed.")

    literal_returns = [node.value for node in ast.walk(agents[0]) if isinstance(node, ast.Return)] if agents else []
    literal_dicts = [node for node in literal_returns if isinstance(node, ast.Dict)]
    if literal_dicts:
        has_action_shape = any(
            REQUIRED_ACTION_KEYS.issubset({key.value for key in item.keys if isinstance(key, ast.Constant)})
            for item in literal_dicts
        )
        if not has_action_shape:
            warnings.append("No literal return containing farmer, hands, and market was found. Dynamic returns are allowed, but verify the action schema in Sandbox.")
    else:
        warnings.append("The action shape is dynamic. Run a Sandbox match before submitting.")

    return ValidationReport(not errors, list(dict.fromkeys(errors)), warnings)


def validate_agent_source(source: str) -> ValidationReport:
    report = inspect_agent_source(source)
    if not report.valid:
        raise AgentValidationError("\n".join(report.errors))
    return report


def validate_action_shape(action: object, hand_count: int | None = None) -> list[str]:
    errors: list[str] = []
    if not isinstance(action, dict):
        return ["Agent action must be a dictionary."]
    missing = REQUIRED_ACTION_KEYS - set(action)
    if missing:
        errors.append(f"Action is missing: {', '.join(sorted(missing))}.")
    if "farmer" in action and not isinstance(action["farmer"], list):
        errors.append("farmer action must be a list.")
    if "hands" in action and not isinstance(action["hands"], list):
        errors.append("hands actions must be a list.")
    elif hand_count is not None and len(action.get("hands", [])) != hand_count:
        errors.append(f"Expected {hand_count} hand actions, received {len(action.get('hands', []))}.")
    if "market" in action and not isinstance(action["market"], list):
        errors.append("market actions must be a list.")
    return errors

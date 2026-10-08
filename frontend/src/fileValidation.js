export function agentFileError(file) {
  if (!file) return "Choose agent.py or main.py first.";
  if (!["agent.py", "main.py"].includes(file.name.toLowerCase())) return "Use a single file named agent.py or main.py.";
  if (file.size === 0) return "The Python file is empty.";
  if (file.size > 256 * 1024) return "The Python file exceeds the 256 KB upload limit.";
  return null;
}

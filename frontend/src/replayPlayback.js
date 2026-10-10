export const REPLAY_TURN_MS = 60;

export function nextReplayStep(step, totalSteps) {
  if (!Number.isInteger(totalSteps) || totalSteps < 1) return 0;
  return Math.min(step + 1, totalSteps - 1);
}

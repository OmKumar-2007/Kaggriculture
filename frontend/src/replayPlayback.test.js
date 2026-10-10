import test from "node:test";
import assert from "node:assert/strict";
import { REPLAY_TURN_MS, nextReplayStep } from "./replayPlayback.js";

test("replay always advances at fixed 10x timing", () => {
  assert.equal(REPLAY_TURN_MS, 60);
  assert.equal(nextReplayStep(0, 2), 1);
  assert.equal(nextReplayStep(1, 2), 1);
  assert.equal(nextReplayStep(0, 0), 0);
});

import test from "node:test";
import assert from "node:assert/strict";

import {
  formatApiError,
  safeLatencyMs,
  isSessionTermination
} from "./sessionUtils.js";

test("FastAPI validation errors become readable", () => {
  const detail = [
    { loc: ["body", "latencyMs"], msg: "Input should be less than or equal to 10000" }
  ];

  assert.match(formatApiError(detail), /less than or equal to 10000/);
  assert.doesNotMatch(formatApiError(detail), /\[object Object\]/);
});

test("ordinary error strings remain readable", () => {
  assert.equal(formatApiError("Session expired"), "Session expired");
  assert.equal(formatApiError({}, "Request failed."), "Request failed.");
});

test("heartbeat latency remains valid", () => {
  assert.equal(safeLatencyMs(125), 125);
  assert.equal(safeLatencyMs(15000), 10000);
  assert.equal(safeLatencyMs(-1), null);
  assert.equal(safeLatencyMs(Infinity), null);
  assert.equal(safeLatencyMs(null), null);
});

test("only actual session termination triggers logout", () => {
  assert.equal(isSessionTermination(401), true);
  assert.equal(isSessionTermination(423), true);
  assert.equal(isSessionTermination(422), false);
  assert.equal(isSessionTermination(429), false);
  assert.equal(isSessionTermination(500), false);
  assert.equal(isSessionTermination(403), false);
});

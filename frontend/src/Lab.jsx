import { formatApiError } from "./sessionUtils.js";
import { useCallback, useEffect, useState } from "react";
import { STRATEGY_MISSIONS } from "./strategyMissions.js";
import GuidePage from "./GuidePage.jsx";
import { API_BASE, participantFetch } from "./participantApi.js";
import { agentFileError } from "./fileValidation.js";


const money = (value) => value === null || value === undefined ? "—" : Number(value).toLocaleString();
const date = (value) => value ? new Date(value).toLocaleString() : "—";

async function api(path, options) {
  const response = await participantFetch(path, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(formatApiError(data.detail, "Request failed."));
  }
  return data;
}

export default function ContestantPortal({ section, onNavigate, identity }) {
  const team = identity.team;
  const [summary, setSummary] = useState(null);
  const [agentFile, setAgentFile] = useState(null);
  const [opponents, setOpponents] = useState([]);
  const [opponent, setOpponent] = useState("starter_crop");
  const [seed, setSeed] = useState("20260929");
  const [analytics, setAnalytics] = useState(null);
  const [leaderboard, setLeaderboard] = useState(null);
  const [message, setMessage] = useState(null);
  const [busy, setBusy] = useState(false);
  const [activeJob, setActiveJob] = useState(null);

  const loadSummary = useCallback(async (name) => {
    if (!name) { setSummary(null); return; }
    try { setSummary(await api(`/botlab/${encodeURIComponent(name)}`)); }
    catch (error) { setMessage({ type: "error", text: error.message }); }
  }, []);

  useEffect(() => {
    if (!team) return undefined;
    const timer = window.setTimeout(() => { void loadSummary(team); }, 0);
    return () => window.clearTimeout(timer);
  }, [team, loadSummary]);
  useEffect(() => {
    if (!team) return undefined;
    const saved = localStorage.getItem(`neural-coliseum-job-${team}`);
    if (saved) api(`/jobs/${saved}`).then((job) => {
      if (["queued", "running"].includes(job.status)) setActiveJob(job);
      else localStorage.removeItem(`neural-coliseum-job-${team}`);
    }).catch(() => localStorage.removeItem(`neural-coliseum-job-${team}`));
  }, [team]);
  useEffect(() => {
    if (!activeJob?.id || !["queued", "running"].includes(activeJob.status)) return undefined;
    const stream = new EventSource(`${API_BASE}/jobs/${activeJob.id}/events`, { withCredentials: true });
    let finished = false;
    const handleUpdate = async (job) => {
      if (finished) return;
      setActiveJob(job);
      if (["completed", "failed", "timeout", "cancelled"].includes(job.status)) {
        finished = true;
        stream.close(); localStorage.removeItem(`neural-coliseum-job-${team}`); await loadSummary(team);
        setMessage(job.status === "completed" ? { type: "success", text: job.type === "sandbox" ? "Sandbox completed. Results and replay are ready." : `Official evaluation completed. Rating: ${money(job.result?.rating)}` } : job.status === "cancelled" ? { type: "info", text: "Evaluation cancelled by the organizer." } : { type: "error", text: job.errorKind === "contestant" ? `Your bot failed: ${job.error}` : `Simulation infrastructure failed: ${job.error}` });
      }
    };
    stream.addEventListener("job", (event) => { void handleUpdate(JSON.parse(event.data)); });
    stream.onerror = () => stream.close();
    const poll = window.setInterval(() => { void api(`/jobs/${activeJob.id}`).then(handleUpdate).catch(() => {}); }, 5000);
    return () => { stream.close(); window.clearInterval(poll); };
  }, [activeJob?.id, activeJob?.status, loadSummary, team]);
  useEffect(() => { api("/sandbox/opponents").then((data) => setOpponents(data.opponents || [])).catch(() => {}); }, []);
  useEffect(() => {
    const replayId = summary?.lastTest?.replay_id;
    if (replayId && ["lab", "sandbox", "analytics"].includes(section)) api(`/replays/${replayId}/analytics`).then(setAnalytics).catch((error) => setMessage({ type: "error", text: error.message }));
  }, [section, summary?.lastTest?.replay_id]);
  useEffect(() => {
    if (section === "leaderboard") api("/leaderboard").then(setLeaderboard).catch((error) => setMessage({ type: "error", text: error.message }));
  }, [section]);

  async function upload() {
    const fileError = agentFileError(agentFile);
    if (fileError) { setMessage({ type: "error", text: fileError }); return; }
    const body = new FormData(); body.append("username", team); body.append("agent", agentFile); setBusy(true);
    try {
      const data = await api("/botlab/upload", { method: "POST", body });
      setMessage({ type: data.validation.valid ? "success" : "error", text: data.validation.valid ? `v${data.submission.version} uploaded and validated.` : data.validation.errors.join("\n") });
      await loadSummary(team);
    } catch (error) { setMessage({ type: "error", text: error.message }); } finally { setBusy(false); }
  }

  async function command(path, body) {
    if (!team) { setMessage({ type: "error", text: "Set your team first." }); return null; }
    setBusy(true);
    try { const data = await api(`/botlab/${encodeURIComponent(team)}${path}`, { method: "POST", body }); if (data.id) { setActiveJob(data); localStorage.setItem(`neural-coliseum-job-${team}`, data.id); } await loadSummary(team); return data; }
    catch (error) { setMessage({ type: "error", text: error.message }); return null; } finally { setBusy(false); }
  }

  async function validate() {
    const data = await command("/validate");
    if (data) setMessage({ type: data.valid ? "success" : "error", text: data.valid ? (data.warnings?.[0] || "Validation passed.") : data.errors.join("\n") });
  }

  async function runSandbox() {
    const body = new FormData(); body.append("opponent", opponent); body.append("seed", seed);
    const data = await command("/sandbox", body);
    if (data) setMessage({ type: "info", text: data.queuePosition ? `Sandbox queued · ${data.queuePosition - 1} job${data.queuePosition === 2 ? "" : "s"} ahead.` : "Sandbox queued." });
  }

  async function submit() {
    const data = await command("/submit");
    if (data) setMessage({ type: "info", text: data.queuePosition ? `Official evaluation queued · ${data.queuePosition - 1} ahead.` : data.message });
  }

  const current = summary?.currentSubmission;
  const lastTest = summary?.lastTest;
  const detected = summary?.capabilities?.filter((item) => item.detected) || [];
  const nextInsight = analytics?.diagnostics?.[0];

  if (section === "guide") return <GuidePage onNavigate={onNavigate} />;
  if (section === "leaderboard") return <main className="portal-page"><PageHead code="06" title="Leaderboard" copy="Official ratings combine hidden opponents, multiple seeds, and both starting positions." /><Leaderboard data={leaderboard} /></main>;
  if (section === "strategy") return <StrategyPath summary={summary} onNavigate={onNavigate} />;

  return <main className={`portal-page portal-${section}`}>
    <PageHead code={section === "sandbox" ? "03" : section === "analytics" ? "04" : section === "submissions" ? "05" : "01"} title={section === "sandbox" ? "Sandbox" : section === "analytics" ? "Match analytics" : section === "submissions" ? "Submission history" : "Bot laboratory"} copy={section === "lab" ? "Build, validate, test, and activate one understandable strategy at a time." : "Use public development results to improve your next version."} />
    <>
      <div className="portal-identity"><span>ACTIVE TEAM</span><b>{team}</b><small>ID {identity.teamId}</small></div>
      {message && <div className={`notice ${message.type}`}>{message.text}</div>}
      {activeJob && <JobStatus job={activeJob} />}

      {section === "lab" && <>
        <section className="lab-command"><div><span>ACTIVE CONTENDER</span><h2>{team}</h2><p>{summary?.currentVersion || "No build"} · {summary?.submissionCount || 0} saved versions · {summary?.sandboxRunCount || 0} arena tests</p></div><div className="command-rating"><small>LEADERBOARD</small><strong>{summary?.leaderboardRank ? `#${summary.leaderboardRank}` : "UNRANKED"}</strong><em>{summary?.winRate != null ? `${Number(summary.winRate).toFixed(1)}% win rate` : "Submit an official build"}</em></div><button className="button primary" disabled={busy || !current || ["queued","running"].includes(activeJob?.status)} onClick={() => onNavigate("sandbox")}>Launch test</button></section>
        <div className="lab-stats"><Stat label="Current bot" value={summary?.currentVersion || "—"} /><Stat label="Validation" value={summary?.validationStatus || "Not uploaded"} tone={summary?.validationStatus === "valid" ? "lime" : ""} /><Stat label="Last test" value={lastTest ? `${money(lastTest.bot_money)} credits` : "—"} /><Stat label="Best score" value={money(summary?.bestScore)} tone="amber" /></div>
        <div className="insight-grid"><section className="lab-panel capability-panel"><div className="panel-label">CURRENT STRATEGY PROFILE <b>{detected.length}/{summary?.capabilities?.length || 9} SIGNALS</b></div><div className="capability-list">{(summary?.capabilities || []).map((item) => <div className={item.detected ? "detected" : "missing"} key={item.id}><span>{item.detected ? "✓" : "○"}</span>{item.label}</div>)}{!summary?.capabilities?.length && <p>Upload a bot to map its current capabilities.</p>}</div></section><section className="lab-panel next-insight"><div className="panel-label">NEXT INSIGHT</div><span className="insight-kicker">{nextInsight ? "MATCH EVIDENCE" : "STRATEGY PATH"}</span><h3>{nextInsight?.title || "Build one capability at a time"}</h3><p>{nextInsight?.detail || "Start with a working farm loop, then use arena evidence to choose the next focused improvement."}</p><button className="button" onClick={() => onNavigate(nextInsight ? "analytics" : "strategy")}>{nextInsight ? "Inspect evidence" : "Open strategy path"}</button></section></div>
        <div className="lab-grid"><section className="lab-panel"><div className="panel-label">BOT BUILD</div><div className={`file-target ${agentFile ? "loaded" : ""}`}><input type="file" accept=".py" onChange={(event) => setAgentFile(event.target.files?.[0] || null)} /><span>{agentFile ? "AGENT READY" : "SELECT AGENT.PY OR MAIN.PY"}</span><b>{agentFile?.name || "Single Python file · 256 KB maximum"}</b></div><div className="lab-actions"><button className="button primary" disabled={busy} onClick={upload}>Upload bot</button><button className="button" disabled={busy || !current} onClick={validate}>Validate current</button></div></section>
          <section className="lab-panel"><div className="panel-label">DEVELOPMENT FLOW</div><ol className="lab-flow"><li><b>1</b>Download the starter</li><li><b>2</b>Ask an LLM for one focused change</li><li><b>3</b>Upload and validate</li><li><b>4</b>Run public sandbox seeds</li><li><b>5</b>Activate your best version</li></ol><div className="lab-actions"><a className="button" href={`${API_BASE}/starter/download`}>Download starter</a><button className="button" onClick={() => onNavigate("guide")}>Game guide</button></div></section>
          <section className="lab-panel active-build"><div className="panel-label">ROUND 1 — QUALIFICATION</div><strong>{summary?.activeSubmission ? `Best rated build v${summary.activeSubmission.version}` : "No rated build yet"}</strong><p>{summary?.qualificationPhase === "QUALIFICATION_OPEN" ? `Official submission remaining: ${summary?.officialAttempts?.remaining ?? "—"}. Top ${summary?.qualifierCount ?? "—"} advance.` : `Current phase: ${summary?.qualificationPhase || "SETUP"}.`}{summary?.qualified ? " You qualified for Round 2." : ""}</p><button className="button primary wide" disabled={busy || summary?.qualificationPhase !== "QUALIFICATION_OPEN" || !summary?.officialAttempts?.remaining || !current || current.validation_status !== "valid" || ["queued","running"].includes(activeJob?.status)} onClick={submit}>Submit official bot</button></section>
        </div>
      </>}

      {section === "sandbox" && <><div className="arena-versus"><div><span>YOUR BOT</span><strong>{team}</strong><small>{summary?.currentVersion || "NO BUILD"}</small></div><i>VS</i><div className="opponent-select"><span>DEVELOPMENT RIVAL</span><strong>{opponents.find((item) => item.id === opponent)?.name || "Select rival"}</strong><small>PUBLIC BENCHMARK</small></div></div><div className="sandbox-grid"><section className="lab-panel"><div className="panel-label">TEST ARENA CONFIGURATION</div><label className="lab-field">Public opponent<select value={opponent} onChange={(event) => setOpponent(event.target.value)}>{opponents.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><label className="lab-field">Public seed<input type="number" min="0" max="2147483647" value={seed} onChange={(event) => setSeed(event.target.value)} /></label><button className="button primary wide" disabled={busy || !current || ["queued","running"].includes(activeJob?.status)} onClick={runSandbox}>{activeJob?.type === "sandbox" && ["queued","running"].includes(activeJob.status) ? "Match in queue" : "Launch match"}</button></section><ResultCard result={lastTest} team={team} /></div>{analytics?.diagnostics?.length > 0 && <Diagnostics items={analytics.diagnostics} onNavigate={onNavigate} />}</>}

      {section === "analytics" && <><div className="analytics-grid"><Stat label="Final cash" value={money(analytics?.finalCash ?? lastTest?.bot_money)} tone="lime" /><Stat label="Peak cash" value={money(analytics?.peakCash)} /><Stat label="Minimum cash" value={money(analytics?.minimumCash)} /><Stat label="Unsold value" value={money(analytics?.finalUnsoldValue)} /><Stat label="Land unlocked" value={analytics ? `${analytics.landQuadrantsUnlocked}/4` : "—"} /><Stat label="Farm utilization" value={analytics ? `${analytics.farmUtilization}%` : "—"} /><Stat label="Movement load" value={analytics ? `${analytics.movementRate}%` : "—"} /><Stat label="Idle load" value={analytics ? `${analytics.idleRate}%` : "—"} /></div>{analytics?.series?.length ? <div className="chart-grid"><LineChart title="Money vs time" data={analytics.series} field="money" color="#b9ff38" /><LineChart title="Workers vs time" data={analytics.series} field="workers" color="#ffb11b" /><LineChart title="Farm utilization" data={analytics.series} field="utilization" color="#f1f0e8" suffix="%" /></div> : <div className="portal-empty chart-placeholder">Run a new sandbox match to capture replay-backed analytics.</div>}{analytics?.diagnostics?.length > 0 && <Diagnostics items={analytics.diagnostics} onNavigate={onNavigate} />}{lastTest?.replay_id && <ReplayViewer key={lastTest.replay_id} replayId={lastTest.replay_id} />}</>}

      {section === "submissions" && <SubmissionTable items={summary?.submissions || []} />}
    </>
  </main>;
}

function JobStatus({ job }) {
  const total = job.progressTotal; const current = job.progressCurrent;
  const progress = total ? Math.min(100, Math.max(0, Math.round(((current || 0) / total) * 100))) : null;
  return <section className={`job-status job-${job.status}`} aria-live="polite"><div><span>{job.type === "official" ? "OFFICIAL EVALUATION" : job.type === "tournament" ? "TOURNAMENT JOB" : "SANDBOX JOB"}</span><strong>{job.status.toUpperCase()}</strong></div><p>{job.status === "queued" ? (job.queuePosition ? `${job.queuePosition - 1} jobs ahead of you` : "Waiting for an available worker") : job.status === "running" && total ? `Running game ${Math.min((current || 0) + 1, total)} / ${total}` : job.status === "running" ? "Simulation worker active" : job.status === "completed" ? "Results saved" : job.error || "Job stopped"}</p>{progress !== null && <div className="job-progress" role="progressbar" aria-label="Evaluation progress" aria-valuemin="0" aria-valuemax="100" aria-valuenow={progress}><i style={{ width: `${progress}%` }} /></div>}</section>;
}

function PageHead({ code, title, copy }) { return <header className={`portal-head portal-head-${code}`}><span>{code} / FARMCRAFT</span><h1>{title}</h1><p>{copy}</p></header>; }
function Stat({ label, value, tone = "" }) { return <div className={`lab-stat ${tone}`}><span>{label}</span><b>{value}</b></div>; }
function ResultCard({ result, team }) { return <section className="lab-panel sandbox-result"><div className="panel-label">LAST TEST RESULT</div>{result ? <><span className="result-status">{result.status}</span><h2>{result.status === "contestant_error" ? "Bot execution failed" : result.winner === "bot" ? `${team} wins` : result.winner === "tie" ? "Draw" : "Opponent wins"}</h2><div className="sandbox-score"><b>{money(result.bot_money)}</b><span>—</span><b>{money(result.opponent_money)}</b></div><p>{result.opponent} · seed {result.seed} · {Number(result.runtime_seconds).toFixed(2)}s</p>{result.error && <pre className="sandbox-error">{result.error}</pre>}</> : <div className="empty-state">No sandbox result yet.</div>}</section>; }
function SubmissionTable({ items }) { return <div className="submission-table"><div className="submission-row head"><span>Version</span><span>Uploaded</span><span>Validation</span><span>Sandbox</span><span>Official</span><span>Runtime</span><span>State</span></div>{items.map((item) => <div className="submission-row" key={item.id}><b>v{item.version}</b><span>{date(item.created_at)}</span><span className={item.validation_status === "valid" ? "valid" : "invalid"}>{item.validation_status}</span><span>{money(item.sandbox_score)}</span><span>{money(item.official_score)}</span><span>{item.runtime_seconds ? `${Number(item.runtime_seconds).toFixed(2)}s` : "—"}</span><span>{item.is_active ? "ACTIVE" : "ARCHIVED"}</span></div>)}{!items.length && <div className="portal-empty">No versions uploaded.</div>}</div>; }

function StrategyPath({ summary, onNavigate }) {
  const [copied, setCopied] = useState("");
  const [selected, setSelected] = useState(null);
  const [strategyError, setStrategyError] = useState("");
  useEffect(() => { api("/api/participants/strategy").then((data) => setSelected(data.missionId)).catch(() => {}); }, []);
  async function copyMission(mission) {
    await navigator.clipboard.writeText(mission.prompt);
    setCopied(mission.id); window.setTimeout(() => setCopied(""), 1600);
  }
  async function selectMission(mission) {
    try {
      const response = await api("/api/participants/strategy", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ missionId: mission.id }) });
      setSelected(response.missionId); setStrategyError("");
    } catch (error) { setStrategyError(error.message); }
  }
  return <main className="portal-page strategy-page">
    <PageHead code="02" title="Strategy path" copy="All nine strategy guides are available from day one. Choose a focus, then test your ideas in the arena." />
    <div className="path-legend"><span><i className="open" />All strategies available</span><b>{summary?.sandboxRunCount || 0} arena tests completed</b></div>
    {strategyError && <div className="notice error" role="alert">{strategyError}</div>}
    <div className="mission-grid">{STRATEGY_MISSIONS.map((mission) => <article className={`mission-card unlocked ${selected === mission.id ? "selected" : ""}`} key={mission.id}>
      <div className="mission-top"><span>STRATEGY {String(mission.level).padStart(2, "0")}</span><em>{mission.branch}</em></div>
      <h2>{mission.title}</h2><p>{mission.concept}</p>
      <div className="mission-detail"><small>PROBLEM</small>{mission.problem}</div><div className="mission-detail"><small>FIELD HINT</small>{mission.hint}</div>
      <div className="mission-actions"><button className={selected === mission.id ? "selected" : ""} onClick={() => selectMission(mission)}>{selected === mission.id ? "Selected focus" : "Select focus"}</button><button onClick={() => copyMission(mission)}>{copied === mission.id ? "Copied" : "Copy prompt"}</button></div>
    </article>)}</div>
    <button className="button primary path-cta" onClick={() => onNavigate("sandbox")}>Test current bot</button>
  </main>;
}

function Diagnostics({ items, onNavigate }) {
  const [copied, setCopied] = useState("");
  async function copy(item) { await navigator.clipboard.writeText(item.prompt); setCopied(item.title); window.setTimeout(() => setCopied(""), 1500); }
  return <section className="diagnostics"><div className="panel-label">WHAT WENT WRONG? <b>DERIVED FROM MATCH TELEMETRY</b></div><div className="diagnostic-grid">{items.map((item) => <article key={item.title}><span>FIELD SIGNAL</span><h3>{item.title}</h3><p>{item.detail}</p><div><button onClick={() => onNavigate("strategy")}>View lesson</button><button onClick={() => copy(item)}>{copied === item.title ? "Copied" : "Copy prompt"}</button></div></article>)}</div></section>;
}

function Leaderboard({ data }) {
  const entries = data?.entries || [];
  const qualifierTotal = data?.qualifierCount;
  const finalized = ["QUALIFICATION_FINALIZED", "TOURNAMENT_READY", "TOURNAMENT_RUNNING", "TOURNAMENT_COMPLETED"].includes(data?.phase);
  return <><div className="leaderboard-meta"><div><span>ROUND 1 — QUALIFICATION</span><b>{data ? `${data.evaluationGames} games per official attempt` : "Loading…"}</b><p>{data?.sideSwapped ? "Each reference opponent is played from both positions." : "Configured event format."}</p></div><div className="qualifier-note">{qualifierTotal ? `TOP ${qualifierTotal} ADVANCE TO ROUND 2` : "Qualifier cutoff loading…"}</div></div><div className="leaderboard-table"><div className="leaderboard-row head"><span>Rank</span><span>Team</span><span>Rating</span><span>Win rate</span><span>Avg. cash</span><span>Games</span><span>Status</span></div>{entries.map((entry) => { const qualifying = finalized ? data.qualifiedTeams?.includes(entry.team) : entry.rank <= qualifierTotal; return <div className={`leaderboard-row ${entry.rank === 1 ? "podium-first" : ""} ${qualifying ? "in-qualifiers" : ""} ${qualifierTotal && entry.rank === qualifierTotal + 1 ? "cutoff-row" : ""}`} key={entry.team}><strong>#{entry.rank}</strong><b>{entry.team}</b><span className="rating">{money(entry.rating)}</span><span>{Number(entry.winRate).toFixed(1)}%</span><span>{money(entry.averageFinalMoney)}</span><span>{entry.games}</span><span className={`qualification-tag ${qualifying ? "qualifying" : ""}`}>{finalized ? qualifying ? "Qualified" : "Not qualified" : qualifying ? "Currently in qualifying positions" : "Outside current cutoff"}</span></div>; })}{!entries.length && <div className="portal-empty">No completed Round 1 evaluations yet.</div>}</div></>;
}

function LineChart({ title, data, field, color, suffix = "" }) {
  const values = data.map((item) => Number(item[field] || 0));
  const min = Math.min(...values); const max = Math.max(...values); const span = max - min || 1;
  const points = values.map((value, index) => `${(index / Math.max(1, values.length - 1)) * 100},${92 - ((value - min) / span) * 78}`).join(" ");
  return <section className="mini-chart"><div><span>{title}</span><b>{money(values.at(-1))}{suffix}</b></div><svg viewBox="0 0 100 100" preserveAspectRatio="none"><polyline points={points} fill="none" stroke={color} strokeWidth="2" vectorEffect="non-scaling-stroke" /></svg><small>{money(min)} → {money(max)}{suffix}</small></section>;
}

export function ReplayViewer({ replayId }) {
  const [frame, setFrame] = useState(null); const [step, setStep] = useState(0); const [playing, setPlaying] = useState(false); const [speed, setSpeed] = useState(1); const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    api(`/replays/${replayId}/frame/${step}`, { signal: controller.signal }).then((next) => { setFrame(next); setError(""); }).catch((failure) => { if (failure.name !== "AbortError") { setPlaying(false); setError(failure.message); } });
    return () => controller.abort();
  }, [replayId, step]);
  useEffect(() => {
    if (!playing || frame?.step !== step) return undefined;
    if (step >= frame.totalSteps - 1) return undefined;
    const timer = window.setTimeout(() => { setStep((value) => value + 1); if (step + 1 >= frame.totalSteps - 1) setPlaying(false); }, 600 / speed);
    return () => window.clearTimeout(timer);
  }, [playing, frame, speed, step]);
  const seek = (next) => { setPlaying(false); setStep(next); };
  const farmer = frame?.farm?.farmer || []; const hands = frame?.farm?.hands || [];
  const tiles = frame?.farm?.tiles || Array.from({ length: 10 }, () => Array(10).fill("LOCKED"));
  return <section className="replay-panel"><div className="panel-label">MATCH REPLAY <b>{frame ? `DAY ${frame.day} · HOUR ${frame.hour} · TURN ${frame.step + 1}/${frame.totalSteps}` : "LOADING"}</b></div>{error && <p className="notice error" role="alert">Replay unavailable: {error}</p>}<div className="replay-layout"><div className="farm-board" style={{ gridTemplateColumns: `repeat(${tiles[0]?.length || 10}, minmax(0, 1fr))` }}>{tiles.flatMap((row, y) => row.map((tile, x) => { const unit = farmer[0] === x && farmer[1] === y ? "F" : hands.some((pos) => pos[0] === x && pos[1] === y) ? "H" : ""; const kind = tile === "LOCKED" ? "locked" : tile === null ? "empty" : (tile.kind || "object").toLowerCase(); return <div className={`farm-tile ${kind}`} key={`${x}-${y}`} title={`${x},${y} ${kind}`}>{unit || (kind === "plant" ? String(tile.crop || "")[0] : kind === "weed" ? "×" : tile?.animal ? String(tile.animal)[0] : "")}</div>; }))}</div><div className="decision-inspector"><span>TURN {frame?.step ?? 0}</span><h3>Decision inspector</h3><pre>{JSON.stringify(frame?.action || {}, null, 2)}</pre><p>Cash <b>{money(frame?.farm?.money)}</b></p><p>Reward <b>{money(frame?.reward)}</b></p></div></div><div className="replay-controls"><button disabled={!frame || step === 0} onClick={() => seek(Math.max(0, step - 1))}>Previous</button><button className="play" disabled={!frame || !!error || frame.totalSteps < 2} onClick={() => { if (step >= frame.totalSteps - 1) setStep(0); setPlaying(!playing); }}>{playing ? "Pause" : "Play"}</button><button disabled={!frame || step >= frame.totalSteps - 1} onClick={() => seek(Math.min((frame?.totalSteps || 1) - 1, step + 1))}>Next</button><select aria-label="Playback speed" value={speed} onChange={(event) => setSpeed(Number(event.target.value))}><option value="0.5">0.5×</option><option value="1">1×</option><option value="2">2×</option><option value="4">4×</option></select><input aria-label="Replay turn" type="range" min="0" max={Math.max(0, (frame?.totalSteps || 1) - 1)} value={step} onChange={(event) => seek(Number(event.target.value))} /></div></section>;
}

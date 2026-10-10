import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import "./App.css";
import "./Experience.css";
const arenaImage = "/farmcraft-voxel-arena.webp";
const brandMark = "/farmcraft-mark.svg";
import ContestantPortal, { ReplayViewer } from "./Lab.jsx";
import AdminApp from "./AdminApp.jsx";
import { API_BASE, participantFetch, signInParticipant, restoreParticipantSession, recoverParticipant, logoutParticipant } from "./participantApi.js";
import { agentFileError } from "./fileValidation.js";

const EMPTY_STATE = {
  status: "registration", message: "Registration is open.", playersCount: 0,
  maxPlayers: 100, registeredPlayers: [], currentRound: 0, totalRoundsEstimate: 0,
  currentMatches: [], roundsHistory: [], byes: [], eliminatedPlayers: [],
  allMatches: [], champion: null, finalScore: null, error: null, isLive: false,
};

const playerName = (player) => typeof player === "string" ? player : player?.username || "UNKNOWN";
const score = (value) => value === null || value === undefined ? "—" : Number(value).toLocaleString();

function StatusLight({ status }) {
  const labels = { registration: "Round 1 open", ready: "Seeded bracket ready", starting: "Preparing bracket", round_running: "Round live", next_round: "Round secured", final: "Final live", champion: "Champion crowned", error: "Arena fault" };
  return <div className={`status-light status-${status}`}><span />{labels[status] || status}</div>;
}

function DuelCard({ match, featured = false, onReplay }) {
  const running = match?.status === "running";
  const completed = match?.status === "completed";
  const aborted = match?.status === "aborted";
  const p1 = match?.player1 || "Awaiting bot";
  const p2 = match?.player2 || "Awaiting bot";
  const p1Won = completed && match?.winner === p1;
  const p2Won = completed && match?.winner === p2;
  return <article className={`duel-card ${running ? "is-live" : ""} ${featured ? "featured" : ""}`}>
    <div className="duel-topline"><span>{match?.id || "Arena pairing"}</span><b>{running ? "LIVE" : completed ? "FINAL" : aborted ? "ABORTED" : "QUEUED"}</b></div>
    <div className={`combatant ${p1Won ? "winner" : ""} ${completed && !p1Won ? "defeated" : ""}`}><i>A</i><strong>{match?.seedA ? `#${match.seedA} ` : ""}{p1}</strong><span>{score(match?.p1Score)}</span></div>
    <div className="versus-line"><span>VS</span></div>
    <div className={`combatant amber ${p2Won ? "winner" : ""} ${completed && !p2Won ? "defeated" : ""}`}><i>B</i><strong>{match?.seedB ? `#${match.seedB} ` : ""}{p2}</strong><span>{score(match?.p2Score)}</span></div>
    {completed && match?.winner && <div className="winner-verdict"><span>WINNER</span><strong>{match.winner}</strong><small>ADVANCES TO THE NEXT ROUND</small></div>}
    {match?.tieReplays > 0 && <p className="replay-note">Overtime replay × {match.tieReplays}{match.tieBreak === "higher_qualification_seed" ? " · Higher qualification seed advanced" : ""}</p>}
    {aborted && <p className="replay-note">Match stopped: {match.error || "Tournament halted"}</p>}
    {!!match?.replayIds?.length && <div className="duel-replays">{match.replayIds.map((id, index) => <button key={id} onClick={() => onReplay?.(id)}>Watch leg {index + 1}</button>)}</div>}
  </article>;
}

function ActionFeed({ match }) {
  return <div className="action-feed" aria-live="polite">
    <div className="feed-head"><span>OFFICIAL MATCH STATUS</span><span>{match?.status?.toUpperCase() || "QUEUED"}</span></div>
    <div className="feed-event lime"><b>{match?.player1 || "BOT A"}</b><em>{match?.status === "completed" ? score(match?.p1Score) : "—"}</em><span>{match?.status === "running" ? "Evaluating in the arena" : match?.status === "completed" ? "Final score" : match?.status === "aborted" ? "Tournament halted" : "Awaiting worker"}</span></div>
    <div className="feed-event amber"><b>{match?.player2 || "BOT B"}</b><em>{match?.status === "completed" ? score(match?.p2Score) : "—"}</em><span>{match?.winner ? `Winner: ${match.winner}` : "Official result pending"}</span></div>
  </div>;
}

function App() {
  const [identity, setIdentity] = useState(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [teamInput, setTeamInput] = useState("");
  const [recoveryCode, setRecoveryCode] = useState("");
  const [recovering, setRecovering] = useState(false);
  const [authError, setAuthError] = useState("");
  const [authBusy, setAuthBusy] = useState(false);
  const [agentFile, setAgentFile] = useState(null);
  const [players, setPlayers] = useState([]);
  const [tournament, setTournament] = useState(EMPTY_STATE);
  const [tab, setTab] = useState("arena");
  const [notice, setNotice] = useState(null);
  const [busy, setBusy] = useState(false);
  const [battleResult, setBattleResult] = useState(null);
  const [eventConfig, setEventConfig] = useState(null);
  const [entrySummary, setEntrySummary] = useState(null);
  const [selectedReplayId, setSelectedReplayId] = useState(null);
  const [view, setView] = useState("tournament");
  const seenResults = useRef(new Set());
  const resultTimer = useRef(null);
  const isRegistration = tournament.status === "registration";
  const isActive = ["starting", "round_running", "next_round", "final"].includes(tournament.status);
  const isChampion = tournament.status === "champion";
  const featuredMatch = tournament.currentMatches?.find((m) => m.status === "running") || tournament.currentMatches?.[0];

  useEffect(() => {
    let active = true;
    restoreParticipantSession().then((session) => { if (active) setIdentity(session); })
      .catch(() => {}).finally(() => { if (active) setAuthLoading(false); });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    const ended = (event) => { setIdentity(null); setAuthError(String(event.detail || "Your session has ended.")); };
    window.addEventListener("farmcraft:session-ended", ended);
    return () => window.removeEventListener("farmcraft:session-ended", ended);
  }, []);

  async function enterArena(event) {
    event.preventDefault(); setAuthBusy(true); setAuthError("");
    try {
      const session = recovering ? await recoverParticipant(teamInput.trim(), recoveryCode.trim()) : await signInParticipant(teamInput.trim());
      setEntrySummary(null); setIdentity(session); setRecoveryCode(""); setRecovering(false);
    } catch (error) { setAuthError(error.message); }
    finally { setAuthBusy(false); }
  }

  async function leaveArena() {
    try { await logoutParticipant(); }
    finally { setIdentity(null); setEntrySummary(null); setSelectedReplayId(null); setView("tournament"); setNotice(null); }
  }

  const refresh = useCallback(async () => {
    try {
      const [playersRes, statusRes, eventRes] = await Promise.all([fetch(`${API_BASE}/players`), fetch(`${API_BASE}/tournament/status`), fetch(`${API_BASE}/event/status`)]);
      if (playersRes.ok) setPlayers((await playersRes.json()).players || []);
      if (statusRes.ok) setTournament(await statusRes.json());
      if (eventRes.ok) setEventConfig(await eventRes.json());
    } catch { setNotice({ type: "error", text: "Arena backend is offline." }); }
  }, []);

  useEffect(() => {
    const initial = window.setTimeout(() => { void refresh(); }, 0);
    const timer = window.setInterval(() => { void refresh(); }, isActive ? 3000 : 15000);
    return () => { window.clearTimeout(initial); window.clearInterval(timer); };
  }, [isActive, refresh]);
  useEffect(() => {
    if (!identity?.team || view !== "tournament") return undefined;
    let active = true;
    const loadEntry = async () => {
      try {
        const response = await participantFetch(`/botlab/${encodeURIComponent(identity.team)}`);
        if (response.ok) { const summary = await response.json(); if (active) setEntrySummary(summary); }
      } catch { /* The shared session handler surfaces authentication failures. */ }
    };
    void loadEntry();
    const timer = window.setInterval(() => { void loadEntry(); }, 5000);
    return () => { active = false; window.clearInterval(timer); };
  }, [identity?.team, view]);
  useEffect(() => {
    const completed = [...(tournament.allMatches || []), ...(tournament.currentMatches || [])]
      .filter((match) => match.status === "completed" && match.winner);
    const unseen = completed.filter((match, index) => {
      const key = match.id || `${match.player1}-${match.player2}-${match.winner}-${index}`;
      return !seenResults.current.has(key);
    });
    completed.forEach((match, index) => seenResults.current.add(match.id || `${match.player1}-${match.player2}-${match.winner}-${index}`));
    if (!unseen.length) return;
    setBattleResult(unseen[unseen.length - 1]);
    clearTimeout(resultTimer.current);
    resultTimer.current = setTimeout(() => setBattleResult(null), 4500);
  }, [tournament.allMatches, tournament.currentMatches]);
  useEffect(() => () => clearTimeout(resultTimer.current), []);

  const rounds = useMemo(() => {
    const list = (tournament.roundsHistory || []).map((round) => ({ ...round, completed: true }));
    if (!list.length && tournament.currentRound === 0 && tournament.openingMatches?.length) list.push({ round: 1, matches: tournament.openingMatches.filter(match => match.player2), byePlayers: tournament.openingMatches.filter(match => !match.player2).map(match => match.player1), completed: false });
    if (tournament.currentRound > 0 && tournament.currentMatches?.length && !list.some((r) => r.round === tournament.currentRound)) list.push({ round: tournament.currentRound, matches: tournament.currentMatches, completed: false });
    return list;
  }, [tournament]);

  async function register(event) {
    event.preventDefault();
    if (!identity) return;
    const fileError = agentFileError(agentFile);
    if (fileError) { setNotice({ type: "error", text: fileError }); return; }
    const body = new FormData(); body.append("username", identity.team); body.append("agent", agentFile); setBusy(true);
    try {
      const response = await participantFetch("/register", { method: "POST", body }); const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Registration failed.");
      if (data.job?.id) localStorage.setItem(`neural-coliseum-job-${data.player.username}`, data.job.id);
      setNotice({ type: "success", text: `${data.player.username} registered. Submission #${data.submissionId} is ${data.status.toUpperCase()}${data.job?.queuePosition ? ` at position ${data.job.queuePosition}` : ""}. Track it in Bot Lab.` }); setAgentFile(null);
      document.getElementById("agent-file-input").value = ""; await refresh();
    } catch (error) { setNotice({ type: "error", text: error.message }); } finally { setBusy(false); }
  }

  const survivors = tournament.registeredPlayers?.filter((name) => !(tournament.eliminatedPlayers || []).some((entry) => playerName(entry) === playerName(name) || entry.player === playerName(name))) || [];
  const alreadyRegistered = players.some((player) => player.username?.toLowerCase() === identity?.team?.toLowerCase());
  const latestOfficial = entrySummary?.jobs?.find((job) => job.type === "official");

  if (authLoading) return <main className="team-entry loading-entry"><img src={brandMark} alt="" /><span>Preparing the arena…</span></main>;
  if (!identity) return <main className="team-entry"><div className="entry-art" role="img" aria-label="Voxel farm arena at dusk" /><form className="entry-card" onSubmit={enterArena}><img src={brandMark} alt="FarmCraft" /><span className="eyebrow">SDC (AI/ML WING) · NIT WARANGAL</span><h1>Welcome to the arena.</h1><p>One team. One farm. Every strategy is yours to explore.</p><label htmlFor="team-name">Your team name</label><input id="team-name" autoFocus required maxLength={32} pattern="[A-Za-z0-9_-]+" value={teamInput} onChange={(event) => setTeamInput(event.target.value)} placeholder="TEAM_ALPHA" autoComplete="off" />{recovering && <><label htmlFor="recovery-code">Organizer recovery code</label><input id="recovery-code" required value={recoveryCode} onChange={(event) => setRecoveryCode(event.target.value)} placeholder="Paste your one-time code" autoComplete="off" /></>}{authError && <div className="notice error" role="alert">{authError}</div>}<button className="button primary wide" disabled={authBusy}>{authBusy ? "Entering…" : recovering ? "Recover team" : "Enter FarmCraft"}</button><button type="button" className="entry-switch" onClick={() => { setRecovering(!recovering); setAuthError(""); }}>{recovering ? "Create a new team" : "Already registered? Recover with the organizer"}</button><small>Returning on this browser? Your session is restored automatically.</small></form></main>;

  return <div className="app-shell">
    <header className="topbar">
      <a className="brand" href="#top" aria-label="FarmCraft home"><img src={brandMark} alt="FarmCraft pixel farm emblem" /><span><b>FARMCRAFT</b><small>AI FARMING AGENT CHAMPIONSHIP</small></span></a>
      <StatusLight status={tournament.status} />
      <div className="top-actions"><span className="team-chip">TEAM <b>{identity.team}</b></span><button className="logout-button" onClick={leaveArena}>Logout</button></div>
    </header>
    <nav className="product-nav">
      {["lab", "strategy", "sandbox", "analytics", "submissions", "leaderboard", "tournament", "guide"].map((item) => <button className={view === item ? "active" : ""} onClick={() => setView(item)} key={item}>{item === "lab" ? "Bot Lab" : item === "strategy" ? "Strategy Path" : item}</button>)}
    </nav>
    {eventConfig && (eventConfig.mode !== "DEVELOPMENT" || !eventConfig.uploadsEnabled || !eventConfig.sandboxEnabled || !eventConfig.officialEnabled || !eventConfig.tournamentEnabled) && <div className="notice event-status-notice">EVENT MODE · {eventConfig.mode}{[!eventConfig.uploadsEnabled && "uploads", !eventConfig.sandboxEnabled && "sandbox runs", !eventConfig.officialEnabled && "official submissions", !eventConfig.tournamentEnabled && "tournament launch"].filter(Boolean).length > 0 && ` — paused: ${[!eventConfig.uploadsEnabled && "uploads", !eventConfig.sandboxEnabled && "sandbox runs", !eventConfig.officialEnabled && "official submissions", !eventConfig.tournamentEnabled && "tournament launch"].filter(Boolean).join(", ")}.`}</div>}

    {view !== "tournament" ? <ContestantPortal section={view} onNavigate={setView} identity={identity} /> : isRegistration ? <main id="top">
      <section className="hero" style={{ "--arena-image": `url(${arenaImage})` }}><div className="hero-grid" /><div className="hero-copy">
        <span className="eyebrow">SDC (AI/ML WING) · NIT WARANGAL</span><h1>Build your agent.<br /><span>Master the farm.</span></h1>
        <p>Plant a strategy. Train an AI farmer. Compete in a living farm simulation where every turn can change the leaderboard.</p>
        <div className="hero-actions"><button className="button primary" onClick={() => document.querySelector(".registration-zone")?.scrollIntoView({ behavior: "smooth" })}>Enter the tournament</button><button className="button" onClick={() => setView("lab")}>Open Bot Lab</button></div>
        <div className="hero-metrics"><div><b>{String(players.length).padStart(2, "0")}</b><span>agents registered</span></div><div><b>720</b><span>turns per match</span></div><div><b>1V1</b><span>head-to-head rounds</span></div></div>
      </div><div className="hero-stamp"><span>SEASON</span><b>01</b><small>LIVE BUILD</small></div></section>

      <section className="arena-features"><div className="section-title"><span>THE COMPETITION LOOP</span><h2>From code to champion</h2></div><div className="feature-grid">{[
        ["01", "Bot Lab", "Build and validate a farming agent with a clear version history.", "lab"],
        ["02", "Strategies", "Explore every farming approach from the first day.", "strategy"],
        ["03", "Sandbox", "Test against public rivals before committing a build.", "sandbox"],
        ["04", "Leaderboard", "Track official ratings earned from real match results.", "leaderboard"],
      ].map(([number,title,copy,target]) => <button className="feature-card" key={title} onClick={() => setView(target)}><span>{number} / FIELD SYSTEM</span><h3>{title}</h3><p>{copy}</p><b>Explore ↗</b></button>)}</div></section>

      <section className="registration-zone"><div className="section-title"><span>01 / ENTER THE ARENA</span><h2>Deploy your contender</h2></div>
        <div className="tournament-entry-status" aria-live="polite"><div><small>YOUR TEAM</small><strong>{identity.team}</strong><span>{alreadyRegistered ? "On the tournament roster" : "Registration awaiting a bot"}</span></div><div><small>BOT VERSION</small><strong>{entrySummary?.currentVersion || "—"}</strong><span>{entrySummary?.validationStatus || "No upload yet"}</span></div><div><small>OFFICIAL EVALUATION</small><strong>{latestOfficial?.status || "Not submitted"}</strong><span>{latestOfficial?.status === "running" && latestOfficial.progressTotal ? `${latestOfficial.progressCurrent || 0}/${latestOfficial.progressTotal} games completed` : latestOfficial?.status === "failed" ? latestOfficial.error || "Open Bot Lab for details" : "Results update automatically"}</span></div><div><small>OFFICIAL RATING</small><strong>{score(entrySummary?.activeSubmission?.official_score)}</strong><span>{entrySummary?.leaderboardRank ? `Rank #${entrySummary.leaderboardRank}` : "Awaiting ranked result"}</span></div></div>
        <div className="tournament-entry-links"><button onClick={() => setView("lab")}>Bot Lab</button><button onClick={() => setView("submissions")}>Submission history</button><button onClick={() => setView("leaderboard")}>Leaderboard</button></div>
        <div className="registration-grid">
        <form className="deploy-card" onSubmit={register}><div className="panel-label">AGENT INTAKE</div>
          <div className="deploy-identity">REGISTERING AS <b>{identity.team}</b></div>
          <label>Python combat logic<div className={`file-target ${agentFile ? "loaded" : ""}`}><input id="agent-file-input" type="file" accept=".py" onChange={(e) => setAgentFile(e.target.files?.[0] || null)} /><span>{agentFile ? "FILE LOCKED" : "SELECT AGENT.PY OR MAIN.PY"}</span><b>{agentFile?.name || "Maximum 256 KB · def agent(obs) required"}</b></div></label>
          <button className="button primary wide" disabled={busy || alreadyRegistered}>{busy ? "Validating…" : alreadyRegistered ? "Registered — update in Bot Lab" : "Register bot"}</button>{notice && <div className={`notice ${notice.type}`}>{notice.text}</div>}
        </form>
        <div className="roster-panel"><div className="panel-label">ACTIVE ROSTER <b>{players.length}/{tournament.maxPlayers || 100}</b></div><div className="roster-list">{players.length ? players.map((player, index) => <div className="roster-row" key={player.username}><span>{String(index + 1).padStart(2, "0")}</span><strong>{player.username}</strong><i>READY</i></div>) : <div className="empty-state">The arena is quiet.<br />Register the first bot.</div>}</div></div>
        <div className="protocol-panel"><div className="panel-label">BATTLE PROTOCOL</div><ol><li><b>01</b><span>Qualification rank sets the bracket</span></li><li><b>02</b><span>720-turn farm simulation</span></li><li><b>03</b><span>Highest bank survives</span></li><li><b>04</b><span>Ties trigger overtime</span></li></ol></div>
      </div></section>
    </main> : <main className="battle-page">
      <section className="battle-hero" style={{ "--arena-image": `url(${arenaImage})` }}><div className="battle-overlay" />
        {isChampion && tournament.champion ? <div className="champion-reveal"><img src={brandMark} alt="Champion crest" /><span>ARENA CHAMPION</span><h1>{playerName(tournament.champion)}</h1><p>The field belongs to one.</p></div> : <div className="live-stage">
          <div className="round-kicker">ROUND {tournament.currentRound || "—"} · {tournament.message}</div>
          {featuredMatch ? <><div className="fighter-name left"><span>CONTENDER A</span><b>{featuredMatch.player1}</b></div><div className="clash-mark"><i /><strong>VS</strong><i /></div><div className="fighter-name right"><span>CONTENDER B</span><b>{featuredMatch.player2}</b></div><ActionFeed match={featuredMatch} /></> : <div className="pairing-loader"><i /><span>Building the battlefield</span></div>}
        </div>}
      </section>
      <nav className="battle-nav">{["arena", "bracket", "history", "roster"].map((item) => <button className={tab === item ? "active" : ""} onClick={() => setTab(item)} key={item}>{item}</button>)}</nav>
      <section className="battle-content">{notice && <div className={`notice ${notice.type}`}>{notice.text}</div>}
        {tab === "arena" && <div className="match-grid">{(tournament.currentMatches || []).length ? tournament.currentMatches.map((match, index) => <DuelCard match={match} onReplay={setSelectedReplayId} featured={index === 0} key={match.id || index} />) : <div className="empty-state large">Match telemetry will appear when the round begins.</div>}</div>}
        {tab === "bracket" && <div className="bracket-board">{rounds.length ? rounds.map((round) => <div className="round-column" key={round.round}><div className="round-head"><span>ROUND {round.round}</span><b>{round.matches?.length || 0} DUELS</b></div>{(round.matches || []).map((match, index) => <DuelCard match={match} onReplay={setSelectedReplayId} key={match.id || index} />)}{(round.byePlayers || (round.byePlayer ? [round.byePlayer] : [])).map(name => <div className="bye-card" key={name}><span>BYE PASS</span><b>{playerName(name)}</b></div>)}</div>) : <div className="empty-state large">Bracket calibration in progress.</div>}{isChampion && tournament.champion && <div className="round-column champion-column"><div className="round-head"><span>VICTOR</span></div><div className="victor-card"><img src={brandMark} alt="" /><b>{playerName(tournament.champion)}</b></div></div>}</div>}
        {tab === "history" && <div className="history-board"><div className="table-head"><span>DUEL</span><span>COMBATANTS</span><span>SCORE</span><span>VICTOR</span></div>{(tournament.allMatches || []).map((match, index) => <div className="history-row" key={match.matchId || index}><span>{match.matchId || `#${index + 1}`}</span><strong>{match.player1} <i>vs</i> {match.player2}</strong><span>{score(match.p1Score)} — {score(match.p2Score)}</span><b>{match.winner || "Pending"}{match.tieBreak === "higher_qualification_seed" && <small> (higher qualification seed)</small>}</b>{!!match.replayIds?.length && <div className="history-replays">{match.replayIds.map((id, leg) => <button key={id} onClick={() => setSelectedReplayId(id)}>Replay leg {leg + 1}</button>)}</div>}</div>)}{!tournament.allMatches?.length && <div className="empty-state large">No completed battles.</div>}</div>}
        {tab === "roster" && <div className="standings-grid"><div className="standing-panel"><div className="panel-label">STILL STANDING</div>{survivors.map((name, index) => <div className="standing-row" key={playerName(name)}><span>#{tournament.qualificationSeeds?.[playerName(name)] || index + 1}</span><b>{playerName(name)}</b><i>ACTIVE</i></div>)}</div><div className="standing-panel dim"><div className="panel-label">ELIMINATED</div>{(tournament.eliminatedPlayers || []).map((entry, index) => <div className="standing-row" key={`${playerName(entry)}-${index}`}><span>×</span><b>{playerName(entry.player || entry)}</b><i>OUT</i></div>)}</div><div className="standing-panel"><div className="panel-label">BYE PASSES</div>{(tournament.byes || []).map((entry, index) => <div className="standing-row" key={`${entry.player}-${index}`}><span>R{entry.round}</span><b>{entry.player}</b><i>PASS</i></div>)}</div></div>}
        {selectedReplayId && <div className="tournament-replay"><button className="button" onClick={() => setSelectedReplayId(null)}>Close replay</button><ReplayViewer key={selectedReplayId} replayId={selectedReplayId} /></div>}
      </section>
    </main>}
    {view === "tournament" && battleResult && <div className="result-reveal" onClick={() => setBattleResult(null)} role="status">
      <div className="result-shockwave" /><div className="result-content"><span>BATTLE COMPLETE</span><img src={brandMark} alt="" /><small>WINNER</small><h2>{battleResult.winner}</h2><div className="result-score"><b>{battleResult.player1}</b><strong>{score(battleResult.p1Score)} <i>—</i> {score(battleResult.p2Score)}</strong><b>{battleResult.player2}</b></div><p>{battleResult.tieBreak === "seeded_lot" ? "SEEDED DRAW AFTER EXACT TIE · ADVANCES TO THE NEXT ROUND" : "ADVANCES TO THE NEXT ROUND"}</p></div>
    </div>}
    <footer><span>FARMCRAFT</span><span>SDC (AI/ML WING) · NIT WARANGAL</span><span>AI FARMING AGENT CHAMPIONSHIP</span></footer>
  </div>;
}

function Root() { return window.location.pathname.startsWith("/admin") ? <AdminApp /> : <App />; }

export default Root;

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import "./App.css";
import arenaImage from "./assets/farmcraft-arena.png";
const brandMark = "/farmcraft-mark.svg";
import ContestantPortal from "./Lab.jsx";
import AdminApp from "./AdminApp.jsx";

const API_BASE = import.meta.env.VITE_API_BASE || "http://127.0.0.1:8000";
const EMPTY_STATE = {
  status: "registration", message: "Registration is open.", playersCount: 0,
  maxPlayers: 100, registeredPlayers: [], currentRound: 0, totalRoundsEstimate: 0,
  currentMatches: [], roundsHistory: [], byes: [], eliminatedPlayers: [],
  allMatches: [], champion: null, finalScore: null, error: null, isLive: false,
};
const ACTIONS = [
  ["SCAN", "Reading market volatility"], ["MOVE", "Repositioning field unit"],
  ["BUY", "Acquiring high-yield seed"], ["PLANT", "Deploying crop strategy"],
  ["WATER", "Protecting active harvest"], ["HARVEST", "Converting yield to inventory"],
  ["SELL", "Executing market order"], ["COUNTER", "Responding to rival economy"],
];

const playerName = (player) => typeof player === "string" ? player : player?.username || "UNKNOWN";
const score = (value) => value === null || value === undefined ? "—" : Number(value).toLocaleString();

function StatusLight({ status }) {
  const labels = { registration: "Gates open", starting: "Seeding bracket", round_running: "Round live", next_round: "Round secured", final: "Final live", champion: "Champion crowned", error: "Arena fault" };
  return <div className={`status-light status-${status}`}><span />{labels[status] || status}</div>;
}

function DuelCard({ match, featured = false }) {
  const running = match?.status === "running";
  const completed = match?.status === "completed";
  const p1 = match?.player1 || "Awaiting bot";
  const p2 = match?.player2 || "Awaiting bot";
  const p1Won = completed && match?.winner === p1;
  const p2Won = completed && match?.winner === p2;
  return <article className={`duel-card ${running ? "is-live" : ""} ${featured ? "featured" : ""}`}>
    <div className="duel-topline"><span>{match?.id || "Arena pairing"}</span><b>{running ? "LIVE" : completed ? "FINAL" : "QUEUED"}</b></div>
    <div className={`combatant ${p1Won ? "winner" : ""} ${completed && !p1Won ? "defeated" : ""}`}><i>A</i><strong>{p1}</strong><span>{score(match?.p1Score)}</span></div>
    <div className="versus-line"><span>VS</span></div>
    <div className={`combatant amber ${p2Won ? "winner" : ""} ${completed && !p2Won ? "defeated" : ""}`}><i>B</i><strong>{p2}</strong><span>{score(match?.p2Score)}</span></div>
    {completed && match?.winner && <div className="winner-verdict"><span>WINNER</span><strong>{match.winner}</strong><small>ADVANCES TO THE NEXT ROUND</small></div>}
    {match?.tieReplays > 0 && <p className="replay-note">Overtime replay × {match.tieReplays}</p>}
  </article>;
}

function ActionFeed({ match, tick }) {
  const leftAction = ACTIONS[tick % ACTIONS.length];
  const rightAction = ACTIONS[(tick + 3) % ACTIONS.length];
  return <div className="action-feed" aria-live="polite">
    <div className="feed-head"><span>SIMULATION FEED</span><span>TURN {(tick * 17) % 720 + 1} / 720</span></div>
    <div className="feed-event lime"><b>{match?.player1 || "BOT A"}</b><em>{leftAction[0]}</em><span>{leftAction[1]}</span></div>
    <div className="feed-event amber"><b>{match?.player2 || "BOT B"}</b><em>{rightAction[0]}</em><span>{rightAction[1]}</span></div>
    <div className="turn-track"><span style={{ width: `${(((tick * 17) % 720) / 720) * 100}%` }} /></div>
  </div>;
}

function App() {
  const [username, setUsername] = useState("");
  const [agentFile, setAgentFile] = useState(null);
  const [players, setPlayers] = useState([]);
  const [tournament, setTournament] = useState(EMPTY_STATE);
  const [tab, setTab] = useState("arena");
  const [notice, setNotice] = useState(null);
  const [busy, setBusy] = useState(false);
  const [tick, setTick] = useState(0);
  const [battleResult, setBattleResult] = useState(null);
  const [eventConfig, setEventConfig] = useState(null);
  const [view, setView] = useState("tournament");
  const seenResults = useRef(new Set());
  const resultTimer = useRef(null);
  const isRegistration = tournament.status === "registration";
  const isActive = ["starting", "round_running", "next_round", "final"].includes(tournament.status);
  const isChampion = tournament.status === "champion";
  const featuredMatch = tournament.currentMatches?.find((m) => m.status === "running") || tournament.currentMatches?.[0];

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
  useEffect(() => { if (!isActive) return undefined; const timer = setInterval(() => setTick((value) => value + 1), 1450); return () => clearInterval(timer); }, [isActive]);
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
    if (tournament.currentRound > 0 && tournament.currentMatches?.length && !list.some((r) => r.round === tournament.currentRound)) list.push({ round: tournament.currentRound, matches: tournament.currentMatches, completed: false });
    return list;
  }, [tournament]);

  async function register(event) {
    event.preventDefault();
    if (!username.trim() || !agentFile) { setNotice({ type: "error", text: "Add a team name and Python agent file." }); return; }
    const body = new FormData(); body.append("username", username.trim()); body.append("agent", agentFile); setBusy(true);
    try {
      const response = await fetch(`${API_BASE}/register`, { method: "POST", body }); const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Registration failed.");
      setNotice({ type: "success", text: `${data.player.username} is cleared for battle.` }); setUsername(""); setAgentFile(null);
      document.getElementById("agent-file-input").value = ""; await refresh();
    } catch (error) { setNotice({ type: "error", text: error.message }); } finally { setBusy(false); }
  }

  const survivors = tournament.registeredPlayers?.filter((name) => !(tournament.eliminatedPlayers || []).some((entry) => playerName(entry) === playerName(name) || entry.player === playerName(name))) || [];

  return <div className="app-shell">
    <header className="topbar">
      <a className="brand" href="#top" aria-label="FarmCraft home"><img src={brandMark} alt="FarmCraft pixel farm emblem" /><span><b>FARMCRAFT</b><small>AI FARMING AGENT CHAMPIONSHIP</small></span></a>
      <StatusLight status={tournament.status} />
      <div className="top-actions" />
    </header>
    <nav className="product-nav">
      {["lab", "strategy", "sandbox", "analytics", "submissions", "leaderboard", "tournament", "guide"].map((item) => <button className={view === item ? "active" : ""} onClick={() => setView(item)} key={item}>{item === "lab" ? "Bot Lab" : item === "strategy" ? "Strategy Path" : item}</button>)}
    </nav>
    {eventConfig && (eventConfig.mode !== "DEVELOPMENT" || !eventConfig.uploadsEnabled || !eventConfig.sandboxEnabled || !eventConfig.officialEnabled || !eventConfig.tournamentEnabled) && <div className="notice event-status-notice">EVENT MODE · {eventConfig.mode}{[!eventConfig.uploadsEnabled && "uploads", !eventConfig.sandboxEnabled && "sandbox runs", !eventConfig.officialEnabled && "official submissions", !eventConfig.tournamentEnabled && "tournament launch"].filter(Boolean).length > 0 && ` — paused: ${[!eventConfig.uploadsEnabled && "uploads", !eventConfig.sandboxEnabled && "sandbox runs", !eventConfig.officialEnabled && "official submissions", !eventConfig.tournamentEnabled && "tournament launch"].filter(Boolean).join(", ")}.`}</div>}

    {view !== "tournament" ? <ContestantPortal section={view} onNavigate={setView} /> : isRegistration ? <main id="top">
      <section className="hero" style={{ "--arena-image": `url(${arenaImage})` }}><div className="hero-grid" /><div className="hero-copy">
        <span className="eyebrow">SDC (AI/ML WING) · NIT WARANGAL</span><h1>Build your agent.<br /><span>Master the farm.</span></h1>
        <p>Plant a strategy. Train an AI farmer. Compete in a living farm simulation where every turn can change the leaderboard.</p>
        <div className="hero-metrics"><div><b>{String(players.length).padStart(2, "0")}</b><span>agents registered</span></div><div><b>720</b><span>turns per match</span></div><div><b>1V1</b><span>head-to-head rounds</span></div></div>
      </div><div className="hero-stamp"><span>SEASON</span><b>01</b><small>LIVE BUILD</small></div></section>

      <section className="registration-zone"><div className="section-title"><span>01 / ENTER THE ARENA</span><h2>Deploy your contender</h2></div><div className="registration-grid">
        <form className="deploy-card" onSubmit={register}><div className="panel-label">AGENT INTAKE</div>
          <label>Team identity<input type="text" value={username} onChange={(e) => setUsername(e.target.value)} placeholder="Enter callsign" maxLength={32} /></label>
          <label>Python combat logic<div className={`file-target ${agentFile ? "loaded" : ""}`}><input id="agent-file-input" type="file" accept=".py" onChange={(e) => setAgentFile(e.target.files?.[0] || null)} /><span>{agentFile ? "FILE LOCKED" : "DROP AGENT.PY"}</span><b>{agentFile?.name || "Maximum 100 KB · def agent(obs) required"}</b></div></label>
          <button className="button primary wide" disabled={busy}>{busy ? "Validating…" : "Register bot"}</button>{notice && <div className={`notice ${notice.type}`}>{notice.text}</div>}
        </form>
        <div className="roster-panel"><div className="panel-label">ACTIVE ROSTER <b>{players.length}/100</b></div><div className="roster-list">{players.length ? players.map((player, index) => <div className="roster-row" key={player.username}><span>{String(index + 1).padStart(2, "0")}</span><strong>{player.username}</strong><i>READY</i></div>) : <div className="empty-state">The arena is quiet.<br />Register the first bot.</div>}</div></div>
        <div className="protocol-panel"><div className="panel-label">BATTLE PROTOCOL</div><ol><li><b>01</b><span>Random pairings</span></li><li><b>02</b><span>720-turn farm simulation</span></li><li><b>03</b><span>Highest bank survives</span></li><li><b>04</b><span>Ties trigger overtime</span></li></ol></div>
      </div></section>
    </main> : <main className="battle-page">
      <section className="battle-hero" style={{ "--arena-image": `url(${arenaImage})` }}><div className="battle-overlay" />
        {isChampion && tournament.champion ? <div className="champion-reveal"><img src={brandMark} alt="Champion crest" /><span>ARENA CHAMPION</span><h1>{playerName(tournament.champion)}</h1><p>The field belongs to one.</p></div> : <div className="live-stage">
          <div className="round-kicker">ROUND {tournament.currentRound || "—"} · {tournament.message}</div>
          {featuredMatch ? <><div className="fighter-name left"><span>CONTENDER A</span><b>{featuredMatch.player1}</b></div><div className="clash-mark"><i /><strong>VS</strong><i /></div><div className="fighter-name right"><span>CONTENDER B</span><b>{featuredMatch.player2}</b></div><ActionFeed match={featuredMatch} tick={tick} /></> : <div className="pairing-loader"><i /><span>Building the battlefield</span></div>}
        </div>}
      </section>
      <nav className="battle-nav">{["arena", "bracket", "history", "roster"].map((item) => <button className={tab === item ? "active" : ""} onClick={() => setTab(item)} key={item}>{item}</button>)}</nav>
      <section className="battle-content">{notice && <div className={`notice ${notice.type}`}>{notice.text}</div>}
        {tab === "arena" && <div className="match-grid">{(tournament.currentMatches || []).length ? tournament.currentMatches.map((match, index) => <DuelCard match={match} featured={index === 0} key={match.id || index} />) : <div className="empty-state large">Match telemetry will appear when the round begins.</div>}</div>}
        {tab === "bracket" && <div className="bracket-board">{rounds.length ? rounds.map((round) => <div className="round-column" key={round.round}><div className="round-head"><span>ROUND {round.round}</span><b>{round.matches?.length || 0} DUELS</b></div>{(round.matches || []).map((match, index) => <DuelCard match={match} key={match.id || index} />)}{round.byePlayer && <div className="bye-card"><span>BYE PASS</span><b>{playerName(round.byePlayer)}</b></div>}</div>) : <div className="empty-state large">Bracket calibration in progress.</div>}{isChampion && tournament.champion && <div className="round-column champion-column"><div className="round-head"><span>VICTOR</span></div><div className="victor-card"><img src={brandMark} alt="" /><b>{playerName(tournament.champion)}</b></div></div>}</div>}
        {tab === "history" && <div className="history-board"><div className="table-head"><span>DUEL</span><span>COMBATANTS</span><span>SCORE</span><span>VICTOR</span></div>{(tournament.allMatches || []).map((match, index) => <div className="history-row" key={match.id || index}><span>{match.id || `#${index + 1}`}</span><strong>{match.player1} <i>vs</i> {match.player2}</strong><span>{score(match.p1Score)} — {score(match.p2Score)}</span><b>{match.winner || "Pending"}</b></div>)}{!tournament.allMatches?.length && <div className="empty-state large">No completed battles.</div>}</div>}
        {tab === "roster" && <div className="standings-grid"><div className="standing-panel"><div className="panel-label">STILL STANDING</div>{survivors.map((name, index) => <div className="standing-row" key={playerName(name)}><span>{index + 1}</span><b>{playerName(name)}</b><i>ACTIVE</i></div>)}</div><div className="standing-panel dim"><div className="panel-label">ELIMINATED</div>{(tournament.eliminatedPlayers || []).map((entry, index) => <div className="standing-row" key={`${playerName(entry)}-${index}`}><span>×</span><b>{playerName(entry.player || entry)}</b><i>OUT</i></div>)}</div><div className="standing-panel"><div className="panel-label">BYE PASSES</div>{(tournament.byes || []).map((entry, index) => <div className="standing-row" key={`${entry.player}-${index}`}><span>R{entry.round}</span><b>{entry.player}</b><i>PASS</i></div>)}</div></div>}
      </section>
    </main>}
    {view === "tournament" && battleResult && <div className="result-reveal" onClick={() => setBattleResult(null)} role="status">
      <div className="result-shockwave" /><div className="result-content"><span>BATTLE COMPLETE</span><img src={brandMark} alt="" /><small>WINNER</small><h2>{battleResult.winner}</h2><div className="result-score"><b>{battleResult.player1}</b><strong>{score(battleResult.p1Score)} <i>—</i> {score(battleResult.p2Score)}</strong><b>{battleResult.player2}</b></div><p>ADVANCES TO THE NEXT ROUND</p></div>
    </div>}
    <footer><span>FARMCRAFT</span><span>SDC (AI/ML WING) · NIT WARANGAL</span><span>AI FARMING AGENT CHAMPIONSHIP</span></footer>
  </div>;
}

function Root() { return window.location.pathname.startsWith("/admin") ? <AdminApp /> : <App />; }

export default Root;

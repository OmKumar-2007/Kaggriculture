import {
  ACTION_CODE, ANIMALS, BEGINNER_MISTAKES, CROPS, GAME_FACTS, GUIDE_SECTIONS,
  MARKET_ACTIONS, OBSERVATION_CODE, QUICK_START, STARTER_CODE, UNIT_ACTIONS,
} from "./data/guideContent.js";

const Code = ({ children }) => <pre className="guide-code"><code>{children}</code></pre>;
const Section = ({ id, number, eyebrow, title, children }) => <section className="guide-section" id={id}>
  <div className="guide-section-head"><span>{number}</span><div><small>{eyebrow}</small><h2>{title}</h2></div></div>{children}
</section>;
const Callout = ({ tone = "lime", label, children }) => <div className={`guide-callout ${tone}`}><span>{label}</span><p>{children}</p></div>;

export default function GuidePage({ onNavigate }) {
  return <main className="guide-page">
    <header className="guide-hero">
      <div><span>FIELD MANUAL · 5–10 MIN READ</span><h1>Build your first contender.</h1><p>Learn the arena, understand the data, and turn one Python function into a competitive farming agent.</p></div>
      <div className="guide-order"><small>PRIMARY DIRECTIVE</small><strong>Finish with more money.</strong><p>You control decisions. The engine handles the world.</p></div>
    </header>

    <div className="guide-layout">
      <aside className="guide-nav"><span>ON THIS PAGE</span>{GUIDE_SECTIONS.map(([id, label], index) => <a href={`#${id}`} key={id}><b>{String(index + 1).padStart(2, "0")}</b>{label}</a>)}</aside>
      <article className="guide-body">
        <Section id="overview" number="01" eyebrow="MISSION BRIEF" title="What is FarmCraft?">
          <div className="guide-intro-grid"><div><p>Two AI-controlled farms compete through a fixed 30-day season. Your bot controls farming, workers, crops, animals, buying, selling and expansion.</p><p className="guide-lede">You are not manually playing. You are writing an AI agent that receives the current state and chooses actions every turn.</p></div><div className="guide-facts">{GAME_FACTS.map(([value, label]) => <div key={label}><strong>{value}</strong><span>{label}</span></div>)}</div></div>
          <Callout label="WIN CONDITION">The player with the most bank money after turn 720 wins. Unsold products, carried items, seeds, animals and land do not automatically become score.</Callout>
        </Section>

        <Section id="match" number="02" eyebrow="THE LOOP" title="How a match works">
          <div className="loop-diagram">{["GAME STATE", "agent(obs)", "YOUR DECISIONS", "GAME ENGINE", "UPDATED STATE"].map((item, index) => <div key={item}><b>{item}</b>{index < 4 && <i>↓</i>}</div>)}</div>
          <p>Each day has 24 turns. On every turn the engine sends an observation, calls your <code>agent(obs)</code>, applies one action per unit plus up to 10 market orders, updates both farms and the shared market, then repeats.</p>
          <p>Plants and animals refresh at day boundaries. Hired hands disappear after dropping their inventory into the shed, then must be hired again on the next day.</p>
        </Section>

        <Section id="board" number="03" eyebrow="THE FIELD" title="Board, shed and distance">
          <div className="board-explainer"><div className="quadrant-map"><span>NW<small>STARTS OPEN</small></span><span>NE<small>1,000</small></span><span>SW<small>2,000</small></span><span>SE<small>4,000</small></span><b>SHED</b></div><div><p>Each farm is a 10×10 grid split into four 5×5 quadrants. The northwest 25 tiles start unlocked. <code>BUY_LAND</code> opens NE, SW and SE in that order.</p><p>The shed sits at the center but is not a board tile. Its access positions are <code>(4,4)</code>, <code>(5,4)</code>, <code>(4,5)</code> and <code>(5,5)</code>.</p><p>Movement is one north, south, east or west step per turn. A practical distance estimate is Manhattan distance: <code>|x₁−x₂| + |y₁−y₂|</code>.</p></div></div>
          <Callout tone="amber" label="STRATEGIC QUESTION">Which task is valuable enough to justify the travel time? Nearby work takes fewer movement actions than distant work.</Callout>
        </Section>

        <Section id="production" number="04" eyebrow="PRODUCTION" title="Crops and animals">
          <p>The crop loop is <b>buy seed → plant → water → grow → harvest → return to shed → sell</b>. Every plant needs same-day watering after planting: planting already counts as its first unwatered day, and two consecutive missed day refreshes turn it into a weed.</p>
          <div className="guide-table-wrap"><table className="guide-table"><thead><tr><th>Crop</th><th>Seed</th><th>First yield</th><th>Peak / last cycle</th><th>Yield</th><th>Type</th></tr></thead><tbody>{CROPS.map(c => <tr key={c.name}><th>{c.name}</th><td>{c.cost}</td><td>Day {c.first}</td><td>Day {c.peak}</td><td>{c.yield}</td><td>{c.behavior}</td></tr>)}</tbody></table></div>
          <p className="guide-footnote">* Wheat reaches 4 and carrot 3 with ordinary daily watering; fertilizer can raise them to their engine caps of 6 and 4. Tomato and strawberry produce a limited number of cycles before decay.</p>
          <div className="animal-grid">{ANIMALS.map(a => <article key={a.name}><span>{a.home}</span><h3>{a.name}</h3><b>{a.cost} credits</b><p>{a.product} from day {a.first}, {a.cadence.toLowerCase()}. Holds up to {a.held} unharvested units.</p></article>)}</div>
          <p>Animals are long-term investments. Build the matching structure, buy the animal, pick it up at the shed and <code>PLACE</code> it. Feed one wheat daily. Two missed day refreshes make it escape. <code>CARE</code> banks a bonus for the next scheduled production, and each surviving animal makes one collectible fertilizer per day.</p>
          <Callout label="OPEN QUESTION">The highest price is not automatically the best choice. Consider cost, time, yield, remaining days, worker effort and how much product will reach the market.</Callout>
        </Section>

        <Section id="workers" number="05" eyebrow="LOGISTICS" title="Workers and the shed">
          <div className="guide-card-grid"><article><span>MAIN FARMER</span><h3>Persistent</h3><p>Acts every turn and returns to the shed area at the start of each day.</p></article><article><span>HIRED HANDS</span><h3>Daily capacity</h3><p>Each acts independently. Hire prices follow 1, 1, 2, 3, 5, 8… during a day, then reset.</p></article><article><span>SHED</span><h3>100 items</h3><p>Stores non-seed goods. End-of-day overflow is discarded. Seeds use separate unlimited slots.</p></article></div>
          <p>Workers can move, plant, water, harvest, fertilize, build, feed, care, collect, dig, pick up and return goods. When several jobs compete, your bot must choose both the most useful task and the best worker for it. Multiple units may share a tile, but duplicate assignments can waste turns.</p>
        </Section>

        <Section id="market" number="06" eyebrow="ECONOMY" title="A shared, moving market">
          <div className="market-diagram"><div><b>LOW SUPPLY</b><i>→</i><strong>HIGHER PRICE</strong></div><div><b>HIGH SUPPLY</b><i>→</i><strong>LOWER PRICE</strong></div></div>
          <p>Both players trade into one market. Selling adds supply and usually pushes later prices down. Town demand and purchases remove supply and can raise prices. Prices are rounded to whole credits and never fall below 1.</p><p>Seeds and animals have fixed purchase costs. Only wheat and fertilizer can be bought as products. Every harvested product can be sold. Orders execute one unit at a time across both players, so a large order can receive changing prices.</p>
          <p>New town shops appear every 3 days and consume their listed products every 4 turns. Their names are visible in <code>obs["town"]["unlocked_shops"]</code>. This means current price alone does not describe future supply and demand.</p>
          <Callout tone="amber" label="CAPITAL TRADE-OFF">More land adds capacity, but also costs 1,000, then 2,000, then 4,000 credits and creates more work. Expansion, workers, animals and seeds compete for the same cash.</Callout>
        </Section>

        <Section id="interface" number="07" eyebrow="BOT INTERFACE" title="What your agent sees and returns">
          <p>Your public observation includes both farms: money, tiles, unit positions, unlocked quadrants and today’s hire count. Only your own shed, seeds and carried inventories are private.</p>
          <Code>{OBSERVATION_CODE}</Code>
          <details className="guide-details"><summary>Full observation reference</summary><div><ul><li><code>farms[player].tiles[y][x]</code>: <code>None</code>, <code>"LOCKED"</code>, or a plant, weed, coop or pasture object.</li><li>Plant fields include crop, planting day, watering state, missed-water count, ready yield and fertilizer window.</li><li>Animal structures include animal, placement day, ready yield, feed/care state, missed-feed count and fertilizer availability.</li><li><code>private.inventories[0]</code> belongs to the farmer; later entries match hired hands.</li><li><code>market.prices</code> and <code>market.inventory</code> are shared and visible to both agents.</li></ul></div></details>
          <h3 className="guide-subtitle">One action dictionary per turn</h3><Code>{ACTION_CODE}</Code>
          <div className="action-reference">{UNIT_ACTIONS.map(([group, actions]) => <div key={group}><b>{group}</b><span>{actions}</span></div>)}</div>
          <div className="market-actions">{MARKET_ACTIONS.map(action => <code key={action}>{action}</code>)}</div>
          <div className="validity-grid"><div><span>VALID</span><code>["PLANT", "WHEAT"]</code><code>["SELL", "EGG", 3]</code><code>["BUY_LAND"]</code></div><div><span>COMMON NO-OPS / ERRORS</span><code>["PLANT", "RICE"]</code><code>["SELL", "WHEAT", -2]</code><code>return ["WATER"]</code><p>Also avoid a missing <code>agent(obs)</code>, wrong hand count or acting on a locked/incorrect tile.</p></div></div>
        </Section>

        <Section id="build" number="08" eyebrow="YOUR CODE" title="What are you actually building?">
          <div className="ownership-grid"><article><span>PROVIDED</span><ul><li>Game engine and movement rules</li><li>Observation and scanning helpers</li><li>Safe action formatting</li><li>Basic job discovery and assignment</li><li>Game constants and starter loop</li></ul></article><article><span>YOU DESIGN</span><ul><li>Crop selection</li><li>Worker priorities and count</li><li>Buying and selling</li><li>Animals and land expansion</li><li>Cash reserve and risk decisions</li></ul></article></div>
          <p>You are changing the decision logic of one farming agent. You do not build the engine, movement physics or frontend.</p><Code>{STARTER_CODE}</Code>
          <Callout label="SAFE START">Keep the provided infrastructure intact first. Make one focused strategy change, then measure what it did.</Callout>
        </Section>

        <Section id="workflow" number="09" eyebrow="ITERATION" title="Use an LLM as a strategy partner">
          <div className="step-line">{["RUN", "FIND ONE PROBLEM", "WRITE A FOCUSED PROMPT", "CHANGE", "TEST AGAIN"].map((step, index) => <div key={step}><b>{index + 1}</b><span>{step}</span></div>)}</div>
          <div className="prompt-compare"><div><span>WEAK PROMPT</span><p>“Make my bot better.”</p></div><div><span>FOCUSED PROMPT</span><p>“My workers spend too many turns moving. Here is my <code>job_score()</code>. Each worker and task has x,y coordinates. Improve only this function so task value and Manhattan distance are both considered. Do not rewrite the agent.”</p></div></div>
          <p>Useful prompts contain: <b>the observed problem, the current function, available information, a constraint, and one requested improvement.</b></p>
          <div className="iteration-example"><span>EXAMPLE</span><p><b>Problem:</b> expensive crops emptied the bank.</p><i>↓</i><p><b>Possible cause:</b> no cash reserve.</p><i>↓</i><p><b>Prompt:</b> keep emergency cash for seeds and feed.</p><i>↓</i><p><b>Compare:</b> minimum cash and final money across several runs.</p></div>
        </Section>

        <Section id="testing" number="10" eyebrow="THE LAB" title="Sandbox, analytics and Strategy Path">
          <p>Sandbox matches are experiments. They do not automatically become your official submission. Choose a public opponent and seed, run the match, inspect the result and replay, then improve your bot. Public opponents differ from hidden evaluation opponents.</p>
          <div className="metric-grid">{[["Final money","The bank balance that decides the match."],["Peak / minimum cash","Shows your financial range and whether spending became fragile."],["Movement %","High travel may indicate poor task assignment or distant layout."],["Idle %","Shows how often units had no productive action."],["Farm utilization","How much unlocked land was occupied."],["Unsold value","Products that never became final score."],["Plants harvested","Production throughput; profit still depends on cost and price."],["Replay","Shows where units moved and what each turn produced."]].map(([name, copy]) => <article key={name}><b>{name}</b><p>{copy}</p></article>)}</div>
          <p>The Strategy Path supplies progressively harder questions and focused prompt starters. It does not provide a final bot. Teams can branch through crop economics, season awareness, workforce, markets, capital, livestock, opponent intelligence and adaptive optimization.</p>
          <button className="button" onClick={() => onNavigate("strategy")}>Open Strategy Path</button>
        </Section>

        <Section id="evaluation" number="11" eyebrow="COMPETITION" title="Hidden evaluation and tournament">
          <p>Official submissions currently play <b>8 hidden games</b>: two hidden opponents × two seeds × both player positions. Rating combines win rate and economic performance. The top <b>16</b> rated teams can be loaded into the live single-elimination tournament.</p>
          <Callout tone="amber" label="GENERALIZE">Do not tune only for one public bot or one seed. Test whether your reasoning survives different prices, layouts, opponents and starting sides.</Callout>
          <div className="mistakes"><span>COMMON BEGINNER MISTAKES</span>{BEGINNER_MISTAKES.map(item => <div key={item}>× {item}</div>)}</div>
        </Section>

        <Section id="quick-start" number="12" eyebrow="DEPLOYMENT CHECKLIST" title="Quick start">
          <ol className="quick-list">{QUICK_START.map((item, index) => <li key={item}><b>{String(index + 1).padStart(2, "0")}</b><span>{item}</span></li>)}</ol>
          <div className="guide-final-actions"><a className="button primary" href={`${import.meta.env.VITE_API_BASE || "http://127.0.0.1:8000"}/starter/download`}>Download starter</a><button className="button" onClick={() => onNavigate("sandbox")}>Enter Sandbox</button></div>
        </Section>
      </article>
    </div>
  </main>;
}

# Neural Coliseum Contestant Guide

## What is Harvest Protocol?

Harvest Protocol is a two-player farming economy simulation. Your Python agent
receives the current game observation once per turn and returns actions for its
farmer, hired hands, and market orders. The season lasts 720 turns. The player
with the most banked money at the end wins.

The event is presented by **SDC (AI/ML Wing), NIT Warangal** through the
**Neural Coliseum** platform.

The challenge is intentionally LLM-assisted. You receive working infrastructure
for reading the state and assigning basic work. Your job is to design and tune a
strategy. Different choices should lead to genuinely different bots.

## Strategy Path and prompt missions

The Strategy Path introduces one concept at a time. A mission explains the
problem, gives a small field hint, and provides a focused prompt you can take to
an LLM. Missions branch into market, workforce, livestock, capital, trading,
opponent awareness, and endgame topics. Arena tests unlock deeper lessons and
produce evidence-based diagnostics. Compare results across public seeds and
keep changes you can explain.

## How a match works

Both agents act from their observations each turn. They can move units, plant and
water crops, harvest products, manage animals, hire workers, buy land, and trade
with a shared dynamic market. Market prices react to supply, and town demand
changes during the season.

A strong bot must balance money, time, distance, production, and market risk.
There is no single strategy required by the starter.

## Observation structure

Your required entry point is:

```python
def agent(obs):
    ...
```

Useful top-level fields include:

```text
obs["player"]   your player index
obs["step"]     current turn
obs["day"]      current day
obs["hour"]     turn within the day
obs["farms"]    both public farm states
obs["private"]  your shed, seeds, and unit inventories
obs["market"]   current inventory and sale prices
obs["town"]     unlocked shops
```

Farm tiles are either empty, locked, or dictionaries describing a plant, weed,
coop, pasture, or animal. Inspect fields defensively with `.get()` because tile
types do not all share the same fields.

## Action structure

Return one dictionary every turn:

```python
{
    "farmer": ["PASS"],
    "hands": [["PASS"], ["PASS"]],
    "market": [],
}
```

There must be one hand action for every currently hired hand. Market actions are
an ordered list and are capped by the environment.

Common unit actions include movement, `PLANT`, `WATER`, `HARVEST`, `DIG`,
`PICKUP`, `DROP`, animal structure actions, `FEED`, and `CARE`. Market actions
include buying seeds, products, animals, land, hiring hands, and selling goods.

## Crops

Crops differ in seed cost, time to first yield, total production, watering value,
and market behavior. Short-cycle crops can return cash sooner. Long-cycle crops
may offer larger payouts but occupy land and capital for longer.

Possible directions include crop specialization, diversification, short-cycle
cash flow, or higher-risk premium crops. The starter deliberately uses only a
simple score. Improve it based on the tradeoffs you want your bot to make.

## Animals

Animals need the correct structure and regular feeding. They can create recurring
products and fertilizer, but they consume capital, worker actions, and wheat.
Animal-heavy, mixed, and crop-only strategies are all valid experiments.

## Market

Sale prices move with shared inventory. A product that looks valuable now may be
oversupplied by the time your harvest arrives. Town shops also create demand.
Think about when to sell, when to hold, and whether your opponent is likely to
produce the same item.

## Workers and movement

Hired hands provide more actions, but they cost money and still spend turns
travelling. Worker count and job assignment should be considered together. A job
can be economically attractive but operationally poor when it is far away.

## Land

Additional quadrants increase capacity but tie up cash. Expanding early, late, or
not at all can each be reasonable depending on the rest of your strategy.

## Starter bot architecture

The downloadable `agent.py` separates two areas:

```text
PROVIDED INFRASTRUCTURE
  observation parsing, farm scanning, movement, job discovery,
  safe market formatting, and basic worker assignment

CONTESTANT STRATEGY
  PARAMS, crop_score, job_score, desired_workers,
  market_strategy, animal_strategy, and land_strategy
```

Start by changing one strategic idea at a time. Use Sandbox results to decide
whether the change helped.

## Strategy directions to explore

- Crop-heavy or animal-heavy production
- Balanced or diversified farms
- Aggressive expansion or cash conservation
- Market speculation or immediate selling
- High-worker automation or low-worker efficiency
- Opponent-aware production
- Premium-crop risk taking
- Short-cycle farming

These are directions, not answers. Combining all of them usually produces an
unclear bot. Choose a thesis and test it.

## Useful questions for your LLM

- How should I calculate crop profitability?
- Should I optimize profit per day or profit per action?
- When should I buy land?
- When should I hire workers?
- How should Manhattan distance affect job priority?
- When should I sell products instead of holding them?
- How can I detect market oversupply?
- Should I specialize or diversify?
- How can I react to what my opponent is growing?
- How much money should I keep as reserve?

Example focused prompts:

```text
My crop selection currently only uses current price. Modify crop_score() so it
also considers expected profit per day. Keep the existing function signature.
```

```text
My workers waste turns travelling. Improve job_score() to account for Manhattan
distance without changing the provided movement helpers.
```

```text
My bot runs out of money early. Add a configurable cash reserve and explain which
buying decisions should respect it.
```

```text
My bot oversupplies one crop and crashes its price. Add market-inventory awareness
to crop_score() and market_strategy() without hardcoding one preferred crop.
```

Ask for explanations and small patches. Avoid prompts such as “write the best
possible bot,” which make results harder to understand and debug.

## How to test your bot

1. Validate the file before running it.
2. Test against several modest public opponents.
3. Reuse a seed when comparing two versions.
4. Try several different public seeds before drawing conclusions.
5. Inspect errors and final money, not only win/loss.
6. Change one or two strategic ideas, then test again.

## What you may modify

Contestants may modify the single downloaded `agent.py`, including provided
helpers if they understand the consequences. Strategy hooks and `PARAMS` are the
recommended starting point.

The submission must remain one Python file, define `agent(obs)`, return the
official action schema, stay within the size limit, and avoid filesystem,
network, process, and interactive operations.

## What you should not modify

Do not depend on local files, environment variables, network calls, subprocesses,
or packages unavailable in the competition worker. Do not create a separate game
environment inside the agent. Do not print large logs or wait for user input.

## Common mistakes

- Returning the wrong number of hand actions
- Spending the full bank with no operating reserve
- Ignoring travel distance
- Buying seeds without enough empty unlocked land
- Forgetting to water or feed for consecutive days
- Harvesting without returning inventory to the shed
- Producing one good after its market becomes oversupplied
- Measuring only one seed or one opponent
- Making many changes before retesting
- Treating a validation failure as a score of zero instead of reading the error

The starter contains no hidden optimal constants. Its defaults are deliberately
modest so the competition rewards analysis, prompting, experimentation, and
strategy design.

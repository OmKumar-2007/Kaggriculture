export const GAME_FACTS = [
  ["2", "AI farms"],
  ["30", "in-game days"],
  ["720", "total turns"],
  ["10×10", "tiles per farm"],
  ["3,000", "starting credits"],
  ["100", "shed capacity"],
];

export const CROPS = [
  { name: "Wheat", cost: 10, first: 2, peak: 4, yield: "6 max*", behavior: "One-time" },
  { name: "Carrot", cost: 20, first: 2, peak: 3, yield: "4 max*", behavior: "One-time" },
  { name: "Tomato", cost: 50, first: 8, peak: 11, yield: "4 cycles", behavior: "Daily ongoing" },
  { name: "Strawberry", cost: 100, first: 10, peak: 16, yield: "4 cycles", behavior: "Every 2 days" },
  { name: "Melon", cost: 80, first: 10, peak: 12, yield: "6 max", behavior: "One-time" },
];

export const ANIMALS = [
  { name: "Goose", cost: 300, home: "Coop", first: 4, cadence: "Daily", product: "Egg", held: 4 },
  { name: "Cow", cost: 400, home: "Pasture", first: 8, cadence: "Every 2 days", product: "Milk", held: 6 },
  { name: "Sheep", cost: 500, home: "Pasture", first: 6, cadence: "Every 3 days", product: "Wool", held: 6 },
];

export const UNIT_ACTIONS = [
  ["Movement", "NORTH · SOUTH · EAST · WEST · PASS"],
  ["Crops", "PLANT crop · WATER · HARVEST · FERTILIZE"],
  ["Animals", "BUILD_COOP · BUILD_PASTURE · PLACE · FEED · CARE · HARVEST · COLLECT_FERTILIZER"],
  ["Logistics", "PICKUP item [n] · PLACE item [n] · DROP · DIG"],
];

export const MARKET_ACTIONS = [
  "BUY_SEED crop n", "BUY_PRODUCT item n", "BUY_ANIMAL animal n",
  "SELL item n", "HIRE", "BUY_LAND",
];

export const GUIDE_SECTIONS = [
  ["overview", "Mission brief"],
  ["match", "Match loop"],
  ["board", "Farm board"],
  ["production", "Crops & animals"],
  ["workers", "Workers & shed"],
  ["market", "Market & land"],
  ["interface", "Observations & actions"],
  ["build", "What you build"],
  ["workflow", "LLM workflow"],
  ["testing", "Testing & analytics"],
  ["evaluation", "Evaluation"],
  ["quick-start", "Quick start"],
];

export const OBSERVATION_CODE = `obs = {
    "step": 0,
    "day": 0,
    "hour": 0,
    "player": 0,
    "farms": [your_public_farm, opponent_public_farm],
    "private": {
        "shed": {...},
        "seeds": {...},
        "inventories": [farmer_inventory, ...]
    },
    "market": {"prices": {...}, "inventory": {...}},
    "town": {"unlocked_shops": [...]}
}`;

export const ACTION_CODE = `return {
    "farmer": ["WATER"],
    "hands": [["HARVEST"], ["WEST"]],
    "market": [
        ["SELL", "CARROT", 4],
        ["BUY_SEED", "WHEAT", 2]
    ]
}`;

export const STARTER_CODE = `PARAMS = { ... }                    # EDIT

def crop_score(crop, state): ...   # EDIT
def job_score(job, worker, state): ...
def desired_workers(state): ...
def market_strategy(state, crop): ...
def animal_strategy(state): ...
def land_strategy(state): ...

def agent(obs):                    # PROVIDED PIPELINE
    state = build_state(obs)
    jobs = discover_jobs(state, choose_crop(state))
    actions = assign_workers(jobs, state)
    return {"farmer": ..., "hands": ..., "market": ...}`;

export const QUICK_START = [
  "Download the starter bot.",
  "Read the editable strategy functions.",
  "Run one sandbox match unchanged.",
  "Inspect the score, diagnostics, analytics and replay.",
  "Choose one weakness.",
  "Copy a focused Strategy Path prompt.",
  "Ask your LLM to improve only that part.",
  "Upload and test again with more than one seed.",
  "Repeat, then submit your best version.",
];

export const BEGINNER_MISTAKES = [
  "Choosing crops only by current price",
  "Spending every available credit",
  "Ignoring remaining days",
  "Sending workers to the same job",
  "Ignoring travel distance",
  "Overproducing one product",
  "Forgetting feed or same-day watering",
  "Ending with unsold goods",
  "Testing only one seed or opponent",
  "Asking an LLM to rewrite the whole bot",
];

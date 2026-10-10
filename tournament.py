import sys
import os
import json
import random
import re
import subprocess
from pathlib import Path

# Fix Windows console charmap / emoji encoding issues
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from py_env import get_kaggle_python


# ============================================================
# PROJECT ROOT
# ============================================================

ROOT = Path(__file__).resolve().parent

RUN_MATCH = ROOT / "run_match.py"

PLAYERS_DIR = ROOT / "players"

# Maximum number of times a tied match can be replayed
MAX_TIE_REPLAYS = 10


def run_seeded_tournament(participants, *, seed=20260929, max_tie_replays=3,
                          on_progress=None, completed_matches=None, completed_games=None):
    """Run a fixed bracket from a frozen, rank-ordered qualifier roster.

    ``completed_matches`` permits a restarted worker to reuse committed pairings.
    A single pairing is committed only after both side-swapped legs succeed.
    """
    from backend.services.bracket import aggregate_swapped_legs, opening_bracket, seed_positions

    bracket = opening_bracket(participants)
    if max_tie_replays < 0 or max_tie_replays > 20:
        raise ValueError("Tie replay limit must be between 0 and 20.")
    completed = {row["matchId"]: row for row in completed_matches or []}
    saved_games = {row["gameId"]: row for row in completed_games or []}
    # The caller supplies frozen file paths, ordered by qualification rank.
    slots = [participants[s - 1] if s <= len(participants) else None
             for s in seed_positions(bracket["capacity"])]
    history = list(completed.values())
    for round_number in range(1, bracket["rounds"] + 1):
        next_slots = []
        planned = []
        for index in range(0, len(slots), 2):
            left, right = slots[index:index + 2]
            match_id = f"R{round_number}_M{index // 2 + 1}"
            if left and right:
                planned.append({"id": match_id, "round": round_number,
                                "matchIndex": index // 2, "player1": left["username"],
                                "player2": right["username"],"seedA":left["seed"],
                                "seedB":right["seed"],"status": "pending"})
        if on_progress:
            on_progress("ROUND_START", {"round": round_number, "matches": planned,
                                         "byePlayers": [p["username"] for i in range(0, len(slots), 2)
                                                        for p in [slots[i]] if p and slots[i + 1] is None],
                                         "isFinal": len(slots) == 2})
        for index in range(0, len(slots), 2):
            left, right = slots[index:index + 2]
            match_id = f"R{round_number}_M{index // 2 + 1}"
            if right is None:
                if left is None:
                    raise ValueError("Invalid empty bracket pairing.")
                next_slots.append(left)
                continue
            if left is None:
                next_slots.append(right)
                continue
            prior = completed.get(match_id)
            if prior:
                if (prior.get("player1"), prior.get("player2")) != (left["username"], right["username"]):
                    raise ValueError("Persisted match does not match the frozen bracket.")
                if prior.get("winner") not in (left["username"], right["username"]):
                    raise ValueError("Persisted match has no valid winner.")
                winner = left if prior["winner"] == left["username"] else right
                next_slots.append(winner)
                continue
            if on_progress:
                on_progress("MATCH_START", {"round": round_number, "matchIndex": index // 2,
                                             "matchId": match_id, "player1": left["username"],
                                             "player2": right["username"]})
            total_left = total_right = 0.0
            replay_ids = []
            tiebreak = None
            for replay in range(max_tie_replays + 1):
                match_seed = seed + round_number * 100000 + (index // 2) * 100 + replay
                def leg_result(leg_index, zero, one):
                    game_id = f"{match_id}_P{replay}_L{leg_index}"
                    saved = saved_games.get(game_id)
                    if saved:
                        if (saved["seed"], saved["playerZero"], saved["playerOne"]) != (
                            match_seed, zero["username"], one["username"]):
                            raise ValueError("Persisted game does not match the frozen bracket.")
                        return {"p1Score": saved["scoreZero"], "p2Score": saved["scoreOne"],
                                "replayId": saved.get("replayId")}
                    game = run_match(zero, one, match_seed, docker_only=True)
                    if on_progress:
                        on_progress("GAME_END", {"gameId": game_id, "matchId": match_id,
                            "round": round_number, "replay": replay, "leg": leg_index,
                            "seed": match_seed, "playerZero": zero["username"],
                            "playerOne": one["username"], "scoreZero": game["p1Score"],
                            "scoreOne": game["p2Score"], "replayId": game.get("replayId")})
                    return game
                first = leg_result(0, left, right)
                second = leg_result(1, right, left)
                leg_left, leg_right = aggregate_swapped_legs(first, second)
                total_left += leg_left
                total_right += leg_right
                replay_ids.extend(leg["replayId"] for leg in (first, second) if leg.get("replayId"))
                if total_left != total_right:
                    break
            if total_left == total_right:
                winner = left if left["seed"] < right["seed"] else right
                tiebreak = "higher_qualification_seed"
            else:
                winner = left if total_left > total_right else right
            loser = right if winner is left else left
            record = {"round": round_number, "matchId": match_id,
                      "matchIndex": index // 2, "player1": left["username"],
                      "player2": right["username"],"seedA":left["seed"],
                      "seedB":right["seed"],"p1Score": total_left,
                      "p2Score": total_right, "winner": winner["username"],
                      "loser": loser["username"], "seed": match_seed,
                      "tieReplays": replay, "tieBreak": tiebreak,
                      "legs": 2 * (replay + 1), "replayIds": replay_ids,
                      "status": "completed"}
            history.append(record)
            if on_progress:
                on_progress("MATCH_END", record)
            next_slots.append(winner)
        slots = next_slots
        if on_progress:
            on_progress("ROUND_END", {"round": round_number,
                                       "advancing": [p["username"] for p in slots],
                                       "remainingCount": len(slots)})
    if len(history) != len(participants) - 1:
        raise ValueError("The bracket did not complete the required pairings.")
    champion = {"username": slots[0]["username"]}
    if on_progress:
        on_progress("TOURNAMENT_END", {"champion": champion, "finalMatch": history[-1]})
    return {"champion": champion, "history": history, "error": None,
            "totalRounds": bracket["rounds"]}


# ============================================================
# JSON EXTRACTION
# ============================================================

def extract_json_from_output(output):
    """
    Extract a JSON object from noisy subprocess output.
    """

    if not output:
        raise ValueError(
            "run_match.py produced no output."
        )

    output = output.strip()

    # --------------------------------------------------------
    # 1. Try complete lines from bottom to top
    # --------------------------------------------------------

    lines = output.splitlines()

    for line in reversed(lines):

        line = line.strip()

        if not line:
            continue

        if not (
            line.startswith("{")
            and line.endswith("}")
        ):
            continue

        try:

            data = json.loads(line)

            if isinstance(data, dict):
                return data

        except json.JSONDecodeError:
            pass

    # --------------------------------------------------------
    # 2. Regex fallback
    # --------------------------------------------------------

    matches = re.findall(
        r"\{[\s\S]*?\}",
        output
    )

    for match in reversed(matches):

        try:

            data = json.loads(match)

            if isinstance(data, dict):
                return data

        except json.JSONDecodeError:
            continue

    raise ValueError(
        "Could not find valid JSON in run_match output.\n"
        f"Output was:\n{output}"
    )


# ============================================================
# PATH RESOLUTION
# ============================================================

def resolve_participant_path(file_path):
    """
    Convert participant path into an absolute path.
    """

    raw = Path(str(file_path)).expanduser()

    # Already absolute
    if raw.is_absolute():

        path = raw.resolve()

    else:

        # Try relative to tournament project
        path = (ROOT / raw).resolve()

        # If not found, try current directory
        if not path.exists():

            path = (
                Path.cwd() / raw
            ).resolve()

    if not path.exists():

        raise FileNotFoundError(
            f"Participant file does not exist:\n{path}"
        )

    if not path.is_file():

        raise ValueError(
            f"Participant path is not a file:\n{path}"
        )

    if path.suffix.lower() != ".py":

        raise ValueError(
            f"Participant must be a .py file:\n{path}"
        )

    return path


# ============================================================
# LOAD REGISTERED PLAYERS
# ============================================================

def load_registered_players():
    """
    Load all players registered through the frontend.

    Expected structure:

        players/
        ├── ansh/
        │   └── agent.py
        ├── manav/
        │   └── agent.py
        ├── saksham/
        │   └── agent.py
        └── trushank/
            └── agent.py
    """

    if not PLAYERS_DIR.exists():

        raise RuntimeError(
            "players/ directory does not exist."
        )

    participants = []

    for player_dir in PLAYERS_DIR.iterdir():

        if not player_dir.is_dir():
            continue

        agent_path = player_dir / "agent.py"

        # Ignore incomplete registrations
        if not agent_path.exists():
            continue

        participants.append(
            {
                "username": player_dir.name,
                "filePath": str(
                    agent_path.resolve()
                ),
            }
        )

    # Predictable ordering before random tournament pairing
    participants.sort(
        key=lambda player:
        player["username"].lower()
    )

    return participants


# ============================================================
# RUN ONE MATCH
# ============================================================

def run_match(player1, player2, seed, *, docker_only=False):
    """
    Run run_match.py through subprocess.
    """

    agent1 = resolve_participant_path(
        player1["filePath"]
    )

    agent2 = resolve_participant_path(
        player2["filePath"]
    )

    # --------------------------------------------------------
    # Build subprocess command
    # NOTE: [DEV / TRUSTED LOCAL EXECUTION PATH]
    # For production, wrap with Docker container isolation.
    # --------------------------------------------------------

    if docker_only or os.getenv("NEURAL_COLISEUM_TRUSTED_LOCAL") != "1":
        from backend.services.sandbox import _run_docker, REPLAY_DIR
        from backend.services.blob_storage import objects
        from uuid import uuid4
        replay_id = uuid4().hex
        replay_path = REPLAY_DIR / f"{replay_id}.json"
        result = _run_docker(agent1, agent2, seed, replay_path)
        result["p1Score"] = float(result["p1Score"])
        result["p2Score"] = float(result["p2Score"])
        if replay_path.is_file():
            objects.put_bytes(f"replays/{replay_id}.json", replay_path.read_bytes(), "application/json")
            result["replayId"] = replay_id
        return result

    python_exe = get_kaggle_python()

    command = [
        python_exe,
        str(RUN_MATCH),

        "--agent1",
        str(agent1),

        "--agent2",
        str(agent2),

        "--seed",
        str(seed),
    ]

    print(
        f"[MATCH] "
        f"{player1['username']} "
        f"vs "
        f"{player2['username']}..."
    )

    try:

        process = subprocess.run(
            command,

            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,

            text=True,

            cwd=str(ROOT),

            timeout=120,
        )

    except subprocess.TimeoutExpired:

        raise RuntimeError(
            "Match timed out after 120 seconds."
        )

    except Exception as e:

        raise RuntimeError(
            f"Could not start match process: {e}"
        )

    # --------------------------------------------------------
    # Get output
    # --------------------------------------------------------

    stdout = process.stdout or ""
    stderr = process.stderr or ""

    combined_output = (
        stdout
        + "\n"
        + stderr
    )

    # --------------------------------------------------------
    # Extract JSON
    # --------------------------------------------------------

    try:

        result = extract_json_from_output(
            combined_output
        )

    except Exception as e:

        raise RuntimeError(
            "Could not parse match result.\n"
            f"Process exit code: {process.returncode}\n"
            f"STDOUT:\n{stdout}\n"
            f"STDERR:\n{stderr}\n"
            f"Parser error:\n{e}"
        )

    # --------------------------------------------------------
    # Check explicit error
    # --------------------------------------------------------

    if "error" in result:

        raise RuntimeError(
            f"Match execution failed: "
            f"{result['error']}"
        )

    # --------------------------------------------------------
    # Validate required fields
    # --------------------------------------------------------

    required = [
        "p1Score",
        "p2Score",
        "winner",
    ]

    for key in required:

        if key not in result:

            raise RuntimeError(
                f"Match result missing '{key}'.\n"
                f"Received: {result}"
            )

    # --------------------------------------------------------
    # Validate winner
    # --------------------------------------------------------

    if (
        result["winner"] is not None
        and result["winner"] not in (0, 1)
    ):

        raise RuntimeError(
            f"Invalid winner value: "
            f"{result['winner']}"
        )

    # --------------------------------------------------------
    # Convert scores
    # --------------------------------------------------------

    try:

        result["p1Score"] = float(
            result["p1Score"]
        )

        result["p2Score"] = float(
            result["p2Score"]
        )

    except (TypeError, ValueError):

        raise RuntimeError(
            f"Invalid score values: {result}"
        )

    # --------------------------------------------------------
    # Determine tie
    # --------------------------------------------------------

    result["tie"] = (
        result["p1Score"]
        == result["p2Score"]
    )

    return result


# ============================================================
# TOURNAMENT
# ============================================================

def run_tournament(
    participants,
    seed=20260929,
    random_seed=None,
    on_progress=None,
):
    """
    Run a complete single-elimination tournament.
    Optional on_progress callback receives (event_name, payload).
    """

    def _notify(event, data):
        if on_progress:
            on_progress(event, data)

    # --------------------------------------------------------
    # Basic validation
    # --------------------------------------------------------

    if not participants:

        raise ValueError(
            "Tournament has no participants."
        )

    # --------------------------------------------------------
    # Validate all participants BEFORE starting
    # --------------------------------------------------------

    validated_players = []

    usernames = set()

    for player in participants:

        if "username" not in player:

            raise ValueError(
                "Participant missing username."
            )

        if "filePath" not in player:

            raise ValueError(
                f"{player['username']} "
                "missing filePath."
            )

        username = str(
            player["username"]
        ).strip()

        if not username:

            raise ValueError(
                "Participant has empty username."
            )

        if username.lower() in usernames:

            raise ValueError(
                f"Duplicate username: {username}"
            )

        usernames.add(
            username.lower()
        )

        absolute_path = resolve_participant_path(
            player["filePath"]
        )

        validated_players.append(
            {
                "username": username,
                "filePath": str(
                    absolute_path
                ),
            }
        )

    players = validated_players

    # --------------------------------------------------------
    # Random generator
    # --------------------------------------------------------

    if random_seed is None:

        rng = random.SystemRandom()

    else:

        rng = random.Random(
            random_seed
        )

    round_number = 1

    match_history = []

    # ========================================================
    # ROUND LOOP
    # ========================================================

    while len(players) > 1:

        print()

        print(
            "=" * 20
            + f" ROUND {round_number} "
            + "=" * 20
        )

        print(
            f"Players remaining: {len(players)}"
        )

        # ----------------------------------------------------
        # Random BYE if odd number
        # ----------------------------------------------------

        bye_player = None

        if len(players) % 2 == 1:

            bye_index = rng.randrange(
                len(players)
            )

            bye_player = players.pop(
                bye_index
            )

            print()

            print(
                f"[BYE] "
                f"{bye_player['username']} "
                f"advances automatically."
            )

        # ----------------------------------------------------
        # Randomize pairings
        # ----------------------------------------------------

        rng.shuffle(players)

        next_round = []

        # ----------------------------------------------------
        # Prepare planned matches & notify round start
        # ----------------------------------------------------

        planned_matches = []
        for m_idx in range(0, len(players), 2):
            planned_matches.append({
                "id": f"R{round_number}_M{m_idx // 2 + 1}",
                "round": round_number,
                "matchIndex": m_idx // 2,
                "player1": players[m_idx]["username"],
                "player2": players[m_idx + 1]["username"],
                "status": "pending",
                "p1Score": None,
                "p2Score": None,
                "winner": None,
                "loser": None,
                "tieReplays": 0,
                "replayIds": [],
            })

        _notify("ROUND_START", {
            "round": round_number,
            "playersRemaining": [p["username"] for p in players] + ([bye_player["username"]] if bye_player else []),
            "matches": planned_matches,
            "byePlayer": bye_player["username"] if bye_player else None,
            "isFinal": len(players) == 2 and bye_player is None,
        })

        # ----------------------------------------------------
        # Run matches
        # ----------------------------------------------------

        for i in range(
            0,
            len(players),
            2
        ):

            player1 = players[i]
            player2 = players[i + 1]
            match_id = f"R{round_number}_M{i // 2 + 1}"

            print()

            _notify("MATCH_START", {
                "round": round_number,
                "matchIndex": i // 2,
                "matchId": match_id,
                "player1": player1["username"],
                "player2": player2["username"],
            })

            # =================================================
            # MATCH + TIE REPLAY SYSTEM
            # =================================================

            match_seed = seed
            tie_replays = 0

            try:

                while True:
                    is_final_series = len(players) == 2 and bye_player is None
                    if is_final_series:
                        first_leg = run_match(player1, player2, match_seed)
                        second_leg = run_match(player2, player1, match_seed)
                        p1_total = first_leg["p1Score"] + second_leg["p2Score"]
                        p2_total = first_leg["p2Score"] + second_leg["p1Score"]
                        result = {
                            "p1Score": p1_total, "p2Score": p2_total,
                            "winner": 0 if p1_total > p2_total else 1 if p2_total > p1_total else None,
                            "tie": p1_total == p2_total, "legs": 2,
                            "failures": [leg.get("failure") for leg in (first_leg, second_leg) if leg.get("failure")],
                            "replayIds": [leg["replayId"] for leg in (first_leg, second_leg) if leg.get("replayId")],
                        }
                    else:
                        result = run_match(player1, player2, match_seed)
                        result["legs"] = 1
                        result["replayIds"] = [result["replayId"]] if result.get("replayId") else []

                    # ------------------------------------------------
                    # TIE
                    # ------------------------------------------------

                    if result["tie"]:
                        print(
                            f"    -> TIE "
                            f"({result['p1Score']} - "
                            f"{result['p2Score']})"
                        )

                        # A persistent exact draw cannot advance an elimination
                        # bracket. Use the bracket's seeded RNG only after all
                        # permitted replays, and disclose that decision.
                        if tie_replays >= MAX_TIE_REPLAYS:
                            result["winner"] = rng.randrange(2)
                            result["tie"] = False
                            result["tieBreak"] = "seeded_lot"
                            print("    -> Winner selected by seeded lot after tied replays.")
                            break

                        tie_replays += 1

                        # ------------------------------------------------
                        # New seed for replay
                        # ------------------------------------------------

                        match_seed = (
                            seed + tie_replays
                        )

                        print(
                            f"    -> Replaying match "
                            f"with seed {match_seed}..."
                        )

                        continue

                    # ------------------------------------------------
                    # Decisive result
                    # ------------------------------------------------

                    break

            except Exception as e:

                print(
                    f"[ERROR] "
                    f"{player1['username']} vs "
                    f"{player2['username']}"
                )

                print(
                    f"        {e}"
                )

                print()

                print(
                    "Tournament aborted because "
                    "a match could not be executed."
                )

                _notify("TOURNAMENT_ERROR", {
                    "error": str(e),
                    "round": round_number,
                    "matchId": match_id,
                })

                return {
                    "champion": None,
                    "history": match_history,
                    "error": str(e),
                }

            # =================================================
            # DETERMINE WINNER
            # =================================================

            if result["winner"] == 0:

                winner = player1
                loser = player2

            else:

                winner = player2
                loser = player1

            # ------------------------------------------------
            # Display final match result
            # ------------------------------------------------

            print(
                f"    "
                f"{player1['username']} "
                f"({result['p1Score']}) "
                f"vs "
                f"{player2['username']} "
                f"({result['p2Score']})"
            )

            print(
                f"    -> WINNER: "
                f"{winner['username']}"
            )

            if tie_replays > 0:

                print(
                    f"    -> Tie replays: "
                    f"{tie_replays}"
                )

            # =================================================
            # SAVE MATCH HISTORY
            # =================================================

            match_history.append(
                {
                    "round": round_number,

                    "player1": player1["username"],
                    "player2": player2["username"],

                    "p1Score": result["p1Score"],
                    "p2Score": result["p2Score"],

                    "winner": winner["username"],
                    "loser": loser["username"],

                    "seed": match_seed,

                    "tieReplays": tie_replays,
                    "tieBreak": result.get("tieBreak"),
                    "legs": result.get("legs", 1),
                    "replayIds": result.get("replayIds", []),
                    "failures": result.get("failures", [result.get("failure")] if result.get("failure") else []),
                }
            )

            _notify("MATCH_END", {
                "round": round_number,
                "matchIndex": i // 2,
                "matchId": match_id,
                "player1": player1["username"],
                "player2": player2["username"],
                "p1Score": result["p1Score"],
                "p2Score": result["p2Score"],
                "winner": winner["username"],
                "loser": loser["username"],
                "seed": match_seed,
                "tieReplays": tie_replays,
                "tieBreak": result.get("tieBreak"),
                "legs": result.get("legs", 1),
                "replayIds": result.get("replayIds", []),
                "failures": result.get("failures", [result.get("failure")] if result.get("failure") else []),
            })

            # ------------------------------------------------
            # Advance winner
            # ------------------------------------------------

            next_round.append(
                winner
            )

        # ----------------------------------------------------
        # Add BYE player to next round
        # ----------------------------------------------------

        if bye_player is not None:

            next_round.append(
                bye_player
            )

        # ----------------------------------------------------
        # Move to next round
        # ----------------------------------------------------

        players = next_round

        _notify("ROUND_END", {
            "round": round_number,
            "advancing": [p["username"] for p in next_round],
            "remainingCount": len(players),
        })

        round_number += 1

    # ========================================================
    # CHAMPION
    # ========================================================

    champion = players[0]

    print()

    print(
        "=" * 55
    )

    print(
        f"*** TOURNAMENT CHAMPION: "
        f"{champion['username']} ***"
    )

    print(
        f"Agent: {champion['filePath']}"
    )

    print(
        "=" * 55
    )

    public_champion = {"username": champion["username"]}
    _notify("TOURNAMENT_END", {
        "champion": public_champion,
        "history": match_history,
        "totalRounds": round_number - 1,
        "finalMatch": match_history[-1] if match_history else None,
    })

    return {
        "champion": public_champion,
        "history": match_history,
        "error": None,
        "totalRounds": round_number - 1,
    }


# ============================================================
# START TOURNAMENT USING REGISTERED PLAYERS
# ============================================================

if __name__ == "__main__":

    try:

        participants = load_registered_players()

        print()

        print(
            "=" * 55
        )

        print(
            "REGISTERED PLAYERS"
        )

        print(
            "=" * 55
        )

        for index, player in enumerate(
            participants,
            start=1
        ):

            print(
                f"{index:02d}. "
                f"{player['username']}"
            )

        print()

        print(
            f"Total players: "
            f"{len(participants)}"
        )

        print(
            "=" * 55
        )

        # ----------------------------------------------------
        # Minimum players
        # ----------------------------------------------------

        if len(participants) < 2:

            print(
                "Need at least 2 players "
                "to start the tournament."
            )

            sys.exit(1)

        # ----------------------------------------------------
        # Start tournament
        # ----------------------------------------------------

        result = run_tournament(
            participants,
            seed=20260929,
            random_seed=42,
        )

        print()

        print(
            "Tournament result:"
        )

        print(
            json.dumps(
                result,
                indent=2
            )
        )

    except Exception as e:

        print()

        print(
            f"[ERROR] {e}"
        )

        sys.exit(1)

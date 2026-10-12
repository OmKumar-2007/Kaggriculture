"""Capacity estimate only; this script does not submit jobs or contact Azure."""
import argparse
import math


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--teams", type=int, default=30)
    parser.add_argument("--references", type=int, default=3)
    parser.add_argument("--seeds", type=int, default=1)
    parser.add_argument("--seconds-per-game", type=float, required=True,
                        help="Measured p95 of full-length isolated engine games")
    parser.add_argument("--overhead-seconds", type=float, default=120,
                        help="Budget for startup, queueing, upload, and result persistence")
    parser.add_argument("--target-seconds", type=float, default=900)
    args = parser.parse_args()
    if min(args.teams, args.references, args.seeds) < 1 or args.seconds_per_game <= 0:
        parser.error("counts and game duration must be positive")
    available = args.target_seconds - args.overhead_seconds
    if available <= 0:
        parser.error("target must exceed overhead")
    games = args.teams * args.references * args.seeds * 2
    slots = math.ceil(games * args.seconds_per_game / available)
    print(f"{games} games; {games * args.seconds_per_game:.0f} slot-seconds; "
          f"at least {slots} concurrent evaluation slots before retry/capacity margin")


if __name__ == "__main__":
    main()

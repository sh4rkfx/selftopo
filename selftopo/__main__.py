"""Command line interface: `python -m selftopo <command>`."""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Callable
from datetime import date

from . import activities, bloodpressure, climbs, config, fitness, garmin, hevy, lifestyle, yazio

log = logging.getLogger("selftopo")

SOURCES: dict[str, Callable[..., None]] = {
    "garmin": garmin.sync,
    "activities": activities.sync,
    "climbs": climbs.sync,  # needs the activities written just before
    "fitness": fitness.sync,
    "bp": bloodpressure.sync,
    "lifestyle": lifestyle.sync,
    "hevy": hevy.sync,
    "yazio": yazio.sync,
}


def _positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def cmd_sync(args: argparse.Namespace) -> int:
    """Run each selected source; one failing source does not stop the others."""
    selected = list(SOURCES) if args.source == "all" else [args.source]
    failed = []
    for name in selected:
        if name == "yazio" and args.source == "all" and not yazio.is_configured():
            log.info("yazio: not set up, skipped (run `yazio-login` to enable it)")
            continue
        try:
            SOURCES[name](args.days, refresh=args.refresh)
        except config.SetupError as exc:
            log.error("%s: %s", name, exc)
            failed.append(name)
        except Exception:
            log.exception("%s: sync failed", name)
            failed.append(name)
    if failed:
        log.error("Failed sources: %s", ", ".join(failed))
        return 1
    return 0


def cmd_analyze(args: argparse.Namespace) -> int:
    from . import analyze, recommend  # pandas and scipy are only needed for these commands

    result = analyze.run(args.days)
    # The daily workflow only calls analyze, so the recommendations are refreshed here as well.
    # A failing rule must not cost the analysis, which is already written.
    try:
        recommend.run()
    except Exception:
        log.exception("recommend: failed, recommendations.json not updated")
    period = result.get("period")
    if not period:
        print(result.get("note", "No data."))
        return 0
    print(f"{period['start']} to {period['end']}: {result['tested']} pairs tested, {result['robust']} robust")
    shown = [f for f in result["findings"] if f["status"] != "none"]
    for finding in shown[: args.top]:
        marker = "robust  " if finding["status"] == "robust" else "tendency"
        print(f"  {marker} {analyze.describe(finding)}")
    if not shown:
        print("  No relationship stands out yet. More days usually help.")
    return 0


def cmd_login(_: argparse.Namespace) -> int:
    garmin.login_interactive()
    print(f"Garmin tokens saved to {config.TOKEN_DIR}")
    return 0


def cmd_recommend(_: argparse.Namespace) -> int:
    from . import recommend  # pandas is only needed for this command

    result = recommend.run()
    if result["today"]:
        print(f"Today: {result['today']['title']['text']}")
    for card in result["safety"] + result["cards"]:
        print(f"  {card['number']:>2} {card['title']['text']}")
    if not result["goals"]:
        print('No goals set. Add "goals" to settings.json to get recommendations beyond the Today card.')
    return 0


def cmd_push_keys(_: argparse.Namespace) -> int:
    from . import push

    public, private = push.generate_keys()
    print("Public key (dashboard: gear icon -> App -> Push notifications):")
    print(f"  {public}")
    print("Private key (data repository: Settings -> Secrets -> Actions -> VAPID_PRIVATE_KEY; keep it secret):")
    print(f"  {private}")
    return 0


def cmd_push(args: argparse.Namespace) -> int:
    from . import push

    push.run(test=args.test)
    return 0


def cmd_export_tokens(_: argparse.Namespace) -> int:
    print(garmin.export_tokens())
    return 0


def cmd_yazio_login(_: argparse.Namespace) -> int:
    yazio.login_interactive()
    print(f"YAZIO tokens saved to {config.YAZIO_TOKEN_DIR}")
    return 0


def cmd_yazio_tokens(_: argparse.Namespace) -> int:
    print(yazio.export_tokens())
    return 0


def cmd_dump_yazio(args: argparse.Namespace) -> int:
    path = yazio.dump_raw(args.date)
    print(f"Raw YAZIO responses written to {path} (contains health data, do not commit)")
    return 0


def cmd_dump_fitness(_: argparse.Namespace) -> int:
    print(garmin.dump_fitness())
    return 0


def cmd_dump_raw(args: argparse.Namespace) -> int:
    path = garmin.dump_raw(args.date)
    print(f"Raw Garmin responses written to {path} (contains health data, do not commit)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m selftopo", description=__doc__)
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    commands = parser.add_subparsers(dest="command", required=True)

    sync = commands.add_parser("sync", help="fetch data and update the CSV files")
    sync.add_argument("--days", type=_positive_int, default=30, help="days to fetch (default: 30)")
    sync.add_argument("--source", choices=["all", *SOURCES], default="all")
    sync.add_argument("--refresh", action="store_true",
                      help="fetch stored Garmin days again, e.g. to fill newly added columns")
    sync.set_defaults(handler=cmd_sync)

    analyze = commands.add_parser("analyze", help="find time-lagged relationships, write data/insights.json "
                                  "and data/recommendations.json")
    analyze.add_argument("--days", type=_positive_int, default=180, help="days to analyze (default: 180)")
    analyze.add_argument("--top", type=_positive_int, default=10, help="findings to print (default: 10)")
    analyze.set_defaults(handler=cmd_analyze)

    recommend = commands.add_parser("recommend", help="evaluate the rules for your goals, write "
                                    "data/recommendations.json (analyze does this too)")
    recommend.set_defaults(handler=cmd_recommend)

    push_keys = commands.add_parser("push-keys", help="make the key pair for push notifications")
    push_keys.set_defaults(handler=cmd_push_keys)

    push = commands.add_parser("push", help="send today's Today card to the devices with notifications on")
    push.add_argument("--test", action="store_true", help="send a test message instead")
    push.set_defaults(handler=cmd_push)

    login = commands.add_parser("login", help="log in to Garmin with email/password and save tokens")
    login.set_defaults(handler=cmd_login)

    export = commands.add_parser("export-tokens", help="print Garmin tokens for the GitHub secret")
    export.set_defaults(handler=cmd_export_tokens)

    yazio_login = commands.add_parser("yazio-login", help="log in to YAZIO with email/password and save tokens")
    yazio_login.set_defaults(handler=cmd_yazio_login)

    yazio_tokens = commands.add_parser("yazio-tokens", help="print YAZIO tokens for the GitHub secret")
    yazio_tokens.set_defaults(handler=cmd_yazio_tokens)

    dump_yazio = commands.add_parser("dump-yazio", help="save raw YAZIO responses for one day")
    dump_yazio.add_argument("--date", type=date.fromisoformat, default=config.today(), help="YYYY-MM-DD")
    dump_yazio.set_defaults(handler=cmd_dump_yazio)

    dump_fit = commands.add_parser("dump-fitness", help="save raw Garmin fitness responses next to the data files")
    dump_fit.set_defaults(handler=cmd_dump_fitness)

    dump = commands.add_parser("dump-raw", help="save raw Garmin responses for one day")
    dump.add_argument("--date", type=date.fromisoformat, default=config.today(), help="YYYY-MM-DD")
    dump.set_defaults(handler=cmd_dump_raw)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    for problem in config.SETTINGS_PROBLEMS:
        log.warning("settings: %s", problem)
    if config.TIMEZONE_SOURCE == "default" and args.handler in (cmd_sync, cmd_analyze, cmd_recommend):
        log.warning('settings: no time zone set, using UTC. Add "timezone" to %s or set SELFTOPO_TZ.',
                    config.SETTINGS_JSON)
    try:
        return args.handler(args)
    except config.SetupError as exc:
        log.error("%s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())

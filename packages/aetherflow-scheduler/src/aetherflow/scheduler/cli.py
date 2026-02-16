import argparse
import sys

from aetherflow.scheduler.scheduler import run_scheduler


def main(argv=None) -> int:
    argv = argv or sys.argv[1:]
    p = argparse.ArgumentParser(prog="aetherflow-scheduler")
    p.add_argument("cmd", choices=["run"])
    p.add_argument("scheduler_yaml")
    args = p.parse_args(argv)
    if args.cmd == "run":
        run_scheduler(args.scheduler_yaml)
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

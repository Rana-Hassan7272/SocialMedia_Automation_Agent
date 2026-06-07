import argparse
import subprocess
import sys


def run_streamlit():
    subprocess.run(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            "app.py",
            "--server.headless",
            "true",
            "--browser.gatherUsageStats",
            "false",
        ],
        check=False,
    )


def run_verify():
    from verify_setup import main as verify_main
    verify_main()


def run_init_db():
    from init_db import main as init_main
    init_main()


def run_migrate():
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=False)


def main():
    parser = argparse.ArgumentParser(description="SignalDraft application entrypoint")
    parser.add_argument(
        "command",
        nargs="?",
        default="app",
        choices=["app", "verify", "init-db", "migrate"],
        help="app (default): launch Streamlit UI",
    )
    args = parser.parse_args()

    if args.command == "verify":
        run_verify()
    elif args.command == "init-db":
        run_init_db()
    elif args.command == "migrate":
        run_migrate()
    else:
        run_streamlit()


if __name__ == "__main__":
    main()

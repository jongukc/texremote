import argparse
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="paperhere",
        description="Local and SSH Neovim LaTeX workflow with live browser preview",
    )
    sub = parser.add_subparsers(dest="command")

    # open (browser-based local or remote workflow)
    p_open = sub.add_parser("open", help="Open a local or SSH LaTeX project")
    p_open.add_argument("target", help="Project directory or server:path")
    p_open.add_argument("--tex", help="Main TeX file (auto-detected if omitted)")
    p_open.add_argument("--pdf", help="PDF file (defaults to the main TeX basename)")
    p_open.add_argument("--build-cmd", help="Build command; VimTeX/latexmk is used by default")
    p_open.add_argument("--nvim", help="Neovim executable (auto-detected, including remotely)")
    p_open.add_argument("--port", type=int, help="Local browser port (random if omitted)")
    p_open.add_argument("--browser", help="Browser to open (e.g. firefox)")
    p_open.add_argument("--no-auto-build", action="store_true", help="Do not build on startup")
    p_open.add_argument("--no-browser", action="store_true", help="Print the preview URL only")
    p_open.add_argument("--no-editor", action="store_true", help=argparse.SUPPRESS)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    if args.command == "open":
        from .launcher import run_open
        run_open(args)


if __name__ == "__main__":
    main()

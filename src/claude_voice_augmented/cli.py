import argparse


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cva", description="Narrate Claude Code sessions.")
    parser.parse_args(argv)
    return 0

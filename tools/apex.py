#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys

sys.dont_write_bytecode = True
from bootstrap import boot
from apexlib.common import Blocked


def main():
    parser = argparse.ArgumentParser(description="Apex isolated build and test tools")
    boot(parser)


if __name__ == "__main__":
    try:
        main()
    except (Blocked, subprocess.CalledProcessError, OSError, ValueError) as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        sys.exit(2)

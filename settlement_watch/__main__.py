from __future__ import annotations

import sys

from settlement_watch.cli import main
from settlement_watch.gui import run


def entry() -> None:
    if len(sys.argv) > 1:
        raise SystemExit(main())
    run()


if __name__ == "__main__":
    entry()

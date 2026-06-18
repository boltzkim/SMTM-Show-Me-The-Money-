import sys

sys.path.insert(0, "src")

from smtm.ui import main


if __name__ == "__main__":
    raise SystemExit(main(["--host", "127.0.0.1", "--port", "8765"]))


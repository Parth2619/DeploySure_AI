"""Run the deployment-risk pipeline on this folder:  python scripts/run_demo.py"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True  # keep swapped files from running out of an old .pyc

from app.main import run_pipeline  # noqa: E402

if __name__ == "__main__":
    sys.exit(run_pipeline(ROOT)["exit_code"])

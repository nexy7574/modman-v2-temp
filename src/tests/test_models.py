import json
import sys
from pathlib import Path

sys.path.extend([".", ".."])
DATA = Path(__file__).parent / "data"


def test_search_result():
    with open(DATA / "search_iris.json") as fd:
        data = json.load(fd)

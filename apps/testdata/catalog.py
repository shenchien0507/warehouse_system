"""測試資料產生用的選項清單（catalog.json），由 build_testdata_catalog 指令從範例訂單檔抽出來。"""

import json
from functools import cache
from pathlib import Path

CATALOG_PATH = Path(__file__).resolve().parent / "catalog.json"


@cache
def load_catalog():
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))

#!/usr/bin/env python3
from __future__ import annotations

import tempfile
from pathlib import Path

from openpyxl import Workbook

from bai_compact_timeline import episode_asset_reference_cards


HEADERS = [
    "资产类型",
    "资产中文原名",
    "资产本地化英文名",
    "资产简介",
    "原始中文解析描述",
    "角色状态中文参考描述",
    "角色状态本地化参考",
    "出现集号",
]


def main() -> int:
    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "assets.xlsx"
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(HEADERS)
        sheet.append(["人物", "甲-正装", "Arthur - Formal Suit", "", "深色正装", "", "", "EP01"])
        sheet.append(["场景", "甲宅卧室", "Arthur Manor Bedroom", "", "软包大床", "", "", "EP01, EP03"])
        sheet.append(["道具", "八十大寿蛋糕", "Eightieth Birthday Celebration Cake", "", "双层蛋糕", "", "", "EP01"])
        sheet.append(["道具", "第二集信件", "Episode Two Letter", "", "折叠信纸", "", "", "EP02"])
        workbook.save(path)

        cards = episode_asset_reference_cards(path, "01")
        assert len(cards) == 3
        assert any(card.startswith("- [人物] 甲-正装｜") for card in cards)
        assert any(card.startswith("- [场景] 甲宅卧室｜") for card in cards)
        assert any(card.startswith("- [道具] 八十大寿蛋糕｜") for card in cards)
        assert not any("第二集信件" in card for card in cards)

    print("episode asset injection: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

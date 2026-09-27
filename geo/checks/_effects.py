"""目錄和 builder 對不對得起來。

    python3 -m geo.checks._effects

**目錄有一格、而沒有人實作它**，症狀是那一種安靜地不畫 —— 分鏡表上
寫著有，成片裡沒有，兩邊都不報錯。反過來（有 builder 沒目錄）則是那一支
永遠不會被叫到。

這一支毫秒就跑完，接在 `make` 上，所以加一種特效忘了註冊會當場知道。
"""
from __future__ import annotations

import sys

from geo import effects
from geo.effects import builders as _builders          # noqa: F401  註冊用


def main() -> int:
    book = effects.catalogue()
    made = set(effects._MAKERS)
    can = {k for k, v in book.items() if v.get("renders")}
    wrong = 0

    missing = sorted(can - made)
    if missing:
        print(f"✗ 這幾種說畫得出來，卻沒有 builder：{'、'.join(missing)}")
        wrong += 1
    astray = sorted(made - set(book))
    if astray:
        print(f"✗ 這幾支 builder 在目錄裡沒有對應：{'、'.join(astray)}")
        wrong += 1
    idle = sorted(made & (set(book) - can))
    if idle:
        print(f"⚠ 這幾種有 builder 但目錄說畫不出來：{'、'.join(idle)}")

    # 每一格該有的欄位
    for kind, one in book.items():
        for key in ("名", "當", "layer", "renders"):
            if key not in one:
                print(f"✗ {kind} 少了 `{key}`"); wrong += 1
        if not one.get("renders") and not one.get("沒做"):
            print(f"✗ {kind} 說畫不出來，卻沒寫為什麼（`沒做`）"); wrong += 1
        for key, val in (one.get("要") or {}).items():
            if not (isinstance(val, list) and len(val) == 2):
                print(f"✗ {kind} 的 `要.{key}` 要寫成 [中文名, 說明]")
                wrong += 1

    print(f"\n目錄 {len(book)} 種，畫得出來 {len(can)} 種，builder {len(made)} 支")
    if wrong:
        print(f"{wrong} 個對不起來")
    else:
        print("對得起來 ✅")
    return 1 if wrong else 0


if __name__ == "__main__":
    sys.exit(main())

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

    # **同一個欄位名，在 check() 裡只有一種意思。** 「跑數字」的數到幾
    # 本來也叫 `to`，而 `to` 在 check() 裡是地名 —— 數字 3 被拿去 atlas
    # 查，TypeError。模型答完九分鐘才炸，而且只要挑了這一種就一定炸。
    # 所以拿一份合法的餵進去要過，一份地名錯的要擋。
    world = {"美國": {}, "格陵蘭": {}}
    for act, kind, ok in (
            ({"數到": 3, "單位": "份條約"}, "count_up", True),
            ({"從": "美國", "到": "月球"}, "draw_route", False)):
        try:
            effects.check(act, kind, world, "種的")
            passed = True
        except SystemExit:
            passed = False
        except Exception as bad:  # noqa: BLE001
            print(f"✗ {kind} 驗到一半就炸了（{type(bad).__name__}：{bad}）")
            wrong += 1
            continue
        if passed != ok:
            print(f"✗ {kind} 那一份{'該過卻被擋' if ok else '該擋卻放過'}：{act}")
            wrong += 1

    # **數字要停得住。** 「3 份條約」顯示 1.0 秒、數字要跑 1.2 秒，觀眾
    # 最後看到的是「2份條約」—— 每一道門都過，截圖才看到。所以拿一格
    # 放不下的（1.0 秒）餵給 builder，最後那個數字至少要停 `hold` 秒。
    box = book["count_up"]["params"]
    spec = {"start_s": 10.0, "duration_s": 1.0, "span_s": 1.0,
            "params": dict(box), "many": 3}
    got = {"cards": []}
    effects._MAKERS["count_up"](spec, book["count_up"],
                                {"atlas": {}, "whole": 99.0}, got)
    one = got["cards"][0]
    stays = one["end"] - one["start"] - one["count"]["seconds"]
    if stays < float(box.get("hold", 0.8)) - 1e-6:
        print(f"✗ 跑數字在 1.0 秒的格子裡，最後的數字只停 {stays:.2f} 秒"
              f"（要 {box.get('hold', 0.8)}）—— 觀眾讀不到")
        wrong += 1

    print(f"\n目錄 {len(book)} 種，畫得出來 {len(can)} 種，builder {len(made)} 支")
    if wrong:
        print(f"{wrong} 個對不起來")
    else:
        print("對得起來 ✅")
    return 1 if wrong else 0


if __name__ == "__main__":
    sys.exit(main())

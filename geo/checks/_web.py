"""網頁那幾件不會報錯的事。

    python3 -m geo.checks._web

## 一、開背景 job 的那幾支，畫面上要有人盯著

舊專案踩過：網頁打了一支會跑十二分鐘的 API，當場拿回 `undefined` 就印
「寫好了：undefined」，而真正的工作還在跑。**那不會報錯** ——
HTTP 回 200，JS 也沒例外，只是畫面在說謊。

這裡對 `server.py` 的 `STARTS_JOB` 和 JS 逐一比對：

```
STARTS_JOB 列的每一支      JS 裡要有 fetch，而且那個 fetch 要在 run() 裡
run()                     一定要接 watch()
watch()                   一定要問 /job/ 而且會再排一次（setTimeout）
```

## 二、鈕的樣式只准有一份

`skin.py` 有 `.btn`。其他地方再定義一次的話，兩份會分家，而分家的那一份
**只有打開那一頁的人看得到**。

## 三、不准把 CSS 寫進 HTML 的 style 屬性裡（除了排版微調）

顏色寫在 `style="color:#…"` 裡，`skin.py` 改主題的時候改不到它。
"""
from __future__ import annotations

import re
import sys

from geo.pipe import paths

WEB = paths.GEO / "pipe" / "server.py"
SKIN = paths.GEO / "pipe" / "skin.py"


def _text(where) -> str:
    return where.read_text(encoding="utf-8")


def job_watched() -> list[str]:
    """開 job 的每一支，畫面上有沒有人盯著。"""
    body = _text(WEB)
    bad = []

    got = re.search(r"STARTS_JOB\s*=\s*\(([^)]*)\)", body)
    if not got:
        return ["server.py 裡找不到 `STARTS_JOB` —— 那張表是這道門的輸入，"
                "沒有它等於沒有門"]
    routes = re.findall(r"[\"']([^\"']+)[\"']", got.group(1))
    if not routes:
        return ["`STARTS_JOB` 是空的。真的沒有背景 job 的話請寫一行註解說明"]

    js = re.search(r"^JS\s*=\s*\"\"\"(.*?)\"\"\"", body, re.S | re.M)
    if not js:
        return ["server.py 裡找不到 `JS`"]
    js = js.group(1)

    # run() 裡面 fetch 了哪幾支
    run = re.search(r"async function run\(.*?\n\}", js, re.S)
    if not run:
        bad.append("JS 裡沒有 `async function run(` —— "
                   "開 job 一定要走同一支，不然下一個會忘了接 watch()")
        run_body = ""
    else:
        run_body = run.group(0)
        if "watch(" not in run_body:
            bad.append("`run()` 沒有接 `watch()` —— "
                       "開了 job 卻沒有人盯著，畫面會停在一個假的完成")

    for one in routes:
        if f"'{one}'" not in run_body and f'"{one}"' not in run_body:
            bad.append(f"`STARTS_JOB` 列了 {one}，而 `run()` 裡沒有打它。"
                       f"別的地方打的話就不會經過 watch()")
        n = len(re.findall(re.escape(one), js))
        if n > 1:
            bad.append(f"{one} 在 JS 裡被打了 {n} 次 —— "
                       f"只准 `run()` 那一次，其他的繞過了盯著的人")

    watch = re.search(r"async function watch\(.*?\n\}", js, re.S)
    if not watch:
        bad.append("JS 裡沒有 `async function watch(`")
    else:
        body_ = watch.group(0)
        if "/job/" not in body_:
            bad.append("`watch()` 沒有問 `/job/` —— 它沒有在盯任何東西")
        # **查它有沒有再叫自己，不是查有沒有 setTimeout。**
        # 第一版查 `setTimeout`，而 `watch()` 結尾本來就有一個
        # `setTimeout(reload)` —— 把真正的輪詢整行刪掉，那道門不會叫。
        # 種違規試出來的：三道門種了四次，只有這一次沒叫。
        again = re.findall(r"watch\(", body_[body_.index("{"):])
        if not again:
            bad.append("`watch()` 沒有再叫自己 —— 問一次就不問了，"
                       "而跑十二分鐘的工作，問一次拿到的一定是「還在跑」")
    return bad


def one_button() -> list[str]:
    """鈕的樣式只准有一份。"""
    bad = []
    if ".btn{" not in _text(SKIN).replace(" ", ""):
        bad.append("skin.py 的 CSS 裡沒有 `.btn{` —— 共用的那一份不見了")
    for one in sorted((paths.GEO / "pipe").glob("*.py")):
        if one.name == "skin.py":
            continue
        body = _text(one).replace(" ", "")
        if ".btn{" in body:
            bad.append(f"{one.name} 自己定義了 `.btn` —— "
                       f"搬進 skin.py，兩份會分家")
    return bad


def no_inline_colour() -> list[str]:
    """顏色不准寫在 style 屬性裡。"""
    bad = []
    for one in sorted((paths.GEO / "pipe").glob("*.py")):
        if one.name in ("skin.py", "look.py", "watch.py"):
            # look/watch 產的是離線打開的單一檔案，沒有共用樣式表可以指。
            # **豁免要寫得出理由** —— 沒有理由的豁免跟把門關掉一樣。
            continue
        for at, row in enumerate(_text(one).splitlines(), 1):
            if re.search(r"style=['\"][^'\"]*(color|background)\s*:", row):
                bad.append(f"{one.name}:{at} 把顏色寫進 style 屬性 —— "
                           f"skin.py 換主題的時候改不到它")
    return bad


CHECKS = (("開 job 的有沒有人盯著", job_watched),
          ("鈕只有一份", one_button),
          ("顏色沒有寫死在 style 裡", no_inline_colour))


def main() -> int:
    bad = 0
    for name, fn in CHECKS:
        got = fn()
        bad += len(got)
        print(f"{'❌' if got else '✅'} {name}")
        for one in got:
            print(f"    {one}")
    print(f"\n{len(CHECKS)} 道都過" if not bad else f"\n{bad} 件要修")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

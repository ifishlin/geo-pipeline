"""文件裡的相對連結指到不存在的檔案，不會報錯。

    python3 -m geo.checks._links

**這一份文件寫得對不對沒有人檢查得了，但「它指的東西在不在」查得到。**

2026-09-27 抓到的第一批：那次搬 repo 的腳本把 21 個中文檔名弄壞，
`geo/refs/` 整個目錄消失 —— 而 `geo.check`、`_effects`、`_parts`、
`npm run validate` 全部通過，因為壞掉的那些**沒有一個是程式會讀的**。
是 README 裡一行「`geo/refs/` 三份 md」讓人去 `ls`，才發現的。

## 為什麼這個值得一道檢查

`CLAUDE.md` 說「一次性的搬遷不該變成門」。連結不一樣：**文件會一直被改，
所以連結會一直斷**，而斷掉的症狀是「有人點下去，什麼都沒有」——
沒有例外、沒有測試失敗。

## 已知會列出來的

`geo/refs/格陵蘭…規格.md` 有 11 張 `storyboards/*.jpg` 從來沒進過這個
repo（那份文件是從別處帶進來的）。那一份的開頭寫了這件事。
"""
from __future__ import annotations

import re
import sys

from geo.pipe import paths

LINK = re.compile(r"\[([^\]]*)\]\(([^)\s]+)\)")

# 已知指不到、而且不打算修的。**每一筆都要寫得出理由** ——
# 沒有理由的豁免，跟把門關掉一樣。
#
# 留著不刪那些連結，是因為文字的描述會用到它們（「第 3 格：船航行」）；
# 刪掉連結那句話就少一半。
KNOWN: dict[str, str] = {
    "storyboards/": "那份規格是從別處帶進來的，11 張分鏡圖從來沒進過這個"
                    "repo（2026-09-27 查過父 repo、這裡、桌面）",
}


def excused(link: str) -> str:
    for head, why in KNOWN.items():
        if link.startswith(head):
            return why
    return ""


def broken() -> list[tuple[str, str, str]]:
    """回 (哪一份文件, 連結的字, 指到哪)。指得到的不回。"""
    out = []
    for one in paths.docs():
        for text, link in LINK.findall(one.read_text(encoding="utf-8")):
            if link.startswith(("http://", "https://", "#", "mailto:")):
                continue
            # 錨點（`檔名.md#那一節`）只查檔名那一半 —— 節的名字查不了，
            # 而為了查不了的那一半整個不查，等於什麼都沒查。
            where = (one.parent / link.split("#")[0]).resolve()
            if not where.exists():
                out.append((str(one.relative_to(paths.ROOT)), text, link))
    return out


def main() -> int:
    bad = broken()
    total = sum(
        len([1 for _, link in LINK.findall(one.read_text(encoding="utf-8"))
             if not link.startswith(("http://", "https://", "#", "mailto:"))])
        for one in paths.docs())
    known = [one for one in bad if excused(one[2])]
    new = [one for one in bad if not excused(one[2])]

    # **分母一起寫。** 一個「0」看不出是都過了還是沒檢查。
    print(f"掃了 {total} 個相對連結，{total - len(bad)} 個指得到")
    for head, why in KNOWN.items():
        n = len([1 for one in known if one[2].startswith(head)])
        if n:
            print(f"　已知指不到 {n} 個（{head}*）：{why}")

    if not new:
        print("沒有新的斷掉 ✅")
        return 0
    # **會亂叫的警告等於沒有警告。** 已知那 11 個每次都列的話，
    # 第 12 個出現的時候沒有人會發現 —— 所以只印新的。
    for where, text, link in new:
        print(f"  ❌ {where}　[{text[:30]}]({link})")
    print(f"\n{len(new)} 個新斷掉的。"
          f"修不了的話寫進 `KNOWN`，**而且要寫得出理由**。")
    return 1


if __name__ == "__main__":
    sys.exit(main())

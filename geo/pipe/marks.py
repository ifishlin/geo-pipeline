"""台詞裡的就地標記：停頓和變速。

```
⏸0.3          停頓。插在任何位置，包括句子中間
⟪-10 第三次⟫   變速。包住要變速的那幾個字，不必整句
```

## 為什麼是就地標記，不是另開一欄

這個專案為「另開一欄，程式拿去找」修過一次 —— 封面的強調字本來是把要
變色的字另外列一欄，而程式去正文裡找：**找不到、找到兩次、跨行都不報錯**。
改成 `機場*沒有飛機*` 之後那三種錯一次消失，因為位置就在字裡面。

停頓和快慢是同一個形狀，而且更嚴重：它們要指的不是一整句，是
「這三個字」「這個逗號後面」。

## 為什麼 geo 一開始沒有

搬這一套的時候我只看得到程式在做什麼，看不到為什麼 —— 心得散在
`core/voice.py` 的註解、`docs/AUK.md`（一份講安裝的文件）和一則 commit
message 裡。現在收在 `docs/VOICE.md`。

沒有這兩個標記的時候，停頓只能放在**整行之間**（文案裡的 `停　0.8`），
句子中間一個工具都沒有 —— 而「唸起來斷斷續續」和「該停的地方不停」
都發生在句子中間。

## 值只能從清單挑

`rules.json` 的 `voice.pauses` / `voice.rates`。清單外的會被擋。

給清單而不是範圍，是量出來的：**範圍型的要求，模型會貼著極端寫。**
而清單的每一個值，事後都可以回頭比。
"""
from __future__ import annotations

import re

PAUSE = "⏸"
OPEN, CLOSE = "⟪", "⟫"

# ⏸0.3 或 ⏸0.1
_PAUSE_AT = re.compile(rf"{PAUSE}(\d+(?:\.\d+)?)")
# ⟪-10 第三次⟫ —— 數字、一個空白、要變速的字
_SPAN_AT = re.compile(rf"{OPEN}([-+]?\d+)\s+([^{OPEN}{CLOSE}]*?){CLOSE}")


def strip(said: str) -> str:
    """把標記拿掉，剩下真正會被唸出來的字（標點還在）。

    **每一個數字數都要走這一支。** 字數、句號數、長度估計如果照原字串算，
    `⏸0.3` 那三個字元會被當成台詞的一部分 —— 而它們一個字都不會唸出來。
    """
    said = _SPAN_AT.sub(lambda m: m.group(2), said)
    return _PAUSE_AT.sub("", said)


def held(said: str) -> float:
    """這一句裡的 `⏸` 加起來停幾秒。算長度的時候要加回去。"""
    return sum(float(x) for x in _PAUSE_AT.findall(said))


def to_ssml(said: str, esc) -> str:
    """把標記翻成 SSML。`esc` 是呼叫端的跳脫函式（`&` `<` `>`）。

    **跳脫要在翻譯之後、對著文字那幾段做**，不是先跳脫整句 —— 先跳脫的話
    `⟪` 裡面的內容沒事，但產生出來的 `<prosody>` 標籤會被自己跳脫掉。
    """
    out: list[str] = []
    at = 0
    for one in _SPAN_AT.finditer(said):
        out.append(_pauses(said[at:one.start()], esc))
        out.append(f'<prosody rate="{int(one.group(1)):+d}%">'
                   f"{_pauses(one.group(2), esc)}</prosody>")
        at = one.end()
    out.append(_pauses(said[at:], esc))
    return "".join(out)


def _pauses(text: str, esc) -> str:
    out: list[str] = []
    at = 0
    for one in _PAUSE_AT.finditer(text):
        out.append(esc(text[at:one.start()]))
        out.append(f'<break time="{int(round(float(one.group(1)) * 1000))}ms"/>')
        at = one.end()
    out.append(esc(text[at:]))
    return "".join(out)


def check(said: str, pauses: list[float], rates: list[int]) -> list[str]:
    """標記合不合規矩。回一串說得出口的問題。

    **清單外的值要擋。** 不擋的話 `⏸2.5` 會安靜地在片子中間開一個兩秒半
    的洞 —— 那是合法的 SSML，壓得出片，只有看的人知道不對。
    """
    bad: list[str] = []
    for one in _PAUSE_AT.findall(said):
        if float(one) not in pauses:
            bad.append(f"`{PAUSE}{one}` 不在可以用的停頓裡（"
                       + "、".join(str(x) for x in pauses) + "）")
    for size, _ in _SPAN_AT.findall(said):
        if int(size) not in rates:
            bad.append(f"`{OPEN}{size}` 不在可以用的語速裡（"
                       + "、".join(f"{x:+d}" for x in rates) + "）")
    # 落單的符號 —— 開了沒關，或者關了沒開。這種在成片裡會被唸出來。
    left = strip(said)
    for sign in (PAUSE, OPEN, CLOSE):
        if sign in left:
            bad.append(f"有一個 `{sign}` 沒有配成完整的標記：{left[:24]}")
    return bad

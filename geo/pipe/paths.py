"""一個題目的東西放在哪。**只有這一支答得出來。**

路徑自己拼是這個專案最會出事的一種 —— 主鍵、檔名、目錄形狀一改，每一個
讀取點都要重新確認，而它們不會報錯：檔案還在、清單還在、每道門都過，
只有人打開頁面才看得到。所以這裡集中一份，別處一律問它。

## 為什麼是一步一個檔

```
0-sources.json    抓回來的來源（網址、標題、全文的檔名）
1-facts.json      事實清單，每則帶 quote 和 entity
2-spine.json      骨幹：時間線的節點、轉在哪
3-script.tsv      台詞　誰⇥講什麼（`停` 也是一種「誰」）
4-voice/          配音：wav、逐字時間、送出去的 SSML
5-atlas.json      實體 → 地理（geoId、外框、算出來的相機）
6-storyboard.json 分鏡：哪一段看哪裡、哪個接縫是斷點
7-scene.json      隔壁吃的那份
8-film.mp4        成片
```

編號在檔名上，因為**一眼要看得出跑到哪一步**。少了第 5 個檔就是第 5 步沒跑，
不用去猜、不用去讀 log。而每一步只讀前面的、只寫自己那一個 —— 一步壞掉重跑
一步就好，不必整題重來（重收素材讓最貴的兩步付兩倍，那是付過的學費）。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent          # geo/pipe
GEO = HERE.parent                               # geo
ROOT = GEO.parent                               # Video_pipeline
STORIES = GEO / "stories"
PROMPTS = GEO / "prompts"

# 一步一個檔名。**加一步要加在這裡**，不要在別處硬寫字串。
STEPS: dict[str, str] = {
    "sources": "0-sources.json",
    "facts": "1-facts.json",
    "spine": "2-spine.json",
    "script": "3-script.tsv",
    "voice": "4-voice",
    "atlas": "5-atlas.json",
    "storyboard": "6-storyboard.json",
    "scene": "7-scene.json",
    "film": "8-film.mp4",
}

# 每一步要先有哪幾步的產物。跑之前對一次，缺了就說缺哪一個 ——
# **昂貴的步驟前面要先確認它的產物用得到**（算好 48 段切點、寫完文案，
# 三十分鐘後才在壓片那一刻 raise「還沒剪出檔案」，那是付過的學費）。
NEEDS: dict[str, tuple[str, ...]] = {
    "sources": (),
    "facts": ("sources",),
    "spine": ("facts",),
    "script": ("spine",),
    "voice": ("script",),
    "atlas": ("script",),
    "storyboard": ("voice", "atlas"),
    "scene": ("storyboard",),
    "film": ("scene",),
}


def home(story: str) -> Path:
    """這個題目的資料夾。"""
    return STORIES / story


def at(story: str, step: str) -> Path:
    """這個題目的第幾步產物在哪。"""
    if step not in STEPS:
        raise KeyError(f"沒有這一步：{step}。有的是 {'、'.join(STEPS)}")
    return home(story) / STEPS[step]


def done(story: str, step: str) -> bool:
    """這一步跑過了沒有。**目錄算跑過要看裡面有沒有東西** —— 空目錄是
    「開了但沒產出」，跟沒跑過一樣，而它在 `ls` 上看起來像跑過了。"""
    one = at(story, step)
    if one.is_dir():
        return any(one.iterdir())
    return one.is_file()


def missing(story: str, step: str) -> list[str]:
    """這一步缺哪幾個前置。"""
    return [one for one in NEEDS.get(step, ()) if not done(story, one)]


def insist(story: str, step: str) -> None:
    """前置沒齊就停，而且說得出缺哪一個。"""
    gap = missing(story, step)
    if gap:
        raise RuntimeError(
            f"「{step}」跑不了，缺 {'、'.join(gap)} —— "
            f"先跑 `python3 -m geo.pipe.make {story} {gap[0]}`")


def _when(story: str, step: str) -> float:
    """這一步的產物是什麼時候寫的。目錄取裡面最新的那一個。"""
    one = at(story, step)
    if one.is_dir():
        return max((x.stat().st_mtime for x in one.rglob("*") if x.is_file()),
                   default=0.0)
    return one.stat().st_mtime if one.is_file() else 0.0


def stale(story: str, step: str) -> list[str]:
    """哪幾個上游比這一步新 —— 也就是這一步的產物過期了。

    **這是這條路上最危險的一種錯。** 改了台詞重跑配音，而 storyboard、
    scene、成片全都還在 —— 每一個檔案都存在、每一道門都過、`make` 看到
    「跑過了」就跳過，於是成片裡是舊的畫面配新的聲音。而**畫面的錯不會
    報錯**：影片壓得出來，只有人看的時候才存在。

    比的是檔案時間，不是內容指紋。時間比較笨（碰一下檔案就算改過），
    但它抓得到「檔案被重寫了」這件事，而那正是要抓的。誤判的代價是
    多跑一次，漏判的代價是一支錯的片。
    """
    mine = _when(story, step)
    if not mine:
        return []
    out = []
    for one in NEEDS.get(step, ()):
        if _when(story, one) > mine:
            out.append(one)
    return out


def raw_stale(story: str, raw: Path, step: str,
              prompts: tuple[str, ...] = ()) -> bool:
    """模型那份答案是不是拿舊資料問出來的。

    問模型很貴（兩分鐘、一筆錢），所以每一步都把回答存成 `*.raw.json`
    沿用。但**沿用的前提是問題沒變** —— storyboard 的答案是照句子編號寫的
    （「第 12 句切到格陵蘭」），台詞一改，那些編號指的就是別的句子了，
    而程式照樣算得出秒數、照樣壓得出片。

    所以沿用之前對一次時間：上游比它新就重問。
    """
    if not raw.is_file():
        return True
    when = raw.stat().st_mtime
    if any(_when(story, one) > when for one in NEEDS.get(step, ())):
        return True
    # **改了 prompt，快取的答案也過期。**
    #
    # 這是後來才發現的：我在 `script.md` 加了一條「不要出現拉丁字母」，
    # 而上一次的答案是照舊規則寫的 —— 它照樣被沿用，然後在那道新的門
    # 前面被擋下來，而重跑幾次都一樣，因為問題在快取裡。
    #
    # 「規則改了、答案沒跟著改」跟「資料改了、答案沒跟著改」是同一件事。
    for one in prompts:
        md = PROMPTS / one
        if md.is_file() and md.stat().st_mtime > when:
            return True
    return False


def load(story: str, step: str) -> Any:
    one = at(story, step)
    if not one.is_file():
        raise FileNotFoundError(f"還沒有 {one}")
    return json.loads(one.read_text(encoding="utf-8"))


def save(story: str, step: str, body: Any) -> Path:
    """寫進去。**先寫暫存檔再 rename**，所以不會有寫到一半的產物。

    寫到一半的 JSON 讀起來是壞的，而這條路上每一步都讀前一步 —— 一次中斷
    會讓下游看到一個「存在但讀不出來」的檔案。這個形狀在題目檔和情境影片
    索引上各出過一次，兩次都是靜默的。
    """
    one = at(story, step)
    one.parent.mkdir(parents=True, exist_ok=True)
    said = body if isinstance(body, str) else json.dumps(
        body, ensure_ascii=False, indent=1)
    half = one.with_suffix(one.suffix + ".part")
    half.write_text(said, encoding="utf-8")
    half.replace(one)
    return one


def stories() -> list[str]:
    """有哪幾個題目 —— **數出來的**，不存一份清單。"""
    if not STORIES.is_dir():
        return []
    return sorted(one.name for one in STORIES.iterdir()
                  if one.is_dir() and not one.name.startswith("_"))


# 不算文件的目錄：別人的素材、跑出來的東西（`_ask/` 的 prompt 在
# /asks 那一頁看，不混進文件）。
NOT_DOCS = ("reference", ".git", "__pycache__", "stories", ".venv")


def docs() -> list[Path]:
    """repo 裡算文件的 md。**連結檢查和網頁的文件頁都問這一支** ——
    各列一份的話，一邊看得到的文件另一邊不檢查。"""
    return sorted(one for one in ROOT.rglob("*.md")
                  if not any(bit in one.relative_to(ROOT).parts
                             for bit in NOT_DOCS))

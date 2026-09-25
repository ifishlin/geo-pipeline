"""一個題目的設定：叫什麼、誰用哪個聲音、畫面長什麼樣。

    geo/stories/<題目>/story.json

**跟產物分開**。產物是一步一步長出來的（`0-sources.json` … `8-film.mp4`），
設定是人寫的，重跑不會把它蓋掉。混在一起的話，重跑第 3 步就會洗掉 cast。

金鑰一律從 `~/.config/video_pipeline/` 讀，跟現有的那條路同一個地方 ——
**絕不進版控，也絕不寫進故事檔**。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from geo.pipe import paths

KEYS = Path.home() / ".config" / "video_pipeline"
VOICES = paths.GEO / "data" / "voices.json"

# 沒寫就用這些。**一個題目不該為了跑起來被迫填十格**。
FALLBACK: dict[str, Any] = {
    "lang": "zh-TW",
    "rate_percent": 40,          # 整條旁白的語速，跟現有管線同一個值
    "sentence_gap_ms": 150,      # 句尾換氣；Azure 預設 630 太久
    "map_style": "clean",
    "video": {"width": 1080, "height": 1920, "fps": 30},
    # 版面：主體裝進畫面上面這幾成、算完再往上抬幾成。字幕在 0.715，
    # 所以下面那塊要讓開。兩個數字分開，因為它們可以不相等。
    "hold": 0.72,
    "lift": 0.06,
    "pad": 0.12,
}


def path_of(story: str) -> Path:
    return paths.home(story) / "story.json"


def load(story: str) -> dict[str, Any]:
    one = path_of(story)
    if not one.is_file():
        raise SystemExit(
            f"還沒有 {one}。一個題目至少要有 title 和 cast，"
            f"看 geo/README.md 的「開一個新題目」")
    got = json.loads(one.read_text(encoding="utf-8"))
    return {**FALLBACK, **got}


def voices() -> dict[str, dict[str, Any]]:
    got = json.loads(VOICES.read_text(encoding="utf-8"))["slots"]
    return {k: v for k, v in got.items() if not k.startswith("_")}


def cast_of(spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """角色 → 那個位子的完整設定。

    故事只寫「格陵蘭用 male-a」，音色名和 pitch 從 `geo/data/voices.json` 查。
    **故事裡不准直接寫音色名字** —— 寫了的話四支片就有四份，改一份其他三份
    不會跟著動，而不同步的那份不會報錯。
    """
    slots = voices()
    out: dict[str, dict[str, Any]] = {}
    for who, slot in (spec.get("cast") or {}).items():
        if not isinstance(slot, str):
            raise SystemExit(
                f"cast 的「{who}」要寫位子的名字（字串），不是 {slot!r}。"
                f"可以用的位子：{'、'.join(slots)}")
        if slot not in slots:
            raise SystemExit(
                f"cast 的「{who}」指向 {slot}，而 voices.json 沒有這個位子。"
                f"有的是：{'、'.join(slots)}")
        out[who] = dict(slots[slot], slot=slot)
    if not out:
        raise SystemExit("cast 是空的 —— 至少要有一個旁白")
    doubled = [s for s in {v["slot"] for v in out.values()}
               if sum(1 for v in out.values() if v["slot"] == s) > 1]
    if doubled:
        # 兩個角色共用一個位子＝兩個角色同一個聲音。擋在這裡而不是等到
        # 量基頻那一步 —— 這一個不用合成就知道。
        who = {s: [k for k, v in out.items() if v["slot"] == s]
               for s in doubled}
        raise SystemExit("兩個角色共用同一個聲音："
                         + "、".join(f"{s}（{'、'.join(n)}）"
                                     for s, n in who.items()))
    return out


def azure_key() -> str:
    """Azure 的金鑰。環境變數優先，再來是設定目錄。"""
    got = os.environ.get("AZURE_SPEECH_KEY", "").strip()
    if got:
        return got
    one = KEYS / "azure"
    if not one.is_file():
        raise SystemExit(f"找不到 {one}，也沒有 AZURE_SPEECH_KEY")
    return one.read_text(encoding="utf-8").strip()


def azure_region() -> str:
    """區域。現有管線存在 `~/.config/video_pipeline/config.toml`，讀同一份。

    **要抓引號裡的那一段，不是等號後面的全部** —— 那一行後面跟著註解
    （`region = "germanywestcentral"   # 金鑰綁區域…`），照 `split("=")` 取
    會把註解一起送出去，而 Azure 的錯誤訊息是「連不上遠端主機」，看起來
    像網路問題。查了才知道是自己送了一個帶註解的區域名。
    """
    import re
    got = os.environ.get("AZURE_SPEECH_REGION", "").strip()
    if got:
        return got
    one = KEYS / "config.toml"
    if one.is_file():
        for row in one.read_text(encoding="utf-8").splitlines():
            if row.strip().startswith("region"):
                hit = re.search(r'["\']([^"\']+)["\']', row)
                if hit:
                    return hit.group(1)
    raise SystemExit(
        f"找不到 Azure 的區域 —— {KEYS / 'config.toml'} 裡沒有 region，"
        f"也沒有 AZURE_SPEECH_REGION。猜一個的話會連不上，而錯誤訊息"
        f"看起來像網路問題")

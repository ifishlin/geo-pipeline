"""借隔壁壓成影片，聲音在這邊接上去。

    python3 -m geo.pipe.make <題目> film [--draft]

## 界線

```
這邊    寫 scene.json、接聲音、量成品
隔壁    只做一件事：把 scene.json 畫成無聲的 mp4
```

**我們的檔案一個都不放進隔壁的 repo。** 它的 `render.ts` 吃絕對路徑、輸出
也吃絕對路徑，所以只是借它跑一趟。它唯一會寫的是自己的 `out/.props.json`
（它自己的暫存），那是它本來就在做的事。

聲音不交給它，是因為它的 `audio.src` 相對於它的 `public/` —— 照做就得把
wav 搬進去。用 ffmpeg 接的另一個好處是響度歸我們管。

## 先驗再壓

`npm run validate` 一秒鐘，壓片十二分鐘。**昂貴的步驟前面要先確認產物用得到**
—— 這條規則在隔壁專案付過一次學費，在這邊也一樣。

## 壓完要量

回 0 不代表畫面對。所以最後量三件事：**長度對不對、有沒有聲音、聲音多大**。
影音長度差超過 `DRIFT` 就 raise —— 那通常是某一格的 duration 被四捨五入
吃掉，而畫面上只是「結尾少了半句話」。
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from geo.pipe import paths, story as story_module

MAPS = paths.ROOT.parent / "Map_Animation"

# 影音長度差超過這麼多秒就是有問題。一幀是 0.033 秒，留三幀的餘裕。
DRIFT = 0.10

# 成片的響度目標，跟現有管線同一個值（`assets/rules.json` 的 sound.mix_*）。
# **抄數字不好，但這兩個是平台標準**，而且那邊是量了十支對照片訂出來的。
LOUD, PEAK = -14, -1.5


def _run(args: list[str], say, where: Path | None = None) -> None:
    got = subprocess.run(args, cwd=str(where) if where else None)
    if got.returncode != 0:
        raise SystemExit(f"跑失敗（exit {got.returncode}）：{' '.join(args[:4])}…")


def seconds_of(one: Path) -> float:
    got = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(one)], capture_output=True, text=True)
    return float(got.stdout.strip() or 0)


def loudness_of(one: Path) -> float | None:
    """整支片的響度（LUFS）。量不到回 None。

    **`-v error` 會把摘要一起吃掉** —— ebur128 的「Integrated loudness」
    印在 info 等級。第一版照習慣加了 `-v error`，於是量到的永遠是 None，
    而那道門就一直在叫「loudnorm 可能沒生效」，其實生效得好好的
    （−14.6 LUFS，正中目標）。**量錯地方的門會叫人去修沒有壞的東西。**
    """
    got = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(one),
         "-af", "ebur128=framelog=quiet", "-f", "null", "-"],
        capture_output=True, text=True)
    rows = got.stderr.splitlines()
    for at, row in enumerate(rows):
        if "Integrated loudness" in row:
            for other in rows[at:at + 4]:
                if "I:" in other and "LUFS" in other:
                    try:
                        return float(other.split("I:")[1]
                                     .split("LUFS")[0].strip())
                    except ValueError:
                        return None
    return None


def check(where, say=print) -> None:
    """讓隔壁驗一次 schema。**一秒鐘，而錯過的話是壓十二分鐘才炸。**

    抽成一支是因為兩個地方要用：寫檔的那一步（`scene`）和壓片的那一步。
    各寫一次的話會有一邊漏掉，而漏掉的那一邊不會報錯 —— 它只是沒驗。
    """
    _run(["npx", "tsx", "scripts/validate.ts", str(where.resolve())],
         say, MAPS)


def run(story: str, say=print, draft: bool = False) -> dict[str, Any]:
    paths.insist(story, "film")
    if not MAPS.is_dir():
        raise SystemExit(
            f"找不到渲染器 {MAPS}。這條路只借它畫圖，其他都在這邊；"
            f"它搬走了就改 render.py 的 MAPS 那一格")
    if not shutil.which("ffmpeg"):
        raise SystemExit("沒有 ffmpeg，接不了聲音")

    spec = story_module.load(story)
    where = paths.at(story, "scene")
    wav = paths.at(story, "voice") / "said.wav"
    silent = paths.home(story) / "8-film.silent.mp4"
    film = paths.at(story, "film")

    say("一、先驗（一秒鐘，比壓完才發現便宜十二分鐘）")
    check(where, say)

    say(f"\n二、壓成無聲影片{'（草稿畫質）' if draft else ''}")
    args = ["npm", "run", "render", "--", str(where.resolve()),
            str(silent.resolve())]
    if draft:
        args.append("--scale=0.4")
    _run(args, say, MAPS)

    say("\n三、接聲音")
    # 影片 copy、聲音轉 aac。`-shortest` 不加 —— 長度不一樣要**被看見**，
    # 不是被靜靜切掉。
    _run(["ffmpeg", "-v", "error", "-y", "-i", str(silent), "-i", str(wav),
          "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
          "-af", f"loudnorm=I={LOUD}:TP={PEAK}:LRA=11",
          "-map", "0:v:0", "-map", "1:a:0", str(film)], say)

    say("\n四、量成品")
    vision, sound = seconds_of(silent), seconds_of(wav)
    whole = seconds_of(film)
    heard = loudness_of(film)
    say(f"  影片 {vision:.2f}s　聲音 {sound:.2f}s　成片 {whole:.2f}s")
    say(f"  響度 {heard:.1f} LUFS（目標 {LOUD}）" if heard is not None
        else "  ⚠ 量不到響度")
    if abs(vision - sound) > DRIFT:
        raise SystemExit(
            f"影片 {vision:.2f}s 跟聲音 {sound:.2f}s 差 "
            f"{abs(vision - sound):.2f}s（容許 {DRIFT}）—— "
            f"通常是某一格的 duration 被四捨五入吃掉，而畫面上只是"
            f"「結尾少了半句話」")
    if heard is None or heard < LOUD - 3 or heard > LOUD + 2:
        raise SystemExit(f"響度 {heard} 離目標 {LOUD} 太遠 —— "
                         f"loudnorm 可能沒生效")
    silent.unlink(missing_ok=True)
    say(f"\n{film.relative_to(paths.ROOT)}　{whole:.1f} 秒"
        f"　{film.stat().st_size / 1048576:.1f} MB")
    return {"file": str(film), "seconds": whole, "loudness": heard}


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "", draft="--draft" in sys.argv)

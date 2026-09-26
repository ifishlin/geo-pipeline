"""一個題目從頭跑到尾。

    python3 -m geo.pipe.make <題目>              跑到還沒跑的那一步為止
    python3 -m geo.pipe.make <題目> <步驟>       只跑那一步
    python3 -m geo.pipe.make <題目> <步驟> --again  那一步重來
    python3 -m geo.pipe.make                    列出有哪些題目、各跑到哪

**照 `paths.STEPS` 那張表跑，不是照我手寫的順序。** 手寫的那種在這個專案
出過事：照清單跑的旁邊手寫兩道，漏了第三道。加一步只要改那張表。

## 為什麼預設是「跑到還沒跑的那一步」

這條路上最貴的兩步是問模型（`storyboard`，兩分鐘）和壓片（十二分鐘）。
重跑整題等於那兩步再付一次錢，而多數時候要重跑的只有一步。所以預設**跳過
已經有產物的**，要重來的那一步自己指名。
"""
from __future__ import annotations

import sys
import time
from typing import Any, Callable

from geo.pipe import paths


def _step(name: str) -> Callable[..., Any]:
    """哪一步由誰做。**延後 import** —— 每一步的相依不一樣（配音要 Azure
    的 SDK、壓片要 ffmpeg），一開始全部載進來的話，只想跑 atlas 的人會被
    一個裝不起來的套件擋住。"""
    if name == "sources":
        from geo.pipe import sources
        return sources.run
    if name == "facts":
        from geo.pipe import facts
        return facts.run
    if name == "spine":
        from geo.pipe import spine
        return spine.run
    if name == "script":
        from geo.pipe import script
        return script.run
    if name == "voice":
        from geo.pipe import voice
        return voice.run
    if name == "atlas":
        from geo.pipe import atlas
        return atlas.run
    if name == "storyboard":
        from geo.pipe import storyboard
        return storyboard.run
    if name == "scene":
        from geo.pipe import scene
        return scene.run
    if name == "film":
        from geo.pipe import render
        return render.run
    raise SystemExit(f"沒有這一步：{name}")


def status(story: str) -> str:
    return "".join("●" if paths.done(story, one) else "○" for one in paths.STEPS)


def listing() -> None:
    names = paths.stories()
    if not names:
        print("還沒有題目。開一個：geo/stories/<名字>/story.json")
        return
    print("　".join(f"{one[:2]}" for one in paths.STEPS), "　（●跑過 ○還沒）")
    for one in names:
        print(f"  {status(one)}　{one}")


def run(story: str, only: str = "", again: bool = False,
        draft: bool = False, plain: bool = False) -> None:
    if story not in paths.stories():
        raise SystemExit(f"沒有這個題目：{story}。"
                         f"有的是：{'、'.join(paths.stories()) or '（一個都沒有）'}")
    steps = [only] if only else list(paths.STEPS)
    for name in steps:
        if not only and paths.done(story, name):
            # **跑過了不代表還算數。** 上游重寫過的話，這一步的產物是拿
            # 舊資料做的 —— 檔案在、門會過、`make` 會跳過它，而成片裡就是
            # 舊的畫面配新的聲音。所以過期的照跑，而且說一聲為什麼。
            old = paths.stale(story, name)
            if not old:
                continue
            print(f"\n（{name} 過期了：{'、'.join(old)} 比它新，重跑）")
        gap = paths.missing(story, name)
        if gap:
            if only:
                raise SystemExit(f"「{name}」跑不了，缺 {'、'.join(gap)}")
            print(f"\n停在「{name}」—— 缺 {'、'.join(gap)}")
            return
        print(f"\n{'─' * 8} {name} {'─' * 8}")
        began = time.time()
        call = _step(name)
        # 哪一步吃哪個旗標。**問模型的那幾步都吃 `--again`** —— 第一版
        # 只列了 storyboard，於是 `make … script --again` 安靜地沿用舊答案，
        # 而畫面上只是「怎麼跑一次還是一樣」。一個收進來卻沒被用的參數，
        # 跟沒有那個功能一樣。
        kinds: dict[str, dict[str, Any]] = {"film": {"draft": draft}}
        for one in ("facts", "spine", "script", "storyboard"):
            kinds[one] = {"again": again}
        # `--plain` 只給寫台詞那一步：停在旁白稿，不配角色。
        # 想先確認「故事本身站不站得住」的時候用。
        kinds["script"] = {"again": again, "plain": plain}
        call(story, **kinds.get(name, {}))
        print(f"（{time.time() - began:.0f} 秒）")
    print(f"\n{status(story)}　{story}")


if __name__ == "__main__":
    args = [one for one in sys.argv[1:] if not one.startswith("--")]
    if not args:
        listing()
    else:
        run(args[0], args[1] if len(args) > 1 else "",
            again="--again" in sys.argv, draft="--draft" in sys.argv,
            plain="--plain" in sys.argv)

"""問模型。**薄薄一層，只做三件事：送出去、存下來、把 JSON 挖出來。**

送出去的每一份 prompt 和收回來的每一份原文都落地（`_ask/` 底下），因為
「模型為什麼這樣答」只有那兩份答得出來，而**留在記憶體裡的東西等於沒有**。

## 為什麼不接現有那支

`core/asking.py` 做的事多得多（同一個 session、計費、四種供應商）。這條路
是新的一套，接過去就變成「改那邊會弄壞這邊」，而這正是被交代不要發生的事。
需要它的功能再抄，不要先接。
"""
from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from geo.pipe import paths

MODEL = "claude-opus-5"
WAIT = 2400

# 允許多長的回答。**預設 32000 不夠** —— 寫 41 句台詞那一趟撞上上限，
# 跑了 21 分鐘之後回一行 `API Error: … exceeded the 32000 output token
# maximum`，整趟白費。模型在交出 JSON 之前會想很久，那些也算在裡面。
OUTPUT_MOST = "64000"


def send(story: str, task: str, prompt: str, say=print) -> str:
    """問一次，回原文。兩份都存。"""
    into = paths.home(story) / "_ask"
    into.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%m%d-%H%M%S")
    (into / f"{task}-{stamp}.prompt.md").write_text(prompt, encoding="utf-8")
    say(f"問模型（{task}，{len(prompt)} 字）…")
    began = time.time()
    import os
    got = subprocess.run(
        ["claude", "-p", "--model", MODEL, "--output-format", "text"],
        input=prompt, capture_output=True, text=True, timeout=WAIT,
        env={**os.environ, "CLAUDE_CODE_MAX_OUTPUT_TOKENS": OUTPUT_MOST})
    took = time.time() - began
    said = got.stdout or ""
    (into / f"{task}-{stamp}.said.md").write_text(said, encoding="utf-8")
    # **把真正的訊息印出來。** 第一版看到 exit≠0 就報「模型沒有回答」，
    # 而回答其實在 stdout 裡躺著 —— 那一行是
    # `API Error: Claude's response exceeded the 32000 output token maximum`。
    # 21 分鐘之後拿到一句沒有資訊的錯誤，真正的原因在檔案裡沒有人看。
    if got.returncode != 0 or not said.strip():
        raise SystemExit(
            f"模型那一趟失敗了（exit {got.returncode}，{took:.0f}s）\n"
            + (f"  它說：{said.strip()[:400]}\n" if said.strip() else "")
            + (f"  stderr：{got.stderr.strip()[:300]}\n"
               if got.stderr.strip() else "")
            + f"  送出去的和收回來的都存著：{into.name}/")
    if said.lstrip().startswith("API Error"):
        raise SystemExit(f"模型回了一句錯誤訊息（{took:.0f}s）：\n"
                         f"  {said.strip()[:400]}")
    say(f"  回來了　{took:.0f}s　{len(said)} 字")
    return said


def as_json(said: str) -> Any:
    """從回答裡把 JSON 挖出來。

    **不要整份 `json.loads`** —— 模型常常在前後加一句話，或包在 ```json 裡。
    先找圍欄，沒有就找第一個 `{` 到最後一個 `}`。兩個都失敗就 raise，
    **不要回一個空的** ——「解析不出來」和「它說沒有」在下游長得一模一樣，
    而後者才是真的。
    """
    hit = re.search(r"```(?:json)?\s*\n(.+?)\n```", said, re.S)
    body = hit.group(1) if hit else said
    if not hit:
        start, end = body.find("{"), body.rfind("}")
        if start < 0 or end <= start:
            raise SystemExit(f"回答裡找不到 JSON：{said[:200]}…")
        body = body[start:end + 1]
    try:
        return json.loads(body)
    except json.JSONDecodeError as bad:
        raise SystemExit(f"JSON 讀不出來（{bad}）：{body[:300]}…") from None


def prompt_of(name: str, **fill: Any) -> str:
    """讀一份 prompt，把 `{名字}` 換掉。

    **缺一格就 raise。** 少填一格的話那句話會變成「畫面要看到 {see}」，
    而模型會照著那個字面去想 —— 它不會說「你少給我一個東西」。
    """
    one = paths.PROMPTS / name
    if not one.is_file():
        raise SystemExit(f"沒有這份 prompt：{one}")
    text = one.read_text(encoding="utf-8")
    # **掃樣板，不是掃填完的結果。** 第一版掃填完的全文，而塞進去的維基
    # 原文裡本來就有 `{parabr}` 這種字 —— 門當場叫「還有沒填的格子」，
    # 而那一格根本不存在。**誤報的門會叫人去修沒有壞的東西。**
    slots = set(re.findall(r"\{([a-z_]+)\}", text))
    left = slots - set(fill)
    if left:
        raise SystemExit(f"{name} 還有沒填的格子：{'、'.join(sorted(left))}")
    spare = set(fill) - slots
    if spare:
        # 給了樣板不要的東西，通常是改了樣板忘了改呼叫端。不擋，但要說。
        print(f"⚠ {name} 用不到這幾個：{'、'.join(sorted(spare))}")
    for key, value in fill.items():
        text = text.replace("{" + key + "}", str(value))
    return text

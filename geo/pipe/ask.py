"""問模型。**薄薄一層，只做三件事：送出去、存下來、把 JSON 挖出來。**

送出去的每一份 prompt 和收回來的每一份原文都落地（`_ask/` 底下），因為
「模型為什麼這樣答」只有那兩份答得出來，而**留在記憶體裡的東西等於沒有**。

## 為什麼不接現有那支

`core/asking.py` 做的事多得多（同一個 session、計費、四種供應商）。這條路
是新的一套，接過去就變成「改那邊會弄壞這邊」，而這正是被交代不要發生的事。
需要它的功能再抄，不要先接。
"""
from __future__ import annotations

import codecs
import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from geo.pipe import paths

MODEL = "claude-opus-5"

# **不給工具、而且把 repo 移出視野。**
#
# 這是舊那條路（`core/asking.py`）做對、我一開始漏掉的事。量出來的後果：
# 36 次呼叫裡有 8 次用了工具（Bash 58、Write 3、Read 3）。絕大多數是它在
# /tmp 寫小程式數自己的字數（為了過字數那道門），那還好；但其中三次
# **讀了 `geo/pipe/script.py`** —— 也就是放門的那支程式。
#
# 問題不是「作弊」，是**我不知道它看了什麼**：我一直在「改 prompt → 看結果
# → 再改」，而那個迴圈的前提是「輸入只有我送的那一份」。前提不成立的話，
# 寫得好我分不出是 prompt 的功勞還是它自己翻到的。
#
# cwd 設成 /tmp 還有第二個作用：CLI 的 transcript 是照工作目錄分資料夾的，
# 不設的話每一次呼叫都在這個專案底下留一個 session（一天 36 個）。
NO_TOOLS = ""
AWAY = "/tmp"
WAIT = 2400

# 允許多長的回答。**預設 32000 不夠** —— 寫 41 句台詞那一趟撞上上限，
# 跑了 21 分鐘之後回一行 `API Error: … exceeded the 32000 output token
# maximum`，整趟白費。模型在交出 JSON 之前會想很久，那些也算在裡面。
OUTPUT_MOST = "64000"


# 多久報一次「收到幾個字了」。
#
# **四十分鐘全黑是這條路最貴的一種失敗。** 一趟逾時砍掉之後，回答還在
# pipe 裡，什麼都沒留下 —— 而「它在慢慢吐字」和「它從第一秒就卡死」
# 長得一模一樣，那正是最需要分辨的兩件事。
BEAT = 60

# **寫一份文案的那幾趟接同一個 CLI session。**
#
# 舊那條路（`core/asking.py`）早就這樣做，而且量過（2026-09-12）：
#
#     shots 那一步   獨立  5 次成功 3 次，輸出平均 78,822 token
#                   共用  4 次全成功，輸出平均 47,404 token
#     每秒吐字       67.9 vs 68.8 —— 一樣快
#
# **省的不是速度，是模型要寫的量。** 前幾趟的結論還在對話裡，它不用把
# 「這支片在講什麼、每一句是什麼角色」在答案裡重新推導一遍再動筆。
#
# 代價是輸入一路累積，而長輸入本身會讓模型變鈍 —— 那正是當初把一次寫完
# 拆成四步的理由。所以留成開關。
SHARE = True

# 一份文案的邊界：**這一趟開新的，後面那幾趟接上去。**
# 少了這個邊界，下一個題目會接到上一個的尾巴，而那沒有任何跡象。
OPENS = "spine"

# 接哪一個。存進題目資料夾，因為 spine 和 script 跑在**不同的行程**裡，
# 放記憶體的話 script 起來就什麼都接不到了。
def _session_at(story: str) -> Path:
    return paths.home(story) / "_ask" / "session.json"


def _session_of(story: str, task: str) -> str:
    """這一趟要接誰。開新的就回空字串。"""
    if not SHARE or task == OPENS:
        return ""
    one = _session_at(story)
    if not one.is_file():
        return ""
    try:
        return str(json.loads(one.read_text(encoding="utf-8")).get("id") or "")
    except json.JSONDecodeError:
        return ""


def _remember(story: str, task: str, sid: str) -> None:
    if not (SHARE and sid):
        return
    _session_at(story).write_text(
        json.dumps({"id": sid, "opened_by": task,
                    "when": time.strftime("%F %T")},
                   ensure_ascii=False, indent=1), encoding="utf-8")


def spent(story: str) -> list[dict[str, Any]]:
    """這個題目問過幾趟、各花了多少。一趟一行，存在 `_ask/spend.jsonl`。"""
    one = paths.home(story) / "_ask" / "spend.jsonl"
    if not one.is_file():
        return []
    out = []
    for row in one.read_text(encoding="utf-8").splitlines():
        if row.strip():
            try:
                out.append(json.loads(row))
            except json.JSONDecodeError:
                continue
    return out


def send(story: str, task: str, prompt: str, say=print) -> str:
    """問一次，回原文。兩份都存，而且**回答是邊收邊寫的**。"""
    into = paths.home(story) / "_ask"
    into.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%m%d-%H%M%S")
    (into / f"{task}-{stamp}.prompt.md").write_text(prompt, encoding="utf-8")
    said_at = into / f"{task}-{stamp}.said.md"
    carry = _session_of(story, task)
    say(f"問模型（{task}，{len(prompt)} 字"
        + (f"，接 {carry[:8]}…" if carry else "，開新的") + "）…")
    began = time.time()
    import os
    import threading

    how = subprocess.Popen(
        ["claude", "-p", "--model", MODEL, "--output-format", "json",
         "--allowedTools", NO_TOOLS]
        + (["--resume", carry] if carry else []),
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, cwd=AWAY,
        env={**os.environ, "CLAUDE_CODE_MAX_OUTPUT_TOKENS": OUTPUT_MOST})

    # 收的那一條線自己跑，主線才能一邊計時一邊報進度。
    bits: list[str] = []
    errs: list[str] = []

    def _drain(pipe, into_: list[str], sink=None) -> None:
        """**有多少讀多少。**

        不要用 `pipe.read(n)` —— 它會等湊滿 n 個字才回來，於是慢慢吐字
        的那四十分鐘照樣是黑的，而那正是這整段程式要解決的事。
        `os.read` 有一個 byte 就回一個。

        中文一個字三個 byte，可能切在字中間，所以用 incremental decoder
        接著上一塊解 —— 直接 `decode()` 會在邊界炸掉。
        """
        eat = codecs.getincrementaldecoder("utf-8")("replace")
        while True:
            raw = os.read(pipe.fileno(), 65536)
            if not raw:
                break
            piece = eat.decode(raw)
            if not piece:
                continue
            into_.append(piece)
            if sink is not None:
                sink.write(piece)
                sink.flush()
        pipe.close()

    with said_at.open("w", encoding="utf-8") as sink:
        ear = threading.Thread(target=_drain, args=(how.stdout, bits, sink),
                               daemon=True)
        eye = threading.Thread(target=_drain, args=(how.stderr, errs),
                               daemon=True)
        ear.start()
        eye.start()
        try:
            how.stdin.write(prompt.encode('utf-8'))
            how.stdin.close()
        except BrokenPipeError:
            pass
        killed = False
        while True:
            try:
                how.wait(timeout=BEAT)
                break
            except subprocess.TimeoutExpired:
                waited = time.time() - began
                if waited > WAIT:
                    how.kill()
                    how.wait()
                    killed = True
                    break
                say(f"　…{waited / 60:.0f} 分　收到 "
                    f"{sum(len(x) for x in bits)} 字")
        ear.join(timeout=5)
        eye.join(timeout=5)

    took = time.time() - began
    said = "".join(bits)
    if killed:
        # **逾時不是零產出。** 收到多少就留多少，下一個人才看得出它是
        # 在慢慢寫、還是從頭到尾一個字都沒吐。
        raise SystemExit(
            f"等了 {took / 60:.0f} 分鐘還沒講完（上限 {WAIT / 60:.0f} 分）"
            f"，砍掉了。\n"
            f"  這段時間它吐了 {len(said)} 個字"
            + ("（一個字都沒有 —— 這比較像卡住，不像在想）"
               if not said else f"，存著：{said_at.name}")
            + (f"\n  它最後寫到：…{said[-120:]}" if said else ""))
    # —— 拆信封 ——
    # `--output-format json` 回的是一層外殼：`result` 是模型講的話，
    # 外面還掛著 session_id 和 usage。**換成 json 就是為了那兩樣** ——
    # 沒有 session_id 接不了下一趟，沒有 usage 講不出「省了多少」。
    envelope: dict[str, Any] = {}
    if said.lstrip().startswith("{"):
        try:
            envelope = json.loads(said)
        except json.JSONDecodeError:
            envelope = {}
    if envelope:
        text = str(envelope.get("result") or "")
        # **把外殼換成內容再存一次。** 下游（`as_json`、過程頁）要的是
        # 模型講的話；外殼留在 `.meta.json`，兩邊都看得到，而且不必去猜
        # 檔案裡躺的是哪一種。
        if text:
            said_at.write_text(text, encoding="utf-8")
        (into / f"{task}-{stamp}.meta.json").write_text(
            json.dumps({k: v for k, v in envelope.items() if k != "result"},
                       ensure_ascii=False, indent=1), encoding="utf-8")
        # **每一趟都把回來的 id 記下來**，不是只記開頭那一趟的。`--resume`
        # 有可能回一個新的 id，只記第一個的話第三趟就接到第一趟、把第二趟
        # 的內容丟了 —— 而那不會報錯，只會安靜地少記得一段。
        sid = str(envelope.get("session_id") or "")
        if sid:
            _remember(story, task, sid)
        use = envelope.get("usage") or {}
        row = {"when": time.strftime("%F %T"), "task": task,
               "took": round(took), "carried": bool(carry),
               "in": use.get("input_tokens"),
               "cached": use.get("cache_read_input_tokens"),
               "wrote_cache": use.get("cache_creation_input_tokens"),
               "out": use.get("output_tokens"),
               "usd": envelope.get("total_cost_usd"),
               "said": len(text)}
        with (into / "spend.jsonl").open("a", encoding="utf-8") as book:
            book.write(json.dumps(row, ensure_ascii=False) + "\n")
        say(f"　{use.get('output_tokens', '?')} token 出　"
            f"{use.get('cache_read_input_tokens', 0)} 命中快取　"
            f"${envelope.get('total_cost_usd', 0):.2f}")
        if envelope.get("is_error"):
            raise SystemExit(f"模型那一趟出錯了（{took:.0f}s）：{text[:300]}")
        said = text
    # **接不上就自己開一個，不要整趟死掉。** session 是綁在工作目錄上的，
    # 換過 cwd、清過暫存、隔太久都會接不到；而那時候該做的是重問一次，
    # 不是讓一份跑到一半的文案停在這裡。舊路的 `asking.alone()` 同一件事。
    if carry and how.returncode != 0 and "No conversation found" in (
            "".join(errs) + said):
        say("　接不上那個 session（可能被清掉了），自己開一個重問…")
        _session_at(story).unlink(missing_ok=True)
        return send(story, task, prompt, say)
    got = subprocess.CompletedProcess(
        how.args, how.returncode, said, "".join(errs))
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

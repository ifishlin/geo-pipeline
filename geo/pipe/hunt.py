"""給一句題目，自己去找出該讀的來源。

    python3 -m geo.pipe.hunt <題目>            繞圈找，寫進 story.json
    python3 -m geo.pipe.hunt <題目> --dry      找，但不寫進 story.json
    python3 -m geo.pipe.hunt <題目> --again    丟掉上一次的狀態重來

## 為什麼是迴圈，不是問一次

問一次的話，模型只能憑記憶列清單 —— 而它的記憶有截止日，這個月發生的事
它沒聽過。

人工做那一次（2026-09-22 那支片）實際是這樣走的：

```
輪1  搜題目            → 看到一則報導
輪2  讀報導            → 冒出「自治」「主權」，才知道要查身分
輪3  讀自治的條目      → 冒出「外交國防留在誰手上」，這變成整支片的問題
輪4  讀一篇分析        → 它說「大部分只是把更早那一份重講一次」
輪5  照著那句去搜      → 找到前傳。**那才是結尾**
```

**輪 5 那個是整支片的靈魂，而輪 1 的人完全不知道它存在。** 沒有輪 4 就
不會有輪 5 —— 讀到的東西決定下一個要讀什麼，這才是「聰明」的來源。

## 誰做什麼

```
模型   自己搜、自己讀、說出還缺什麼        （這一步是唯一給它工具的）
程式   管迴圈、管狀態、驗網址、算還缺多少、決定什麼時候停
```

**停不停由程式說。** 問模型「夠了嗎」它永遠會說夠了 —— 它的 `enough`
照樣收下來，但只拿來跟程式算的比對，不拿來當開關。

## 停的三條線

```
飽和   連續幾輪沒有新網址          ← 真正的判準
夠了   四類都到下限、五塊地盤都填到
上限   繞滿幾輪                    ← 防失控
```

**「找到所有資料」不是判準，那沒有盡頭。** 判準是「再多讀一個也不會
改變故事」。

## 狀態寫在檔案裡

`_hunt/state.json`。跑到一半掛掉（模型逾時、網路斷）接得回來，而且
**這一趟到底發生了什麼，事後查得到** —— 存在記憶體裡的東西等於沒有。
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
import urllib.parse
from typing import Any

from geo.pipe import ask, paths, story as story_module

RULES = paths.GEO / "data" / "rules.json"

# 這一步要工具。**只有這一步。** 其他每一步都是「看著我給的材料判斷」。
TOOLS = "WebSearch WebFetch"

KINDS = ("news", "wiki", "official", "study", "voices")
LANDS = ("now", "status", "turn", "before", "novel")
LAND_SAY = {"now": "現在", "status": "身分", "turn": "轉折",
            "before": "前傳", "novel": "新不新"}

# 連得上就算數。**403 不算開不了** —— 很多站擋的是「用什麼工具連」，
# 不是網址本身。把 403 當成壞掉的話會丟掉真的來源，那比留著假的更糟。
DEAD = (404, 410)


def _rules() -> dict[str, Any]:
    got = json.loads(RULES.read_text(encoding="utf-8")).get("hunt")
    if not got:
        raise SystemExit("rules.json 沒有 hunt 這一節")
    return got


def _state_at(story: str):
    return paths.home(story) / "_hunt" / "state.json"


def _load(story: str) -> dict[str, Any]:
    """讀狀態。**讀不出來要 raise，不要回空的。**

    這個形狀這個專案修過兩次（題目檔壞了四天沒人發現、情境影片索引變成
    31 位元組的空殼）—— 讀失敗就回空的話，下一次寫入會把空的存回去，
    而畫面上只是「還沒跑過」。
    """
    one = _state_at(story)
    if not one.is_file():
        return {"spine": "", "read": [], "unknown": [], "rounds": [],
                "covered": {k: False for k in LANDS}}
    try:
        return json.loads(one.read_text(encoding="utf-8"))
    except Exception as bad:                                  # noqa: BLE001
        raise SystemExit(
            f"{one} 讀不出來（{type(bad).__name__}：{bad}）。"
            f"要重來的話先把它刪掉，或加 --again")


def _save(story: str, state: dict[str, Any]) -> None:
    one = _state_at(story)
    one.parent.mkdir(parents=True, exist_ok=True)
    tmp = one.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    tmp.replace(one)


UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124 Safari/537.36")


def opens(url: str) -> tuple[bool, str]:
    """這個網址真的開得起來嗎。**程式去問，不信模型說有。**

    模型會給出看起來很合理而不存在的網址 —— 這條路上同一個形狀出現過：
    收回四家媒體，名字、地區、立場都填得漂亮，四家都不存在。

    **用 curl，不用 urllib。** 這台機器的 Python 沒有 CA 憑證
    （`CERTIFICATE_VERIFY_FAILED`），urllib 連 en.wikipedia.org 都連不上
    —— 而那會讓這一支把每一筆真來源都當成死連結丟掉，然後回報「找到 0 筆」。
    加這一支的時候先拿七個網址試過，就是這樣抓到的。
    """
    got = subprocess.run(
        ["curl", "-sS", "-L", "-o", "/dev/null", "-w", "%{http_code}",
         "--max-time", "25", "-A", UA, url],
        capture_output=True, text=True)
    code = (got.stdout or "").strip()
    if code == "000" or not code.isdigit():
        return False, (got.stderr or "連不上").strip()[:60]
    if int(code) in DEAD:
        return False, code
    if int(code) >= 400:
        # **403 不算開不了。** 很多站擋的是「用什麼工具連」，不是網址本身。
        # 當成壞掉的話會丟掉真的來源，那比留著一筆可疑的更糟。
        return True, f"{code}（擋機器人，網址本身在）"
    return True, code


def tongue_of(url: str) -> str:
    """維基網址的語言。不是維基的回空字串。"""
    host = urllib.parse.urlparse(url).netloc
    got = re.match(r"([a-z-]+)\.(m\.)?wikipedia\.org$", host)
    return got.group(1) if got else ""


def host_of(url: str) -> str:
    return urllib.parse.urlparse(url).netloc.lower().removeprefix("www.")


def trusted(url: str, trust: list[str]) -> bool:
    host = host_of(url)
    return any(host.endswith(one) or host == one.lstrip(".") for one in trust)


def wells(state: dict[str, Any]) -> set[str]:
    """voices 打過幾口**井**，不是幾筆。

    第一次實測，`voices 2/2` 是同一個平台的兩次查詢，只有查詢字串不同
    —— 而模型自己老實講了「這是同一個場域」，是我的配額照收。
    **同一口井打兩次不是兩個來源。**
    """
    return {host_of(one["url"]) for one in state["read"]
            if one["kind"] == "voices"}


def _need(state: dict[str, Any], rule: dict[str, Any]) -> list[str]:
    """還缺什麼。**每一格都寫分母** —— 一個「0」看不出是都過了還是沒查。"""
    out = []
    have = {k: sum(1 for one in state["read"] if one["kind"] == k)
            for k in KINDS}
    for kind, want in rule["least"].items():
        if have.get(kind, 0) < want:
            out.append(f"{kind} {have.get(kind, 0)}/{want}")
    gone = [LAND_SAY[k] for k in LANDS if not state["covered"].get(k)]
    if gone:
        out.append("還沒填到的地盤：" + "、".join(gone))
    dug = wells(state)
    if len(dug) < int(rule.get("voices_wells_least", 0)):
        out.append(f"voices 打過的井 {len(dug)}/{rule['voices_wells_least']}"
                   f"（同一個平台查兩次只算一口）")
    tongues = {tongue_of(one["url"]) for one in state["read"]} - {"", "en"}
    if len(tongues) < int(rule.get("tongues_least", 0)):
        out.append(f"英文以外的維基語言 {len(tongues)}/"
                   f"{rule['tongues_least']}")
    return out


def _round(story: str, spec: dict[str, Any], state: dict[str, Any],
           at: int, rule: dict[str, Any], say=print) -> dict[str, Any]:
    read = "\n".join(
        f"- [{one['kind']}] {one['url']}\n    {one['gist'][:200]}"
        for one in state["read"]) or "（還沒讀過任何東西）"
    unknown = "\n".join(f"- {one}" for one in state["unknown"]) \
        or "（還沒有 —— 這是第一輪）"
    need = "\n".join(f"- {one}" for one in _need(state, rule)) or "（都到了）"
    tongues = "、".join(sorted(
        {tongue_of(one["url"]) for one in state["read"]} - {""})) or "（還沒讀過維基）"
    prompt = ask.prompt_of(
        "hunt.md", title=spec["title"], round=at,
        rounds_most=rule["rounds_most"],
        spine=state["spine"] or "（還沒定，這一輪由你定）",
        read=read, unknown=unknown, need=need, tongues=tongues,
        tongues_least=rule.get("tongues_least", 0),
        most_sources=rule["most_sources"],
        trust="　".join(rule["trust"]),
        study_trust="　".join(rule["study_trust"]),
        voices_wells_least=rule.get("voices_wells_least", 0),
        wells="、".join(sorted(wells(state))) or "（還沒打過）")
    return ask.as_json(ask.send(story, "hunt", prompt, say, tools=TOOLS))


def _merge(state: dict[str, Any], got: dict[str, Any], rule: dict[str, Any],
           at: int, say=print) -> int:
    """把這一輪收到的併進狀態，回「新增幾筆」。"""
    if got.get("spine"):
        if state["spine"] and got["spine"] != state["spine"]:
            say(f"　問題線改了：{state['spine']}")
            say(f"　　　　　　→ {got['spine']}")
            if got.get("why_spine"):
                say(f"　　理由：{got['why_spine']}")
        state["spine"] = got["spine"]

    seen = {one["url"] for one in state["read"]}
    fresh = 0
    for one in got.get("found") or []:
        url = str(one.get("url") or "").strip()
        kind = str(one.get("kind") or "").strip()
        if not url or url in seen:
            continue
        if kind not in KINDS:
            say(f"　⚠ 丟掉：kind 是 {kind!r}，不在 {'／'.join(KINDS)} 裡"
                f"　{url[:70]}")
            continue
        # **兩張白名單，不是一張。** 第一次實測混用一張的後果：大學的新聞
        # 稿被當成「原始文件」—— 那跟人工那次把智庫標成 official 是同一個
        # 錯。一張白名單混淆了兩件事：**可信**和**一手**。
        gate = {"official": (rule["trust"], "一手文件"),
                "study": (rule["study_trust"], "分析")}.get(kind)
        if gate and not trusted(url, gate[0]):
            say(f"　⚠ 丟掉：{kind} 的網域不在{gate[1]}白名單　{url[:70]}")
            continue
        # **白名單要雙向。** 只查「標 study 的是不是 study 網域」，那標錯
        # 的往另一邊跑就繞過去了 —— 實測第二趟，brookings.edu 被標成
        # `news`，於是「分析」那一格看起來還缺，而它其實已經在手上。
        # 模型自己在 `why` 裡註記了「此筆屬 study 性質」，是我沒接住。
        wrong = [name for name, book in (("official", rule["trust"]),
                                         ("study", rule["study_trust"]))
                 if name != kind and trusted(url, book)]
        if wrong and kind in ("news", "voices"):
            say(f"　⚠ 丟掉：標成 {kind}，而網域是 {wrong[0]} 那一類"
                f"　{url[:70]}")
            continue
        alive, why = opens(url)
        if not alive:
            say(f"　⚠ 丟掉：開不起來（{why}）　{url[:70]}")
            continue
        seen.add(url)
        fresh += 1
        state["read"].append({
            "url": url, "kind": kind, "round": at,
            "why": str(one.get("why") or ""),
            "gist": str(one.get("gist") or "")})

    for k in LANDS:
        if (got.get("covered") or {}).get(k):
            state["covered"][k] = True
    state["unknown"] = [str(x) for x in (got.get("unknown") or [])]
    state["rounds"].append({
        "at": at, "found": fresh, "enough": bool(got.get("enough")),
        "when": time.strftime("%m-%d %H:%M")})
    return fresh


def run(story: str, say=print, dry: bool = False,
        again: bool = False) -> dict[str, Any]:
    spec = story_module.load(story)
    rule = _rules()
    if again:
        _state_at(story).unlink(missing_ok=True)
    state = _load(story)
    quiet = 0

    for at in range(len(state["rounds"]) + 1, rule["rounds_most"] + 1):
        gap = _need(state, rule)
        if not gap and state["read"]:
            say(f"\n四類和五塊地盤都到了，第 {at} 輪不跑")
            break
        say(f"\n{'─' * 8} 第 {at} 輪 / {rule['rounds_most']} {'─' * 8}")
        for one in gap:
            say(f"　缺：{one}")
        got = _round(story, spec, state, at, rule, say)
        fresh = _merge(state, got, rule, at, say)
        _save(story, state)
        say(f"　這一輪新增 {fresh} 筆，累計 {len(state['read'])} 筆"
            + ("　（模型說夠了）" if got.get("enough") else ""))
        if fresh == 0:
            quiet += 1
            if quiet >= int(rule.get("stop_when_nothing_new", 1)):
                say(f"　連續 {quiet} 輪沒有新東西 —— 飽和了，停")
                break
        else:
            quiet = 0

    return _finish(story, state, rule, say, dry)


def _finish(story: str, state: dict[str, Any], rule: dict[str, Any],
            say, dry: bool) -> dict[str, Any]:
    say(f"\n{'═' * 8} 結果 {'═' * 8}")
    say(f"問題線：{state['spine'] or '⚠ 一直沒有定下來'}")
    have = {k: sum(1 for one in state["read"] if one["kind"] == k)
            for k in KINDS}
    for kind in KINDS:
        want = rule["least"].get(kind, 0)
        say(f"  {kind:<9}{have[kind]}/{want}"
            + ("" if have[kind] >= want else "　⚠ 不足"))
    dug = wells(state)
    say(f"  voices 的井 {len(dug)}/{rule.get('voices_wells_least', 0)}"
        f"　{'、'.join(sorted(dug)) or '（沒有）'}"
        + ("" if len(dug) >= int(rule.get("voices_wells_least", 0))
           else "　⚠ 同一口井打兩次不算兩個"))
    tongues = sorted({tongue_of(one["url"]) for one in state["read"]} - {""})
    say(f"  維基語言   {'、'.join(tongues) or '（沒有）'}"
        + ("" if len([t for t in tongues if t != 'en'])
           >= int(rule.get("tongues_least", 0)) else "　⚠ 只有英文"))
    for k in LANDS:
        say(f"  {LAND_SAY[k]:<9}{'✅' if state['covered'].get(k) else '⚠ 沒填到'}")

    keep = state["read"][:rule["most_sources"]]
    if dry:
        say(f"\n--dry：沒有寫進 story.json（{len(keep)} 筆）")
    else:
        where = story_module.path_of(story)
        spec = json.loads(where.read_text(encoding="utf-8"))
        spec["sources"] = [{"url": one["url"], "kind": one["kind"],
                            "why": one["why"]} for one in keep]
        tmp = where.with_suffix(".tmp")
        tmp.write_text(json.dumps(spec, ensure_ascii=False, indent=1) + "\n",
                       encoding="utf-8")
        tmp.replace(where)
        say(f"\n寫進 story.json：{len(keep)} 筆來源")
    return state


def main() -> int:
    args = [one for one in sys.argv[1:] if not one.startswith("--")]
    if not args:
        print("用法：python3 -m geo.pipe.hunt <題目> [--dry] [--again]")
        return 1
    run(args[0], dry="--dry" in sys.argv, again="--again" in sys.argv)
    return 0


if __name__ == "__main__":
    sys.exit(main())

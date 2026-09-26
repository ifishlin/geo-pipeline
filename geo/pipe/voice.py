"""台詞 → 音檔 ＋ 一條時間軸。

    python3 -m geo.pipe.make <題目> voice

讀 `3-script.tsv`（`誰⇥講什麼`，`停⇥秒數` 也是一行），寫 `4-voice/`：

```
said.wav     24k 16bit mono
said.ssml    送出去的原文 —— 出事的時候只有這份答得出「為什麼唸成這樣」
said.json    每一句的起訖、每一個字的毫秒、量到的基頻
```

## 一次合成，不是各唸各的再接

各唸各的話，響度、語速、句子之間的間隔全都變成我們算的，而**整條路後面
每一步都靠這一條時間軸**（切點吸到字上、字幕、成片長度）。Azure 一個
`<speak>` 裡可以放多個 `<voice>`，書籤照樣回報毫秒，所以沒有理由分開唸。

連續同一個角色的併成一段。一句一段的話 Azure 每段重新起頭，聽起來一句一句
斷開，而且段數直接決定將來 RVC 要跑幾次。

## 兩道門

```
書籤     少一個就 raise —— 少一個就是某一句的起點不知道，而硬切出來的
         東西看起來完全正常
音色     合成完逐段量基頻，兩兩差不到 SPREAD 倍就 raise
```

第二道是**加了才發現需要**的：第一版四個角色只給音色，量完旁白 198 Hz、
丹麥 202 Hz —— 兩個都是 zh-TW 女聲，在耳朵裡是同一個人。而 Azure 回成功、
36 個書籤全回來、每一格都對。**能算出來的就不要靠耳朵記得去聽。**
"""
from __future__ import annotations

import json
import math
import shutil
import sys
import wave
from pathlib import Path
from typing import Any

import numpy as np

from geo.pipe import paths, story as story_module

# 兩個角色的中位基頻差不到這麼多倍，就算「聽起來是同一個人」。
#
# 1.15 是量出來的：未調整前旁白 198 Hz、丹麥 202 Hz（1.02 倍，同一個人）；
# 調完之後最接近的一組是格陵蘭 131 對丹麥 159（1.21 倍，分得開）。門訂在
# 中間偏低，讓「剛好分得開」過得去，「其實沒分開」過不去。
SPREAD = 1.15

# 唸出來可以離目標多遠。比寫稿那一道（±6%）鬆一點 —— 那一道擋的是
# 「估計就不對」，這一道擋的是「估計對了但唸出來不對」，後者是最後一關，
# 太嚴的話會為了兩秒把一份好稿子退回去。
OVER = 0.08


def read_script(story: str) -> list[tuple[str, str]]:
    """`3-script.tsv` 讀成 [(誰, 講什麼)]。`停` 也是一種「誰」。"""
    one = paths.at(story, "script")
    out: list[tuple[str, str]] = []
    for at, row in enumerate(one.read_text(encoding="utf-8").splitlines(), 1):
        if not row.strip() or row.lstrip().startswith("#"):
            continue
        cols = row.split("\t")
        if len(cols) != 2 or not cols[1].strip():
            raise SystemExit(
                f"{one.name} 第 {at} 行不是「誰⇥講什麼」兩欄：{row!r}")
        out.append((cols[0].strip(), cols[1].strip()))
    if not out:
        raise SystemExit(f"{one.name} 是空的")
    return out


def _esc(said: str) -> str:
    return (said.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _to_ssml(said: str) -> str:
    """一句台詞 → SSML。**就地標記在這裡變成真的停頓和變速。**

    `⏸0.3` → `<break time="300ms"/>`，`⟪-10 字⟫` → `<prosody rate="-10%">`。
    沒有這一步的話那些符號會被 Azure 當成字唸出來。
    """
    from geo.pipe import marks
    return marks.to_ssml(said, _esc)


def build_ssml(rows: list[tuple[str, str]], cast: dict[str, dict[str, Any]],
               rate: int, gap: int, lang: str) -> tuple[str, int]:
    """組 SSML，連續同角色併成一個 `<voice>`。回 (ssml, 幾句)。"""
    parts: list[str] = []
    body: list[str] = []
    now = ""
    said = 0

    def close() -> None:
        if not body:
            return
        knobs: dict[str, str] = {}
        if rate:
            knobs["rate"] = f"{rate:+d}%"
        if cast[now].get("pitch"):
            knobs["pitch"] = str(cast[now]["pitch"])
        inner = "".join(body)
        if knobs:
            inner = ("<prosody"
                     + "".join(f' {k}="{v}"' for k, v in knobs.items())
                     + f">{inner}</prosody>")
        # 句尾換氣由我們決定，不用 Azure 的 630ms 預設。**要在 voice 裡面** ——
        # 放外面 Azure 收下然後安靜忽略，而「標記沒生效」聽了才知道。
        parts.append(f'<voice name="{cast[now]["voice"]}">'
                     f'<mstts:silence type="Sentenceboundary" value="{gap}ms"/>'
                     f"{inner}</voice>")
        body.clear()

    for who, text in rows:
        if who == "停":
            try:
                many = float(text)
            except ValueError:
                raise SystemExit(f"停頓不是數字：{text!r}") from None
            # 停頓掛在**前一段的尾巴**，留在同一條時間軸上。
            body.append(f'<break time="{int(many * 1000)}ms"/>')
            continue
        if who != now:
            close()
            now = who
        body.append(f'<bookmark mark="L{said}"/>{_to_ssml(text)}')
        said += 1
    close()
    return ('<speak version="1.0" '
            'xmlns="http://www.w3.org/2001/10/synthesis" '
            'xmlns:mstts="http://www.w3.org/2001/mstts" '
            f'xml:lang="{lang}">' + "".join(parts) + "</speak>"), said


def pitches(wav: Path, bounds: list[list[float]], who: list[str]
            ) -> dict[str, float]:
    """逐段量中位基頻。**自相關，只取有聲的幀。**"""
    with wave.open(str(wav)) as f:
        rate = f.getframerate()
        sound = (np.frombuffer(f.readframes(f.getnframes()), dtype=np.int16)
                 .astype(np.float64) / 32768)
    window, hop, lo, hi = int(0.04 * rate), int(0.02 * rate), 70, 400
    got: dict[str, list[float]] = {}
    for name, (start, end) in zip(who, bounds):
        piece = sound[int(start * rate):int(end * rate)]
        found = got.setdefault(name, [])
        for at in range(0, max(0, len(piece) - window), hop):
            frame = piece[at:at + window]
            if math.sqrt((frame ** 2).mean()) < 0.02:
                continue
            frame = frame - frame.mean()
            corr = np.correlate(frame, frame, "full")[window - 1:]
            lo_k, hi_k = rate // hi, rate // lo
            if hi_k >= len(corr):
                continue
            k = int(np.argmax(corr[lo_k:hi_k])) + lo_k
            if corr[k] > 0.3 * corr[0]:
                found.append(rate / k)
    return {name: float(np.median(seen)) for name, seen in got.items() if seen}


def spread_ok(heard: dict[str, float]) -> list[str]:
    """哪幾組角色聽起來是同一個人。"""
    names = sorted(heard)
    bad = []
    for i, one in enumerate(names):
        for other in names[i + 1:]:
            a, b = heard[one], heard[other]
            times = max(a, b) / min(a, b)
            if times < SPREAD:
                bad.append(f"{one}（{a:.0f} Hz）跟 {other}（{b:.0f} Hz）"
                           f"只差 {times:.2f} 倍")
    return bad


def run(story: str, say=print) -> dict[str, Any]:
    import azure.cognitiveservices.speech as speechsdk

    paths.insist(story, "voice")
    spec = story_module.load(story)
    rows = read_script(story)
    lines = [(w, t) for w, t in rows if w != "停"]
    cast = story_module.cast_of(spec)

    unknown = sorted({w for w, _ in lines} - set(cast))
    if unknown:
        raise SystemExit(
            f"稿子裡有 cast 沒宣告的角色：{'、'.join(unknown)}。"
            f"到 {paths.home(story) / 'story.json'} 的 cast 補上，"
            f"可以用的位子在 geo/data/voices.json")
    idle = sorted(set(cast) - {w for w, _ in lines})
    if idle:
        # 不擋，但要出聲：宣告了卻沒人講，通常是稿子裡的名字打錯了。
        say(f"⚠ cast 宣告了但稿子裡沒出現：{'、'.join(idle)}")

    # **語速和句號停頓從 `rules.json` 讀，不是從故事檔，更不是寫在這裡。**
    # 原本是 `spec.get("rate_percent", 40)` —— 而 story.json 根本沒寫那一格，
    # 所以真正生效的是這一行裡的預設值。**數字藏在程式裡，設定檔看不到。**
    from geo.pipe.spine import rules as _rules
    how = _rules().get("voice") or {}
    ssml, many = build_ssml(rows, cast, int(how.get("rate_percent", 40)),
                            int(how.get("sentence_gap_ms", 150)),
                            spec.get("lang", "zh-TW"))
    if many != len(lines):
        raise SystemExit(f"書籤 {many} 個對不上 {len(lines)} 句")

    # **先寫進暫存目錄，全部做完才換上去。**
    #
    # 這一步中間有兩道門（書籤數、音色分得開），而合成在門之前 —— 第一版
    # 直接寫進 `4-voice/`，於是音色那道門擋下來的時候，新的 wav 已經躺在
    # 那裡了，而 `said.json` 還是上一版的。下一次跑：`done()` 說跑過了、
    # `stale()` 看 wav 的時間說沒過期，整個步驟被跳過 —— **成片用的是
    # 上一版台詞的聲音，而每一個檔案都在、每一道門都過。**
    #
    # 破壞已經發生，產出還沒發生。同一個形狀這個專案出過四次。
    final = paths.at(story, "voice")
    into = final.with_name(final.name + ".part")
    if into.is_dir():
        shutil.rmtree(into)
    into.mkdir(parents=True, exist_ok=True)
    wav = into / "said.wav"
    (into / "said.ssml").write_text(ssml, encoding="utf-8")
    say(f"{len(lines)} 句、{len(rows) - len(lines)} 個停頓、"
        f"{ssml.count('<voice ')} 段")
    for name in sorted(cast, key=lambda n: -sum(1 for w, _ in lines if w == n)):
        got = sum(1 for w, _ in lines if w == name)
        mark = "　（借的腔調）" if cast[name].get("borrowed") else ""
        say(f"  {name:<5}{got:>3} 句　{cast[name]['voice']}"
            f"{'　' + cast[name]['pitch'] if cast[name].get('pitch') else ''}{mark}")

    key = story_module.azure_key()
    talk = speechsdk.SpeechConfig(subscription=key,
                                  region=story_module.azure_region())
    talk.set_speech_synthesis_output_format(
        speechsdk.SpeechSynthesisOutputFormat.Riff24Khz16BitMonoPcm)
    talk.set_property(
        speechsdk.PropertyId.SpeechServiceResponse_RequestWordBoundary, "true")
    engine = speechsdk.SpeechSynthesizer(
        speech_config=talk,
        audio_config=speechsdk.audio.AudioOutputConfig(filename=str(wav)))

    words: list[dict[str, Any]] = []

    def _word(one: Any) -> None:
        # 不是每個事件都真的是一個字：英文軌出過 `Word` 帶 331 個字元的。
        # 丟掉而不是修 —— 那幾筆的時間點跟真正的逐字事件重複。
        kind = str(one.boundary_type).split(".")[-1]
        text = str(one.text)
        if len(text) > (4 if kind == "Punctuation" else 30):
            return
        words.append({"at": round(one.audio_offset / 10_000_000, 3),
                      "text": text, "kind": kind})

    engine.synthesis_word_boundary.connect(_word)
    at_ms: dict[int, float] = {}
    engine.bookmark_reached.connect(
        lambda one: at_ms.__setitem__(int(str(one.text).lstrip("L")),
                                      one.audio_offset / 10_000_000))
    say("送出去唸…")
    got = engine.speak_ssml_async(ssml).get()
    if got.reason != speechsdk.ResultReason.SynthesizingAudioCompleted:
        note = getattr(got, "cancellation_details", None)
        raise SystemExit(f"沒唸出來：{got.reason}"
                         f"{'　' + str(note.error_details) if note else ''}")
    if len(at_ms) != len(lines):
        raise SystemExit(f"書籤只回來 {len(at_ms)}/{len(lines)} 個 —— "
                         f"少一個就是某一句的起點不知道，不猜")

    whole = len(got.audio_data) / 2 / 24000
    starts = [at_ms[i] for i in range(len(lines))]
    bounds = [[round(starts[i], 3),
               round(starts[i + 1] if i + 1 < len(starts) else whole, 3)]
              for i in range(len(starts))]
    who = [w for w, _ in lines]
    heard = pitches(wav, bounds, who)
    same = spread_ok(heard)
    say("")
    for name in sorted(heard, key=lambda n: -heard[n]):
        say(f"  {name:<5}{heard[name]:>6.0f} Hz")
    if same:
        raise SystemExit(
            "這幾組角色聽起來是同一個人：\n  " + "\n  ".join(same)
            + f"\n到 geo/data/voices.json 調 pitch，或換一個位子。"
            f"（門檻 {SPREAD} 倍）")

    # **量到的真秒數，擋在估計式後面。** 寫稿那一步用的是一條估計式
    # （字數、句數、停頓），而估計式會錯 —— 第一版只算字數，585 字估
    # 115 秒、唸出來 133 秒。估計式改好了，但它仍然只是一條式子；
    # 這一道問的是「實際上唸了幾秒」，那個沒有猜的成分。
    #
    # 放在這裡而不是壓片那一步：**昂貴的步驟前面要先確認產物用得到**，
    # 而超長的音檔會讓後面十分鐘的渲染變成白工。
    aim = float(spec.get("seconds") or 0)
    if aim and abs(whole - aim) > aim * OVER:
        raise SystemExit(
            f"唸出來 {whole:.1f} 秒，而目標是 {aim:.0f}"
            f"（容許 {aim * (1 - OVER):.0f}–{aim * (1 + OVER):.0f}）。\n"
            f"  這是量到的，不是估的。回去重寫台詞："
            f"`python3 -m geo.pipe.make {story} script --again`\n"
            f"  差得多的話，`script.py` 的 RATE／PER_LINE 要拿這一次的"
            f"數字重新校：{len(lines)} 句、"
            f"{sum(len(__import__('re').findall(r'[一-龥]', t)) for _, t in lines)} 個漢字")

    body = {"file": wav.name, "seconds": round(whole, 3),
            "who": who, "lines": [t for _, t in lines],
            "bounds": bounds, "words": words,
            "pitch": {k: round(v, 1) for k, v in heard.items()}}
    (into / "said.json").write_text(
        json.dumps(body, ensure_ascii=False, indent=1), encoding="utf-8")
    # 全部做完、每一道門都過了，才換上去。
    if final.is_dir():
        shutil.rmtree(final)
    into.rename(final)
    wav = final / wav.name
    say(f"\n{wav.relative_to(paths.ROOT)}　{whole:.1f} 秒"
        f"（{int(whole // 60)}:{whole % 60:04.1f}）　逐字 {len(words)} 個")
    return body


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "")

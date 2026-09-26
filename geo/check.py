"""掃「函式裡用了不存在的名字」。

    python3 -m geo.check

## 為什麼要這一支

一個晚上被同一個形狀咬三次：整塊改常數的時候把幾個一起刪掉，而
**`import` 過不代表函式裡的名字存在** —— Python 要等那一行真的跑到才查。

三次都是在**模型呼叫之後**才炸：

```
NameError: ASIDE_LEAST      在 12 分鐘的呼叫之後
NameError: DATE_HEAD_MOST   在 3 分鐘的呼叫之後
KeyError: 'nodes'           在整趟配音之後
```

那幾趟的答案有存下來，所以損失是時間不是錢。但十二分鐘就是十二分鐘。

## 怎麼掃

用 AST，不用 `co_names` —— 後者把 `paths.ROOT` 的 `ROOT` 也算進去，
二十個報告裡二十個是誤報。**會亂叫的檢查等於沒有檢查。**

抓得到：用了沒定義的全域名。抓不到：字典的鍵（`bones["nodes"]`）、
屬性（`spec.hero`）—— 那些要靠型別，這裡不做。
"""
from __future__ import annotations

import ast
import builtins
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
KNOWN = set(dir(builtins)) | {"__file__", "__name__", "__doc__"}


def _bound(node: ast.AST) -> set[str]:
    """這個函式（或模組）自己綁了哪些名字。"""
    out: set[str] = set()
    for one in ast.walk(node):
        if isinstance(one, ast.arg):
            out.add(one.arg)
        elif isinstance(one, ast.Name) and isinstance(one.ctx, ast.Store):
            out.add(one.id)
        elif isinstance(one, (ast.FunctionDef, ast.AsyncFunctionDef,
                              ast.ClassDef)):
            out.add(one.name)
        elif isinstance(one, (ast.Import, ast.ImportFrom)):
            for alias in one.names:
                out.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(one, ast.ExceptHandler) and one.name:
            out.add(one.name)
        elif isinstance(one, (ast.Global, ast.Nonlocal)):
            out.update(one.names)
    return out


def scan(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
    outer = _bound(tree) | KNOWN
    bad: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        inside = outer | _bound(node)
        for one in ast.walk(node):
            if (isinstance(one, ast.Name) and isinstance(one.ctx, ast.Load)
                    and one.id not in inside):
                bad.append(f"{path.name}:{one.lineno}　{node.name}() "
                           f"用到不存在的 {one.id}")
    return bad


def main() -> None:
    files = sorted(p for p in HERE.rglob("*.py")
                   if "__pycache__" not in str(p))
    bad: list[str] = []
    for one in files:
        bad += scan(one)
    print(f"掃了 {len(files)} 個檔")
    for one in bad:
        print(f"  ✗ {one}")
    if bad:
        sys.exit(f"\n{len(bad)} 個名字不存在")
    print("✅ 沒有用到不存在的名字")


if __name__ == "__main__":
    main()

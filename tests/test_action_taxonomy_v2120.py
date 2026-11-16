# -*- coding: utf-8 -*-
"""B · 动作分类 / 事件分档的钉子（v2.12.0 第 12 轮）。

判据（作业单 §六）：README 里「打扰还是陪伴」一节的**每个事件名**必须在
pet_events.TAXONOMY 里存在，反之亦然（两边同源）；分档值也只能是 disturb / companion。

## 每条能真失败在哪

- README 里多写一个 TAXONOMY 没有的事件名 → test_doc_has_no_extra_events 红；
- TAXONOMY 里加一个 README 没写的事件 → test_table_has_no_missing_events 红；
- 把某一行的分档从「打扰」改成「陪伴」而不改代码 → test_kind_column_matches_table 红；
- 把 TAXONOMY 的某个值写成第三种分档（例如 info）→ test_kinds_are_only_two 红；
- 删掉 README 里的标记块 → test_markers_exist 红（判据不许退化成空检查）。
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import pet_events  # noqa: E402

_BEGIN = "<!-- taxonomy:begin -->"
_END = "<!-- taxonomy:end -->"
_ROW_RE = re.compile(r"^\|\s*`([a-z_]+)`\s*\|\s*(打扰|陪伴)\s*\|.*\|$")


def _doc_section():
    src = open(os.path.join(HERE, "README.md"), encoding="utf-8").read()
    i = src.index(_BEGIN)
    j = src.index(_END)
    return src[i:j]


def _doc_rows():
    rows = {}
    for line in _doc_section().splitlines():
        m = _ROW_RE.match(line.strip())
        if m:
            rows[m.group(1)] = m.group(2)
    return rows


def test_markers_exist():
    seg = _doc_section()
    assert "`notify`" in seg or _doc_rows(), "标记块在，但里面一条事件行都解析不出来"
    assert len(_doc_rows()) == len(pet_events.TAXONOMY)


def test_table_has_no_missing_events():
    missing = sorted(set(pet_events.TAXONOMY) - set(_doc_rows()))
    assert missing == [], "代码表里有、README 里没写：%r" % (missing,)


def test_doc_has_no_extra_events():
    extra = sorted(set(_doc_rows()) - set(pet_events.TAXONOMY))
    assert extra == [], "README 里写了、代码表里没有：%r" % (extra,)


def test_kind_column_matches_table():
    want = {"disturb": "打扰", "companion": "陪伴"}
    rows = _doc_rows()
    for name, val in pet_events.TAXONOMY.items():
        kind = val[0]
        assert rows.get(name) == want[kind], "%s 的分档两边对不上：doc=%r code=%r" % (
            name, rows.get(name), kind)


def test_kinds_are_only_two():
    for name, val in pet_events.TAXONOMY.items():
        assert isinstance(val, tuple) and len(val) == 2, name
        assert val[0] in pet_events.KINDS, "%s 的分档不在 %r 里" % (name, pet_events.KINDS)


def test_unknown_event_is_conservative():
    assert pet_events.kind_of("nope") is None
    assert pet_events.is_disturb("nope") is True   # 没登记 = 按打扰审
    assert pet_events.is_disturb("easter") is False

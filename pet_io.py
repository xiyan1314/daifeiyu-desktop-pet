# -*- coding: utf-8 -*-
"""
大肥鱼桌宠 · 全仓共用的原子 IO 助手（v2.3.1，落地评审 P0-1 / P0-2 / P1-3 / P2-2）。

为什么要有这个模块
------------------
v2.3.0 只给 pet_book/pet_config 修了"固定 .tmp + 无锁"这一处同款 bug，其余 6 个
模块（pet_chat/pet_resources/pet_alarm/pet_behaviors/pet_voice/pet_lines）仍是旧口径：

- 固定临时名 "<file>.tmp" + 无锁：两个线程同时写同一文件会互相截断，json.dump 的
  多次 write 在字节级交错 → os.replace 把半截 JSON 提交上盘。
  （error.log 实测：load_chat_memory 读取失败 ×140、pet_book._read_json ×170）
- os.replace 在 Windows 上会因杀软/索引器/残留句柄抛 PermissionError（共享冲突），
  旧代码一律 except 吞掉 → 这次写入静默丢失、坏文件原样留在磁盘上。
- 读到坏文件只返回默认值、不回写 → 坏 JSON 每次启动重报（根因 B）。

本模块把这三件事一次做对。全部纯 stdlib、**Qt-free**（不 import pet_log / PySide6），
可脱离 GUI 单测：

- path_lock(path)          按路径分锁：同一文件的所有写者共用同一把可重入锁（键已 normcase）
- atomic_write_json(...)   原子写 JSON：进程+线程唯一临时名 + os.replace 冲突短重试
- atomic_write_bytes(...)  原子写二进制（语音缓存等同款需求）
- _read_json_status(...)   读 JSON → (data, corrupted, unreadable)，绝不抛（读侧单一实现）
- read_json_or(...)        二元口径薄壳：读 JSON 并**如实告知是否损坏**（文件缺失 ≠ 损坏）
- read_json_ex(...)        三元口径 + 可选**当场愈合**（读只一次、锁内完成；全仓读侧真源）
- heal_json(...)           read_json_ex 的薄壳：回写合法结构（顶层坏 / 内层类型非法）
- backup_before_heal(...)  愈合/重建前留 "<path>.bak"（自建恢复路径的模块共用）
- backup_before_overwrite(...)  覆盖写**之前**留同一份 "<path>.bak"（读不到/非 UTF-8 的模块共用）
- clean_tmp_files(...)     清扫 "<p>.tmp" / "<p>.<线程号>.tmp" / "<p>.<进程号>.<线程号>.tmp"
- fallback_encodings()     编码回退候选顺序（本机 locale 页 → GBK → 单字节西文页最后）
- read_json_fallback(...)  非 UTF-8 文件的**恢复读**（按字节重读 + 换编码 + 解析），绝不写盘
- is_single_byte_encoding(...) / is_local_encoding(...)  回退判据（文案与排序共用）

v2.3.1（读侧愈合口径一致性收口，本轮）：
- 临时名加**进程号**（同机多实例/调试时不再撞名），clean_tmp_files 的白名单同步放宽；
- ".bak" 每个目标路径**只保留一份**（反复愈合覆盖旧的那份，覆盖时记一行日志说明）；
- heal_json 增加 normalize 判据：顶层合法但**内层类型非法**（如 {"history": {...}}）
  也能被检出 → 记一行日志 + .bak + 按调用方给的归一化结构重建（重建是否安全由调用方
  判定：返回 reason 为空 = 一个字节都不写，只当没这回事）；
- _MergeGuard 改成**真变参**（此前 __enter__ 只 acquire 前两把锁，第 3 把被静默忽略）。

并发语义（重要）
----------------
1. 锁的粒度是**规范化绝对路径**（normcase(abspath)）：Windows/macOS 文件系统大小写
   不敏感，"x.json" 与 "X.JSON" 是同一个文件，必须映射到同一把锁。缓存 dict 由一把
   全局锁保护（不是每个调用点各拿一把自己的锁——那等于没锁），同一路径的所有写者真正串行。
2. 锁可重入（RLock）：读-改-写（pet_chat 的 memory.json 合并）能在**同一把锁**内
   完成读与写——既不会自己死锁，也不会被别的线程插进来用旧快照覆盖。
3. atomic_write_* 总是拿"路径锁"；调用方另有自己的锁时（pet_book/pet_config 保留
   历史锁语义），按固定顺序"调用方锁 → 路径锁"获取，不存在反向路径，故无死锁。
4. read_json_ex / heal_json 的"读 + 判 + 愈合回写"全在**同一把路径锁内**完成：锁内本进程
   没有别的写者，所以既不会覆盖在途写者刚写好的新数据，也不必"先在锁外读一遍探测、再进锁
   复查一遍"（v2.4.1 前那样写的话，每次真损坏要读两遍磁盘）。
5. 锁只覆盖本进程；跨进程并发不在本模块范围内（桌宠用命名互斥体保证单实例）。

日志口径：异常一律在 except 里交给调用方注入的 log 回调（默认 None=不记），
本模块**绝不向上抛异常**——持久化失败降级成返回值/日志，绝不把调用方拖崩。

类型注解口径（v2.4.3 澄清，第三轮找茬的"口径误导"一条）
--------------------------------------------------------
本模块的注解范围 = **公开 API 与纯函数**（25/28；未标的 3 个是 _MergeGuard 的
__init__/__enter__/__exit__）。全仓口径见 README「类型注解口径」一节：v2.4.1 那句
「pet_tools + pet_lines 82 个函数补全注解」只覆盖那两个 Qt-free 模块；桌宠、pet_dialogs、
pet_voice 等大文件仍是零注解，属**单独立项**——别把 82/82 读成"全仓注解完成"。
（本模块自己不再扩注解范围：这轮只澄清口径。）
"""
import codecs
import json
import locale
import os
import re
import shutil
import threading
import time
from typing import Any, Callable, Iterable

# 全局锁 → 保护 _LOCKS 这张表本身；_LOCKS[绝对路径] → 该路径的专用可重入锁
_LOCKS_GUARD = threading.Lock()
_LOCKS = {}

# 原子写临时名的中间段（白名单判据，**单一来源**）：
#   ""                     → "<名字>.tmp"（v2.3.0 之前的固定名，历史残留仍要清）
#   "<线程号>"             → "<名字>.<线程号>.tmp"（v2.3.0/2.3.1 早期）
#   "<进程号>.<线程号>"     → "<名字>.<进程号>.<线程号>.tmp"（v2.3.1 起，见 atomic_write_bytes）
# 只认"两段以内纯十进制数字"：用户自己的 "lines.json.v2.tmp" / "x.bak" 一律不在白名单里。
# 用 [0-9] 而不是 \d：[0-9] 只认 ASCII，\d 在 Python 里还认阿拉伯-印度数字等（会误删）。
_TMP_MID_RE = re.compile(r"[0-9]+(?:\.[0-9]+)?\Z")

# os.replace 共享冲突（Windows 杀软/索引器/残留句柄）重试间隔：实测 50ms 足够让
# 瞬时句柄释放，最多重试 retries 次（默认 3 → 最坏多等 150ms，只发生在故障路径上）
_RETRY_SLEEP = 0.05


def path_lock(path: str | os.PathLike) -> threading.RLock:
    """取某路径的专用锁（可重入）。同一路径的所有写者拿到的必须是同一把锁。

    v2.3.1（L1 修复）：键先 normcase(abspath)——Windows 文件系统大小写不敏感，
    "x.json" 与 "X.JSON" 指向**同一个文件**，按字面路径分锁会给出两把不同的锁
    （等于没锁：两个写者各自持锁交错写盘）。macOS 默认同款。
    """
    key = os.path.normcase(os.path.abspath(str(path)))
    with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()   # 可重入：读-改-写要在同一把锁里读+写
            _LOCKS[key] = lock
        return lock


def _log(log: Callable[[str], Any] | None, msg: str) -> None:
    """日志回调（注入式）：日志通道自身出错不影响持久化主流程。"""
    if log is None:
        return
    try:
        log(msg)
    except Exception:
        pass  # 有意忽略：日志失败绝不影响写盘


def _cleanup_tmp(tmp: str, log: Callable[[str], Any] | None) -> None:
    """删除本次写入自己的临时文件（进程+线程唯一名，别人不会用这个路径）。"""
    try:
        if os.path.exists(tmp):
            os.remove(tmp)
    except Exception as e:
        _log(log, "pet_io 临时文件清理失败 %s: %r" % (tmp, e))


def _default_from(factory: Callable[[], Any], expect: type | None,
                  log: Callable[[str], Any] | None, path: object) -> Any:
    """取调用方注入的默认值；连默认值都造不出来时退回与 expect 同型的空容器。

    v2.3.1（M3）：本模块对外的承诺是"绝不抛异常"，而 factory 是**调用方注入**的
    可调用对象——它自己抛异常时不能穿透到调用栈（读文件的位置通常没有 try）。
    """
    try:
        return factory()
    except Exception as e:
        _log(log, "pet_io 默认值构造失败（改用空结构）%s: %r" % (path, e))
        if expect is dict:
            return {}
        if expect is list:
            return []
        return None


def backup_before_heal(path: str | os.PathLike,
                       log: Callable[[str], Any] | None = None) -> bool:
    """愈合/重建**之前**把原文件另存 "<path>.bak"（留证，判错时可手工恢复）。

    返回 True=已备份、False=文件不存在或备份失败（失败只记日志，绝不抛：
    备份失败不该反过来挡住愈合）。所有"自建读+回写愈合"的调用点都应先调它，
    与 heal_json 内部口径一致。

    **.bak 生命周期（v2.3.1 一致性收口）**：备份名是**固定**的 "<path>.bak"，不生成
    "<path>.bak.1/.2/…"。因此：
      · 单个目标路径的 .bak 数量上限恒为 1（同目录 .bak 总数 = 被愈合过的目标路径数，
        不会随愈合次数增长——愈合 N 次也只多一份"最近一次愈合前的内容"）；
      · 上一轮残留的 .bak 会被本次覆盖，覆盖时**记一行日志**说明，避免用户把新备份
        误当成最早那份坏数据（老备份没有诊断价值，这是刻意的取舍：宁可留最近的，
        也不要备份无限增殖把数据目录撑满）。
    运行时残留（.tmp/.bak）不进绿色版目录与发布包——_check_release.py 会点名。
    """
    src = str(path)
    try:
        if not os.path.exists(src):
            return False
        if os.path.exists(src + ".bak"):
            _log(log, "pet_io 旧备份已被本次愈合覆盖（同目标只保留最近一份 .bak）%s"
                 % (src + ".bak"))
        shutil.copyfile(src, src + ".bak")
        return True
    except Exception as e:
        _log(log, "pet_io 愈合备份失败（继续愈合）%s: %r" % (src, e))
        return False


def backup_before_overwrite(path: str | os.PathLike,
                            log: Callable[[str], Any] | None = None) -> bool:
    """**覆盖写之前**把磁盘上的原文件另存 "<path>.bak"（原文快照，写坏了还能回去）。

    v2.4.2（兼容 M4）：与 pet_lines/pet_book 的"脏读 → 首次写前留 .bak"同口径，抽成
    共用 API 给 pet_alarm/pet_behaviors 用——这两个模块此前**没有任何**保护：alarms.json
    是 GBK/读不到时内存里是空库，用户第一次加闹钟就把原文整份覆盖成 {"alarms": […] }，
    旧条目与自定义顶层键一起消失、无 .bak、不可恢复。

    与 backup_before_heal 的关系：落盘动作**完全相同**（同一份 .bak、同一套覆盖日志），
    这里直接复用它的实现，不复制第二份。区别只在调用时机与触发条件：
      · backup_before_heal：读侧判定"文件坏了，马上要愈合重建"；
      · 本函数：读侧这次没读到（权限/共享占用）或编码不是 UTF-8，而用户接下来的一次
        写会把原文改成另一种编码（或只剩内存里的种子库）→ 写前留证。
    调用方负责"一次脏读只留一份"（用自己的标志位去重）：每写一次都调它等于把 .bak
    反复覆盖成最新内容，最早那份原文反而没了。
    """
    return backup_before_heal(path, log)


# ---------------- 编码回退读（v2.4.2 兼容 M3/M4：全仓单一实现） ----------------
# 记事本「ANSI」另存在中文 Windows 上是 GBK/cp936、日文是 cp932、繁体是 cp950、韩文是 cp949：
# 内容完全可读，而 _read_json_status 的 UTF-8 口径只能把它们归成 unreadable（不能证明损坏，
# 所以一个字节都不写）。本段是"换编码再解一次"的**唯一实现**，pet_lines / pet_alarm /
# pet_behaviors 共用（入口 read_json_fallback）；绝不写盘——救回来的内容交给各模块自己的
# 归一化与"首次写前留 .bak"口径（见 backup_before_overwrite）。
FALLBACK_ENCODINGS = ("gbk", "cp936")   # cp936 在 Python 里是 gbk 的别名，写上只为可读

# "几乎就是 UTF-8"的两条容差（见 _almost_utf8）：损坏**段数**上限 = max(1, 总字节数 // 200)
# （≈0.5%），且替换解码后至少还剩 1 个**完好**的非 ASCII 字符（文件里确实有完整的多字节
# UTF-8 序列，而不是"每个高位字节都是坏字节"的单字节西文文件）。
# v2.4.3（第三轮找茬 P3-4）：**极小文件会退化**——总字节数 < 200 时整除结果为 0，被 max()
# 兜成"允许 1 段"（不是 0.5% 而是"一个损坏段也算数"）。这里有意不收紧：判据二要求除
# U+FFFD 之外还有一个完好的非 ASCII 字符，纯西文小文件（"caf\xe9" 的重音符全是坏字节，
# 解出来只剩 U+FFFD）仍会被拒；而真被截断/坏一字节的小文件里其余汉字都还在，能救回来。
# 判据二的回归见 tests/test_round3_a_fixes.py::test_tiny_western_file_is_not_almost_utf8。
_UTF8_DAMAGE_DIVISOR = 200
_UTF8_MIN_SURVIVORS = 1
# U+FFFD（替换字符）：用 chr() 写，源码里不放不可见字符（判据见 _almost_utf8）
_FFFD = chr(0xFFFD)


def preferred_encoding() -> str:
    """本机默认编码（locale.getpreferredencoding(False)）；取不到返回 ""（绝不抛）。"""
    try:
        return str(locale.getpreferredencoding(False) or "")
    except Exception:
        return ""   # 有意忽略：拿不到系统默认编码 ≠ 读不了文件，固定表已覆盖 GBK


def _codec_name(enc: str) -> str:
    """编码 → 规范名（"cp936"→"gbk"、"latin-1"→"iso8859-1"）；不认识的返回小写原样。

    去重与"命中编码 == 本机编码"的比较**必须**走规范名：cp936 与 gbk 是同一个编解码器，
    按字面比较会把"就是按本机 ANSI 读到的"误判成"猜的"（文案会跟着变成谨慎口径）。
    """
    e = str(enc or "").strip().lower()
    if not e:
        return ""
    try:
        return codecs.lookup(e).name
    except Exception:
        return e   # 有意忽略：查不到的别名按字面比较（宁可判成"不是本机编码"，也不抛）


def is_single_byte_encoding(enc: str) -> bool:
    """单字节代码页判据：0x80~0xFF 里**几乎每个字节单独**都能解出一个字符。

    实测 cp1252/cp1251/latin-1/cp850 通过（cp1252 有 5 个未定义字节，容差 8），而
    gbk/cp932/cp950/cp949/big5/utf-8 对孤立的高位字节一律抛 UnicodeDecodeError（首字节
    缺尾字节）。判据的用途：这类编码能把**任意**字节序列解出来（永不抛），所以既不能排
    在多字节 CJK 页前面（排序见 fallback_encodings），命中时也不能对用户承诺"内容没丢"
    （见 pet_lines.read_notice）。
    """
    if not enc:
        return False
    bad = 0
    for b in range(0x80, 0x100):
        try:
            bytes((b,)).decode(enc)
        except UnicodeDecodeError:
            bad += 1
            if bad > 8:
                return False
        except (LookupError, ValueError):
            return False
        except Exception:
            return False   # 有意忽略：编解码器自身异常按"不是单字节页"处理（宁可少判一次）
    return True


def is_gbk_encoding(enc: str) -> bool:
    """命中编码是不是 GBK 家族（GBK / cp936；"gb2312"/"gb18030" 也是同族的超集）。

    用途：文案分支（GBK 那份老文案逐字不变，见 pet_lines.notice_for_encoding）。按规范名
    比较，所以 "cp936" 与 "gbk" 会走同一条分支。
    """
    return _codec_name(enc) in ("gbk", "gb2312", "gb18030")


def is_local_encoding(enc: str) -> bool:
    """命中编码是不是**本机默认编码**（规范名比较：cp936 == gbk）。

    回退读有两种性质完全不同的结果：「按本机 ANSI 页读到的」（这台机器的记事本就写这个，
    内容可信）与「按别的页猜的」（GBK 只是最可能的猜测）。只有前者才敢对用户说
    "你的台词都还在"，后者必须用谨慎文案（见 pet_lines.read_notice）。
    """
    name = _codec_name(enc)
    return bool(name) and name == _codec_name(preferred_encoding())


def fallback_encodings() -> list[str]:
    """编码回退候选顺序（单一来源）：**本机 locale 页 → GBK/cp936 → 单字节西文页最后**。

    顺序由三条实测结论定（v2.4.2 兼容审查）：
      · 本机 locale 是**多字节**页（cp932/cp950/cp949/cp936…）时**先试它**：那台机器上
        记事本的「ANSI」就是它。固定表在前会把日文 cp932 台词库按 GBK 解成乱码
        （「こんにちは」→「偙傫偵偪偼」），而乱码**照样能过 JSON 解析** → 被当成"读到了"、
        气泡还说"台词都还在"，首次保存就把乱码转成 UTF-8。
      · 其余情况 GBK/cp936 在前（"ANSI 另存"最可能就是这个；locale 不是它的机器上，
        GBK 至少还是个**多字节**页，不会把任意字节都解出来）。
      · **单字节西文页（cp1252/cp1251/latin-1…）一律排最后**：它们能把任意字节序列解出来，
        放前面等于"任何文件都能被它接住"——实测 cp1252 会把"坏了一个字节的 UTF-8"
        整份接住并给出 mojibake（ÿ½ å¥½ï¼Œä¸–ç•Œ）。
      · 只列这几个候选是有意的：每多一个候选就多一份"解错了也能过 JSON 解析"的风险，
        够用即可（真读到 UTF-16 这类应当走脏读/愈合路径，不该靠本函数猜）。
    去重按规范名（cp936 与 gbk 只留一个），本机就是 cp936 时保留可读性更好的字面量 "gbk"
    （日志与气泡都说 GBK）。本函数绝不抛。
    """
    out: list[str] = []
    seen: set[str] = set()

    def _add(enc: str) -> None:
        name = _codec_name(enc)
        if not name or name in seen:
            return
        seen.add(name)
        out.append(enc)

    pref = preferred_encoding()
    pref_name = _codec_name(pref)
    # UTF-8 系/ASCII 不是"另一种编码"，不能当候选（那正是刚才失败的那次解码）
    usable = bool(pref_name) and not pref_name.startswith("utf") and pref_name != "ascii"
    single = usable and is_single_byte_encoding(pref)
    if usable and not single:
        _add("gbk" if pref_name == "gbk" else pref)
    for enc in FALLBACK_ENCODINGS:
        _add(enc)
    if single:
        _add(pref)
    return out


def _almost_utf8(raw: bytes) -> bool:
    """"几乎就是 UTF-8"：整份按 UTF-8 解只差**少量**字节（坏一个字节 / 被截断的尾巴）。

    用途见 read_json_fallback：这种文件落到单字节西文页手里会变成 mojibake（实测"坏一个
    字节的中文台词库"→ cp1252 → ÿ½ å¥½ï¼Œä¸–ç•Œ），所以先把它从单字节候选里排除。
    两条判据都要满足（宁可漏判，也不要把正常的西文文件误判成"坏 UTF-8"）：
      · 替换解码出的**损坏段数** ≥1 且 ≤ max(1, 总字节数 // 200)（≈0.5%）。按"段"而不是按
        U+FFFD 字符数：一个坏掉的汉字会解出 2~3 个 U+FFFD（首字节/尾字节各自成段），按
        字符数算会把"只坏了 1 个字"的小文件挡在门外（实测 92 字节坏 1 字 = 3 个 U+FFFD）。
        真 ANSI 文件实测坏字节占比 9%~13%，远在这条线之上；
      · 除去 U+FFFD 之后仍有 ≥1 个非 ASCII 字符——文件里确实存在**完整的**多字节 UTF-8
        序列（"坏了一个字节的中文台词库"里其余汉字都还在）；纯西文文件一个都不会有
        （"café" 的重音符全是坏字节，解出来只剩 U+FFFD），所以不会被误判。

    v2.4.3（第三轮找茬 P3-4）：判据一的段数上限对 **<200 字节**的文件退化成 max(1, 0) = 1
    （见常量 _UTF8_DAMAGE_DIVISOR 处的说明）。这是**已知且有意保留**的退化：极小文件本来
    就只可能有一两个损坏段，"按比例"没有意义；真正把纯西文文件挡在门外的是判据二，
    两个判据联合后极小文件不会误判（有测试钉住这条边界）。
    """
    try:
        raw.decode("utf-8")
        return False        # 本来就是 UTF-8：不该走回退
    except UnicodeDecodeError:
        pass
    try:
        text = raw.decode("utf-8", "replace")
    except Exception:
        return False        # 有意忽略：替换解码不该失败；真失败就按"不是"处理（不拦候选）
    runs = len(re.findall(_FFFD + "+", text))
    if runs < 1 or runs > max(1, len(raw) // _UTF8_DAMAGE_DIVISOR):
        return False
    return sum(1 for ch in text if ord(ch) > 127 and ch != _FFFD) >= _UTF8_MIN_SURVIVORS


def read_json_fallback(path: str | os.PathLike, *, expect: type | None = dict,
                       log: Callable[[str], Any] | None = None) -> tuple[Any, str]:
    """UTF-8 读失败后的**恢复读**：按字节重读一次，先判编码再解析。绝不写盘、绝不抛。

    返回 (data, 编码名)：
      · (dict, "")      文件本来就是 UTF-8——刚才那次失败是瞬时 IO（共享冲突/权限），重读即可；
      · (dict, "gbk")   确实不是 UTF-8，按该编码读出来了（调用方据此提示用户）；
      · (None, "")      回退也读不出来（权限/占用/解不开/JSON 坏/顶层类型不对）。

    为什么不是"换个 encoding 再 open 一次"：pet_io 把"解码失败"与"这次读不到"归成同一个
    unreadable 口径，而这两者必须区别对待——解码失败才该换编码；读不到换什么编码都一样。
    更要命的是，一份**正常的 UTF-8** 文件按 GBK 也能"解出来"，那样会把好文件读成乱码还
    谎称"已按 GBK 读取"。所以先按字节读：读得到才谈编码。

    只认「能解码**且**能解析成 expect 类型（默认顶层 dict）」的结果：解码成功但 JSON 仍坏、
    或顶层不是对象，一律算失败——宁可少救一次，也不能把"其实读不懂"的文件当成读懂了再用
    UTF-8 覆盖回去。候选顺序见 fallback_encodings；单字节候选还要先过 _almost_utf8。
    """
    try:
        with open(str(path), "rb") as f:
            raw = f.read()
    except OSError as e:
        _log(log, "pet_io 回退读失败（按默认值继续）%s: %r" % (path, e))
        return None, ""     # 还是读不到（权限/占用）→ 交回调用方的"读不到"路径，一个字节都不写
    enc = ""
    try:
        text = raw.decode("utf-8-sig")   # 与 _read_json_status 同口径：UTF-8 with BOM 也算 UTF-8
    except UnicodeDecodeError:
        text = ""
        for cand in fallback_encodings():
            if is_single_byte_encoding(cand) and _almost_utf8(raw):
                continue    # 单字节页 + "几乎就是 UTF-8" → 这是被写坏的 UTF-8，不是西文文件
            try:
                text = raw.decode(cand)
            except (UnicodeDecodeError, LookupError):
                continue
            enc = cand
            break
        if not text:
            return None, ""
    try:
        data = json.loads(text)
    except (ValueError, RecursionError) as e:
        _log(log, "pet_io 回退读解码成功但 JSON 仍坏（按默认值继续）%s: %r" % (path, e))
        return None, ""
    if expect is not None and not isinstance(data, expect):
        _log(log, "pet_io 回退读顶层结构非法（按默认值继续）%s: %s" % (path, type(data).__name__))
        return None, ""
    return data, enc


def clean_tmp_files(targets: Iterable[str | os.PathLike],
                    log: Callable[[str], Any] | None = None) -> int:
    """清扫这些目标文件的原子写残留（三种临时名形状，见 _TMP_MID_RE）。

    v2.3.1（L4）：临时名带线程号之后，退出/清 Key 时只删固定名 ".tmp" 已经扫不到
    真正会残留的文件（崩溃时留下的是 "<p>.12345.tmp"）。
    v2.3.1（一致性收口）：临时名再加**进程号**（"<p>.<pid>.<tid>.tmp"），白名单同步放宽成
    "中间段 ≤2 段纯十进制数字"——旧形状（"<p>.tmp" / "<p>.<tid>.tmp"）仍要清（升级后
    磁盘上就有这种残留），新形状也要清。**白名单**：只认这三种形状，不动用户的其它文件
    （"<p>.v2.tmp"、"<p>.bak" 都不在白名单里）。

    返回实际删除条数，绝不抛异常。每个目标先取**同一把路径锁**：在途写者持锁期间
    （锁内是"写 tmp → os.replace"整段）它的 tmp 不可能被本函数删掉，因此运行期调用也安全。
    """
    removed = 0
    for p in (targets or ()):
        p = str(p)
        d = os.path.dirname(p) or "."
        base = os.path.basename(p)
        try:
            with path_lock(p):
                names = [base + ".tmp"]
                try:
                    for n in os.listdir(d):
                        if n.startswith(base + ".") and n.endswith(".tmp"):
                            if _TMP_MID_RE.match(n[len(base) + 1:-4]):
                                names.append(n)
                except OSError as e:
                    _log(log, "pet_io 临时文件枚举失败 %s: %r" % (d, e))
                for n in names:
                    fp = os.path.join(d, n)
                    try:
                        if os.path.isfile(fp):
                            os.remove(fp)
                            removed += 1
                    except OSError as e:
                        _log(log, "pet_io 临时文件清理失败 %s: %r" % (fp, e))
        except Exception as e:
            _log(log, "pet_io 临时文件清理跳过 %s: %r" % (p, e))
    return removed


def _guard(path: str | os.PathLike, lock: object) -> object:
    """按固定顺序取锁：调用方锁（可选）→ 路径锁。返回 contextmanager。"""
    path_lk = path_lock(path)
    if lock is None or lock is path_lk:
        return path_lk
    return _MergeGuard(lock, path_lk)


class _MergeGuard(object):
    """同时持有"调用方锁 + 路径锁（可以更多把）"的极简上下文（顺序固定 → 不会死锁）。

    v2.3.1（一致性收口）：此前 __enter__ 写死了 self._locks[0] / [1]——传第 3 把锁会被
    **静默忽略**（调用方以为自己持锁了，其实没有；这比直接报错危险得多）。现在改成真变参：
    按传入顺序逐个 acquire，中途失败就**逆序回滚**已拿到的那几把；__exit__ 逆序释放。
    同一个锁对象被重复传入时只 acquire 一次（否则非可重入锁会自己把自己锁死）。
    """

    __slots__ = ("_locks",)

    def __init__(self, *locks):
        uniq = []
        seen = set()
        for lk in locks:
            if id(lk) in seen:      # 重复传入同一对象：只算一把（RLock 之外的自锁死保护）
                continue
            seen.add(id(lk))
            uniq.append(lk)
        self._locks = tuple(uniq)

    def __enter__(self):
        held = []
        try:
            for lk in self._locks:
                lk.acquire()
                held.append(lk)
        except Exception:
            for lk in reversed(held):   # 中途失败：把自己已经拿到的锁还回去
                lk.release()
            raise
        return self

    def __exit__(self, *exc):
        for lk in reversed(self._locks):
            lk.release()
        return False


def atomic_write_bytes(path: str | os.PathLike, data: bytes, *,
                       lock: Any = None, retries: int = 3,
                       log: Callable[[str], Any] | None = None) -> str | None:
    """原子写二进制：临时文件 + os.replace；成功返回 None，失败返回错误字符串（绝不抛）。

    临时名带**进程号 + 线程号**（"%s.%d.%d.tmp" % (path, pid, tid)）——两个线程同时写
    同一文件不会抢同一个 tmp 互相截断，**同机多实例/调试双开**时也不会撞名（两个进程的
    线程号完全可能相同，只带线程号挡不住跨进程撞名）。os.replace 因共享冲突失败时 sleep
    后重试（最多 retries 次），最终失败则清理自己的 tmp 并记日志。
    clean_tmp_files 按同一形状白名单清扫（见 _TMP_MID_RE）。
    """
    path = str(path)
    tmp = "%s.%d.%d.tmp" % (path, os.getpid(), threading.get_ident())
    attempts = max(1, int(retries) + 1)   # 首写 1 次 + 重试 retries 次
    try:
        with _guard(path, lock):
            d = os.path.dirname(path)
            if d:
                os.makedirs(d, exist_ok=True)
            with open(tmp, "wb") as f:
                f.write(data)
            last = None
            for i in range(attempts):
                try:
                    os.replace(tmp, path)
                    return None
                except PermissionError as e:
                    # Windows 共享冲突：杀软/索引器/残留句柄瞬时锁住目标文件
                    last = e
                    if i < attempts - 1:
                        time.sleep(_RETRY_SLEEP)
            raise last
    except Exception as e:
        _cleanup_tmp(tmp, log)   # 失败清理自己的 tmp（退出时的 *.tmp 清扫见 clean_tmp_files）
        _log(log, "pet_io 写盘失败 %s: %r" % (path, e))
        return str(e)


def atomic_write_json(path: str | os.PathLike, data: Any, *,
                      lock: Any = None, retries: int = 3,
                      log: Callable[[str], Any] | None = None,
                      indent: int | None = 2) -> str | None:
    """原子写 JSON（UTF-8 / ensure_ascii=False）；成功 None，失败错误字符串。

    indent 默认 2（与 pet_book/pet_resources/… 原口径一致）；记忆文件传 indent=None
    保持原来的紧凑单行格式（不改用户的既有文件观感）。
    """
    try:
        text = json.dumps(data, ensure_ascii=False, indent=indent)
    except Exception as e:
        _log(log, "pet_io JSON 序列化失败 %s: %r" % (path, e))
        return str(e)   # 序列化失败时还没有 tmp 落盘，无需清理
    return atomic_write_bytes(path, text.encode("utf-8"),
                              lock=lock, retries=retries, log=log)


def _read_json_status(path: str | os.PathLike, factory: Callable[[], Any] = dict, *,
                      expect: type | None = dict,
                      log: Callable[[str], Any] | None = None) -> tuple[Any, bool, bool]:
    """读 JSON → (data, corrupted, unreadable)，绝不抛出。

    **v2.4.1（A 区一致性收口）：这是全仓读侧的单一实现**——read_json_or / load_json /
    read_json_ex / heal_json 都走它（此前 pet_book._read_json 与 pet_resources._read_json_ex
    是两份逐字相同的复制品，"修一处漏一处"）。

    - 文件不存在 → (factory(), False, False)：首次运行不是错误，也**不需要愈合**
    - 解析失败 / 顶层类型不是 expect → (factory(), True, False)：真损坏，调用方可据此愈合
    - 读取本身失败但文件在（权限/共享占用等）→ (factory(), False, True)：**不能证明损坏**，
      绝不据此回写（否则可能用空结构覆盖掉别人的好文件）
    - 非 UTF-8 编码（GBK/ANSI 另存）同 OSError 口径 → unreadable=True、corrupted=False

    与 heal_json 同口径：factory 自己抛异常也不外泄（M3），退回与 expect 同型的空容器。
    """
    try:
        # v2.3.1（兼容审查 S1）：用 utf-8-sig——用户用记事本另存为「UTF-8 with BOM」时
        # 内容其实完好，用 utf-8 读会抛 JSONDecodeError 被判"损坏"→ 被空结构覆盖清空。
        with open(str(path), "r", encoding="utf-8-sig") as f:
            data = json.load(f)
    except FileNotFoundError:
        return _default_from(factory, expect, log, path), False, False
    except OSError as e:
        _log(log, "pet_io 读取失败（按默认值继续）%s: %r" % (path, e))
        return _default_from(factory, expect, log, path), False, True
    except UnicodeDecodeError as e:
        # v2.3.1（兼容审查 S1）：解码失败 ≠ 内容损坏。GBK/ANSI 另存的文件内容完全可读，
        # 旧版对它一个字节都不动；把它判成"坏"再回写 = 原地销毁用户数据。
        # 与 OSError 同口径：不能证明损坏 → 不回写，只记一行日志。
        _log(log, "pet_io 编码不是 UTF-8（按默认值继续，不覆盖原文件）%s: %r" % (path, e))
        return _default_from(factory, expect, log, path), False, True
    except Exception as e:
        # 其余（JSONDecodeError / RecursionError…）= 文件内容确实坏了
        _log(log, "pet_io 解析失败（按默认值重建）%s: %r" % (path, e))
        return _default_from(factory, expect, log, path), True, False
    if expect is not None and not isinstance(data, expect):
        _log(log, "pet_io 顶层结构非法（按默认值重建）%s: %s"
             % (path, type(data).__name__))
        return _default_from(factory, expect, log, path), True, False
    return data, False, False


def read_json_or(path: str | os.PathLike, factory: Callable[[], Any] = dict, *,
                 expect: type | None = dict, log: Callable[[str], Any] | None = None
                 ) -> tuple[Any, bool]:
    """读 JSON；返回 (data, corrupted: bool)（= _read_json_status 的二元口径）。

    调用方要区分"文件不存在"与"文件在但读不到"时改用 read_json_ex（三元口径）。
    """
    data, corrupted, _unreadable = _read_json_status(path, factory, expect=expect, log=log)
    return data, corrupted


def read_json_ex(path: str | os.PathLike, factory: Callable[[], Any] = dict, *,
                 expect: type | None = dict, log: Callable[[str], Any] | None = None,
                 heal: bool = True, retries: int = 3, indent: int | None = 2,
                 normalize: Callable[[Any], tuple[Any, Any]] | None = None
                 ) -> tuple[Any, bool, bool]:
    """读 JSON → (data, corrupted, unreadable)，可选**当场愈合**（读侧唯一真源）。

    v2.4.1（A 区一致性收口）：pet_book._read_json / pet_resources._read_json_ex 此前是
    两份逐字相同的自建实现（各自 read_json_or + heal_json 读两遍磁盘），现在收敛到本函数，
    那两个函数退化成薄壳。口径：

    · **读只发生一次**：读、判、愈合回写全在同一把路径锁内完成。锁内本进程没有别的写者，
      因此既不需要"先读一遍探测、再进锁复查一遍"（旧写法每次真损坏都要读两遍磁盘），
      也不存在"回写覆盖在途写者刚写好的新数据"的窗口。
    · corrupted=False 时**一个字节都不写**（文件不存在 / 读不到 / BOM / GBK 都算）。
      heal=False 给"马上要改名 / 另有更强恢复路径"的调用方（如 pet_book 的 usage.json 迁移）。
    · unreadable=True 专指"文件在磁盘上但这次读不到（权限/共享占用/非 UTF-8）"——
      调用方据此**跳过整体回写**：一次瞬时 PermissionError 不许把完好数据清空。
    · normalize(data) -> (fixed, reason)：顶层合法但内层类型非法时的判据（见 _safe_normalize，
      判据自己坏了就一个字节都不写）；真损坏时走 factory() 重建、不看 normalize。
      **unreadable=True 时判据一次都不跑**：那时手里的 data 是 factory() 默认值、不是文件内容，
      拿它判“脏”就是对着没读到过的文件回写（v2.4.1 找茬 S1）。
    """
    lock = path_lock(path)
    with lock:
        data, corrupted, unreadable = _read_json_status(path, factory, expect=expect, log=log)
        if corrupted:
            if heal:
                # v2.3.1（兼容审查 S1）：愈合前先把原文件另存 .bak——万一判错了（未来又出现
                # 某种"内容可读但被判坏"的假阳性），用户的数据还在，可手工恢复。
                backup_before_heal(path, log)
                atomic_write_json(path, data, lock=lock, retries=retries, log=log, indent=indent)
        elif normalize is not None and not unreadable:
            # v2.4.1（找茬 S1）：unreadable=True 时 data 是 **factory() 默认值**，不是文件内容。
            # 拿默认值去跑判据 = 对着一个从没读到过的用户文件报"内层结构脏" → backup_before_heal
            # + 覆盖写，把"这次读不到"变成"永久改写"。读不到就一个字节都不写（与 380 行承诺一致），
            # 判据只在**真读到内容**时才跑（见 _safe_normalize）。
            fixed, reason = _safe_normalize(normalize, data, log, path)
            if reason:
                backup_before_heal(path, log)
                _log(log, "pet_io 内层结构非法（已留 .bak 并按归一化结构重建）%s: %s"
                     % (path, reason))
                atomic_write_json(path, fixed, lock=lock, retries=retries, log=log, indent=indent)
                data = fixed
    return data, corrupted, unreadable


def load_json(path: str | os.PathLike, factory: Callable[[], Any] = dict, *,
              expect: type | None = dict, log: Callable[[str], Any] | None = None
              ) -> tuple[Any, bool]:
    """read_json_or 的 ok 口径快捷版：返回 (data, ok)（ok=False=文件损坏）。

    v2.4.1 去留判定：**有意保留的 API**（不是残留）。它把"损坏"翻成布尔口径
    （ok = not corrupted），是 pet_io 读侧唯一的 bool 门面；生产路径当前不直接调用
    （各模块更关心 corrupted / unreadable 的分支），但它是公开薄壳，删掉等于破坏读侧
    API 的完整性。要用就用它，别在调用方自己写 "not corrupted"。
    契约测试：tests/test_io_v231.py::test_read_json_reports_corruption（第 206 行那条
    "ok 口径的等价入口"）；结构性回归在 tests/test_deadcode_types_v241.py（判定为保留、
    不得被当死代码删掉）。
    """
    data, corrupted = read_json_or(path, factory, expect=expect, log=log)
    return data, not corrupted


def _safe_normalize(normalize: Callable[[Any], Any] | None, data: Any,
                    log: Callable[[str], Any] | None, path: object) -> tuple[Any, Any]:
    """跑调用方注入的"内层结构"判据，返回 (fixed, reason)，绝不抛。

    normalize(data) 应当返回 (fixed, reason)：
      · reason 为空（None/""/False）= 内层结构合法 → 调用方**一个字节都不该被写**；
      · reason 非空 = 顶层合法但内层类型非法（如 {"history": {...}}）→ fixed 是"能被
        安全重建"的结构，本模块据此记日志 + 留 .bak + 回写。
    判据自己抛异常、或返回值不是二元组（写错了 API）时按"没坏"处理——**宁可少写一次，
    也不能因为判据写错就把用户的文件洗掉**。

    调用条件（v2.4.1 找茬 S1）：判据**只在真读到文件内容时才跑**。文件不存在 / 这次读不到
    （unreadable=True）时 data 是 factory() 默认值，把它当内容判脏会直接覆盖用户文件——
    read_json_ex 的分支已经挡掉这两种情况，本函数只负责"跑起来了就绝不抛、绝不误写"。
    """
    try:
        fixed, reason = normalize(data)
    except Exception as e:
        _log(log, "pet_io 内层结构检查失败（按原样继续，不写盘）%s: %r" % (path, e))
        return data, None
    if not reason:
        return data, None
    return fixed, str(reason)


def heal_json(path: str | os.PathLike, factory: Callable[[], Any] = dict, *,
              expect: type | None = dict, log: Callable[[str], Any] | None = None,
              retries: int = 3, indent: int | None = 2,
              normalize: Callable[[Any], tuple[Any, Any]] | None = None
              ) -> tuple[Any, bool]:
    """读 JSON；**只在文件仍然是坏的**时才回写 factory() 结构（一次性愈合）。

    返回 (data, corrupted)。v2.4.1（A 区一致性收口）：本函数是 pet_io.read_json_ex 的
    **薄壳**（此前"读侧愈合"有三套命名：pet_book._read_json / pet_resources._read_json_ex /
    各模块内联环，现在全部收敛到 read_json_ex 这一份实现）。因此：
      · 读只发生一次，且与"判坏 + 回写"在同一把路径锁内完成——锁内本进程没有别的写者，
        既不需要"先读一遍探测、再进锁复查一遍"，也不会覆盖在途写者刚写好的新数据；
      · indent：愈合回写的缩进口径（默认 2）；memory.json 这类原本是**紧凑单行**的文件
        由调用方传 indent=None（L2：愈合不能顺手改变文件格式）；
      · normalize：内层类型判据 callable(data) -> (fixed, reason)（v2.3.1 加）。顶层结构合法、
        但内层字段类型非法（P2：{"history": {...}}、"clips": [...] 这类）以前**静默返回空、
        无日志、不愈合**；给判据后统一成：reason 非空 → 记一行日志 + 留 .bak + 回写 fixed
        （与顶层损坏同一把锁、同一份备份口径），并把 fixed 作为返回的 data（让调用方内存态
        与盘上内容一致）。reason 为空 → 原样返回，不写。只有"能被归一化安全重建"的字段才该
        由调用方给出 fixed；不安全的（重建会丢用户能用的数据）请让判据自己记日志并返回 None。
    """
    data, corrupted, _unreadable = read_json_ex(path, factory, expect=expect, log=log, heal=True,
                                                retries=retries, indent=indent,
                                                normalize=normalize)
    return data, corrupted

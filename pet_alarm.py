# -*- coding: utf-8 -*-
"""
大肥鱼桌宠 · 闹钟系统（v2.0.5）
MIT License

职责：闹钟数据（alarms.json 原子写）、时间校验、到点判定（纯函数）、
自定义铃声导入（wav/mp3 复制进 alarms/ 目录）。纯逻辑、Qt-free，可无 GUI 单测。

闹钟结构：{"id": "<8位hex>", "time": "HH:MM", "label": 提醒文案,
           "ringtone": ""|文件名, "enabled": true, "last_fired_date": "YYYY-MM-DD"}
预留扩展字段（本版不使用其逻辑，但数据原样透传、绝不丢——未来版本直接升级）：
  repeat: ""=单次（默认）；未来 "daily"/"weekly"…（重复）
  snooze_min: 0=不贪睡；未来 >0 触发后 X 分钟再响（贪睡）

到点语义：enabled 且 now 的 HH:MM >= time 且 last_fired_date != 今天 → 触发一次，
触发后记 last_fired_date=今天（同日不重复响；跨天自动重新待命）。
"""
import os
import re
import time
import uuid

import pet_io   # v2.3.1：全仓共用原子写/安全读（分锁 + 线程唯一临时名 + replace 重试）
import pet_log

TIME_RE = re.compile(r"^([01]?\d|2[0-3]):[0-5]\d$")
RINGTONE_EXTS = (".wav", ".mp3")
ALARM_LABEL_MAX = 40
ALARMS_MAX = 50  # 闹钟数量上限（防配置爆炸）


def _empty_index():
    """合法的空闹钟库结构（愈合/默认值共用；**每次新建对象**，不做共享可变默认值）。"""
    return {"alarms": []}


def valid_time(t):
    """"HH:MM" 合法（00:00~23:59）。"""
    return isinstance(t, str) and bool(TIME_RE.match(t))


def normalize_time(t):
    """归一到 "HH:MM" 两位补零；非法返回 ""。

    P1-1（v2.3.1）：先**宽松补零**再回退严格正则。历史/手编数据里的 "7:5"、"8:0"、
    "07:30:00"（带秒）此前被判死丢弃（error.log 实测「时间格式应为 HH:MM」×15 次），
    现在分别补成 "07:05"/"08:00"/"07:30" 予以挽回；仍不合法的（"25:00"/"abc"/"7"）
    才丢弃。严格正则仍是**最终判据**，宽松解析只负责补零。
    """
    if valid_time(t):
        h, m = t.split(":")
        return "%02d:%02d" % (int(h), int(m))
    if not isinstance(t, str):
        return ""
    parts = t.strip().split(":")
    if len(parts) not in (2, 3):      # 只认 HH:MM 与 HH:MM:SS（多一段就是坏格式）
        return ""
    try:
        cand = "%02d:%02d" % (int(parts[0]), int(parts[1]))
        if len(parts) == 3:
            int(parts[2])             # 秒：必须存在且是数字，值本身忽略（"07:30:00" → "07:30"）
    except (TypeError, ValueError):
        return ""
    return cand if valid_time(cand) else ""


def now_hhmm():
    """当前本地时间 "HH:MM"（两位补零）。到点判定函数另收 now/today 参数以便测试注入。"""
    return time.strftime("%H:%M")


def today_str():
    return time.strftime("%Y-%m-%d")


def _hhmm_minutes(t):
    """"HH:MM"（已合法）→ 当天分钟数 0..1439（结构化比较用，见 due_alarms）。"""
    return int(t[:2]) * 60 + int(t[3:])


def _now_minutes(now):
    """now → 当天分钟数；非法返回 None（宽松补零：测试传 "7:59" 也认）。"""
    t = normalize_time(now)
    return _hhmm_minutes(t) if t else None


_NOW_INVALID_WARNED = False


def _warn_invalid_now(now):
    """now 非法时记**一次**日志（due_alarms 每 15s 被闹钟轮询调一次，逐次记会刷爆 error.log）。

    v2.4.1（找茬 L5）：非法 now 从"全响"改成"一个都不响"是对的，但新失败模式是**静默**的
    ——调用方格式传错只会觉得"闹钟莫名其妙不响了"，error.log 里一个字都没有。
    生产路径（now_hhmm()）永远走不到这里，所以只记一次就够定位。
    """
    global _NOW_INVALID_WARNED
    if _NOW_INVALID_WARNED:
        return
    _NOW_INVALID_WARNED = True
    pet_log.log_error("闹钟到点判定：now 非法（%r），本次一个都不响（检查调用方传入的格式）"
                      % (now,))


def due_alarms(alarms, now, today):
    """到点判定（纯函数）：返回 [(alarm, normalized_time), ...]。

    now="HH:MM"（生产侧 now_hhmm() 保证两位补零，测试可注入）、today="YYYY-MM-DD"；
    enabled 且 now >= time 且当日未触发 → 到点。

    v2.4.1（P3-5）：比较改成**结构化分钟数**，不再比字符串。"HH:MM" 的字典序在生产路径上
    恰好等于时间序（两侧都补零），但 API 很脆：调用方传未补零的 now（"7:59"）时
    "7:59" >= "08:00" 为真 → 07:59 就把 08:00 的闹钟响了；传 "abc" 更是全表齐响。
    现在两侧都先归一化成分钟数：now 非法 → 一个都不响（宁可少响一次，也不误响一整天）。
    v2.4.1（找茬 L5）：这条新失败模式不许静默——非法 now 记一次日志（见 _warn_invalid_now）。
    """
    now_min = _now_minutes(now)
    if now_min is None:
        _warn_invalid_now(now)
        return []
    out = []
    for a in alarms:
        if not isinstance(a, dict) or not a.get("enabled"):
            continue
        t = normalize_time(a.get("time", ""))
        if not t:
            continue
        if a.get("last_fired_date") == today:
            continue
        if now_min >= _hhmm_minutes(t):
            out.append((a, t))
    return out


class AlarmService:
    """闹钟库：alarms.json 持久化 + 增删改查 + 铃声导入/清除。主线程调用。"""

    def __init__(self, data_dir, log=None):
        self._dir = os.path.join(data_dir, "alarms")
        self._index = os.path.join(data_dir, "alarms.json")
        self._log = log or pet_log.log_error
        self._alarms = {}  # {id: alarm}
        # v2.4.2（Q）：alarms.json 顶层未知键的暂存（读取时收集，_save 时原样带回）
        self._top_extra = {}
        # v2.4.2（兼容 M4）：这次启动"文件在磁盘上却没读到"（编码不是 UTF-8 且回退也解不开 /
        # 权限 / 共享占用）或"按回退编码读到、原文不是 UTF-8"。两种情况下用户**第一次**
        # 增删闹钟都会把原文改掉（前者只剩内存里的空库，后者会改编码），所以首次写前必须先
        # 留一份 .bak——与 pet_lines/pet_book 同口径（见 _save）。
        self._read_failed = False
        self._reencoded_read = False
        self._backed_before_write = False
        self._load()

    # ---------- 持久化 ----------
    def _load(self):
        """读闹钟库并归一化；**清洗过就回写愈合**（P0-2）。

        此前把坏条目从内存丢掉却不落盘：坏数据留在 alarms.json 里，
        每次启动都重报「时间格式应为 HH:MM」（error.log 实测 ×15）。
        现在只要"损坏 / 丢条目 / 归一化确实改了内容"就愈合回写一次，
        下次启动读到的是干净文件，报错不再复发。

        v2.4.1（A 区一致性收口）：自建"读 + 清洗 + 手工 backup + _save"环改成
        pet_io.heal_json（清洗判据走它的 normalize 入参）——读、判、回写都在**同一把
        路径锁内**完成，与 alarms 之外的模块共用同一套 .bak / 日志口径；不再自己维护
        一份（自建环的两个弱点：从"读到坏"到"回写"之间本进程写者能插进来；备份与回写
        是两次独立操作，口径容易与 pet_io 漂移）。
        """
        self._alarms = {}
        self._top_extra = {}
        self._read_failed = False
        self._reencoded_read = False
        self._backed_before_write = False
        _normalize_ran = []      # 判据跑过 = pet_io 这次**真读到了**文件内容（见文件末尾）

        def _normalize(data):
            """内层结构判据（交给 heal_json）：清洗 alarms 数组 → (fixed, reason)。

            reason 非空 = 内存态与盘上内容不一致（损坏 / 丢条目 / 补零清洗）→ 需要回写愈合；
            为空 = **一个字节都不写**。data 一定是 dict（read_json_or 的 expect=dict 兜着）。
            """
            _normalize_ran.append(True)   # 判据只在"真读到内容"时才被调（见 heal_json 的 unreadable 口径）
            raw = data.get("alarms")
            clean = {}
            dirty = False
            if not isinstance(raw, list):
                if raw is not None:
                    self._log("alarm index alarms field not a list, reset to empty")
                    dirty = True
                raw = []
            for a in raw:
                na, err = self._norm_alarm(a)
                if na is None:
                    # 坏条目=用户数据损坏：记日志留痕（不弹窗，静默恢复）
                    self._log("alarm index dropped bad entry: %s" % (err or "格式非法"))
                    dirty = True
                elif na["id"] not in clean:
                    clean[na["id"]] = na
                    if na != a:
                        dirty = True   # 补零/清洗（如 "7:5"→"07:05"）也要落盘，避免每次启动重做
                else:
                    self._log("alarm index dropped duplicate id: %s" % na["id"])
                    dirty = True
            # 内存态与**本次真读到的**内容一致（含愈合后的）；一个字节都不写时也走这里
            self._alarms = clean
            self._top_extra = {k: v for k, v in data.items() if k != "alarms"}
            if not dirty:
                return data, None
            # v2.4.2（Q）：愈合回写**保留顶层未知键**。条目级未知键一直在保留（见 _norm_alarm
            # "复制原条目再覆盖已知键"），顶层此前却是整份重建 {"alarms": ...}——用户手加的
            # 自定义段 / 未来版本写入的新键会在"读一次就愈合"这一步永久消失。
            # 口径：fixed = dict(原顶层) 后只覆盖已知段；坏条目按 clean 重建（不回带）。
            fixed = dict(data)
            fixed["alarms"] = [a for a in clean.values()]
            return fixed, "alarms 索引含坏条目/非法结构"

        _data, _corrupted = pet_io.heal_json(self._index, _empty_index, log=self._log,
                                             normalize=_normalize)
        # v2.4.2（兼容 M4）：heal_json 的 unreadable 分支**不跑判据**（那时手里只有 factory()
        # 默认值，拿它判"脏"就是对着没读到过的文件回写——v2.4.1 找茬 S1 的口径，不动）。
        # 于是"判据没跑过 + 文件确实存在"就等于"这次没读到"：编码不是 UTF-8（记事本「ANSI」
        # 另存）或权限/共享占用。前者先试编码回退（与 pet_lines 同一个 pet_io 实现）——
        # 能读到就一条不丢；连回退都解不开才置 _read_failed（首次写前留 .bak，见 _save）。
        # 修之前这里是**零保护**：GBK 的 alarms.json 读到空库，用户第一次加闹钟就把原文整份
        # 覆盖成 {"alarms": [新条目]}，旧条目与自定义顶层键一起消失、没有 .bak、不可恢复。
        if not _normalize_ran and not _corrupted and os.path.exists(self._index):
            fb, _enc = pet_io.read_json_fallback(self._index, expect=dict, log=self._log)
            if fb is not None:
                _normalize(fb)          # 同一套清洗判据（只改内存态，不写盘）
                self._reencoded_read = bool(_enc)
                if _enc:
                    self._log("alarms.json 不是 UTF-8，已按 %s 读取（内容正常，未改写原文件）"
                              % str(_enc).upper())
            else:
                self._read_failed = True
                self._log("alarms.json 在磁盘上但读不出来（编码/占用），本次按空库继续；"
                          "改动前会先备份成 alarms.json.bak")

    def _save(self):
        # v2.4.2（Q）：顶层未知键原样带回（先铺未知键、再覆盖已知段）——否则"愈合时保住了、
        # 用户下一次加/删闹钟又丢"等于没修。条目级未知键一直由 _norm_alarm 保留，此处补齐顶层。
        data = dict(self._top_extra)
        data["alarms"] = list(self._alarms.values())
        # v2.4.2（兼容 M4）：本次启动没读到原文（脏读）→ 这一写会把用户原文整份覆盖成内存里的
        # 空库 + 新条目；回退读到的原文同样会在这一写里被改成 UTF-8。两种情况下**写前**先留
        # 一份 .bak（一次脏读只留一份：写失败重试不重复覆盖，成功后清标记回到正常路径）。
        _reencode = self._read_failed or self._reencoded_read
        if _reencode and not self._backed_before_write:
            if pet_io.backup_before_overwrite(self._index, self._log):
                self._backed_before_write = True
        err = pet_io.atomic_write_json(self._index, data, log=self._log)
        if err is None and _reencode:
            _had_bak = self._backed_before_write
            _why = ("原文件不是 UTF-8（回退读取），本次已转存为 UTF-8"
                    if self._reencoded_read else "原文件此前读不到")
            self._read_failed = False
            self._reencoded_read = False
            self._backed_before_write = False
            self._log("alarms.json 已按 UTF-8 重建（%s；%s）"
                      % (_why, "原文已留 .bak" if _had_bak else "**备份失败**，原文已被覆盖"))
        # 有意忽略：写盘失败记日志（内存态仍可用）——pet_io 已在 except 里记过，这里不重复

    @staticmethod
    def _norm_alarm(a):
        """单条闹钟归一化：非法结构/时间返回 (None, err)；预留字段透传不丢。"""
        if not isinstance(a, dict):
            return None, "闹钟条目不是对象"
        t = normalize_time(a.get("time", ""))
        if not t:
            return None, "时间格式应为 HH:MM"
        # v2.3.1（兼容审查 M1）：**先复制原条目**再覆盖已知键——否则任何未知键
        # （用户手加的备注、未来版本写入的新字段）都会在"读取时归一化回写"这一步被永久删掉
        out = dict(a)
        out.update({
            "id": str(a.get("id") or uuid.uuid4().hex[:8]),
            "time": t,
            "label": str(a.get("label") or "闹钟").strip()[:ALARM_LABEL_MAX] or "闹钟",
            "ringtone": str(a.get("ringtone") or ""),
            "enabled": a.get("enabled") is not False,
            "last_fired_date": str(a.get("last_fired_date") or ""),
            "repeat": str(a.get("repeat") or ""),       # 预留：重复（本版不使用但保留）
            # 预留：贪睡（本版不使用但保留；仅非负 int 透传，坏值落 0）
            "snooze_min": a.get("snooze_min") if (isinstance(a.get("snooze_min"), int)
                                                  and a.get("snooze_min") >= 0) else 0,
        })
        if out["ringtone"] and not out["ringtone"].lower().endswith(RINGTONE_EXTS):
            out["ringtone"] = ""  # 坏扩展：清洗为默认提示音
        # 拒绝含路径分隔符/上级目录的铃声引用（防播放 alarms/ 目录外文件）
        if out["ringtone"] and os.path.basename(out["ringtone"]) != out["ringtone"]:
            out["ringtone"] = ""
        return out, ""

    # ---------- 查改 ----------
    def list(self):
        return [dict(a) for a in sorted(self._alarms.values(), key=lambda x: x["time"])]

    def get(self, aid):
        a = self._alarms.get(str(aid or ""))
        return dict(a) if a is not None else None

    def add(self, time_s, label="闹钟", ringtone="", enabled=True, repeat="", snooze_min=0):
        """新增闹钟。返回 (alarm|None, err)。enabled/repeat/snooze_min 供
        导入路径透传（预留字段本版不使用逻辑但数据保留）。"""
        na, err = self._norm_alarm({"time": time_s, "label": label, "ringtone": ringtone,
                                    "enabled": enabled, "repeat": repeat,
                                    "snooze_min": snooze_min})
        if na is None:
            return None, err
        if len(self._alarms) >= ALARMS_MAX:
            return None, "闹钟太多了，先删几个吧（最多 %d 个）" % ALARMS_MAX
        aid = uuid.uuid4().hex[:8]
        while aid in self._alarms:
            aid = uuid.uuid4().hex[:8]
        na["id"] = aid
        self._alarms[aid] = na
        self._save()
        return dict(na), ""

    def update(self, aid, time_s=None, label=None, enabled=None, ringtone=None):
        """更新字段（None=不动）；返回 (ok, err)。"""
        a = self._alarms.get(str(aid or ""))
        if a is None:
            return False, "闹钟不存在"
        if time_s is not None:
            t = normalize_time(time_s)
            if not t:
                return False, "时间格式应为 HH:MM"
            if t != a.get("time"):
                a["last_fired_date"] = ""  # v2.2（找茬 M2）：改时间=重新武装，当天到点应能再响
            a["time"] = t
        if label is not None:
            a["label"] = str(label).strip()[:ALARM_LABEL_MAX] or "闹钟"
        if enabled is not None:
            if bool(enabled) and not a.get("enabled"):
                a["last_fired_date"] = ""  # v2.2（找茬 M2）：重新启用=重新武装
            a["enabled"] = bool(enabled)
        if ringtone is not None:
            # N1（v2.4.1）：**先校验再赋值**。此前是"先写进内存、校验失败直接 return False"
            # （只跳过 _save）——内存里的闹钟已经被改成非法铃声，之后任何一次成功保存
            # （改别的字段 / mark_fired / 新增闹钟）都会把它写进 alarms.json：
            # 失败路径不但没挡住，反而污染了持久化。
            rt = str(ringtone or "")
            if rt and not rt.lower().endswith(RINGTONE_EXTS):
                return False, "铃声仅支持 wav/mp3"
            a["ringtone"] = rt
        self._save()
        return True, ""

    def delete(self, aid):
        aid = str(aid or "")
        if aid not in self._alarms:
            return False, "闹钟不存在"
        self._alarms.pop(aid, None)
        self._save()
        return True, ""

    def mark_fired(self, aid, today):
        """到点触发后记 last_fired_date（同日不重复响）。"""
        a = self._alarms.get(str(aid or ""))
        if a is None:
            return
        a["last_fired_date"] = str(today or today_str())
        self._save()

    def toggle(self, aid, enabled):
        return self.update(aid, enabled=enabled)

    # ---------- 铃声文件 ----------
    RINGTONE_MAX_BYTES = 20 * 1024 * 1024  # 铃声容量上限（先于任何读取检查，防大文件塞爆目录）

    def ringtone_path(self, filename):
        """铃声绝对路径；空/不存在返回 None。强制 basename（防路径注入）。"""
        if not filename:
            return None
        p = os.path.join(self._dir, os.path.basename(str(filename)))
        return p if os.path.isfile(p) else None

    def import_ringtone(self, src_path):
        """导入铃声（wav/mp3 复制进 alarms/ 目录，换新文件名防覆盖）。
        容量上限先于任何读取（防内存/磁盘 DoS）；分块复制。返回 (filename|None, err)。"""
        if not isinstance(src_path, str) or not os.path.isfile(src_path):
            return None, "音频文件不存在"
        ext = os.path.splitext(src_path)[1].lower()
        if ext not in RINGTONE_EXTS:
            return None, "铃声仅支持 wav/mp3"
        try:
            size = os.path.getsize(src_path)
        except OSError as e:
            return None, "无法读取文件：%s" % e
        if size > self.RINGTONE_MAX_BYTES:
            return None, "铃声太大啦（最多 20MB）"
        try:
            os.makedirs(self._dir, exist_ok=True)
            fn = "%s_r%s%s" % (uuid.uuid4().hex[:8], uuid.uuid4().hex[:6], ext)
            with open(src_path, "rb") as src, open(os.path.join(self._dir, fn), "wb") as dst:
                while True:
                    chunk = src.read(1024 * 1024)  # 1MB 分块，避免整文件进内存
                    if not chunk:
                        break
                    dst.write(chunk)
            return fn, ""
        except Exception as e:
            return None, "铃声导入失败：%s" % e  # 有意忽略：复制失败明确报错（不静默）


if __name__ == "__main__":
    # 命令行冒烟：无 GUI 自检（python pet_alarm.py）
    import tempfile
    _svc = AlarmService(tempfile.mkdtemp(prefix="alm_"))
    _a, _e = _svc.add("07:30", "起床")
    assert _a is not None and not _e, _e
    assert valid_time("07:30") and valid_time("23:59") and not valid_time("24:00")
    assert valid_time("00:00") and not valid_time("7:5")  # valid_time 仍是严格 HH:MM
    assert normalize_time("07:05") == "07:05"
    # v2.3.1（P1-1）：normalize_time 宽松补零（历史数据挽回），严格正则仍是最终判据
    assert normalize_time("7:5") == "07:05" and normalize_time("8:0") == "08:00"
    assert normalize_time("07:30:00") == "07:30"
    assert normalize_time("24:00") == "" and normalize_time("abc") == "" and normalize_time("7") == ""
    _due = due_alarms(_svc.list(), "07:31", "2026-09-30")
    assert len(_due) == 1
    _svc.mark_fired(_a["id"], "2026-09-30")
    assert due_alarms(_svc.list(), "07:31", "2026-09-30") == []  # 当日不重复响
    assert due_alarms(_svc.list(), "07:31", "2026-10-01")  # 跨天重新待命
    assert _svc.delete(_a["id"]) == (True, "")
    print("SMOKE OK")

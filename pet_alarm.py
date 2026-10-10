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


def due_alarms(alarms, now, today):
    """到点判定（纯函数）：返回 [(alarm, normalized_time), ...]。

    now="HH:MM"（须两位补零，生产侧 now_hhmm() 保证）、today="YYYY-MM-DD"；
    enabled 且 now >= time 且当日未触发 → 到点。
    """
    out = []
    for a in alarms:
        if not isinstance(a, dict) or not a.get("enabled"):
            continue
        t = normalize_time(a.get("time", ""))
        if not t:
            continue
        if a.get("last_fired_date") == today:
            continue
        if now >= t:
            out.append((a, t))
    return out


class AlarmService:
    """闹钟库：alarms.json 持久化 + 增删改查 + 铃声导入/清除。主线程调用。"""

    def __init__(self, data_dir, log=None):
        self._dir = os.path.join(data_dir, "alarms")
        self._index = os.path.join(data_dir, "alarms.json")
        self._log = log or pet_log.log_error
        self._alarms = {}  # {id: alarm}
        self._load()

    # ---------- 持久化 ----------
    def _load(self):
        """读闹钟库并归一化；**清洗过就回写愈合**（P0-2）。

        此前把坏条目从内存丢掉却不落盘：坏数据留在 alarms.json 里，
        每次启动都重报「时间格式应为 HH:MM」（error.log 实测 ×15）。
        现在只要"损坏 / 丢条目 / 归一化确实改了内容"就 _save() 一次，
        下次启动读到的是干净文件，报错不再复发。
        """
        data, corrupted = pet_io.read_json_or(self._index, dict, log=self._log)
        self._alarms = {}
        dirty = corrupted   # 文件本身坏了：读完立刻用合法空库覆盖
        if isinstance(data, dict):
            raw = data.get("alarms")
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
                elif na["id"] not in self._alarms:
                    self._alarms[na["id"]] = na
                    if na != a:
                        dirty = True   # 补零/清洗（如 "7:5"→"07:05"）也要落盘，避免每次启动重做
                else:
                    self._log("alarm index dropped duplicate id: %s" % na["id"])
                    dirty = True
        if dirty:
            self._save()   # 愈合回写（走 pet_io 的同一把路径锁，与在途写者串行）

    def _save(self):
        err = pet_io.atomic_write_json(self._index, {"alarms": list(self._alarms.values())},
                                       log=self._log)
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
            a["ringtone"] = str(ringtone or "")
            if a["ringtone"] and not a["ringtone"].lower().endswith(RINGTONE_EXTS):
                return False, "铃声仅支持 wav/mp3"
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

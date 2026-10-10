# -*- coding: utf-8 -*-
"""
大肥鱼桌宠 · 角色导出/导入（v2.0.3）
MIT License

职责：把「角色（含全部素材文件）+ 行为库 + 可分享配置（语音开关/音效组/气泡样式/
自定义台词/待机行为选择）」打包成单个 .dfypet.zip 分享文件；导入侧解包、
校验素材完整性、生成新 id 防覆盖、缺资源明确报错。纯逻辑、Qt-free，可无 GUI 单测。

敏感内容默认不导出：config 只取白名单键（api_key 等密钥一律排除，manifest 里
记录被排除的键名）；语音只导出开关/合成参数，不导出用户音频片段文件。

包结构：
  manifest.json  {"format":"dfypet-role","version":1,"role":{...},"behaviors":[...],
                  "config":{...},"excluded":["api_key",...],"alarms":[闹钟设置]}
  roles/<文件名>  角色引用的全部 png（manifest.role 内以文件名引用）

闹钟设置（系统⑥）v2.0.5 已启用：manifest.alarms 携带闹钟列表
（铃声文件不随包，导入侧换默认提示音并明确警告）；缺失/未知字段宽容处理。
"""

import itertools
import json
import os
import shutil
import tempfile
import threading
import time
import uuid
import zipfile

BUNDLE_FORMAT = "dfypet-role"
BUNDLE_VERSION = 1
MANIFEST_NAME = "manifest.json"

# v2.4.2（兼容 M1）：临时文件名的**进程内序号**。原先只有线程号：同一线程连续两次导出
# （或调用方绕过重入守卫）两个 BundleWriter 的 tmp 名逐字相同，交错写同一个文件 → 先收尾
# 的那个报 WinError 32、后收尾的靠自校验侥幸救回。加序号后每个写者的 tmp 都是私有的。
_TMP_SEQ = itertools.count(1)

# 包容量上限（导出/校验同口径单一来源）：放宽到合法大角色必然往返成功
# （role_frame_max 可调至 60 帧 × 8 形态 × 多动作 + 各形态 side/front/states）
EXPORT_MAX_ENTRIES = 2000
EXPORT_MAX_BYTES = 512 * 1024 * 1024

# v2.4.2（兼容 M2）：单个大条目（参考音可以几十 MB）必须能**跨片**写。
# 旧实现是"写完一条才检查预算"——13 条里放一个 24MB 不可压缩成员，实测每片
# [20.7, 23.3, 21.7, 822.9, 13.5, …] ms：那条大成员独占一片 822.9ms（12ms 预算的 68 倍），
# 慢盘/网络盘还会等比放大，"导出不再卡"在这条路径上不成立。
# 现在：≥ 门槛的条目走 zf.open(arc, "w") 分块续写（块与块之间回事件循环），低于门槛的
# 一条就是一次 zf.write（最坏 ≈10ms 量级）。产出**逐位不变**：同一份 ZipInfo.from_file +
# 同一个压缩级别，只是数据分几次喂给同一个 deflate 流（zlib 的输出与喂入块大小无关）。
_BIG_ENTRY_MIN_BYTES = 256 * 1024       # 分块写的门槛
_BIG_ENTRY_CHUNK_BYTES = 256 * 1024     # 单次 write 的块大小（不可压缩实测 ≈7~9ms/块）

# 可分享配置键白名单（导出/导入共用；api_key 等敏感键永不在此列）
EXPORT_CONFIG_KEYS = ("voice", "sound_group", "bubble_style", "lines_extra", "idle_behavior",
                      # v2.1：待机系统（两触发/待机形态/待机动作列表/播放模式）
                      "idle_trigger_delay", "idle_delay_after_full", "idle_form",
                      "idle_actions", "idle_play_mode", "idle_resume_on_interrupt")

# v2.1：voice 配置里必须剥掉的敏感子键（导出包不得带密钥）
VOICE_SECRET_KEYS = ("backend_keys",)
# 敏感键：默认不导出（manifest.excluded 记录，导入侧自然缺省）
SENSITIVE_KEYS = ("api_key",)


def _role_file_refs(role):
    """角色 dict 引用的全部相对文件名（file/file_full/顶层 frames 兼容视图/
    forms 的 file·front·animations 各动作帧·states 状态图），去重排序。

    与 RoleLibrary._role_paths 同口径 + 顶层 frames（第三方旧格式包兼容）；
    非字符串值（坏数据）一律跳过，防逐字符/整 list 冒充文件名造成乱码报错。"""
    names = []
    for v in (role.get("file"), role.get("file_full")):
        if isinstance(v, str) and v:
            names.append(v)
    if isinstance(role.get("frames"), list):
        names.extend(x for x in role["frames"] if isinstance(x, str))
    for fm in role.get("forms") or []:
        if not isinstance(fm, dict):
            continue
        for v in (fm.get("file"), fm.get("front")):
            if isinstance(v, str) and v:
                names.append(v)
        anims = fm.get("animations")
        if isinstance(anims, dict):
            for act in anims:
                lst = anims.get(act)
                if isinstance(lst, list):
                    names.extend(x for x in lst if isinstance(x, str))
        states = fm.get("states")
        if isinstance(states, dict):
            names.extend(v for v in states.values() if isinstance(v, str))
    return sorted(set(names))


def _remap_role_files(role, name_map):
    """把 role dict 里的全部文件名按 name_map 换成新名（导入防同名覆盖）。"""
    def _map(v):
        return name_map.get(str(v), str(v))
    out = dict(role)
    if out.get("file"):
        out["file"] = _map(out["file"])
    if out.get("file_full"):
        out["file_full"] = _map(out["file_full"])
    if isinstance(out.get("frames"), list):
        out["frames"] = [_map(x) for x in out["frames"] if isinstance(x, str)]
    forms = []
    for fm in out.get("forms") or []:
        if not isinstance(fm, dict):
            forms.append(fm)
            continue
        f2 = dict(fm)
        if f2.get("file"):
            f2["file"] = _map(f2["file"])
        if f2.get("front"):
            f2["front"] = _map(f2["front"])
        if isinstance(f2.get("animations"), dict):
            f2["animations"] = {a: [_map(x) for x in lst] if isinstance(lst, list) else lst
                                for a, lst in f2["animations"].items()}
        if isinstance(f2.get("states"), dict):
            f2["states"] = {s: _map(p) if isinstance(p, str) else p
                            for s, p in f2["states"].items()}
        forms.append(f2)
    if forms:
        out["forms"] = forms
    return out


def _scrub_config(config):
    """剥掉嵌套敏感子键与 URL 内嵌凭据（导出包不得携带任何密钥）。

    - voice.backend_keys：各家克隆后端的 API Key
    - base_url 里的 query 串：形如 https://x?key=xxx / &token=xxx 的内嵌凭据（L10）
    """
    out = dict(config or {})
    v = out.get("voice")
    if isinstance(v, dict):
        v = dict(v)
        for k in VOICE_SECRET_KEYS:
            v.pop(k, None)
        params = v.get("backend_params")
        if isinstance(params, dict):
            params = dict(params)
            for bid, sub in list(params.items()):
                if isinstance(sub, dict) and isinstance(sub.get("base_url"), str):
                    sub = dict(sub)
                    sub["base_url"] = _strip_url_creds(sub["base_url"])
                    params[bid] = sub
            v["backend_params"] = params
        out["voice"] = v
    return out


def _strip_url_creds(url):
    """去掉 URL query 里的凭据参数（key/token/secret/access_key 等），保留其余部分。"""
    u = str(url or "")
    if "?" not in u:
        return u
    base, _q, query = u.partition("?")
    keep = []
    for part in query.split("&"):
        name = part.split("=", 1)[0].strip().lower()
        if name in ("key", "api_key", "apikey", "token", "access_token", "secret",
                    "access_key", "sk"):
            continue
        if part:
            keep.append(part)
    return base + (("?" + "&".join(keep)) if keep else "")


def build_manifest(role, behaviors, cfg, alarms=None, lines=None, dialogues=None,
                   voice_assets=None, meta=None):
    """构造导出 manifest。返回 (manifest, err)；角色缺文件引用报错。

    role=role_lib.get(rid)；behaviors=行为 dict 列表；cfg=当前配置 dict；
    alarms=闹钟 dict 列表（v2.0.5）；lines/dialogues=台词与对白（v2.1）；
    voice_assets=随包的声音素材元数据（v2.1，默认 None=不带参考音文件）。
    """
    if not isinstance(role, dict) or not role.get("id"):
        return None, "角色不存在或数据为空"
    config = {}
    for k in EXPORT_CONFIG_KEYS:
        if k in cfg:
            config[k] = cfg[k]
    config = _scrub_config(config)
    manifest = {
        "format": BUNDLE_FORMAT,
        "version": BUNDLE_VERSION,
        # v2.3.0：角色包"身份证"（作者/简介/标签/许可…）——纯展示信息，
        # **不参与校验**：缺 meta 的旧包照常导入，未知键原样透传不丢。
        "meta": dict(meta) if isinstance(meta, dict) else {},
        "role": dict(role),
        "behaviors": [dict(b) for b in (behaviors or []) if isinstance(b, dict)],
        "config": config,
        # 记录本次实际被排除的敏感键（cfg 里存在的那些；白名单才是真防线）
        "excluded": [k for k in SENSITIVE_KEYS if k in cfg]
                    + (["voice." + k for k in VOICE_SECRET_KEYS
                        if isinstance(cfg.get("voice"), dict) and k in cfg["voice"]]),
        # v2.0.5：闹钟设置（铃声文件不随包，导入侧明确提示换默认音）
        "alarms": list(alarms) if isinstance(alarms, list) else None,
        # v2.1：台词 / 对白 /（可选）声音素材。L8 修复：非 dict 元素过滤掉（与 behaviors 同口径），
        # 否则伪造/坏数据会在导出时抛 TypeError（只能看到笼统的"导出失败"）。
        "lines": [dict(x) for x in lines if isinstance(x, dict)] if isinstance(lines, list) else None,
        "dialogues": [dict(x) for x in dialogues if isinstance(x, dict)]
        if isinstance(dialogues, list) else None,
        "voice_assets": [dict(x) for x in voice_assets if isinstance(x, dict)]
        if isinstance(voice_assets, list) else None,
    }
    return manifest, ""


def plan_bundle(role_lib, behaviors_svc, cfg, alarms_getter=None,
                lines_getter=None, dialogues_getter=None,
                voice_assets_getter=None, include_voice_ids=None, meta=None):
    """**收集阶段**（两段式导出 API 的第一段）：算出要写进包里的全部东西，不写盘。

    返回 (plan, err)。plan = {"manifest": dict, "entries": [(arcname, 绝对源路径), ...]}，
    条目顺序与旧版 export_bundle 逐位相同：manifest.json（单独写）→ roles/<文件名>
    （= _role_file_refs 的顺序）→ voice_ref/<id><ext>（= 勾选顺序）。

    为什么拆开：导出一个 20~60 帧的角色要 125~205 ms，全压在主线程同步跑（zipfile 长
    循环 + zlib 压缩），导出期间桌宠整个假死。收集阶段只做 stat/manifest（实测 ≈1 ms），
    真正占时间的是逐条写盘——那一段交给 BundleWriter 分片（见其文档）。
    错误文案与旧版 export_bundle 逐字相同（调用方与测试依赖这些字面量）。
    """
    rid = str((cfg or {}).get("role") or "")
    role = role_lib.get(rid) if rid else None
    if role is None:
        return None, "请先在「角色」面板选择一个自定义角色再导出"
    try:
        entries = []
        for ref in _role_file_refs(role):
            if ref != os.path.basename(ref):
                # 引用含路径分隔符 = 角色数据异常（正常管线不产生），拒绝自产坏包
                return None, "角色数据异常：引用含路径「%s」，请重新导入该角色" % ref
            p = role_lib.resolve(ref)
            if not os.path.isfile(p):
                return None, "角色素材缺失，无法导出：%s" % ref
            entries.append(("roles/" + os.path.basename(ref), p))
        _behaviors = behaviors_svc.list() if behaviors_svc is not None else []
        _alarms = alarms_getter() if alarms_getter is not None else None
        _lines = lines_getter() if lines_getter is not None else None
        _dlgs = dialogues_getter() if dialogues_getter is not None else None
        # v2.1：参考音默认不打包；勾选（include_voice_ids）才带文件
        _vmeta, _vfiles = None, []
        if voice_assets_getter is not None and include_voice_ids:
            _want = {str(x) for x in include_voice_ids}
            for a in (voice_assets_getter() or []):
                if str(a.get("id")) not in _want:
                    continue
                _p = a.get("path")
                if not _p or not os.path.isfile(_p):
                    return None, "声音素材文件缺失，无法导出：%s" % a.get("name", a.get("id"))
                _ext = os.path.splitext(_p)[1].lower()
                _vmeta = (_vmeta or [])
                _vmeta.append({"id": str(a.get("id")), "name": str(a.get("name") or ""),
                               "ext": _ext, "file": "voice_ref/%s%s" % (a.get("id"), _ext)})
                _vfiles.append(("voice_ref/%s%s" % (a.get("id"), _ext), _p))
        meta = meta or {}  # v2.3.0：角色信息（作者/简介/标签），由导出对话框收集
        manifest, err = build_manifest(role, _behaviors, cfg or {}, _alarms, _lines, _dlgs,
                                       _vmeta, meta)
        if manifest is None:
            return None, err
        return {"manifest": manifest, "entries": entries + _vfiles}, ""
    except Exception as e:
        return None, "导出失败：%s" % e


class BundleWriter(object):
    """**逐条写阶段**（两段式导出 API 的第二段）：把 plan 写成分片可续的 zip。

    为什么不减少工作总量也能救场：导出 125~205 ms 是**主线程上的连续阻塞**，窗口在这
    期间一次事件循环都不转（用户看到假死）。分片把这段连续阻塞切成"若干次 ≤budget_ms
    的小阻塞"，每次之间事件循环照常转（窗口能重绘、能响应），总 CPU 工作量不变。

    产出与"一口气写完"**逐条目相同**：同一个 plan、同一套 zipfile 调用、同一个压缩
    级别与条目顺序，差别只在"每次写几条"。用法::

        plan, err = plan_bundle(...)
        w = BundleWriter(plan, out_path)
        while not w.done:
            w.step(budget_ms=12.0)      # 一小片
            QApplication.processEvents()  # 或 QTimer(0) 接力
        ok, err = w.finish()            # 关包 + 原子替换 + 自校验

    不分片（budget_ms=None）时行为与旧版 export_bundle 的写盘段逐位相同。
    """

    def __init__(self, plan, out_path, compresslevel=None):
        self.plan = plan
        self.out_path = out_path
        self.compresslevel = compresslevel
        self.entries = list((plan or {}).get("entries") or [])
        # v2.3.1（同类遗留）：线程唯一临时名，避免与其它写者抢同一个 .tmp
        # v2.4.2（兼容 M1）：再加**进程内序号**——同一线程连续两次导出时，只有线程号会撞名，
        # 两个写者交错写同一个 tmp，先收尾的 finish() 直接 WinError 32。
        self.tmp = "%s.%d.%d.tmp" % (out_path, threading.get_ident(), next(_TMP_SEQ))
        self.written = 0
        self.total = len(self.entries)
        self.done = False
        self.error = None
        self._zf = None
        # v2.4.2（兼容 M2）：在途的大条目（跨片续写）。None = 当前没有半途的条目。
        self._big = None          # zipfile 的写入句柄（_ZipWriteFile）
        self._big_src = None      # 对应的源文件句柄

    # ---- 内部 ----
    def _open(self):
        if self._zf is None:
            self._zf = zipfile.ZipFile(self.tmp, "w", zipfile.ZIP_DEFLATED,
                                       compresslevel=self.compresslevel)
            # v2.4.3（第三轮找茬复审 M5）：manifest 条目的时间戳**必须确定**——此前走
            # writestr(str)，它按 time.localtime(time.time()) 取当前时钟，于是同一个 plan
            # 隔 2 秒再导出就逐字节不同（差异只在两处 DOS 时间字段），"导出逐位不变"的结论
            # 跨 2 秒即失效，整包字节比较的用例也变成偶发红。
            # 固定成 zip 的 DOS 时间原点 1980-01-01；其余属性手工对齐 writestr(str) 分支
            # （compress_type/_compresslevel/external_attr）——数据条目走
            # ZipInfo.from_file，用源文件 mtime，本来就是确定的。
            _zi = zipfile.ZipInfo(MANIFEST_NAME, date_time=(1980, 1, 1, 0, 0, 0))
            _zi.compress_type = self._zf.compression
            _zi._compresslevel = self._zf.compresslevel
            _zi.external_attr = 0o600 << 16
            self._zf.writestr(_zi,
                              json.dumps(self.plan["manifest"], ensure_ascii=False, indent=2))

    def _cleanup_tmp(self):
        try:
            self._big_close()   # 先放在途条目句柄：_ZipWriteFile.close 要回填本地文件头，
        except Exception:       # _zf 先关掉它就会抛 AttributeError（见 zipfile 的实现）
            self._big, self._big_src = None, None   # 有意忽略：清理路径尽力而为
        try:
            if self._zf is not None:
                self._zf.close()
                self._zf = None
        except Exception:
            pass  # 有意忽略：关包失败也要继续清残留
        try:
            if os.path.isfile(self.tmp):
                os.remove(self.tmp)
        except Exception:
            pass  # 有意忽略：残留临时文件清理尽力而为

    # ---- 大条目（跨片续写）----
    def _big_begin(self, arc, src):
        """开一个在途的大条目：ZipInfo 与 zf.write(src, arc) 用的**逐位相同**。

        zipfile.ZipFile.write 的实现就是 ZipInfo.from_file(...) + open(zinfo, "w") 再
        shutil.copyfileobj；这里照抄前半段（含压缩级别与 strict_timestamps），只是把数据
        改成自己分块喂——同一个 deflate 流、同一批字节，压缩输出与喂入块大小无关。
        （_dev 实测：同一条目走这两条路写出的整包字节完全相同，sha256 相等。）
        """
        src_f = open(src, "rb")
        try:
            zinfo = zipfile.ZipInfo.from_file(src, arc)
            zinfo.compress_type = self._zf.compression
            # v2.4.3（第三轮找茬 P3-3）：_compresslevel 是 CPython zipfile 的**私有**属性，
            # 不是公开 API——这里有意照抄 zipfile.ZipFile.write() 的实现（同一行就是
            # "zinfo._compresslevel = self.compresslevel"）。不设它，zf.open(zinfo, "w")
            # 会用 ZipInfo 自己的默认级别（None → zlib 默认 6），产出字节与 zf.write()
            # 不再逐位相同（_dev 实测 sha256 相等的那条结论即失效）。
            # 依赖的 CPython：3.10.2（绿色版实测）～3.12，ZipInfo.__init__ 都不设该属性，
            # 只有 ZipFile.write/_open_to_write 这条路径会读它（_get_compressor 取级别）。
            # Python 升级后若改名/改语义，tests/test_round3_a_fixes.py 里
            # test_zipinfo_compresslevel_is_still_consumed 会立刻变红（它用"换压缩级别
            # 必须换产出字节"反证该属性真被消费），不会静默退化。
            zinfo._compresslevel = self._zf.compresslevel
            self._big_src = src_f
            self._big = self._zf.open(zinfo, "w")
        except Exception:
            src_f.close()
            self._big, self._big_src = None, None
            raise

    def _big_write_some(self):
        """给在途的大条目写一块；返回 True = 这条写完了（句柄已关）。

        一次只写一块（_BIG_ENTRY_CHUNK_BYTES）：单片阻塞 ≈ 压缩一块的时间，与 budget_ms
        同一个量级；写完一块就回到 step 的预算检查，超预算就留着句柄下一片接着写。
        """
        chunk = self._big_src.read(_BIG_ENTRY_CHUNK_BYTES)
        if chunk:
            self._big.write(chunk)
            return False
        self._big_close()
        return True

    def _big_close(self):
        """收尾在途的大条目：关数据句柄（回填文件头里的 CRC/长度）+ 关源文件句柄。

        先赋值再关：关闭过程中抛异常也不会留下"以为还开着"的脏状态。
        """
        handle, self._big = self._big, None
        src_f, self._big_src = self._big_src, None
        try:
            if handle is not None:
                handle.close()
        finally:
            if src_f is not None:
                src_f.close()

    # ---- 分片驱动 ----
    def step(self, budget_ms=None):
        """写一小片：最多花 budget_ms 毫秒（None = 一次把剩余条目全写完）。

        返回已写条目数。写盘异常不抛出：记进 self.error 并把 done 置真，
        由 finish() 统一转成旧版的"写入失败：…"文案。

        v2.4.2（兼容 M2）：预算检查落在**块**粒度上——小条目一条 = 一块，大条目一条 =
        若干块（见 _big_begin/_big_write_some）。所以单片阻塞 = max(一块的耗时, 小条目一条)，
        而不是"一条大成员的全部耗时"（24MB 不可压缩成员实测 822.9ms）。
        """
        if self.done:
            return self.written
        try:
            self._open()
            t0 = time.perf_counter()
            while self.written < self.total:
                if self._big is not None:
                    # 在途的大条目：续写一块（写完这一条才 +1，见 _big_write_some）
                    if self._big_write_some():
                        self.written += 1
                else:
                    arc, src = self.entries[self.written]
                    if budget_ms is None or os.path.getsize(src) < _BIG_ENTRY_MIN_BYTES:
                        # 小条目（或调用方要一口气写完）：与旧版逐位相同的写法
                        self._zf.write(src, arc)
                        self.written += 1
                    else:
                        self._big_begin(arc, src)   # 大条目：开句柄，下一轮起分块续写
                        continue                    # 开句柄本身很便宜，不占预算检查
                if budget_ms is not None and (time.perf_counter() - t0) * 1000.0 >= budget_ms:
                    break
            if self.written >= self.total:
                self.done = True
        except Exception as e:
            self.error = e
            self.done = True
        return self.written

    def abort(self):
        """放弃本次写包：关包 + 删掉半截临时文件。

        正式输出文件从没被碰过（原子替换还没发生），所以"中途放弃"不留下坏包；
        典型触发场景是窗口正在退出（桌宠._export_step 见 _closing 即放弃）。
        """
        self._cleanup_tmp()
        self.done = True

    def finish(self):
        """收尾：关包 → 原子替换 → 自校验。返回 (ok, err)，文案与旧版逐字相同。"""
        if not self.done:
            self.step(budget_ms=None)
        if self.error is not None:
            err = self.error
            self._cleanup_tmp()
            return False, "写入失败：%s" % err
        if self._zf is None:
            # v2.4.2（兼容 L6）：abort() 之后再 finish()（或压根没开过包）——此前这里吐的是
            # 内部错误 "NoneType object has no attribute close"（用户看到的是解释器细节）；
            # 语义上"这次导出已经作废、正式文件从没被碰过"，给一句体面文案。
            return False, "导出已取消"
        try:
            self._zf.close()
            self._zf = None
            os.replace(self.tmp, self.out_path)  # 原子替换：半截包不会被当作有效文件
        except Exception as e:
            self._cleanup_tmp()
            return False, "写入失败：%s" % e
        # 导出侧自校验：容量上限同口径，导出时即报错而不是让接收方导入才踩坑
        _m, _err = validate_bundle(self.out_path)
        if _m is None:
            try:
                os.remove(self.out_path)
            except Exception:
                pass  # 有意忽略：自校验失败包的清理尽力而为
            return False, "导出包自校验失败：%s" % _err
        return True, ""


def export_bundle(role_lib, behaviors_svc, cfg, out_path, alarms_getter=None,
                  lines_getter=None, dialogues_getter=None,
                  voice_assets_getter=None, include_voice_ids=None, meta=None):
    """导出角色包到 out_path（zip）。返回 (ok, err)。**旧签名保留为薄壳**。

    v2.4.2：本体拆成 plan_bundle（收集）+ BundleWriter（逐条写）。本薄壳不分片，
    行为与拆分前逐位相同（同一批条目、同一顺序、同一压缩级别、同一批错误文案）；
    要"不卡主线程"的调用方（桌宠._export_role）自己拿这两段分片驱动。

    收集 role_lib 当前角色的全部素材文件进 roles/ 子目录；缺文件明确报错。
    alarms_getter（可选）：闹钟设置（不含铃声文件）。
    lines_getter/dialogues_getter（可选）：台词与对白（v2.1，随包分享）。
    voice_assets_getter（可选）+ include_voice_ids（勾选的素材 id）：
        把参考音文件打进 voice_ref/（**默认不打包**，体积与隐私考虑，用户勾选才带）。
    """
    plan, err = plan_bundle(role_lib, behaviors_svc, cfg,
                            alarms_getter=alarms_getter, lines_getter=lines_getter,
                            dialogues_getter=dialogues_getter,
                            voice_assets_getter=voice_assets_getter,
                            include_voice_ids=include_voice_ids, meta=meta)
    if plan is None:
        return False, err
    w = BundleWriter(plan, out_path)
    w.step()          # budget_ms=None：一口气写完 = 旧行为
    return w.finish()


def validate_bundle(zip_path):
    """校验角色包结构与素材完整性。返回 (manifest, err)。"""
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            # 恶意包防御：条目数/解压总量上限（防 zip 炸弹）——先于任何解压读取
            info = zf.infolist()
            if len(info) > EXPORT_MAX_ENTRIES or sum(i.file_size for i in info) > EXPORT_MAX_BYTES:
                return None, "角色包条目过多或体积过大，已拒绝"
            try:
                manifest = json.loads(zf.read(MANIFEST_NAME).decode("utf-8"))
            except KeyError:
                return None, "不是角色包：缺少 manifest.json"
            except Exception as e:
                return None, "manifest.json 无法解析：%s" % e
            if not isinstance(manifest, dict):
                return None, "manifest 不是对象"
            if manifest.get("format") != BUNDLE_FORMAT:
                return None, "不是大肥鱼角色包（format=%r）" % manifest.get("format")
            role = manifest.get("role")
            if not isinstance(role, dict) or not role.get("file"):
                return None, "角色包缺少角色数据"
            # 坏结构明确报错：id 必须为非空字符串（缺失/数字 id 会产出幽灵角色）
            if not isinstance(role.get("id"), str) or not role.get("id", "").strip():
                return None, "角色包缺少角色 id"
            names = zf.namelist()
            missing = []
            for ref in _role_file_refs(role):
                if ref != os.path.basename(ref):
                    # 非法引用（含路径分隔符/上级目录）：直接拒绝，不做 basename 归一
                    return None, "角色包引用非法文件名：%s" % ref
                if "roles/" + ref not in names:
                    missing.append(ref)
            if missing:
                return None, "角色包素材缺失：%s" % "、".join(missing[:5])
            return manifest, ""
    except zipfile.BadZipFile:
        return None, "文件不是有效的 zip 包"
    except Exception as e:
        return None, "打开失败：%s" % e


def import_bundle(role_lib, behaviors_svc, cfg, zip_path, alarms_apply=None,
                  voice_apply=None, lines_apply=None):
    """导入角色包：解包素材（换新文件名防覆盖）、注册角色与行为（新 id）、
    应用可分享配置与闹钟设置。返回 (result|None, err)；任何缺资源/坏结构明确报错。

    alarms_apply（可选）：接收包内闹钟设置列表、返回警告列表的回调。
    voice_apply（可选）：接收（声音素材列表, 解包目录）、返回 {旧槽位: 新槽位} 映射的回调。
    lines_apply（可选）：接收（台词列表, 对白列表, 映射表）、返回警告列表的回调；
        映射表 = {"voice": 旧→新声音槽位, "role": 旧→新角色 id}。
    result = {"role_id", "behavior_map": {旧id: 新id}, "warnings": [...]}
    """
    manifest, err = validate_bundle(zip_path)
    if manifest is None:
        return None, err
    warnings = []
    written = []          # 本次已解包的文件（异常时回滚）
    role_appended = False
    role_map = {}         # v2.1：旧角色 id → 新角色 id（绑定/台词引用重映射用）
    extract_dir = None    # v2.1：随包声音素材的临时解包目录（用完即删）
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            role = dict(manifest["role"])
            _old_rid = str(role.get("id") or "")
            # 素材换新文件名（防与现有角色文件同名覆盖），并重写全部引用
            name_map = {}
            for ref in _role_file_refs(role):
                new_name = "%s_i%s.png" % (uuid.uuid4().hex[:8], uuid.uuid4().hex[:6])
                src = zf.read("roles/" + os.path.basename(ref))
                dst = role_lib.resolve(new_name)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                with open(dst, "wb") as f:
                    f.write(src)
                name_map[ref] = new_name
                written.append(dst)
            role = _remap_role_files(role, name_map)
            # 行为：全部换新 id 导入，记录旧→新映射（供 idle_behavior 重映射）
            # 恶意/坏结构防御：behaviors 非列表或条目非对象 → 跳过并记警告，不崩
            behavior_map = {}
            _bhvs = manifest.get("behaviors")
            if not isinstance(_bhvs, list):
                warnings.append("包内行为数据格式非法，已跳过")
                _bhvs = []
            for b in _bhvs:
                if not isinstance(b, dict):
                    warnings.append("跳过非法行为条目")
                    continue
                nb, berr = behaviors_svc.add(str(b.get("name") or "imported"),
                                             b.get("steps"))
                if nb is not None:
                    behavior_map[str(b.get("id") or "")] = nb["id"]
                else:
                    warnings.append("行为「%s」未导入：%s" % (b.get("name"), berr))
            # 应用可分享配置（白名单键；idle_behavior 经映射重指；
            # 坏值跳过并记警告——伪造包不得污染运行配置）
            # S1 修复：导出包**不含**密钥，导入时若整段覆盖会把用户自己的 Key 清掉 →
            # 先把本地 backend_keys 备份出来，应用配置后回填。
            _local_keys = {}
            try:
                _lv = (cfg or {}).get("voice") or {}
                if isinstance(_lv.get("backend_keys"), dict):
                    _local_keys = dict(_lv["backend_keys"])
            except Exception:
                _local_keys = {}  # 有意忽略：拿不到就当作没有本地密钥
            _cfg = manifest.get("config") or {}
            if "idle_behavior" in _cfg:
                if not isinstance(_cfg["idle_behavior"], str):
                    warnings.append("包内待机行为配置非法，已跳过")
                    _cfg.pop("idle_behavior", None)
                else:
                    _old = str(_cfg["idle_behavior"] or "")
                    _cfg["idle_behavior"] = behavior_map.get(_old, "")
                    if _old and not _cfg["idle_behavior"]:
                        warnings.append("待机行为不在包内，已置为不启用")
            # v2.1：待机动作列表里的行为 id 要按映射重指；失效的行为条目丢弃并提示
            if "idle_actions" in _cfg:
                _ia = _cfg.get("idle_actions")
                if not isinstance(_ia, list):
                    warnings.append("包内待机动作列表非法，已跳过")
                    _cfg.pop("idle_actions", None)
                else:
                    _kept = []
                    for _a in _ia:
                        if not isinstance(_a, dict):
                            continue
                        _old_b = str(_a.get("behavior_id") or "")
                        _new_b = behavior_map.get(_old_b)
                        if not _new_b:
                            continue
                        _kept.append({"id": _new_b, "behavior_id": _new_b,
                                      "enabled": _a.get("enabled") is not False,
                                      "weight": _a.get("weight", 1.0),
                                      "order": _a.get("order", len(_kept) + 1)})
                    if len(_kept) != len(_ia):
                        warnings.append("待机列表里有行为不在包内，已跳过")
                    _cfg["idle_actions"] = _kept
            # 待机形态属于具体角色：导入包里的形态键可能不存在，交给用户重选
            if _cfg.get("idle_form"):
                warnings.append("待机形态沿用包内设置（%s），若当前角色没有该形态会自动忽略"
                                % _cfg["idle_form"])
            for k in ("voice", "bubble_style", "lines_extra"):
                if k in _cfg and not isinstance(_cfg[k], dict):
                    warnings.append("包内「%s」配置格式非法，已跳过" % k)
                    _cfg.pop(k, None)
            if "sound_group" in _cfg and _cfg["sound_group"] not in ("default", "custom"):
                warnings.append("包内音效组配置非法，已跳过")
                _cfg.pop("sound_group", None)
            for k in EXPORT_CONFIG_KEYS:
                if k not in _cfg:
                    continue
                if k == "voice":
                    # L7 修复：别人的后端/地址不该替换本机已配置的（只补空缺），否则导入一个包
                    # 就把本地配音设置顶掉。声音绑定另行处理（已在上面按映射重指/清理）。
                    _local = dict(cfg.get("voice") or {})
                    _incoming = dict(_cfg["voice"]) if isinstance(_cfg["voice"], dict) else {}
                    _merged = dict(_incoming)
                    for _key in ("backend", "backend_params", "backend_keys"):
                        if _local.get(_key) and not _incoming.get(_key):
                            _merged[_key] = _local[_key]
                    if _local.get("backend") and _incoming.get("backend") \
                            and _local["backend"] != _incoming["backend"]:
                        warnings.append("包里的配音后端与本机不同，仍用本机的（%s）"
                                        % _local["backend"])
                        _merged["backend"] = _local["backend"]
                        _merged["backend_params"] = _local.get("backend_params") or {}
                    cfg["voice"] = _merged
                    continue
                cfg[k] = _cfg[k]
            # S1 修复：回填本地密钥（包内本来就不带密钥；只补回用户自己没有的后端）
            if _local_keys:
                _v = cfg.setdefault("voice", {})
                _bk = dict(_v.get("backend_keys") or {})
                for _bid, _val in _local_keys.items():
                    if _val and not _bk.get(_bid):
                        _bk[_bid] = _val
                _v["backend_keys"] = _bk
            try:
                _ver = int(manifest.get("version") or BUNDLE_VERSION)
            except (TypeError, ValueError):
                # v2.4.1（B 区 · A 档静默 except 判定）：**误报**——这里只做"能不能比较
                # 版本号"的防御性读取，包里的 version 写坏了就按当前版本处理，最坏是
                # 少弹一句"包版本高于当前支持"的提示；不丢数据、不产生用户可见错误。
                _ver = BUNDLE_VERSION
            if _ver > BUNDLE_VERSION:
                warnings.append("包版本高于当前支持，部分内容可能未生效")
            # v2.1：随包声音素材先解到临时目录（文件读取不受 with 块限制）
            _va = manifest.get("voice_assets")
            if isinstance(_va, list) and _va and voice_apply is not None:
                extract_dir = tempfile.mkdtemp(prefix="dfypet_voice_")
                for a in _va:
                    if not isinstance(a, dict):
                        continue
                    arc = str(a.get("file") or "")
                    if not arc or not arc.startswith("voice_ref/"):
                        continue
                    try:
                        data = zf.read(arc)
                    except KeyError:
                        warnings.append("包内声音素材缺失：%s" % (a.get("name") or a.get("id")))
                        continue
                    with open(os.path.join(extract_dir, os.path.basename(arc)), "wb") as f:
                        f.write(data)
            # 角色最后入库：id 冲突换新（不覆盖现有角色）；写索引失败必须回滚
            if role_lib.get(str(role.get("id") or "")) is not None:
                role["id"] = uuid.uuid4().hex[:8]
            role_map[_old_rid] = role["id"]
            role["added"] = ""
            role_lib._data.setdefault("roles", []).append(role)
            role_appended = True
            _serr = role_lib._save()
            if _serr:
                role_lib._data["roles"] = [x for x in role_lib._data.get("roles", [])
                                           if x is not role]
                role_appended = False
                for p in written:
                    try:
                        if os.path.isfile(p):
                            os.remove(p)
                    except Exception:
                        pass  # 有意忽略：回滚清理尽力而为
                return None, "保存角色失败：%s" % _serr
            # v2.1：先落声音素材（拿到「旧槽位→新槽位」映射），再落台词/对白
            # （台词的声音引用与角色绑定都要按映射改写）；最后才应用闹钟。
            _voice_map = {}
            _va2 = manifest.get("voice_assets")
            if _va2 is not None:
                if not isinstance(_va2, list):
                    warnings.append("包内声音素材格式非法，已跳过")
                elif voice_apply is not None:
                    try:
                        _voice_map = voice_apply(list(_va2), extract_dir) or {}
                    except Exception as e:
                        warnings.append("声音素材应用失败，已跳过：%s" % e)
                else:
                    warnings.append("包内含声音素材，当前版本尚未支持，已忽略")
            # 绑定重映射：包内绑定引用的角色/声音槽位都是旧 id
            _vb = (cfg.get("voice") or {}).get("bindings")
            if isinstance(_vb, dict) and (role_map or _voice_map):
                _new_b = {}
                for _rs, _vs in _vb.items():
                    _nr = role_map.get(str(_rs), str(_rs))
                    _nv = _voice_map.get(str(_vs), str(_vs))
                    if _nv:
                        _new_b[_nr] = _nv
                cfg.setdefault("voice", {})["bindings"] = _new_b
            _lines_in = manifest.get("lines")
            if _lines_in is not None:
                if not isinstance(_lines_in, list):
                    warnings.append("包内台词格式非法，已跳过")
                elif lines_apply is not None:
                    try:
                        warnings.extend(lines_apply(
                            list(_lines_in), manifest.get("dialogues"),
                            {"voice": _voice_map, "role": role_map}) or [])
                    except Exception as e:
                        warnings.append("台词应用失败，已跳过：%s" % e)
                else:
                    warnings.append("包内含台词，当前版本尚未支持，已忽略")
            # 闹钟设置最后应用：角色入库成功才落地（导入事务性）；
            # 应用回调异常转警告，不撤销已成功的角色导入
            _alarms = manifest.get("alarms")
            if _alarms is not None:
                if not isinstance(_alarms, list):
                    warnings.append("包内闹钟设置格式非法，已跳过")
                elif alarms_apply is not None:
                    try:
                        warnings.extend(alarms_apply(list(_alarms)))
                    except Exception as e:
                        warnings.append("闹钟设置应用失败，已跳过：%s" % e)
                else:
                    warnings.append("包内含闹钟设置，当前版本尚未支持，已忽略")
            # v2.3.0：把角色包自带的展示信息带回调用方（"作者/简介"），供导入完成气泡展示；
            # 缺 meta（旧包）→ 空 dict，不报错、不影响导入
            _meta = manifest.get("meta")
            return {"role_id": role["id"], "behavior_map": behavior_map,
                    "voice_map": _voice_map, "warnings": warnings,
                    "meta": dict(_meta) if isinstance(_meta, dict) else {}}, ""
    except Exception as e:
        # 非事务回滚：清理本次已入索引的角色条目与已解包文件（尽力而为）
        if role_appended:
            try:
                role_lib._data["roles"].remove(role)
                role_lib._save()
            except Exception:
                # 有意忽略：回滚保存尽力而为。**最坏后果 = 留一个空角色条目**（索引里有角色、
                # 素材已被下面的 written 循环删掉 → 下次启动看到一个没有素材的形态）。
                # 不引 pet_log 上报是对的取舍：为一个"回滚中的回滚"引入依赖，收益不抵改动面。
                pass
        for p in written:
            try:
                if os.path.isfile(p):
                    os.remove(p)
            except Exception:
                pass  # 有意忽略：回滚清理尽力而为
        return None, "导入失败：%s" % e
    finally:
        if extract_dir:
            shutil.rmtree(extract_dir, ignore_errors=True)  # 随包参考音临时目录用完即删


if __name__ == "__main__":
    # 命令行冒烟：无 GUI 自检（python pet_export.py）
    import tempfile
    _d = tempfile.mkdtemp(prefix="exp_")
    _role = {"id": "r1", "name": "x", "file": "a.png", "form": "single",
             "frames": ["a.png"], "added": ""}
    _m, _e = build_manifest(_role, [], {"api_key": "SECRET", "voice": {"enabled": False},
                                       "bubble_style": {}})
    assert _m is not None and not _e
    # 与 pytest 同口径：敏感值不进包、敏感键不进 config；excluded 记录键名（有意设计）
    assert "SECRET" not in json.dumps(_m)
    assert "api_key" not in _m["config"]
    assert _m["excluded"] == ["api_key"]
    assert "voice" in _m["config"] and "bubble_style" in _m["config"]
    print("SMOKE OK")

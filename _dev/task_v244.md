# v2.4.4 收口任务书（第 1 轮）

仓库：E:\deep seek\desktop-pet。基线 v2.4.3 = HEAD 9ab85bb。工作树有 6 个未跟踪产物，那是上一轮的，**不要动也不要提交**。

**你是本轮唯一写入者**（之后我还会派一路做证据重跑，会等它先完工）。领地：pet_balance.py · 桌宠.py · tests/** · _verify_v13.py · _dev/mutations_relay_v243.json。

## 两条铁律（先看）
1. 跑全量 pytest 前确认 _dev/.mutation.lock/ 不存在。
2. 在绿色版目录里调用 python.exe 一律加 -B（否则多 14 个 stdlib pyc）。

## 任务 1（A-1）：pet_balance 的 _fetching_balance 标志归属 → 请求代次
现状：worker 的 finally 提前复位 _fetching_balance，而槽还没跑（emit 排队中）→ 用户这时再点一次会真的起第二个并发线程（审查探针实测 started==2，旧口径只会排队）；随后先到的槽会把新请求的标志抹掉 → 后果不止多发一次 HTTP：反馈会落到别的结果上（重复/错配）。
> 【v2.4.4 质量审查校正】原文写"第二个请求落地会再弹气泡、再放金币音、再撒一次钱"，这句**从旧代码推不出来**（要让两颗结果先后命中 _manual_pending，中间还得再点一次）。可验证的口径就是上面这句（连点会多起一个并发请求 · 反馈重复/错配），代码与 README 已按此改准。
修法：引入请求代次（generation）。每次 refresh() 自增代次并随请求带下去；worker 与槽只复位/消费自己那一代的状态；旧代的迟到结果丢弃并记一条日志（不许静默）。
注意：这会连带改 P1-1 的三条证据用例（先 grep 找位置）。改测试时不许放宽断言——要保留 同一时刻只有一个在途请求 与 旧代结果不产生副作用（不弹气泡、不放音、不撒钱） 这类实质判据。

## 任务 2（A-2）：桌宠.py 的零推进自锁改死名单
现状：_state_pix_pending 在 本轮零推进 时被整表清空；而 _ensure_state_pix 开头是 if not pend: return → pending 为空是单向门：一旦因异常走进那个 finally，该状态永久缺失直到重启（_show_state 只 _log_error 后静默 no-op）。审查 A/B 实测确认过。
修法：别整表清空——改成记一个 已试过且失败的名字集合（例如 _state_pix_dead），只跳过真正试过且没建出来的名字；pending 里没试过的留到下一轮。要保证：(1) 正常路径行为与现在逐位相同；(2) 异常一次后恢复真方法再调 _state_pix(angry) 仍能补建（这是验收核心）。
连带：_dev/mutations_relay_v243.json 里钉这条自锁的锚点（M-R8 之类）要重锚并在 results 段重新跑一遍（用 _dev/mutate_check.py，它在 %TEMP% 影子副本里跑，真仓只读）。

## 任务 3（C-2）：启动/导出分片测试的墙钟阈值 → 注入 per-frame 慢速 spy
现状：tests/test_startup_defer_v242.py 与 tests/test_relay_v243.py 等用绝对毫秒阈值（如小于 60ms）判 分片没退化，在负载下会抖（同一份代码在影子里曾跑到 96/70/97ms；relay 那条只剩约 17ms 余量）→ 抖动会被误判成退化。
修法：照撒钱预载那条已经给出的正确姿势——注入一个每帧故意变慢的 spy（把单帧解码耗时人为放大），让 步数/切片数 变成确定性判据，绝对时间只作宽松上界或干脆去掉。要求：(1) 改完在有并发负载时也不抖（尽量）；(2) 故意破坏分片（例如把一步做完）必须变红（用变异验证）。

## 任务 4（C-3）：_verify_v13.py 的 proc resets to idle 1.2 秒时序窗 → 轮询（带超时）
现状：固定 1.2 秒预算，是计时抖动（首次基线红过一次，之后 8 次全绿）。修法：改成 轮询直到条件成立、带超时上限——超时才判失败，并在失败信息里带上实际等了多久与轮询次数。
注意：_verify_v13.py 有 EXPECT_CHECKS 常量与末尾硬断言 len(CHECKS)；新增或减少 check() 必须同步改常量；能不加 check() 就别加。

## 硬性要求
1. 每条改动配能真失败的测试（优先变异验证：把修复拿掉必须红）。
2. 完工回报三项实测：python -m pytest tests -o addopts= -q（目标 0 failed；当前 707）· python _verify_v13.py（273 项 0 FAILS）· python _check_static.py（单跑 0/0）。
3. 不碰 VERSION / version_info.txt / _verify_green.py / CHANGELOG.md / _release_notes_*.md / 绿色版 / 发布 zip。
4. 不要提交（提交由我统一做）。
5. 如实报告没做到的。
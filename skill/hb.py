#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""心跳：tick.py 自动在后台拉起，每 20 秒告诉 wxtest「我还活着」，续上本 agent 手里所有任务（只防「掉线」：单条领走 5 分钟没交，wxtest 照样收回）。
tick.py/watch.py 超过 2 分钟没动静（Muse 停了）或 skill 代码换了就自己退出，wxtest 60 秒收不到心跳就把任务收回给别的 agent。"""
import os, sys, time
import awx, db

EVERY, IDLE = 20, 120
PID = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hb.pid")

def alive():
    try:
        pid = int(open(PID).read()); os.kill(pid, 0); return pid != os.getpid()
    except (OSError, ValueError):
        return False

def main():
    if alive() or not awx.AGENT:             # 没名字的 agent 不续心跳（tick 会提醒本人起名）
        return
    open(PID, "w").write(str(os.getpid()))
    c = db.conn()
    while time.time() - int(db.meta(c, "tick_at") or 0) < IDLE:
        if awx._build() != awx.BUILD:          # skill 升级了：退出，tick 下一轮用新代码拉起（不然旧心跳一直报旧指纹）
            print("[hb] skill 代码换了，退出让 tick 用新代码重拉", file=sys.stderr, flush=True); break
        try:
            awx.api("/heartbeat", {}, timeout=15)
        except Exception as e:
            print(f"[hb] {e}", file=sys.stderr, flush=True)
        time.sleep(EVERY)
    try: os.remove(PID)
    except OSError: pass

if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""开机钩子（兜底）：Muse/hatch 沙箱的平台每 60 秒扫 <HOME>/hooks/definitions/，有 home-init 定义、<HOME>/init.sh 可执行（700），
沙箱每次启动就跑一次 init.sh（/run 里打标记，失败不重试）。我们在 init.sh 里放一行 `watch.py boot`：重建后 systemd unit 丢了照样装回、拉起值班。
主路仍是每 10 秒的平台 hook（watch.py hook），这条只防那个 hook 被删或停了。机制来自 bytehola/muse-guardian 的说明，11-07 起在本项目机器上实测。
只在有 /home/hatch 的机器上装；init.sh 里已有别人的内容不覆盖：插在第一个 exec 行前（exec 之后的行跑不到），没有 exec 就追加。
定义和钩子脚本已存在（比如别的 skill 装过）就不动，只保证 init.sh 里有我们这一行。只写日志，不往 stdout 输出（hook 有输出才叫醒 AI）。"""
import json, os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
HOME = os.environ.get("AWX_HATCH_HOME", "/home/hatch")
TAG = "# ai-wechat-auto 开机兜底"
TRY = os.path.join(HERE, ".boothook_try")     # 装失败的时间（mtime），RETRY 秒内不再试
RETRY = 600
LOGF = os.path.join(HERE, "watch.log")

def log(m):
    try:
        with open(LOGF, "a") as f: f.write(f"{time.strftime('%H:%M:%S')} {m}\n")
    except OSError: print(time.strftime("%H:%M:%S"), m, file=sys.stderr, flush=True)

def paths():
    return (os.path.join(HOME, "hooks", "definitions", "home-init.json"), os.path.join(HOME, "hooks", "scripts", "home-init.sh"),
            os.path.join(HOME, "init.sh"))

def line():
    return f"{sys.executable} {os.path.join(HERE, 'watch.py')} boot >>{LOGF} 2>&1 || true  {TAG}"

DEF = {"created_at_ms": 0, "delivery": {"surface": "main"}, "enabled": True, "id": "home-init", "poll_interval_secs": 60,
       "prompt": "Managed Home initialization hook. Its script always returns silent.", "script_timeout_secs": 600,
       "updated_at_ms": 0, "version": 1}

SCRIPT = """#!/bin/bash
# 平台每 60 秒调一次；每次沙箱启动只跑一次 init.sh（/run 是内存盘，重启清零）。永远 silent，不叫醒 AI。
umask 077
source "${HATCH_HOOK_RUNTIME:?}"
[[ "${HATCH_HOOK_DRY_RUN:-0}" == 1 ]] && silent "dry-run"
[[ -x HOME_DIR/init.sh ]] || silent "no init.sh"
mkdir -p /run/hatch-home-init
exec 9>/run/hatch-home-init/lock
flock -n 9 || silent "running"
[[ ! -e /run/hatch-home-init/started ]] || silent "already run"
cd HOME_DIR
{ touch /run/hatch-home-init/started; printf '\\n[%s] init started\\n' "$(date -Is)"
  /bin/bash ./init.sh 9>&- </dev/null && rc=0 || rc=$?; printf '[%s] init exited: %s\\n' "$(date -Is)" "$rc"; } >>/tmp/home-init.log 2>&1
silent "already run"
"""

def _write(p, body, mode):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w") as f: f.write(body)
    os.chmod(tmp, mode); os.replace(tmp, p)

def ensure():
    """装好（或补齐）开机钩子；装好的什么都不动。返回给人看的一句话（不在 hatch 沙箱返回空串）。setup 和每次 hook 都调。"""
    if not os.path.isdir(HOME): return ""
    d, s, i = paths()
    try: cur = open(i).read()
    except FileNotFoundError: cur = None
    except OSError as e: cur = ""; log(f"[boot] 读 init.sh 没成：{e}")
    if cur is not None and TAG in cur and os.path.exists(d) and os.path.exists(s) and os.access(i, os.X_OK): return "开机钩子已装好。"
    try:
        if time.time() - os.path.getmtime(TRY) < RETRY: return ""
    except OSError: pass
    try:
        if not os.path.exists(d): _write(d, json.dumps(dict(DEF, script_path=s), ensure_ascii=False, indent=2) + "\n", 0o644)
        if not os.path.exists(s): _write(s, SCRIPT.replace("HOME_DIR", HOME), 0o755)
        if cur is None: body = "#!/bin/bash\n" + line() + "\n"
        elif TAG in cur: body = cur
        else:
            ls = cur.splitlines()
            at = next((n for n, l in enumerate(ls) if l.lstrip().startswith("exec ")), len(ls))
            body = "\n".join(ls[:at] + [line()] + ls[at:]) + "\n"
        _write(i, body, 0o700)
    except OSError as e:
        open(TRY, "w").close(); log(f"[boot] 开机钩子没装上（{e}），{RETRY} 秒后再试"); return f"开机钩子没装上：{e}"
    try: os.remove(TRY)
    except FileNotFoundError: pass
    log("[boot] 开机钩子已装好（沙箱每次启动跑一次 watch.py boot，兜底 10 秒 hook）")
    return "开机钩子已装好（沙箱每次启动自动把值班拉回，兜底平台 hook）。"

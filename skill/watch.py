#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""值班循环：一直挂在 wxtest 上领任务，手里永远只拿一条。
  python3 watch.py          常驻（已有一份在跑就直接退出，可反复调用来「保活」）
  python3 watch.py setup    一键上岗：停旧值班（run_loop.sh/watch_loop.sh、crontab 里的开班）→ 装 systemd（装不上就算了）→ 拉起 → 自检，最后打印平台 hook 要填的那一行
  python3 watch.py hook     平台 hook 每 10 秒跑这一句：保活（up）+ 新任务打印一次（REMIND 秒后还在再打印一次），其余时候什么都不输出；在哪个目录调用都行
  python3 watch.py install  装成 systemd 用户服务（挂了 5 秒自动拉起、开机自启），装不上会说明改用 hook
  python3 watch.py up       保活：没在跑就脱离当前会话在后台拉起一份（setsid），在跑就什么都不做
  python3 watch.py next     打印最早一条待处理任务（没有就什么都不输出）
  python3 watch.py status   看本机名字、代码指纹和 wxtest 上在线的 agent
  python3 watch.py update   马上从 wxtest 拉它自带的那版 skill 覆盖本地代码（平时落后了 wxtest 会自己派，不用手动）
  python3 watch.py done ID  处理完删掉（带 --task 的任务 act.py 交回后会自动删，alert/摘要等没有 --task 的要手动 done）
领到任务写进 inbox/<ID>.json，设置了 wake 就马上跑它叫醒 Muse，然后不再领下一条，直到 inbox 空了；等待期间续着 tick_at，后台心跳不会退出。
wxtest 规定单条领走 5 分钟没交就收回，所以处理要快；处理不了也别拖，交 {} 或 done 掉，好让别的 agent 接。"""
import fcntl, glob, json, os, re, subprocess, sys, time, types
import db, psync

HERE = os.path.dirname(os.path.abspath(__file__))
INBOX = os.path.join(HERE, "inbox")
REMIND = 240        # hook 同一条只叫醒一次，这么久还没处理再提醒一次（每 10 秒都打印会把平台唤醒放大 33 倍，处理员排队几小时）
STALE = 330          # 超过 wxtest 的单条上限（300 秒）还没处理完：wxtest 已收回改派别人，本地这份作废，丢掉接着领

def log(m):
    print(time.strftime("%H:%M:%S"), m, file=sys.stderr, flush=True)

def pending():
    return sorted(glob.glob(os.path.join(INBOX, "*.json")), key=os.path.getmtime)

def save(out):
    m = re.search(r"--task ([\w-]+)", out)
    tid = m.group(1) if m else f"n{int(time.time() * 1000)}"
    tmp = os.path.join(INBOX, f".{tid}.tmp")
    open(tmp, "w", encoding="utf-8").write(out)
    path = os.path.join(INBOX, f"{tid}.json")
    os.replace(tmp, path)
    log(f"[watch] 领到 {tid}")
    wake(tid, path)

def wake(tid, path):
    """设置 wake 填了就马上叫醒 Muse；失败只记日志，hook 定时看 next 兜底。"""
    cmd = db.config(db.conn())["wake"]
    if not cmd:
        return
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10,
                           env=dict(os.environ, AWX_TASK_ID=tid, AWX_TASK_FILE=path))
        if r.returncode: log(f"[wake] 退出码 {r.returncode}：{(r.stderr or r.stdout).strip()[:200]}")
        else: mark(tid)                        # 叫醒过了，hook 不再重复叫
    except Exception as e:
        log(f"[wake] {e}")

def shown(tid):   # inbox/.<ID>.shown：已经叫醒过几次（内容）、最后一次什么时候（mtime）
    return os.path.join(INBOX, f".{tid}.shown")

def mark(tid):
    p = shown(tid)
    try: n = int(open(p).read() or 0)
    except (OSError, ValueError): n = 0
    open(p, "w").write(str(n + 1))

def done(tid):
    tid = os.path.basename(tid).removesuffix(".json")
    for p in (os.path.join(INBOX, f"{tid}.json"), shown(tid)):
        try: os.remove(p)
        except OSError: pass

LOCK = os.path.join(HERE, "watch.lock")
UNIT = "awx-watch.service"

def running():
    """已有一份值班在跑（它拿着 watch.lock）。"""
    with open(LOCK, "a") as f:
        try: fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError: return True
        fcntl.flock(f, fcntl.LOCK_UN); return False

def up():
    """hook 保活：不挂在调用它的会话上（会话结束、超时被平台清进程树时值班不跟着死）。"""
    if running(): return
    log_f = open(os.path.join(HERE, "watch.log"), "a")
    subprocess.Popen([sys.executable, os.path.abspath(__file__)], cwd=HERE, stdin=subprocess.DEVNULL,
                     stdout=log_f, stderr=log_f, start_new_session=True)
    log("[watch] up：没在跑，已在后台拉起")

def install():
    """写 systemd 用户服务并启用。返回 0 成功；失败打印原因和 hook 兜底办法，返回 1。"""
    d = os.path.expanduser("~/.config/systemd/user"); os.makedirs(d, exist_ok=True)
    open(os.path.join(d, UNIT), "w").write(
        "[Unit]\nDescription=ai-wechat-auto 值班循环（muse-skill/watch.py）\nStartLimitIntervalSec=0\n\n"
        f"[Service]\nWorkingDirectory={HERE}\nExecStart={sys.executable} {os.path.abspath(__file__)}\n"
        f"Restart=always\nRestartSec=5\nStandardOutput=append:{HERE}/watch.log\nStandardError=append:{HERE}/watch.log\n\n"
        "[Install]\nWantedBy=default.target\n")
    steps = [["systemctl", "--user", "daemon-reload"], ["systemctl", "--user", "enable", "--now", UNIT]]
    for cmd in steps:
        try: r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired) as e: r = types.SimpleNamespace(returncode=1, stderr=str(e), stdout="")
        if r.returncode:
            print(f"systemd 用户服务没装上（{' '.join(cmd)}：{(r.stderr or r.stdout).strip()[:200]}）。"
                  f"改用平台 hook 每 10 秒执行：cd {HERE} && python3 watch.py up")
            return 1
    try: subprocess.run(["loginctl", "enable-linger", os.environ.get("USER", "")], capture_output=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as e: log(f"[watch] enable-linger 没做成（不影响已在跑的服务）：{e}")
    print(f"已装好并启动 {UNIT}（挂了 5 秒自动拉起、开机自启）。另建议 hook 每 10 秒执行 python3 watch.py up 兜底（在跑就什么都不做）。")
    return 0

OLD = ("run_loop.sh", "watch_loop.sh")   # 旧值班脚本（cron 开班 / 会话里循环），setup 时停掉

def stop_old():
    """停掉旧式值班进程，删掉 crontab 里开班的行。返回做了什么（给 setup 打印）。"""
    did = []
    for d in glob.glob("/proc/[0-9]*"):
        try: cmd = open(f"{d}/cmdline", "rb").read().replace(b"\0", b" ").decode(errors="replace")
        except OSError: continue
        if any(o in cmd for o in OLD) and int(d[6:]) != os.getpid():
            try: os.kill(int(d[6:]), 15); did.append(f"停了旧进程 {d[6:]}：{cmd.strip()[:80]}")
            except OSError as e: did.append(f"停不了旧进程 {d[6:]}：{e}")
    try:
        r = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            keep = [l for l in r.stdout.splitlines() if not any(o in l for o in OLD + ("tick.py",))]
            if len(keep) < len(r.stdout.splitlines()):
                subprocess.run(["crontab", "-"], input="\n".join(keep) + "\n", text=True, timeout=10, check=True)
                did.append(f"删了 crontab 里 {len(r.stdout.splitlines()) - len(keep)} 行开班")
    except (OSError, subprocess.SubprocessError) as e:
        log(f"[setup] 查 crontab 没做成：{e}")
    return did

def status_line():
    try:
        import awx
        st = awx.api("/status", timeout=15)
        return f"本机 {awx.AGENT or '（没填名字，不会领任务）'}，代码指纹 {awx.BUILD}；wxtest 登录 {st.get('logged_in')}，在线 agent：" + "，".join(f"{a.get('agent')}({a.get('hb_ago')}秒)" for a in st.get("agents") or [])
    except BaseException as e:            # awx 缺令牌是 SystemExit，也只报不退
        return f"连不上 wxtest：{e}"

def setup():
    for d in stop_old(): print(d)
    systemd = install() == 0
    up()
    for _ in range(10):
        if running(): break
        time.sleep(1)
    ok = running()
    print(("值班已在跑。" if ok else "值班没起来，看 watch.log。") + status_line())
    print("画像同步：" + ("已请 wxtest 马上安排一次（第一次是全量）" if psync.request(db.conn(), log) else "没请成，wxtest 按 sync_min 会自己安排"))
    print(f"还差平台上一步（代码做不了）：建一个每 10 秒的定时 hook，执行\n  {sys.executable} {os.path.abspath(__file__)} hook\n"
          "没有输出就什么都不做；有输出就是一条任务（JSON），叫醒处理员马上处理。"
          + ("" if systemd else "（本机 systemd 用户服务装不上，保活全靠这个 hook。）")
          + "\n平台自带的定时开班（例如 cron 每 N 分钟跑值班脚本）请删掉，不要再用。")
    return 0 if ok else 1

def loop():
    lock = open(LOCK, "w")
    try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError: return                      # 已有一份在跑
    os.makedirs(INBOX, exist_ok=True)
    c = db.conn()
    log("[watch] 开始值班")
    try: import awx                             # 没令牌时 awx import 就退出：那就不查升级，值班照跑
    except SystemExit: awx = None; log("[watch] awx 起不来（没令牌？），不查代码升级")
    build, checked = awx and awx.BUILD, time.time()
    while True:
        if awx and time.time() - checked > 60 and not pending():   # skill 升级了（拉了新代码）：手里没活时退出，hook 10 秒内用新代码拉起
            checked = time.time()
            if awx._build() != build:
                log(f"[watch] skill 代码换了（{build} → {awx._build()}），退出让 hook 用新代码重拉"); return
        try:
            step(c)
        except Exception as e:                  # 什么错都不许把值班循环弄死
            log(f"[watch] {e}"); time.sleep(5)

_sync_try = {"at": 0, "sig": None, "stuck": 0}
URGENT_EVERY, STUCK_WAIT = 10, 600
def maybe_urgent(c):
    """手里没任务时：本机画像/规则/设置有没推的改动就请 wxtest 马上给本机下放同步（即时同步），最多 URGENT_EVERY 秒请一次。
    别台改的不用请：wxtest 收下后会给其余在线的全部下放。防死循环：同一批改动请过、也同步过一轮还在（推不上去），
    退到 STUCK_WAIT 秒才再请，并记日志让人查。"""
    now = time.time()
    if now - _sync_try["at"] < (STUCK_WAIT if _sync_try["stuck"] else URGENT_EVERY) or db.config(c)["sync_min"] <= 0: return
    if not psync.urgent(c): _sync_try.update(sig=None, stuck=0); return
    sig = psync.signature(c)
    synced_since = int(db.meta(c, "psync_at") or 0) > _sync_try["at"] > 0
    if sig == _sync_try["sig"] and synced_since:
        if not _sync_try["stuck"]: log(f"[watch] 同步过一轮这批改动还没推上去（{sig[:8]}），{STUCK_WAIT} 秒后再请；查 watch.log 里 [psync] 那行")
        _sync_try["stuck"] = 1
    else: _sync_try["stuck"] = 0
    _sync_try.update(at=now, sig=sig)
    psync.request(c, log)

_noname = [0]
def step(c):
    if not db.meta(c, "agent"):                 # 没名字不领任务；10 分钟跑一次 tick，让 wxtest 发文件传输助手提醒本人
        if time.time() - _noname[0] > 600:
            _noname[0] = time.time()
            log("[watch] settings.json 里没填 agent（这台的名字），不领任务：问用户起一个（几台各不相同），写进去再跑 seed.py")
            try: subprocess.run([sys.executable, os.path.join(HERE, "tick.py")], cwd=HERE, capture_output=True, timeout=60)
            except (OSError, subprocess.TimeoutExpired) as e: log(f"[watch] 提醒没名字没成：{e}")
        time.sleep(30); return
    p = pending()
    if p:
        if time.time() - os.path.getmtime(p[0]) > STALE:
            log(f"[watch] {os.path.basename(p[0])} 超过 {STALE} 秒没处理完（wxtest 已收回改派），丢弃；请查处理员为什么没处理")
            done(p[0]); return
        db.meta_set(c, "tick_at", str(int(time.time())))   # 手里有活，心跳别退
        time.sleep(2); return
    maybe_urgent(c)
    try:
        r = subprocess.run([sys.executable, os.path.join(HERE, "tick.py")], cwd=HERE,
                           capture_output=True, text=True, timeout=400)   # 别杀太早：awx 失败会重试多轮，半路杀掉领到的任务就白占 5 分钟
    except subprocess.TimeoutExpired:
        log("[watch] tick.py 400 秒没返回，重来"); return
    if r.stderr.strip(): sys.stderr.write(r.stderr); sys.stderr.flush()
    if r.stdout.strip(): save(r.stdout.strip())
    if r.returncode: log(f"[watch] tick.py 退出码 {r.returncode}"); time.sleep(5)

def main_next(hook=False):
    p = pending()
    if p and hook:                             # hook：同一条只给一次，REMIND 秒后还在再给一次，之后不再给（330 秒丢弃）
        tid = os.path.basename(p[0])[:-5]
        try: n, ago = int(open(shown(tid)).read() or 0), time.time() - os.path.getmtime(shown(tid))
        except (OSError, ValueError): n, ago = 0, 0
        if n >= 2 or (n == 1 and ago < REMIND): return
        mark(tid)
    if p:
        print(json.dumps({"id": os.path.basename(p[0])[:-5], **json.load(open(p[0], encoding="utf-8"))}, ensure_ascii=False))

def main():
    a = sys.argv[1:]
    if not a:
        return loop()
    if a[0] == "next":
        main_next()
    elif a[0] == "done" and len(a) > 1:
        done(a[1])
    elif a[0] == "up":
        up()
    elif a[0] == "hook":
        up(); main_next(hook=True)
    elif a[0] == "setup":
        sys.exit(setup())
    elif a[0] == "install":
        sys.exit(install())
    elif a[0] == "status":
        print(status_line())
    elif a[0] == "update":
        import skillup
        r = skillup.run(); print(json.dumps(r, ensure_ascii=False)); sys.exit(0 if r.get("ok") else 1)
    else:
        sys.exit(__doc__)

if __name__ == "__main__":
    main()

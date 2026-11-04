"""从 wxtest 拉它镜像自带的那版 skill，覆盖本目录（wxtest 发现本机落后时派 kind=update，tick.py 领到就做；手动：python3 watch.py update）。
本人 11-03 授权：这是唯一允许自动改 skill 代码的路子。只换仓库里的代码和文档；settings.json、awx.env、store.db、rules/<人>.md 等本机数据一律不动。
步骤：先全写进临时目录核对指纹、全部 .py 能编译，再把旧文件备份到 .bak/<时间>/（留 3 份）逐个替换；替换后指纹不对就整份恢复。"""
import os, sys, time, shutil, tempfile
import awx

HERE = os.path.dirname(os.path.abspath(__file__))
KEEP = 3        # 备份留几份（.bak/<时间>-<旧指纹>/）
DATA = ("settings.json", "awx.env", "store.db", "hb.pid", "watch.lock", "watch.log")

def _ok(rel):
    """只认仓库跟踪的那几类：顶层 .py/SKILL.md/schema.sql/settings.example.json、docs/ styles/ 下的 .md、rules/_example.md。"""
    if not rel or rel.startswith(("/", ".")) or "\\" in rel or ".." in rel.split("/") or os.path.basename(rel) in DATA: return False
    parts = rel.split("/")
    if len(parts) == 1: return rel.endswith(".py") or rel in ("SKILL.md", "schema.sql", "settings.example.json")
    return (len(parts) == 2 and parts[0] in ("docs", "styles") and rel.endswith(".md")) or rel == "rules/_example.md"

def _code(d):
    return sorted(f for f in os.listdir(d) if f.endswith(".py") or f in ("schema.sql", "SKILL.md"))

def run(want="", here=None, api=None):
    """返回 {"ok", "build", "from", "changed", "removed"} 或 {"ok": False, "why"}。"""
    here, api = here or HERE, api or awx.api
    old = awx._build(here)
    b = api("/skill", timeout=120)
    build, files = b.get("full") or b.get("build") or "", b.get("files") or {}   # full 含文档（新版 wxtest）；旧版只有 build
    if not build or not files: return {"ok": False, "why": "wxtest 没有自带 skill（旧镜像）"}
    if want and want not in (build, b.get("build")): print(f"[update] 派单时目标 {want}，wxtest 现在自带 {build}，按现在的来", file=sys.stderr)
    if build == old: return {"ok": True, "build": build, "from": old, "changed": [], "removed": []}
    bad = [r for r in files if not _ok(r)]
    if bad: return {"ok": False, "why": f"包里有不该有的路径：{bad[:3]}"}
    tmp = tempfile.mkdtemp(prefix=".skillup-", dir=here)
    try:
        for rel, text in files.items():
            p = os.path.join(tmp, rel); os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8", newline="") as f: f.write(text)
        if awx._build(tmp) != build: return {"ok": False, "why": f"拉下来的指纹 {awx._build(tmp)} 和 wxtest 说的 {build} 不一样，没换"}
        for rel in files:
            if rel.endswith(".py"):
                try: compile(files[rel], rel, "exec")
                except (SyntaxError, ValueError) as e: return {"ok": False, "why": f"{rel} 编译不过，没换：{str(e)[:120]}"}
        changed = [r for r in sorted(files) if not os.path.exists(os.path.join(here, r)) or open(os.path.join(here, r), encoding="utf-8", errors="replace").read() != files[r]]
        removed = [f for f in _code(here) if f not in files]   # 上游删掉的顶层代码（不删就会算进指纹、对不上）
        bak = os.path.join(here, ".bak", time.strftime("%Y%m%d-%H%M%S") + f"-{old}")
        added = []
        for rel in changed + removed:
            src = os.path.join(here, rel)
            if os.path.exists(src):
                os.makedirs(os.path.dirname(os.path.join(bak, rel)), exist_ok=True); shutil.copy2(src, os.path.join(bak, rel))
            elif rel in files: added.append(rel)
        for rel in changed:
            dst = os.path.join(here, rel); os.makedirs(os.path.dirname(dst), exist_ok=True); os.replace(os.path.join(tmp, rel), dst)
        for rel in removed: os.remove(os.path.join(here, rel))
        now = awx._build(here)
        if now != build:                                       # 替换途中出了岔子：整份恢复
            _restore(here, bak, added)
            return {"ok": False, "why": f"换完指纹是 {now} 不是 {build}，已恢复原样（备份 {os.path.basename(bak)}）"}
        _prune(os.path.join(here, ".bak"))
        print(f"[update] skill {old} → {build}：改 {len(changed)} 个、删 {len(removed)} 个，旧文件备份在 .bak/{os.path.basename(bak)}", file=sys.stderr)
        return {"ok": True, "build": build, "from": old, "changed": changed, "removed": removed}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

def _restore(here, bak, added):
    for root, _, fs in os.walk(bak):
        for f in fs:
            src = os.path.join(root, f); shutil.copy2(src, os.path.join(here, os.path.relpath(src, bak)))
    for rel in added:
        try: os.remove(os.path.join(here, rel))
        except OSError as e: print(f"[update] 恢复时删 {rel} 失败：{e}", file=sys.stderr)

def _prune(d):
    try:
        for x in sorted(os.listdir(d))[:-KEEP]: shutil.rmtree(os.path.join(d, x), ignore_errors=True)
    except OSError as e: print(f"[update] 清旧备份失败：{e}", file=sys.stderr)

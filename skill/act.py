#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""执行 Muse 的决定：python3 act.py <chat> [--media] [--sns tid:评论id] [--task ID] <<'EOF' … Muse 写的 JSON … EOF
JSON 可含 "profile"（画像，写库）和 "intent" + "reply"（回复）。
技术问题要联网查时先写 {"intent": "tech", "wait": "稍等的话"}：这里先把稍等发出去、任务不交，查完再跑一次同样的命令交正式回复。发不发、发草稿还是只通知，按风险表由这里决定，不由 Muse 决定。
定下来的结论交回 wxtest：要发的回复（send）和给本人的通知（notify）由 wxtest 去发，发不出它自己重试，这里不等。"""
import json, sys, time
import awx, db, reply_rules as rr, sns, voices, watch


def ai_labels(p, cfg):
    """AI 给的三层标签：大类（label_top）、关系（label_rel，选了关系就按设置配上它的大类）、补充最多 2 个；
    大类和关系都没有就一个不打；本人专用的（label_mine）一律不打。"""
    rel = str(p.get("label") or "").strip()
    rel = rel if rel in cfg["label_rel"] else ""
    top = db.label_parent(cfg, rel) if rel else ""
    if not top and str(p.get("top") or "").strip() in cfg["label_top"]: top = str(p["top"]).strip()
    out = [x for x in (top, rel) if x]
    if not out: return []
    extra = p.get("label_extra") if isinstance(p.get("label_extra"), list) else []
    ok = [x for x in (str(x).strip()[:12] for x in extra)
          if x and x not in cfg["label_mine"] and x not in cfg["label_top"] and x not in cfg["label_rel"]]
    out += list(dict.fromkeys(ok))[:2]
    return out

def ai_remark(data):
    """AI 给没备注的人起的备注（JSON 顶层或 profile 里的 remark），最长 30 字；没有返回 None。"""
    p = data.get("profile") if isinstance(data.get("profile"), dict) else {}
    r = " ".join(str(data.get("remark") or p.get("remark") or "").split()).strip("-—")[:30]
    return r or None

def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    chat, args = sys.argv[1], sys.argv[2:]
    tid = args[args.index("--task") + 1] if "--task" in args else None
    c = db.conn(); db.init(c)
    waited = db.meta_json(c, "task:" + chat, {}).get("waited")
    chk = tid and not waited and awx.task_check(tid)   # 已回过稍等的照旧做完（被收回了下面补发，有没有人回过由 wxtest 在发送锁里把关）
    if chk and not chk["mine"]:        # 早被收回、别台处理过或已作废（处理员晚了几小时才跑）：什么都不动，画像、标签、草稿、稍等都不写不发
        print(f"[task] {tid} 已不是本机的（{chk['status']}，{chk['agent']}），不处理", flush=True)
        watch.done(tid); return
    if tid: watch.begin(tid)           # 告诉值班：已在处理，别自动交还
    out = run(chat, "--media" in args, args[args.index("--sns") + 1] if "--sns" in args else None)
    if out is None:                    # 只发了「稍等」，任务留在手里，查完再跑一次
        return
    draft = out.pop("draft", None)
    if "--task" not in args:           # 批量画像没有 --task：不交结论，草稿直接存
        if draft: db.add_draft(db.conn(), chat, *draft)
        return
    r = awx.task_done(tid, out)
    watch.done(tid)                    # 交了（或被拒）就从值班收件箱删掉，watch.py 接着领下一条
    ok = bool(r and r.get("ok"))
    if not ok:
        print(f"[task] {tid} 结论没交上：{(r or {}).get('error', '连不上')}，现状 {(r or {}).get('status')}（{(r or {}).get('agent')}）", flush=True)
    if ok:                             # 问过 AI 补标签/备注：交上了才算问过（3 天内不再问），没交上下次照问
        c = db.conn()
        for k in db.meta_json(c, "task:" + chat, {}).get("ask") or []:
            db.meta_set(c, f"{k}:{chat}", str(int(time.time())))
    if draft:
        if ok: db.add_draft(db.conn(), chat, *draft)
        else: print(f"[draft] {tid} 草稿不存", flush=True)
    snd = out.get("send")
    if not ok and snd and out.get("waited"):   # 查资料超过 5 分钟、任务被收回：重派的会因已回过稍等而跳过，这里自己补发；稍等之后已有人回过，wxtest 发送锁里会挡掉（reply_to）
        ok, st, _ = awx.send(chat, snd["text"], db.config(db.conn())["me_id"], snd["group"], reply_to=snd["reply_to"])
        print(f"[send] 任务已收回，直接补发：{st}", flush=True)

def run(chat, media, sns_ref=None):
    """返回交给 wxtest 的结论：{"result": {...}, "send": {...}, "notify": "...", "notify_if_sent": "..."}。"""
    raw = sys.stdin.read()
    try:
        data = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
    except ValueError:
        data = {}
    c = db.conn(); db.init(c)
    cfg = db.config(c)
    row = c.execute("SELECT alias FROM profile WHERE chat=?", (chat,)).fetchone()
    name = (row and row["alias"]) or chat
    if isinstance(data.get("profile"), dict):
        p = data["profile"]
        if "risk" in p and p["risk"] not in ("low", "mid", "high"):
            p["risk"] = "high"
        db.save_profile(c, chat, name, p)
        print(f"[profile] {name}: {p.get('relation')} {p.get('risk')}", flush=True)
    lp = data.get("profile") if isinstance(data.get("profile"), dict) and (data["profile"].get("label") or data["profile"].get("top")) else data
    lbs = ai_labels(lp, cfg)
    rmk = ai_remark(data)
    if (lbs or rmk) and not db.is_group(chat):   # AI 自己决定给没标签/没备注的人弄的：wxtest 去做（本人弄过的不动），日报里给本人核对
        awx.set_labels(chat, lbs, ai=True, remark=rmk)
        print(f"[label] {name}: {'、'.join(lbs)} 备注={rmk}", flush=True)
    if "intent" not in data and "reply" not in data:
        miss = str(data.get("missing") or "").strip()[:12]
        return {"result": {"action": "label" if lbs else "none", **({"labels": lbs} if lbs else {}), **({"missing": miss} if miss else {})}}
    if sns_ref:                                    # 朋友圈评论：只回闲聊/技术，规矩见 sns.py
        tid, _, cid = sns_ref.partition(":")
        return sns.decide(c, chat, tid, int(cid), data, cfg)
    prof = db.profile(c, chat)
    tk = db.meta_json(c, "task:" + chat, {})       # tick.py 记下的：回的是哪条、对方说了什么
    rid, said = tk.get("rid"), tk.get("said", "")
    if data.get("wait") and data.get("intent") == "tech" and not media:
        if rr.decide(prof, "tech", "x", cfg)[0] != "auto":   # 只存草稿的人不发稍等
            print(f"[wait] {name}: 这个人只存草稿，不发稍等；查完直接再跑一次 act 交正式回复", flush=True)
            return None
        return wait(c, chat, name, prof, cfg, tk, str(data["wait"]).strip())
    if media and prof["risk"] != "low":
        act, text = "skip", ""
    else:
        act, text = rr.decide(prof, data.get("intent"), (data.get("reply") or "").strip(), cfg)
    if tk.get("waited") and act == "skip":          # 已经让对方稍等了，查不出来也得让本人知道
        act = "notify"
    out = {"result": {"action": act, "intent": data.get("intent")}, "waited": bool(tk.get("waited"))}
    note = lambda x: x if cfg["notify_to"] else None     # wxtest 发给本人时自己加【助理通知】
    if act == "auto":   # wxtest 去发：本人这几秒接话了、或对方又说话了，它会作废这条（AI 按新上下文重答）
        out["send"] = {"text": text, "group": prof["is_group"], "reply_to": rid, "alias": name}
        if tk.get("voice"):                          # 对方发的语音：转语音发，用 tick.py 定的声音，结尾自报身份
            out["send"].update(voice=tk["voice"], tail=voices.tail(cfg, tk["voice"]))
        if text == cfg["hold"]:
            out["notify_if_sent"] = note(f"{name} 问{'价格' if data.get('intent') == 'price' else '正事'}：「{said}」，"
                                         f"已回套话「{text}」，等你亲自回。")
        elif data.get("intent") == "tech" and prof["risk"] == "high":
            out["notify_if_sent"] = note(f"{name} 问技术：「{said}」，AI 已代答「{text}」，你可以看一眼。")
        print(f"[send] {name} -> {text!r}", flush=True)
    elif act == "draft":
        out["draft"] = (name, text)    # 交结论成功才写本地草稿（main），被拒的任务别留下没人要的草稿
        out["notify"] = note(f"{name}：「{said}」→ 草稿「{text}」，没发。")
    elif act == "notify":
        out["notify"] = note(f"{name} 说了需要你亲自处理的事：「{said}」，AI 没回。" if not tk.get("waited") else
                             f"{name} 问技术：「{said}」，已回稍等但没查到靠谱资料，等你亲自回。")
    else:
        print(f"[skip] {name}: 不回", flush=True)
    return out

def wait(c, chat, name, prof, cfg, tk, text):
    """技术问题要联网查：先回一句稍等，再把「回的是哪条」挪到这句稍等上，正式回复才不会被当成已经回过而跳过。"""
    ok, st, _ = awx.send(chat, text, cfg["me_id"], prof["is_group"], reply_to=tk.get("rid"))
    if not ok:                                     # 稍等没发出去（对方/本人刚接话等），按原来的直接答
        print(f"[wait] {name}: 稍等没发出（{st}），查完照常交回复", flush=True)
        return None
    mine = [m["id"] for m in awx.messages(chat, 5) if m.get("ai")]   # 刚发出的那句稍等
    if mine:
        db.meta_set(c, "task:" + chat, json.dumps(dict(tk, rid=mine[-1], waited=1), ensure_ascii=False))
    if cfg["notify_to"]:                           # 本人也知道一声：在帮谁查什么（只提交不等，不耽误查资料）
        awx.send(cfg["notify_to"], f"【助理通知】{name} 问技术：「{tk.get('said', '')}」，AI 已回稍等，正在联网查资料，查完自动回复。",
                 cfg["me_id"], wait=0)
    print(f"[wait] {name} -> {text!r}；已发稍等，查完资料再跑一次同样的 act 命令交正式回复（别再写 wait）", flush=True)
    return None

if __name__ == "__main__":
    main()

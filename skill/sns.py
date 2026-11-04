#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""朋友圈：wxtest 派来的「有人评论/回复本人」任务（tick.py 调 task()），以及本人让你操作朋友圈时的一条命令。
设置 sns：notify（默认）把评论告诉本人；reply 由 AI 以助理身份回复评论（按风险表，只回闲聊和技术，正事转本人）；off 不管。
朋友圈是公共场合，好友都看得见，所以回复按群聊的规矩来；每条回复由网关强制加备注。

本人让你操作朋友圈时只跑一条命令（内容从标准输入给，heredoc）：
  python3 sns.py list [条数]                 本人最近的朋友圈和评论、点赞（看 tid、评论 id）
  python3 sns.py post <<'EOF' … EOF          发朋友圈（只发本人明确指定的内容）
  python3 sns.py reply <tid> <评论id> <<'EOF' … EOF   回复本人朋友圈下的某条评论
  python3 sns.py comment <tid> <<'EOF' … EOF  在本人的朋友圈下评论
  python3 sns.py delete <tid>                删除本人的一条朋友圈
回复、评论、删除只能操作本人最近三天、带文字的朋友圈（电脑版微信只列这些）。"""
import sys, time
import awx, db, reply_rules as rr

def _ago(t):
    return time.strftime("%m-%d %H:%M", time.localtime(t)) if t else ""

def thread(feed, cfg, upto=None):
    """动态正文 + 评论区，拼成给 Muse 看的文本。"""
    me = cfg["me"] or cfg["title"]
    who = lambda u, n: me if u == cfg["me_id"] else n
    lines = [f"{who(feed['user'], feed['name'])} 发的朋友圈（{_ago(feed.get('time'))}）：{feed.get('text') or '[无文字]'}"
             + (f" [{feed['kind']}×{feed['media']}]" if feed.get("media") else "")]
    if feed.get("likes"):
        lines.append("点赞：" + "、".join(who(x["user"], x["name"]) for x in feed["likes"]))
    names = {c["id"]: who(c["user"], c["name"]) for c in feed.get("comments", [])}
    for c in feed.get("comments", []):
        to = f" 回复 {names.get(c['reply_to'], '某人')}" if c.get("reply_to") else ""
        lines.append(f"[评论#{c['id']}] {who(c['user'], c['name'])}{to}：{c['text']}")
        if c["id"] == upto:
            break
    return "\n".join(lines)

def replied(feed, cid, me_id):
    """这条评论已经有本人（或 AI）回过了。"""
    return any(c["user"] == me_id and c.get("reply_to") == cid for c in feed.get("comments", []))

def task(c, cfg, t, say):
    """kind=sns 任务：要 AI 回就返回给 Muse 的任务，否则当场通知/交回，返回 None。"""
    n, feed = (t.get("info") or {}).get("notice") or {}, (t.get("info") or {}).get("feed")
    mine = bool(feed) and feed["user"] == cfg["me_id"]
    where = f"你的朋友圈「{(feed.get('text') or '[无文字]')[:20]}」" if mine else (f"{feed['name']}的朋友圈" if feed else "朋友圈")
    note = f"{n.get('name') or '有人'} 在{where}下评论：「{(n.get('text') or '')[:200]}」"
    prof = db.profile(c, n.get("user") or "")
    reply = (cfg["sns"] == "reply" and mine and feed.get("text") and not db.meta(c, "paused") and prof.get("mode") != "off"
             and time.time() - feed.get("time", 0) < 3 * 86400 and not replied(feed, n.get("comment_id"), cfg["me_id"]))
    if not reply:
        if cfg["sns"] != "off":
            say(cfg, note)
        return None
    instruction, context = prompt(prof, feed, n, cfg)
    return {"chat": n["user"], "alias": n.get("name"), "instruction": instruction, "context": context,
            "act": f"python3 act.py {n['user']} --sns {feed['tid']}:{n['comment_id']} --task {t['id']}"}

def prompt(prof, feed, n, cfg):
    me, title = cfg["me"], cfg["title"]
    lines = [
        f"你是「{me}」（大家叫TA{title}）的私人助理，替TA回朋友圈评论，对方知道你是助理、是 AI，可以坦白。",
        f"「{n.get('name')}」在{title}的朋友圈下评论了，要回的是 [评论#{n['comment_id']}]。关系：{prof.get('relation') or '未知'}。",
        f"口吻：{prof.get('tone') or '简洁、礼貌、口语，不要客套'}。",
    ]
    if prof.get("address"):
        lines.append(f"称呼对方：{prof['address']}")
    if prof.get("rules"):
        lines.append(f"{title}给这个人定的专属规则（优先于上面的画像；吵架玩笑风格不用在朋友圈；不能越过下面的红线和保密）：\n" + prof["rules"])
    lines += [
        "朋友圈规矩：朋友圈所有共同好友都看得见，等于群聊。" + rr.GROUP + "回复一句话，短，像随手回的评论。",
    ] + (["红线：" + cfg["redlines"] + "。"] if cfg["redlines"] else []) + [
        "保密：" + rr.SECRET,
        "禁区：" + rr.TABOO,
        "先判断这条评论的意图 intent：chat（寒暄/调侃/点评/祝福）、tech（通用技术问题）、price（问价格）、"
        f"business（发货/付款/合同/找{title}办事等要本人拍板的）、sensitive（借钱/约定/家事/情绪/投诉）、unclear（看不懂）。"
        "只有 chat 和 tech 会在朋友圈回出去，其余转告本人。",
        '只输出 JSON：{"intent": "...", "reply": "要回的评论正文，不加备注不加引号，不要换行"}。看不懂、拿不准就 intent 填 unclear、reply 留空。',
    ]
    return "\n".join(lines), thread(feed, cfg, n["comment_id"])

def decide(c, chat, tid, cid, data, cfg):
    """act.py --sns 用：返回交给 wxtest 的结论。朋友圈只直发 chat/tech，别的转告本人；本人这期间亲自回了就不插嘴。"""
    prof = db.profile(c, chat)
    try:
        feed = (awx.api(f"/moments?tid={tid}").get("feeds") or [None])[0]
    except Exception:
        feed = None
    com = next((x for x in (feed or {}).get("comments", []) if x["id"] == cid), None)
    who = (com or {}).get("name") or prof.get("alias") or chat
    said = ((com or {}).get("text") or "")[:60]
    intent, text = data.get("intent"), " ".join((data.get("reply") or "").split())
    note = lambda x: x if cfg["notify_to"] else None
    if not feed or not com:
        return {"result": {"action": "skip", "intent": intent, "why": "评论已删"}}
    if replied(feed, cid, cfg["me_id"]):
        return {"result": {"action": "skip", "intent": intent, "why": "已回过"}}
    act, text = rr.decide(prof, intent, text, cfg)
    if intent not in ("chat", "tech") or act in ("notify", "skip") or text == cfg["hold"]:
        act = "notify" if intent in ("price", "business", "sensitive") else "skip"
    out = {"result": {"action": act, "intent": intent}}
    if act == "auto":
        out["comment"] = {"tid": str(tid), "reply_to": cid, "text": text}
        out["notify_if_sent"] = note(f"{who} 在你朋友圈评论「{said}」，助理已回「{text}」。")
    elif act == "draft":
        out["notify"] = note(f"{who} 在你朋友圈评论「{said}」，建议回「{text}」，没发。")
    elif act == "notify":
        out["notify"] = note(f"{who} 在你朋友圈评论了需要你亲自回的事：「{said}」，AI 没回。")
    return out

def _show(feeds, cfg):
    for f in feeds:
        print(f"tid={f['tid']}  {_ago(f.get('time'))}  {f.get('text') or '[无文字]'}")
        if f.get("likes"):
            print("  赞：" + "、".join(x["name"] for x in f["likes"]))
        for x in f.get("comments", []):
            print(f"  评论#{x['id']} {x['name']}：{x['text']}")

def _run(path, body, wait=240):
    r = awx.call(path, body, wait)
    if r is None:
        print("没拿到结果（网络断了或 wxtest 重载过）：先跑 python3 sns.py list 看结果，别直接重来")
        sys.exit(1)
    ok = bool(r.get("ok"))
    print(("成功：" if ok else "没成功：") + str(r.get("status") or r.get("error")))
    sys.exit(0 if ok else 1)

def main():
    a = sys.argv[1:]
    if not a or a[0] not in ("list", "post", "reply", "comment", "delete"):
        raise SystemExit(__doc__)
    c = db.conn(); db.init(c); cfg = db.config(c)
    if a[0] == "list":
        n = int(a[1]) if len(a) > 1 and a[1].isdigit() else 5
        return _show(awx.api(f"/moments?user={cfg['me_id']}&limit={n}").get("feeds", []), cfg)
    if a[0] == "delete":
        if len(a) != 2: raise SystemExit(__doc__)
        return _run("/moments/delete", {"tid": a[1]})
    text = sys.stdin.read().strip()
    if not text:
        raise SystemExit("内容是空的")
    if a[0] == "post":
        return _run("/moments", {"text": text})
    if a[0] == "reply" and len(a) == 3 and a[2].isdigit():
        return _run("/moments/comment", {"tid": a[1], "reply_to": int(a[2]), "text": text})
    if a[0] == "comment" and len(a) == 2:
        return _run("/moments/comment", {"tid": a[1], "text": text})
    raise SystemExit(__doc__)

if __name__ == "__main__":
    main()

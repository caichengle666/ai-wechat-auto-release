#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""自动画像：把某人的历史聊天交给 Muse 总结成画像，结果用 act.py 写回。只存结论，聊天用完即丢。
用法：python3 persona.py next [N]   # 输出最多 N 个（默认 5）待画像任务的 JSON（最近 30 天活跃的前 100 个私聊里没画过或超 7 天的；群不画像）
Muse 对每个任务写出 {"profile": {...}}，再 echo 这段 JSON | python3 act.py <chat>。"""
import json, sys, time
import awx, db

DAYS, TOP, HISTORY, STALE = 30, 100, 200, 7 * 86400

FIELDS_HELP = """"profile" 字段都用简短中文（{title} 是用户本人）：
- relation：家人/朋友/同行/客户/供应商/员工/陌生人/其他 选一个
- risk：low（损友、熟人闲聊为主）/ mid（同行、员工）/ high（客户、供应商、长辈、谈钱谈货多、关系看不清）。拿不准给 high
- tone：替{title}的私人助理回这个人时该用的口吻，一句话
- style：{title}本人对这个人的说话习惯（句子长短、口头禅、爱用的表情）
- address：{title}平时怎么称呼对方，没有就空
- topics：常聊话题，逗号分隔
- sensitive：敏感点（报价、账款、私事等），没有就空"""

LABEL_EVERY = 3 * 86400    # 同一个没标签/没备注的人最多 3 天问 AI 一次补不补

def _tops(cfg):
    return "；".join(f"{t}（{'、'.join(k) or '不细分'}）" for t, k in cfg["label_top"].items())

def label_help(cfg, existing, must=False):
    """还没标签的人：按三层标签（大类、关系、补充）给 TA 打（act.py 交给 wxtest 打上，日报里给本人核对）。
    must=False（聊得少）：有把握才打；must=True（聊满 50 条）：大类必须给（只分工作/亲友这种粗的，聊这么多不会分不出）。"""
    title, rel, mine, top = cfg["title"], cfg["label_rel"], set(cfg["label_mine"]), cfg["label_top"]
    extra = [x for x in existing if x not in rel and x not in mine and x not in top][:40]
    out = ["\nTA 还没有微信标签。" + ("" if must else "不是必须打：读完聊天有把握才打，拿不准就不写（以后聊多了还会再问你）。")]
    if top:
        out.append(f"\n- top：大类，从这些里选一个原样写：{_tops(cfg)}。"
                   + ("你们已经聊了 50 条以上，大类一定要写，不许空。" if must else "看得出就写。"))
    if rel:
        out.append(f"\n- label：关系，从这些里选一个原样写：{'、'.join(rel)}（工作上认识又是朋友的，按工作关系选，再在 label_extra 加「朋友」）。"
                   + ("细的关系看不准就只写大类。" if top else "聊这么多一定选得出最接近的一个。" if must else "看不出来就不写。"))
    out.append(f"\n- label_extra：补充标签，数组，最多 2 个，看得出才写：TA 做什么（行业、公司类型、职位等）、或「朋友」。"
               f"现有的补充标签：{'、'.join(extra) or '（还没有）'}，合适就原样用，没有才起新的（2~6 个字）。"
               f"{'、'.join(mine)} 这些只由{title}自己打，你别写。")
    if must:
        out.append("\n- missing：现有关系里实在没有贴切的（比如 TA 明显是房东，列表里没这类），写一个你建议本人新增的关系名（2~6 字），"
                   "日报会告诉本人；别把它写进 label，没有就不写。")
    return "".join(out)

def label_task(c, cfg, t):
    """wxtest 派来的 kind=label：这个好友聊满 50 条还没标签，读历史给 TA 打（至少一个大类）。不用打了返回 None。"""
    chat = t["chat"]
    if not db.labels_on(cfg) or db.skip_chat(chat) or db.is_group(chat): return None
    if awx.api("/labels?user=" + awx.quote(chat)).get("labels"): return None     # 派出后本人自己打了
    h = history(c, chat)
    if not h: return None
    return {"chat": chat, "alias": (t.get("info") or {}).get("name") or chat, "kind": "打标签",
            "instruction": f"读下面{cfg['title']}和这个好友的历史聊天（已超过 50 条），给 TA 打微信标签，只输出 JSON："
                           "{\"top\": \"\", \"label\": \"\", \"label_extra\": [], \"missing\": \"\"}。不回复任何人。"
                           + label_help(cfg, awx.all_labels(), must=True),
            "history": h, "act": f"python3 act.py {chat} --task {t['id']}"}

REMARK_HELP = ("\n- remark：TA 在微信里还没有备注（写在 JSON 顶层）。聊天里看得出 TA 的称呼和公司才写，格式「称呼-公司简称」，如「李生-某某科技」「王总-某某贸易」，"
               "只知道一样就只写那一样，最长 15 个字；公司、称呼都拿不准就不写，别编")

def stale(prof):
    return time.time() - (prof.get("profiled_at") or 0) > STALE

def history(c, chat):
    """画像用的历史对话文本；聊得太少（文字少于 5 条）返回空。"""
    msgs = awx.messages(chat, HISTORY)
    if sum(m.get("type") == 1 for m in msgs) < 5:
        return ""
    cfg = db.config(c)
    return awx.transcript(msgs, cfg["me_id"], cfg["me"] or cfg["title"])[-12000:]

def task(c, chat, alias):
    h = history(c, chat)
    if not h:                                # 画不出来：记下时间，按兜底（高风险）处理
        db.save_profile(c, chat, alias, {})
        return None
    return {"chat": chat, "alias": alias, "kind": "群聊" if db.is_group(chat) else "私聊",
            "instruction": "读下面的历史聊天，给这个联系人画像。只输出 JSON：{\"profile\": {...}}。\n"
                           + FIELDS_HELP.format(title=db.config(c)["title"]),
            "history": h}

def main():
    if sys.argv[1:2] != ["next"]:
        sys.exit(__doc__)
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    c = db.conn(); db.init(c)
    since, out = time.time() - DAYS * 86400, []
    for s in [s for s in awx.api("/sessions").get("sessions", [])
              if s["ts"] >= since and not db.skip_chat(s["username"]) and not db.is_group(s["username"])][:TOP]:
        if len(out) >= n:
            break
        if stale(db.profile(c, s["username"])):
            t = task(c, s["username"], s.get("name"))
            if t and db.config(c)["label_rel"] and not awx.api("/labels?user=" + awx.quote(s["username"])).get("labels"):
                t["instruction"] += label_help(db.config(c), awx.all_labels())
            if t:
                out.append(t)
    print(json.dumps({"tasks": out}, ensure_ascii=False))

if __name__ == "__main__":
    main()

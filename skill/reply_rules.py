#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回复规则：该不该回、整理这个人的资料、按意图决定直发/草稿/转告本人。
所有人名、称呼、备注、红线都来自 cfg（db.config，安装时问用户填的）。"""
from collections import Counter
import re, unicodedata
import awx


# 保密、群聊公共场合、禁区、意图分类、输出格式这些固定规矩写在 SKILL.md「写回复的规矩」，不进任务包：
# 任务包里一大段命令口吻的说明会被 Muse 平台安全检查当成外部内容夹带指令拦下（11-05 对照试验：带说明 4/4 拦，不带 0/9）。

# 发不发由 AI 定（本人 11-18 定）：AI 写了回复就发，没写就不发并通知本人；敏感一律不回、转告本人。
# 价格不再写死转本人（本人 11-19 定：不是每个用户都做生意）：能不能谈价格看用户自己写的红线。
# 红线管 AI 自己说出去的话（本人 11-19 09:55 定）：碰到红线 AI 照样回，只是不越线（婉拒、拖一拖、说要问本人），结论标 red；
# 实在不越线就回不了才留空 → 转告本人。守着红线回的敏感事也照发，发完告诉本人。
ASK_OWNER = ("sensitive",)

# 红线和关键字（本人 11-19 定：用户自己写，代码不带默认；不是每个用户都做生意）。都交给 AI 按意思判断，代码不对字面。
# 红线：全局一行一条（换行或分号隔开）。联系人卡片里勾掉的几条（profile.red_off，一行一条原文）对 TA 不算；任务包里只给 TA 实际生效的，千人千面。
# 关键字三层（只通知 ask_kw / 回并通知 tell_kw / 直接回 reply_kw）：任务包 keywords 里只放对 TA 生效的，AI 看对方说到哪层的事，
# 结论里标 kw（同时说到几层按最保守的：ask ＞ tell ＞ reply），act.py 照层办：ask 不发、转本人；tell 发完告诉本人；reply 发了不打扰。
# 没带的层 = 对 TA 不设，照默认（AI 自己定，正事/问价回完告诉本人，敏感/看不懂转本人）。
# 写法：逗号/顿号/分号/换行隔开；「价格+多少」= 两件都说到才算（给 AI 看的写法）。
# 联系人卡片：勾掉全局的几个（profile.kw_off，三层共用，一行一条原文；比对不看空格标点、全半角）+ 只对 TA 加的（profile 同名列，叠在全局后面）。
KW_MAX = 50
TIERS = (("ask_kw", "ask"), ("tell_kw", "tell"), ("reply_kw", "reply"))   # 从保守到宽松
_KW_SEP = re.compile(r"[,，、;；\n]+")
_RL_SEP = re.compile(r"[\n;；]+")
_KW_JUNK = re.compile(r"[\W_]+")
_KW_END = " \t\u3000。.！!？?～~…"
KW_OFF = ("无", "不用", "none", "off")       # 卡片里填这些 = 不给 TA 加（不会当成关键字「无」）

def _kw_norm(s):
    return _KW_JUNK.sub("", unicodedata.normalize("NFKC", s or "").lower())

def kw_items(text, cap=KW_MAX):
    """'多少钱，报价、价格 + 多少' → ['多少钱', '报价', '价格+多少']；原样保留给 AI 看，去重（不看空格标点），最多 KW_MAX 条。"""
    if (text or "").strip().lower() in KW_OFF:
        return []
    out, seen = [], set()
    for part in _KW_SEP.split(text or ""):
        w = "+".join(x.strip(_KW_END) for x in part.replace("＋", "+").split("+") if x.strip(_KW_END))   # 两头的句号问号空格去掉（「问价格。」→「问价格」）
        if _kw_norm(w) and _kw_norm(w) not in seen:
            seen.add(_kw_norm(w)); out.append(w)
    return out[:cap] if cap else out

def kw_list(prof, cfg, key="ask_kw"):
    """这一层对这个人实际生效的关键字：全局的去掉卡片里勾掉的，再加上只对 TA 加的。"""
    off = {_kw_norm(x) for x in kw_items(prof.get("kw_off"), None)}
    rules = [r for r in kw_items(cfg.get(key)) if _kw_norm(r) not in off]
    have = {_kw_norm(r) for r in rules}
    return rules + [r for r in kw_items(prof.get(key)) if _kw_norm(r) not in have]

def keywords(prof, cfg):
    """任务包 keywords：{层: [对 TA 生效的关键字]}，空的层不放；全空 = {}。"""
    return {tier: w for key, tier in TIERS if (w := kw_list(prof, cfg, key))}

def redline_items(text):
    """红线一行一条（分号也算分行），去重，原样保留。"""
    return list(dict.fromkeys(x.strip() for x in _RL_SEP.split(text or "") if x.strip()))

def redlines(prof, cfg):
    """对这个人实际生效的红线：全局的去掉卡片里勾掉的（比对时不看空格标点、全半角）。"""
    off = {_kw_norm(x) for x in redline_items(prof.get("red_off"))}
    return [x for x in redline_items(cfg.get("redlines")) if _kw_norm(x) not in off]

def _owner(m, cfg):
    """本人亲自发的：本人号上、不是 wxtest 那台发的（消息不带 ai；wxtest 按微信库来源字段标，不看内容）。"""
    return m.get("sender_id") == cfg["me_id"] and not m.get("ai")

SPAM = 3                         # 同一句出现 3 次及以上算刷屏（是否叫醒 AI 由 wxtest 判；这里只在喂给 AI 时合成一条）

def _k(m):
    return m.get("sender_id"), m.get("content")

def squash(msgs):
    """喂给 AI 前把刷屏的同一句合成一条（留最后一次，注明刷了几次）。"""
    cnt = Counter(_k(m) for m in msgs if m.get("type") == 1)
    seen, out = set(), []
    for m in reversed(msgs):
        k = _k(m)
        if m.get("type") == 1 and cnt[k] >= SPAM:
            if k in seen:
                continue
            seen.add(k); m = dict(m, content=f"{m.get('content')}（同一句刷了 {cnt[k]} 次）")
        out.append(m)
    return out[::-1]

def paid(new, cfg):
    """别人给本人的钱：转账（待收款那条，wxtest 会自动收）和红包（本人自己在手机上领），返回说明列表。"""
    out = []
    for m in new:
        if m.get("sender_id") == cfg["me_id"]:
            continue
        if m.get("app") == 2000 and (m.get("pay") or {}).get("sub") == 1:
            out.append(f"转账{(m.get('pay') or {}).get('amount') or ''}，已自动收下")
        elif m.get("app") == 2001:
            out.append("红包，本人会自己领")
    return out

def videos(new, cfg):
    """对方这批新发的视频和视频号分享（消息 id）。"""
    return [m["id"] for m in new if m.get("sender_id") != cfg["me_id"] and (m.get("type") == 43 or (m.get("type") == 49 and m.get("finder")))]

def should_reply(prof, new, cfg, called):
    """不回的人/群、本人在聊、群里没叫到本人，wxtest 派任务前已经挡掉了（只有一套，这里不再判）；called 是 wxtest 算好的。"""
    if not new:
        return False, "无新消息"
    if new[-1].get("sender_id") == cfg["me_id"]:
        return False, "最后一条是自己发的"
    if all(m.get("type") == 10000 for m in new):
        return False, "只有拍一拍/系统消息"
    content = (1, 3, 50) if cfg.get("vision") else (1, 50)   # 能看图时图片也算正经内容；文件、转发的聊天记录、没接到的电话总算
    if not prof["is_group"] and paid(new, cfg):          # 别人单聊转钱给本人：一定要回（道谢+接个话题）
        return True, "ok"
    if not prof["is_group"] and videos(new, cfg):       # 单聊发视频：先看懂再聊两句（本人 11-03 定，群里不做）
        return True, "ok"
    if all(m.get("type") not in content and m.get("app") not in (6, 19) for m in new) and prof.get("risk") != "low" and not called:
        return False, "只有图片/表情"
    return True, "ok"

def person(prof, recent, cfg):
    """回复任务里「这个人」的资料（只写事实，不写命令）和最近 30 条上下文。千人千面就在这里。"""
    mine = [m.get("content") for m in recent if _owner(m, cfg) and m.get("type") == 1][-10:]   # 只学本人亲口说的
    p = {"name": prof.get("alias") or prof["chat"], "relation": prof.get("relation") or "未知",
         "tone": prof.get("tone") or "简洁、礼貌、口语，不要客套"}
    for k in ("address", "style", "topics", "sensitive", "rules"):
        if prof.get(k):
            p[k] = prof[k]
    if mine:
        p["owner_said"] = mine
    return p, awx.transcript(squash(recent[-30:]), cfg["me_id"], cfg["me"] or cfg["title"])

INTENTS = ("chat", "tech", "price", "business", "sensitive")
ALIAS = {"闲聊": "chat", "寒暄": "chat", "调侃": "chat", "技术": "tech", "专业": "tech", "常识": "tech",
         "价格": "price", "问价": "price", "报价": "price", "正事": "business", "业务": "business",
         "敏感": "sensitive", "看不懂": "unclear", "不清楚": "unclear", "拿不准": "unclear"}

def intent_of(x):
    """AI 偶尔把意图写成中文（「技术」「闲聊」）：换回英文代码；认不出的原样返回，由 decide 转告本人。"""
    s = str(x or "").strip().lower()
    return ALIAS.get(s, s)

def decide(prof, intent, reply, cfg, kw=None, red=False):
    """返回 (动作, 正文)。动作：auto / draft / notify / skip。unclear 和认不出的意图转告本人，绝不悄悄丢掉。
    kw：AI 判断对方说到了本人设的哪层关键字。ask 只通知：不发、转本人；tell / reply：本人允许回这类话，
    AI 判成敏感也照发（红线由 AI 守，越线它会留空）。
    red：AI 碰到红线、守着红线写了回复（婉拒/拖/说要问本人），敏感的也照发（act.py 发完告诉本人）。"""
    if kw == "ask":
        return "notify", ""
    intent = intent_of(intent)
    if intent not in INTENTS:
        if intent != "unclear":
            print(f"[intent] 认不出的意图「{intent[:20]}」，没回，转告本人", flush=True)
        return "notify", ""
    if (intent in ASK_OWNER and kw not in ("tell", "reply") and not red) or not reply:  # 敏感转本人（本人设了能回的关键字、守着红线回的除外）；AI 没写回复也告诉本人
        return "notify", ""
    if prof.get("mode") == "draft":   # 只存草稿的人（草稿<名>）
        return "draft", reply
    return "auto", reply

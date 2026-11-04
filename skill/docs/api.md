# 网关接口与掉线自修（要直接调接口或微信掉线时才读）

## 接口说明去哪查
全部接口、参数、返回值以 wxtest 自带的说明为准（最新、最全，这里不抄一份）：
`curl -s -H "X-Token: $AWX_TOKEN" "$AWX_BASE/api"`

能用现成脚本就别直接调接口（`tick.py` 领任务、`act.py` 交结论、`hb.py` 心跳、`say.py` 代发、`sns.py` 朋友圈、`radar.py` 群商机，`awx.py` 已封装好下面这些坑）。自己调时记住：
- 慢操作（`/send`、`/voice2text`、`/moments*` 的 POST）跨机器一律在 body 带 `job`，再 `GET /job?id=&wait=15` 轮询；同一个 `job` 重复提交不会重做；查到 `unknown`（网关重载过）或 `UNCONFIRMED` 就先查消息/动态确认发没发出，别直接重发。
- 发文件：文件在 agent 机器上，用 `file_b64` + `filename` 传；`file` 只认微信机器上 `WX_FILE_DIR` 里的文件。
- 不要自己给回复加备注，网关强制加。

## 微信掉线了怎么自己修
本人只需要在手机上点一下确认或扫码，其余都由你做。按顺序：
1. `GET /status` 看 `logged_in`；没登录时看 `login_stage`：
   - `confirm`：已自动点了「登录」，在等手机确认 → 告诉本人「手机微信上点一下确认登录」。
   - `scan`：要扫码 → 把扫码页 `<AWX_BASE>/qr?token=<AWX_TOKEN>` 发给本人（页面每 5 秒刷新，二维码过期自动换新）。
   - `starting`：微信刚重启，等 30 秒再看。
   - `stuck`：卡住了（没二维码也没在等确认）→ wxtest 会自己重启微信进程（最多 10 分钟一次）；急的话可以 `POST /relogin`，30 秒后再看 `/status`。
2. 拿不准屏幕上是什么：`GET /screen` 取截图看一眼；本人想自己看可以开 `/desktop?token=` 远程桌面（只看不点）。
3. 登录后 `/status` 变回 `logged_in: true`，tick.py 自动接着干。

铁律：
- **只在没登录时调 `/relogin`**（在线时接口会拒绝）；它只重启微信进程，最多 10 分钟一次（wxtest 卡住时已经会自己做）。
- **不要重启容器**（`docker restart` 会让在线的号也重新走登录确认）。更新了 `app/` 代码就 `docker cp` 进去再 `POST /reload`，只重载接口，微信不受影响。
- 扫码页、令牌只发给本人，不发给任何联系人。

接口：
- `GET /status` → `logged_in`、`login_stage`（scan / confirm / starting / stuck）、`agents`（在线 agent 名单）
- `POST /relogin` → 掉线自修：重启微信进程回到登录页，自动点「登录」等手机确认，超时出新二维码
- `GET /qr?token=` → 扫码页；`GET /screen` → 屏幕截图 PNG
- `POST /reload` → 只重载接口进程（用上新代码），微信不动

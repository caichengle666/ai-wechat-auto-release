# 部署与安装（第一次装才读）

## 第零步：先跟用户说清要准备什么（一次说完，按用户要的功能列）
把下面这张清单原样发给用户，让 TA 勾要哪些可选功能，没勾的就不配：

> 必须准备：
> 1. 一台常开、装了 Docker 的 Linux 机器（x86_64 或 arm64，建议 2G 内存以上，能上外网），用来跑电脑版微信。
> 2. 一部登着你微信的手机：第一次要扫码，以后容器重启要在手机上点确认。
> 3. 外网地址（AI 和微信不在一台机器）：推荐一个 Cloudflare 免费账号 + 一个托管在 Cloudflare 的域名，做固定地址；没有也行，会用临时地址，但每次重启会变。
> 可选功能（要哪个准备哪个）：
> 4. 语音（对方发语音，AI 回语音）：主用的从 Fish 或其他平台里选一个，Cloudflare 默认加上当备用（主用的不通自动换它；不想要可以说不要）
>    - Fish Audio API key（fish.audio 注册）：可以克隆你自己的声音、多个声音；免费模型有期限（目前到 2026-11-30），之后要付费或改用 Cloudflare。
>    - 其他语音平台（通用接口）：任何兼容 OpenAI 语音接口的平台都行（如 OpenAI、硅基流动），自己在平台上拿 key、选模型和音色；所有人都用这一个音色，不能克隆。
>    - Cloudflare 免费账号：免费、不用绑卡，但只有一种标准女声，不能克隆。
>    顺序是 Fish → 其他平台 → Cloudflare，前一个不通自动换下一个。只想用免费的，只配 Cloudflare 也行。
> 5. 看懂视频（好友发视频，AI 听完再聊）：一个谷歌账号，能打开 notebooklm.google.com；还要一台有浏览器的电脑登录一次导出登录文件。不配的话只看画面截图。
> 6. 掉线告警发到手机（可选）：Bark、邮箱或 webhook 地址，见 `docs/settings.md` 的 `alert`。

## 第一步：部署

先 `curl $AWX_BASE/health` 看有没有现成的服务；通了就跳到「第二步：让用户自己设定」。

### 必须问用户、不能自己定的
一次问清，给出推荐项让用户回个「好」就行：
1. **装在哪台机器**：要一台常开、有 Docker 的 Linux（x86_64 或 arm64 都行，镜像自动选）。不要替用户挑机器。
2. **外网怎么访问**：AI（Muse 等 agent）一般和微信不在一台机器，必须有外网地址。默认走 Cloudflare 隧道（只往外连，机器不用公网 IP）：
   - **推荐** `CF_TUNNEL_TOKEN` + `WX_PUBLIC_URL`：用户自己的 Cloudflare 命名隧道，固定域名，搬机器地址不变
   - 什么都不给：自动开免账号临时隧道，但**每次重启地址会变**
   - 用户有自己的公网端口 / HTTPS 反代：加 `WX_TUNNEL=off`
3. **能不能发消息**：只读（`WX_SEND=0`）还是可发；要不要 `WX_SEND_ALLOW` 白名单只准发给指定人。设了白名单要把 `filehelper` 也写进去，不然装 skill 的命令和掉线告警发不到文件传输助手。
4. **助理设置**：见「第二步」，部署完再填。

### AI 自己定、不用问的
```bash
docker run -d --name ai-wechat-auto --restart unless-stopped \
  --cap-add=SYS_PTRACE --shm-size 512m \
  -v wxdata:/data \
  -p 127.0.0.1:18500:18500 \
  ghcr.io/caichengle666/ai-wechat-auto-bin:latest
```
命名隧道加 `-e CF_TUNNEL_TOKEN=... -e WX_PUBLIC_URL=https://域名`，两个都要给，少了 `WX_PUBLIC_URL` wxtest 不知道自己的地址（不加就是临时隧道，`docker logs` 里找 `[tunnel]`）；不要隧道加 `-e WX_TUNNEL=off`；只读加 `-e WX_SEND=0`。
- `--cap-add=SYS_PTRACE` **不能省**，否则抓不到数据库密钥。
- 端口只绑 `127.0.0.1`，对外只走用户选的那一种方式；只开 18500 一个端口（API、扫码页、远程桌面都在上面）。
- 卷 `/data` 存登录态和密钥，重建容器只要卷还在就不用重扫码。

### 登录（需要用户本人）
- 令牌：`docker exec ai-wechat-auto cat /data/wxauto/api_token`
- 首次：让用户用手机微信扫码。二维码三选一：`docker logs` 字符画、`<地址>/qr?token=令牌`、控制面板里的远程桌面（`<地址>/panel`，本人登录后用验证码打开）。扫码页要在**别的屏幕**打开，手机才扫得到。
- 以前登过：会自动点「登录」，只需用户在手机上点确认。
- 等 `/status` 出现 `logged_in:true`、`keys_ready:true`、`ctrl_enter:true` 才算就绪；`ctrl_enter` 不是 true 时 `/send` 会拒绝。用户看不懂 JSON 的话，让 TA 打开体检页 `<地址>/check?token=令牌`，哪项不对一眼看出、截图就能排查。

### 给 AI 装 skill（第一次）
skill 跟镜像走，从用户自己的 wxtest 拉（最省事）；也可从公开仓库 https://github.com/caichengle666/ai-wechat-auto-release 的 `skill/` 目录下载，再自己写 `awx.env`。微信登录好以后，wxtest 会把一段填好地址和令牌的话发到用户的**文件传输助手**一次，用户整段转给 AI。AI 按这个顺序做，每步把输出原样给用户看，出错就停下说原因，不要自己改代码：
0. **先自报**：你是哪个 AI 平台；能不能跑 shell 命令（要有 curl 和 python3）；能不能建每 10 秒跑一次的定时任务（hook，值班要用）。有一项不能就停下告诉用户，别硬装。
1. 建目录并写配置（只有自己能读）：
```bash
mkdir -p muse-wechat && cd muse-wechat
(umask 077; printf 'AWX_BASE=%s\nAWX_TOKEN=%s\n' '<地址>' '<令牌>' > awx.env)
```
2. 下载安装脚本，先读一遍再跑（不要用 `curl | python3` 管道）：
```bash
curl -fsSL -A awx -o install.py <地址>/skill?install=1
python3 install.py
```
脚本先自检：Python 版本、连不连得上 wxtest、令牌对不对（这三项不过就停下，按它说的原因告诉用户）；微信没登录、发送键没确认只提示，可以先装。然后把 skill 写到当前目录，打印**体检页**（`<地址>/check?token=令牌`）和**控制面板**（`<地址>/panel`，不带令牌）。**装完第一件事：把这两个地址发给用户本人**（只发本人；你第一次连上后 wxtest 也会往本人文件传输助手发一条「装好了」新手引导）：控制面板里能改设置、打开远程桌面看微信界面（掉线扫码也用它），本人第一次打开设账号密码（验证码发到文件传输助手，微信没登录才用令牌），以后登录和开远程桌面都要发到文件传输助手的验证码；体检页用大白话列出哪里不对，出问题让用户截图（地址栏裁掉）就能排查，不用跑命令。然后接着做「第二步」。已经装过的目录不会重装；以后的升级由 wxtest 自动派，不用再跑。临时隧道重启后地址会变，wxtest 会再往文件传输助手发一条新地址，让 AI 改 `awx.env` 的 `AWX_BASE`。

### 常见问题
- AI 平台（如 Muse）弹出访问 wxtest 域名的出网审批：让用户选「该站点永久允许」，只点一次以后不再问；只选本次，下载 skill 会在半路被掐断。审批有时要几次请求后才弹出，install.py 被掐断时会自己重试约 2.5 分钟等它，不用重跑。
- 一直停在「登录」按钮、手机收不到确认：`docker restart ai-wechat-auto`。
- 同一个微信同时只能登一处 Linux 微信，换机器部署后旧的那台会掉线。
- 令牌等于微信控制权，别贴到公开地方；公网访问也必须带令牌。

### 语音（用户第零步勾了才配，不要就跳过，并把设置 `voice_reply` 改成 off）
主用的按用户选的配（A Fish 或 B 通用接口，也可以都不要）；C Cloudflare 默认都配上当备用，用户明确说不要才跳过。顺序固定 Fish → 通用接口 → Cloudflare，前一个不通自动换下一个，只配哪一个都能用。不想要某一种：`awx.api('/tts',{'drop':'fish'})`（`oai`、`cf` 同理）。key、令牌都只存在微信那台的数据目录，不进 skill 文件，用完从对话里忘掉。

#### A. Fish Audio（能克隆声音、多个声音）
把这段原样发给用户：
> 1. 打开 https://fish.audio 注册登录。
> 2. 右上角头像 →「API Keys」→ 新建一个，复制发给我。
> 免费模型有期限（目前到 2026-11-30），到期要在 Fish 充值，或者改用 Cloudflare。
拿到后：
```bash
python3 -c "import awx,json;print(json.dumps(awx.api('/tts',{'fish_key':'用户给的key'}),ensure_ascii=False))"
```
`GET /tts` 看到 `https://api.fish.audio` 即成功。代码不带任何自带声音（没克隆前是 Fish 默认音色）；把 `docs/voice.md` 原样发给用户，照着做就能克隆成 TA 自己的声音（wxtest 自己克隆，会回一条试听）。

#### B. 其他语音平台（通用接口，兼容 OpenAI 语音格式的都行）
问用户用哪家，让 TA 在那家后台拿四样东西发给你：接口地址（写到 `/v1` 这一级，如 `https://api.openai.com/v1`）、API key、语音模型名、音色名（各家写法不同，以那家文档为准，你可以帮 TA 查）。拿到后：
```bash
python3 -c "import awx,json;print(json.dumps(awx.api('/tts',{'oai_url':'地址','oai_key':'key','oai_model':'模型','oai_voice':'音色'}),ensure_ascii=False))"
```
wxtest 保存后当场合成一句试：回 `"ok": true` 带 `合成成功 N 秒` 即成功；`"ok": false` 时 `error` 里是平台原话（key 错、模型名或音色名不对），照着让用户改了再跑一次。所有声音都用这一个音色、不能克隆，`docs/voice.md` 里的克隆命令只对 Fish 有效，跟用户说清楚。

#### C. Cloudflare（免费、只有一种标准女声、不能克隆）
把这段原样发给用户：
> 1. 打开 https://dash.cloudflare.com 注册/登录（免费账号就行，不用绑卡）。
> 2. 左边菜单「管理账户」→「账户 API 令牌」→「创建令牌」。
> 3. 「权限策略」点「Full account and zone access」（全部权限，最省事）。
> 4. 「令牌过期时间」选「7 天」（令牌只用来部署这一次；部署好的语音服务用自己的密钥，令牌过期、删掉都不影响合成）→ 拉到底点「创建令牌」。
> 5. 把显示的令牌复制发给我（只显示这一次）。我用一次部署完就丢，不保存；以后不想用了，在同一页把它删掉即可。
拿到后在 skill 目录跑（令牌只放命令行环境变量，别写进任何文件）：
```bash
CF_TOKEN='用户给的令牌' python3 cftts.py
```
它在用户账号部署 Worker `wxtts`、生成专用密钥、告诉 wxtest（`POST /tts`）。报权限错就让用户按第 2~4 步重建。`GET /tts` 能看到 workers.dev 地址即成功。

都不通时，自动回复的语音改发文字，不会发不出去。

### 看懂视频：NotebookLM（用户第零步勾了才配）
有人声的视频交给 NotebookLM 听完回答；不配也能用，只是改看画面截图。把这段原样发给用户（要在**有浏览器的电脑**上做，Windows、Mac、Linux 都行）：
> 1. 先确认你的谷歌账号能打开 https://notebooklm.google.com 并新建笔记本。
> 2. 电脑上装好 Python 3.10 以上，打开终端（Windows 用 PowerShell）依次运行：
>    `pip install "notebooklm-py[browser]"`
>    `notebooklm login`
>    会弹出浏览器，登录你的谷歌账号，看到 NotebookLM 首页后回终端按回车。
> 3. 运行 `notebooklm auth check --test`，看到 ok 就成功了。
> 4. 运行 `notebooklm status --paths`，「Storage State」那一行就是登录文件（一般是用户目录下 `.notebooklm/profiles/default/storage_state.json`，Windows 在 `C:\Users\你的用户名\.notebooklm\profiles\default\`），把这个文件发给我。
> 这个文件等于谷歌账号的登录凭据，只发给我，别发到群里。登录失效时（一般几周）我会提醒你，重做第 2~4 步即可。
拿到文件后在 skill 目录跑（文件放临时目录，传完立刻删）：
```bash
python3 -c "import awx,json;print(json.dumps(awx.api('/video/login',json.load(open('/tmp/storage_state.json'))),ensure_ascii=False))" && rm -f /tmp/storage_state.json
```
回 `{"ok": true, "notebooks": 数字}` 即成功；报错说明文件不对或已失效，让用户重新登录导出。

## 第二步：让用户自己设定（隐私，必须由用户本人提供）
**先看是不是加第二台、第三台**：`python3 -c "import awx;print(awx.api('/status')['agents'])"` 里已经有别的 agent，说明用户在别的 AI 上填过设置，**不要再从头问**：只问用户给这台起个名字（别和名单里的重名），然后 `python3 psync.py join 名字`，它会从 wxtest 拿共用设置写好 `settings.json`，直接做第三步。名单是空的才是第一台，按下面逐项问。

`cp settings.example.json settings.json`，然后**打开 `docs/settings.md`，按里面的说明逐项问用户**：每项讲清用途、使用场景和默认值，用户说默认就不填，想改就照 TA 说的写。`sign`、`voice_sign` 必须单独问。红线 `redlines` 也必须单独问（AI 绝不能说、不能答应的事）：用户自己说的照抄；用户说不知道、默认或不写，就按 `docs/settings.md` 里的通用模板替 TA 写一份，念给 TA 听、TA 点头再写进去，不能留空。标签也要单独问，三层：大类（最粗，如工作、亲友）→ 每个大类下的关系（如客户、同事；家人、朋友）→ 补充（AI 看出来自己加）。让用户按自己的圈子说，写进 `label_top`（`工作=客户,同事;亲友=家人,朋友`），不要替 TA 编、不要套别的行业；用户不想要就留空，AI 就不给人打标签。

## 第三步：初始化
```bash
cat > awx.env <<'X'                 # wxtest凭据存本地文件，agent 重启/忘了上下文也不断；不进 git、不外发
AWX_BASE=部署时选的外网地址          # agent 和微信不在一台机器，走外网
AWX_TOKEN=容器里的 /data/wxauto/api_token
X
chmod 600 awx.env
export AWX_DB=store.db
python3 seed.py        # 读 settings.json 写库、认出本人、导入会话；会把设置回显一遍，让用户确认
python3 alert.py test  # 填了 alert 才跑：发一条测试提醒，问用户收到没有
```
装完告诉用户：在微信「文件传输助手」发「教程」，会收到完整使用说明（所有命令和用法）。

## 第四步：一次性：批量画像
反复做，直到输出 `{"tasks": []}`：
1. `python3 persona.py next 5` → 得到最多 5 个任务，每个有 `history`（可能带 `ask_label`）。
2. 对每个任务按 SKILL.md「写回复的规矩」里的「画像」读 `history`，写出 `{"profile": {...}}`（有 `ask_label` 一并打标签）。
3. 写库：`python3 act.py <chat> <<'EOF'` 换行贴 JSON 再换行 `EOF`（用 heredoc，免得回复里的引号把命令弄坏）。


## 多个 agent 同时接
可以在几台机器上各装一份、连同一个微信，防止一个 agent 掉了没人回：
- 每份都按本文件装好、各自 `seed.py` 和画像（`store.db` 各管各的），`agent` 名字问用户起、各不相同（没填不领任务），都跑值班循环 `watch.py`（见 SKILL.md「常驻」）。每份手里只拿一条，其余的留给别的副本，所以多一份就多一路并行。画像和 `rules/` 各存本地，经 wxtest 即时互相同步（哪台改了马上推、别台马上对齐，掉线回来先对齐），空闲时每 `sync_min` 分钟再兜底一次（见 docs/settings.md），新上岗的一份 `watch.py setup` 时会先拉全量。除 `agent`、`wake`、`vision` 外的设置也一起同步：在任一台改 settings.json 跑 seed.py，别台跟着改。几台 skill 代码不一致、两台同名、有一台没名字，wxtest 都会发文件传输助手提醒本人；两台同名时只给先来的派任务（后来的领任务、交结论、心跳都被挡），后来的那台每 30 分钟经 Muse 提醒一次去改名；先来的 3 分钟没动静（重装、沙箱重启）后来的自动接班。
- 从别的副本拷 `store.db` 过来的，拷完要再跑一次 `seed.py`，否则库里还是原来那台的名字。
- 装完自查：`watch.py` 跑起来后，在本份目录跑
  `python3 -c "import awx;print(awx.AGENT, awx.api('/status')['agents'])"`
  前面打出的名字必须是这份自己的、跟其他副本不重名（重名时 wxtest 只给先来的那台派任务，另一台干等）；后面的在线名单里要有它、`hb_ago` 在 60 以内，没有就是 `watch.py` 没在跑（看 `watch.log`）或连不上 wxtest。
- wxtest 按租约派任务：一条任务只派给一个 agent；它的后台心跳（`hb.py`，`tick.py` 自动拉起）每 20 秒一次，只防掉线，60 秒没心跳就把它手里的任务收回给别的 agent，单条 5 分钟没交也收回；收回后旧结论交上来会被拒，所以不会回两次。文件传输助手的管理命令每个在线 agent 各收一份（各自的库都要改），只有一个回话。


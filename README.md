# ai-wechat-auto

这里只放安装说明、编译好的镜像和 AI 用的 skill。镜像：[ghcr.io/caichengle666/ai-wechat-auto-bin](https://github.com/users/caichengle666/packages/container/package/ai-wechat-auto-bin)（x86_64 / arm64）。

把电脑版微信装进 Docker，让你自己的 AI 助理（Muse 等）帮你看消息、回消息。微信和 AI 不在同一台机器上。

## 要准备
1. 一台常开、装了 Docker 的 Linux 机器（x86_64 或 arm64，2G 内存以上，能上外网）。
2. 一部登着你微信的手机：第一次要扫码，以后容器重启要在手机上点确认。
3. 一个 AI 助理（Muse 等），它那台机器要有 curl 和 python3。
4. 可选：Cloudflare 免费账号和一个托管在 Cloudflare 的域名，用来做固定地址。没有也能用，但每次重启地址都会变。

## 第 1 步：启动
```bash
docker run -d --name ai-wechat-auto --restart unless-stopped \
  --cap-add=SYS_PTRACE --shm-size 512m \
  -v wxdata:/data -p 127.0.0.1:18500:18500 \
  ghcr.io/caichengle666/ai-wechat-auto-bin:latest
```
- 有固定域名：加 `-e CF_TUNNEL_TOKEN=隧道令牌 -e WX_PUBLIC_URL=https://你的域名`，两个都要给。
- `--cap-add=SYS_PTRACE` 不能省。

## 第 2 步：扫码登录
```bash
docker logs -f ai-wechat-auto
```
日志里会出现字符画二维码，用手机微信扫码并确认。扫不了的话，用日志里 `[tunnel] 扫码页` 那个地址在另一块屏幕上打开（`<令牌>` 用 `docker exec ai-wechat-auto cat /data/wxauto/api_token` 取）。

## 第 3 步：交给 AI
登录好后，你的微信「文件传输助手」会收到一条「给 AI 装微信助理」，把两条横线之间的整段原样发给你的 AI，它会先自检再装好，然后一步步问你设置。同一条消息里还有远程桌面和体检页地址：远程桌面能看到这台微信的界面，掉线扫码也用它；体检页用大白话列出哪里不对，出问题截图（地址栏裁掉）发给帮你的人就行，不用跑命令。建议都收藏。

- 那段话里有令牌，等于你微信的控制权：只发给你自己的 AI，别转给别人。
- 找不到那条了，或要再装一台 AI：在文件传输助手发「装AI」，会再收到一份。

## 控制面板
浏览器打开 `你的地址/panel`（文件传输助手那条消息里有链接），第一次打开设个账号密码，验证码会发到你的文件传输助手（微信没登录时改填令牌）。设置、哪些群回哪些不回、给 AI 定的规则、声音都能在这里改，每项都有说明，改完 AI 自动收到。
- 没用固定域名时，重启后地址会变，文件传输助手会再收到一条新地址，转给 AI 即可。
- 以后的升级由容器自动推给 AI，不用再操作。

## 外部工具（可选）
有 MCP 服务（笔记、网盘、智能家居、自己写的系统等），在控制面板「外部工具」里接给 AI，可以接多个：远程的填地址和令牌（新版 Streamable HTTP 和旧版 SSE 自动识别）；只在本机跑的（stdio）选「本机程序」填一行命令（如 `npx -y 包名`、`uvx 包名`），它在容器里单独的低权限用户下跑，碰不到微信和聊天记录、连不了本机端口。本机程序需要启动时加 `--cap-add=NET_ADMIN`，没加就不放行。令牌只存在你的容器里，AI 看不到。每个工具可以单独关掉，整个服务也能一键停用。你在微信「自己和自己的聊天」里交代的事，AI 会按需要调用它们；回别人消息时只用来查资料，不会用它改东西。

## 导入手机里的老聊天记录

电脑上默认只有登录以后的记录。要把手机里的老聊天搬进来，见 [skill/docs/migration.md](skill/docs/migration.md)，也可以直接跟你的 AI 说「帮我导入聊天记录」，它会照着这篇一步步带你做（要家里一台常开的 Linux 设备，比如旁路由、NAS、小主机，再装 Tailscale）。

## 升级
镜像有新版时，在装微信的机器上换新容器（登录数据在 wxdata 里不会丢，手机上点一下确认即可）：
```bash
docker pull ghcr.io/caichengle666/ai-wechat-auto-bin:latest
docker rm -f ai-wechat-auto
```
然后用第 1 步同一条 `docker run` 命令再启动（加过的 `-e` 参数照样带上）。新容器起来后，几分钟内会自动把新 skill 推给 AI，不用动 AI 那边。

## 另一种装 skill 的方式：从这个仓库下载
文件传输助手那段话最省事（地址和令牌已填好）。也可以让 AI 直接从这里下载 `skill/` 目录：
```bash
mkdir -p muse-wechat && curl -fsSL https://github.com/caichengle666/ai-wechat-auto-release/archive/refs/heads/main.tar.gz \
  | tar xz --strip-components=2 -C muse-wechat ai-wechat-auto-release-main/skill
cd muse-wechat && (umask 077; printf 'AWX_BASE=<地址>\nAWX_TOKEN=<令牌>\n' > awx.env)
```
然后让 AI 读 `SKILL.md` 接着做。两种方式装出来一样，以后的升级都由容器自动推给 AI。

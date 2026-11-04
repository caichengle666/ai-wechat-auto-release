# ai-wechat-auto

这里只放安装说明、编译好的镜像和 AI 用的 skill，源码不公开。镜像：[ghcr.io/caichengle666/ai-wechat-auto-bin](https://github.com/users/caichengle666/packages/container/package/ai-wechat-auto-bin)（x86_64 / arm64）。

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
登录好后，你的微信「文件传输助手」会收到一条「给 AI 装微信助理」，里面有一整句命令。把这句原样发给你的 AI，它会自己装好，然后一步步问你设置。

- 那句命令里有令牌，等于你微信的控制权：只发给你自己的 AI，别转给别人。
- 没用固定域名时，重启后地址会变，文件传输助手会再收到一条新地址，转给 AI 即可。
- 以后的升级由容器自动推给 AI，不用再操作。

## 另一种装 skill 的方式：从这个仓库下载
文件传输助手那句命令最省事（地址和令牌已填好）。也可以让 AI 直接从这里下载 `skill/` 目录：
```bash
mkdir -p muse-wechat && curl -fsSL https://github.com/caichengle666/ai-wechat-auto-release/archive/refs/heads/main.tar.gz \
  | tar xz --strip-components=2 -C muse-wechat ai-wechat-auto-release-main/skill
cd muse-wechat && (umask 077; printf 'AWX_BASE=<地址>\nAWX_TOKEN=<令牌>\n' > awx.env)
```
然后让 AI 读 `SKILL.md` 接着做。两种方式装出来一样，以后的升级都由容器自动推给 AI。

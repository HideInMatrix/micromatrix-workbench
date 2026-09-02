# Linux 服务器部署与运维

本文面向无桌面环境的 Linux 服务器，提供两种受支持的部署方式：

- systemd：直接从源码运行，适合固定 VPS、需要宿主机工具链和 Linux `bubblewrap` 沙箱的场景。
- Docker Compose：使用无 GUI 的最小 Server 镜像，适合希望隔离依赖、快速迁移和标准化交付的场景。

两种方式都运行同一个 `start.py` / `agent_workbench.cli` 入口，不维护独立的 Runtime 实现。
GitHub Release 中的 Linux 压缩包是桌面应用，不是本文使用的 headless Server 包。

如果目标是让 AI 检查服务器安全、系统配置和运行环境，请重点阅读
[第 4 节：服务器安全审计模式](#4-服务器安全审计模式)。该模式与普通项目 Workspace
分离，默认只读主机配置并把报告写入独立目录。

## 1. 部署模型

生产环境推荐保持 Runtime 只对本机开放：

```text
Remote MCP Client
       |
       | HTTPS 443
       v
Nginx / Caddy / Cloudflare Tunnel
       |
       | HTTP 127.0.0.1:8234
       v
MicroMatrix Workbench start.py
       |
       v
/srv/micromatrix-workspace
```

不要把 8234 端口直接暴露到公网。公网入口应使用 HTTPS，并将
`AGENT_RUNTIME_SERVER_URL` 设置为客户端实际访问的 canonical URL。

## 2. 通用前置条件

- Linux x86_64 或 ARM64。
- Python 3.11 以上；项目发布 CI 使用 Python 3.13。
- 一个明确、范围尽可能小的 Workspace 目录。
- 一个固定的 HTTPS 域名或受支持的 Tunnel Provider。
- `AGENT_RUNTIME_OAUTH_PASSWORD` 使用独立强随机值。
- DNS、TLS、防火墙和反向代理已经准备好。

生成随机密码示例：

```bash
openssl rand -base64 48
```

Server 运行依赖位于仓库根目录的 `requirements-server.txt`。它不包含
`pywebview`、PyInstaller 等桌面构建依赖。

## 3. 使用 systemd 部署

以下示例使用这些固定路径：

```text
/opt/micromatrix-workbench                 程序源码
/opt/micromatrix-workbench/.venv           Python 虚拟环境
/srv/micromatrix-workspace                 AI 可访问的 Workspace
/etc/micromatrix-workbench/server.env      Server 配置和 Secret
/var/lib/micromatrix-workbench             服务账户 HOME / OAuth 持久化状态
```

如需更换路径，复制并同步修改
`deploy/linux/micromatrix-workbench.service` 中的 `WorkingDirectory`、
`ExecStartPre`、`ExecStart` 和 `ReadWritePaths`。

### 3.1 安装系统依赖

Ubuntu / Debian：

```bash
sudo apt-get update
sudo apt-get install -y git python3 python3-venv bubblewrap nginx
```

创建独立服务用户和目录：

```bash
sudo useradd --system \
  --home-dir /var/lib/micromatrix-workbench \
  --create-home \
  --shell /usr/sbin/nologin \
  micromatrix

sudo install -d -o root -g root -m 0755 /opt/micromatrix-workbench
sudo install -d -o micromatrix -g micromatrix -m 0750 /srv/micromatrix-workspace
sudo install -d -o root -g micromatrix -m 0750 /etc/micromatrix-workbench
```

如果 Workspace 已经存在，不要直接递归修改其所有者。应根据现有权限模型给
`micromatrix` 用户授予所需的最小读写权限。

### 3.2 安装源码和 Server 依赖

将仓库放到 `/opt/micromatrix-workbench`，并固定到需要部署的 release tag：

```bash
sudo git clone https://github.com/HideInMatrix/micromatrix-workbench.git \
  /opt/micromatrix-workbench
cd /opt/micromatrix-workbench
sudo git checkout <release-tag>

sudo python3 -m venv .venv
sudo .venv/bin/python -m pip install --upgrade pip
sudo .venv/bin/python -m pip install -r requirements-server.txt
```

正式环境应固定到经过验证的 tag 或 commit，不建议直接跟随会变化的分支。

### 3.3 配置 Server

```bash
sudo install -o root -g micromatrix -m 0640 \
  deploy/linux/server.env.example \
  /etc/micromatrix-workbench/server.env
sudoedit /etc/micromatrix-workbench/server.env
```

使用 Nginx/Caddy 时推荐：

```env
AGENT_RUNTIME_OAUTH_PASSWORD="替换为强随机密码"
AGENT_RUNTIME_NETWORK_PROVIDER="external"
AGENT_RUNTIME_SERVER_URL="https://mcp.example.com"
AGENT_RUNTIME_PERMISSION_MODE="safe"
AGENT_RUNTIME_ALLOW_NETWORK="0"
AGENT_RUNTIME_OS_SANDBOX="require"
```

`AGENT_RUNTIME_OS_SANDBOX=require` 会在 `bubblewrap` 不存在、不可执行或探测失败时
拒绝启动，防止服务无声降级到仅应用层策略。

### 3.4 安装并启动 unit

```bash
sudo install -o root -g root -m 0644 \
  deploy/linux/micromatrix-workbench.service \
  /etc/systemd/system/micromatrix-workbench.service

sudo systemctl daemon-reload
sudo systemctl enable --now micromatrix-workbench.service
```

unit 每次启动前都会执行 `--check-config`。配置不完整时，主进程不会启动。

检查状态和日志：

```bash
systemctl status micromatrix-workbench.service
journalctl -u micromatrix-workbench.service -f
```

检查本地健康端点：

```bash
curl --fail --silent \
  http://127.0.0.1:8234/.well-known/micromatrix-workbench-health
```

正常响应为：

```json
{"ok": true}
```

### 3.5 systemd 安全边界

仓库提供的 unit 默认启用：

- 独立 `micromatrix` 用户；
- `ProtectSystem=strict`，仅 Workspace 和 `StateDirectory` 可写；
- `ProtectHome=true`；
- `NoNewPrivileges=true`；
- 空 capability 集合；
- 内核、控制组和时钟保护；
- 仅允许 Unix、IPv4、IPv6 socket family；
- `UMask=0077`。

如果 Workspace 内任务需要读取额外的宿主机工具链路径，应通过 unit override 添加精确的
`ReadOnlyPaths=`，不要关闭整组保护：

```bash
sudo systemctl edit micromatrix-workbench.service
```

示例：

```ini
[Service]
ReadOnlyPaths=/opt/toolchains/go
```

修改后执行：

```bash
sudo systemctl daemon-reload
sudo systemctl restart micromatrix-workbench.service
```

## 4. 服务器安全审计模式

普通 `micromatrix-workbench.service` 只把一个项目目录作为 Workspace，适合代码、依赖和
项目运行环境操作。主机安全检查应使用独立的
`micromatrix-workbench-audit.service`，不要把 Workspace 直接设置为 `/`。

审计 unit 会将筛选后的主机信息映射到：

```text
/srv/micromatrix-audit/host       只读主机视图
/srv/micromatrix-audit/reports    AI 可写的报告和修复提案
```

默认只读视图覆盖：

- OS、用户/组、挂载和 DNS 基础配置；
- sysctl、PAM、sudoers、SSH Server 配置；
- systemd units；
- Nginx、Apache、Caddy、Docker、containerd 配置；
- UFW、firewalld、fail2ban、cron 配置；
- 内核参数、网络状态、已加载模块和 cgroup 信息；
- auth/secure、kernel、audit 等存在时的安全日志。

模板明确不映射 `/etc/shadow`、`/root`、SSH/TLS 私钥、进程环境、Docker Socket 和容器
rootfs。部署前仍应逐行审查 `BindReadOnlyPaths=`；如果某个配置目录包含业务 Secret，删除
对应映射。

### 4.1 创建审计 Workspace

systemd 能创建大部分 bind mount 目标，但应先创建稳定的父目录和报告目录：

```bash
sudo install -d -o root -g micromatrix -m 0750 \
  /srv/micromatrix-audit \
  /srv/micromatrix-audit/host \
  /srv/micromatrix-audit/host/manual \
  /srv/micromatrix-audit/host/etc \
  /srv/micromatrix-audit/host/usr/lib \
  /srv/micromatrix-audit/host/lib \
  /srv/micromatrix-audit/host/proc \
  /srv/micromatrix-audit/host/sys/fs \
  /srv/micromatrix-audit/host/var/log \
  /srv/micromatrix-audit/host/run/log

sudo install -d -o micromatrix -g micromatrix -m 0750 \
  /srv/micromatrix-audit/reports
```

### 4.2 安装审计配置和 unit

审计服务使用独立端口 `8235`、独立公网域名和独立 OAuth 状态：

```bash
sudo install -o root -g micromatrix -m 0640 \
  deploy/linux/audit.env.example \
  /etc/micromatrix-workbench/audit.env
sudoedit /etc/micromatrix-workbench/audit.env

sudo install -o root -g root -m 0644 \
  deploy/linux/micromatrix-workbench-audit.service \
  /etc/systemd/system/micromatrix-workbench-audit.service

sudo systemctl daemon-reload
sudo systemctl enable --now micromatrix-workbench-audit.service
```

Nginx/Caddy 应把审计专用域名回源到 `127.0.0.1:8235`。不要让普通项目服务和审计服务
共用 OAuth Password、域名或配置文件。

验证只读边界：

```bash
sudo -u micromatrix test -w /srv/micromatrix-audit/reports
systemctl status micromatrix-workbench-audit.service
curl --fail --silent \
  http://127.0.0.1:8235/.well-known/micromatrix-workbench-health
```

连接后可让 AI 检查 Workspace 内的 `host/` 并把结果写到 `reports/`。适合的任务包括：

- SSH、sudo、PAM、sysctl 和防火墙基线检查；
- 监听端口、服务状态、启动项、定时任务和异常日志分析；
- Nginx/Caddy/TLS、Docker/containerd、systemd unit 配置审查；
- 输出修复优先级、配置 diff、验证命令和回滚步骤。

可直接使用下面的首轮指令：

```text
对 Workspace 内的 host/ 执行只读 Linux 安全基线审计。先记录 OS、内核、暴露面和服务清单，再检查
SSH、sudo/PAM、sysctl、防火墙、systemd、Web Server、容器运行时和安全日志。
把“观察到的证据”和“推断”分开；不要尝试修改 host/。最终将 Markdown 报告、建议的
unified diff、验证命令和逐项回滚命令写入 reports/，按 Critical/High/Medium/Low 排序。
```

读取 journal 需要发行版对应的日志组。确有需要时可将服务用户加入
`systemd-journal` 或 `adm`，但这会扩大可见日志范围：

```bash
sudo usermod -aG systemd-journal,adm micromatrix
sudo systemctl restart micromatrix-workbench-audit.service
```

不存在的组应从命令中删除。

只读 bind mount 不会绕过原文件的 Unix 权限。对于仍仅 root 可读的文件，不要为了 AI
审计而把原文件改成全局可读；应由管理员将确认不含 Secret 的副本放入 `host/manual/`，
或只提供经过脱敏的命令输出。

持久 journal 可通过下面的路径分析：

```bash
journalctl --directory=host/var/log/journal --no-pager
```

如果发行版只使用 volatile journal，则改用审计 Workspace 中的 `host/run/log/journal`。

### 4.3 审计与变更的权限边界

默认模板对能力作如下区分：

| 操作 | 默认支持 | 说明 |
|---|---:|---|
| 读取映射后的系统配置 | 是 | 只读 bind mount，文件工具可直接分析 |
| 查询非特权系统状态 | 是 | 受 `safe` 权限策略和服务用户权限约束 |
| 在 `reports/` 生成报告/diff | 是 | 唯一默认可写的审计目录 |
| 在普通项目 Workspace 建 venv/npm 环境 | 是 | 需要时单独授权网络能力 |
| 修改 `/etc`、内核参数或防火墙 | 否 | 默认生成提案，由管理员审查后应用 |
| `apt`、任意 `systemctl`、`sudo` | 否 | 被非 root、NoNewPrivileges 和空 capabilities 阻止 |
| 访问 Docker Socket | 否 | 等价于高概率宿主机 root，不提供默认挂载 |

这是刻意的安全边界：一个能被远程 AI 调用的“安全审计服务”不应同时拥有无约束 root。
AI 可以在 `reports/` 生成完整替换文件、unified diff、校验命令和回滚命令，管理员审查后再
应用。若未来需要自动应用，应实现独立的、路径与动作双白名单的 privileged broker，而不是
把当前服务改为 root 或给容器挂载 `/var/run/docker.sock`。

### 4.4 项目环境配置

如果“配置环境”指项目自身环境，例如 Python venv、Node.js 依赖、构建、测试和项目服务，
应使用普通 `/srv/micromatrix-workspace` 服务，而不是审计服务。保持
`AGENT_RUNTIME_PERMISSION_MODE=safe`，只有确实需要下载依赖时才设置：

```env
AGENT_RUNTIME_ALLOW_NETWORK="1"
```

网络能力允许项目命令访问网络，不会解除 systemd 的宿主机只读边界。

## 5. 使用 Docker Compose 部署

Docker 镜像只包含 Server 运行所需源码和依赖，不包含 Vue 构建、pywebview 或桌面打包工具。
默认容器具备以下约束：

- UID/GID 可配置的非 root 用户；
- 只读根文件系统；
- 所有 Linux capabilities 均移除；
- `no-new-privileges`；
- 仅 Workspace、OAuth 状态卷和 `/tmp` 可写；
- 宿主机端口仅绑定 `127.0.0.1`；
- 内置 HTTP healthcheck；
- `SIGTERM` 优雅停止和自动重启。

### 5.1 准备配置

```bash
cd deploy/docker
cp server.env.example server.env
chmod 600 server.env
```

编辑 `server.env`，至少设置 OAuth Password 和公网 HTTPS URL。

设置 Workspace 和容器 UID/GID。UID/GID 应能访问宿主机 Workspace：

```bash
export MICROMATRIX_WORKSPACE=/srv/micromatrix-workspace
export MICROMATRIX_UID="$(stat -c '%u' "$MICROMATRIX_WORKSPACE")"
export MICROMATRIX_GID="$(stat -c '%g' "$MICROMATRIX_WORKSPACE")"
```

这些变量也可以写入 `deploy/docker/.env`；该文件不得提交到 Git。

### 5.2 预检、构建和启动

先验证 Compose 展开结果：

```bash
docker compose config
```

构建镜像：

```bash
docker compose build
```

只运行配置预检：

```bash
docker compose run --rm server \
  /workspace \
  --host 0.0.0.0 \
  --port 8234 \
  --env-file /run/micromatrix/server.env \
  --check-config
```

启动：

```bash
docker compose up -d
docker compose ps
docker compose logs -f server
```

宿主机健康检查：

```bash
curl --fail --silent \
  http://127.0.0.1:8234/.well-known/micromatrix-workbench-health
```

### 5.3 Docker 中的 OS sandbox

默认 Docker 配置使用 `AGENT_RUNTIME_OS_SANDBOX=auto`。镜像没有为嵌套
`bubblewrap` 提供额外 capability 或宽松 seccomp；当 bubblewrap 不可用时，Runtime
仍保留应用层权限策略，外层由只读根文件系统、最小挂载、非 root、cap-drop 和
no-new-privileges 提供隔离。

不要简单给容器增加 `--privileged`。如果必须在容器内强制 bubblewrap，应先设计专用
seccomp/user namespace 配置并重新验证威胁边界。

### 5.4 停止和删除

```bash
docker compose down
```

上述命令保留命名状态卷。只有确认不再需要 OAuth Client 注册、Token Secret 等持久化状态时，
才执行：

```bash
docker compose down --volumes
```

删除状态卷会使现有客户端授权失效，需要重新注册和授权。

Docker 适合隔离项目 Workspace，但默认不用于宿主机安全审计：容器看到的是自己的
`/proc`、网络和 systemd namespace。不要为获得宿主机视图而挂载 Docker Socket、`/` 或
使用 `--privileged`；宿主机审计使用第 4 节的 systemd profile。

## 6. Nginx / Caddy 反向代理

### 6.1 Nginx

```nginx
server {
    listen 443 ssl http2;
    server_name mcp.example.com;

    ssl_certificate     /etc/letsencrypt/live/mcp.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/mcp.example.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8234;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_buffering off;
        proxy_request_buffering off;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }
}
```

### 6.2 Caddy

```caddyfile
mcp.example.com {
    reverse_proxy 127.0.0.1:8234 {
        flush_interval -1
    }
}
```

反向代理完成后验证：

```bash
curl --fail https://mcp.example.com/.well-known/micromatrix-workbench-health
curl --fail https://mcp.example.com/.well-known/oauth-authorization-server
curl --fail https://mcp.example.com/.well-known/oauth-protected-resource
```

防火墙只需对公网开放 80/443；8234 应保持本机或内部容器网络可见。

## 7. 其他 Network Provider

配置字段统一放在 `server.env`：

| Provider | 必要条件 |
|---|---|
| `external` | `AGENT_RUNTIME_SERVER_URL`，外部 Nginx/Caddy/入口回源到本地端口 |
| `cloudflare` | Quick Tunnel 时 URL/Token 都留空；Named Tunnel 时 URL 与 Tunnel Token 同时填写 |
| `frp` | Public URL、`frpc` 可执行文件和 `frpc.toml` |
| `ngrok` | `ngrok` 可执行文件；固定域名时同时填写 Public URL |
| `tailscale` | 已登录的 `tailscale` CLI 和 Funnel 权限 |

systemd 源码部署会从 `PATH` 或配置的绝对路径查找 Provider 可执行文件。默认 Docker 镜像不包含
这些客户端，Docker 推荐使用 `external`，将 Tunnel/反向代理作为宿主机或独立容器职责。

更完整的 Provider 配置见
[网络提供商安装与部署教程](NETWORK_PROVIDER_BEGINNER_GUIDE.md)。

## 8. 状态、备份与恢复

固定公网 URL 使用 persistent lifecycle，OAuth Token Secret 和已注册 Client 会持久化。

systemd 默认状态目录：

```text
/var/lib/micromatrix-workbench/.config/micromatrix-workbench
```

Docker 默认状态位于 Compose 命名卷：

```text
micromatrix-workbench_state
```

备份时应同时保护：

- Server 配置文件；
- OAuth 状态目录或 Docker volume；
- Workspace 自身的 Git/备份；
- Nginx/Caddy/Tunnel 配置。

备份文件包含认证状态，应采用与 Secret 相同的访问控制。

## 9. 升级与回滚

### 9.1 systemd

升级前先记录当前 commit/tag 并备份状态，然后：

```bash
sudo systemctl stop micromatrix-workbench.service
cd /opt/micromatrix-workbench
sudo git fetch --tags --prune
sudo git checkout <new-release-tag>
sudo .venv/bin/python -m pip install -r requirements-server.txt
sudo .venv/bin/python start.py /srv/micromatrix-workspace \
  --host 127.0.0.1 \
  --port 8234 \
  --env-file /etc/micromatrix-workbench/server.env \
  --check-config
sudo systemctl start micromatrix-workbench.service
```

回滚时 checkout 原 tag、重新同步依赖并重启。不要删除 OAuth 状态目录。

### 9.2 Docker

为镜像设置明确 tag：

```bash
export MICROMATRIX_IMAGE_TAG=<release-tag>
docker compose build
docker compose up -d
```

回滚时切回原源码 tag 和 `MICROMATRIX_IMAGE_TAG` 后重新构建/启动，保留 `state` volume。

## 10. 故障排查

### 配置检查失败

直接运行与服务相同的 `--check-config` 命令。常见原因：Workspace 不存在、OAuth Password
为空、Public URL 格式错误、Provider 的 Token/配置文件不完整。

### systemd 报 sandbox probe 失败

确认：

```bash
command -v bwrap
sudo -u micromatrix /usr/bin/bwrap --version
sysctl kernel.unprivileged_userns_clone
```

不要在未确认风险的情况下把 `require` 改为 `off`。应先修复 bubblewrap 安装、内核 user
namespace 或 unit 限制。

### 容器无法写 Workspace

确认 `MICROMATRIX_UID` / `MICROMATRIX_GID` 与宿主机 Workspace 权限匹配，并检查 bind mount：

```bash
docker compose exec server id
docker compose exec server ls -ld /workspace
```

### 本地健康但公网失败

依次检查本地 health、反向代理 health、DNS、TLS 和
`AGENT_RUNTIME_SERVER_URL`。Public URL 必须与客户端实际访问地址一致。

### OAuth 客户端突然全部失效

检查服务用户 HOME、systemd `StateDirectory` 或 Docker `state` volume 是否被替换/删除。
Persistent lifecycle 依赖其中的 Token Secret 和 Client Registry。

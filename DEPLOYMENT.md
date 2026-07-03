# 部署说明（生产环境）

把这个 RAG 应用上线到真实使用场景的完整步骤:**Ubuntu/Debian 服务器 + uv + systemd + nginx + HTTPS**。

> 架构提示:后端是一个 FastAPI 进程(uvicorn),**同时**提供 `/api/*` 接口和 `/` 前端静态页。
> 数据都在本地文件:`backend/chroma_db/`(向量库)、`backend/users.db`(账号)、`docs/`(课程文档)。
> 因此用 **nginx 反代 + 单进程 uvicorn** 即可,不需要单独的前端服务器。

---

## 0. 前置条件

- 一台 Linux 服务器(Ubuntu 22.04+ / Debian 12+),有 sudo 权限
- 一个域名(如 `rag.example.com`),其 DNS A 记录指向服务器公网 IP
- 开放端口 **80 / 443**(HTTP/HTTPS);**不要**对外开放 8000
- Python 3.13+(uv 可自动安装)

```bash
# 安装 uv（官方脚本）
curl -LsSf https://astral.sh/uv/install.sh | sh
# 安装 nginx / certbot / git
sudo apt update && sudo apt install -y nginx git
sudo apt install -y certbot python3-certbot-nginx
```

---

## 1. 取代码 + 建运行用户

用一个**非 root** 用户跑服务,代码放 `/opt/course-rag`。

```bash
sudo useradd -r -m -d /opt/course-rag -s /bin/bash appuser
sudo -u appuser git clone https://github.com/Alan-Lin-hub/My-First-Project.git /opt/course-rag
cd /opt/course-rag
sudo -u appuser ~/.local/bin/uv sync     # 安装依赖到 .venv
```

> 如果 `uv` 不在 appuser 的 PATH 里,用绝对路径(`/home/appuser/.local/bin/uv` 或安装后的实际路径),systemd 单元里也用绝对路径。

`docs/` 里可放初始课程文档(启动时自动导入);之后也可在网页上传。

---

## 2. 配置 `.env`(生产值)

在仓库根目录 `/opt/course-rag/.env`(`load_dotenv` 会从 `backend/` 向上找到它):

```bash
sudo -u appuser tee /opt/course-rag/.env >/dev/null <<'EOF'
# LLM
DEEPSEEK_API_KEY=sk-你的真实key

# Auth —— 必填,用强随机值
JWT_SECRET=粘贴下面 openssl 生成的值
JWT_EXPIRE_MINUTES=720

# 初始管理员（仅在还没有任何 admin 时播种一次）
ADMIN_USERNAME=admin
ADMIN_PASSWORD=用一个强密码

# 生产把 CORS 收紧为你的真实域名
CORS_ORIGINS=https://rag.example.com
EOF

# 生成 JWT_SECRET 并填进去
openssl rand -hex 32
sudo chmod 600 /opt/course-rag/.env
```

⚠️ 要点:
- `.env` 已在 `.gitignore`,不会进 git。权限设 `600`。
- `ADMIN_PASSWORD` 只在首次(无 admin 时)播种。**上线后立刻登录用「修改密码」改掉**;之后再改这个变量不会生效。
- 同源部署下 CORS 其实可有可无(前端和 API 同域),但仍建议设成真实域名。

---

## 3. systemd 服务(开机自启 + 崩溃重启)

```bash
sudo tee /etc/systemd/system/course-rag.service >/dev/null <<'EOF'
[Unit]
Description=Course Materials RAG (FastAPI)
After=network.target

[Service]
Type=simple
User=appuser
Group=appuser
WorkingDirectory=/opt/course-rag/backend
# 只监听本机回环，由 nginx 反代到 443
ExecStart=/home/appuser/.local/bin/uv run uvicorn app:app --host 127.0.0.1 --port 8000 --workers 1
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now course-rag
sudo systemctl status course-rag --no-pager
journalctl -u course-rag -f      # 看启动日志：应有 "Seeded initial admin account: admin"
```

> **为什么 `--workers 1`**:本应用用**进程内**会话历史(`SessionManager`),且 ChromaDB / SQLite 是**单进程本地文件**。多 worker 会各自持有独立内存、并可能并发写 ChromaDB。对中小规模内部工具,单 worker(FastAPI 仍能并发处理请求)足够。要更高并发需先改造(共享会话存储 + 外部向量库),属于后续工作。

---

## 4. nginx 反向代理

```bash
sudo tee /etc/nginx/sites-available/course-rag >/dev/null <<'EOF'
server {
    listen 80;
    server_name rag.example.com;

    # 课程上传可能是较大的 PDF —— 放宽请求体大小
    client_max_body_size 50M;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;     # LLM 响应可能较慢
    }
}
EOF

sudo ln -s /etc/nginx/sites-available/course-rag /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

---

## 5. HTTPS（Let's Encrypt）

```bash
sudo certbot --nginx -d rag.example.com
# 按提示填邮箱、同意条款，选择自动把 HTTP 跳转到 HTTPS
sudo systemctl status certbot.timer    # 自动续期已启用
```

certbot 会改写上面的 nginx 配置,加上 443 + 证书 + 80→443 跳转。

⚠️ **HTTPS 是硬性要求**:登录密码和 JWT 都不能走明文 HTTP。

---

## 6. 防火墙

```bash
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'    # 80 + 443
sudo ufw enable
# 8000 只在本机回环，外部访问不到（systemd 里绑的是 127.0.0.1）
```

---

## 7. 上线后自检

```bash
curl -I https://rag.example.com/                       # 200，前端可访问
curl -s -o /dev/null -w "%{http_code}\n" https://rag.example.com/api/courses   # 401（未登录）
```

浏览器打开 `https://rag.example.com`:
1. 用 `admin` + 你设的 `ADMIN_PASSWORD` 登录。
2. **立刻去「修改密码」改掉初始密码。**
3. 「用户管理」里建普通用户;确认普通用户登录后**看不到上传/用户管理**。
4. 上传一个课程文档、问一个问题,确认端到端可用。

---

## 8. 备份(重要)

需要备份的是这几样本地数据:`backend/chroma_db/`、`backend/users.db`、`docs/`、`.env`。

```bash
sudo tee /opt/course-rag/backup.sh >/dev/null <<'EOF'
#!/bin/bash
set -e
TS=$(date +%Y%m%d-%H%M%S)
DEST=/opt/backups; mkdir -p "$DEST"
tar -czf "$DEST/course-rag-$TS.tar.gz" \
  -C /opt/course-rag backend/chroma_db backend/users.db docs .env
find "$DEST" -name 'course-rag-*.tar.gz' -mtime +14 -delete
EOF
sudo chmod +x /opt/course-rag/backup.sh
# 每天 03:00 备份
echo "0 3 * * * root /opt/course-rag/backup.sh" | sudo tee /etc/cron.d/course-rag-backup
```

---

## 9. 更新部署

```bash
cd /opt/course-rag
sudo -u appuser git pull
sudo -u appuser ~/.local/bin/uv sync
sudo systemctl restart course-rag
```

> ChromaDB 升级或想强制重新导入文档:停服务 → 删 `backend/chroma_db/` → 启服务(会从 `docs/` 重新摄取)。

---

## 10. 安全清单(上线前逐项确认)

- [ ] 已走 **HTTPS**(certbot 配好,HTTP 自动跳 443)
- [ ] `JWT_SECRET` 是 ≥32 字节随机值;`.env` 权限 600
- [ ] 已**改掉初始 `admin` 密码**(用「修改密码」)
- [ ] `CORS_ORIGINS` 设为真实域名(非 `*`)
- [ ] 8000 端口不对外(仅 `127.0.0.1`),ufw 只放 80/443
- [ ] 备份计划已生效
- [ ] 轮换掉开发阶段暴露过的 `DEEPSEEK_API_KEY` 和演示密码

---

## 已内置的安全能力(无需额外做)

- **登录限流**防爆破:`/api/auth/login` 已由进程内 `RateLimiter`(`rate_limit.py`)按客户端 IP 限流——只有失败计数,成功即清零,超过 `LOGIN_MAX_FAILURES`/`LOGIN_FAILURE_WINDOW_SECONDS` 返回 429。注意是**进程内**状态(重启即清、多 worker 不共享)。
- **改密即踢下线**:每个 JWT 携带用户的 `token_version`(`ver`);任何改密(自助或管理员重置)都会把它 +1,**旧 token 立即失效**。`change-password` 会返回新 token 让本人会话存活。

## 进一步加固(可选,后续)

- **TrustedHost 收紧**:`app.py` 里 `allowed_hosts=["*"]` 可改成你的域名。
- **多实例 / 高并发**:需把会话与登录限流改为共享存储(Redis)、向量库改为可并发的部署,再上多 worker / 多机。详见仓库根目录 [`SCALING.md`](SCALING.md)。

---

# 附:本地 Mac 自托管 + GitHub Actions CI/CD(当前实际部署方式)

上面 0–10 是 Ubuntu 服务器方案。**当前实际跑的是另一套**:部署目标是本机 Mac,用 ngrok 暴露公网,通过 GitHub Actions **self-hosted runner** 实现 push 即自动部署。两套独立,本节是现状的运维参考。

## 架构与组成

```
push main → GitHub Actions
   ├ test   (云端 ubuntu)          ruff + pytest
   └ deploy (self-hosted, 本机Mac) scripts/deploy-mac.sh:git pull→uv sync→重启服务→健康检查
uvicorn / ngrok 由 launchd 托管(常驻、崩溃自启、开机自启),与 runner 进程树解耦
```

- **runner**:装在 `~/actions-runner/`,以 LaunchAgent 形式常驻(`./svc.sh install`)。
- **两个 launchd 服务**(plist 源文件在 `scripts/launchd/`,已拷到 `~/Library/LaunchAgents/`):
  - `com.courserag.api` → uvicorn `app:app` 0.0.0.0:8000(无 `--reload`、单 worker)
  - `com.courserag.ngrok` → `ngrok http --url=https://engraving-exile-fester.ngrok-free.dev 8000`
- **workflow**:`.github/workflows/ci.yml` 的 `deploy` job(`if main push` + `needs: test`)。
- 日志在 `~/Library/Logs/courserag/`。

## 工作方式

**改代码 → commit → `git push origin main`**,其余全自动(test 通过才 deploy;deploy 失败 Actions 标红,旧服务因 launchd 仍在跑)。
> 该目录 checkout 在 `main`,开发=部署同一份。建议直接在 main 上改;要试验另开分支,上线时合回 main。

## 日常运维命令

```bash
APP=/Users/linsen/开发工具/My-First-Project; U=$(id -u)

# —— 看日志 ——
tail -f ~/Library/Logs/courserag/api.err.log        # API 日志(启动/报错)
tail -f ~/Library/Logs/courserag/ngrok.err.log      # 隧道日志

# —— 手动重启(改了 .env / 需要重载时) ——
launchctl kickstart -k "gui/$U/com.courserag.api"
launchctl kickstart -k "gui/$U/com.courserag.ngrok"

# —— 查状态 / 健康 ——
launchctl print "gui/$U/com.courserag.api"   | grep "state ="
curl -fsS http://127.0.0.1:8000/ >/dev/null && echo OK     # 本地
curl -s http://127.0.0.1:4040/api/tunnels | grep -o '"public_url":"[^"]*"'  # 公网隧道URL

# —— 停 / 启某个服务 ——
launchctl unload ~/Library/LaunchAgents/com.courserag.api.plist
launchctl load -w ~/Library/LaunchAgents/com.courserag.api.plist

# —— 改了 plist 后生效(unload→拷新→load) ——
cp "$APP"/scripts/launchd/com.courserag.api.plist ~/Library/LaunchAgents/
launchctl unload ~/Library/LaunchAgents/com.courserag.api.plist
launchctl load   -w ~/Library/LaunchAgents/com.courserag.api.plist

# —— 查 runner ——
cd ~/actions-runner && ./svc.sh status

# —— 回滚到上一个版本 ——
cd "$APP" && git revert HEAD && git push origin main   # 触发一次自动部署回退
```

## 常见故障

- **公网 `ERR_NGROK_3200`(隧道 offline)**:ngrok 服务没起。看 `ngrok.err.log`。
- **`ERR_NGROK_9009`(authentication failed, proxy)**:免费版 ngrok 不能走代理。系统开了全局代理(如 ClashX)时,launchd 进程会继承——plist 里已用空的 `http_proxy/https_proxy/all_proxy` 屏蔽;若复发,确认 plist 的 `EnvironmentVariables` 仍在。
- **API 重启后短暂 502/连不上**:正常,embedding 模型加载约 10–15s,健康检查会等。
- **deploy job 排队不动**:Mac 没开机/休眠,或 runner 服务停了(`./svc.sh status`)。

## 安全提醒(本套特有)

- 仓库**必须 Private**:self-hosted runner 会执行仓库 workflow,公开仓库等于让任何人在你 Mac 上跑代码。
- Mac 需保持开机联网,否则部署排队、隧道断开。
- 密钥放本地 `.env`(launchd 从 `backend/` 向上加载),**不进 GitHub Secrets、不进 git**。

test1

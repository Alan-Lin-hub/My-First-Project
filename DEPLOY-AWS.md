# 部署到 AWS Lightsail(2GB) + duckdns 免费 HTTPS

把这个 RAG 应用从"本地 Mac + ngrok"迁到 **AWS Lightsail 常开实例**,并把 CI/CD 从
self-hosted runner 换成**云端 SSH 部署**——从此不依赖你的 Mac 开机。

- 实例:Lightsail 2GB(2 vCPU / 60GB SSD),Ubuntu 22.04,约 $12/月,$100 代金券可用 ~8 个月
- 域名/HTTPS:免费 `xxx.duckdns.org` 子域 + Let's Encrypt(certbot)
- 部署方式:push main → GitHub Actions 云端 test → SSH 进实例跑 `scripts/deploy.sh`(systemd 版)

> 需要你**先填 3 个占位值**并全程替换:
> - `<SUBDOMAIN>` = 你在 duckdns 建的子域前缀(如 `course-rag`)
> - `<STATIC_IP>` = Lightsail 分配的静态 IP
> - `<DUCKDNS_TOKEN>` = duckdns 面板给的 token

---

## Part 1 — 创建 Lightsail 实例(控制台点几下)

1. 打开 https://lightsail.aws.amazon.com → **Create instance**
2. **Region**:选对中国大陆延迟友好的 → **Singapore(ap-southeast-1)** 或 **Tokyo(ap-northeast-1)**
3. **Platform**:Linux/Unix → **OS Only → Ubuntu 22.04 LTS**
4. **Plan**:选 **$12/月(2GB RAM / 2 vCPU / 60GB SSD)**(别选 512MB/1GB,装不下 embedding 模型)
5. 命名(如 `course-rag`)→ **Create instance**,等 1–2 分钟变 Running

### 1.1 分配静态 IP(必做,否则重启换 IP)
- 左侧 **Networking → Create static IP → 绑定到刚才的实例** → 记下这个 IP = `<STATIC_IP>`

### 1.2 开放端口
- 实例详情 → **Networking → IPv4 Firewall**,确保放行:**SSH(22)、HTTP(80)、HTTPS(443)**
- **不要**开 8000(只在本机回环,由 nginx 反代)

---

## Part 2 — duckdns 免费域名

1. 打开 https://www.duckdns.org,用 GitHub/Google 登录
2. 顶部 **token** 记下 = `<DUCKDNS_TOKEN>`
3. 输入子域前缀(如 `course-rag`)→ **add domain** → 得到 `<SUBDOMAIN>.duckdns.org`
4. 在该域那行的 **current ip** 填 `<STATIC_IP>` → **update ip**
5. 本地验证解析:`ping <SUBDOMAIN>.duckdns.org` 应回 `<STATIC_IP>`

> 静态 IP 不变,理论上填一次即可。稳妥起见 Part 3 里会装一个每 5 分钟自动回写的定时任务。

---

## Part 3 — SSH 登录并装环境

**登录方式**:Lightsail 实例页有 **Connect using SSH**(浏览器直接进),或本地:
下载实例密钥(Account → SSH keys → Download default key)后 `chmod 600 key.pem && ssh -i key.pem ubuntu@<STATIC_IP>`

进去后**逐段执行**:

```bash
# 3.1 系统更新 + 基础组件
sudo apt update && sudo apt -y upgrade
sudo apt install -y nginx git certbot python3-certbot-nginx curl

# 3.2 加 2GB swap(2GB 内存档必做,否则加载模型可能 OOM)
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
free -h   # 确认 Swap 有 2Gi

# 3.3 duckdns 自动回写 IP(每5分钟,防 IP 变动)
mkdir -p ~/duckdns
cat > ~/duckdns/duck.sh <<EOF
echo url="https://www.duckdns.org/update?domains=<SUBDOMAIN>&token=<DUCKDNS_TOKEN>&ip=" | curl -k -o ~/duckdns/duck.log -K -
EOF
chmod +x ~/duckdns/duck.sh && ~/duckdns/duck.sh && cat ~/duckdns/duck.log   # 应输出 OK
( crontab -l 2>/dev/null; echo "*/5 * * * * ~/duckdns/duck.sh >/dev/null 2>&1" ) | crontab -
```

### 3.4 建运行用户 + 取代码 + 装依赖

```bash
# 非 root 用户跑服务,代码放 /opt/course-rag
sudo useradd -r -m -d /opt/course-rag -s /bin/bash appuser
sudo -u appuser bash -lc 'curl -LsSf https://astral.sh/uv/install.sh | sh'
sudo -u appuser git clone https://github.com/Alan-Lin-hub/My-First-Project.git /opt/course-rag
sudo -u appuser bash -lc 'cd /opt/course-rag && ~/.local/bin/uv sync'
```

### 3.5 写 .env(用全新密钥,别用泄露过的旧值)

```bash
# 先生成一个新 JWT_SECRET
openssl rand -hex 32     # 复制输出备用

sudo -u appuser tee /opt/course-rag/.env >/dev/null <<'EOF'
DEEPSEEK_API_KEY=sk-你的真实DeepSeek密钥
JWT_SECRET=粘贴上面openssl生成的值
JWT_EXPIRE_MINUTES=720
ADMIN_USERNAME=admin
ADMIN_PASSWORD=设一个强密码
CORS_ORIGINS=https://<SUBDOMAIN>.duckdns.org
EOF
sudo chmod 600 /opt/course-rag/.env
```

### 3.6 systemd 服务(开机自启 + 崩溃重启)

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
ExecStart=/opt/course-rag/.local/bin/uv run uvicorn app:app --host 127.0.0.1 --port 8000 --workers 1
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now course-rag
sleep 15 && curl -fsS http://127.0.0.1:8000/ >/dev/null && echo "✅ 本地起来了"
journalctl -u course-rag -n 30 --no-pager    # 看到 "Application startup complete"
```

### 3.7 nginx 反代 + HTTPS

```bash
sudo tee /etc/nginx/sites-available/course-rag >/dev/null <<'EOF'
server {
    listen 80;
    server_name <SUBDOMAIN>.duckdns.org;
    client_max_body_size 50M;          # PDF 上传
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;       # LLM 响应慢
    }
}
EOF
# 注意:上面 heredoc 用了单引号所以 <SUBDOMAIN> 不会被替换,需手动改:
sudo sed -i 's/<SUBDOMAIN>/你的子域前缀/g' /etc/nginx/sites-available/course-rag

sudo ln -sf /etc/nginx/sites-available/course-rag /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx

# 出免费 HTTPS(按提示填邮箱、同意、选自动跳转 443)
sudo certbot --nginx -d <SUBDOMAIN>.duckdns.org
```

### 3.8 防火墙 + 自检

```bash
sudo ufw allow OpenSSH && sudo ufw allow 'Nginx Full' && sudo ufw --force enable
curl -I https://<SUBDOMAIN>.duckdns.org/                    # 200
curl -s -o /dev/null -w "%{http_code}\n" https://<SUBDOMAIN>.duckdns.org/api/courses   # 401(未登录,正常)
```

浏览器打开 `https://<SUBDOMAIN>.duckdns.org` → 用 admin + 你设的密码登录 → **立刻改密码** → 上传文档问一句,确认端到端可用。

---

## Part 4 — 把 CI/CD 从"Mac 自托管"换成"云端 SSH 部署"

上云后不再需要 self-hosted runner。改用云端 runner SSH 进实例跑已存在的 `scripts/deploy.sh`。

### 4.1 生成部署专用 SSH 密钥(在你本地 Mac)

```bash
ssh-keygen -t ed25519 -f ~/deploy_key -N "" -C "github-actions-deploy"
# 公钥装到服务器 appuser
ssh-copy-id -i ~/deploy_key.pub -o IdentityFile=<你的Lightsail密钥> appuser@<STATIC_IP>
# 若 ssh-copy-id 不便,手动:把 ~/deploy_key.pub 内容追加到服务器 /opt/course-rag/.ssh/authorized_keys
```

### 4.2 让 appuser 能免密重启服务(deploy.sh 里要 systemctl restart)

在服务器上:
```bash
echo 'appuser ALL=(root) NOPASSWD: /bin/systemctl restart course-rag, /bin/systemctl status course-rag' | sudo tee /etc/sudoers.d/course-rag-deploy
sudo chmod 440 /etc/sudoers.d/course-rag-deploy
```

### 4.3 GitHub 仓库加 3 个 Secrets
仓库 → Settings → Secrets and variables → Actions → New repository secret:
- `SSH_HOST` = `<STATIC_IP>`
- `SSH_USER` = `appuser`
- `SSH_KEY`  = `~/deploy_key` 私钥全文(`cat ~/deploy_key`)

### 4.4 改 `.github/workflows/ci.yml` 的 deploy job

把原来的 self-hosted 版替换为:
```yaml
  deploy:
    needs: test
    if: github.ref == 'refs/heads/main' && github.event_name == 'push'
    runs-on: ubuntu-latest
    steps:
      - name: SSH deploy
        uses: appleboy/ssh-action@v1
        with:
          host: ${{ secrets.SSH_HOST }}
          username: ${{ secrets.SSH_USER }}
          key: ${{ secrets.SSH_KEY }}
          script: cd /opt/course-rag && bash scripts/deploy.sh
```

> 若 `scripts/deploy.sh` 里用的是 `git pull`/`uv sync`/`systemctl restart course-rag`/健康检查,直接可用;
> 路径或单元名不同则对应调整。SKIP_BACKUP 等开关见脚本内注释。

### 4.5 收尾:停用 Mac 那套(可选)
- Mac 上:`launchctl unload ~/Library/LaunchAgents/com.courserag.*.plist`;runner 可在 GitHub Settings→Actions→Runners 里移除,或 `cd ~/actions-runner && ./svc.sh stop`。

---

## 成本与备份

- **实例** $12/月(代金券覆盖);**流量**含在套餐;**域名/HTTPS** 免费。DeepSeek API 另计(很低)。
- **备份**(照 DEPLOYMENT.md 第 8 节):每天打包 `backend/chroma_db`、`backend/users.db`、`docs`、`.env`。
  Lightsail 还可开**自动快照**(实例页 → Snapshots → 每日自动),多一层保险。

## 安全清单

- [ ] `.env` 用**全新**密钥(泄露过的 JWT/PAT 已作废)
- [ ] 登录后改掉初始 admin 密码
- [ ] 8000 不对外,ufw 只放 22/80/443
- [ ] 仓库保持 Private
- [ ] certbot 自动续期已启用(`systemctl status certbot.timer`)

# 部署指南:GitHub + 海外 VPS + 推送即自动部署

整体流程分三大步:

1. **本地** → 把项目推到 GitHub
2. **服务器** → 装好 Docker,第一次手动跑起来
3. **自动化** → 配好 GitHub Actions,以后 `git push` 就自动部署

---

## Part 0:先理解整个链路(很重要)

```
你电脑 --git push--> GitHub --触发 Actions--> SSH 进服务器
                                                  |
                                          git pull + docker compose up
                                                  |
                                          应用更新完成 ✅
```

关键点:**镜像是在服务器上构建的**(`docker compose up --build`),GitHub Actions 只负责"远程下命令"。这是个人项目最简单稳妥的方案,不用折腾镜像仓库。

---

## Part 1:推到 GitHub

### 1.1 在 GitHub 建一个空仓库

打开 https://github.com/new ,填仓库名(例如 `rag`),**不要**勾选 "Add README/.gitignore/license"(保持空仓库),建好后复制它的地址,例如:

```
git@github.com:你的用户名/rag.git
```

> 用 SSH 地址(`git@`)而不是 https,推送时不用反复输密码。如果你还没配过 GitHub SSH key,先做 1.2;配过就跳到 1.3。

### 1.2 (首次)给你电脑配 GitHub SSH key

```bash
# Generate a key if you don't have one
ssh-keygen -t ed25519 -C "zxl17302206700@gmail.com"
# Press Enter to accept defaults

# Copy the PUBLIC key
cat ~/.ssh/id_ed25519.pub
```

把输出的整段贴到 GitHub → Settings → SSH and GPG keys → New SSH key。

### 1.3 本地初始化并推送

在项目根目录(`RAG system/`)执行:

```bash
git init
git add .
git commit -m "Initial commit: RAG system"
git branch -M main
git remote add origin git@github.com:你的用户名/rag.git
git push -u origin main
```

**推送前务必确认 `.env` 没被提交**(里面有你的 API key)。我已经写好 `.gitignore` 排除它,可以这样验证:

```bash
git status            # .env 不应该出现在列表里
git ls-files | grep .env   # 应该只看到 .env.example
```

---

## Part 2:服务器首次部署(手动跑通一次)

> 先手动跑通,确认没问题,再上自动化。这样出错时你知道是代码问题还是 CI 问题。

### 2.1 SSH 登录服务器

```bash
ssh ubuntu@你的服务器IP
```

### 2.2 安装 Docker(Ubuntu 一次性脚本)

```bash
# Official convenience script
curl -fsSL https://get.docker.com | sudo sh

# Let your user run docker without sudo
sudo usermod -aG docker $USER
# IMPORTANT: log out and back in for the group change to take effect
exit
```

重新 SSH 登录后验证:

```bash
docker --version
docker compose version
```

### 2.3 把代码拉到服务器

**公开仓库**直接 clone:

```bash
cd ~
git clone https://github.com/你的用户名/rag.git
cd rag
```

**私有仓库**:服务器需要一个能读仓库的凭据。最简单的是给服务器生成一把 SSH key 并加为仓库的 **Deploy Key**:

```bash
ssh-keygen -t ed25519 -C "server-deploy"   # 一路回车
cat ~/.ssh/id_ed25519.pub
# 把它贴到 GitHub 仓库 → Settings → Deploy keys → Add deploy key(只读即可)
# 然后用 SSH 地址 clone:
git clone git@github.com:你的用户名/rag.git
cd rag
```

记下这个目录的绝对路径(后面 CI 要用),例如 `/home/ubuntu/rag`:

```bash
pwd
```

### 2.4 创建服务器上的 .env

`.env` 不在 git 里,要在服务器手动建:

```bash
cp .env.example .env
nano .env     # 填入真实的 ANTHROPIC_API_KEY,保存退出 (Ctrl+O, Enter, Ctrl+X)
```

### 2.5 启动整个栈

```bash
docker compose up -d --build
```

第一次会比较慢(拉镜像 + 装 Python 依赖)。完成后检查:

```bash
docker compose ps          # 三个服务都应是 running/healthy
docker compose logs -f app # 看应用日志,Ctrl+C 退出
```

### 2.6 开放端口 / 访问

应用监听 `8001`。确认两层防火墙都放行:

- **云厂商安全组**:在控制台给实例放行入站 `8001`(以及 `22` SSH)。
- **服务器本机防火墙**(如果开了 ufw):

```bash
sudo ufw allow 8001
```

浏览器打开 `http://你的服务器IP:8001` 即可看到上传/问答界面。

> 安全提醒:`docker-compose.yml` 现在把 `5432`(Postgres)和 `8000`(Chroma)也映射到了公网。生产环境建议**只对外暴露 8001**,把另外两个的 `ports` 注释掉(容器之间走内部网络,不需要公网端口)。等你跑通后我可以帮你改。

---

## Part 3:配置 CI/CD(推送即自动部署)

代码里已经有 `.github/workflows/deploy.yml`,它做的事:push 到 `main` → SSH 进服务器 → `git pull` → `docker compose up -d --build`。你只需要把 5 个密钥告诉 GitHub。

### 3.1 准备一把"部署专用"SSH key

让 GitHub Actions 能登录你的服务器。**在你本地电脑**生成一把新 key(不要复用日常 key):

```bash
ssh-keygen -t ed25519 -f ~/.ssh/rag_deploy -C "github-actions" -N ""
```

把**公钥**加到服务器的授权列表:

```bash
ssh-copy-id -i ~/.ssh/rag_deploy.pub ubuntu@你的服务器IP
# 或手动:把 rag_deploy.pub 内容追加到服务器的 ~/.ssh/authorized_keys
```

### 3.2 在 GitHub 仓库添加 Secrets

仓库 → Settings → Secrets and variables → Actions → New repository secret,逐个添加:

| Name | Value |
|------|-------|
| `SSH_HOST` | 服务器 IP |
| `SSH_USER` | `ubuntu`(你的登录用户) |
| `SSH_PORT` | `22` |
| `SSH_KEY` | `cat ~/.ssh/rag_deploy` 的**完整私钥内容**(含首尾 BEGIN/END 行) |
| `DEPLOY_PATH` | 2.3 里 `pwd` 得到的路径,如 `/home/ubuntu/rag` |

### 3.3 测试自动部署

本地随便改点东西并推送:

```bash
git commit -am "test: trigger CI deploy"
git push
```

打开 GitHub 仓库的 **Actions** 标签,能看到 `Deploy` 任务在跑。绿勾 = 成功,服务器已自动更新。也可以在 Actions 页点 "Run workflow" 手动触发。

---

## 常见问题排查

- **Actions 报 `Permission denied (publickey)`**:`SSH_KEY` 贴的是私钥不是公钥;或公钥没加到服务器 `authorized_keys`;或 `SSH_USER` 写错。
- **`git pull` 报冲突**:服务器上别手动改代码。所有改动都从本地 push,服务器只 pull。
- **改了代码但页面没变**:工作流用的是 `--build`,确认 Actions 这次真的跑成功了;再 `docker compose logs app` 看有没有报错。
- **磁盘越来越满**:工作流已自动 `docker image prune -f`;数据卷(pgdata/chromadata)是你的真实数据,不要删。
- **环境变量改了**:`.env` 改动要手动在服务器改并 `docker compose up -d` 重启(CI 不碰 .env)。

---

## 最终架构总览(两把 key,别搞混)

整套部署涉及**两把方向相反、用途不同的 SSH key**。这是当初 debug 最容易绕晕的地方,记住它就不会再迷路。

**Key A — GitHub Actions 登录 VPS**(方向:GitHub → 服务器)

- 私钥:存在 GitHub 仓库 secret `SSH_KEY` 里。
- 公钥:加在服务器 `deploy` 用户的 `~/.ssh/authorized_keys`。
- 作用:让 CI 能 SSH 进服务器下命令。

**Key B — VPS 拉取私有仓库**(方向:服务器 → GitHub)

- 私钥:存在服务器 `/home/deploy/.ssh/` 里。
- 公钥:注册在 GitHub 仓库的 **Deploy Keys**(只读即可)。
- 作用:让 deploy 用户能 `git pull` 私有仓库。

**一次部署的完整流程:**

```
你 push 到 main
  → GitHub Actions 启动
  → 用 Key A，SSH 进 VPS 的 deploy 用户
  → deploy 执行 git pull（用 Key B 从私有仓库拉新代码）
  → docker compose up -d --build 重建并重启
  → 完成 ✅
```

**排查 SSH 认证的黄金法则**:任何一次登录失败,先问"**正确的公钥,在不在我要连的那台机器、那个用户的 `authorized_keys` 里**"。本地"能登录"不等于"这把特定的 key 能登录"——ssh-agent 会拿别的 key 兜底。要隔离验证某一把 key,必须加 `-o IdentitiesOnly=yes`:

```bash
ssh -i ~/.ssh/某私钥 -o IdentitiesOnly=yes user@host
```

这条命令的行为才和 GitHub Actions 的干净环境等价。

**网络暴露面**:只有应用端口 `8001` 对公网开放;Postgres `5432`、Chroma `8000` 已绑定到 `127.0.0.1`,只能从服务器本机或 SSH 隧道访问。想从本地连库:

```bash
ssh -L 5432:localhost:5432 deploy@服务器IP
```

## 之后还能加的(可选)

- CI 里先跑测试/lint,通过才部署
- 用 Nginx + 域名 + HTTPS(Let's Encrypt)替代裸 IP:端口
- 数据库定时备份脚本

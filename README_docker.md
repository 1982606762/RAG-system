# 家用文件知识库 — Docker 部署（双数据库）

一条命令拉起整个栈：PostgreSQL（结构化元数据）+ ChromaDB（向量检索）
+ Redis/Celery（后台入库）+ FastAPI（API）+ React/nginx（Web）。

## 目录结构

```
.
├── docker-compose.yml        # 全部服务编排
├── .env.example              # 复制成 .env 填入 API key
├── db/init/01_schema.sql     # 首次启动自动建表
├── files/                    # 把要入库的图片放这里
├── app/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py               # FastAPI 装配入口（uvicorn 跑这个）
│   ├── cli.py                # 命令行入口
│   ├── core/
│   │   └── config.py         # 全部读环境变量
│   ├── db/
│   │   └── storage.py        # PostgreSQL + ChromaDB 读写
│   ├── rag/
│   │   ├── process.py        # Claude Vision -> 结构化 JSON
│   │   ├── service.py        # 入库编排（CLI 与 API 共用）
│   │   ├── answer.py         # 简单 RAG
│   │   └── agent.py          # Agentic RAG（tool calling）
│   └── api/
│       └── routes.py         # /api/* 路由
└── frontend/                 # React 前端与 nginx 反向代理
```

## 启动

```bash
# 1. 配置 API key
cp .env.example .env
# 编辑 .env 填入你的 ANTHROPIC_API_KEY

# 2. 拉起全部服务（首次会构建 app 镜像、下载 postgres/chroma 镜像）
docker compose up -d --build

# 3. 确认两个数据库都连通
docker compose exec app python cli.py healthcheck
# 期望输出：ChromaDB: OK / PostgreSQL: OK / Overall: ALL GOOD
```

## Web 界面

启动后直接打开浏览器：

```
http://localhost:8001
```

三个标签页：**上传**（拖拽/点击上传文件，自动入库）、**文件**（已入库文件列表）、**问答**（自然语言提问，走 Agentic RAG）。

后端 API（也可用 curl 调）：

```
GET  /api/health       两库连通状态
POST /api/upload_async 上传并创建后台入库任务（multipart file）
GET  /api/tasks/{id}   查询当前用户的任务状态
GET  /api/documents    文件列表
POST /api/ask          {"question": "..."} -> 智能问答
```

CLI 仍可用于调试：`docker compose exec app python cli.py agent "..."`。

## 使用

```bash
# 把图片放进 files/ 后入库（容器内路径是 /files/...）
docker compose exec app python cli.py ingest /files/发票.jpg

# 模糊语义检索（向量库找到 file_id，再回 PostgreSQL 取详情）
docker compose exec app python cli.py vsearch "我买的零食"

# 精确查询（向量库做不到的：完整列举、范围、汇总）
docker compose exec app python cli.py sql \
  "SELECT doc_type, vendor, amount FROM documents ORDER BY created_at DESC"

# 查 JSONB 动态字段
docker compose exec app python cli.py sql \
  "SELECT file_id, full_analysis->'details' FROM documents WHERE full_analysis->'details'->>'brand'='小米'"
```

## 验证两个库确实连通

```bash
# PostgreSQL 里看到的行
docker compose exec postgres psql -U postgres -d ragdb -c "SELECT file_id, doc_type FROM documents;"

# ChromaDB 心跳
curl http://localhost:8000/api/v2/heartbeat
```

同一个 `file_id` 既出现在 PostgreSQL 的行里，也是 ChromaDB 里向量的 id —— 这就是两个库被串起来的证据。

## 常用运维

```bash
docker compose logs -f app      # 看日志
docker compose down             # 停止（数据保留在具名卷里）
docker compose down -v          # 停止并删除数据卷（清空数据库）
```

## 说明

- embedding 由 app/worker 内的 `SentenceTransformer` 计算，再写入 Chroma。切换模型后需要清空向量集合并重新入库。
- `app` 是常驻 FastAPI API；`celery_worker` 负责后台入库；浏览器只访问 nginx 暴露的 `8001`。

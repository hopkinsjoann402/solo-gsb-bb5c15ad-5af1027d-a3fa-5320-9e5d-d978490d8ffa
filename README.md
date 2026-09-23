# 许可证依赖冲突审计台

基于 **FastAPI + SQLite** 的依赖许可证合规审计工具。上传包含包名、版本、许可证及依赖边的
manifest，系统会：

1. **规范化节点** —— 统一包名/版本写法、把许可证别名（`Apache 2.0`、`GPLv3`、`MIT License`…）
   映射为规范 SPDX 标识，合并重复节点并归一依赖边；
2. **计算传递约束** —— 按内置许可证兼容矩阵（宽松型 / 弱 copyleft / 强 copyleft / 专有），
   对依赖图做传递可达性分析，记录每个节点受到的来自所有祖先的许可证约束；
3. **标出最短冲突路径** —— 对每一对不兼容的“祖先许可证 → 后代许可证”，用 BFS 给出
   **最短依赖路径**（冲突路径上每个节点都标注许可证），硬冲突与“需人工确认”告警分级展示；
4. **按包筛选** —— 包名子串过滤，凡最短路径经过该包的冲突都会保留；
5. **导出 JSON** —— 完整审计结果（含筛选结果）可一键下载；审计记录持久化在 SQLite；
6. **两次审计对比** —— 从历史记录中选择两个 `audit_id`，按 **包名@版本** 配对节点，
   展示两次审计之间新增、消失及状态变化（级别 / 许可证 / 原因 / 最短路径变化）的冲突与告警，
   并同时给出双方各自的最短依赖路径。对比只读取历史记录，**不会写入新审计**。

## 快速开始（Docker Compose，推荐）

```bash
docker compose up --build
```

容器启动时会自动初始化数据库（SQLite 文件位于卷 `audit-data`，容器内路径 `/data/audit.db`），
随后在宿主机 **8000 端口** 提供服务。

启动后访问：

| 地址 | 说明 |
| --- | --- |
| <http://localhost:8000/> | 网页界面（已自动载入示例 manifest，页内可做两次审计对比） |
| <http://localhost:8000/docs> | Swagger 风格交互式 JSON API 文档 |
| <http://localhost:8000/redoc> | ReDoc API 文档 |
| <http://localhost:8000/api/matrix> | 许可证兼容矩阵（机器可读） |
| <http://localhost:8000/healthz> | 健康检查 |

端口在 `docker-compose.yml` 的 `ports: ["8000:8000"]` 映射，宿主机 8000 被占用时可改为
`"18000:8000"` 再访问 <http://localhost:18000/>。

停止并保留数据：`docker compose down`；连同数据卷一起清除：`docker compose down -v`。

## 本地直接运行

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

数据库默认创建在 `./data/audit.db`，可用环境变量覆盖：

- `DATA_DIR` —— 数据库目录（默认 `./data`）；
- `DATABASE_URL` —— 直接指定 SQLite 文件路径（如 `/var/lib/audit/audit.db`）。

## manifest 格式

```json
{
  "name": "my-app",
  "packages": [
    {
      "name": "web-app",
      "version": "1.0.0",
      "license": "AGPL-3.0",
      "dependencies": [
        "billing-core@1.2.0",
        { "name": "ui-kit", "version": "^0.9.0" },
        { "name": "font-pack", "version": "2.0.0", "license": "MIT" }
      ]
    },
    { "name": "billing-core", "version": "1.2.0", "license": "GPL-2.0" }
  ],
  "dependencies": {
    "billing-core@1.2.0": ["font-pack@2.0.0"]
  },
  "edges": [
    { "source": "web-app@1.0.0", "target": "billing-core@1.2.0" }
  ]
}
```

约定：

- `packages` 声明节点；`dependencies`（包内或顶层，数组或 `名字: 版本` 映射均可）与
  `edges` 声明依赖边，方向为 **使用方 → 被依赖方**，传递约束沿边传播；
- 只给包名不给版本时，若 `packages` 中该名字唯一则自动解析，多个版本需用 `name@version` 消歧；
- 无法解析到已声明节点的依赖会进入 `unresolved` 列表并产生告警，不会凭空造节点；
- 未在矩阵中识别的许可证（如 `OFL-1.1`）保留原文并标记为 unknown，
  相关边按“需人工确认”告警处理，而非误判为兼容；
- 依赖环会被安全处理（BFS 节点只访问一次），不影响最短路径计算。

## JSON API 速览

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/audit` | 提交 JSON：`{"manifest": {...}, "name": "可选名称"}` |
| POST | `/api/audit/upload` | 上传 `.json` manifest 文件（multipart） |
| GET | `/api/audits?limit=20` | 历史审计列表 |
| GET | `/api/audits/{id}` | 获取审计结果；`?package=xxx` 按包筛选 |
| GET | `/api/audits/{id}?download=true&package=xxx` | 导出（筛选后的）JSON 文件 |
| DELETE | `/api/audits/{id}` | 删除审计记录 |
| GET | `/api/diff?base_id=1&target_id=2` | 对比两次审计（新增/消失/状态变化，含双方最短路径） |
| GET | `/api/matrix` | 许可证兼容矩阵 |
| GET | `/api/sample` | 内置示例 manifest |

示例：

```bash
# 上传文件审计
curl -F "file=@static/examples/sample-manifest.json" http://localhost:8000/api/audit/upload

# 按包筛选并导出
curl -OJ "http://localhost:8000/api/audits/1?package=pdf-export&download=true"

# 对比审计 #1（基准/旧）与 #2（对比/新），仅读取历史，不会生成新审计
curl "http://localhost:8000/api/diff?base_id=1&target_id=2"
```

任一 `audit_id` 不存在时返回 `404` 并指明缺失的是哪一条，例如：

```json
{ "detail": "对比审计记录不存在：9" }
```

### 对比结果结构（节选）

- `base` / `target`：两侧审计的 `audit_id`、名称、状态与汇总；
- `summary`：新增 / 消失 / 状态变化的冲突、节点、告警计数；
- `conflicts.added` / `removed` / `changed`：每条冲突附带 `base` 与 `target`
  两侧快照，`severity`（error=硬冲突 / warning=需人工确认）、`distance` 与
  `path`（该侧 BFS 算出的最短依赖路径）；`added` 仅有 `target`，`removed` 仅有
  `base`，`changed` 两侧都有并给出 `changes`（`status` / `license` / `reason` / `path`）；
- `nodes.added` / `removed` / `license_changed`：按 **包名@版本** 配对的节点变化；
- `warnings.added` / `removed`：解析告警（含未解析依赖）的文本级差异。

```json
{
  "base":   { "audit_id": 1, "manifest_name": "billing-platform-demo", "status": "conflict" },
  "target": { "audit_id": 2, "manifest_name": "billing-platform-demo", "status": "conflict" },
  "summary": {
    "conflicts_added": 1, "conflicts_removed": 2, "conflicts_changed": 1,
    "nodes_added": 1, "nodes_removed": 1, "nodes_license_changed": 1,
    "warnings_added": 0, "warnings_removed": 0
  },
  "conflicts": {
    "added": [
      { "ancestor": "new-g@1.0.0", "node": "apache-lib@1.0.0",
        "base": null,
        "target": { "severity": "error", "distance": 1,
                    "path": ["new-g@1.0.0", "apache-lib@1.0.0"], "reason": "…" } }
    ],
    "removed": [ /* 同构，仅有 base */ ],
    "changed": [
      { "ancestor": "web-app@2.1.0", "node": "duo@1.0.0",
        "changes": ["status", "license"],
        "base":   { "severity": "warning", "distance": 1, "path": ["…", "…"] },
        "target": { "severity": "error",   "distance": 1, "path": ["…", "…"] } }
    ]
  },
  "nodes": {
    "added":   [ { "id": "new-g@1.0.0", "license_display": "GPL-2.0" } ],
    "removed": [ { "id": "gone@1.0.0", "license_display": "GPL-2.0" } ],
    "license_changed": [
      { "id": "duo@1.0.0", "base_license": "OFL-1.1", "target_license": "GPL-2.0" }
    ]
  },
  "warnings": { "added": [], "removed": [] }
}
```

网页上对应入口为页面底部的 **「两次审计对比」** 卡片：两个下拉分别选择基准与对比记录
（默认基准=次新、对比=最新），点击「开始对比」即可看到上述分组结果与双方最短路径。

## 审计结果结构（节选）

```json
{
  "audit_id": 1,
  "manifest_name": "billing-platform-demo",
  "status": "conflict",
  "summary": { "packages": 13, "edges": 15, "conflicts": 4, "license_warnings": 3, "unresolved": 1 },
  "nodes": [
    { "id": "pdf-export@4.0.0", "name": "pdf-export", "version": "4.0.0",
      "license_display": "Apache 2.0", "license": "Apache-2.0",
      "license_category": "permissive",
      "constraints": [ { "from": "billing-core@1.2.0", "license": "GPL-2.0", "distance": 1, "status": "conflict" } ] }
  ],
  "conflicts": [
    {
      "id": "C001", "kind": "license-conflict", "severity": "error",
      "ancestor": "billing-core@1.2.0", "node": "pdf-export@4.0.0",
      "ancestor_license": "GPL-2.0", "node_license": "Apache 2.0",
      "distance": 1,
      "path": ["billing-core@1.2.0", "pdf-export@4.0.0"],
      "reason": "GPL-2.0 与 Apache-2.0 专利条款冲突，不能组合进同一作品。"
    }
  ],
  "unresolved": [ { "source": "web-app@2.1.0", "reference": "cache-redis", "reason": "依赖包未在 packages 中声明" } ],
  "warnings": ["未解析依赖：web-app@2.1.0 -> cache-redis（依赖包未在 packages 中声明）"]
}
```

## 兼容矩阵说明（方向：父作品许可证 → 依赖许可证）

| 父 \ 依赖 | MIT / BSD / ISC / CC0 | Apache-2.0 | MPL-2.0 | LGPL-2.1 / 3.0 | GPL-2.0 | GPL-3.0 | AGPL-3.0 | Proprietary |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| MIT 等宽松型 | ✅ | ✅ | ✅ | ✅* | ✅* | ✅* | ✅* | ⚠️ 授权 |
| MPL-2.0 | ✅ | ✅ | ✅ | 2.1 ❌ / 3.0 ✅ | ❌ | ✅ | ❌ | ❌ |
| LGPL-2.1 | ✅ | ✅ | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ 静态合并 |
| LGPL-3.0 | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ❌ 静态合并 |
| GPL-2.0 | ✅ | ❌ 专利条款 | ❌ | 2.1 ✅ / 3.0 ❌ | ✅ | ❌ | ❌ | ❌ |
| GPL-3.0 | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ❌ | ❌ |
| AGPL-3.0 | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ✅ | ❌ |
| Proprietary | ✅ | ✅ | ⚠️ 需动态链接 | ⚠️ 需动态链接 | ❌ | ❌ | ❌ | ⚠️ 商业授权 |

`*` 弱/强 copyleft 依赖虽可被宽松作品使用，但其义务会继续向分发链下游传递，本工具会在
`constraints` 中如实记录。完整且带逐条理由的矩阵以 `GET /api/matrix` 返回为准。

> 矩阵依据 SPDX / FSF 对常见许可证组合的通行说明整理，仅用于工程侧自动筛查，
> 不构成法律意见；标记 ⚠️ 与 unknown 的条目请由法务人工确认。

## 项目结构

```
.
├── app/
│   ├── main.py        # FastAPI 路由（JSON API + 网页），含 GET /api/diff
│   ├── analyzer.py    # manifest 解析、节点规范化、传递约束、最短路径
│   ├── diff.py        # 两次审计对比：节点/冲突/告警的新增、消失、状态变化
│   ├── licenses.py    # 许可证别名规范化与兼容矩阵
│   └── database.py    # SQLite 初始化与审计记录持久化（对比只读、不写入）
├── static/
│   ├── index.html     # 单文件网页（无外部 CDN 依赖，含审计对比卡片）
│   └── examples/sample-manifest.json
├── tests/
│   ├── test_analyzer.py
│   └── test_diff.py
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

轻量自测（无测试框架依赖）：

```bash
python3 -m tests.test_analyzer   # 规范化 / 兼容矩阵 / 最短路径
python3 -m tests.test_diff       # 两次审计对比
```

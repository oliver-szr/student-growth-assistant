# 项目目录结构与文件说明

当前为 Phase 2：已实现 FastAPI 健康检查，以及 Task、TimeRule 的后端 CRUD。`docs/` 还记录了后续阶段的冻结设计，不代表那些功能已经实现。

```text
student-growth-assistant/
├── .gitignore
├── README.md
├── DIRECTORY_STRUCTURE.md
├── docs/
│   ├── architecture.md
│   └── api-contract.md
└── backend/
    ├── requirements.txt
    ├── pytest.ini
    ├── app/
    │   ├── __init__.py
    │   ├── main.py
    │   ├── database.py
    │   ├── models.py
    │   ├── schemas.py
    │   └── routers/
    │       ├── __init__.py
    │       ├── tasks.py
    │       └── time_rules.py
    ├── data/
    │   └── .gitkeep
    └── tests/
        ├── __init__.py
        ├── conftest.py
        ├── test_health.py
        ├── test_tasks.py
        └── test_time_rules.py
```

| 路径 | 用途 |
|---|---|
| `README.md` | `app_env` 安装、运行、测试和 Swagger 示例。 |
| `.gitignore` | 忽略环境变量、本地 SQLite 文件、缓存、测试临时目录和前端构建产物。 |
| `docs/architecture.md` | Phase 0 冻结架构及分阶段边界。 |
| `docs/api-contract.md` | 核心 API 契约，区分已实现的 Phase 1–2 与后续计划接口。 |
| `backend/app/main.py` | FastAPI 应用、health、路由注册及启动时创建缺失表。 |
| `backend/app/database.py` | 唯一的 SQLite engine、Session 工厂、Base 和 `get_db`。 |
| `backend/app/models.py` | Task、TimeRule ORM 表及受限枚举。 |
| `backend/app/schemas.py` | 两种资源的 Pydantic 创建、更新、响应模型与输入校验。 |
| `backend/app/routers/` | 直接使用 SQLAlchemy Session 的 Task、TimeRule CRUD 路由。 |
| `backend/tests/conftest.py` | 每个测试创建独立临时 SQLite 文件并覆盖数据库依赖。 |
| `backend/tests/test_*.py` | 对真实 FastAPI 路由、持久化和非法输入的测试。 |
| `backend/pytest.ini` | 将 pytest 临时目录放在仓库内的忽略路径。 |
| `backend/data/.gitkeep` | 保留数据目录；本地 `app.db` 被 Git 忽略。 |

运行和测试时还会生成 `__pycache__/`、`.pytest_cache/`、`.pytest_tmp/` 和 `backend/data/app.db`，均不属于源码。当前没有 Plan、Scheduler、AI 或 React 实现。

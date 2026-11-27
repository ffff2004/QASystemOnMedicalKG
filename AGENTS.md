# AGENTS.md

## 项目摘要

中文医疗知识图谱问答（终端与本地 Web）。DeepSeek Flash 生成 Cypher，查询只读 Neo4j，再据图谱结果作答。

## 关键文件

- `chatbot_graph.py`：终端问答入口。
- `llm_qa.py`：workflow / agent 问答；修改 DeepSeek 请求或工具往返前，读 [API 核对记录](docs/deepseek-api-reference.md)。
- `cypher_graph.py`：图谱 schema 和受限的只读查询入口。
- `web_app.py`：本地 Web 入口（FastAPI，仅监听 127.0.0.1）。
- `web_conversations.py`、`web/`：Web 会话文件与前端；`sessions/` 为运行数据。
- `build_medicalgraph.py`、`data/medical.json`：图谱入库脚本和数据。
- `graph_connection.py`：入库脚本的 Neo4j 连接。
- `.env.example`：Neo4j 与 DeepSeek 配置模板。
- `pyproject.toml`、`uv.lock`：Python 依赖声明和锁文件。

## 常用命令

在仓库根目录执行。启动 Neo4j 或配置连接时，参见 [README 的运行说明](README.md#项目运行方式)。

```bash
uv sync --locked                       # 按锁文件同步依赖
uv lock --check                        # 检查锁文件是否与项目配置一致
uv run python -m unittest discover -s tests  # 离线问答测试
uv run python build_medicalgraph.py    # 幂等导入；--reset 先清空数据库
uv run python chatbot_graph.py         # 启动终端问答
uv run python web_app.py               # 启动本地 Web 演示（需 uv sync --extra web）
```

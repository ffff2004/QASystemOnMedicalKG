# AGENTS.md

## 项目摘要

中文医疗知识图谱终端问答。入库脚本将仓库自带的数据导入 Neo4j；问答脚本用词典识别实体和问题类型，生成 Cypher 查询并格式化结果。

## 关键文件

- `chatbot_graph.py`：终端问答入口。
- `question_classifier.py`、`dict/`：问句分类和实体词典。
- `question_parser.py`、`answer_search.py`：生成和执行 Cypher 查询，格式化答案。
- `build_medicalgraph.py`、`data/medical.json`：图谱入库脚本和数据。
- `graph_connection.py`：入库和问答共用的 Neo4j 连接配置，从环境变量或 `.env` 读取。
- `.env.example`：Neo4j 连接配置模板；复制为 `.env` 后使用。
- `pyproject.toml`、`uv.lock`：Python 依赖声明和锁文件。

## 常用命令

在仓库根目录执行。启动 Neo4j 或配置连接时，参见 [README 的运行说明](README.md#项目运行方式)。

```bash
uv sync --locked                       # 按锁文件同步依赖
uv lock --check                        # 检查锁文件是否与项目配置一致
uv run python build_medicalgraph.py    # 幂等导入；--reset 先清空数据库
uv run python chatbot_graph.py         # 启动终端问答
```

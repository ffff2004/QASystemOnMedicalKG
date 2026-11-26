# 医疗知识图谱问答 Demo

中文终端问答。DeepSeek Flash 把问题转成 Cypher，只读查询 Neo4j，再根据图谱结果回答。数据来自原项目随仓库提供的 `data/medical.json`，仅供演示，不用于诊断、处方或商用。

## 项目运行方式

需要 `uv` 和专用的本地 Neo4j（已验证 Community `2026.10.2`）。在仓库根目录执行：

```bash
uv sync --locked
cp -n .env.example .env
```

在 `.env` 中设置 `NEO4J_PASSWORD` 和 `DEEPSEEK_API_KEY`。已有同名环境变量优先；不要提交 `.env`。已有实例和数据可跳过新建容器和入库。

### 新建实例与入库

示例使用 Podman。先启动可写实例、完成入库，再设为只读。

```bash
set -a; . ./.env; set +a
podman run -d --name medical-neo4j \
  -p 127.0.0.1:7687:7687 \
  -e NEO4J_AUTH="${NEO4J_USER}/${NEO4J_PASSWORD}" \
  docker.io/library/neo4j:2026.10.2-community
# 等 Neo4j 就绪后执行（podman logs medical-neo4j 可查看启动状态）
uv run python build_medicalgraph.py
```

在 Neo4j 的 `neo4j.conf` 中设置 `server.databases.read_only=neo4j`（若改了 `NEO4J_DATABASE`，用对应库名），再重启 Neo4j。上面容器的配置路径是 `/var/lib/neo4j/conf/neo4j.conf`。问答启动时会检查服务端只读状态；库可写时不会执行 LLM 生成的 Cypher。

重新导入前，停止问答，临时从 `server.databases.read_only` 移除目标库并重启 Neo4j。导入命令可重复执行；`--reset` 会先清空目标库，仅在确实要重建时使用。导入后恢复只读设置并重启。

### 问答

```bash
# 默认：交互式 workflow，逐问独立处理
uv run python chatbot_graph.py
# 交互式 agent：可拆解查询、追加查询和多轮追问；/reset 清空会话
uv run python chatbot_graph.py --mode agent
# 非交互：只回答一问，并在 stderr 展示 Cypher、参数、Neo4j 原始结果行
uv run python chatbot_graph.py --question '乳腺癌的症状有哪些？' --show-cypher
```

`workflow` 固定按生成查询、查图、作答的顺序执行；`agent` 可根据中间结果追加查询。默认只有交互式 `agent` 重放近期问答和工具往返，历史超出预算时逐轮移除最旧记录；默认退出不保存。历史用于理解追问，答案仍需要本轮查询结果。结果受行数和体积限制，被截断时会标注。

`DEEPSEEK_REASONING_EFFORT` 默认为 `none`（关闭推理），可设为 `low`、`high` 或 `max`。启用推理后，可加 `--show-reasoning` 查看。两个 `--show-*` 开关都只控制 stderr 的展示，不改变模型请求；非交互的 stdout 只输出答案。

Demo 只输入公开知识问句。问句、schema、必要的查询结果和近期 agent 会话上下文可能发送给 DeepSeek；应用不会自动识别患者信息，请勿输入。

### 记录与恢复

```bash
uv run python chatbot_graph.py --mode agent --record session.jsonl
uv run python chatbot_graph.py --mode agent --resume session.jsonl --question '那常见并发症呢？' --record follow-up.jsonl
```

`--record` 适用于所有模式，逐轮写入新的 JSONL 文件，不覆盖已有文件。记录包含问答、查询、结果、模型请求耗时和可用的 token 用量；agent 还会保存工具往返及 API 返回的推理内容。文件可能含敏感内容，请勿直接分享，只导入自己信任的记录。

`--resume` 仅适用于 agent，支持交互式和单问。有 `--record` 时，新文件包含原记录和续跑内容，源文件保持不变。恢复只重放最近一次 `/reset` 后预算内可重放的完整轮次，不重跑旧查询。缺少必需推理字段的已完成轮次仅供分析。可调整 thinking 强度，但不能改变开关状态。异常退出留下的未写完尾行会告警并跳过，其他损坏会阻止导入。

## 开发验证

```bash
uv lock --check
uv run python -m unittest discover -s tests
```

离线测试不需要 API key。修改请求协议时参考 [DeepSeek API 核对记录](docs/deepseek-api-reference.md)。

图谱和数据来自 [刘焕勇的原项目](https://github.com/liuhuanyong/QABasedOnMedicalKnowledgeGraph)。

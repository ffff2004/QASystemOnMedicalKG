import os
from pathlib import Path

from dotenv import load_dotenv
from py2neo import Graph

# 仓库根目录的 .env；已存在的环境变量优先
load_dotenv(Path(__file__).with_name('.env'), override=False)


def connect_graph():
    uri = os.environ.get('NEO4J_URI', 'bolt://127.0.0.1:7687')
    user = os.environ.get('NEO4J_USER', 'neo4j')
    password = os.environ.get('NEO4J_PASSWORD')
    if not password:
        raise SystemExit('请设置 NEO4J_PASSWORD 环境变量，或在 .env 中配置，再连接 Neo4j。')
    return Graph(uri, auth=(user, password))

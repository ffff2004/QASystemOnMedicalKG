import os

from py2neo import Graph


def connect_graph():
    uri = os.environ.get('NEO4J_URI', 'bolt://127.0.0.1:7687')
    user = os.environ.get('NEO4J_USER', 'neo4j')
    password = os.environ.get('NEO4J_PASSWORD')
    if not password:
        raise SystemExit('请设置 NEO4J_PASSWORD 环境变量，再连接 Neo4j。')
    return Graph(uri, auth=(user, password))

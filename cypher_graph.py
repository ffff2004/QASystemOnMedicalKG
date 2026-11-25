"""Bounded, read-only access to the medical knowledge graph."""

import json
import math
import os
import re
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase, READ_ACCESS
from neo4j.exceptions import DriverError, Neo4jError


SCHEMA = """Neo4j 医疗知识图谱（标签、属性、关系类型区分大小写）：
节点：Disease、Symptom、Drug、Food、Check、Department、Producer，均有 name。
Disease 还包含 desc、prevent、cause、easy_get、cure_department、cure_way、
cure_lasttime、cured_prob；cure_department 和 cure_way 可能是字符串列表。

有方向的关系（关系属性 name 为中文描述）：
(:Disease)-[:has_symptom]->(:Symptom)             症状
(:Disease)-[:acompany_with]->(:Disease)            并发症
(:Disease)-[:belongs_to]->(:Department)            所属科室
(:Department)-[:belongs_to]->(:Department)         子科室到上级科室
(:Disease)-[:common_drug]->(:Drug)                 常用药品
(:Disease)-[:recommand_drug]->(:Drug)               好评药品
(:Producer)-[:drugs_of]->(:Drug)                    生产药品
(:Disease)-[:need_check]->(:Check)                  诊断检查
(:Disease)-[:no_eat]->(:Food)                       忌吃
(:Disease)-[:do_eat]->(:Food)                       宜吃
(:Disease)-[:recommand_eat]->(:Food)                推荐食谱

仅生成一条只读的 MATCH / OPTIONAL MATCH / WITH / RETURN 查询，可用 WHERE、
ORDER BY、SKIP；末尾 LIMIT 如需指定，只用非负整数字面量，否则由服务限制返回行数。
所有用户值用 $parameter 传入，另给 parameters 对象；不要在 Cypher 中拼接这些值。
变量和别名使用 ASCII 标识符；不要使用引号、反引号、注释或分号。
使用有方向、固定跳数的关系。RETURN 投影有明确别名的标量（如 s.name AS symptom，
count(*) AS total），也可返回属性中的短标量列表；不要返回节点、关系、路径或映射。
cause 和 prevent 可能过长，必要时用 substring 返回明确标注的节选。
需要多项时优先逐行返回，不用 collect。可用函数：abs、avg、coalesce、count、
head、last、ltrim、max、min、round、rtrim、size、substring、sum、toFloat、
toInteger、toLower、toString、toUpper、trim。不要调用过程、查询子句嵌套或写入。
示例：MATCH (d:Disease {name: $disease})-[:has_symptom]->(s:Symptom)
RETURN DISTINCT s.name AS symptom ORDER BY symptom
"""


class GraphQueryError(Exception):
    """The read-only graph could not be verified or queried safely."""


_TIMEOUT = 5.0
_MAX_QUERY_CHARS = 8_192
_MAX_ROWS = 100
_MAX_COLUMNS = 32
_MAX_LIST_ITEMS = 128
_MAX_VALUE_BYTES = 8_192
_MAX_PARAM_BYTES = 32_768
_MAX_ROW_BYTES = 12_288
_MAX_RESULT_BYTES = 32_768

_IDENTIFIER = re.compile(r'[A-Za-z_][A-Za-z_0-9]*')
_TOKEN = re.compile(r'[ \t\r\n]+|\$?[A-Za-z_][A-Za-z_0-9]*|[0-9]+|[()\[\]{},.:=<>!+*/%^-]')
_FUNCTIONS = frozenset('''
    ABS AVG COALESCE COUNT HEAD LAST LTRIM MAX MIN ROUND RTRIM SIZE SUBSTRING
    SUM TOFLOAT TOINTEGER TOLOWER TOSTRING TOUPPER TRIM
'''.split())
_BEFORE_PAREN = frozenset('''
    MATCH WHERE WITH RETURN DISTINCT AND OR XOR NOT IN WHEN THEN ELSE BY
    AS STARTS ENDS CONTAINS
'''.split())
_UNSUPPORTED_WORDS = frozenset('''
    ALTER CALL CREATE CYPHER DEALLOCATE DELETE DENY DETACH DROP ENABLE EXECUTE EXISTS
    EXPLAIN FILTER FINISH FOREACH GRANT INSERT LET LOAD MERGE NODETACH OFFSET
    PROFILE REALLOCATE REMOVE RENAME REVOKE SET SHOW START STOP
    TERMINATE TRANSACTIONS UNION UNWIND USE
'''.split())
_DATABASE_STATUS_QUERY = (
    'SHOW DATABASES YIELD name, access, currentStatus '
    'WHERE name = $database RETURN access, currentStatus LIMIT 2'
)


def _bounded_query(cypher: str) -> str:
    """Filter the supported syntax; Neo4j remains responsible for parsing it."""
    if type(cypher) is not str or len(cypher) > _MAX_QUERY_CHARS or not cypher.strip():
        raise GraphQueryError('Cypher 为空或超过长度限制。')
    if any(marker in cypher for marker in ('//', '/*', '*/')):
        raise GraphQueryError('Cypher 不允许注释。')

    tokens = []
    end = 0
    for match in _TOKEN.finditer(cypher):
        if match.start() != end:
            raise GraphQueryError('Cypher 含不支持的字符；请用参数传值。')
        end = match.end()
        if not match[0].isspace():
            tokens.append((match[0].upper(), match.start()))
    if end != len(cypher) or not tokens:
        raise GraphQueryError('Cypher 含不支持的字符；请用参数传值。')
    words = [word for word, _ in tokens]
    if words[0] not in {'MATCH', 'OPTIONAL', 'WITH', 'RETURN'}:
        raise GraphQueryError('仅支持 MATCH、OPTIONAL MATCH、WITH 或 RETURN 开头的查询。')

    stack = []
    has_return = False
    final_limit = None
    closing = {')': '(', ']': '[', '}': '{'}
    for i, word in enumerate(words):
        before = words[i - 1] if i else ''
        after = words[i + 1] if i + 1 < len(words) else ''
        if word in _UNSUPPORTED_WORDS:
            raise GraphQueryError('Cypher 含不支持的关键词。')
        if after == '(' and _IDENTIFIER.fullmatch(word):
            if before == '.' or word not in _FUNCTIONS | _BEFORE_PAREN:
                raise GraphQueryError('Cypher 使用了不支持的函数或语法。')

        # Only allow map braces inside parentheses (e.g. node properties).
        if word in ('(', '[', '{'):
            if word == '{' and (not stack or stack[-1] != '('):
                raise GraphQueryError('不支持 Cypher 子查询或量化路径。')
            stack.append(word)
        elif word in closing:
            if not stack or stack.pop() != closing[word]:
                raise GraphQueryError('Cypher 括号不匹配。')
        elif word == '*' and not (i >= 2 and words[i - 2:i] == ['COUNT', '('] and after == ')'):
            raise GraphQueryError('仅支持在 count(*) 中使用 *。')
        elif word == '+' and before in {')', '>', '-'}:
            raise GraphQueryError('不支持量化路径。')
        elif word == 'OPTIONAL' and after != 'MATCH':
            raise GraphQueryError('OPTIONAL 仅可用于 OPTIONAL MATCH。')
        elif word in {'MATCH', 'RETURN', 'WITH'} and before not in {'STARTS', 'ENDS'}:
            if stack or has_return:
                raise GraphQueryError('不支持 Cypher 子查询或 RETURN 后的查询子句。')
            has_return = word == 'RETURN'
        elif not stack and has_return and word == 'LIMIT':
            if final_limit is not None or i + 2 != len(words) or not after.isdigit():
                raise GraphQueryError('末尾 LIMIT 只接受一个非负整数字面量。')
            final_limit = i

    if stack or not has_return:
        raise GraphQueryError('Cypher 括号不匹配或缺少 RETURN。')
    probe_limit = _MAX_ROWS + 1
    if final_limit is not None:
        digits = words[final_limit + 1].lstrip('0') or '0'
        if len(digits) <= len(str(probe_limit)):
            probe_limit = min(probe_limit, int(digits))
        cypher = cypher[:tokens[final_limit][1]]
    return f'{cypher.rstrip()}\nLIMIT {probe_limit}'


def _scalar(value):
    return (
        value is None or type(value) in (bool, str)
        or (type(value) is int and -(2**63) <= value < 2**63)
        or (type(value) is float and math.isfinite(value))
    )


def _json_size(value, limit: int) -> int:
    """Count compact UTF-8 JSON without serializing unbounded containers."""
    if type(value) is list:
        if len(value) > _MAX_LIST_ITEMS:
            return limit + 1
        size = max(0, len(value) - 1) + 2  # brackets and commas
        for item in value:
            if not _scalar(item):
                raise GraphQueryError('列表仅支持标量值。')
            size += _json_size(item, min(limit - size, _MAX_VALUE_BYTES))
            if size > limit:
                return limit + 1
        return size
    if not _scalar(value):
        raise GraphQueryError('仅支持 JSON 标量或标量列表。')
    if type(value) is str and len(value) + 2 > limit:
        return limit + 1
    try:
        return len(json.dumps(value, ensure_ascii=False).encode('utf-8'))
    except UnicodeError:
        raise GraphQueryError('参数或结果含无效 Unicode。') from None


def _mapping_size(mapping: dict, limit: int) -> int:
    if len(mapping) > _MAX_COLUMNS:
        return limit + 1
    size = max(0, len(mapping) - 1) + 2  # braces and commas
    for key, value in mapping.items():
        size += _json_size(key, limit - size) + 1  # colon
        remaining = min(limit - size, _MAX_VALUE_BYTES)
        value_size = _json_size(value, remaining)
        if value_size > remaining:
            return limit + 1
        size += value_size
    return size


class CypherGraph:
    """Call ensure_read_only() at startup; each query also checks before execution."""

    def __init__(self):
        # Match graph_connection.py's defaults without using its py2neo driver.
        load_dotenv(Path(__file__).with_name('.env'), override=False)
        uri = os.environ.get('NEO4J_URI', 'bolt://127.0.0.1:7687')
        user = os.environ.get('NEO4J_USER', 'neo4j')
        password = os.environ.get('NEO4J_PASSWORD')
        self._database = os.environ.get('NEO4J_DATABASE', 'neo4j')
        if not password:
            raise GraphQueryError('请设置 NEO4J_PASSWORD。')
        if not self._database or self._database.lower() == 'system':
            raise GraphQueryError('NEO4J_DATABASE 必须是可验证的只读图谱数据库。')
        try:
            self._driver = GraphDatabase.driver(
                uri, auth=(user, password), connection_timeout=_TIMEOUT,
                connection_acquisition_timeout=_TIMEOUT,
            )
        except (DriverError, Neo4jError, OSError, ValueError):
            raise GraphQueryError('无法初始化 Neo4j 驱动；请检查连接配置。') from None

    def ensure_read_only(self):
        """Require the configured database to be visible, online and read-only."""
        # Driver READ routing is defense in depth, not the authorization check.
        try:
            with self._driver.session(database='system', default_access_mode=READ_ACCESS) as session:
                with session.begin_transaction(timeout=_TIMEOUT) as tx:
                    rows = list(tx.run(_DATABASE_STATUS_QUERY, parameters={'database': self._database}))
        except (DriverError, Neo4jError, OSError, ValueError):
            raise GraphQueryError('无法验证 Neo4j 数据库的服务端只读状态。') from None
        if (len(rows) != 1 or rows[0].get('access') != 'read-only'
                or rows[0].get('currentStatus') != 'online'):
            raise GraphQueryError('Neo4j 数据库未确认在线且为服务端只读，已拒绝查询。')

    def query(self, cypher: str, parameters: dict) -> dict:
        """Return raw rows up to the first exceeded limit, marking any truncation."""
        cypher = _bounded_query(cypher)
        if (type(parameters) is not dict or len(parameters) > _MAX_COLUMNS
                or any(type(key) is not str or len(key) > 128 or not _IDENTIFIER.fullmatch(key)
                       for key in parameters)):
            raise GraphQueryError('parameters 必须是使用 ASCII 标识符作为键的参数字典。')
        if _mapping_size(parameters, _MAX_PARAM_BYTES) > _MAX_PARAM_BYTES:
            raise GraphQueryError('Cypher 参数超过大小限制。')

        self.ensure_read_only()
        rows = []
        truncated = False
        result_size = 2  # surrounding array
        try:
            with self._driver.session(
                database=self._database, default_access_mode=READ_ACCESS, fetch_size=1,
            ) as session:
                with session.begin_transaction(timeout=_TIMEOUT) as tx:
                    for record in tx.run(cypher, parameters=parameters):
                        if len(rows) == _MAX_ROWS or len(record) > _MAX_COLUMNS:
                            truncated = True
                            break
                        # Record.data() coerces graph entities; retain original values instead.
                        row = dict(record)
                        row_size = _mapping_size(row, _MAX_ROW_BYTES)
                        result_size += row_size + bool(rows)
                        if row_size > _MAX_ROW_BYTES or result_size > _MAX_RESULT_BYTES:
                            truncated = True
                            break
                        rows.append(row)
        except (DriverError, Neo4jError, OSError, ValueError):
            raise GraphQueryError('Neo4j 无法执行此只读 Cypher 查询。') from None
        return {'rows': rows, 'truncated': truncated, 'executed_cypher': cypher}

    def close(self):
        self._driver.close()

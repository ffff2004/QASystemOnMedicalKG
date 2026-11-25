import os
import unittest
from contextlib import nullcontext
from unittest.mock import patch

from cypher_graph import CypherGraph, GraphQueryError


class FakeDriver:
    def __init__(self, access, rows):
        self.access = access
        self.rows = rows
        self.graph_queries = []

    def session(self, *, database, **kwargs):
        driver = self

        class Session:
            def begin_transaction(self, **kwargs):
                return nullcontext(self)

            def run(self, cypher, *, parameters):
                if database == 'system':
                    return [{'access': driver.access, 'currentStatus': 'online'}]
                driver.graph_queries.append((cypher, parameters))
                return iter(driver.rows)

        return nullcontext(Session())

    def close(self):
        pass


class GraphQueryTest(unittest.TestCase):
    def graph(self, driver):
        with (
            patch.dict(os.environ, {'NEO4J_PASSWORD': 'offline-test', 'NEO4J_DATABASE': 'neo4j'}),
            patch('cypher_graph.GraphDatabase.driver', return_value=driver),
        ):
            graph = CypherGraph()
        self.addCleanup(graph.close)
        return graph

    def test_refuses_execution_if_server_switches_to_read_write(self):
        driver = FakeDriver('read-only', [])
        graph = self.graph(driver)
        graph.ensure_read_only()
        driver.access = 'read-write'

        with self.assertRaises(GraphQueryError):
            graph.query('MATCH (d:Disease) RETURN d.name AS disease', {})
        self.assertEqual(driver.graph_queries, [])

    def test_returns_raw_bounded_rows_and_reports_executed_cypher(self):
        rows = [{'disease': f'疾病 {i}'} for i in range(101)]
        driver = FakeDriver('read-only', rows)
        graph = self.graph(driver)
        params = {'prefix': '疾病'}

        result = graph.query('MATCH (d:Disease) WHERE d.name STARTS WITH $prefix RETURN d.name AS disease', params)

        self.assertTrue(result['truncated'])
        self.assertLess(len(result['rows']), len(rows))
        self.assertEqual(result['rows'], rows[:len(result['rows'])])
        self.assertEqual(driver.graph_queries, [(result['executed_cypher'], params)])

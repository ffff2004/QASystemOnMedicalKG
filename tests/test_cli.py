import io
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from chatbot_graph import main


def completion(content):
    message = SimpleNamespace(content=content, reasoning_content='模拟推理', tool_calls=None)
    return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason='stop')])


class CLITest(unittest.TestCase):
    def run_workflow(self, flags):
        client = MagicMock()
        client.__enter__.return_value = client
        client.chat.completions.create.side_effect = [
            completion('{"queries":[{"cypher":"MATCH (d:Disease) RETURN d.name AS disease", "parameters":{}}]}'),
            completion('这是最终答案。'),
        ]
        graph = MagicMock()
        graph.query.return_value = {
            'rows': [{'disease': '乳腺癌'}], 'truncated': True,
            'executed_cypher': 'MATCH (d:Disease) RETURN d.name AS disease\nLIMIT 101',
        }
        stdout, stderr = io.StringIO(), io.StringIO()
        with (
            patch.dict(os.environ, {'DEEPSEEK_API_KEY': 'offline-test', 'DEEPSEEK_THINKING': 'enabled'}),
            patch('chatbot_graph.CypherGraph', return_value=graph),
            patch('chatbot_graph.OpenAI', return_value=client),
            redirect_stdout(stdout), redirect_stderr(stderr),
        ):
            self.assertEqual(main(['--question', '查一个疾病名称', *flags]), 0)
        requests = [call.kwargs for call in client.chat.completions.create.call_args_list]
        return stdout.getvalue(), stderr.getvalue(), requests

    def test_traces_are_opt_in_and_do_not_change_requests(self):
        plain, quiet, quiet_requests = self.run_workflow([])
        traced, diagnostics, traced_requests = self.run_workflow(['--show-cypher', '--show-reasoning'])

        self.assertEqual(plain, traced)
        self.assertIn('这是最终答案。', traced)
        self.assertEqual(quiet, '')
        self.assertIn('MATCH (d:Disease)', diagnostics)
        self.assertIn('LIMIT 101', diagnostics)
        self.assertIn('{"disease": "乳腺癌"}', diagnostics)
        self.assertIn('结果已截断', diagnostics)
        self.assertIn('模拟推理', diagnostics)
        self.assertEqual(quiet_requests, traced_requests)

    def test_interactive_and_question_cannot_be_combined(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            main(['--interactive', '--question', '问题'])
        self.assertEqual(error.exception.code, 2)

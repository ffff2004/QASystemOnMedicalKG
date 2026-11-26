import io
import json
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from chatbot_graph import main


def completion(content, *, calls=None, reasoning='模拟推理', finish_reason='stop'):
    message = SimpleNamespace(content=content, reasoning_content=reasoning, tool_calls=calls)
    usage = SimpleNamespace(prompt_tokens=30, completion_tokens=10,
                            prompt_cache_hit_tokens=20, prompt_cache_miss_tokens=10)
    return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason=finish_reason)], usage=usage)


def graph_call():
    arguments = '{"cypher":"MATCH (d:Disease) RETURN d.name AS disease", "parameters":{}}'
    return SimpleNamespace(id='call-1', type='function',
                           function=SimpleNamespace(name='query_graph', arguments=arguments))


def events(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').split('\n') if line]


def encode_events(*items):
    return ''.join(json.dumps(item) + '\n' for item in items).encode('utf-8')


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
            patch.dict(os.environ, {'DEEPSEEK_API_KEY': 'offline-test', 'DEEPSEEK_REASONING_EFFORT': 'low'}),
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
        self.assertEqual([req['reasoning_effort'] for req in traced_requests], ['low', 'low'])

    def test_removed_interactive_flag_is_rejected(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            main(['--interactive'])
        self.assertEqual(error.exception.code, 2)

    def test_workflow_records_queries_and_request_usage_without_changing_stdout(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'workflow.jsonl'
            stdout, stderr, _ = self.run_workflow(['--record', str(path)])
            header, turn = events(path)

        self.assertEqual(stderr, '')
        self.assertEqual(stdout, '这是最终答案。\n')
        self.assertEqual(header['mode'], 'workflow')
        self.assertEqual(turn['answer'], stdout.strip())
        self.assertEqual(turn['queries'][0]['result']['rows'], [{'disease': '乳腺癌'}])
        self.assertEqual(len(turn['requests']), 2)
        for request in turn['requests']:
            self.assertGreaterEqual(request['elapsed_ms'], 0)
            self.assertEqual(request['prompt_tokens'], 30)
            self.assertEqual(request['completion_tokens'], 10)
            self.assertEqual(request['prompt_cache_hit_tokens'], 20)
            self.assertEqual(request['prompt_cache_miss_tokens'], 10)

    def run_agent(self, flags, *responses, questions=(), effort='low'):
        client = MagicMock()
        client.__enter__.return_value = client
        client.chat.completions.create.side_effect = responses
        graph = MagicMock()
        graph.query.return_value = {'rows': [{'disease': '乳腺癌'}], 'truncated': False}
        stdout, stderr = io.StringIO(), io.StringIO()
        with (
            patch.dict(os.environ, {'DEEPSEEK_API_KEY': 'offline-test', 'DEEPSEEK_REASONING_EFFORT': effort}),
            patch('chatbot_graph.CypherGraph', return_value=graph),
            patch('chatbot_graph.OpenAI', return_value=client),
            patch('builtins.input', side_effect=[*questions, EOFError]),
            redirect_stdout(stdout), redirect_stderr(stderr),
        ):
            code = main(['--mode', 'agent', *flags])
        requests = [call.kwargs for call in client.chat.completions.create.call_args_list]
        return code, stdout.getvalue(), stderr.getvalue(), requests, graph.query.call_count

    def test_agent_resume_forks_log_and_replays_only_completed_turns_since_reset(self):
        with TemporaryDirectory() as directory:
            source = Path(directory) / 'source.jsonl'
            output = Path(directory) / 'fork.jsonl'
            code, _, _, _, _ = self.run_agent(
                ['--record', str(source)], completion('没有证据'), RuntimeError('offline'),
                completion(None, calls=[graph_call()]), completion('保留的回答'),
                questions=['已重置的问题', '/reset', '失败的问题', '保留的问题'],
            )
            self.assertEqual(code, 0)
            original = source.read_bytes()
            source_events = events(source)
            self.assertEqual([e['event'] for e in source_events], ['header', 'turn', 'reset', 'turn', 'turn'])
            self.assertEqual(source_events[3]['status'], 'failed')
            self.assertEqual(source.stat().st_mode & 0o077, 0)

            code, stdout, stderr, requests, n_queries = self.run_agent(
                ['--resume', str(source), '--record', str(output), '--question', '继续追问'],
                completion('不能使用旧证据直接回答'), effort='high',
            )
            self.assertEqual(code, 0)
            self.assertEqual(stderr, '')
            self.assertIn('未找到足够的图谱证据', stdout)
            self.assertEqual(n_queries, 0)
            self.assertEqual(requests[0]['messages'][1:-1], source_events[-1]['messages'])
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(events(output)[:-1], source_events)
            self.assertEqual(events(output)[-1]['reasoning_effort'], 'high')
            code, _, _, requests, _ = self.run_agent(
                ['--resume', str(output)], completion('无新证据'), questions=['再追问'],
            )
            self.assertEqual(code, 0)
            self.assertEqual(requests[0]['messages'][1:-1],
                             source_events[-1]['messages'] + events(output)[-1]['messages'])

    def test_resume_warns_for_partial_tail_and_rejects_invalid_or_mismatched_records(self):
        with TemporaryDirectory() as directory:
            source = Path(directory) / 'source.jsonl'
            code, _, _, _, _ = self.run_agent(
                ['--record', str(source), '--question', '起始问题'], completion('无证据'),
            )
            self.assertEqual(code, 0)
            original = source.read_bytes()
            source.write_bytes(original + b'{"event":')
            options = ['--resume', str(source), '--question', '追问']
            code, _, stderr, requests, _ = self.run_agent(options, completion('无证据'))
            self.assertEqual(code, 0)
            self.assertIn('末尾未写完', stderr)
            self.assertIn('起始问题', requests[0]['messages'][1]['content'])

            source.write_bytes(original)
            code, _, stderr, requests, _ = self.run_agent(options + ['--record', str(source)])
            self.assertEqual(code, 1)
            self.assertIn('已存在', stderr)
            self.assertFalse(requests)
            self.assertEqual(source.read_bytes(), original)

            code, _, stderr, requests, _ = self.run_agent(options, effort='none')
            self.assertEqual(code, 1)
            self.assertIn('thinking 开关', stderr)
            self.assertFalse(requests)

            header, turn = events(source)
            user, assistant = turn['messages']
            for bad_record in (encode_events(header) + b'{invalid}\n' + encode_events(turn),
                               encode_events({**header, 'version': 99}, turn),
                               encode_events(header, {**turn, 'messages': [user, {**assistant, 'role': 'system'}]})):
                with self.subTest(bad_record=bad_record):
                    source.write_bytes(bad_record)
                    code, _, stderr, requests, _ = self.run_agent(options)
                    self.assertEqual(code, 1)
                    self.assertIn('记录文件', stderr)
                    self.assertFalse(requests)

    def test_agent_keeps_answers_with_missing_thinking_for_analysis_only(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'source.jsonl'
            code, stdout, _, requests, _ = self.run_agent(
                ['--record', str(path)], completion(None, calls=[graph_call()]),
                completion('已查到证据。', reasoning=None), completion('没有证据'),
                questions=['首问', '第二问'],
            )
            self.assertEqual(code, 0)
            self.assertIn('已查到证据。', stdout)
            self.assertEqual([m['role'] for m in requests[-1]['messages']], ['system', 'user'])

            _, first, second = events(path)
            self.assertEqual(first['answer'], '已查到证据。')
            self.assertIs(first['replayable'], False)
            code, _, stderr, requests, _ = self.run_agent(
                ['--resume', str(path), '--question', '第三问'], completion('没有证据'),
            )
            self.assertEqual(code, 0, stderr)
            self.assertEqual(requests[0]['messages'][1:-1], second['messages'])

    def test_agent_does_not_continue_tool_round_with_missing_thinking(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'source.jsonl'
            code, stdout, stderr, requests, queries = self.run_agent(
                ['--record', str(path), '--question', '首问'], completion(None, calls=[graph_call()], reasoning=None),
            )
            self.assertEqual(code, 1)
            self.assertEqual(stdout, '')
            self.assertIn('缺少推理', stderr)
            self.assertEqual(len(requests), 1)
            self.assertEqual(queries, 0)
            code, _, stderr, requests, _ = self.run_agent(
                ['--resume', str(path), '--question', '第二问'], completion('没有证据'),
            )
            self.assertEqual(code, 0, stderr)
            self.assertEqual([m['role'] for m in requests[0]['messages']], ['system', 'user'])

    def test_resume_rejects_invalid_analysis_fields_with_line_number(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'source.jsonl'
            self.run_agent(
                ['--record', str(path)], RuntimeError('offline'),
                completion(None, calls=[graph_call()]), completion('有证据'),
                questions=['首问', '第二问'],
            )
            header, failed, completed = events(path)
            missing_requests = {key: value for key, value in completed.items() if key != 'requests'}
            empty_cypher = {**completed['queries'][0], 'cypher': ' '}
            for broken, line in (([{**failed, 'messages': [None]}, completed], 2),
                                 ([{**failed, 'requests': 1}, completed], 2),
                                 ([failed, missing_requests], 3),
                                 ([failed, {**completed, 'requests': []}], 3),
                                 ([failed, {**completed, 'queries': [empty_cypher]}], 3),
                                 ([failed, {**completed, 'queries': [{'result': []}]}], 3),
                                 ([failed, {**completed, 'requests': [{'elapsed_ms': 'bad'}]}], 3)):
                with self.subTest(broken=broken):
                    path.write_bytes(encode_events(header, *broken))
                    code, _, stderr, requests, _ = self.run_agent(['--resume', str(path), '--question', '第三问'])
                    self.assertEqual(code, 1)
                    self.assertIn(f'第 {line} 行', stderr)
                    self.assertFalse(requests)

    def test_failed_agent_request_records_returned_reasoning_and_nested_cache_usage(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'source.jsonl'
            response = completion(None, reasoning='中止前的推理原文。 ', finish_reason='length')
            response.usage = SimpleNamespace(prompt_tokens=30, completion_tokens=10,
                                             prompt_tokens_details=SimpleNamespace(cached_tokens=20))
            code, stdout, _, _, _ = self.run_agent(
                ['--record', str(path), '--question', '首问'], response,
            )
            self.assertEqual(code, 1)
            self.assertEqual(stdout, '')
            _, turn = events(path)
            self.assertEqual(turn['status'], 'failed')
            request, = turn['requests']
            self.assertEqual(request['reasoning_content'], '中止前的推理原文。 ')
            self.assertEqual(request['prompt_cache_hit_tokens'], 20)
            self.assertEqual(request['prompt_cache_miss_tokens'], 10)

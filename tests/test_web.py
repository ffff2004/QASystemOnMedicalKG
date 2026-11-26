import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

try:
    from fastapi.testclient import TestClient
    from web_app import create_app
except ImportError:  # The web extra is optional; the terminal QA is not.
    TestClient = None

from cypher_graph import GraphQueryError
from session_record import load_record, read_header, replay_turns


def completion(content, *, calls=None, reasoning='模拟推理', finish_reason='stop'):
    message = SimpleNamespace(content=content, reasoning_content=reasoning, tool_calls=calls)
    usage = SimpleNamespace(prompt_tokens=30, completion_tokens=10,
                            prompt_cache_hit_tokens=20, prompt_cache_miss_tokens=10)
    return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason=finish_reason)], usage=usage)


def graph_call(cypher='MATCH (d:Disease) RETURN d.name AS disease', call_id='call-1'):
    return SimpleNamespace(id=call_id, type='function', function=SimpleNamespace(
        name='query_graph', arguments=json.dumps({'cypher': cypher, 'parameters': {}})))


def parse_sse(text):
    events = []
    for block in text.split('\n\n'):
        name, data = None, []
        for line in block.splitlines():
            if line.startswith('event: '):
                name = line[7:]
            elif line.startswith('data: '):
                data.append(line[6:])
        if name and data:
            events.append((name, json.loads('\n'.join(data))))
    return events


@unittest.skipUnless(TestClient is not None, '需要安装 web 依赖：uv sync --extra web')
class WebTest(unittest.TestCase):
    def setUp(self):
        self._directory = TemporaryDirectory()
        self.sessions = Path(self._directory.name)
        self.llm = MagicMock()
        self.graph = MagicMock()
        self.graph.query.return_value = {'rows': [{'disease': '乳腺癌'}], 'truncated': False}
        self.app = create_app(client=self.llm, graph=self.graph, sessions_dir=self.sessions)
        self.http = TestClient(self.app)

    def tearDown(self):
        self._directory.cleanup()

    def create(self, mode='workflow', effort='low'):
        response = self.http.post('/api/conversations', json={'mode': mode, 'effort': effort})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()['conversation']

    def ask(self, conversation_id, question='乳腺癌的症状有哪些？'):
        response = self.http.post(f'/api/conversations/{conversation_id}/turns', json={'question': question})
        self.assertEqual(response.status_code, 200, response.text)
        return parse_sse(response.text)

    def view(self, conversation_id):
        response = self.http.get(f'/api/conversations/{conversation_id}')
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()['conversation']

    def path(self, conversation_id):
        return self.sessions / f'{conversation_id}.jsonl'

    def test_conversations_are_created_listed_and_deleted(self):
        with patch.dict(os.environ, {'DEEPSEEK_REASONING_EFFORT': 'high'}):
            self.assertEqual(self.http.get('/api/config').json(), {'default_effort': 'high'})

        conversation = self.create(mode='agent', effort='low')
        header = read_header(self.path(conversation['id']))
        self.assertEqual((header['mode'], header['effort']), ('agent', 'low'))
        self.assertEqual(header['thinking'], True)

        listed = self.http.get('/api/conversations').json()['conversations']
        self.assertEqual([(item['id'], item['title']) for item in listed], [(conversation['id'], '新对话')])

        view = self.view(conversation['id'])
        self.assertEqual(view['turns'], [])
        self.assertTrue(view['resumable'])
        self.assertIsNone(view['pending'])

        self.assertEqual(self.http.delete(f"/api/conversations/{conversation['id']}").status_code, 204)
        self.assertFalse(self.path(conversation['id']).exists())
        self.assertEqual(self.http.get(f"/api/conversations/{conversation['id']}").status_code, 404)
        self.assertEqual(self.http.delete(f"/api/conversations/{conversation['id']}").status_code, 404)
        self.assertEqual(self.http.get('/api/conversations/not-an-id').status_code, 404)
        self.assertEqual(self.http.post('/api/conversations', json={'mode': 'chat'}).status_code, 422)
        self.assertEqual(self.http.post('/api/conversations', json={'effort': 'minimal'}).status_code, 422)

    def test_turns_reject_empty_and_overlong_questions(self):
        conversation = self.create()
        for question in ('', '   ', 'x' * 4001):
            response = self.http.post(f"/api/conversations/{conversation['id']}/turns",
                                      json={'question': question})
            self.assertEqual(response.status_code, 422)
        self.assertEqual(self.view(conversation['id'])['turns'], [])

    def test_serves_the_single_page_ui(self):
        page = self.http.get('/')
        self.assertEqual(page.status_code, 200)
        self.assertIn('医学图谱问答', page.text)
        for asset in ('styles.css', 'app.js'):
            self.assertEqual(self.http.get(f'/assets/{asset}').status_code, 200)

    def test_workflow_turn_streams_ordered_steps_and_survives_restart(self):
        self.llm.chat.completions.create.side_effect = [
            completion('{"queries":[{"cypher":"MATCH (d:Disease) RETURN d.name AS disease",'
                       '"parameters":{}}]}', reasoning='规划推理'),
            completion('这是最终答案。', reasoning='作答推理'),
        ]
        conversation = self.create()
        events = self.ask(conversation['id'])

        self.assertEqual([name for name, _ in events], ['step', 'step', 'step', 'turn'])
        steps = [data for name, data in events if name == 'step']
        self.assertEqual([step['kind'] for step in steps], ['reasoning', 'query', 'reasoning'])
        self.assertEqual(steps[0]['text'], '规划推理')
        self.assertEqual(steps[1]['cypher'], 'MATCH (d:Disease) RETURN d.name AS disease')
        self.assertEqual(steps[1]['result']['rows'], [{'disease': '乳腺癌'}])
        self.assertEqual(steps[2]['text'], '作答推理')

        turn = events[-1][1]
        self.assertEqual(turn['answer'], '这是最终答案。')
        self.assertEqual(turn['status'], 'completed')
        self.assertEqual(turn['usage']['prompt_tokens'], 60)
        self.assertEqual(turn['usage']['completion_tokens'], 20)
        self.assertEqual(turn['usage']['prompt_cache_hit_tokens'], 40)
        self.assertEqual([step['kind'] for step in turn['steps']], ['reasoning', 'query', 'reasoning'])

        restarted = TestClient(create_app(client=self.llm, graph=self.graph, sessions_dir=self.sessions))
        view = restarted.get(f"/api/conversations/{conversation['id']}").json()['conversation']
        self.assertEqual(view['title'], '乳腺癌的症状有哪些？')
        self.assertEqual([turn['question'] for turn in view['turns']], ['乳腺癌的症状有哪些？'])
        self.assertEqual([step['kind'] for step in view['turns'][0]['steps']], ['reasoning', 'query', 'reasoning'])
        self.assertEqual(view['turns'][0]['steps'][0]['text'], '规划推理')
        self.assertEqual(view['turns'][0]['steps'][2]['text'], '作答推理')

    def test_agent_turn_replays_completed_turns_into_the_next_request(self):
        self.llm.chat.completions.create.side_effect = [
            completion(None, calls=[graph_call()], reasoning='第一轮推理'),
            completion('第一轮答案。', reasoning='第一轮作答'),
            completion(None, calls=[graph_call(call_id='call-2')], reasoning='第二轮推理'),
            completion('第二轮答案。', reasoning='第二轮作答'),
        ]
        conversation = self.create(mode='agent')
        self.assertEqual(self.ask(conversation['id'], '第一问')[-1][1]['answer'], '第一轮答案。')
        self.assertEqual(self.ask(conversation['id'], '第二问')[-1][1]['answer'], '第二轮答案。')

        requests = [call.kwargs for call in self.llm.chat.completions.create.call_args_list]
        messages = requests[2]['messages']
        self.assertEqual(len(messages), 6)
        self.assertEqual(messages[0]['role'], 'system')
        self.assertEqual(json.loads(messages[1]['content']), {'question': '第一问'})
        self.assertEqual(messages[2]['tool_calls'][0]['function']['name'], 'query_graph')
        self.assertEqual(messages[2]['reasoning_content'], '第一轮推理')
        self.assertEqual(messages[3]['role'], 'tool')
        self.assertEqual(messages[4]['content'], '第一轮答案。')
        self.assertEqual(json.loads(messages[-1]['content']), {'question': '第二问'})

    def test_failed_query_is_visible_in_the_recorded_turn(self):
        self.llm.chat.completions.create.side_effect = [
            completion('{"queries":[{"cypher":"MATCH (d:Disease) RETURN d.name AS disease",'
                       '"parameters":{}}]}'),
        ]
        self.graph.query.side_effect = GraphQueryError('图谱连接失败')
        conversation = self.create()
        turn = self.ask(conversation['id'])[-1][1]

        self.assertEqual(turn['status'], 'failed')
        self.assertIn('图谱查询失败', turn['answer'])
        self.assertEqual([step['kind'] for step in turn['steps']], ['reasoning', 'query'])
        self.assertIn('error', turn['steps'][-1]['result'])
        self.assertEqual(self.view(conversation['id'])['turns'][0]['steps'][-1]['result']['error'],
                         turn['steps'][-1]['result']['error'])

    def test_a_model_failure_still_persists_a_failed_turn(self):
        self.llm.chat.completions.create.side_effect = RuntimeError('boom')
        conversation = self.create()
        turn = self.ask(conversation['id'])[-1][1]

        self.assertEqual(turn['status'], 'failed')
        self.assertIn('模型请求失败', turn['error'])
        self.assertEqual(len(self.view(conversation['id'])['turns']), 1)

    def test_only_one_turn_runs_at_a_time(self):
        conversation = self.create()
        store = self.app.state.conversations
        store.begin(conversation['id'], '正在处理')
        try:
            self.assertEqual(self.view(conversation['id'])['pending']['question'], '正在处理')
            response = self.http.post(f"/api/conversations/{conversation['id']}/turns",
                                      json={'question': '另一个问题'})
            self.assertEqual(response.status_code, 409)
            self.assertEqual(self.http.delete(f"/api/conversations/{conversation['id']}").status_code, 409)
        finally:
            store.end(conversation['id'])
        self.assertEqual(self.http.delete(f"/api/conversations/{conversation['id']}").status_code, 204)

    def test_unreadable_agent_record_is_browsable_but_not_continuable(self):
        conversation = self.create(mode='agent')
        with open(self.path(conversation['id']), 'a', encoding='utf-8') as file:
            file.write('{"event": "turn", "question": "坏行"}\n')

        view = self.view(conversation['id'])
        self.assertFalse(view['resumable'])
        self.assertTrue(view['resume_error'])
        self.assertEqual(view['turns'], [])
        response = self.http.post(f"/api/conversations/{conversation['id']}/turns",
                                  json={'question': '继续'})
        self.assertEqual(response.status_code, 409)

    def test_cli_loader_accepts_a_web_agent_record(self):
        self.llm.chat.completions.create.side_effect = [
            completion(None, calls=[graph_call()]),
            completion('答案。'),
        ]
        conversation = self.create(mode='agent')
        self.ask(conversation['id'])

        source = load_record(self.path(conversation['id']), reasoning_effort='low', warn=self.fail)
        self.assertEqual(len(list(replay_turns(source))), 1)

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from session_record import RecordError, append_file, load_display, read_header, record_file


class SessionRecordTest(unittest.TestCase):
    def setUp(self):
        self._directory = TemporaryDirectory()
        self.path = Path(self._directory.name) / 'session.jsonl'

    def tearDown(self):
        self._directory.cleanup()

    def events(self):
        return [json.loads(line) for line in self.path.read_text(encoding='utf-8').split('\n') if line]

    def turn(self, question='问题', answer='答案'):
        return {
            'event': 'turn', 'question': question, 'status': 'completed', 'model': 'deepseek-flash',
            'reasoning_effort': 'low', 'requests': [{'elapsed_ms': 1.0, 'reasoning_content': '推理'}],
            'queries': [], 'answer': answer,
        }

    def test_append_file_creates_a_private_header_then_appends(self):
        with append_file(self.path, mode='workflow', reasoning_effort='low') as append:
            append(self.turn())

        header = read_header(self.path)
        self.assertEqual((header['mode'], header['thinking'], header['effort']), ('workflow', True, 'low'))
        self.assertEqual(self.path.stat().st_mode & 0o077, 0)
        self.assertEqual(len(self.events()), 2)

        with append_file(self.path, mode='workflow', reasoning_effort='low') as append:
            append(self.turn('第二问', '第二答'))

        self.assertEqual([event.get('question') for event in self.events()[1:]], ['问题', '第二问'])
        self.assertEqual(self.events()[0], header)

    def test_append_file_rejects_a_different_mode_or_thinking_switch(self):
        with append_file(self.path, mode='agent', reasoning_effort='low'):
            pass

        for mode, effort in (('workflow', 'low'), ('agent', 'none'), ('agent', 'high')):
            with self.assertRaises(RecordError):
                with append_file(self.path, mode=mode, reasoning_effort=effort):
                    pass

    def test_append_file_accepts_a_header_written_by_the_cli(self):
        with record_file(self.path, mode='workflow', reasoning_effort='low', source=None) as append:
            append(self.turn())

        header = read_header(self.path)
        self.assertNotIn('effort', header)
        with append_file(self.path, mode='workflow', reasoning_effort='low') as append:
            append(self.turn('第二问', '第二答'))

        self.assertEqual(len(self.events()), 3)
        self.assertEqual(self.path.stat().st_mode & 0o077, 0)

    def test_load_display_skips_unreadable_turns_and_a_partial_tail(self):
        with append_file(self.path, mode='workflow', reasoning_effort='none') as append:
            append(self.turn())
        with open(self.path, 'a', encoding='utf-8') as file:
            file.write('{"event": "turn", "question": "缺状态"}\n')
            file.write('not json\n')
            file.write('{"event": "turn", "question": "未写完"')

        header, turns = load_display(self.path)
        self.assertEqual(header['mode'], 'workflow')
        self.assertEqual([turn['question'] for turn in turns], ['问题'])

    def test_read_header_rejects_a_missing_or_unusable_header(self):
        with self.assertRaises(RecordError):
            read_header(self.path)
        self.path.write_text('{"event": "header", "version": 99}\n', encoding='utf-8')
        with self.assertRaises(RecordError):
            read_header(self.path)

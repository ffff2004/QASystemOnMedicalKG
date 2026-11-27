"""Conversation files and their presentation for the local web demo."""

import re
import threading
import time
import uuid
from pathlib import Path

from session_record import EFFORTS, RecordError, append_file, load_display, load_record, replay_turns

MODES = ("workflow", "agent")
_TITLE_CHARS = 20
_ID = re.compile(r"[0-9a-f]{12}")
_MISSING = "对话不存在。"


class ConversationError(Exception):
    """The conversation cannot be created, read, continued or deleted."""

    status = 409


class ConversationNotFound(ConversationError):
    status = 404


class Conversations:
    """One JSONL file per conversation; the directory is the only source of truth."""

    def __init__(self, directory):
        self.directory = Path(directory)
        self._lock = threading.Lock()
        self._inflight = {}

    def _path(self, conversation_id):
        if not isinstance(conversation_id, str) or not _ID.fullmatch(conversation_id):
            raise ConversationNotFound(_MISSING)
        return self.directory / f"{conversation_id}.jsonl"

    def _read(self, conversation_id):
        path = self._path(conversation_id)
        try:
            header, turns = load_display(path)
        except RecordError:
            raise ConversationNotFound(_MISSING) from None
        return path, header, turns

    def _summary(self, conversation_id, path, header, turns):
        return {
            "id": conversation_id,
            "mode": header["mode"],
            "effort": _effort(header, turns),
            "title": _title(turns),
            "updated_at": round(path.stat().st_mtime, 3),
            "turn_count": len(turns),
            "pending": self._inflight.get(conversation_id),
        }

    def list(self):
        if not self.directory.is_dir():
            return []
        conversations = []
        for path in self.directory.glob("*.jsonl"):
            conversation_id = path.stem
            if not _ID.fullmatch(conversation_id):
                continue
            try:
                header, turns = load_display(path)
                conversations.append(self._summary(conversation_id, path, header, turns))
            except (RecordError, OSError):
                continue
        conversations.sort(key=lambda item: item["updated_at"], reverse=True)
        return conversations

    def create(self, mode, effort):
        if mode not in MODES:
            raise ConversationError("模式必须是 workflow 或 agent。")
        if effort not in EFFORTS:
            raise ConversationError("推理强度必须是 none、low、high 或 max。")
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
        except OSError:
            raise ConversationError("无法创建对话目录。") from None
        while True:
            conversation_id = uuid.uuid4().hex[:12]
            path = self.directory / f"{conversation_id}.jsonl"
            if not path.exists():
                break
        try:
            with append_file(path, mode=mode, reasoning_effort=effort):
                pass
        except RecordError as error:
            raise ConversationError(str(error)) from None
        header, turns = load_display(path)
        return self._summary(conversation_id, path, header, turns)

    def get(self, conversation_id):
        path, header, turns = self._read(conversation_id)
        conversation = self._summary(conversation_id, path, header, turns)
        conversation["turns"] = [turn_view(event, mode=header["mode"]) for event in turns]
        resumable, resume_error = True, None
        if header["mode"] == "agent":
            try:
                load_record(path, reasoning_effort=conversation["effort"], warn=lambda message: None)
            except RecordError as error:
                resumable, resume_error = False, str(error)
        conversation["resumable"] = resumable
        conversation["resume_error"] = resume_error
        return conversation

    def history(self, conversation_id):
        path, header, turns = self._read(conversation_id)
        if header["mode"] != "agent":
            return []
        try:
            source = load_record(path, reasoning_effort=_effort(header, turns), warn=lambda message: None)
        except RecordError as error:
            raise ConversationError(str(error)) from None
        return list(replay_turns(source))

    def begin(self, conversation_id, question):
        self._path(conversation_id)
        with self._lock:
            if self._inflight:
                raise ConversationError("上一轮回答还在生成，请稍候。")
            self._inflight[conversation_id] = {"question": question, "started_at": time.time()}

    def end(self, conversation_id):
        with self._lock:
            self._inflight.pop(conversation_id, None)

    def append(self, conversation_id, mode, effort, event):
        path = self._path(conversation_id)
        try:
            with append_file(path, mode=mode, reasoning_effort=effort) as append:
                append(event)
        except RecordError as error:
            raise ConversationError(str(error)) from None

    def delete(self, conversation_id):
        path = self._path(conversation_id)
        with self._lock:
            if conversation_id in self._inflight:
                raise ConversationError("对话正在生成，暂时无法删除。")
        try:
            path.unlink()
        except FileNotFoundError:
            raise ConversationNotFound(_MISSING) from None
        except OSError:
            raise ConversationError("无法删除对话。") from None


def _effort(header, turns):
    if header.get("effort") in EFFORTS:
        return header["effort"]
    for event in reversed(turns):
        if event.get("reasoning_effort") in EFFORTS:
            return event["reasoning_effort"]
    return "none"


def _title(turns):
    if not turns:
        return "新对话"
    question = " ".join(turns[0]["question"].split())
    if len(question) <= _TITLE_CHARS:
        return question
    return question[:_TITLE_CHARS] + "…"


def turn_view(event, *, mode):
    """Project a recorded turn into the steps the UI renders."""
    queries = event.get("queries") if isinstance(event.get("queries"), list) else []
    messages = event.get("messages")
    if mode == "agent" and isinstance(messages, list) and len(messages) > 1:
        steps = _agent_steps(messages, queries)
    else:
        steps = _request_steps(event.get("requests"), queries)
    return {
        "question": event["question"],
        "status": event["status"],
        "answer": event.get("answer"),
        "error": event.get("error"),
        "steps": steps,
        "usage": _usage(event.get("requests")),
        "replayable": event.get("replayable", True),
    }


def _request_steps(requests, queries):
    """Workflow order: planning request, its queries, then the answer request."""
    steps = []
    for position, request in enumerate(requests if isinstance(requests, list) else []):
        if not isinstance(request, dict):
            continue
        _add_reasoning(steps, request.get("reasoning_content"))
        if position == 0:
            steps.extend(_query_step(query, index) for index, query in enumerate(queries))
    return steps


def _agent_steps(messages, queries):
    """Each assistant message is one request; its tool calls consume the recorded queries."""
    steps, query_index = [], 0
    for message in messages[1:]:
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        _add_reasoning(steps, message.get("reasoning_content"))
        calls = message.get("tool_calls")
        if not isinstance(calls, list):
            continue
        for _ in calls:
            if query_index >= len(queries):
                break
            steps.append(_query_step(queries[query_index], query_index))
            query_index += 1
    for query in queries[query_index:]:
        steps.append(_query_step(query, query_index))
        query_index += 1
    return steps


def _add_reasoning(steps, text):
    if isinstance(text, str) and text:
        steps.append({"kind": "reasoning", "index": _count(steps, "reasoning"), "text": text})


def _count(steps, kind):
    return sum(1 for step in steps if step["kind"] == kind)


def _query_step(query, index):
    if not isinstance(query, dict):
        query = {}
    cypher = query.get("cypher") if isinstance(query.get("cypher"), str) else ""
    parameters = query.get("parameters") if isinstance(query.get("parameters"), dict) else {}
    result = query.get("result") if isinstance(query.get("result"), dict) else {}
    return {
        "kind": "query",
        "index": index,
        "cypher": cypher,
        "parameters": parameters,
        "result": result,
    }


def _usage(requests):
    usage = {}
    for request in requests if isinstance(requests, list) else []:
        if not isinstance(request, dict):
            continue
        for key in ("elapsed_ms", "prompt_tokens", "completion_tokens", "prompt_cache_hit_tokens"):
            value = request.get(key)
            if type(value) in (int, float) and value >= 0:
                usage[key] = usage.get(key, 0) + value
    if "elapsed_ms" in usage:
        usage["elapsed_ms"] = round(usage["elapsed_ms"], 1)
    return usage


class LiveTurn:
    """Translate QA callbacks into ordered step events for the event stream."""

    def __init__(self, emit):
        self._emit = emit
        self._reasoning = 0
        self._queries = 0

    def reasoning(self, text):
        self._emit(("step", {"kind": "reasoning", "index": self._reasoning, "text": text}))
        self._reasoning += 1

    def query(self, cypher, parameters, result):
        self._emit(("step", {"kind": "query", "index": self._queries, "cypher": cypher,
                            "parameters": parameters,
                            "result": {"rows": result["rows"], "truncated": result["truncated"]}}))
        self._queries += 1

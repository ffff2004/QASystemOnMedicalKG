"""Versioned JSONL records; only complete agent turns are replayable."""

import json
import os
from contextlib import contextmanager


class RecordError(Exception):
    """The record could not be read or written."""


_VERSION = 1
TOKEN_FIELDS = ("prompt_tokens", "completion_tokens", "prompt_cache_hit_tokens", "prompt_cache_miss_tokens")


def is_replayable_turn(messages, question, *, thinking):
    """Check the message shape required to send a complete agent turn back to DeepSeek."""
    if not isinstance(messages, list) or len(messages) < 2:
        return False
    try:
        user = messages[0]
        if (set(user) != {"role", "content"} or user["role"] != "user"
                or json.loads(user["content"]) != {"question": question}):
            return False
        remaining = iter(messages[1:])
        end = object()
        for message in remaining:
            if (message["role"] != "assistant"
                    or not set(message) <= {"role", "content", "reasoning_content", "tool_calls"}
                    or (("reasoning_content" in message or thinking)
                        and not isinstance(message.get("reasoning_content"), str))):
                return False
            content = message["content"]
            if "tool_calls" not in message:
                return isinstance(content, str) and next(remaining, end) is end
            calls = message["tool_calls"]
            if (content is not None and not isinstance(content, str)) or not isinstance(calls, list) or not calls:
                return False
            ids = set()
            for call in calls:
                call_id = call["id"]
                function = call["function"]
                reply = next(remaining)
                if (set(call) != {"id", "type", "function"} or call["type"] != "function"
                        or not isinstance(call_id, str) or not call_id or call_id in ids
                        or set(function) != {"name", "arguments"}
                        or not all(isinstance(value, str) for value in function.values())
                        or set(reply) != {"role", "tool_call_id", "content"}
                        or reply["role"] != "tool" or reply["tool_call_id"] != call_id
                        or not isinstance(reply["content"], str)):
                    return False
                ids.add(call_id)
    except (AttributeError, KeyError, TypeError, ValueError, RecursionError, StopIteration):
        return False
    return False


def _reject_constant(value):
    raise ValueError(f"Invalid JSON constant: {value}")


def _valid_request(request):
    if not isinstance(request, dict):
        return False
    elapsed = request.get("elapsed_ms")
    return (type(elapsed) in (int, float) and elapsed >= 0
            and all(type(request[key]) is int and request[key] >= 0 for key in TOKEN_FIELDS if key in request)
            and ("reasoning_content" not in request or isinstance(request["reasoning_content"], str)))


def _valid_query(query):
    if (not isinstance(query, dict) or not isinstance(query.get("cypher"), str)
            or not isinstance(query.get("parameters"), dict) or not isinstance(query.get("result"), dict)):
        return False
    result = query["result"]
    if set(result) == {"error"}:
        return isinstance(result["error"], str)
    return (set(result) == {"rows", "truncated"} and type(result["truncated"]) is bool
            and isinstance(result["rows"], list) and all(isinstance(row, dict) for row in result["rows"]))


def _valid_event(event, *, thinking):
    status = event.get("status")
    requests = event.get("requests")
    queries = event.get("queries")
    question = event.get("question")
    replayable = event.get("replayable", True)
    if (event.get("event") != "turn" or status not in ("completed", "failed", "incomplete")
            or not isinstance(question, str) or not isinstance(event.get("model"), str)
            or event.get("reasoning_effort") not in (("low", "high", "max") if thinking else ("none",))
            or not isinstance(requests, list) or not all(map(_valid_request, requests))
            or not isinstance(queries, list) or not all(map(_valid_query, queries))
            or type(replayable) is not bool
            or any(key in event and not isinstance(event[key], str) for key in ("answer", "error"))):
        return False
    if status == "completed":
        return "answer" in event and is_replayable_turn(event.get("messages"), question,
                                                        thinking=thinking and replayable)
    return ("answer" in event or "error" in event) and (
        "messages" not in event or isinstance(event["messages"], list)
    )


def load_record(path, *, reasoning_effort, warn):
    """Read a resumable agent record without changing it."""
    source = []
    thinking = reasoning_effort != "none"
    try:
        with open(path, "rb") as file:
            for number, line in enumerate(file, 1):
                if not line.endswith(b"\n"):
                    warn(f"已忽略记录文件末尾未写完的第 {number} 行。")
                    break
                try:
                    event = json.loads(line.decode("utf-8"), parse_constant=_reject_constant)
                    # Also reject unpaired surrogates escaped inside otherwise valid JSON.
                    json.dumps(event, ensure_ascii=False, allow_nan=False).encode("utf-8")
                except (ValueError, RecursionError) as error:
                    raise RecordError(f"记录文件第 {number} 行不是有效的 JSON。") from error
                if not isinstance(event, dict):
                    raise RecordError(f"记录文件第 {number} 行不是有效的事件。")
                if number == 1:
                    if (event.get("event") != "header" or type(event.get("version")) is not int
                            or event["version"] != _VERSION):
                        raise RecordError("不支持此记录文件格式或版本。")
                    if event.get("mode") != "agent":
                        raise RecordError("只能恢复 agent 模式的记录。")
                    if type(event.get("thinking")) is not bool or event["thinking"] != thinking:
                        raise RecordError("记录的 thinking 开关与当前 DEEPSEEK_REASONING_EFFORT 不匹配。")
                elif event != {"event": "reset"} and not _valid_event(event, thinking=thinking):
                    raise RecordError(f"记录文件第 {number} 行不是有效的 agent 轮次。")
                source.append(event)
    except OSError as error:
        raise RecordError("无法读取记录文件。") from error
    if not source:
        raise RecordError("记录文件缺少完整的文件头。")
    return source


def replay_turns(source):
    start = next((i + 1 for i in range(len(source) - 1, -1, -1)
                  if source[i]["event"] == "reset"), 1)
    for i in range(start, len(source)):
        event = source[i]
        if event["status"] == "completed" and event.get("replayable", True):
            yield event["messages"]


def _private_open(path, flags):
    return os.open(path, flags, 0o600)


@contextmanager
def record_file(path, *, mode, reasoning_effort, source):
    """Exclusively create a private file, copy the source, then append new events."""
    try:
        file = open(path, "x", encoding="utf-8", opener=_private_open)
    except FileExistsError as error:
        raise RecordError("输出记录文件已存在；请指定新路径。") from error
    except OSError as error:
        raise RecordError("无法创建输出记录文件。") from error

    def append(event):
        try:
            file.write(json.dumps(event, ensure_ascii=False, allow_nan=False, default=str) + "\n")
            file.flush()
        except (OSError, ValueError) as error:
            raise RecordError("无法写入输出记录文件。") from error

    try:
        for event in source or [{"event": "header", "version": _VERSION, "mode": mode,
                                 "thinking": reasoning_effort != "none"}]:
            append(event)
        yield append
    finally:
        try:
            file.close()
        except OSError as error:
            raise RecordError("无法关闭输出记录文件。") from error

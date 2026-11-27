"""Local web demo: a FastAPI transport over the terminal QA."""

import argparse
import json
import os
import queue
import sys
import threading
import traceback
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from openai import OpenAI
from pydantic import BaseModel, field_validator

from cypher_graph import CypherGraph, GraphQueryError
from llm_qa import MAX_QUESTION_CHARS, QA, QAError
from session_record import EFFORTS
from web_conversations import ConversationError, Conversations, LiveTurn, turn_view

_WEB_ROOT = Path(__file__).with_name("web")
_SESSIONS = Path(__file__).with_name("sessions")


class NewConversation(BaseModel):
    mode: Literal["workflow", "agent"] = "workflow"
    effort: Literal["none", "low", "high", "max"] = "none"


class NewTurn(BaseModel):
    question: str

    @field_validator("question")
    @classmethod
    def _usable(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("问题不能为空。")
        if len(value) > MAX_QUESTION_CHARS:
            raise ValueError(f"问题过长，请缩短到 {MAX_QUESTION_CHARS} 个字符以内。")
        return value


def create_app(*, client, graph, sessions_dir):
    conversations = Conversations(sessions_dir)
    app = FastAPI(title="医疗知识图谱问答", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.conversations = conversations
    app.mount("/assets", StaticFiles(directory=_WEB_ROOT), name="assets")

    @app.get("/")
    def index():
        return FileResponse(_WEB_ROOT / "index.html")

    @app.get("/api/config")
    def config():
        effort = os.getenv("DEEPSEEK_REASONING_EFFORT", "none").strip().lower()
        return {"default_effort": effort if effort in EFFORTS else "none"}

    @app.get("/api/conversations")
    def list_conversations():
        return {"conversations": conversations.list()}

    @app.post("/api/conversations", status_code=201)
    def create_conversation(body: NewConversation):
        try:
            return {"conversation": conversations.create(body.mode, body.effort)}
        except ConversationError as error:
            raise HTTPException(error.status, str(error)) from None

    @app.get("/api/conversations/{conversation_id}")
    def read_conversation(conversation_id: str):
        try:
            return {"conversation": conversations.get(conversation_id)}
        except ConversationError as error:
            raise HTTPException(error.status, str(error)) from None

    @app.delete("/api/conversations/{conversation_id}", status_code=204)
    def delete_conversation(conversation_id: str):
        try:
            conversations.delete(conversation_id)
        except ConversationError as error:
            raise HTTPException(error.status, str(error)) from None
        return Response(status_code=204)

    @app.post("/api/conversations/{conversation_id}/turns")
    def create_turn(conversation_id: str, body: NewTurn):
        try:
            conversation = conversations.get(conversation_id)
            if not conversation["resumable"]:
                raise ConversationError(conversation["resume_error"] or "无法继续此对话。")
            history = conversations.history(conversation_id)
            conversations.begin(conversation_id, body.question)
        except ConversationError as error:
            raise HTTPException(error.status, str(error)) from None

        events = queue.Queue()
        ended = []

        def on_record(event):
            ended.append(event)
            try:
                conversations.append(conversation_id, conversation["mode"], conversation["effort"], event)
            except ConversationError as error:
                events.put(("error", {"message": str(error)}))
            events.put(("turn", turn_view(event, mode=conversation["mode"])))

        live = LiveTurn(events.put)
        try:
            qa = QA(client, graph, mode=conversation["mode"], reasoning_effort=conversation["effort"],
                    multi_turn=conversation["mode"] == "agent", history=history,
                    on_query=live.query, on_reasoning=live.reasoning, on_record=on_record)
        except Exception:
            conversations.end(conversation_id)
            raise

        def work():
            try:
                qa.ask(body.question)
            except QAError as error:
                if not ended:
                    events.put(("error", {"message": str(error)}))
            except Exception:
                traceback.print_exc()
                if not ended:
                    events.put(("error", {"message": "问答意外中断，请重试。"}))
            finally:
                events.put(("close", None))
                conversations.end(conversation_id)

        def stream():
            threading.Thread(target=work, daemon=True).start()
            while True:
                kind, payload = events.get()
                if kind == "close":
                    return
                yield f"event: {kind}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    return app


def main(argv=None):
    parser = argparse.ArgumentParser(description="本地 Web 版医疗图谱问答（仅监听 127.0.0.1）")
    parser.add_argument("--port", type=int, default=8000, help="监听端口，默认 8000")
    args = parser.parse_args(argv)

    load_dotenv(Path(__file__).with_name(".env"), override=False)
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        print("请在 .env 或环境变量中配置 DEEPSEEK_API_KEY。", file=sys.stderr)
        return 1
    try:
        graph = CypherGraph()
    except GraphQueryError as error:
        print(f"问答失败：{error}", file=sys.stderr)
        return 1
    try:
        graph.ensure_read_only()
    except GraphQueryError as error:
        graph.close()
        print(f"问答失败：{error}", file=sys.stderr)
        return 1

    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com", timeout=60, max_retries=1)
    app = create_app(client=client, graph=graph, sessions_dir=_SESSIONS)
    import uvicorn

    try:
        uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="info")
    finally:
        client.close()
        graph.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

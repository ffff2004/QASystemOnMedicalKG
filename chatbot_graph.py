#!/usr/bin/env python3
import argparse
import json
import os
from pathlib import Path
import sys

from dotenv import load_dotenv
from openai import OpenAI

from cypher_graph import CypherGraph, GraphQueryError
from llm_qa import QA, QAError


def _trace_query(cypher, parameters, result):
    print(f'[Cypher] {cypher}', file=sys.stderr)
    print(f'[参数] {json.dumps(parameters, ensure_ascii=False)}', file=sys.stderr)
    print(f'[Neo4j] {json.dumps(result["rows"], ensure_ascii=False)}', file=sys.stderr)
    if result['truncated']:
        print('[Neo4j] 结果已截断。', file=sys.stderr)


def _trace_reasoning(text):
    visible = ''.join(char for char in text if char.isprintable() or char == '\n')
    print(f'[DeepSeek 推理] {visible}', file=sys.stderr)


def _interactive(qa, *, multi_turn):
    while True:
        try:
            print('用户：', end='', file=sys.stderr, flush=True)
            question = input().strip()
        except (EOFError, KeyboardInterrupt):
            print(file=sys.stderr)
            return 0
        if not question:
            continue
        if multi_turn and question == '/reset':
            qa.reset()
            print('会话已清空。', file=sys.stderr)
            continue
        try:
            print(qa.ask(question))
        except QAError as error:
            print(f'问答失败：{error}', file=sys.stderr)


def main(argv=None):
    parser = argparse.ArgumentParser(description='基于 Neo4j 医疗知识图谱的 DeepSeek 问答')
    parser.add_argument('--mode', choices=('workflow', 'agent'), default='workflow')
    interaction = parser.add_mutually_exclusive_group()
    interaction.add_argument('--interactive', action='store_true', help='交互问答（默认）')
    interaction.add_argument('--question', help='仅回答一个问题后退出')
    parser.add_argument('--show-cypher', action='store_true', help='在 stderr 展示查询与原始结果行')
    parser.add_argument('--show-reasoning', action='store_true', help='在 stderr 展示 API 返回的推理')
    args = parser.parse_args(argv)
    if args.question is not None and not args.question.strip():
        parser.error('--question 不能为空')

    load_dotenv(Path(__file__).with_name('.env'), override=False)
    api_key = os.getenv('DEEPSEEK_API_KEY', '').strip()
    if not api_key:
        print('请在 .env 或环境变量中配置 DEEPSEEK_API_KEY。', file=sys.stderr)
        return 1
    thinking = os.getenv('DEEPSEEK_THINKING', 'disabled').strip().lower()
    if thinking not in ('enabled', 'disabled'):
        print('DEEPSEEK_THINKING 须为 enabled 或 disabled。', file=sys.stderr)
        return 1
    if args.show_reasoning and thinking == 'disabled':
        print('Thinking 已关闭，没有推理可展示。', file=sys.stderr)

    try:
        graph = CypherGraph()
        try:
            graph.ensure_read_only()
            multi_turn = args.mode == 'agent' and args.question is None
            with OpenAI(api_key=api_key, base_url='https://api.deepseek.com', timeout=60, max_retries=1) as client:
                qa = QA(client, graph, mode=args.mode, thinking=thinking == 'enabled',
                        multi_turn=multi_turn, on_query=_trace_query if args.show_cypher else None,
                        on_reasoning=_trace_reasoning if args.show_reasoning else None)
                if args.question is None:
                    return _interactive(qa, multi_turn=multi_turn)
                print(qa.ask(args.question.strip()))
        finally:
            graph.close()
    except (QAError, GraphQueryError) as error:
        print(f'问答失败：{error}', file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

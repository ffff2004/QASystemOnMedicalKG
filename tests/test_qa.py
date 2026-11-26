import json
import unittest
from collections import deque
from copy import deepcopy
from types import SimpleNamespace

from llm_qa import QA, QAError


CYPHER = "MATCH (d:Disease {name: $name}) RETURN d.name AS name"
QUERY = {"cypher": CYPHER, "parameters": {"name": "示例疾病"}}
RESULT = {"rows": [{"name": "图谱证据"}], "truncated": True}


def completion(content=None, *, calls=None, reasoning=None, finish_reason="stop"):
    message = SimpleNamespace(content=content, tool_calls=calls, reasoning_content=reasoning)
    return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason=finish_reason)])


def plan(*queries):
    return completion(json.dumps({"queries": list(queries)}, ensure_ascii=False))


def tool_call(call_id, query=QUERY):
    function = SimpleNamespace(name="query_graph", arguments=json.dumps(query, ensure_ascii=False))
    return SimpleNamespace(id=call_id, type="function", function=function)


class FakeOpenAI:
    def __init__(self, *responses):
        self.responses = deque(responses)
        self.requests = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **request):
        self.requests.append(deepcopy(request))
        response = self.responses.popleft()
        if isinstance(response, Exception):
            raise response
        return response


class FakeGraph:
    def __init__(self, *results):
        self.calls = []
        self.results = deque(results)

    def query(self, cypher, parameters):
        self.calls.append((cypher, deepcopy(parameters)))
        return self.results.popleft()


def user_text(request):
    return "\n".join(message["content"] for message in request["messages"]
                     if message["role"] == "user")


class WorkflowTests(unittest.TestCase):
    def test_parameterized_plan_supplies_graph_evidence_to_answer(self):
        question = "图谱中有哪些记录？"
        answer = "找到了部分记录，结果可能不完整。"
        client = FakeOpenAI(plan(QUERY), completion(answer))
        graph = FakeGraph(RESULT)
        reported = []
        qa = QA(client, graph, on_query=lambda *details: reported.append(details))

        self.assertEqual(qa.ask(question), answer)

        self.assertEqual(graph.calls, [(CYPHER, {"name": "示例疾病"})])
        self.assertEqual(reported, [(CYPHER, {"name": "示例疾病"}, RESULT)])
        planning, answering = client.requests
        self.assertIn(question, user_text(planning))
        self.assertEqual(planning["response_format"], {"type": "json_object"})
        self.assertEqual(planning["reasoning_effort"], "none")
        self.assertEqual(answering["reasoning_effort"], "none")
        self.assertIn(question, user_text(answering))
        self.assertIn("图谱证据", user_text(answering))
        self.assertRegex(user_text(answering), r'"truncated"\s*:\s*true')

    def test_invalid_plan_does_not_execute_even_a_valid_prefix(self):
        for response in (
            completion(" "),
            completion('{"queries": ['),
            plan(QUERY, {"cypher": CYPHER, "parameters": []}),
        ):
            with self.subTest(content=response.choices[0].message.content):
                client = FakeOpenAI(response)
                graph = FakeGraph()
                qa = QA(client, graph)

                with self.assertRaises(QAError):
                    qa.ask("查图谱")

                self.assertEqual(graph.calls, [])
                self.assertEqual(len(client.requests), 1)

    def test_empty_evidence_does_not_generate_an_unsupported_answer(self):
        for results, response in (([], plan()), ([{"rows": [], "truncated": False}], plan(QUERY))):
            with self.subTest(results=results):
                client = FakeOpenAI(response)
                qa = QA(client, FakeGraph(*results))

                answer = qa.ask("查无记录")

                self.assertIn("图谱证据", answer)
                self.assertEqual(len(client.requests), 1)

    def test_failed_or_incomplete_completions_raise_qaerror(self):
        for response in (
            RuntimeError("offline fake transport error"),
            SimpleNamespace(choices=[]),
            completion(json.dumps({"queries": []}), finish_reason="length"),
        ):
            with self.subTest(response=response):
                qa = QA(FakeOpenAI(response), FakeGraph())
                with self.assertRaises(QAError):
                    qa.ask("查图谱")


class AgentTests(unittest.TestCase):
    def test_agent_returns_tool_results_to_the_exact_calls_with_reasoning(self):
        second = {"cypher": CYPHER, "parameters": {"name": "第二个实体"}}
        second_result = {"rows": [{"name": "另一条证据"}], "truncated": False}
        first_call = tool_call("query_B-381")
        second_call = tool_call("query_A-592", second)
        reasoning = "先做两次查询。\n保留推理原文和空白。 "
        final_reasoning = "按结果作答。"
        client = FakeOpenAI(
            completion(calls=[first_call, second_call], reasoning=reasoning, finish_reason="tool_calls"),
            completion("查询完成。", reasoning=final_reasoning),
        )
        graph = FakeGraph(RESULT, second_result)
        reported_reasoning = []
        qa = QA(client, graph, mode="agent", reasoning_effort="high", on_reasoning=reported_reasoning.append)

        self.assertEqual(qa.ask("查询两个实体"), "查询完成。")

        first_request, continuation = client.requests
        self.assertIn("query_graph", [tool["function"]["name"] for tool in first_request["tools"]])
        self.assertEqual(first_request["reasoning_effort"], "high")
        self.assertEqual(continuation["reasoning_effort"], "high")
        self.assertEqual(graph.calls, [(CYPHER, QUERY["parameters"]), (CYPHER, second["parameters"])])
        self.assertEqual(reported_reasoning, [reasoning, final_reasoning])
        assistant, first_reply, second_reply = continuation["messages"][-3:]
        self.assertEqual(assistant["role"], "assistant")
        self.assertEqual(assistant["reasoning_content"], reasoning)
        self.assertEqual(
            [(call["id"], call["function"]["arguments"]) for call in assistant["tool_calls"]],
            [(call.id, call.function.arguments) for call in (first_call, second_call)],
        )
        for reply, call_id, result in ((first_reply, first_call.id, RESULT),
                                       (second_reply, second_call.id, second_result)):
            self.assertEqual(reply["role"], "tool")
            self.assertEqual(reply["tool_call_id"], call_id)
            self.assertEqual(json.loads(reply["content"]), result)

    def test_agent_executes_at_most_four_queries_across_tool_rounds(self):
        calls = [tool_call(f"call_{n}", {"cypher": CYPHER, "parameters": {"name": str(n)}})
                 for n in range(6)]
        client = FakeOpenAI(
            completion(calls=calls[:2], finish_reason="tool_calls"),
            completion(calls=calls[2:5], finish_reason="tool_calls"),
            completion(calls=calls[5:], finish_reason="tool_calls"),
        )
        graph = FakeGraph(RESULT, RESULT, RESULT, RESULT)
        qa = QA(client, graph, mode="agent")

        self.assertTrue(qa.ask("请依次查询各实体"))

        self.assertEqual(graph.calls, [(CYPHER, {"name": str(n)}) for n in range(4)])
        final_request = client.requests[2]
        self.assertEqual(final_request["tool_choice"], "none")
        replies = {message["tool_call_id"]: json.loads(message["content"])
                   for message in final_request["messages"] if message["role"] == "tool"}
        self.assertEqual(set(replies), {call.id for call in calls[:5]})
        self.assertIn("error", replies[calls[4].id])

    def test_agent_history_is_opt_in_and_reset_clears_it(self):
        first_question = "首次提及的实体"
        first_answer = "第一轮回答"
        tool_reasoning = "查图谱的推理"
        final_reasoning = "作答的推理，保留末尾空白。 "
        for multi_turn in (False, True):
            with self.subTest(multi_turn=multi_turn):
                client = FakeOpenAI(
                    completion(calls=[tool_call("old_call")], reasoning=tool_reasoning, finish_reason="tool_calls"),
                    completion(first_answer, reasoning=final_reasoning),
                    completion("未经查询的回答", reasoning="追问的推理"),
                    completion("仍未经查询的回答"),
                    completion("未经查询的回答"),
                )
                graph = FakeGraph(RESULT)
                qa = QA(client, graph, mode="agent", reasoning_effort="high", multi_turn=multi_turn)

                self.assertEqual(qa.ask(first_question), first_answer)
                refusal = qa.ask("它是什么？")
                self.assertIn("图谱证据", refusal)
                self.assertEqual(graph.calls, [(CYPHER, QUERY["parameters"])])

                follow_up = client.requests[2]["messages"]
                if multi_turn:
                    self.assertEqual(follow_up[:-2], client.requests[1]["messages"])
                    self.assertEqual(follow_up[-2], {
                        "role": "assistant", "content": first_answer, "reasoning_content": final_reasoning,
                    })
                else:
                    self.assertEqual([message["role"] for message in follow_up], ["system", "user"])
                self.assertEqual(json.loads(follow_up[-1]["content"])["question"], "它是什么？")

                qa.ask("再追问一次")
                next_follow_up = client.requests[3]["messages"]
                if multi_turn:
                    self.assertEqual(next_follow_up[:-2], follow_up)
                    self.assertEqual(next_follow_up[-2], {
                        "role": "assistant", "content": refusal, "reasoning_content": "追问的推理",
                    })

                qa.reset()
                qa.ask("重置后提问")

                after_reset = client.requests[4]["messages"]
                self.assertEqual([message["role"] for message in after_reset], ["system", "user"])
                self.assertEqual(json.loads(after_reset[-1]["content"])["question"], "重置后提问")

    def test_agent_drops_whole_old_turns_when_history_grows(self):
        responses = []
        for index in range(8):
            responses.extend([
                completion(calls=[tool_call(f"call_{index}")], finish_reason="tool_calls"),
                completion(f"回答 {index}"),
            ])
        responses.append(completion("未经查询的回答"))
        result = {"rows": [{"name": "药" * 2000}] * 5, "truncated": True}
        client = FakeOpenAI(*responses)
        qa = QA(client, FakeGraph(*([result] * 8)), mode="agent", multi_turn=True)

        for index in range(8):
            self.assertEqual(qa.ask(f"问题 {index}"), f"回答 {index}")
        qa.ask("追问")

        replay = client.requests[-1]["messages"][1:-1]
        retained = len(replay) // 4
        self.assertTrue(0 < retained < 8)
        self.assertEqual([message["role"] for message in replay],
                         ["user", "assistant", "tool", "assistant"] * retained)
        self.assertEqual([json.loads(message["content"])["question"] for message in replay[::4]],
                         [f"问题 {index}" for index in range(8 - retained, 8)])
        for index, call, reply in zip(range(8 - retained, 8), replay[1::4], replay[2::4]):
            self.assertEqual(call["tool_calls"][0]["id"], f"call_{index}")
            self.assertEqual(reply["tool_call_id"], f"call_{index}")


if __name__ == "__main__":
    unittest.main()

from app.adapters.llm.ollama import OllamaProvider
from app.core.chat import ChatMessage, ToolCall, ToolDefinition


def test_ollama_serializes_native_tool_definition_and_messages() -> None:
    tool = ToolDefinition(
        name="calculator",
        description="Calculate a safe arithmetic expression.",
        input_schema={
            "type": "object",
            "properties": {"expression": {"type": "string"}},
            "required": ["expression"],
        },
    )
    assistant_message = ChatMessage(
        role="assistant",
        tool_calls=[ToolCall(name="calculator", arguments={"expression": "2 + 2"})],
    )
    tool_result_message = ChatMessage(
        role="tool",
        tool_name="calculator",
        content='{"ok": true, "result": {"result": 4}}',
    )

    assert OllamaProvider._serialize_tool(tool) == {
        "type": "function",
        "function": {
            "name": "calculator",
            "description": "Calculate a safe arithmetic expression.",
            "parameters": tool.input_schema,
        },
    }
    assert OllamaProvider._serialize_message(assistant_message) == {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "type": "function",
                "function": {"name": "calculator", "arguments": {"expression": "2 + 2"}},
            }
        ],
    }
    assert OllamaProvider._serialize_message(tool_result_message) == {
        "role": "tool",
        "content": '{"ok": true, "result": {"result": 4}}',
        "tool_name": "calculator",
    }


def test_ollama_parses_native_tool_calls_without_a_live_server() -> None:
    calls = OllamaProvider._parse_tool_calls(
        [
            {
                "type": "function",
                "function": {"name": "get_time", "arguments": {}},
            }
        ]
    )

    assert calls == [ToolCall(name="get_time", arguments={})]

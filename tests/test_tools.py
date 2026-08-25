import asyncio

import pytest

from app.core.chat import ToolCall
from app.tools.base import PermissionLevel, Tool, ToolInput, ToolInputValidationError
from app.tools.builtin.calculator import CalculatorTool
from app.tools.builtin.system_info import GetDateTool, GetTimeTool, SystemStatusTool
from app.tools.executor import ToolExecutor
from app.tools.registry import DuplicateToolError, ToolRegistry


def run_async(coroutine):
    return asyncio.run(coroutine)


def test_registry_register_lookup_list_and_unregister() -> None:
    registry = ToolRegistry()
    tool = GetTimeTool()

    registry.register(tool)

    assert registry.get("get_time") is tool
    assert registry.list_tools() == [tool]
    assert registry.list_definitions()[0].name == "get_time"
    assert registry.unregister("get_time") is tool
    assert registry.get("get_time") is None


def test_registry_prevents_duplicate_tool_names() -> None:
    registry = ToolRegistry()
    registry.register(GetTimeTool())

    with pytest.raises(DuplicateToolError):
        registry.register(GetTimeTool())


def test_tool_input_validation_accepts_valid_and_rejects_invalid_input() -> None:
    calculator = CalculatorTool()

    validated = calculator.validate_input({"expression": "2 * (3 + 4)"})

    assert validated.expression == "2 * (3 + 4)"
    with pytest.raises(ToolInputValidationError):
        calculator.validate_input({"expression": "1 + 1", "unexpected": True})


def test_calculator_uses_safe_expression_parser() -> None:
    calculator = CalculatorTool()

    result = run_async(calculator.execute(calculator.validate_input({"expression": "(2 + 3) * 4"})))

    assert result == {"expression": "(2 + 3) * 4", "result": 20}


def test_calculator_rejects_python_execution_syntax() -> None:
    registry = ToolRegistry()
    registry.register(CalculatorTool())
    executor = ToolExecutor(registry, allowed_permissions={PermissionLevel.READ})

    result = run_async(
        executor.execute(ToolCall(name="calculator", arguments={"expression": "__import__('os')"}))
    )

    assert result.success is False
    assert result.error_code == "tool_execution_failed"


def test_read_tools_return_expected_data_shapes() -> None:
    time_result = run_async(GetTimeTool().execute(GetTimeTool().validate_input({})))
    date_result = run_async(GetDateTool().execute(GetDateTool().validate_input({})))
    status_result = run_async(SystemStatusTool().execute(SystemStatusTool().validate_input({})))

    assert "time" in time_result and "timezone" in time_result
    assert "date" in date_result and "timezone" in date_result
    assert 0 <= status_result["cpu_percent"] <= 100
    assert {"memory", "disk"} <= status_result.keys()


class WriteProbeTool(Tool[ToolInput]):
    name = "write_probe"
    description = "Test only; no write is performed."
    permission = PermissionLevel.WRITE
    input_model = ToolInput

    async def execute(self, tool_input: ToolInput) -> dict[str, bool]:
        del tool_input
        return {"executed": True}


class DangerousProbeTool(Tool[ToolInput]):
    name = "dangerous_probe"
    description = "Test only; no dangerous operation is performed."
    permission = PermissionLevel.DANGEROUS
    input_model = ToolInput

    async def execute(self, tool_input: ToolInput) -> dict[str, bool]:
        del tool_input
        return {"executed": True}


def test_permission_executor_allows_read_and_blocks_write_and_dangerous() -> None:
    registry = ToolRegistry()
    registry.register(GetDateTool())
    registry.register(WriteProbeTool())
    registry.register(DangerousProbeTool())
    executor = ToolExecutor(registry, allowed_permissions={PermissionLevel.READ})

    read_result = run_async(executor.execute(ToolCall(name="get_date", arguments={})))
    write_result = run_async(executor.execute(ToolCall(name="write_probe", arguments={})))
    dangerous_result = run_async(executor.execute(ToolCall(name="dangerous_probe", arguments={})))

    assert read_result.success is True
    assert write_result.success is False
    assert write_result.error_code == "permission_denied"
    assert dangerous_result.success is False
    assert dangerous_result.error_code == "permission_denied"

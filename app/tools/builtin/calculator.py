"""`eval` kullanmadan güvenli temel matematik hesaplama tool'u."""

import ast
import math
import operator

from pydantic import Field, field_validator

from app.tools.base import PermissionLevel, Tool, ToolExecutionError, ToolInput


class CalculatorInput(ToolInput):
    """Calculator tool'unun doğrulanmış input'u."""

    expression: str = Field(min_length=1, max_length=200)

    @field_validator("expression")
    @classmethod
    def normalize_expression(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("expression boş olamaz")
        return normalized


class CalculatorTool(Tool[CalculatorInput]):
    """Sadece izinli AST düğümleriyle aritmetik hesaplar."""

    name = "calculator"
    description = "Güvenli temel matematiksel bir ifadeyi hesaplar."
    permission = PermissionLevel.READ
    input_model = CalculatorInput

    async def execute(self, tool_input: CalculatorInput) -> dict[str, object]:
        try:
            result = _SafeExpressionEvaluator.evaluate(tool_input.expression)
        except (ArithmeticError, SyntaxError, ValueError) as exc:
            raise ToolExecutionError(f"İfade hesaplanamadı: {exc}") from exc
        return {"expression": tool_input.expression, "result": result}


class _SafeExpressionEvaluator:
    """Sadece sayısal sabitler ve sınırlı aritmetik operatörleri kabul eder."""

    _binary_operators = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv,
        ast.Mod: operator.mod,
        ast.Pow: operator.pow,
    }
    _unary_operators = {ast.UAdd: operator.pos, ast.USub: operator.neg}

    @classmethod
    def evaluate(cls, expression: str) -> int | float:
        tree = ast.parse(expression, mode="eval")
        result = cls._visit(tree.body)
        if not math.isfinite(float(result)):
            raise ValueError("sonuç sonlu bir sayı olmalı")
        return result

    @classmethod
    def _visit(cls, node: ast.AST) -> int | float:
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
                raise ValueError("yalnızca sayısal sabitlere izin verilir")
            if abs(node.value) > 1_000_000_000_000:
                raise ValueError("sayısal sabit sınırı aşıldı")
            return node.value

        if isinstance(node, ast.UnaryOp) and type(node.op) in cls._unary_operators:
            return cls._unary_operators[type(node.op)](cls._visit(node.operand))

        if isinstance(node, ast.BinOp) and type(node.op) in cls._binary_operators:
            left = cls._visit(node.left)
            right = cls._visit(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 100:
                raise ValueError("üs sınırı aşıldı")
            result = cls._binary_operators[type(node.op)](left, right)
            if abs(result) > 1e100:
                raise ValueError("sonuç boyutu sınırı aşıldı")
            return result

        raise ValueError("izin verilmeyen matematiksel ifade")

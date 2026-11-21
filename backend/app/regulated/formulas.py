"""Formulele și verificările formularelor (`report_forms.structure`).

Sintaxa: `[cod]` — valoarea finală a rândului (după corecțiile manuale),
`{sursă}` — valoarea calculată din contabilitate, numere, `+ - * /`, paranteze,
`max(...)` / `min(...)`, comparații (`<= >= == < > !=`) și `and` / `or`.
Expresia se evaluează pe arborele `ast`, cu noduri permise explicit — nu se
execută cod.
"""

import ast
import re
from collections.abc import Callable
from decimal import ROUND_HALF_UP, Decimal

from app.regulated.errors import ReportError

_REF = re.compile(r"\[([0-9A-Za-z_.]+)\]|\{([0-9A-Za-z_.:]+)\}")


class FormulaError(ReportError):
    """Formulă greșită în structura formularului."""


def parse(expr: str) -> tuple[ast.Expression, dict[str, tuple[str, str]]]:
    """Înlocuiește trimiterile cu nume Python; întoarce arborele și harta numelor."""
    names: dict[str, tuple[str, str]] = {}

    def repl(m: re.Match) -> str:
        name = f"_r{len(names)}"
        names[name] = ("cell", m.group(1)) if m.group(1) is not None else ("source", m.group(2))
        return name

    try:
        tree = ast.parse(_REF.sub(repl, expr), mode="eval")
    except SyntaxError as exc:
        raise FormulaError(f"Formulă greșită: {expr}") from exc
    return tree, names


def references(expr: str) -> list[tuple[str, str]]:
    """Trimiterile expresiei: („cell”, cod) sau („source”, nume)."""
    return list(parse(expr)[1].values())


_BIN = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b if b else Decimal(0),
}
_CMP = {
    ast.Lt: lambda a, b: a < b,
    ast.LtE: lambda a, b: a <= b,
    ast.Gt: lambda a, b: a > b,
    ast.GtE: lambda a, b: a >= b,
    ast.Eq: lambda a, b: a == b,
    ast.NotEq: lambda a, b: a != b,
}
_FUNCS = {"max": max, "min": min}


def evaluate(expr: str, cell: Callable[[str], Decimal], source: Callable[[str], Decimal]):
    tree, names = parse(expr)

    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, int | float) and not isinstance(node.value, bool):
            return Decimal(str(node.value))
        if isinstance(node, ast.Name):
            if node.id not in names:
                raise FormulaError(f"Nume necunoscut în formulă: {expr}")
            kind, key = names[node.id]
            return cell(key) if kind == "cell" else source(key)
        if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
            return _BIN[type(node.op)](ev(node.left), ev(node.right))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return -ev(node.operand)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCS and not node.keywords:
            return _FUNCS[node.func.id](*(ev(a) for a in node.args))
        if isinstance(node, ast.Compare):
            left = ev(node.left)
            for op, comparator in zip(node.ops, node.comparators, strict=True):
                right = ev(comparator)
                if type(op) not in _CMP or not _CMP[type(op)](left, right):
                    return False
                left = right
            return True
        if isinstance(node, ast.BoolOp):
            values = [ev(v) for v in node.values]
            return all(values) if isinstance(node.op, ast.And) else any(values)
        raise FormulaError(f"Construcție nepermisă în formulă: {expr}")

    return ev(tree)


def quantize(value: Decimal, decimals: int) -> Decimal:
    return Decimal(value).quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP)

"""SQL safety validator — single SELECT (or UNION/INTERSECT/EXCEPT of SELECTs), no DML/DDL/file IO."""

from __future__ import annotations

import sqlglot
from sqlglot import expressions as exp

_ALLOWED_ROOTS: tuple[type[exp.Expression], ...] = (
    exp.Select,
    exp.Union,
    exp.Intersect,
    exp.Except,
)

# Constructs that can nest inside a Select tree. Statement-level DML/DDL
# (Insert/Update/Delete/Create/Drop/Alter/Set/Use/...) is already filtered by _ALLOWED_ROOTS.
_FORBIDDEN_NODES: tuple[type[exp.Expression], ...] = (
    exp.Command,  # sqlglot fallback for unmodeled statements: TRUNCATE / GRANT / CALL / etc.
    exp.Into,     # SELECT ... INTO OUTFILE / DUMPFILE / @var
)

# DoS or filesystem-access functions. The read-only DB role would block them
# anyway, but failing here keeps the error message useful for the retry prompt.
_BLACKLISTED_FUNCS: frozenset[str] = frozenset(
    {"LOAD_FILE", "SLEEP", "BENCHMARK", "GET_LOCK", "RELEASE_LOCK"}
)


class SqlValidationError(ValueError):
    """Raised when SQL fails the read-only safety check."""


def validate_select_only(sql: str) -> exp.Expression:
    """Parse `sql` (MySQL dialect), verify a single read-only SELECT, return the AST."""
    try:
        statements = sqlglot.parse(sql, dialect="mysql")
    except sqlglot.errors.ParseError as e:
        raise SqlValidationError(f"could not parse SQL: {e}") from e

    statements = [s for s in statements if s is not None]
    if not statements:
        raise SqlValidationError("empty SQL")
    if len(statements) > 1:
        raise SqlValidationError(
            f"expected one statement, got {len(statements)} — statement chaining is not allowed"
        )

    tree = statements[0]
    if not isinstance(tree, _ALLOWED_ROOTS):
        raise SqlValidationError(
            f"only SELECT (and UNION/INTERSECT/EXCEPT of SELECTs) is allowed; got {type(tree).__name__}"
        )

    forbidden = next(iter(tree.find_all(*_FORBIDDEN_NODES)), None)
    if forbidden is not None:
        raise SqlValidationError(f"forbidden node in SQL: {type(forbidden).__name__}")

    for func in tree.find_all(exp.Func):
        name = (func.name or "").upper()
        if name in _BLACKLISTED_FUNCS:
            raise SqlValidationError(f"forbidden function: {name}()")

    return tree

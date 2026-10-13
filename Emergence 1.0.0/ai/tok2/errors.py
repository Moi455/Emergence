"""errors.py - the one exception of tok-2: every refusal of an input is a TokenError (never ValueError/TypeError)."""


class TokenError(ValueError):
    """A record, a value, a key or a proposition the tokenizer refuses: it never silently drops or invents
    information. (It stays a ValueError subclass for the callers that already catch ValueError.)"""


def short(x, n: int = 60) -> str:
    """A value for an error message: never raises (a giant integer cannot be printed in Python 3.11+), never long."""
    try:
        if isinstance(x, int) and not isinstance(x, bool) and x.bit_length() > 64:
            return f"<int of {x.bit_length()} bits>"
        s = repr(x)
    except (ValueError, RecursionError, TypeError):
        return f"<{type(x).__name__}>"
    s = ascii(s)
    return s if len(s) <= n else s[:n - 3] + "..."


def listing(items, n: int = 200) -> str:
    """A list of names for an error message, at most ~n characters."""
    out, size = [], 0
    for it in items:
        s = short(it, 40)
        if size + len(s) > n:
            out.append(f"... ({len(items) - len(out)} more)")
            break
        out.append(s)
        size += len(s) + 2
    return "[" + ", ".join(out) + "]"


def clip(s: str, n: int = 200) -> str:
    return s if len(s) <= n else s[:n - 3] + "..."

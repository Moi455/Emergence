"""errors.py - the one exception of tok-2: every refusal of an input is a TokenError (never ValueError/TypeError)."""


class TokenError(ValueError):
    """A record, a value, a key or a proposition the tokenizer refuses: it never silently drops or invents
    information. (It stays a ValueError subclass for the callers that already catch ValueError.)"""

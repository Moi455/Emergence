"""tok-2: the input tokenizer of the NPC Transformer, generated from catalogue/generated/model_interface.json.

Python oracle of the C++ tokenizer (D31). See tokenizer.py for the contract, layout.py and codecs.py for the
columns, registry.py for the stable identifiers.
"""
from .errors import TokenError
from .interface import InputVocabulary, ModelInterface
from .layout import Layout
from .tokenizer import DecisionContext, Encoded, Record, Tokenizer

__all__ = ["DecisionContext", "Encoded", "InputVocabulary", "Layout", "ModelInterface", "Record", "Registry",
           "TokenError", "Tokenizer"]


def __getattr__(name):                         # Registry is loaded on demand (see tokenizer.py)
    if name == "Registry":
        from .registry import Registry
        return Registry
    raise AttributeError(name)

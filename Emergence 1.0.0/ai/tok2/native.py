"""native.py - the C++ tokenizer (engine/social/tokenizer) through its C interface: ONE tokenizer, in the game and here.

    from tok2.native import NativeTokenizer
    nt = NativeTokenizer()                       # finds libemergence_tok2_capi.so (EM_TOK2_LIB, or a build folder)
    enc = nt.encode_json(ctx.dumps(tokenizer))   # arrays identical to tokenizer.encode(ctx), bit for bit
    enc.digest == oracle_encoded.digest()        # parity check

Memory rule (docs/14 6.2): the library owns its handle; Python owns every buffer it passes and every array it gets
back (a copy). One NativeTokenizer per thread. Nothing here is imported by tok2/__init__: the oracle never depends on
the C++ build; this module is loaded on demand and raises NativeUnavailable when the library is not built.
"""
from __future__ import annotations

import ctypes as C
import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
LIB_NAME = "libemergence_tok2_capi.so"
ARRAYS = ("type_id", "num", "known", "cat", "cat_known", "ptr", "ptr_known", "prop_sym", "prop_arity", "prop_depth",
          "prop_slot", "prop_num")
_DTYPES = {"type_id": np.uint8, "num": np.float16, "known": np.uint8, "cat": np.int16, "cat_known": np.uint8,
           "ptr": np.uint8, "ptr_known": np.uint8, "prop_sym": np.int16, "prop_arity": np.uint8, "prop_depth": np.uint8,
           "prop_slot": np.uint8, "prop_num": np.float16}


class NativeUnavailable(RuntimeError):
    """The C++ library is not built (cmake -S engine -B build && cmake --build build --target emergence_tok2_capi)."""


class NativeRefusal(ValueError):
    """The C++ tokenizer refused the context (the oracle's TokenError)."""


class _Info(C.Structure):
    _fields_ = [("n", C.c_uint32), ("digest", C.c_uint32), ("n_ghosts", C.c_uint32), ("reserved", C.c_uint32)]


@dataclass
class NativeEncoded:
    """The arrays of one decision (copies owned by Python), same names, dtypes and shapes as tok2.Encoded."""
    n: int
    digest: int
    n_ghosts: int
    arrays: dict

    def __getattr__(self, name):
        try:
            return self.__dict__["arrays"][name]
        except KeyError:
            raise AttributeError(name) from None


@dataclass
class NativeMask:
    gesture_ok: np.ndarray      # [40] bool
    refs: np.ndarray            # [40, 3, 129] bool: nobody, then token slots 1..128
    flags: np.ndarray           # [40, 3] uint8: bit0 used, bit1 optional, bit2 direction, bit3 form
    gestures: list


def find_library() -> Path | None:
    env = os.environ.get("EM_TOK2_LIB")
    if env:
        return Path(env) if Path(env).exists() else None
    for d in sorted((ROOT / "build").glob("**/" + LIB_NAME)) if (ROOT / "build").exists() else []:
        return d
    for d in sorted(ROOT.glob("build*/**/" + LIB_NAME)):
        return d
    return None


class NativeTokenizer:
    def __init__(self, lib_path: str | os.PathLike | None = None):
        path = Path(lib_path) if lib_path else find_library()
        if path is None or not Path(path).exists():
            raise NativeUnavailable(f"{LIB_NAME} not found: build the target emergence_tok2_capi or set EM_TOK2_LIB")
        self._lib = lib = C.CDLL(str(path))
        lib.em_tok2_create.restype = C.c_void_p
        lib.em_tok2_destroy.argtypes = [C.c_void_p]
        for f in ("em_tok2_layout_fingerprint", "em_tok2_interface_fingerprint", "em_tok2_vocab_fingerprint"):
            getattr(lib, f).restype = C.c_uint64
        lib.em_tok2_buffer_size.restype = C.c_size_t
        lib.em_tok2_array_name.restype = C.c_char_p
        lib.em_tok2_array_offset.restype = C.c_size_t
        lib.em_tok2_array_bytes.restype = C.c_size_t
        lib.em_tok2_gesture_name.restype = C.c_char_p
        lib.em_tok2_to_half.restype = C.c_uint16
        lib.em_tok2_to_half.argtypes = [C.c_double]
        lib.em_tok2_crc32.restype = C.c_uint32
        lib.em_tok2_crc32.argtypes = [C.c_uint32, C.c_char_p, C.c_size_t]
        lib.em_tok2_encode_json.argtypes = [C.c_void_p, C.c_char_p, C.c_size_t, C.c_void_p, C.POINTER(_Info), C.c_char_p, C.c_size_t]
        lib.em_tok2_encode_batch.argtypes = [C.c_void_p, C.POINTER(C.c_char_p), C.POINTER(C.c_size_t), C.c_int, C.c_void_p,
                                             C.POINTER(_Info), C.POINTER(C.c_int)]
        lib.em_tok2_feasibility.argtypes = [C.c_void_p, C.c_void_p, C.c_uint32, C.c_void_p, C.c_void_p, C.c_void_p]
        self._check_fresh()
        self._h = lib.em_tok2_create()
        if not self._h:
            raise NativeUnavailable("em_tok2_create failed")
        self.size = int(lib.em_tok2_buffer_size())
        assert lib.em_tok2_array_count() == len(ARRAYS)
        rows = lib.em_tok2_array_rows()
        self._plan = []
        for i, name in enumerate(ARRAYS):
            assert lib.em_tok2_array_name(i).decode() == name
            cols = lib.em_tok2_array_cols(i)
            self._plan.append((name, int(lib.em_tok2_array_offset(i)), int(lib.em_tok2_array_bytes(i)),
                               (rows, cols) if cols else (rows,)))
        self.gestures = [lib.em_tok2_gesture_name(g).decode() for g in range(lib.em_tok2_gesture_count())]

    def _check_fresh(self) -> None:
        """A stale library must never load silently: its layout/interface/vocabulary fingerprints must be the oracle's."""
        from .tokenizer import Tokenizer      # lazy: the oracle is only needed for this check
        py = Tokenizer()
        got = (int(self._lib.em_tok2_layout_fingerprint()), int(self._lib.em_tok2_interface_fingerprint()),
               int(self._lib.em_tok2_vocab_fingerprint()))
        want = (py.layout.fingerprint, py.interface.fingerprint, py.vocab.fingerprint)
        if got != want:
            raise NativeUnavailable("the C++ library is stale (layout/interface/vocabulary fingerprints "
                                    f"{[f'{x:016x}' for x in got]} != oracle {[f'{x:016x}' for x in want]}): "
                                    "run python3 engine/social/tokenizer/gen_tok2.py and rebuild emergence_tok2_capi")

    def __del__(self):
        h, lib = getattr(self, "_h", None), getattr(self, "_lib", None)
        if h and lib:
            lib.em_tok2_destroy(h)
            self._h = None

    # ---- identity
    @property
    def layout_fingerprint(self) -> int:
        return int(self._lib.em_tok2_layout_fingerprint())

    @property
    def interface_fingerprint(self) -> int:
        return int(self._lib.em_tok2_interface_fingerprint())

    @property
    def vocab_fingerprint(self) -> int:
        return int(self._lib.em_tok2_vocab_fingerprint())

    def header(self) -> dict:
        return {"schema": "tok2-context-1", "interface": f"{self.interface_fingerprint:016x}",
                "layout": f"{self.layout_fingerprint:016x}"}

    # ---- encoding
    def _arrays(self, buf: np.ndarray) -> dict:
        out = {}
        for name, off, nbytes, shape in self._plan:
            raw = buf[off:off + nbytes]
            out[name] = raw.view(_DTYPES[name]).reshape(shape).copy()
        return out

    def encode_json(self, text: str | bytes) -> NativeEncoded:
        data = text.encode("utf-8") if isinstance(text, str) else text
        buf = np.zeros(self.size, np.uint8)
        info, err = _Info(), C.create_string_buffer(512)
        rc = self._lib.em_tok2_encode_json(self._h, data, len(data), buf.ctypes.data, C.byref(info), err, len(err))
        if rc != 0:
            raise NativeRefusal(err.value.decode("utf-8", "replace"))
        return NativeEncoded(info.n, info.digest, info.n_ghosts, self._arrays(buf))

    def encode(self, ctx, tokenizer) -> NativeEncoded:
        """A tok2.DecisionContext through its canonical JSON (the text both tokenizers read)."""
        return self.encode_json(ctx.dumps(tokenizer))

    def encode_batch(self, texts: list) -> tuple[list, np.ndarray]:
        """(NativeEncoded or None per text, status array). One call into C++ for the whole batch."""
        n = len(texts)
        datas = [t.encode("utf-8") if isinstance(t, str) else t for t in texts]
        arr = (C.c_char_p * n)(*datas)
        lens = (C.c_size_t * n)(*[len(d) for d in datas])
        bufs = np.zeros(n * self.size, np.uint8)
        infos, status = (_Info * n)(), (C.c_int * n)()
        self._lib.em_tok2_encode_batch(self._h, arr, lens, n, bufs.ctypes.data, infos, status)
        out = []
        for i in range(n):
            out.append(None if status[i] else NativeEncoded(
                infos[i].n, infos[i].digest, infos[i].n_ghosts, self._arrays(bufs[i * self.size:(i + 1) * self.size])))
        return out, np.array(list(status), np.int32)

    # ---- feasibility mask (read from the arrays only)
    def feasibility(self, enc: NativeEncoded) -> NativeMask:
        buf = np.zeros(self.size, np.uint8)
        for name, off, nbytes, shape in self._plan:
            buf[off:off + nbytes] = np.ascontiguousarray(enc.arrays[name]).view(np.uint8).reshape(-1)
        g = np.zeros(40, np.uint8)
        refs = np.zeros((40, 3, 129), np.uint8)
        flags = np.zeros((40, 3), np.uint8)
        rc = self._lib.em_tok2_feasibility(self._h, buf.ctypes.data, enc.n, g.ctypes.data, refs.ctypes.data, flags.ctypes.data)
        if rc:
            raise NativeRefusal("feasibility failed")
        return NativeMask(g.astype(bool), refs.astype(bool), flags, list(self.gestures))

    # ---- helpers exposed for the parity tests
    def to_half_bits(self, x: float) -> int:
        return int(self._lib.em_tok2_to_half(float(x)))

    def crc32(self, data: bytes, crc: int = 0) -> int:
        return int(self._lib.em_tok2_crc32(crc, data, len(data)))

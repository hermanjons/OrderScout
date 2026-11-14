"""Read small planning metadata without loading tensors or tokenizer arrays."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import struct


_FIXED = {0: "B", 1: "b", 2: "H", 3: "h", 4: "I", 5: "i", 6: "f", 7: "?", 10: "Q", 11: "q", 12: "d"}
_SUFFIXES = (".block_count", ".context_length", ".embedding_length", ".attention.head_count",
             ".attention.head_count_kv", ".attention.key_length", ".attention.value_length")


class InvalidGGUF(ValueError):
    pass


def read_gguf_metadata(path: str | Path) -> dict:
    source = Path(path)
    stat = source.stat()
    return dict(_read_cached(str(source.resolve()), stat.st_size, stat.st_mtime_ns))


@lru_cache(maxsize=64)
def _read_cached(path: str, size: int, mtime: int) -> dict:
    del mtime
    with open(path, "rb") as stream:
        def read(fmt):
            length = struct.calcsize("<" + fmt)
            raw = stream.read(length)
            if len(raw) != length:
                raise InvalidGGUF("GGUF üst bilgisi eksik.")
            return struct.unpack("<" + fmt, raw)[0]

        def skip(length):
            if length < 0 or stream.tell() + length > size:
                raise InvalidGGUF("GGUF alan uzunluğu geçersiz.")
            stream.seek(length, 1)

        def string(keep=False):
            length = read("Q")
            if keep:
                if length > 1024 * 1024 or stream.tell() + length > size:
                    raise InvalidGGUF("GGUF metin alanı geçersiz.")
                return stream.read(length).decode("utf-8", errors="replace")
            skip(length)

        def value(kind, keep=False, depth=0):
            if depth > 2:
                raise InvalidGGUF("GGUF dizi derinliği geçersiz.")
            if kind in _FIXED:
                return read(_FIXED[kind])
            if kind == 8:
                return string(keep)
            if kind == 9:
                element, count = read("I"), read("Q")
                if count > 10_000_000:
                    raise InvalidGGUF("GGUF dizi uzunluğu geçersiz.")
                if element in _FIXED:
                    skip(count * struct.calcsize("<" + _FIXED[element]))
                else:
                    for _ in range(count):
                        value(element, False, depth + 1)
                return None
            raise InvalidGGUF("Desteklenmeyen GGUF alan türü.")

        if stream.read(4) != b"GGUF" or read("I") not in (2, 3):
            raise InvalidGGUF("GGUF v2/v3 dosyası gerekli.")
        tensor_count, count = read("Q"), read("Q")
        if count > 100_000 or tensor_count > 1_000_000:
            raise InvalidGGUF("GGUF üst bilgisi sınırı aşıldı.")
        result = {"file_bytes": size, "tensor_count": tensor_count}
        for _ in range(count):
            key = string(True)
            keep = key in {"general.architecture", "general.name", "general.file_type", "split.count"} or key.endswith(_SUFFIXES)
            item = value(read("I"), keep)
            if keep and isinstance(item, (str, int, float, bool)):
                result[key] = item
            if stream.tell() > 128 * 1024 * 1024:
                raise InvalidGGUF("GGUF üst bilgisi çok büyük.")
        return result

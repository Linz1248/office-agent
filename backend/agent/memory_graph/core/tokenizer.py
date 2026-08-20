"""token 计数：复用 Comet 的 tiktoken cl100k_base 口径，保证与原系统分块一致。"""
import tiktoken

_encoder = tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    return len(_encoder.encode(text or ""))


__all__ = ["count_tokens"]

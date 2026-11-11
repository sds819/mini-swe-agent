"""Secrets do not belong in the log of a session, nor in the context of the model.

The output of a tool is written to the event log and sent to the provider. A
secret that is read from a file or printed by a command ends up in both.
"""

import re

PLACEHOLDER = "[redacted]"

PATTERNS: list[tuple[re.Pattern, str]] = [
    (
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL),
        "[redacted private key]",
    ),
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}"), PLACEHOLDER),
    (re.compile(r"\b(?:ghp|gho|ghs|ghu|ghr)_[A-Za-z0-9]{16,}"), PLACEHOLDER),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"), PLACEHOLDER),
    (re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), PLACEHOLDER),
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}"), PLACEHOLDER),
    (re.compile(r"\bAIza[A-Za-z0-9_\-]{35}\b"), PLACEHOLDER),
    (re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}"), PLACEHOLDER),
    (re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9_\-\.=]{8,}"), rf"\1{PLACEHOLDER}"),
    (
        re.compile(
            r"(?i)\b((?:password|passwd|pwd|secret|api[_\-]?key|access[_\-]?token|refresh[_\-]?token"
            r"|auth[_\-]?token|client[_\-]?secret|private[_\-]?key)\s*[:=]\s*[\"']?)([^\s\"',;}]{4,})"
        ),
        rf"\1{PLACEHOLDER}",
    ),
]
"""The secrets that are known by their shape, and the name of the key that holds them."""


def redact(text: str) -> str:
    """The text without the secrets in it."""
    if not text:
        return text
    for pattern, replacement in PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def has_secret(text: str) -> bool:
    """True when the text holds something that looks like a secret."""
    return bool(text) and redact(text) != text


__all__ = ["PATTERNS", "PLACEHOLDER", "has_secret", "redact"]

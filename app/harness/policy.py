from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatchcase
from typing import Literal

PolicyAction = Literal["read", "write", "delete", "execute"]
PolicyEffect = Literal["allow", "deny"]


@dataclass(frozen=True, slots=True)
class PermissionRule:
    effect: PolicyEffect
    action: PolicyAction
    pattern: str

    @classmethod
    def allow(cls, action: PolicyAction, pattern: str) -> "PermissionRule":
        return cls("allow", action, pattern)

    @classmethod
    def deny(cls, action: PolicyAction, pattern: str) -> "PermissionRule":
        return cls("deny", action, pattern)

    def matches(self, action: PolicyAction, path: str) -> bool:
        return self.action == action and fnmatchcase(path, self.pattern)


class PermissionPolicy:
    """First-match permission policy with deny-by-default behavior."""

    def __init__(self, rules: list[PermissionRule]) -> None:
        self._rules = tuple(rules)

    @classmethod
    def default(cls) -> "PermissionPolicy":
        return cls(
            [
                PermissionRule.allow("read", "/"),
                PermissionRule.allow("read", "/workspace"),
                PermissionRule.allow("read", "/workspace/**"),
                PermissionRule.allow("write", "/workspace"),
                PermissionRule.allow("write", "/workspace/**"),
                PermissionRule.allow("delete", "/workspace"),
                PermissionRule.allow("delete", "/workspace/**"),
                PermissionRule.allow("execute", "/workspace"),
                PermissionRule.allow("execute", "/workspace/**"),
                PermissionRule.allow("read", "/memory"),
                PermissionRule.allow("read", "/memory/**"),
                PermissionRule.allow("write", "/memory"),
                PermissionRule.allow("write", "/memory/**"),
                PermissionRule.allow("delete", "/memory"),
                PermissionRule.allow("delete", "/memory/**"),
                PermissionRule.allow("read", "/outputs"),
                PermissionRule.allow("read", "/outputs/**"),
                PermissionRule.allow("write", "/outputs"),
                PermissionRule.allow("write", "/outputs/**"),
                PermissionRule.allow("delete", "/outputs"),
                PermissionRule.allow("delete", "/outputs/**"),
                PermissionRule.allow("read", "/vault"),
                PermissionRule.allow("read", "/vault/**"),
                PermissionRule.allow("write", "/vault"),
                PermissionRule.allow("write", "/vault/**"),
                PermissionRule.allow("delete", "/vault"),
                PermissionRule.allow("delete", "/vault/**"),
                PermissionRule.allow("read", "/repos"),
                PermissionRule.allow("read", "/repos/**"),
            ]
        )

    def allows(self, action: PolicyAction, path: str) -> bool:
        for rule in self._rules:
            if rule.matches(action, path):
                return rule.effect == "allow"
        return False

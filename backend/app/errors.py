from __future__ import annotations


class DomainError(Exception):
    """A rule was broken (wrong state, not your ride, ...). Mapped to an HTTP error by the API layer."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def not_found(what: str) -> DomainError:
    return DomainError(404, f"{what} not found")


def conflict(message: str) -> DomainError:
    return DomainError(409, message)


def forbidden(message: str = "not allowed") -> DomainError:
    return DomainError(403, message)

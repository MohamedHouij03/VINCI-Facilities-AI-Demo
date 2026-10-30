"""Service-level exceptions, mapped to HTTP responses in backend.main."""

from __future__ import annotations


class ServiceError(Exception):
    status_code = 400

    def __init__(self, message: str, **details: object) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class NotFoundError(ServiceError):
    status_code = 404


class ConflictError(ServiceError):
    status_code = 409


class InvalidInputError(ServiceError):
    status_code = 422

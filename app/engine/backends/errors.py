class FilesystemBackendError(Exception):
    """Base error for filesystem backend operations."""


class InvalidPathError(FilesystemBackendError):
    """Raised when a path is invalid for the backend policy."""


class PathEscapeError(InvalidPathError):
    """Raised when a path escapes the configured backend base path."""


class PathNotFoundError(FilesystemBackendError):
    """Raised when a required path does not exist."""


class OperationFailedError(FilesystemBackendError):
    """Raised when a filesystem operation fails."""

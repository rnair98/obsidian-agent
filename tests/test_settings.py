from app.core.settings import FilesystemConfig
from app.engine.backends.factory import FilesystemBackendType


def test_filesystem_config_defaults_to_supported_backend_type() -> None:
    config = FilesystemConfig()

    assert config.backend_type == FilesystemBackendType.IN_PROCESS

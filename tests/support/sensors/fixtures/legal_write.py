from pathlib import Path


class Vault:
    backend: object


def legal(backend: object, vault: Vault) -> None:
    backend.write_text("a.md", "x", encoding="utf-8")
    vault.backend.write_text("b.md", "y")
    Path("a.md").open().read()

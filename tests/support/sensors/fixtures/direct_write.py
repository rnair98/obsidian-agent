from pathlib import Path


def bad() -> None:
    open("note.md", "w").write("x")
    Path("note.md").write_text("x")
    Path("note.md").write_bytes(b"x")

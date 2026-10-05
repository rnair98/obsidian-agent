"""Offline characterization of actual OpenResearch functions; no app or providers.

Run: python3 docs/research/openresearch-audit-checks.py [OpenResearch checkout]
Requires rustc. Extracts two complete source definitions between reviewed markers,
compiles them with stdlib-only scaffolding, and uses temporary synthetic logs.
These assertions characterize flaws, so an upstream fix should fail this check.
"""
from pathlib import Path
import subprocess
import sys
import tempfile

root = Path(sys.argv[1] if len(sys.argv) > 1 else "OpenResearch")
source = (root / "src/jobs/localbox.rs").read_text()
start = source.index("pub fn stream_logs(")
end = source.index("/// TERM the process group", start)
stream = source[start:end]
start = source.index("fn exit_code_state(")
end = source.index("/// Job state in the shared stage vocabulary", start)
status = source[start:end]
program = r'''
use std::path::Path;
type Result<T> = std::io::Result<T>;
struct JobState { stage: String, message: Option<String> }
'''+stream+status+r'''
fn main() {
    let arg = std::env::args().nth(1).unwrap();
    let dir = Path::new(&arg);
    let log = dir.join("log");
    let mut lines = Vec::new();
    std::fs::write(&log, "metric=0.").unwrap();
    let cursor = stream_logs(dir, 0, &mut |s| lines.push(s.to_string())).unwrap();
    std::fs::write(&log, "metric=0.95\nnext=1\n").unwrap();
    stream_logs(dir, cursor, &mut |s| lines.push(s.to_string())).unwrap();
    assert_eq!(lines, vec!["metric=0.", "next=1"]);
    println!("CONFIRMED: line cursor loses appended suffix of a partial metric line.");
    std::fs::write(&log, b"metric=0.95\n\xff\n").unwrap();
    let mut count = 0;
    assert_eq!(stream_logs(dir, 0, &mut |_| count += 1).unwrap(), 0);
    assert_eq!(count, 0);
    println!("CONFIRMED: invalid UTF-8 anywhere suppresses even valid log lines without an error.");
    std::fs::write(dir.join("exit_code"), "0\n").unwrap();
    let result = exit_code_state(dir).unwrap();
    assert_eq!(result.stage, "COMPLETED");
    assert!(result.message.is_none());
    println!("CONFIRMED: successful process exit needs no result artifact or valid metric (execution status only).");
}
'''
with tempfile.TemporaryDirectory(prefix="openresearch-audit-") as directory:
    tmp = Path(directory)
    code = tmp / "check.rs"
    binary = tmp / "check"
    code.write_text(program)
    subprocess.run(["rustc", "--edition=2021", str(code), "-o", str(binary)], check=True)
    subprocess.run([str(binary), str(tmp)], check=True)

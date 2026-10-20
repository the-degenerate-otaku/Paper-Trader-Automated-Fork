from __future__ import annotations

import hashlib
import io
import json
import re
import subprocess
from pathlib import Path

BASELINE = "3c48168bc78e7c34b0c8247543349b02ee5aefd2"


def git(*args: str, content: bytes | None = None) -> bytes:
    return subprocess.run(["git", *args], input=content, capture_output=True, check=True).stdout


def scan() -> int:
    rules = {
        "credential": re.compile(
            rb"gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|"
            rb"AKIA[0-9A-Z]{16}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
        ),
        "personal_path": re.compile(rb"(?:[A-Za-z]:[/\\]Users[/\\]|/home/|/Users/)[\w.-]+"),
        "email": re.compile(rb"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}"),
    }
    baseline = set(git("rev-list", "--objects", BASELINE).decode().splitlines())
    baseline_ids = {line.split(" ", 1)[0] for line in baseline}
    objects = git("rev-list", "--objects", "--all").decode().splitlines()
    stream = io.BytesIO(
        git("cat-file", "--batch", content="\n".join(x.split(" ")[0] for x in objects).encode())
    )
    candidates = []
    baseline_hashes = set()
    for entry in objects:
        header = stream.readline().decode().split()
        content = stream.read(int(header[2]))
        stream.read(1)
        if header[1] != "blob":
            continue
        inherited = header[0] in baseline_ids
        if inherited:
            baseline_hashes.add(hashlib.sha256(content).digest())
        candidates.append((f"history:{entry}", content, inherited))
    for name in (
        git("ls-files", "--cached", "--others", "--exclude-standard", "-z").decode().split("\0")
    ):
        if name and Path(name).is_file():
            content = Path(name).read_bytes()
            candidates.append(
                (f"working:{name}", content, hashlib.sha256(content).digest() in baseline_hashes)
            )
    findings = []
    inherited_findings: dict[str, int] = {}
    for name, content, inherited in candidates:
        for rule, pattern in rules.items():
            matches = pattern.findall(content)
            if rule == "email":
                matches = [m for m in matches if not m.endswith(b"@users.noreply.github.com")]
            if not matches:
                continue
            if inherited and rule != "credential":
                inherited_findings[rule] = inherited_findings.get(rule, 0) + len(matches)
            else:
                findings.append({"location": name, "kind": rule, "count": len(matches)})
    print(
        json.dumps(
            {
                "file_versions_scanned": len(candidates),
                "public_upstream_baseline_findings": inherited_findings,
                "blocking_findings": findings,
            },
            indent=2,
        )
    )
    return int(bool(findings))


if __name__ == "__main__":
    raise SystemExit(scan())

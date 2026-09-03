from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


class SyncTexError(RuntimeError):
    """Raised when a SyncTeX query cannot be completed."""


@dataclass(frozen=True)
class PdfPosition:
    page: int
    x: float
    y: float
    h: float
    v: float
    width: float
    height: float


@dataclass(frozen=True)
class SourcePosition:
    path: Path
    line: int
    column: int


def _records(output: str) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("SyncTeX result"):
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        if key in {"Output", "Input"} and current and key in current:
            records.append(current)
            current = {}
        current[key] = value
    if current:
        records.append(current)
    return records


def _run(args: list[str], cwd: Path) -> str:
    try:
        result = subprocess.run(
            args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SyncTexError(f"Unable to run SyncTeX: {exc}") from exc
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "query failed"
        raise SyncTexError(detail)
    return result.stdout


def forward(
    *, source: Path, line: int, column: int, pdf: Path, cwd: Path
) -> PdfPosition:
    output = _run(
        [
            "synctex",
            "view",
            "-i",
            f"{line}:{column}:{source}",
            "-o",
            str(pdf),
        ],
        cwd,
    )
    for record in _records(output):
        if "Page" not in record:
            continue
        try:
            return PdfPosition(
                page=int(record["Page"]),
                x=float(record.get("x", record.get("h", "0"))),
                y=float(record.get("y", record.get("v", "0"))),
                h=float(record.get("h", record.get("x", "0"))),
                v=float(record.get("v", record.get("y", "0"))),
                width=float(record.get("W", "0")),
                height=float(record.get("H", "0")),
            )
        except (KeyError, ValueError) as exc:
            raise SyncTexError("SyncTeX returned an invalid forward result") from exc
    raise SyncTexError("No location in the PDF corresponds to this source position")


def inverse(*, pdf: Path, page: int, x: float, y: float, cwd: Path) -> SourcePosition:
    output = _run(
        ["synctex", "edit", "-o", f"{page}:{x}:{y}:{pdf}"],
        cwd,
    )
    for record in _records(output):
        if "Input" not in record or "Line" not in record:
            continue
        try:
            raw_path = Path(record["Input"])
            path = raw_path if raw_path.is_absolute() else cwd / raw_path
            return SourcePosition(
                path=path.resolve(),
                line=max(1, int(record["Line"])),
                column=max(0, int(record.get("Column", "0"))),
            )
        except ValueError as exc:
            raise SyncTexError("SyncTeX returned an invalid inverse result") from exc
    raise SyncTexError("No source location corresponds to this point in the PDF")

"""
progress.py — Pipeline progress tracker for the brainrot video generator.

Two outputs, always in sync:
  1. TTY  — colored, human-readable stage/step lines written to stdout
  2. JSON — output/<job>.status.json updated atomically after every transition
             so external tools (cat, watch, jq, scripts) can poll it any time

Usage:
    from progress import Progress

    p = Progress("episode1", total_steps=6, output_dir="output")
    p.stage("PARSING", "episode1.md")
    p.stage("ALIGNING", detail="3 audio files", step=1, step_total=3)
    p.step(2, 3, label="stewie_001.mp3")
    p.stage("EXPORTING", "output/episode1.mp4")
    p.done("output/episode1.mp4")

Check from another terminal:
    cat output/episode1.status.json
    watch -n1 cat output/episode1.status.json
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


# ── ANSI color helpers ────────────────────────────────────────────────────────

_ANSI = {
    "reset":  "\033[0m",
    "bold":   "\033[1m",
    "dim":    "\033[2m",
    "cyan":   "\033[36m",
    "green":  "\033[32m",
    "yellow": "\033[33m",
    "red":    "\033[31m",
    "white":  "\033[97m",
    "gray":   "\033[90m",
}

# Disable colors when not writing to a real TTY (e.g. piped to a file)
_COLOR = sys.stdout.isatty()


def _c(text: str, *codes: str) -> str:
    """Wrap text in ANSI escape codes if stdout is a TTY."""
    if not _COLOR:
        return text
    prefix = "".join(_ANSI[c] for c in codes)
    return f"{prefix}{text}{_ANSI['reset']}"


# ── Stage metadata ────────────────────────────────────────────────────────────

# Ordered pipeline stages — used to derive percent complete
PIPELINE_STAGES = [
    "PARSING",
    "VALIDATING",
    "GENERATING",
    "ALIGNING",
    "BACKGROUND",
    "COMPOSITING",
    "EXPORTING",
    "DONE",
]

_STAGE_ICONS = {
    "PARSING":      "📄",
    "VALIDATING":   "🔍",
    "GENERATING":   "🔊",
    "ALIGNING":     "🎙 ",
    "BACKGROUND":   "🎮",
    "COMPOSITING":  "🎬",
    "EXPORTING":    "📦",
    "DONE":         "✅",
    "ERROR":        "❌",
}


# ── Progress class ────────────────────────────────────────────────────────────

class Progress:
    """Tracks and broadcasts pipeline progress to the TTY and a status file.

    Args:
        job:         Short job identifier used in the status filename
                     (e.g. "episode1" → output/episode1.status.json).
        output_dir:  Directory where the status JSON is written.
    """

    def __init__(self, job: str, output_dir: str = "output") -> None:
        self.job = job
        self._output_dir = Path(output_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._status_path = self._output_dir / f"{job}.status.json"

        self._started_at: float = time.monotonic()
        self._started_wall: str = _now_iso()

        # Current state
        self._stage: str = "STARTING"
        self._stage_detail: str = ""
        self._step: int = 0
        self._step_total: int = 0
        self._step_label: str = ""

        self._write_status()

    # ── Public API ────────────────────────────────────────────────────────────

    def stage(
        self,
        name: str,
        detail: str = "",
        *,
        step: int = 0,
        step_total: int = 0,
    ) -> None:
        """Announce the start of a new pipeline stage.

        Prints a header line to the TTY and updates the status file.

        Args:
            name:       Stage name (one of PIPELINE_STAGES or "ERROR").
            detail:     Optional human-readable detail string.
            step:       Current sub-step within this stage (0 = not applicable).
            step_total: Total sub-steps in this stage.
        """
        self._stage = name.upper()
        self._stage_detail = detail
        self._step = step
        self._step_total = step_total
        self._step_label = ""

        icon = _STAGE_ICONS.get(self._stage, "▶ ")
        percent = self._percent()
        bar = _progress_bar(percent)

        line = (
            f"\n{icon}  "
            f"{_c(self._stage, 'bold', 'cyan')}  "
            f"{_c(detail, 'white') if detail else ''}"
            f"  {bar}  {_c(str(percent) + '%', 'bold')}"
            f"  {_c('(elapsed ' + self._elapsed() + ')', 'gray')}"
        )
        _print(line)

        self._write_status()

    def step(self, current: int, total: int, label: str = "") -> None:
        """Update the sub-step counter within the current stage.

        Prints a compact progress line and updates the status file.

        Args:
            current: 1-based current step number.
            total:   Total number of steps.
            label:   Short description of this step.
        """
        self._step = current
        self._step_total = total
        self._step_label = label

        frac = f"{current}/{total}"
        bar = _progress_bar(int(current / total * 100), width=20)
        _print(
            f"   {_c('├─', 'gray')} "
            f"{_c(frac, 'yellow')} {bar}  "
            f"{_c(label, 'dim')}"
        )
        self._write_status()

    def info(self, message: str) -> None:
        """Print an informational line without changing stage/step state.

        Args:
            message: Free-form message string.
        """
        _print(f"   {_c('│ ', 'gray')}{_c(message, 'dim')}")
        # No status file update — info lines are transient

    def warn(self, message: str) -> None:
        """Print a warning line.

        Args:
            message: Warning message string.
        """
        _print(f"   {_c('⚠ ', 'yellow')}{_c(message, 'yellow')}")

    def done(self, output_path: str = "") -> None:
        """Mark the job as successfully completed.

        Args:
            output_path: Path to the finished output file.
        """
        elapsed = self._elapsed()
        self._stage = "DONE"
        self._stage_detail = output_path
        self._step = 0
        self._step_total = 0

        _print(
            f"\n{_STAGE_ICONS['DONE']}  "
            f"{_c('DONE', 'bold', 'green')}  "
            f"{_c(output_path, 'white')}  "
            f"{_c('in ' + elapsed, 'gray')}\n"
        )
        self._write_status(finished=True)

    def error(self, message: str) -> None:
        """Mark the job as failed.

        Args:
            message: Error description.
        """
        self._stage = "ERROR"
        self._stage_detail = message
        _print(
            f"\n{_STAGE_ICONS['ERROR']}  "
            f"{_c('ERROR', 'bold', 'red')}  "
            f"{_c(message, 'red')}\n"
        )
        self._write_status(finished=True)

    # ── Status file ───────────────────────────────────────────────────────────

    def _write_status(self, finished: bool = False) -> None:
        """Atomically write current state to the status JSON file.

        Uses a temp-file + rename so readers never see a partial write.
        """
        payload = {
            "job":          self.job,
            "stage":        self._stage,
            "stage_detail": self._stage_detail,
            "step":         self._step,
            "step_total":   self._step_total,
            "step_label":   self._step_label,
            "percent":      self._percent(),
            "elapsed_s":    round(time.monotonic() - self._started_at, 1),
            "started_at":   self._started_wall,
            "updated_at":   _now_iso(),
            "status_file":  str(self._status_path),
            "finished":     finished,
        }

        tmp = self._status_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(self._status_path)  # atomic on POSIX

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _percent(self) -> int:
        """Estimate overall completion percentage based on current stage."""
        try:
            stage_i = PIPELINE_STAGES.index(self._stage)
        except ValueError:
            stage_i = 0

        # Base percent from stage position
        base = int(stage_i / len(PIPELINE_STAGES) * 100)

        # Add fractional progress within stage if sub-steps are tracked
        if self._step_total > 0:
            stage_span = int(1 / len(PIPELINE_STAGES) * 100)
            base += int(self._step / self._step_total * stage_span)

        return min(base, 99 if self._stage != "DONE" else 100)

    def _elapsed(self) -> str:
        """Return elapsed time as a human-readable string (e.g. '1m 23s')."""
        secs = int(time.monotonic() - self._started_at)
        if secs < 60:
            return f"{secs}s"
        return f"{secs // 60}m {secs % 60}s"


# ── Module-level helpers ──────────────────────────────────────────────────────

def _progress_bar(percent: int, width: int = 24) -> str:
    """Render a compact ASCII progress bar.

    Args:
        percent: 0–100 completion value.
        width:   Total bar character width (excluding brackets).

    Returns:
        A string like  [████████░░░░░░░░]  63%
    """
    filled = int(width * percent / 100)
    bar = "█" * filled + "░" * (width - filled)
    return _c(f"[{bar}]", "gray")


def _print(msg: str) -> None:
    """Flush-print a message to stdout."""
    print(msg, flush=True)


def _now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── CLI: print current status file ───────────────────────────────────────────

if __name__ == "__main__":
    """Quick status viewer: python progress.py output/episode1.status.json"""
    import sys

    path = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if path is None or not path.exists():
        # Auto-discover the most recently modified status file
        found = sorted(Path("output").glob("*.status.json"), key=os.path.getmtime)
        if not found:
            print("No status files found in output/")
            sys.exit(1)
        path = found[-1]

    data = json.loads(path.read_text())
    bar = _progress_bar(data["percent"])
    print(
        f"\n  Job     : {data['job']}\n"
        f"  Stage   : {data['stage']}  {data.get('stage_detail','')}\n"
        f"  Step    : {data['step']}/{data['step_total']}  {data.get('step_label','')}\n"
        f"  Progress: {bar}  {data['percent']}%\n"
        f"  Elapsed : {data['elapsed_s']}s\n"
        f"  Updated : {data['updated_at']}\n"
        f"  File    : {data['status_file']}\n"
    )

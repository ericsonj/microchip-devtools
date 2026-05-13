#!/usr/bin/env python3
"""
microchip_devtools.mcc.mcc_refresh — Force full MCC regeneration of driver files.

GUI-assisted: MPLAB X is launched automatically; the operator opens MCC and
clicks "Generate Code", then confirms by pressing Enter here.

Workflow (default)
------------------
1. Preflight  – verify MCC project structure and MPLAB X installation.
2. Backup     – copy generated dir to build/backups/{timestamp}/ for rollback.
3. Clean      – delete generated output tree + MCC hash-tracking flags.
4. Launch     – open project in MPLAB X (unless --skip-launch).
5. Wait       – prompt operator to confirm MCC generation is complete.
6. Merge      – launch meld to review old vs new files (unless --skip-merge).
7. Validate   – run check-peripheral (Bug 1 + Bug 3 guards).
8. Report     – print git diff stat for the generated directory.

Usage
-----
    mcc-refresh [--root PATH] [--project-name NAME] [options]

    --root PATH           Project root (default: $VOLTU_PROJECT_ROOT or cwd)
    --project-name NAME   Project name (default: $VOLTU_PROJECT_NAME or folder name)
    --dry-run             Preview only
    --force               Skip backup + skip merge tool
    --skip-launch         IDE already open
    --skip-merge          Backup but no merge review
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from rich.console import Console

from microchip_devtools._project import project_name as _env_project_name
from microchip_devtools._project import project_root as _env_project_root

_DEFAULT_MERGE_TOOL = "meld"
_console = Console(stderr=True)


def _resolve_mplab_ide() -> Path:
    val = os.environ.get("MPLAB_IDE")
    if not val:
        _console.print(
            "[bold red]Error:[/bold red] [yellow]MPLAB_IDE[/yellow] environment variable is not set.\n"
            "Define it before running this command. Example:\n\n"
            "  [cyan]export MPLAB_IDE=/opt/microchip/mplabx/v6.25/mplab_platform/bin/mplab_ide[/cyan]"
        )
        sys.exit(1)
    return Path(val)


def log(msg: str) -> None:
    print(f"[mcc-refresh] {msg}", flush=True)


def _count_files(path: Path) -> int:
    return sum(1 for _ in path.rglob("*") if _.is_file()) if path.exists() else 0


def _build_paths(root: Path, name: str) -> dict[str, Path]:
    return {
        "generated_dir": root / "firmware/src/config/default",
        "flags_dir": root / f"firmware/{name}.X/.generated_files/flags/default",
        "mcc_project": root / f"firmware/{name}.X",
        "mcc_config": root / f"firmware/{name}.X/{name}_default/mcc-config.mc4",
        "success_manifest": root
        / "firmware/src/config/default/harmony-manifest-success.yml",
        "log_dir": root / "build/logs",
        "backup_dir": root / "build/backups",
    }


def preflight(args: argparse.Namespace, paths: dict[str, Path], root: Path) -> None:
    merge_tool = os.environ.get("MCC_MERGE_TOOL", _DEFAULT_MERGE_TOOL)
    errors: list[str] = []

    if not args.skip_launch:
        mplab_ide = _resolve_mplab_ide()
    else:
        mplab_ide = None

    if not paths["generated_dir"].is_dir():
        errors.append(
            f"Generated output directory not found: {paths['generated_dir'].relative_to(root)}"
        )

    if not paths["mcc_config"].exists():
        errors.append(f"MCC config not found: {paths['mcc_config'].relative_to(root)}")

    if not args.skip_launch and mplab_ide is not None and not mplab_ide.exists():
        errors.append(
            f"MPLAB X IDE not found: {mplab_ide}\n"
            "  Set MPLAB_IDE env var or use --skip-launch if IDE is already open."
        )

    if not args.force and not args.skip_merge and shutil.which(merge_tool) is None:
        errors.append(
            f"Merge tool not found: {merge_tool}\n"
            f"  Install {merge_tool} or use --skip-merge.\n"
            f"  Set MCC_MERGE_TOOL env var to use a different tool."
        )

    if errors:
        for e in errors:
            log(f"ERROR: {e}")
        sys.exit(1)

    log("Preflight OK")


def backup(dry_run: bool, paths: dict[str, Path], root: Path) -> Optional[Path]:
    if dry_run:
        log("[dry-run] Would backup generated files to build/backups/{timestamp}/")
        return None

    paths["backup_dir"].mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    backup_path = paths["backup_dir"] / f"generated_{ts}"

    if paths["generated_dir"].exists():
        log(f"Backing up generated files to: {backup_path.relative_to(root)}")
        shutil.copytree(paths["generated_dir"], backup_path, dirs_exist_ok=False)
        log(f"Backup complete: {_count_files(backup_path)} files")
        return backup_path

    log("Generated directory does not exist; skipping backup")
    return None


def clean(dry_run: bool, paths: dict[str, Path], root: Path) -> None:
    tasks = [
        (paths["generated_dir"], "generated source tree"),
        (paths["flags_dir"], "MCC hash-tracking flags"),
    ]

    for path, label in tasks:
        count = _count_files(path)
        if not path.exists():
            log(f"Skip (already absent): {label}")
            continue
        if dry_run:
            log(
                f"[dry-run] Would delete {count:>4} files — {label}: {path.relative_to(root)}"
            )
        else:
            log(f"Deleting {count:>4} files — {label}: {path.relative_to(root)}")
            shutil.rmtree(path)

    if not dry_run:
        log("Clean complete")


def launch_mplab(dry_run: bool, paths: dict[str, Path], root: Path) -> Optional[subprocess.Popen]:  # type: ignore[type-arg]
    mplab_ide = _resolve_mplab_ide()
    cmd = [str(mplab_ide), "--open", str(paths["mcc_project"]), "--nosplash"]

    if dry_run:
        log(f"[dry-run] Would launch: {' '.join(cmd)}")
        return None

    log(f"Launching MPLAB X (project: {paths['mcc_project'].relative_to(root)})")
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    log(f"MPLAB X launched (PID {proc.pid})")
    return proc


def wait_for_user(dry_run: bool, paths: dict[str, Path], root: Path) -> None:
    if dry_run:
        log("[dry-run] Would wait for operator to click Generate Code in MCC")
        return

    print()
    print("=" * 62)
    print("  ACTION REQUIRED IN MPLAB X")
    print()
    print("  1. Wait for MPLAB X to finish loading the project.")
    print("  2. In the toolbar, click  Tools → MCC  (or press Ctrl+Shift+M).")
    print("  3. In the MCC panel, click  Generate  (the blue Generate button).")
    print("  4. Wait until the progress bar disappears and no errors appear.")
    print()
    print("  Then press Enter here to continue.")
    print("=" * 62)
    print()

    try:
        input("  Press Enter after MCC generation completes > ")
    except KeyboardInterrupt:
        print()
        log("Aborted by user")
        sys.exit(1)

    c_files = (
        list(paths["generated_dir"].rglob("*.c"))
        if paths["generated_dir"].exists()
        else []
    )
    if not c_files:
        log("ERROR: Generated directory is empty or missing after generation.")
        log(f"  Expected sources at: {paths['generated_dir'].relative_to(root)}")
        sys.exit(1)

    if not paths["success_manifest"].exists():
        log(
            f"WARNING: Success manifest not found: {paths['success_manifest'].relative_to(root)}"
        )
        log("  Generation may have completed partially. Continuing to validation.")

    total = _count_files(paths["generated_dir"])
    log(f"Generated directory restored — {total} files")


def merge_review(
    backup_path: Optional[Path], dry_run: bool, paths: dict[str, Path]
) -> None:
    merge_tool = os.environ.get("MCC_MERGE_TOOL", _DEFAULT_MERGE_TOOL)

    if dry_run or backup_path is None:
        if dry_run:
            log(
                f"[dry-run] Would launch {merge_tool} to compare old vs new generated files"
            )
        return

    if not backup_path.exists() or not paths["generated_dir"].exists():
        log("Cannot review: backup or generated directory missing")
        return

    log(f"Launching {merge_tool} to review changes...")
    print()
    print("=" * 62)
    print(f"  Opening {merge_tool} for visual diff/merge review")
    print(f"  Left:  {backup_path.name} (old)")
    print(f"  Right: current generated files")
    print("=" * 62)
    print()

    try:
        subprocess.run(
            [merge_tool, str(backup_path), str(paths["generated_dir"])], check=False
        )
    except (FileNotFoundError, Exception) as e:
        log(f"WARNING: Failed to launch merge tool: {e}")

    log("Merge review complete")


def validate(dry_run: bool, root: Path, name: str) -> None:
    if dry_run:
        log("[dry-run] Would run: check-peripheral")
        return

    log("Running peripheral config validation...")
    result = subprocess.run(
        ["check-peripheral", "--root", str(root), "--project-name", name],
        cwd=root,
    )
    if result.returncode != 0:
        log("VALIDATION FAILED — generated files have configuration mismatches.")
        sys.exit(1)

    log("Validation passed")


def report_diff(dry_run: bool, paths: dict[str, Path], root: Path) -> None:
    if dry_run:
        return

    result = subprocess.run(
        ["git", "diff", "--stat", str(paths["generated_dir"].relative_to(root))],
        cwd=root,
        capture_output=True,
        text=True,
    )
    if result.stdout.strip():
        log("Git diff summary for generated files:")
        print(result.stdout)
    else:
        log("No unstaged changes in generated files (git diff clean)")


def write_log(dry_run: bool, paths: dict[str, Path], success: bool) -> None:
    if dry_run:
        return

    paths["log_dir"].mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    log_path = paths["log_dir"] / f"mcc_refresh_{ts}.log"
    status = "SUCCESS" if success else "FAILED"
    log_path.write_text(f"mcc_refresh {ts} {status}\n")
    log(f"Run log: {log_path.relative_to(paths['log_dir'].parent.parent)}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Force full MCC regeneration of driver files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Project root (default: $VOLTU_PROJECT_ROOT or cwd)",
    )
    parser.add_argument(
        "--project-name",
        default=None,
        help="Project name (default: $VOLTU_PROJECT_NAME or folder name)",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-launch", action="store_true")
    parser.add_argument("--skip-merge", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    root = args.root or _env_project_root()
    name = args.project_name or _env_project_name()
    paths = _build_paths(root, name)

    if args.dry_run:
        log("DRY RUN — no files will be modified")

    preflight(args, paths, root)

    if args.force:
        log("Force mode: skipping backup and merge review")
        backup_path = None
    else:
        backup_path = backup(args.dry_run, paths, root)

    clean(args.dry_run, paths, root)

    if not args.skip_launch:
        launch_mplab(args.dry_run, paths, root)
    else:
        log("Skipping MPLAB X launch (--skip-launch)")

    wait_for_user(args.dry_run, paths, root)

    if not args.force and not args.skip_merge:
        merge_review(backup_path, args.dry_run, paths)

    validate(args.dry_run, root, name)
    report_diff(args.dry_run, paths, root)
    write_log(args.dry_run, paths, success=True)
    log("Done.")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Release automation script for AN-DETECT-ZIP-AGM

Automates the release process: version bump, changelog, build, and git operations.
"""

import argparse
import subprocess
import sys
from pathlib import Path
from datetime import datetime
from version import __version__, get_version_info


class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    END = '\033[0m'
    BOLD = '\033[1m'


def print_header(msg):
    print(f"\n{Colors.BOLD}{Colors.BLUE}{'='*60}")
    print(f"  {msg}")
    print(f"{'='*60}{Colors.END}\n")


def print_success(msg):
    print(f"{Colors.GREEN}✓ {msg}{Colors.END}")


def print_error(msg):
    print(f"{Colors.RED}✗ {msg}{Colors.END}")


def print_info(msg):
    print(f"{Colors.BLUE}ℹ {msg}{Colors.END}")


def print_warning(msg):
    print(f"{Colors.YELLOW}⚠ {msg}{Colors.END}")


def run_command(cmd, description):
    """Run a shell command and return success status."""
    try:
        print_info(f"Running: {' '.join(cmd) if isinstance(cmd, list) else cmd}")
        subprocess.check_call(cmd, shell=isinstance(cmd, str))
        print_success(description)
        return True
    except subprocess.CalledProcessError as e:
        print_error(f"{description} (exit code: {e.returncode})")
        return False


def check_git_available():
    """Check if git is available."""
    try:
        subprocess.check_call(["git", "--version"], 
                            stdout=subprocess.DEVNULL, 
                            stderr=subprocess.DEVNULL)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def check_git_status():
    """Check if there are uncommitted changes."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True
        )
        return len(result.stdout.strip()) == 0
    except:
        return None


def create_release(version_type="patch", skip_build=False, skip_git=False):
    """Create a release with version bump, changelog, and git operations."""
    
    print_header(f"AN-DETECT-ZIP-AGM Release Process - {version_type.upper()}")
    print_info(f"Current version: {__version__}")
    
    # Step 1: Bump version
    print_header("Step 1: Bumping Version")
    if not run_command(
        [sys.executable, "version_manager.py", f"--{version_type}"],
        f"Version bumped ({version_type})"
    ):
        print_error("Failed to bump version")
        return False
    
    # Step 2: Check if build.py exists and optionally build
    if not skip_build:
        print_header("Step 2: Building Executable")
        if Path("build.py").exists():
            if run_command(
                [sys.executable, "build.py"],
                "Build completed successfully"
            ):
                print_success("Executable ready in dist/")
            else:
                print_warning("Build failed, but continuing with release")
        else:
            print_warning("build.py not found, skipping build")
    else:
        print_info("Build skipped (--skip-build)")
    
    # Step 3: Git operations
    if not skip_git:
        print_header("Step 3: Git Operations")
        
        if not check_git_available():
            print_warning("Git is not available, skipping git operations")
            return True
        
        # Check for uncommitted changes
        git_clean = check_git_status()
        if git_clean is False:
            print_warning("There are uncommitted changes in git")
            if input("Continue anyway? (y/n): ").lower() != 'y':
                print_error("Release cancelled")
                return False
        
        # Add files
        if not run_command(
            ["git", "add", "version.py"],
            "Added version.py to git"
        ):
            return False
        
        # Commit
        commit_msg = f"Release v{__version__}"
        if not run_command(
            ["git", "commit", "-m", commit_msg],
            f"Committed with message: {commit_msg}"
        ):
            print_warning("Git commit failed (repository may have no changes)")
        
        # Tag
        tag = f"v{__version__}"
        if not run_command(
            ["git", "tag", "-a", tag, "-m", f"Release version {__version__}"],
            f"Created git tag: {tag}"
        ):
            return False
        
        # Optional: push
        if input("Push to remote? (y/n): ").lower() == 'y':
            if not run_command(
                ["git", "push", "origin", "main"],
                "Pushed main branch"
            ):
                print_warning("Push failed")
            
            if not run_command(
                ["git", "push", "origin", "--tags"],
                "Pushed tags"
            ):
                print_warning("Failed to push tags")
    else:
        print_info("Git operations skipped (--skip-git)")
    
    return True


def dry_run(version_type="patch"):
    """Show what would happen without making changes."""
    print_header(f"DRY RUN: {version_type.upper()} Release")
    
    from version import VERSION_MAJOR, VERSION_MINOR, VERSION_PATCH
    
    if version_type == "patch":
        new_version = f"{VERSION_MAJOR}.{VERSION_MINOR}.{VERSION_PATCH + 1}"
    elif version_type == "minor":
        new_version = f"{VERSION_MAJOR}.{VERSION_MINOR + 1}.0"
    elif version_type == "major":
        new_version = f"{VERSION_MAJOR + 1}.0.0"
    else:
        new_version = f"{VERSION_MAJOR}.{VERSION_MINOR}.{VERSION_PATCH}"
    
    print_info(f"Current version: {__version__}")
    print_info(f"New version: {new_version}")
    print_info(f"Release date: {datetime.now().strftime('%Y-%m-%d')}")
    print_info(f"Git tag: v{new_version}")
    print("\nChanges that would be made:")
    print("  - version.py: Version updated")
    print("  - dist/: New executable built")
    print("  - Git: Commit and tag created")
    print("\nTo proceed with actual release, remove --dry-run flag")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Release automation for AN-DETECT-ZIP-AGM",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python release.py patch                  # Release patch version
  python release.py minor --skip-build     # Release minor without building
  python release.py major --dry-run        # Preview major release
  python release.py patch --skip-git       # Release without git operations
        """
    )
    
    parser.add_argument(
        "version",
        nargs="?",
        default="patch",
        choices=["patch", "minor", "major"],
        help="Version bump type (default: patch)"
    )
    
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would happen without making changes"
    )
    
    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="Skip building executable"
    )
    
    parser.add_argument(
        "--skip-git",
        action="store_true",
        help="Skip git operations (commit, tag, push)"
    )
    
    args = parser.parse_args()
    
    if args.dry_run:
        dry_run(args.version)
        return
    
    if not create_release(args.version, args.skip_build, args.skip_git):
        sys.exit(1)
    
    print_header("Release Complete! 🎉")
    info = get_version_info()
    print(f"Version: {info['version']}")
    print(f"Status: {info['status']}")
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("\nYou can now:")
    print("  1. Test the new executable in dist/")
    print("  2. Upload to distribution channels")
    print("  3. Announce the new release")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nRelease cancelled by user")
        sys.exit(1)
    except Exception as e:
        print_error(f"Unexpected error: {e}")
        sys.exit(1)

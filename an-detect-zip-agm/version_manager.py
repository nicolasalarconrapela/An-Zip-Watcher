#!/usr/bin/env python3
"""
Version management utility for AN-DETECT-ZIP-AGM

This script helps manage application versions, update changelogs, and maintain version consistency.
"""

import argparse
import sys
from pathlib import Path
from datetime import datetime
from version import (
    __version__,
    VERSION_MAJOR,
    VERSION_MINOR,
    VERSION_PATCH,
    __status__,
    get_version_info,
)


def update_version_file(major: int, minor: int, patch: int, status: str = None) -> bool:
    """Update version.py with new version numbers."""
    version_file = Path("version.py")
    
    try:
        content = version_file.read_text()
        
        # Update version string
        old_version_line = f'__version__ = "{__version__}"'
        new_version = f"{major}.{minor}.{patch}"
        new_version_line = f'__version__ = "{new_version}"'
        content = content.replace(old_version_line, new_version_line)
        
        # Update version parts
        content = content.replace(
            f"VERSION_MAJOR = {VERSION_MAJOR}",
            f"VERSION_MAJOR = {major}"
        )
        content = content.replace(
            f"VERSION_MINOR = {VERSION_MINOR}",
            f"VERSION_MINOR = {minor}"
        )
        content = content.replace(
            f"VERSION_PATCH = {VERSION_PATCH}",
            f"VERSION_PATCH = {patch}"
        )
        
        # Update status if provided
        if status:
            content = content.replace(
                f'__status__ = "{__status__}"',
                f'__status__ = "{status}"'
            )
        
        version_file.write_text(content)
        print(f"✓ Updated version.py to {new_version}")
        return True
    except Exception as e:
        print(f"✗ Error updating version.py: {e}")
        return False


def add_changelog_entry(version: str, changes: str) -> bool:
    """Add entry to CHANGELOG.md."""
    changelog_file = Path("CHANGELOG.md")
    
    try:
        content = changelog_file.read_text()
        
        # Create new entry
        date = datetime.now().strftime("%Y-%m-%d")
        new_entry = f"## [{version}] - {date}\n\n{changes}\n\n"
        
        # Insert after the first section (after the header)
        lines = content.split("\n")
        insert_pos = 0
        for i, line in enumerate(lines):
            if line.startswith("## ["):
                insert_pos = i
                break
        
        lines.insert(insert_pos, new_entry)
        changelog_file.write_text("\n".join(lines))
        print(f"✓ Added changelog entry for version {version}")
        return True
    except Exception as e:
        print(f"✗ Error updating CHANGELOG.md: {e}")
        return False


def show_version() -> None:
    """Display current version information."""
    info = get_version_info()
    print("\n" + "=" * 50)
    print(f"  {info['title']}")
    print("=" * 50)
    print(f"Version:     {info['version']}")
    print(f"Status:      {info['status']}")
    print(f"Author:      {info['author']}")
    print(f"Description: {info['description']}")
    print(f"License:     {info['license']}")
    print("=" * 50 + "\n")


def bump_patch() -> None:
    """Bump patch version (X.Y.Z -> X.Y.Z+1)."""
    new_patch = VERSION_PATCH + 1
    if update_version_file(VERSION_MAJOR, VERSION_MINOR, new_patch):
        print(f"Bumped to version {VERSION_MAJOR}.{VERSION_MINOR}.{new_patch}")
        show_version()


def bump_minor() -> None:
    """Bump minor version (X.Y.Z -> X.Y+1.0)."""
    new_minor = VERSION_MINOR + 1
    if update_version_file(VERSION_MAJOR, new_minor, 0):
        print(f"Bumped to version {VERSION_MAJOR}.{new_minor}.0")
        show_version()


def bump_major() -> None:
    """Bump major version (X.Y.Z -> X+1.0.0)."""
    new_major = VERSION_MAJOR + 1
    if update_version_file(new_major, 0, 0):
        print(f"Bumped to version {new_major}.0.0")
        show_version()


def set_status(status: str) -> None:
    """Change development status."""
    valid_statuses = ["Development", "Alpha", "Beta", "RC", "Production"]
    if status not in valid_statuses:
        print(f"✗ Invalid status. Choose from: {', '.join(valid_statuses)}")
        return
    
    version_file = Path("version.py")
    try:
        content = version_file.read_text()
        content = content.replace(
            f'__status__ = "{__status__}"',
            f'__status__ = "{status}"'
        )
        version_file.write_text(content)
        print(f"✓ Updated status to '{status}'")
        show_version()
    except Exception as e:
        print(f"✗ Error updating status: {e}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Version management utility for AN-DETECT-ZIP-AGM",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python version_manager.py --show              # Show current version
  python version_manager.py --patch             # Bump patch version
  python version_manager.py --minor             # Bump minor version
  python version_manager.py --major             # Bump major version
  python version_manager.py --status Production # Change development status
        """
    )
    
    parser.add_argument(
        "--show",
        action="store_true",
        help="Display current version information"
    )
    
    parser.add_argument(
        "--patch",
        action="store_true",
        help="Bump patch version (bug fixes)"
    )
    
    parser.add_argument(
        "--minor",
        action="store_true",
        help="Bump minor version (new features)"
    )
    
    parser.add_argument(
        "--major",
        action="store_true",
        help="Bump major version (breaking changes)"
    )
    
    parser.add_argument(
        "--status",
        type=str,
        help="Set development status (Development, Alpha, Beta, RC, Production)"
    )
    
    args = parser.parse_args()
    
    if not any(vars(args).values()):
        parser.print_help()
        return
    
    if args.show:
        show_version()
    
    if args.patch:
        bump_patch()
    
    if args.minor:
        bump_minor()
    
    if args.major:
        bump_major()
    
    if args.status:
        set_status(args.status)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nAborted by user")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

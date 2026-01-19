"""
Version management for AN-DETECT-ZIP-AGM

This module provides version information for the application.

Usage:
    # Display version information directly
    python version.py

    # Import and use in code
    from version import __version__, get_version_info
    print(__version__)  # Output: 1.0.0
    print(get_version_info())  # Output: {'title': '...', 'version': '1.0.0', ...}

Semantic Versioning Format:
    MAJOR.MINOR.PATCH+BUILD
    
    MAJOR: Breaking changes (e.g., 1.0.0 → 2.0.0)
    MINOR: New features, backward compatible (e.g., 1.0.0 → 1.1.0)
    PATCH: Bug fixes (e.g., 1.0.0 → 1.0.1)
    BUILD: Optional build identifier (e.g., git commit)

For version management:
    - Use version_manager.py to change versions
    - Use release.py for automated releases
    
See docs/VERSION_TOOLS_GUIDE.md for complete documentation.
"""

__title__ = "An-Zip-Watcher"
__description__ = "ZIP file detector and repacker with GUI monitoring"
__version__ = "2.1.3"
__author__ = "AnAppWiLos"
__license__ = "MIT"
__status__ = "Production"  # Development, Alpha, Beta, RC, Production

# Version parts
VERSION_MAJOR = 2
VERSION_MINOR = 1
VERSION_PATCH = 3
VERSION_BUILD = None  # Set during build process


def get_version() -> str:
    """Get the full version string."""
    base_version = f"{VERSION_MAJOR}.{VERSION_MINOR}.{VERSION_PATCH}"
    if VERSION_BUILD:
        return f"{base_version}+{VERSION_BUILD}"
    return base_version


def get_version_info() -> dict:
    """Get complete version information as a dictionary."""
    return {
        "title": __title__,
        "version": get_version(),
        "author": __author__,
        "description": __description__,
        "status": __status__,
        "license": __license__,
    }


if __name__ == "__main__":
    info = get_version_info()
    for key, value in info.items():
        print(f"{key}: {value}")

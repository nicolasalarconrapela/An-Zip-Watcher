"""
Version management for AN-DETECT-ZIP-AGM

This module provides version information for the application.
"""

__title__ = "AN-DETECT-ZIP-AGM"
__description__ = "ZIP file detector and repacker with GUI monitoring"
__version__ = "1.0.0"
__author__ = "Development Team"
__license__ = "MIT"
__status__ = "Production"  # Development, Alpha, Beta, RC, Production

# Version parts
VERSION_MAJOR = 1
VERSION_MINOR = 0
VERSION_PATCH = 0
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

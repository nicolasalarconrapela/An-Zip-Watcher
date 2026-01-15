# Versioning Strategy

## Overview

AN-DETECT-ZIP-AGM uses **Semantic Versioning (SemVer)** for version management.

## Version Format

```
MAJOR.MINOR.PATCH+BUILD
```

### Version Components

- **MAJOR**: Breaking changes or significant feature additions
  - Example: `1.0.0` → `2.0.0`
- **MINOR**: New features, backward compatible
  - Example: `1.0.0` → `1.1.0`
- **PATCH**: Bug fixes and minor improvements

  - Example: `1.0.0` → `1.0.1`

- **BUILD**: Optional build identifier (e.g., git commit hash)
  - Example: `1.0.0+abc1234`

## Version Management Files

### `version.py`

Central location for version information. Update this file when releasing new versions.

```python
__version__ = "1.0.0"
VERSION_MAJOR = 1
VERSION_MINOR = 0
VERSION_PATCH = 0
VERSION_BUILD = None
```

### `CHANGELOG.md`

Document all changes for each release, following Keep a Changelog format.

### Status Levels

- **Development**: Active development version
- **Alpha**: Feature-complete but may have bugs
- **Beta**: Released for testing, mostly stable
- **RC**: Release Candidate
- **Production**: Stable release

## Release Process

### Step 1: Update Version Files

1. Edit `version.py`:

   - Update `__version__`
   - Update `VERSION_MAJOR`, `VERSION_MINOR`, `VERSION_PATCH`
   - Update `__status__` if applicable

2. Edit `CHANGELOG.md`:
   - Add new section with version and date
   - List all changes, features, and fixes

### Step 2: Commit Changes

```bash
git add version.py CHANGELOG.md
git commit -m "Release version X.Y.Z"
git tag -a vX.Y.Z -m "Release version X.Y.Z"
```

### Step 3: Build Executable

```bash
python build.py
```

### Step 4: Distribution

- Tag will be pushed with `git push origin --tags`
- Binary distribution will be available in `build/` directory

## Version Access in Code

### From version.py

```python
from version import __version__, get_version, get_version_info

print(f"Version: {__version__}")
print(f"Full version: {get_version()}")
print(f"Version info: {get_version_info()}")
```

### From watch_zip_repack.py

```python
from version import __version__
APP_VERSION = __version__
```

## Examples

### Release a patch version (bug fix)

```python
# version.py
__version__ = "1.0.1"
VERSION_PATCH = 1
```

### Release a minor version (new feature)

```python
# version.py
__version__ = "1.1.0"
VERSION_MINOR = 1
VERSION_PATCH = 0
```

### Release a major version (breaking changes)

```python
# version.py
__version__ = "2.0.0"
VERSION_MAJOR = 2
VERSION_MINOR = 0
VERSION_PATCH = 0
```

## Build Metadata

When building executables, you can set build metadata:

```bash
python build.py --build-id "201"
```

This will result in version strings like: `1.0.0+201`

## Version History

| Version | Date       | Status     | Notes           |
| ------- | ---------- | ---------- | --------------- |
| 1.0.0   | 2026-01-15 | Production | Initial release |

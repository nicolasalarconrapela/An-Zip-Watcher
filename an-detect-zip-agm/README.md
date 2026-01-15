# AN-DETECT-ZIP-AGM

A robust ZIP file detector and repacker application with real-time monitoring and GUI interface.

**Current Version:** v1.0.0 (Production)

## Features

- 🔍 Real-time ZIP file detection and monitoring
- 📦 Automatic ZIP file extraction and repacking
- 🖥️ User-friendly GUI with tkinter
- 📝 Event logging and history
- ⚙️ Configurable settings (JSON-based)
- 🔄 Queue-based architecture for reliable processing
- 📊 Memory-efficient log storage
- 🏗️ PyInstaller support for standalone executables
- 🌍 Cross-platform (Windows, macOS, Linux)

## Installation

### Prerequisites

- Python 3.8 or higher
- pip (Python package manager)

### Required Dependencies

```bash
pip install watchdog
```

### Optional Dependencies (for building)

```bash
pip install pyinstaller>=6.0.0
```

## Usage

### Running from Source

```bash
python watch_zip_repack.py
```

### Building Executable

```bash
python build.py
```

This will create a standalone executable in the `dist/` folder.

## Version Information

This project uses **Semantic Versioning (SemVer)** with automated version management tools.

**Quick Links:**

- 📚 [VERSION_QUICK_START.md](VERSION_QUICK_START.md) - Quick reference for common commands
- 📖 [VERSIONING.md](VERSIONING.md) - Complete versioning strategy and release process
- 📝 [CHANGELOG.md](CHANGELOG.md) - All releases and changes history
- 🎯 [EJEMPLOS_PRACTICOS.md](EJEMPLOS_PRACTICOS.md) - Practical usage examples

## Project Structure

```bash
an-detect-zip-agm/
├── watch_zip_repack.py      # Main application
├── build.py                 # Build script for executables
├── version.py               # Version information
├── settings.json            # Application configuration
├── README.md                # This file
├── CHANGELOG.md             # Version history and changes
├── VERSIONING.md            # Versioning strategy
└── build/                   # Build artifacts (generated)
```

## Version Management

### Checking the Current Version

```bash
# Display version information
python version.py

# Or with version manager tool
python version_manager.py --show
```

**Output:**

```
title: AN-DETECT-ZIP-AGM
version: 1.0.0
author: Development Team
description: ZIP file detector and repacker with GUI monitoring
status: Production
license: MIT
```

### Bumping Versions

Use the `version_manager.py` tool to increment versions following Semantic Versioning:

```bash
# For bug fixes (1.0.0 → 1.0.1)
python version_manager.py --patch

# For new features (1.0.0 → 1.1.0)
python version_manager.py --minor

# For breaking changes (1.0.0 → 2.0.0)
python version_manager.py --major
```

### Creating a Release

**Automated (Recommended):**

```bash
python release.py patch
```

This automatically:

1. Updates version in `version.py`
2. Builds new executable with `python build.py`
3. Creates git commit with updated files
4. Creates git tag for the release

**Preview before release:**

```bash
python release.py patch --dry-run
```

### Development Status

Change the development status of your release:

```bash
python version_manager.py --status Production
# Options: Development, Alpha, Beta, RC, Production
```

### Version Information Files

- **version.py** - Centralized version information (edit to change version manually)
- **CHANGELOG.md** - Record of all releases and changes
- **VERSIONING.md** - Complete versioning strategy documentation

## Configuration

The application stores settings in `settings.json` with configurable options for:

- Extract subdirectory
- Output subdirectory
- Processed files subdirectory
- Trash/deleted files subdirectory
- Polling intervals
- File settle time
- Event logging limits

## Development

### Project Structure - Development

- **Main Application:** `watch_zip_repack.py` - Core functionality with GUI
- **Build System:** `build.py` - PyInstaller integration with version info
- **Versioning:** `version.py` - Centralized version management

### Version Management Tools

The project includes three Python scripts for version management:

1. **version.py** - Displays version information
2. **version_manager.py** - CLI tool for bumping versions and changing status
3. **release.py** - Automates complete release workflow

See [Version Management](#version-management) section above for usage examples.

### Making Releases

**Quick release (recommended):**

```bash
python release.py minor
```

**Step-by-step:**

1. Update version: `python version_manager.py --patch`
2. Update `CHANGELOG.md` with changes
3. Build executable: `python build.py`
4. Commit and tag:
   ```bash
   git add version.py CHANGELOG.md
   git commit -m "Release v1.0.1"
   git tag -a v1.0.1 -m "Release version 1.0.1"
   ```

For detailed information, see [VERSIONING.md](VERSIONING.md).

## License

MIT

## Author

Development Team

---

## Additional Resources

- **Getting Started with Version Management:** [VERSION_QUICK_START.md](VERSION_QUICK_START.md)
- **Complete Versioning Guide:** [VERSIONING.md](VERSIONING.md)
- **Practical Examples:** [EJEMPLOS_PRACTICOS.md](EJEMPLOS_PRACTICOS.md)
- **Release History:** [CHANGELOG.md](CHANGELOG.md)

For a complete overview of the versioning system, see [RESUMEN_VERSIONADO.md](RESUMEN_VERSIONADO.md)

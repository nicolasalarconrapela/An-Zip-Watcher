# Quick Reference - Version Management

## Current Version
**v1.0.0** (Production)

## Files Modified for Versioning

### ✅ New Files Created
1. **version.py** - Central version information
2. **version_manager.py** - CLI tool for version management
3. **CHANGELOG.md** - Version history and changes
4. **VERSIONING.md** - Detailed versioning strategy

### ✅ Updated Files
1. **build.py** - Now displays version info during build
2. **README.md** - Added complete documentation

## Common Commands

### Check Current Version
```bash
python version.py
python version_manager.py --show
```

### Bump Versions
```bash
# For bug fixes
python version_manager.py --patch   # 1.0.0 → 1.0.1

# For new features (backward compatible)
python version_manager.py --minor   # 1.0.0 → 1.1.0

# For breaking changes
python version_manager.py --major   # 1.0.0 → 2.0.0
```

### Change Development Status
```bash
python version_manager.py --status Production
# Options: Development, Alpha, Beta, RC, Production
```

## Semantic Versioning Format

```
MAJOR.MINOR.PATCH+BUILD
```

- **MAJOR**: Breaking changes
- **MINOR**: New backward-compatible features
- **PATCH**: Bug fixes and minor improvements
- **BUILD**: Optional build identifier (git hash, build number)

## Release Workflow

### 1. Update Version
```bash
python version_manager.py --minor  # or --patch, --major
```

### 2. Update Changelog
Edit `CHANGELOG.md` and document changes:
```markdown
## [1.1.0] - 2026-01-15

### Added
- New feature X
- New feature Y

### Fixed
- Bug fix A
- Bug fix B

### Changed
- Modified behavior C
```

### 3. Build Executable
```bash
python build.py
```

### 4. Commit & Tag (Git)
```bash
git add version.py CHANGELOG.md
git commit -m "Release v1.1.0"
git tag -a v1.1.0 -m "Release version 1.1.0"
git push origin main --tags
```

## Version Information API

### In Python Code
```python
from version import __version__, get_version, get_version_info

# Get version string
print(__version__)  # "1.0.0"
print(get_version())  # "1.0.0" or "1.0.0+build123"

# Get full info
info = get_version_info()
# {
#     'title': 'AN-DETECT-ZIP-AGM',
#     'version': '1.0.0',
#     'author': 'Development Team',
#     'description': 'ZIP file detector and repacker',
#     'status': 'Production',
#     'license': 'MIT'
# }
```

## Version History

| Version | Date | Status | Type |
|---------|------|--------|------|
| 1.0.0 | 2026-01-15 | Production | Initial Release |

## Integration in Application UI

To display version in the GUI:
```python
from version import __version__
APP_TITLE = f"AN-DETECT-ZIP-AGM v{__version__}"
window.title(APP_TITLE)
```

## Best Practices

✅ **DO:**
- Update version before release
- Write descriptive changelog entries
- Use semantic versioning consistently
- Tag releases in git
- Test before incrementing major version

❌ **DON'T:**
- Skip changelog entries
- Release without testing
- Use confusing version numbers
- Modify version.py manually after using version_manager.py
- Forget to commit version changes

## Support

For detailed information:
- See [VERSIONING.md](VERSIONING.md) for complete strategy
- See [CHANGELOG.md](CHANGELOG.md) for release history
- Run `python version_manager.py --help` for CLI help

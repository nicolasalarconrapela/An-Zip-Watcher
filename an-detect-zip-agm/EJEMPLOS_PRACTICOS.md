# 📖 Ejemplos Prácticos - Sistema de Versionado

## 📚 Tabla de Contenidos

1. [Uso Básico](#uso-básico)
2. [Ejemplos de Release](#ejemplos-de-release)
3. [Integración en Código](#integración-en-código)
4. [Troubleshooting](#troubleshooting)

---

## 🎯 Uso Básico

### Ejemplo 1: Ver la versión actual

**Opción A - Línea de comandos:**

```bash
$ python version.py
title: AN-DETECT-ZIP-AGM
version: 1.0.0
author: Development Team
description: ZIP file detector and repacker with GUI monitoring
status: Production
license: MIT
```

**Opción B - Con version_manager:**

```bash
$ python version_manager.py --show

==================================================
  AN-DETECT-ZIP-AGM
==================================================
Version:     1.0.0
Status:      Production
Author:      Development Team
Description: ZIP file detector and repacker with GUI monitoring
License:     MIT
==================================================
```

---

## 🚀 Ejemplos de Release

### Ejemplo 2: Lanzar parche (bug fix)

**Situación:** Encontraste y fijaste un bug. Necesitas lanzar 1.0.1

```bash
# Opción automática (recomendada)
$ python release.py patch

# Resultado:
# ✓ Version bumped (patch)
# ✓ Build completed successfully
# ✓ Added version.py to git
# ✓ Committed with message: Release v1.0.1
# ✓ Created git tag: v1.0.1
```

**Resultado final:**

- Versión actualizada a **1.0.1**
- Ejecutable nuevo en `dist/`
- Git commit y tag creados

---

### Ejemplo 3: Lanzar versión menor (nueva feature)

**Situación:** Implementaste una nueva característica. Necesitas lanzar 1.1.0

```bash
# Ver primero qué pasaría
$ python release.py minor --dry-run

# DRY RUN: MINOR Release
# ℹ Current version: 1.0.0
# ℹ New version: 1.1.0
# ℹ Release date: 2026-01-15
# ℹ Git tag: v1.1.0

# Luego hacer el release real
$ python release.py minor

# Resultado:
# ✓ Version bumped (minor)
# ✓ Build completed successfully
# ✓ Added version.py to git
# ✓ Committed with message: Release v1.1.0
# ✓ Created git tag: v1.1.0
```

**Resultado final:**

- Versión actualizada a **1.1.0**
- Ejecutable nuevo en `dist/`
- Git commit y tag creados

---

### Ejemplo 4: Lanzar versión mayor (breaking changes)

**Situación:** Refactorizaste completamente la API. Necesitas lanzar 2.0.0

```bash
# Previsualizar
$ python release.py major --dry-run

# DRY RUN: MAJOR Release
# ℹ Current version: 1.0.0
# ℹ New version: 2.0.0
# ℹ Release date: 2026-01-15
# ℹ Git tag: v2.0.0

# Hacer el release
$ python release.py major

# Resultado: Versión 2.0.0 lista
```

---

### Ejemplo 5: Release sin build (si falla la compilación)

```bash
# Si el build falla o solo quieres actualizar versión
$ python release.py patch --skip-build

# Resultado:
# ✓ Version bumped (patch)
# ℹ Build skipped (--skip-build)
# ✓ Git operations completed
```

---

### Ejemplo 6: Release sin Git (si no usas git)

```bash
# Si no quieres operaciones git (commit/tag/push)
$ python release.py minor --skip-git

# Resultado:
# ✓ Version bumped (minor)
# ✓ Build completed successfully
# ℹ Git operations skipped (--skip-git)
```

---

## 🔧 Integración en Código

### Ejemplo 7: Usar versión en Python

**En watch_zip_repack.py:**

```python
# Importar versión
from version import __version__, get_version_info

# Usar en la aplicación
APP_TITLE = f"AN-DETECT-ZIP-AGM v{__version__}"
print(f"Starting {APP_TITLE}")

# O obtener toda la información
info = get_version_info()
print(f"Running {info['title']} {info['version']}")
print(f"Status: {info['status']}")
```

---

### Ejemplo 8: Mostrar versión en la GUI

**En la ventana principal:**

```python
from version import __version__
import tkinter as tk

root = tk.Tk()
root.title(f"ZipWatcher v{__version__}")

# O en una etiqueta
version_label = tk.Label(root, text=f"v{__version__}")
version_label.pack()

root.mainloop()
```

---

### Ejemplo 9: Mostrar versión en output al iniciar

```python
from version import get_version_info

def main():
    info = get_version_info()

    print("=" * 50)
    print(f"  {info['title']}")
    print("=" * 50)
    print(f"Version:     {info['version']}")
    print(f"Status:      {info['status']}")
    print("=" * 50)

    # Continuar con la aplicación...
    start_application()

if __name__ == "__main__":
    main()
```

---

## 📝 Cambiar Estado de Desarrollo

### Ejemplo 10: Cambiar a Alpha para testing

```bash
$ python version_manager.py --status Alpha

# Resultado:
# ✓ Updated status to 'Alpha'
#
# ==================================================
#   AN-DETECT-ZIP-AGM
# ==================================================
# Version:     1.0.0
# Status:      Alpha
# ...
```

**Valores válidos:**

- `Development` - Desarrollo activo
- `Alpha` - Feature-completo pero con bugs
- `Beta` - Lanzado para testing
- `RC` - Release Candidate
- `Production` - Estable y listo

---

### Ejemplo 11: Release de Beta a Production

```bash
# Cambiar a RC
$ python version_manager.py --status RC

# Después de testing, cambiar a Production
$ python version_manager.py --status Production

# Luego lanzar
$ python release.py patch
```

---

## 🔍 Verificar Cambios Antes de Lanzar

### Ejemplo 12: Ver qué cambiaría un release

```bash
# Previsualizar un patch
$ python release.py patch --dry-run

# DRY RUN: PATCH Release
# ============================================================
#   DRY RUN: PATCH Release
# ============================================================
#
# ℹ Current version: 1.0.0
# ℹ New version: 1.0.1
# ℹ Release date: 2026-01-15
# ℹ Git tag: v1.0.1
#
# Changes that would be made:
#   - version.py: Version updated
#   - dist/: New executable built
#   - Git: Commit and tag created
#
# To proceed with actual release, remove --dry-run flag
```

---

## ⚙️ Workflow Completo Paso a Paso

### Ejemplo 13: Crear una versión 1.1.0 con todas las características

**Paso 1: Preparar cambios**

```bash
# Tu código ya está listo, git staged con los cambios
```

**Paso 2: Previsualizar release**

```bash
$ python release.py minor --dry-run

# Resultado muestra: 1.0.0 → 1.1.0
```

**Paso 3: Actualizar CHANGELOG.md**

```markdown
## [1.1.0] - 2026-01-15

### Added

- New feature: Real-time ZIP monitoring improvements
- New feature: Advanced filtering options

### Fixed

- Fixed memory leak in event logging
- Fixed UI responsiveness on large files

### Changed

- Improved performance by 30%
```

**Paso 4: Hacer el release**

```bash
$ python release.py minor
```

**Paso 5: Verificar resultado**

```bash
python version.py
# version: 1.1.0

ls dist/
# ZipWatcher.exe  (versión 1.1.0)

git log --oneline | head
# a1b2c3d Release v1.1.0
```

---

## 🐛 Troubleshooting

### Problema 1: "ModuleNotFoundError: No module named 'version'"

**Solución:** Asegúrate de estar en el directorio correcto

```bash
cd /path/to/an-detect-zip-agm
python version.py  # ✓ Funciona aquí
```

---

### Problema 2: "Permission denied: 'build.py'"

**Solución:** Dale permisos de ejecución (Linux/macOS)

```bash
chmod +x build.py version_manager.py release.py
```

---

### Problema 3: Git tag ya existe

**Solución:** Si necesitas reasignar un tag

```bash
git tag -d v1.0.1           # Eliminar local
git push origin :v1.0.1     # Eliminar remoto
python release.py patch     # Crear de nuevo
```

---

### Problema 4: Build falla pero quiero actualizar versión

**Solución:** Usa --skip-build

```bash
python release.py patch --skip-build
# Actualiza versión y git, sin compilar
```

---

## 📊 Resumen de Comandos

```bash
# INFORMACIÓN
python version.py                           # Info en tabla
python version_manager.py --show            # Info formateada

# VERSIONES
python version_manager.py --patch           # 1.0.0 → 1.0.1
python version_manager.py --minor           # 1.0.0 → 1.1.0
python version_manager.py --major           # 1.0.0 → 2.0.0

# ESTADO
python version_manager.py --status Alpha    # Cambiar estado

# RELEASE AUTOMÁTICO
python release.py patch                     # Release completo
python release.py minor --skip-build        # Sin build
python release.py major --skip-git          # Sin git
python release.py patch --dry-run           # Previsualizar

# AYUDA
python version_manager.py --help            # Opciones disponibles
python release.py --help                    # Opciones de release
```

---

**¡Ahora tienes ejemplos prácticos para cada situación! 🎓**

Para más detalles, consulta:

- [VERSION_QUICK_START.md](VERSION_QUICK_START.md)
- [VERSIONING.md](VERSIONING.md)
- [INDEX_VERSIONADO.md](INDEX_VERSIONADO.md)

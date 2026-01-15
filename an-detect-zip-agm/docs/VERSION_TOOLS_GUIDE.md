# 🛠️ Version Tools Guide

Guía completa de uso de las herramientas de gestión de versiones para AN-DETECT-ZIP-AGM.

---

## 📋 Tabla de Contenidos

1. [Descripción General](#descripción-general)
2. [Scripts Disponibles](#scripts-disponibles)
3. [Uso de version.py](#uso-de-versionpy)
4. [Uso de version_manager.py](#uso-de-version_managerpy)
5. [Uso de release.py](#uso-de-releasepy)
6. [Flujo Completo de Release](#flujo-completo-de-release)
7. [Troubleshooting](#troubleshooting)

---

## Descripción General

El proyecto utiliza **3 scripts Python** para gestionar versiones de forma automatizada y profesional:

| Script               | Función                          | Uso Principal              |
| -------------------- | -------------------------------- | -------------------------- |
| `version.py`         | Almacena información de versión  | Consulta rápida de versión |
| `version_manager.py` | Gestiona cambios de versión      | Incrementar versiones      |
| `release.py`         | Automatiza el proceso de release | Publicar nuevas versiones  |

---

## Scripts Disponibles

### 1. **version.py** ⓘ

Módulo central que almacena la información de versión de la aplicación.

**Ubicación:** Raíz del proyecto

**Contenido:**

```python
__title__ = "AN-DETECT-ZIP-AGM"
__description__ = "ZIP file detector and repacker with GUI monitoring"
__version__ = "1.0.0"
__author__ = "Development Team"
__license__ = "MIT"
__status__ = "Production"

VERSION_MAJOR = 1
VERSION_MINOR = 0
VERSION_PATCH = 0
VERSION_BUILD = None
```

### 2. **version_manager.py** ⚙️

Herramienta CLI para gestionar versiones sin necesidad de editar archivos manualmente.

**Ubicación:** Raíz del proyecto

**Características:**

- ✅ Ver versión actual
- ✅ Incrementar versión (patch, minor, major)
- ✅ Cambiar estado de desarrollo
- ✅ Actualizar múltiples archivos automáticamente

### 3. **release.py** 🚀

Script de automatización completa que ejecuta todo el flujo de release.

**Ubicación:** Raíz del proyecto

**Características:**

- ✅ Incrementa versión
- ✅ Construye ejecutable
- ✅ Crea commits git
- ✅ Crea tags de versión
- ✅ Modo dry-run para previsualizar

---

## Uso de version.py

### Opción 1: Ejecución Directa

```bash
python version.py
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

### Opción 2: Importar en Python

```python
from version import __version__, get_version_info

# Obtener versión
print(__version__)  # Output: 1.0.0

# Obtener información completa
info = get_version_info()
print(info['version'])  # Output: 1.0.0
```

### Modificación Manual (No Recomendado)

Para cambios manuales, edita directamente el archivo `version.py`:

```python
# Cambio ejemplo: de 1.0.0 a 1.0.1
__version__ = "1.0.1"
VERSION_PATCH = 1
```

---

## Uso de version_manager.py

### Ver Versión Actual

```bash
python version_manager.py --show
```

**Output:**

```
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

### Incrementar Versión - Patch (Bug Fixes)

Usa para correcciones de bugs: `1.0.0` → `1.0.1`

```bash
python version_manager.py --patch
```

**Cambios realizados:**

- ✓ `version.py`: `VERSION_PATCH` incrementa en 1
- ✓ Muestra la nueva versión

**Cuándo usar:**

- Corrección de bugs
- Mejoras de rendimiento
- Ajustes menores sin cambios de API

### Incrementar Versión - Minor (Nuevas Features)

Usa para nuevas características: `1.0.0` → `1.1.0`

```bash
python version_manager.py --minor
```

**Cambios realizados:**

- ✓ `version.py`: `VERSION_MINOR` incrementa en 1
- ✓ `version.py`: `VERSION_PATCH` se resetea a 0
- ✓ Muestra la nueva versión

**Cuándo usar:**

- Nuevas características
- Mejoras retrocompatibles
- Cambios no disruptivos

### Incrementar Versión - Major (Breaking Changes)

Usa para cambios incompatibles: `1.0.0` → `2.0.0`

```bash
python version_manager.py --major
```

**Cambios realizados:**

- ✓ `version.py`: `VERSION_MAJOR` incrementa en 1
- ✓ `version.py`: `VERSION_MINOR` y `VERSION_PATCH` se resetean a 0
- ✓ Muestra la nueva versión

**Cuándo usar:**

- Cambios que rompen compatibilidad
- Reescrituras significativas
- Cambios en API pública

### Cambiar Estado de Desarrollo

Cambia el estado de desarrollo del proyecto.

```bash
python version_manager.py --status [Estado]
```

**Estados disponibles:**

- `Development` - En desarrollo activo
- `Alpha` - Versión alfa (features incompletas)
- `Beta` - En pruebas (features completas)
- `RC` - Release Candidate (casi lista)
- `Production` - Versión estable

**Ejemplos:**

```bash
# Marcar como producción
python version_manager.py --status Production

# Marcar como beta
python version_manager.py --status Beta

# Marcar como en desarrollo
python version_manager.py --status Development
```

### Ver Ayuda

```bash
python version_manager.py --help
```

---

## Uso de release.py

### Resumen Rápido (Dry Run)

Previsualiza los cambios sin hacer nada:

```bash
python release.py patch --dry-run
```

**Output:**

```
Dry Run: PATCH Release
ℹ Current version: 1.0.0
ℹ New version: 1.0.1
ℹ Release date: 2026-01-15
ℹ Git tag: v1.0.1

Changes that would be made:
  - version.py: Version updated
  - dist/: New executable built
  - Git: Commit and tag created
```

### Release de Patch (Bug Fix)

```bash
python release.py patch
```

**Proceso automático:**

1. Incrementa patch version (`1.0.0` → `1.0.1`)
2. Construye ejecutable con `python build.py`
3. Crea commit git: "Release v1.0.1"
4. Crea tag git: `v1.0.1`
5. Pregunta si deseas hacer push a remoto

### Release de Minor (Nuevas Features)

```bash
python release.py minor
```

**Proceso automático:**

1. Incrementa minor version (`1.0.0` → `1.1.0`)
2. Construye ejecutable
3. Crea commit y tag git
4. Pregunta por push a remoto

### Release de Major (Breaking Changes)

```bash
python release.py major
```

**Proceso automático:**

1. Incrementa major version (`1.0.0` → `2.0.0`)
2. Construye ejecutable
3. Crea commit y tag git
4. Pregunta por push a remoto

### Opciones Avanzadas

#### Skip Build (Sin Compilar Ejecutable)

```bash
python release.py patch --skip-build
```

**Uso:** Cuando solo necesitas actualizar versión sin compilar.

#### Skip Git (Sin Operaciones de Git)

```bash
python release.py patch --skip-git
```

**Uso:** Cuando tienes un flujo de git personalizado.

#### Combinadas

```bash
python release.py minor --skip-build --skip-git --dry-run
```

### Ver Ayuda

```bash
python release.py --help
```

---

## Flujo Completo de Release

### Escenario: Lanzar nueva versión 1.0.1 (bug fix)

#### Opción 1: Automática (Recomendada)

```bash
# 1. Previsualizar
python release.py patch --dry-run

# 2. Ejecutar release
python release.py patch

# 3. Responder a prompts (y/n para push)
# Yes or No? > y
```

#### Opción 2: Manual Paso a Paso

```bash
# 1. Incrementar versión
python version_manager.py --patch

# 2. Ver versión confirmada
python version_manager.py --show

# 3. Construir ejecutable
python build.py

# 4. Crear commit
git add version.py
git commit -m "Release v1.0.1"

# 5. Crear tag
git tag -a v1.0.1 -m "Release version 1.0.1"

# 6. Push (opcional)
git push origin main
git push origin --tags
```

### Escenario: Cambiar Estado sin Cambiar Versión

```bash
# Marcar versión actual como Production
python version_manager.py --status Production

# Ver confirmación
python version_manager.py --show
```

### Escenario: Múltiples Cambios Antes de Release

```bash
# 1. Hacer cambios en el código
# ... edita archivos ...

# 2. Previsualizamos
python release.py minor --dry-run

# 3. Si todo está bien, hacer release
python release.py minor
```

---

## Troubleshooting

### Problema: "Error updating version.py"

**Causa:** Permisos de archivo o encoding incorrecto

**Solución:**

```bash
# 1. Verificar permisos
ls -la version.py

# 2. Hacer el archivo escribible
chmod 644 version.py

# 3. Reintentar
python version_manager.py --patch
```

### Problema: "Git is not available"

**Causa:** Git no está instalado o no está en PATH

**Solución:**

```bash
# 1. Instalar Git
# Windows: descargar de https://git-scm.com/download/win
# Mac: brew install git
# Linux: apt-get install git

# 2. Usar flag --skip-git
python release.py patch --skip-git
```

### Problema: "There are uncommitted changes in git"

**Causa:** Hay cambios sin commitear

**Solución:**

```bash
# Opción 1: Hacer commit de cambios primero
git add .
git commit -m "Cambios pendientes"
python release.py patch

# Opción 2: Saltar operaciones de git
python release.py patch --skip-git

# Opción 3: Usar stash
git stash
python release.py patch
git stash pop
```

### Problema: "build.py not found"

**Causa:** El script de build no existe

**Solución:**

```bash
# Si existe build.py, verificar ruta
python release.py patch --skip-build

# Si no existe, crear uno básico o usar skip
```

### Problema: Versión no cambió después de ejecutar comando

**Causa:** El comando tuvo error silencioso

**Solución:**

```bash
# 1. Verificar versión actual
python version_manager.py --show

# 2. Verificar el archivo version.py
cat version.py

# 3. Intentar manualmente
python version_manager.py --patch --verbose

# 4. Verificar permisos y encoding
```

---

## Referencia Rápida

```bash
# Ver versión actual
python version.py
python version_manager.py --show

# Incrementar versión
python version_manager.py --patch    # 1.0.0 → 1.0.1
python version_manager.py --minor    # 1.0.0 → 1.1.0
python version_manager.py --major    # 1.0.0 → 2.0.0

# Cambiar estado
python version_manager.py --status Production
python version_manager.py --status Beta

# Release automático
python release.py patch              # Release patch
python release.py minor              # Release minor
python release.py major              # Release major
python release.py patch --dry-run    # Previsualizar

# Release avanzado
python release.py patch --skip-build # Sin compilar
python release.py patch --skip-git   # Sin git ops
```

---

## Ver También

- [VERSIONING.md](VERSIONING.md) - Estrategia de versionado
- [CHANGELOG.md](../CHANGELOG.md) - Historial de cambios
- [README.md](../README.md) - Documentación general

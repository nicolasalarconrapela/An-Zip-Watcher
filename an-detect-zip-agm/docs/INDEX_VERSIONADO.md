# 📚 Índice del Sistema de Versionado

## 🎯 Archivos Principales de Versioning

### 📄 Documentación (Lee estos primero)
- **[RESUMEN_VERSIONADO.md](RESUMEN_VERSIONADO.md)** ← COMIENZA AQUÍ
  - Resumen completo de todo lo implementado
  - Verificación de qué funciona
  - Próximos pasos opcionales

- **[VERSION_QUICK_START.md](VERSION_QUICK_START.md)**
  - Guía rápida de referencia
  - Comandos más comunes
  - Workflow de lanzamiento resumido

- **[VERSIONING.md](VERSIONING.md)**
  - Documentación detallada de estrategia
  - Explicación completa del Semantic Versioning
  - Proceso de release paso a paso

### 🔧 Scripts Python

- **[version.py](version.py)** - Módulo central
  - Información de versión actual
  - Funciones para obtener versión
  - Importable en otros módulos

- **[version_manager.py](version_manager.py)** - Herramienta CLI
  - Bumping de versiones (patch/minor/major)
  - Cambio de estado (Development/Alpha/Beta/RC/Production)
  - Visualización de info actual

- **[release.py](release.py)** - Automatización de lanzamientos
  - Ejecuta release completo
  - Build automático
  - Operaciones git (commit/tag/push)
  - Modo dry-run para previsualizar

### 📋 Histórico y Cambios

- **[CHANGELOG.md](CHANGELOG.md)**
  - Registro de todas las versiones
  - Historial de cambios y features
  - Actualizar aquí en cada release

### 📖 Documentación General

- **[README.md](README.md)**
  - Documentación general del proyecto
  - Instalación, uso, features
  - Enlaces a archivos de versioning

---

## ⚡ Comandos Rápidos

```bash
# Ver versión actual
python version.py
python version_manager.py --show

# Incrementar versión
python version_manager.py --patch   # Bug fix (1.0.0 → 1.0.1)
python version_manager.py --minor   # Nueva feature (1.0.0 → 1.1.0)
python version_manager.py --major   # Breaking change (1.0.0 → 2.0.0)

# Cambiar estado
python version_manager.py --status Production
# Opciones: Development, Alpha, Beta, RC, Production

# Lanzamiento completo
python release.py patch             # Release de parche
python release.py minor --skip-build # Release sin build
python release.py major --dry-run   # Previsualizar major release
```

---

## 🚀 Workflow de Release Recomendado

### Opción A: Automático (Recomendado)
```bash
# Hace todo automáticamente
python release.py patch
```

### Opción B: Manual paso a paso
```bash
# 1. Actualizar versión
python version_manager.py --patch

# 2. Editar CHANGELOG.md (agregar cambios)
# 3. Construir ejecutable
python build.py

# 4. Confirmar en git
git add version.py CHANGELOG.md
git commit -m "Release v1.0.1"
git tag -a v1.0.1 -m "Release version 1.0.1"
git push origin main --tags
```

---

## 📊 Estructura de Versioning

```
version.py
├── __version__ = "1.0.0"
├── VERSION_MAJOR = 1
├── VERSION_MINOR = 0
├── VERSION_PATCH = 0
├── __status__ = "Production"
└── funciones:
    ├── get_version()
    └── get_version_info()
```

---

## 📌 Información Actual

**Versión:** 1.0.0 (Production)  
**Estado:** Listo para usar  
**Última actualización:** 2026-01-15

---

## 🔄 Información Integrada

### En build.py
- Importa version.py
- Muestra versión al compilar
- Etiqueta ejecutables con versión

### En README.md
- Badge de versión actual
- Enlaces a archivos de versioning
- Documentación actualizada

### En watch_zip_repack.py (opcional)
Puede importar versión con:
```python
from version import __version__
APP_VERSION = __version__
```

---

## 📚 Guía por Caso de Uso

### Caso 1: Revisar versión actual
→ Ejecuta: `python version.py` o lee [VERSION_QUICK_START.md](VERSION_QUICK_START.md)

### Caso 2: Lanzar nueva versión
→ Ejecuta: `python release.py patch` o lee [VERSIONING.md](VERSIONING.md)

### Caso 3: Entender el sistema completo
→ Lee: [RESUMEN_VERSIONADO.md](RESUMEN_VERSIONADO.md)

### Caso 4: Ver comandos disponibles
→ Ejecuta: `python version_manager.py --help` o `python release.py --help`

---

## ✅ Verificación Rápida

Todos estos comandos deben funcionar:

```bash
python version.py                    # ✓ Muestra info
python version_manager.py --show     # ✓ Muestra versión
python version_manager.py --help     # ✓ Ayuda disponible
python release.py --help            # ✓ Ayuda de release
python release.py patch --dry-run   # ✓ Previsualiza release
```

---

## 🎓 Recursos Adicionales

- **Semantic Versioning:** https://semver.org/
- **Keep a Changelog:** https://keepachangelog.com/
- **Python Packaging:** https://packaging.python.org/

---

**¡Sistema de versionado completamente implementado y listo para usar! 🎉**

Para dudas, consulta los archivos de documentación o ejecuta con `--help`

# Changelog

All notable changes to the AN-DETECT-ZIP-AGM project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.1.4] - 2026-01-18

### Fixed
- Actualización automática de eventos procesados ante cambios externos y acciones de mantenimiento.
- Detección recursiva en Trash para estados de archivos movidos.

## [2.1.3] - 2026-01-18

### Fixed
- Detección consistente de carpetas de limpieza y creación de Trash cuando no existe.

## [2.1.2] - 2026-01-18

### Fixed
- Procesamiento consistente usando la carpeta de vigilancia vigente al encolar cada ZIP.

## [2.1.1] - 2026-01-18

### Fixed
- Parada segura de hilos en el cierre de la aplicación para evitar procesos pendientes.

## [2.1.0] - 2026-01-18

### Added
- Cola de procesamiento para encolar ZIPs detectados antes de procesarlos.
- Hilo dedicado para procesar ZIPs desde la cola.

## [1.0.0] - 2026-01-15

### Added
- Initial release of AN-DETECT-ZIP-AGM
- ZIP file detection and monitoring system
- GUI interface with tkinter
- File repacking functionality
- Real-time event logging
- Settings persistence (JSON-based)
- Build automation with PyInstaller
- Versioning system

### Features
- Watch directories for ZIP file changes
- Extract and process ZIP files
- Automatic file organization (extracted, output, processed, trash)
- Event queue-based architecture
- Configurable polling intervals
- Max settle time for file stability checking
- Recent events display in UI
- Log storage with memory limits

### Technical
- Python 3.8+
- Watchdog library integration
- PyInstaller support for standalone executables
- Cross-platform support (Windows, macOS, Linux)

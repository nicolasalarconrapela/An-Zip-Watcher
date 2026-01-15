#!/usr/bin/env python3
"""
Build script to create standalone executables using PyInstaller.
Works on Windows, macOS, and Linux.
"""

import os
import sys
import subprocess
import platform
import shutil
from pathlib import Path


class Colors:
    """ANSI color codes for terminal output"""
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    END = '\033[0m'
    BOLD = '\033[1m'


def print_header(msg):
    """Print a formatted header message"""
    print(f"\n{Colors.BOLD}{Colors.BLUE}{'='*60}")
    print(f"  {msg}")
    print(f"{'='*60}{Colors.END}\n")


def print_success(msg):
    """Print a success message"""
    print(f"{Colors.GREEN}✓ {msg}{Colors.END}")


def print_error(msg):
    """Print an error message"""
    print(f"{Colors.RED}✗ {msg}{Colors.END}")


def print_warning(msg):
    """Print a warning message"""
    print(f"{Colors.YELLOW}⚠ {msg}{Colors.END}")


def print_info(msg):
    """Print an info message"""
    print(f"{Colors.BLUE}ℹ {msg}{Colors.END}")


def check_dependencies():
    """Check if PyInstaller is installed"""
    print_header("Checking Dependencies")
    
    try:
        import PyInstaller
        version = PyInstaller.__version__
        print_success(f"PyInstaller {version} is installed")
        return True
    except ImportError:
        print_error("PyInstaller is not installed")
        print_info("Installing PyInstaller...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller>=6.0.0"])
            print_success("PyInstaller installed successfully")
            return True
        except subprocess.CalledProcessError:
            print_error("Failed to install PyInstaller")
            return False


def clean_build_directories():
    """Remove old build directories"""
    print_header("Cleaning Build Directories")
    
    dirs_to_clean = ['build', 'dist', '__pycache__']
    for dir_name in dirs_to_clean:
        dir_path = Path(dir_name)
        if dir_path.exists():
            shutil.rmtree(dir_path)
            print_success(f"Removed {dir_name}/")
        else:
            print_info(f"{dir_name}/ not found (skipped)")


def get_platform_specific_args():
    """Return platform-specific PyInstaller arguments"""
    system = platform.system()
    
    args = [
        "--onefile",
        "--windowed",
        "--name=ZipWatcher",
    ]
    
    if system == "Windows":
        args.extend([
            "--icon=NONE",
        ])
    elif system == "Darwin":  # macOS
        args.extend([
            "--osx-bundle-identifier=com.zipwatcher.app",
        ])
    elif system == "Linux":
        args.extend([
            "--hidden-import=tkinter",
        ])
    
    return args


def build_executable():
    """Build the executable using PyInstaller"""
    print_header("Building Executable with PyInstaller")
    
    args = get_platform_specific_args()
    args.append("watch_zip_repack.py")
    
    print_info(f"Platform: {platform.system()}")
    print_info(f"Python: {sys.version.split()[0]}")
    print_info(f"Command: pyinstaller {' '.join(args)}\n")
    
    try:
        subprocess.check_call([sys.executable, "-m", "PyInstaller"] + args)
        print_success("Build completed successfully!")
        return True
    except subprocess.CalledProcessError as e:
        print_error(f"Build failed with error code {e.returncode}")
        return False


def show_build_info():
    """Display information about the build result"""
    print_header("Build Information")
    
    dist_path = Path("dist")
    if not dist_path.exists():
        print_error("dist/ directory not found")
        return
    
    system = platform.system()
    
    if system == "Windows":
        exe_name = "ZipWatcher.exe"
        exe_path = dist_path / exe_name
        if exe_path.exists():
            size = exe_path.stat().st_size / (1024 * 1024)
            print_success(f"Executable created: {exe_path}")
            print_info(f"Size: {size:.2f} MB")
            print_info(f"Run: {exe_path}")
        else:
            print_error(f"{exe_name} not found in dist/")
    
    elif system == "Darwin":  # macOS
        app_path = dist_path / "ZipWatcher.app"
        if app_path.exists():
            print_success(f"App bundle created: {app_path}")
            print_info(f"Run: open {app_path}")
        else:
            print_error("ZipWatcher.app not found in dist/")
    
    elif system == "Linux":
        exe_name = "ZipWatcher"
        exe_path = dist_path / exe_name
        if exe_path.exists():
            size = exe_path.stat().st_size / (1024 * 1024)
            print_success(f"Executable created: {exe_path}")
            print_info(f"Size: {size:.2f} MB")
            print_info(f"Run: ./dist/{exe_name}")
        else:
            print_error(f"{exe_name} not found in dist/")


def main():
    """Main build process"""
    print_header("ZipWatcher Build System")
    print_info("Building standalone executable for your system\n")
    
    # Step 1: Check dependencies
    if not check_dependencies():
        sys.exit(1)
    
    # Step 2: Clean old builds
    clean_build_directories()
    
    # Step 3: Build executable
    if not build_executable():
        sys.exit(1)
    
    # Step 4: Show build info
    show_build_info()
    
    print_header("Build Complete!")
    print_success("Your executable is ready in the dist/ folder")
    print_info("You can now distribute it to other computers")


if __name__ == "__main__":
    main()

from PIL import Image
import sys
from pathlib import Path

def convert_to_ico(png_path, ico_path):
    try:
        if not Path(png_path).exists():
            print(f"Error: {png_path} no existe")
            return False
            
        img = Image.open(png_path)
        # Guardar como ICO con múltiples tamaños para mejor calidad en Windows
        img.save(ico_path, format='ICO', sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
        print(f"Éxito: Convertido {png_path} a {ico_path}")
        return True
    except Exception as e:
        print(f"Error convirtiendo icono: {e}")
        return False

if __name__ == "__main__":
    base = Path(__file__).parent
    png = base / "imgs" / "icons.png"
    ico = base / "app.ico"
    
    if convert_to_ico(png, ico):
        sys.exit(0)
    else:
        sys.exit(1)

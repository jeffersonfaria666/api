#!/usr/bin/env python3
"""
Script para configurar cookies de YouTube
Ejecutar localmente y subir el archivo cookies.txt al servidor
"""

import json
import os

def create_cookies_guide():
    """Crea una guía para obtener cookies"""
    
    guide = """
    ============================================
    GUÍA PARA OBTENER COOKIES DE YOUTUBE
    ============================================
    
    1. Instala la extensión "Get cookies.txt" en Chrome:
       https://chrome.google.com/webstore/detail/get-cookiestxt/bgaddhkoddajcdgocldbbfleckgcbcid
    
    2. Ve a youtube.com e inicia sesión con tu cuenta
    
    3. Haz clic en la extensión y exporta las cookies
    
    4. Guarda el archivo como 'cookies.txt' en la raíz del proyecto
    
    5. Sube el archivo a Render.com:
       - Ve a tu servicio en Render
       - Haz clic en "Environment"
       - Sube el archivo en la sección de archivos estáticos
    
    6. En tu código, descomenta la línea:
       # 'cookiefile': 'cookies.txt',
    
    ============================================
    ADVERTENCIA: 
    - No compartas tu archivo cookies.txt
    - Las cookies expiran, necesitarás actualizarlas periódicamente
    - Esto puede violar los Términos de Servicio de YouTube
    ============================================
    """
    
    print(guide)
    
    # Crear archivo de ejemplo
    example_cookies = """# Netscape HTTP Cookie File
.youtube.com	TRUE	/	TRUE	1700000000	VISITOR_INFO1_LIVE	tu_cookie_aqui
.youtube.com	TRUE	/	TRUE	1700000000	YSC	tu_cookie_aqui
.youtube.com	TRUE	/	TRUE	1700000000	LOGIN_INFO	tu_cookie_aqui
"""
    
    with open('cookies_example.txt', 'w') as f:
        f.write(example_cookies)
    
    print(f"✅ Archivo de ejemplo creado: cookies_example.txt")
    print(f"📖 Lee el archivo README_COOKIES.md para más información")

if __name__ == "__main__":
    create_cookies_guide()

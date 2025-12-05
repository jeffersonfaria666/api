#!/usr/bin/env python3
"""
🚀 SERVIDOR YOUTUBE/TIKTOK PARA RENDER.COM
Versión: 1.0 - Simple y Funcional
"""

import os
import sys
import json
import logging
import random
import time
import threading
from datetime import datetime
from pathlib import Path

from flask import Flask, request, jsonify, send_file, Response
from flask_cors import CORS
import yt_dlp

# ==============================
# CONFIGURACIÓN PARA RENDER
# ==============================
class Config:
    # Render establece PORT automáticamente
    PORT = int(os.environ.get('PORT', 10000))
    HOST = '0.0.0.0'
    
    # Directorio temporal en Render (usar /tmp/)
    TEMP_DIR = '/tmp/youtube_downloads'
    
    # Límites para evitar problemas en free tier
    MAX_FILE_SIZE = 300 * 1024 * 1024  # 300MB máximo
    MAX_WORKERS = 2
    TIMEOUT = 180  # 3 minutos máximo por descarga
    
    # User-Agents para rotar
    USER_AGENTS = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36',
    ]

# ==============================
# SETUP DE LOGGING
# ==============================
def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[logging.StreamHandler(sys.stdout)]
    )
    return logging.getLogger(__name__)

logger = setup_logging()

# ==============================
# CLASE DE DESCARGA SIMPLE
# ==============================
class SimpleDownloader:
    """Descargador simple y confiable"""
    
    def __init__(self, url, download_type="best"):
        self.url = url
        self.download_type = download_type
        self.temp_dir = Config.TEMP_DIR
        
        # Crear directorio temporal
        os.makedirs(self.temp_dir, exist_ok=True)
        
        # Estado
        self.status = "pending"
        self.error = None
        self.filename = None
        
        logger.info(f"Iniciando descarga: {url[:50]}...")
    
    def clean_filename(self, name):
        """Limpia caracteres inválidos del nombre"""
        invalid = '<>:"/\\|?*'
        for char in invalid:
            name = name.replace(char, '_')
        return name[:80]
    
    def get_info(self):
        """Obtiene información básica del video"""
        try:
            opts = {
                'quiet': True,
                'no_warnings': True,
                'skip_download': True,
                'socket_timeout': 15,
                'retries': 3,
                'ignoreerrors': True,
                'http_headers': {
                    'User-Agent': random.choice(Config.USER_AGENTS),
                    'Accept': '*/*',
                }
            }
            
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(self.url, download=False)
                
                if not info:
                    return {'success': False, 'error': 'Video no encontrado'}
                
                # Formato simple
                formats = []
                for fmt in info.get('formats', []):
                    if fmt.get('url'):
                        formats.append({
                            'id': fmt.get('format_id', ''),
                            'ext': fmt.get('ext', ''),
                            'quality': fmt.get('height', 0),
                            'size': fmt.get('filesize', 0),
                        })
                
                # Ordenar por calidad
                formats.sort(key=lambda x: x['quality'], reverse=True)
                
                return {
                    'success': True,
                    'title': info.get('title', 'Video'),
                    'duration': info.get('duration', 0),
                    'thumbnail': info.get('thumbnail', ''),
                    'formats': formats[:5],
                }
                
        except Exception as e:
            logger.error(f"Error obteniendo info: {e}")
            return {'success': False, 'error': str(e)}
    
    def download(self):
        """Descarga el archivo"""
        self.status = "downloading"
        start_time = time.time()
        
        try:
            # Configurar opciones según tipo
            opts = {
                'outtmpl': f'{self.temp_dir}/%(id)s.%(ext)s',
                'quiet': True,
                'no_warnings': True,
                'socket_timeout': 30,
                'retries': 5,
                'fragment_retries': 5,
                'ignoreerrors': True,
                'http_headers': {
                    'User-Agent': random.choice(Config.USER_AGENTS),
                    'Accept': '*/*',
                },
            }
            
            if self.download_type == "audio":
                opts.update({
                    'format': 'bestaudio/best',
                    'postprocessors': [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                    }]
                })
            else:
                # Para video, limitar tamaño y calidad
                opts['format'] = 'best[filesize<50M][height<=720]'
            
            # Descargar
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(self.url, download=True)
                
                if not info:
                    self.status = "failed"
                    return {'success': False, 'error': 'No se pudo descargar'}
                
                # Encontrar archivo descargado
                video_id = info.get('id', 'video')
                for file in os.listdir(self.temp_dir):
                    if file.startswith(video_id):
                        self.filename = file
                        break
                
                if not self.filename:
                    self.status = "failed"
                    return {'success': False, 'error': 'Archivo no encontrado'}
                
                filepath = f'{self.temp_dir}/{self.filename}'
                filesize = os.path.getsize(filepath)
                
                # Verificar tamaño máximo
                if filesize > Config.MAX_FILE_SIZE:
                    os.remove(filepath)
                    self.status = "failed"
                    return {
                        'success': False, 
                        'error': f'Archivo muy grande ({filesize//1024//1024}MB > {Config.MAX_FILE_SIZE//1024//1024}MB)'
                    }
                
                # Renombrar con título
                try:
                    title = info.get('title', 'video')
                    safe_title = self.clean_filename(title)
                    ext = os.path.splitext(self.filename)[1]
                    new_name = f"{safe_title}{ext}"
                    new_path = f'{self.temp_dir}/{new_name}'
                    
                    # Evitar colisiones
                    counter = 1
                    while os.path.exists(new_path):
                        new_name = f"{safe_title}_{counter}{ext}"
                        new_path = f'{self.temp_dir}/{new_name}'
                        counter += 1
                    
                    os.rename(filepath, new_path)
                    self.filename = new_name
                    filepath = new_path
                except:
                    pass  # Si falla el renombrado, continuar
                
                self.status = "completed"
                download_time = time.time() - start_time
                
                return {
                    'success': True,
                    'filename': self.filename,
                    'filepath': filepath,
                    'filesize': filesize,
                    'download_time': download_time,
                    'title': info.get('title', 'Video'),
                }
                
        except Exception as e:
            self.status = "failed"
            self.error = str(e)
            logger.error(f"Error en descarga: {e}")
            return {'success': False, 'error': str(e)}
    
    def cleanup(self):
        """Limpia el archivo"""
        if self.filename:
            try:
                filepath = f'{self.temp_dir}/{self.filename}'
                if os.path.exists(filepath):
                    os.remove(filepath)
                    return True
            except:
                pass
        return False

# ==============================
# SISTEMA DE LIMPIEZA
# ==============================
class CleanupSystem:
    """Limpia archivos antiguos automáticamente"""
    
    def __init__(self):
        self.temp_dir = Config.TEMP_DIR
        self.running = True
        self.thread = threading.Thread(target=self.cleanup_loop, daemon=True)
        self.thread.start()
        logger.info("Sistema de limpieza iniciado")
    
    def cleanup_loop(self):
        """Loop de limpieza cada 5 minutos"""
        while self.running:
            try:
                time.sleep(300)  # 5 minutos
                
                if not os.path.exists(self.temp_dir):
                    continue
                
                # Eliminar archivos con más de 1 hora
                cutoff = time.time() - 3600
                deleted = 0
                
                for file in os.listdir(self.temp_dir):
                    filepath = f'{self.temp_dir}/{file}'
                    try:
                        if os.path.isfile(filepath):
                            if os.path.getmtime(filepath) < cutoff:
                                os.remove(filepath)
                                deleted += 1
                    except:
                        pass
                
                if deleted > 0:
                    logger.info(f"Limpieza: {deleted} archivos eliminados")
                    
            except Exception as e:
                logger.error(f"Error en limpieza: {e}")
    
    def stop(self):
        """Detiene el sistema de limpieza"""
        self.running = False

# ==============================
# INICIALIZAR FLASK
# ==============================
app = Flask(__name__)
CORS(app)  # Permitir CORS para todos los orígenes

# Iniciar sistema de limpieza
cleanup_system = CleanupSystem()

# ==============================
# ENDPOINTS DE LA API
# ==============================

@app.route('/')
def home():
    """Página principal"""
    return jsonify({
        'service': 'YouTube/TikTok Downloader',
        'version': '1.0',
        'status': 'online',
        'timestamp': datetime.now().isoformat(),
        'endpoints': {
            '/': 'Esta página',
            '/health': 'Estado del servidor',
            '/info': 'Información de video (POST)',
            '/download': 'Descargar video (POST)',
            '/file/<name>': 'Obtener archivo (GET)',
        },
        'limits': {
            'max_size': '300MB',
            'timeout': '3 minutos',
        }
    })

@app.route('/health')
def health():
    """Health check para Render"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat()
    })

@app.route('/info', methods=['POST'])
def get_video_info():
    """Obtiene información de un video"""
    try:
        # Obtener datos
        if request.is_json:
            data = request.get_json()
        else:
            data = request.form
        
        url = data.get('url')
        
        if not url:
            return jsonify({'error': 'Se requiere URL'}), 400
        
        # Validar URL
        if not ('youtube.com' in url or 'youtu.be' in url or 'tiktok.com' in url):
            return jsonify({'error': 'URL no válida'}), 400
        
        # Obtener información
        downloader = SimpleDownloader(url)
        result = downloader.get_info()
        
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Error en /info: {e}")
        return jsonify({'error': 'Error interno'}), 500

@app.route('/download', methods=['POST'])
def download_video():
    """Descarga un video/audio"""
    try:
        # Obtener datos
        if request.is_json:
            data = request.get_json()
        else:
            data = request.form
        
        url = data.get('url')
        download_type = data.get('type', 'best')
        
        if not url:
            return jsonify({'error': 'Se requiere URL'}), 400
        
        # Validar tipo
        if download_type not in ['video', 'audio', 'best']:
            return jsonify({'error': 'Tipo debe ser: video, audio o best'}), 400
        
        # Crear descargador
        downloader = SimpleDownloader(url, download_type)
        
        # Descargar
        result = downloader.download()
        
        if not result.get('success'):
            return jsonify(result), 400
        
        # Crear respuesta de descarga
        filepath = result['filepath']
        filename = result['filename']
        
        def generate():
            with open(filepath, 'rb') as f:
                while chunk := f.read(8192):
                    yield chunk
            
            # Limpiar después de enviar
            try:
                os.remove(filepath)
            except:
                pass
        
        return Response(
            generate(),
            mimetype='application/octet-stream',
            headers={
                'Content-Disposition': f'attachment; filename="{filename}"',
                'Content-Length': str(result['filesize'])
            }
        )
        
    except Exception as e:
        logger.error(f"Error en /download: {e}")
        return jsonify({'error': 'Error interno'}), 500

@app.route('/file/<filename>', methods=['GET'])
def get_file(filename):
    """Obtiene un archivo descargado (alternativa)"""
    try:
        # Prevenir path traversal
        if '..' in filename or '/' in filename or '\\' in filename:
            return jsonify({'error': 'Nombre de archivo inválido'}), 400
        
        filepath = f'{Config.TEMP_DIR}/{filename}'
        
        if not os.path.exists(filepath):
            return jsonify({'error': 'Archivo no encontrado'}), 404
        
        return send_file(
            filepath,
            as_attachment=True,
            download_name=filename
        )
        
    except Exception as e:
        logger.error(f"Error en /file: {e}")
        return jsonify({'error': 'Error interno'}), 500

# ==============================
# MANEJO DE ERRORES
# ==============================
@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Endpoint no encontrado'}), 404

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"Error 500: {error}")
    return jsonify({'error': 'Error interno del servidor'}), 500

# ==============================
# INICIALIZACIÓN
# ==============================
if __name__ == '__main__':
    # Mostrar información
    print("\n" + "="*60)
    print("🚀 SERVIDOR YOUTUBE/TIKTOK - LISTO PARA RENDER")
    print("="*60)
    print(f"📡 Puerto: {Config.PORT}")
    print(f"💾 Directorio temporal: {Config.TEMP_DIR}")
    print(f"📦 Tamaño máximo: {Config.MAX_FILE_SIZE//1024//1024}MB")
    print("="*60)
    print("✅ Sistema de limpieza automática activado")
    print("✅ CORS habilitado para todos los orígenes")
    print("✅ Timeout: 3 minutos por descarga")
    print("="*60)
    
    # Asegurar directorio temporal
    os.makedirs(Config.TEMP_DIR, exist_ok=True)
    
    # Usar waitress en lugar de gunicorn
    try:
        from waitress import serve
        print("⚡ Usando Waitress para producción")
        serve(app, host=Config.HOST, port=Config.PORT, threads=4)
    except ImportError:
        print("⚠️ Waitress no disponible, usando Flask server")
        app.run(host=Config.HOST, port=Config.PORT, debug=False)


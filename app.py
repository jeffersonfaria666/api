import os
import sys
import time
import sqlite3
import requests
import random
import asyncio
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from yt_dlp import YoutubeDL
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, CallbackQueryHandler, filters
from telegram.error import BadRequest, RetryAfter
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

# Configuración
BOT_TOKEN = os.getenv('BOT_TOKEN', '7239423213:AAE6lmCeiuz9_GoeujWDYo64B0FOfcHoFFA')
USDT_ADDRESS = "0x594EAB95D5683851E0eBFfC457C07dc217Bf4830".lower()
BSC_API_KEY = os.getenv('BSC_API_KEY', '9769MICJ2Z1PAEZVVZCX9HKYSIRWVYZA')
LIMIT_POR_DIA = 100
MIN_USDT = 4.99
DB_NAME = "usuarios.db"
MAX_WORKERS = 2  # Reducido para Render Free
MAX_FRAGMENTS = 8  # Reducido para ahorrar recursos
CHUNK_SIZE = 5 * 1024 * 1024  # Reducido
MAX_FILE_SIZE = 500 * 1024 * 1024  # Reducido a 500MB para Telegram

# Parsear ADMIN_IDS desde variable de entorno
ADMIN_IDS_STR = os.getenv('ADMIN_IDS', '')
ADMIN_IDS = [int(id.strip()) for id in ADMIN_IDS_STR.split(',') if id.strip().isdigit()]

# Sistema de recompensas
REWARD_PER_DOWNLOAD_MIN = 0.01
REWARD_PER_DOWNLOAD_MAX = 0.50
REFERRAL_REWARD = 5.00

# URLs
COMUNIDAD_URL = "https://t.me/descargar_videos_de_tiktok"
DONACION_URL = "https://www.paypal.com/paypalme/JeffersonFaria525"
RECOMPENSAS_URL = "https://cryptorewards.page.gd/"

# Límites
MAX_TT_SIZE_NON_PREMIUM = 50 * 1024 * 1024
YOUTUBE_DAILY_LIMIT = 3  # Reducido para usuarios gratuitos
MIN_WITHDRAWAL = 50

# Almacenamiento temporal
download_jobs = {}
executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)
current_downloads = {}
progress_trackers = {}

# Sistema de colas simplificado para Render
class DownloadQueueSystem:
    def __init__(self, max_workers=2):
        self.max_workers = max_workers
        self.priority_queue = asyncio.Queue()
        self.active_tasks = {}
        self.task_counter = 0
        self.workers = []
        self.is_running = True
        self.app = None
        self.running_on_render = 'RENDER' in os.environ
        
    def set_application(self, app):
        self.app = app
        
    async def start(self):
        """Inicia los workers de la cola"""
        for i in range(self.max_workers):
            worker = asyncio.create_task(self._worker(i))
            self.workers.append(worker)
        log_event(f"🚀 Sistema de colas iniciado con {self.max_workers} workers")
        
    async def stop(self):
        """Detiene todos los workers"""
        self.is_running = False
        for worker in self.workers:
            worker.cancel()
        await asyncio.gather(*self.workers, return_exceptions=True)
        
    async def add_task(self, priority, task_data):
        """Añade una tarea a la cola con prioridad"""
        self.task_counter += 1
        task_id = self.task_counter
        await self.priority_queue.put((priority, task_id, task_data))
        return task_id
        
    async def _worker(self, worker_id):
        """Worker que procesa tareas de la cola"""
        log_event(f"👷 Worker {worker_id} iniciado")
        
        while self.is_running:
            try:
                try:
                    priority, task_id, task_data = await asyncio.wait_for(
                        self.priority_queue.get(), timeout=10.0
                    )
                except asyncio.TimeoutError:
                    continue
                    
                job_id, user_id, url, tipo, chat_id, message_id = task_data
                
                if user_id in self.active_tasks:
                    log_event(f"⏳ Usuario {user_id} ya tiene tarea activa, reencolando...")
                    new_priority = max(0, priority - 0.1)
                    await self.add_task(new_priority, task_data)
                    self.priority_queue.task_done()
                    await asyncio.sleep(2)
                    continue
                
                self.active_tasks[user_id] = task_id
                try:
                    await self._process_task(worker_id, task_data)
                finally:
                    if user_id in self.active_tasks:
                        del self.active_tasks[user_id]
                    self.priority_queue.task_done()
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                log_event(f"❌ Error en worker {worker_id}: {e}")
                await asyncio.sleep(2)
                
    async def _process_task(self, worker_id, task_data):
        """Procesa una tarea individual"""
        job_id, user_id, url, tipo, chat_id, message_id = task_data
        
        try:
            log_event(f"🔁 Worker {worker_id} procesando tarea para usuario {user_id}")
            
            progress_tracker = SafeProgressTracker(chat_id, message_id, user_id, self.app)
            progress_trackers[user_id] = progress_tracker
            
            lang = get_user_language(user_id)
            t = translations[lang]
            
            # Verificar límites
            if "youtube.com" in url or "youtu.be" in url:
                if not await puede_descargar_youtube(user_id):
                    await progress_tracker.safe_edit_message(
                        "❌ Has alcanzado tu límite diario de descargas de YouTube.\n\n"
                        "💎 Conviértete en Premium para descargas ilimitadas de YouTube."
                    )
                    return
            
            await progress_tracker.safe_edit_message(t['analyzing_size'])
            
            # Analizar video
            es_valido, tamano_estimado, titulo, duracion, calidad, formato = await analizar_video_con_detalles(url, user_id, tipo)
            
            if not es_valido:
                if tipo.startswith("tt_"):
                    tamano_mb = tamano_estimado / (1024 * 1024)
                    error_msg = t['video_too_large'].format(tamano_mb)
                    await progress_tracker.safe_edit_message(error_msg)
                return
                
            tamano_mb = tamano_estimado / (1024 * 1024) if tamano_estimado > 0 else 0
            duracion_formateada = format_duration(duracion) if duracion > 0 else "Desconocida"
            
            platform = "YouTube" if "youtube" in url else "TikTok"
            info_msg = f"📊 **Información del {platform}:**\n• Duración: {duracion_formateada}\n• Tamaño estimado: {tamano_mb:.2f}MB\n• Calidad: {calidad}"
            await progress_tracker.safe_edit_message(info_msg)
            await asyncio.sleep(2)
            
            # Descargar
            loop = asyncio.get_event_loop()
            downloader = SafeParallelDownloader(url, user_id, tipo, progress_tracker)
            downloader.estimated_size = tamano_estimado
            
            success = await loop.run_in_executor(executor, downloader.download)
            filename = downloader.filename
            
            if not success or not filename:
                error_msg = t['download_failed'].format(1)
                await progress_tracker.safe_edit_message(error_msg)
                log_event(f"❌ Error al descargar: {url}")
                return
                
            await progress_tracker.safe_edit_message("📤 Preparando para enviar...")
            
            # Enviar archivo
            await self._send_file(user_id, filename, tipo, progress_tracker)
            
            # Actualizar estadísticas
            recompensa = incrementar_descarga(user_id)
            
            if "youtube.com" in url or "youtu.be" in url:
                incrementar_descarga_youtube(user_id)
                
            actualizar_estadisticas(user_id)
            
            # Mostrar menú después de la descarga
            await mostrar_menu_post_descarga(self.app, chat_id, message_id, recompensa)
            
            # Limpiar archivo temporal
            try:
                if filename and os.path.exists(filename):
                    os.remove(filename)
                    log_event(f"🧹 Archivo temporal eliminado: {filename}")
            except Exception as e:
                log_event(f"⚠️ Error eliminando archivo: {e}")
                
        except Exception as e:
            log_event(f"❌ Error procesando tarea: {e}")
            try:
                lang = get_user_language(user_id)
                t = translations[lang]
                await progress_tracker.safe_edit_message(f"❌ Error: {str(e)[:200]}")
            except:
                pass
                
    async def _send_file(self, user_id, filename, tipo, progress_tracker):
        """Envía el archivo al usuario"""
        try:
            file_size = os.path.getsize(filename)
            file_size_mb = file_size / (1024 * 1024)
            
            if file_size > MAX_FILE_SIZE:
                raise Exception(f"Archivo demasiado grande ({file_size_mb:.2f}MB)")
            
            # Simular progreso de envío
            for progress in range(0, 101, 25):
                await progress_tracker.update_upload_progress(progress)
                await asyncio.sleep(0.3)
            
            timeout = 45  # Reducido para Render
            
            if tipo.endswith("video"):
                with open(filename, 'rb') as video_file:
                    await self.app.bot.send_video(
                        chat_id=user_id,
                        video=video_file,
                        caption="✅ ¡Descarga completada!",
                        supports_streaming=True,
                        read_timeout=timeout,
                        write_timeout=timeout,
                        connect_timeout=timeout
                    )
            else:
                with open(filename, 'rb') as audio_file:
                    await self.app.bot.send_audio(
                        chat_id=user_id,
                        audio=audio_file,
                        caption="✅ ¡Descarga completada!",
                        read_timeout=timeout,
                        write_timeout=timeout,
                        connect_timeout=timeout
                    )
                    
            await progress_tracker.update_upload_progress(100)
            log_event(f"✅ Archivo enviado: {filename} ({file_size_mb:.2f}MB)")
            
        except Exception as e:
            log_event(f"❌ Error enviando archivo: {e}")
            raise

download_queue_system = DownloadQueueSystem(max_workers=MAX_WORKERS)

# Estadísticas
stats = {
    "start_time": time.time(),
    "total_downloads": 0,
    "daily_downloads": 0,
    "unique_users": set(),
    "premium_users": 0,
    "active_downloads": 0,
    "completed_today": 0,
    "queue_size": 0,
    "errors": 0,
    "total_rewards": 0.0,
    "total_withdrawals": 0.0,
    "total_referral_earnings": 0.0
}

# Traducciones (mantenemos las mismas)
translations = {
    "es": {
        "welcome": "🌟 ¡Bienvenido al Bot de Descargas más Potente! 🚀",
        "download_options": "🎬 Descarga videos y audio en calidad premium de TikTok y YouTube ✨",
        "select_option": "👇 ¡Elige una opción y comienza a descargar!",
        "download_content": "⬇️ Descargar Contenido",
        "premium": "💎 Premium VIP",
        "referrals": "👥 Programa de Referidos",
        "stats": "📊 Mis Estadísticas",
        "support": "🆘 Soporte Técnico",
        "withdraw": "💰 Retirar Fondos",
        "language": "🌐 Idioma/Language",
        "menu_principal": "🏠 Menú Principal",
        "back": "🔙 Volver",
        "available_downloads": "📊 Descargas disponibles hoy: {}/{}",
        "youtube_downloads": "🎵 Descargas de YouTube hoy: {}/{}",
        "balance_info": "💰 Balance Actual: ${:.2f} USDT",
        "withdraw_minimum": "⚠️ El mínimo para retirar es {} USDT",
        "withdraw_success": "✅ ¡Retiro procesado exitosamente!",
        "withdraw_request": "📋 Solicitud de retiro enviada para revisión",
        "referral_notification": "🎉 ¡Has ganado ${} por referir a un nuevo usuario!",
        "limit_reached": "⛔ ¡Límite Diario Alcanzado!",
        "limit_message": "Has usado tus {} descargas gratuitas de hoy.\n🔓 Obtén descargas ilimitadas:",
        "large_file": "📦 El archivo es grande ({:.2f}MB). ⏳ Esto puede tardar varios minutos...",
        "community": "👥 Unirse a la Comunidad",
        "donate": "❤️ Apoyar con Donación",
        "video_too_large": "❌ **Video demasiado grande**\n\nEste video es de {:.2f}MB y supera el límite de 50MB. ⚠️\n\n💎 Conviértete en Premium para descargar videos de cualquier tamaño.",
        "referral_earnings": "💰 **Ganancias por referidos:** ${:.2f} USDT",
        "processing_queue": "⏳ **Procesando tu solicitud**\n\n{}",
        "queue_position": "📊 Posición en cola: {}",
        "premium_priority": "🚀 Prioridad Premium (procesamiento inmediato)",
        "analyzing": "🔍 **Analizando video...**",
        "downloading": "⬇️ **Descargando... {}%**",
        "uploading": "📤 **Enviando... {}%**",
        "daily_reminder": "📢 **Recordatorio Diario**\n\nTienes {} descargas disponibles hoy!\n\n",
        "error_download": "❌ Error durante la descarga: {}",
        "error_upload": "❌ Error durante el envío: {}",
        "file_too_large": "❌ El archivo es demasiado grande ({:.2f}MB). El límite de Telegram es {:.2f}MB.",
        "try_audio": "💡 Intenta descargar solo el audio o un video de menor calidad.",
        "download_failed": "❌ La descarga falló después de {} intentos.",
        "retrying": "🔄 Reintentando ({}/{})...",
        "download_cancelled": "❌ Descarga cancelada debido a múltiples errores.",
        "analyzing_size": "🔍 **Analizando video...**\n\n📊 Calculando tamaño y duración...",
        "size_info": "📊 **Información del video:**\n• Duración: {}\n• Tamaño estimado: {:.2f}MB\n• Calidad: {}",
        "new_referral": "🎉 **¡Nuevo referido!**\n\n@{} ha usado tu enlace de referido.\n💰 Has ganado ${:.2f} USDT de recompensa!",
        "queue_stalled": "⚠️ **Procesamiento retrasado**\n\nEl sistema está experimentando alta demanda. Tu descarga se reanudará automáticamente.",
        "youtube_premium_only": "❌ **YouTube requiere Premium para video**\n\nPara descargar videos de YouTube necesitas una cuenta Premium. 💎\n\n🎵 Pero puedes descargar el audio MP3 gratis (límite 3 por día)",
        "more_rewards": "🎁 Más Recompensas",
        "youtube_audio_only": "🎵 **Descarga de YouTube**\n\nLos usuarios gratuitos pueden descargar solo audio MP3 de YouTube (límite 3 por día).\n\n💎 Conviértete en Premium para descargar videos completos de YouTube.",
        "enter_tx_hash": "🔍 **Verificación de Pago**\n\nPor favor, envía el **hash de la transacción (TX ID)** de tu pago de 4.99 USDT.\n\nEjemplo: `0x1234567890abcdef...`\n\n⚠️ Asegúrate de que:\n- El monto sea exactamente 4.99 USDT\n- La red sea BSC (BEP-20)\n- La transacción esté confirmada"
    },
    "en": {
        "welcome": "🌟 Welcome to the Most Powerful Download Bot! 🚀",
        "download_options": "🎬 Download premium quality videos and audio from TikTok and YouTube ✨",
        "select_option": "👇 Choose an option and start downloading!",
        "download_content": "⬇️ Download Content",
        "premium": "💎 Premium VIP", 
        "referrals": "👥 Referral Program",
        "stats": "📊 My Statistics",
        "support": "🆘 Technical Support",
        "withdraw": "💰 Withdraw Funds",
        "language": "🌐 Language/Idioma",
        "menu_principal": "🏠 Main Menu",
        "back": "🔙 Back",
        "available_downloads": "📊 Downloads available today: {}/{}",
        "youtube_downloads": "🎵 YouTube downloads today: {}/{}",
        "balance_info": "💰 Current Balance: ${:.2f} USDT",
        "withdraw_minimum": "⚠️ Minimum withdrawal is {} USDT",
        "withdraw_success": "✅ Withdrawal processed successfully!",
        "withdraw_request": "📋 Withdrawal request sent for review",
        "referral_notification": "🎉 You've earned ${} for referring a new user!",
        "limit_reached": "⛔ Daily Limit Reached!",
        "limit_message": "You've used your {} free downloads today.\n🔓 Get unlimited downloads:",
        "large_file": "📦 The file is large ({:.2f}MB). ⏳ This may take several minutes...",
        "community": "👥 Join Community",
        "donate": "❤️ Support with Donation",
        "video_too_large": "❌ **Video too large**\n\nThis video is {:.2f}MB and exceeds the 50MB limit. ⚠️\n\n💎 Become Premium to download videos of any size.",
        "referral_earnings": "💰 **Referral earnings:** ${:.2f} USDT",
        "processing_queue": "⏳ **Processing your request**\n\n{}",
        "queue_position": "📊 Queue position: {}",
        "premium_priority": "🚀 Premium priority (immediate processing)",
        "analyzing": "🔍 **Analyzing video...**",
        "downloading": "⬇️ **Downloading... {}%**",
        "uploading": "📤 **Uploading... {}%**",
        "daily_reminder": "📢 **Daily Reminder**\n\nYou have {} downloads available today!\n\n",
        "error_download": "❌ Error during download: {}",
        "error_upload": "❌ Error during upload: {}",
        "file_too_large": "❌ The file is too large ({:.2f}MB). The Telegram limit is {:.2f}MB.",
        "try_audio": "💡 Try downloading only audio or a lower quality video.",
        "download_failed": "❌ Download failed after {} attempts.",
        "retrying": "🔄 Retrying ({}/{})...",
        "download_cancelled": "❌ Download cancelled due to multiple errors.",
        "analyzing_size": "🔍 **Analyzing video...**\n\n📊 Calculating size and duration...",
        "size_info": "📊 **Video information:**\n• Duration: {}\n• Estimated size: {:.2f}MB\n• Quality: {}",
        "new_referral": "🎉 **New referral!**\n\n@{} used your referral link.\n💰 You earned ${:.2f} USDT reward!",
        "queue_stalled": "⚠️ **Processing delayed**\n\nThe system is experiencing high demand. Your download will resume automatically.",
        "youtube_premium_only": "❌ **YouTube requires Premium for video**\n\nTo download YouTube videos you need a Premium account. 💎\n\n🎵 But you can download MP3 audio for free (limit 3 per day)",
        "more_rewards": "🎁 More Rewards",
        "youtube_audio_only": "🎵 **YouTube Download**\n\nFree users can only download MP3 audio from YouTube (limit 3 per day).\n\n💎 Become Premium to download full YouTube videos.",
        "enter_tx_hash": "🔍 **Payment Verification**\n\nPlease send the **transaction hash (TX ID)** of your 4.99 USDT payment.\n\nExample: `0x1234567890abcdef...`\n\n⚠️ Make sure:\n- Amount is exactly 4.99 USDT\n- Network is BSC (BEP-20)\n- Transaction is confirmed"
    }
}

# Funciones auxiliares (mantener las mismas pero optimizadas)
def print_stats():
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    elapsed_time = time.time() - stats["start_time"]
    hours, remainder = divmod(elapsed_time, 3600)
    minutes, seconds = divmod(remainder, 60)
    
    stats["queue_size"] = download_queue_system.priority_queue.qsize()
    stats["active_downloads"] = len(download_queue_system.active_tasks)
    
    print(f"\n🤖 BOT ACTIVO | {current_time}")
    print("=" * 50)
    print(f"⬇️  DESCARGAS TOTALES: {stats['total_downloads']}")
    print(f"📊 DESCARGAS HOY: {stats['daily_downloads']}")
    print(f"👤 USUARIOS ÚNICOS: {len(stats['unique_users'])}")
    print(f"💎 USUARIOS PREMIUM: {stats['premium_users']}")
    print(f"🚀 DESCARGAS ACTIVAS: {stats['active_downloads']}")
    print(f"⏳ EN COLA: {stats['queue_size']}")
    print(f"✅ COMPLETADAS HOY: {stats['completed_today']}")
    print(f"❌ ERRORES: {stats['errors']}")
    print(f"💰 RECOMPENSAS: ${stats['total_rewards']:.2f}")
    print(f"💸 RETIROS: ${stats['total_withdrawals']:.2f}")
    print(f"👥 GANANCIAS POR REFERIDOS: ${stats['total_referral_earnings']:.2f}")
    print(f"⏱  TIEMPO ACTIVO: {int(hours)}h {int(minutes)}m {int(seconds)}s")
    print("=" * 50)

def log_event(event):
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] {event}")

# ... (mantener todas las funciones auxiliares del código original)
# Solo necesitamos ajustar las que usan recursos intensivos

def conectar_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def crear_tabla():
    conn = conectar_db()
    # ... (mantener igual)
    conn.close()

def es_url_valida(url):
    patterns = [
        r'https?://(www\.)?tiktok\.com/',
        r'https?://vm\.tiktok\.com/',
        r'https?://(www\.)?youtube\.com/',
        r'https?://youtu\.be/'
    ]
    return any(re.match(pattern, url) for pattern in patterns)

# ... (continuar con todas las funciones auxiliares)

# Ajustar la función download del SafeParallelDownloader para usar menos recursos
class SafeParallelDownloader:
    def __init__(self, url, user_id, tipo, progress_tracker):
        self.url = url
        self.user_id = user_id
        self.tipo = tipo
        self.filename = None
        self.video_title = None
        self.estimated_size = 0
        self.priority = 0 if es_premium(user_id) else 1
        self.timestamp = int(time.time())
        self.prefix = "download"
        self.base_filename = f"{self.prefix}_{user_id}_{self.timestamp}"
        self.progress_tracker = progress_tracker
        
    def get_video_info(self):
        try:
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'skip_download': True,
                'forcejson': True,
                'socket_timeout': 30,
                'extract_flat': False
            }
            
            with YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(self.url, download=False)
                self.video_title = info.get('title', 'video')
                self.estimated_size = info.get('filesize', 0) or info.get('filesize_approx', 0)
                return True
        except Exception as e:
            log_event(f"❌ Error obteniendo información del video: {e}")
            self.video_title = None
            self.estimated_size = 0
            return False
            
    def download(self):
        try:
            if not self.get_video_info():
                return False
                
            ydl_opts = self._get_ydl_options()
            
            ydl_opts['progress_hooks'] = [self._progress_hook]
            
            # Configuración optimizada para Render
            ydl_opts['socket_timeout'] = 45
            ydl_opts['retries'] = 2
            ydl_opts['fragment_retries'] = 2
            ydl_opts['extract_flat'] = False
            
            with YoutubeDL(ydl_opts) as ydl:
                ydl.download([self.url])
            
            # Buscar archivo descargado
            for file in os.listdir('.'):
                if file.startswith(self.base_filename):
                    self.filename = file
                    
                    if self.video_title:
                        file_ext = os.path.splitext(file)[1]
                        safe_title = sanitize_filename(self.video_title)
                        new_filename = f"{safe_title}{file_ext}"
                        
                        counter = 1
                        original_new_filename = new_filename
                        while os.path.exists(new_filename):
                            new_filename = f"{os.path.splitext(original_new_filename)[0]}_{counter}{file_ext}"
                            counter += 1
                            
                        os.rename(file, new_filename)
                        self.filename = new_filename
                    
                    file_size = os.path.getsize(self.filename)
                    if file_size > MAX_FILE_SIZE:
                        os.remove(self.filename)
                        raise Exception(f"El archivo es demasiado grande ({file_size/1024/1024:.2f}MB)")
                        
                    return True
            return False
        except Exception as e:
            log_event(f"❌ Error en descarga: {e}")
            stats["errors"] += 1
            return False
            
    def _progress_hook(self, d):
        if d['status'] == 'downloading':
            total = d.get('total_bytes', 0)
            downloaded = d.get('downloaded_bytes', 0)
            if total and downloaded:
                progress = int((downloaded / total) * 100)
                if progress % 10 == 0:  # Actualizar cada 10% para reducir carga
                    try:
                        asyncio.run(self.progress_tracker.update_download_progress(progress))
                    except RuntimeError:
                        pass  # Ignorar si el event loop está cerrado
        
    def _get_ydl_options(self):
        base_opts = {
            'outtmpl': self.base_filename + '.%(ext)s',
            'noprogress': True,
            'socket_timeout': 45,
            'retries': 2,
            'fragment_retries': 2,
            'concurrent_fragment_downloads': 4,  # Reducido para Render
            'http_chunk_size': 2 * 1024 * 1024,  # Reducido
            'abort_on_unavailable_fragment': True,
            'quiet': True,
        }
        
        if self.tipo == "tt_video":
            return {**base_opts, 'format': 'best[filesize<50000000]'}  # Limitado a 50MB
        elif self.tipo == "tt_audio":
            return {
                **base_opts,
                'format': 'bestaudio[filesize<30000000]/bestaudio',
                'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3'}]
            }
        elif self.tipo == "yt_audio":
            return {
                **base_opts,
                'format': 'bestaudio[filesize<30000000]/bestaudio',
                'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3'}]
            }
        elif self.tipo == "yt_video":
            return {**base_opts, 'format': 'best[filesize<100000000]'}  # Limitado a 100MB
        else:
            return {**base_opts, 'format': 'best[filesize<50000000]'}

# Mantener todas las demás funciones iguales...

# Función main optimizada
def main():
    crear_tabla()
    
    stats["start_time"] = time.time()
    print_stats()
    log_event("🤖 Iniciando bot de descargas en Render...")
    
    # Verificar variables de entorno
    if not BOT_TOKEN:
        log_event("❌ ERROR: BOT_TOKEN no configurado")
        sys.exit(1)
    
    application = ApplicationBuilder().token(BOT_TOKEN).build()
    
    # Handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stats", admin_stats))
    application.add_handler(CommandHandler("withdraw", withdraw_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, procesar_descarga))
    application.add_handler(CallbackQueryHandler(callback_handler))
    
    application.add_error_handler(error_handler)
    
    # Iniciar sistema de colas
    start_background_tasks(application)
    
    log_event("🚀 Bot en ejecución en Render...")
    
    try:
        application.run_polling()
    except KeyboardInterrupt:
        log_event("🛑 Bot detenido por el usuario")
    except Exception as e:
        log_event(f"❌ Error crítico: {e}")
    finally:
        executor.shutdown(wait=False)

if __name__ == "__main__":
    main()

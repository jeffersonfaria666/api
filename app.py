import os
import sys
import time
import sqlite3
import requests
import random
import asyncio
import re
import aiohttp
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
MAX_WORKERS = 2
MAX_FRAGMENTS = 8
CHUNK_SIZE = 5 * 1024 * 1024
MAX_FILE_SIZE = 500 * 1024 * 1024

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
YOUTUBE_DAILY_LIMIT = 3
MIN_WITHDRAWAL = 50

# Almacenamiento temporal
download_jobs = {}
executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)
current_downloads = {}
progress_trackers = {}

# Sistema de colas simplificado
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
        self.aiohttp_session = None
        
    async def init_session(self):
        """Inicializar sesión aiohttp"""
        self.aiohttp_session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=45)
        )
        
    async def close_session(self):
        """Cerrar sesión aiohttp"""
        if self.aiohttp_session:
            await self.aiohttp_session.close()
        
    def set_application(self, app):
        self.app = app
        
    async def start(self):
        """Inicia los workers de la cola"""
        await self.init_session()
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
        await self.close_session()
        
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
            
            # Analizar video usando aiohttp para mayor eficiencia
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
            downloader = SafeParallelDownloader(url, user_id, tipo, progress_tracker, self.aiohttp_session)
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
            
            timeout = 45
            
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

# Traducciones
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

# Funciones auxiliares
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

# Database functions
def conectar_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def crear_tabla():
    conn = conectar_db()
    cursor = conn.cursor()
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS usuarios (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        last_name TEXT,
        descargas_hoy INTEGER DEFAULT 0,
        descargas_total INTEGER DEFAULT 0,
        balance REAL DEFAULT 0.0,
        premium INTEGER DEFAULT 0,
        premium_expires TEXT,
        referral_code TEXT UNIQUE,
        referred_by INTEGER,
        youtube_downloads INTEGER DEFAULT 0,
        last_reset TEXT,
        language TEXT DEFAULT 'es',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS transacciones (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        amount REAL,
        tx_hash TEXT,
        status TEXT DEFAULT 'pending',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS recompensas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        amount REAL,
        type TEXT,
        referral_id INTEGER,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    conn.commit()
    conn.close()
    log_event("✅ Base de datos inicializada")

def es_url_valida(url):
    patterns = [
        r'https?://(www\.)?tiktok\.com/',
        r'https?://vm\.tiktok\.com/',
        r'https?://(www\.)?youtube\.com/',
        r'https?://youtu\.be/'
    ]
    return any(re.match(pattern, url) for pattern in patterns)

# Funciones de usuario
def registrar_usuario(user_id, username, first_name, last_name):
    conn = conectar_db()
    cursor = conn.cursor()
    
    cursor.execute('''
    INSERT OR IGNORE INTO usuarios 
    (user_id, username, first_name, last_name, referral_code, created_at)
    VALUES (?, ?, ?, ?, ?, ?)
    ''', (user_id, username, first_name, last_name, f"REF{user_id}", datetime.now().isoformat()))
    
    conn.commit()
    conn.close()

def get_usuario(user_id):
    conn = conectar_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM usuarios WHERE user_id = ?', (user_id,))
    usuario = cursor.fetchone()
    conn.close()
    return usuario

def actualizar_estadisticas(user_id):
    conn = conectar_db()
    cursor = conn.cursor()
    
    usuario = get_usuario(user_id)
    if usuario:
        hoy = datetime.now().date().isoformat()
        if usuario['last_reset'] != hoy:
            cursor.execute('UPDATE usuarios SET descargas_hoy = 0, youtube_downloads = 0, last_reset = ? WHERE user_id = ?',
                          (hoy, user_id))
    
    conn.commit()
    conn.close()

def es_premium(user_id):
    usuario = get_usuario(user_id)
    if not usuario:
        return False
    
    if usuario['premium'] == 1:
        if usuario['premium_expires']:
            try:
                expires = datetime.fromisoformat(usuario['premium_expires'])
                return expires > datetime.now()
            except:
                return False
        return True
    return False

def puede_descargar(user_id):
    usuario = get_usuario(user_id)
    if not usuario:
        return True
    
    hoy = datetime.now().date().isoformat()
    if usuario['last_reset'] != hoy:
        return True
    
    if es_premium(user_id):
        return True
    
    return usuario['descargas_hoy'] < LIMIT_POR_DIA

def puede_descargar_youtube(user_id):
    if es_premium(user_id):
        return True
    
    usuario = get_usuario(user_id)
    if not usuario:
        return True
    
    hoy = datetime.now().date().isoformat()
    if usuario['last_reset'] != hoy:
        return True
    
    return usuario['youtube_downloads'] < YOUTUBE_DAILY_LIMIT

def incrementar_descarga(user_id):
    usuario = get_usuario(user_id)
    if not usuario:
        return 0
    
    conn = conectar_db()
    cursor = conn.cursor()
    
    hoy = datetime.now().date().isoformat()
    if usuario['last_reset'] != hoy:
        cursor.execute('UPDATE usuarios SET descargas_hoy = 1, descargas_total = descargas_total + 1, last_reset = ? WHERE user_id = ?',
                      (hoy, user_id))
    else:
        cursor.execute('UPDATE usuarios SET descargas_hoy = descargas_hoy + 1, descargas_total = descargas_total + 1 WHERE user_id = ?',
                      (user_id,))
    
    # Asignar recompensa aleatoria
    recompensa = round(random.uniform(REWARD_PER_DOWNLOAD_MIN, REWARD_PER_DOWNLOAD_MAX), 2)
    cursor.execute('UPDATE usuarios SET balance = balance + ? WHERE user_id = ?',
                  (recompensa, user_id))
    
    # Registrar recompensa
    cursor.execute('INSERT INTO recompensas (user_id, amount, type) VALUES (?, ?, ?)',
                  (user_id, recompensa, 'download'))
    
    conn.commit()
    conn.close()
    
    stats["total_downloads"] += 1
    stats["daily_downloads"] += 1
    stats["total_rewards"] += recompensa
    
    return recompensa

def incrementar_descarga_youtube(user_id):
    conn = conectar_db()
    cursor = conn.cursor()
    cursor.execute('UPDATE usuarios SET youtube_downloads = youtube_downloads + 1 WHERE user_id = ?',
                  (user_id,))
    conn.commit()
    conn.close()

def get_user_language(user_id):
    usuario = get_usuario(user_id)
    return usuario['language'] if usuario and usuario['language'] else 'es'

# Funciones de descarga
async def analizar_video_con_detalles(url, user_id, tipo):
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
            info = ydl.extract_info(url, download=False)
            
            titulo = info.get('title', 'Video')
            duracion = info.get('duration', 0)
            
            # Determinar tamaño estimado
            tamano_estimado = 0
            calidad = "Desconocida"
            formato = "Desconocido"
            
            if 'formats' in info:
                for f in info['formats']:
                    if f.get('filesize'):
                        tamano_estimado = max(tamano_estimado, f['filesize'])
                        if f.get('height'):
                            calidad = f"{f['height']}p"
                        if f.get('ext'):
                            formato = f['ext']
            
            # Si no hay tamaño en los formatos, estimar
            if tamano_estimado == 0 and duracion > 0:
                # Estimación aproximada: 1 minuto ≈ 10MB para 720p
                tamano_estimado = (duracion / 60) * 10 * 1024 * 1024
            
            # Verificar límites para usuarios no premium
            if tipo.startswith("tt_") and not es_premium(user_id):
                if tamano_estimado > MAX_TT_SIZE_NON_PREMIUM:
                    return False, tamano_estimado, titulo, duracion, calidad, formato
            
            return True, tamano_estimado, titulo, duracion, calidad, formato
            
    except Exception as e:
        log_event(f"❌ Error analizando video: {e}")
        return False, 0, "", 0, "", ""

def format_duration(seconds):
    if seconds <= 0:
        return "0:00"
    
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    else:
        return f"{minutes}:{secs:02d}"

def sanitize_filename(filename):
    # Remover caracteres no válidos para nombres de archivo
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        filename = filename.replace(char, '_')
    
    # Limitar longitud
    if len(filename) > 100:
        name, ext = os.path.splitext(filename)
        filename = name[:100 - len(ext)] + ext
    
    return filename

# Clase para seguimiento de progreso
class SafeProgressTracker:
    def __init__(self, chat_id, message_id, user_id, app):
        self.chat_id = chat_id
        self.message_id = message_id
        self.user_id = user_id
        self.app = app
        self.last_update = time.time()
        self.update_interval = 2.0  # Segundos entre actualizaciones
        
    async def safe_edit_message(self, text, parse_mode='Markdown'):
        try:
            current_time = time.time()
            if current_time - self.last_update < self.update_interval:
                return
                
            await self.app.bot.edit_message_text(
                chat_id=self.chat_id,
                message_id=self.message_id,
                text=text,
                parse_mode=parse_mode
            )
            self.last_update = current_time
        except Exception as e:
            log_event(f"⚠️ Error editando mensaje: {e}")
    
    async def update_download_progress(self, progress):
        lang = get_user_language(self.user_id)
        t = translations[lang]
        await self.safe_edit_message(t['downloading'].format(progress))
    
    async def update_upload_progress(self, progress):
        lang = get_user_language(self.user_id)
        t = translations[lang]
        await self.safe_edit_message(t['uploading'].format(progress))

# Clase mejorada para descargas paralelas
class SafeParallelDownloader:
    def __init__(self, url, user_id, tipo, progress_tracker, aiohttp_session=None):
        self.url = url
        self.user_id = user_id
        self.tipo = tipo
        self.filename = None
        self.video_title = None
        self.estimated_size = 0
        self.progress_tracker = progress_tracker
        self.aiohttp_session = aiohttp_session
        self.prefix = "download"
        self.base_filename = f"{self.prefix}_{user_id}_{int(time.time())}"
        
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
                if progress % 10 == 0:  # Actualizar cada 10%
                    try:
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        loop.run_until_complete(self.progress_tracker.update_download_progress(progress))
                        loop.close()
                    except:
                        pass
        
    def _get_ydl_options(self):
        base_opts = {
            'outtmpl': self.base_filename + '.%(ext)s',
            'noprogress': True,
            'socket_timeout': 45,
            'retries': 2,
            'fragment_retries': 2,
            'concurrent_fragment_downloads': 4,
            'http_chunk_size': 2 * 1024 * 1024,
            'abort_on_unavailable_fragment': True,
            'quiet': True,
        }
        
        if self.tipo == "tt_video":
            return {**base_opts, 'format': 'best[filesize<50000000]'}
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
            return {**base_opts, 'format': 'best[filesize<100000000]'}
        else:
            return {**base_opts, 'format': 'best[filesize<50000000]'}

# Funciones del bot
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username
    first_name = update.effective_user.first_name
    last_name = update.effective_user.last_name
    
    registrar_usuario(user_id, username, first_name, last_name)
    
    lang = get_user_language(user_id)
    t = translations[lang]
    
    keyboard = [
        [InlineKeyboardButton(t['download_content'], callback_data='download_content')],
        [InlineKeyboardButton(t['premium'], callback_data='premium'),
         InlineKeyboardButton(t['referrals'], callback_data='referrals')],
        [InlineKeyboardButton(t['stats'], callback_data='stats'),
         InlineKeyboardButton(t['support'], callback_data='support')],
        [InlineKeyboardButton(t['withdraw'], callback_data='withdraw'),
         InlineKeyboardButton(t['language'], callback_data='language')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"{t['welcome']}\n\n{t['download_options']}\n\n{t['select_option']}",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Solo administradores pueden usar este comando.")
        return
    
    print_stats()
    
    stats_text = f"""
📊 **ESTADÍSTICAS DEL BOT**
━━━━━━━━━━━━━━━━
• Total descargas: {stats['total_downloads']}
• Descargas hoy: {stats['daily_downloads']}
• Usuarios únicos: {len(stats['unique_users'])}
• Usuarios premium: {stats['premium_users']}
• Descargas activas: {stats['active_downloads']}
• En cola: {stats['queue_size']}
• Errores: {stats['errors']}
• Total recompensas: ${stats['total_rewards']:.2f}
• Total retiros: ${stats['total_withdrawals']:.2f}
━━━━━━━━━━━━━━━━
"""
    await update.message.reply_text(stats_text, parse_mode='Markdown')

async def withdraw_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    usuario = get_usuario(user_id)
    
    if not usuario:
        await update.message.reply_text("❌ Primero debes usar /start")
        return
    
    lang = get_user_language(user_id)
    t = translations[lang]
    
    if usuario['balance'] < MIN_WITHDRAWAL:
        await update.message.reply_text(
            t['withdraw_minimum'].format(MIN_WITHDRAWAL) + f"\n\n💰 Tu balance actual: ${usuario['balance']:.2f} USDT"
        )
        return
    
    await update.message.reply_text(
        f"💰 **RETIRO DE FONDOS**\n\n"
        f"• Balance disponible: ${usuario['balance']:.2f} USDT\n"
        f"• Mínimo para retirar: ${MIN_WITHDRAWAL} USDT\n\n"
        f"⚠️ Por favor, envía la dirección de tu wallet BSC (BEP-20) donde deseas recibir los USDT."
    )

async def procesar_descarga(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    url = update.message.text.strip()
    
    if not es_url_valida(url):
        await update.message.reply_text("❌ URL no válida. Envía un enlace de TikTok o YouTube.")
        return
    
    lang = get_user_language(user_id)
    t = translations[lang]
    
    # Verificar si puede descargar
    if not puede_descargar(user_id):
        await update.message.reply_text(
            t['limit_reached'] + "\n\n" + t['limit_message'].format(LIMIT_POR_DIA) +
            "\n\n💎 /premium - Para descargas ilimitadas"
        )
        return
    
    # Determinar tipo de descarga
    if "tiktok.com" in url or "vm.tiktok.com" in url:
        tipo_options = [
            [InlineKeyboardButton("🎬 Video TikTok", callback_data=f"tt_video:{url}")],
            [InlineKeyboardButton("🎵 Audio TikTok (MP3)", callback_data=f"tt_audio:{url}")]
        ]
    elif "youtube.com" in url or "youtu.be" in url:
        if es_premium(user_id):
            tipo_options = [
                [InlineKeyboardButton("🎬 Video YouTube", callback_data=f"yt_video:{url}")],
                [InlineKeyboardButton("🎵 Audio YouTube (MP3)", callback_data=f"yt_audio:{url}")]
            ]
        else:
            await update.message.reply_text(t['youtube_audio_only'])
            tipo_options = [
                [InlineKeyboardButton("🎵 Audio YouTube (MP3)", callback_data=f"yt_audio:{url}")]
            ]
    else:
        await update.message.reply_text("❌ Plataforma no soportada. Solo TikTok y YouTube.")
        return
    
    reply_markup = InlineKeyboardMarkup(tipo_options)
    await update.message.reply_text("🎬 **Selecciona el tipo de descarga:**", reply_markup=reply_markup)

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    callback_data = query.data
    chat_id = query.message.chat_id
    message_id = query.message.message_id
    
    lang = get_user_language(user_id)
    t = translations[lang]
    
    if callback_data == 'download_content':
        await query.edit_message_text(
            "🎬 **Descargar Contenido**\n\n"
            "Envía el enlace del video que quieres descargar:\n"
            "• TikTok: https://tiktok.com/...\n"
            "• YouTube: https://youtube.com/...\n\n"
            "⚠️ Límite de 50MB para usuarios gratuitos"
        )
    
    elif callback_data == 'premium':
        keyboard = [
            [InlineKeyboardButton("💎 Comprar Premium", callback_data='buy_premium')],
            [InlineKeyboardButton("🔙 Volver", callback_data='menu_principal')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "💎 **PREMIUM VIP**\n\n"
            "✨ **Beneficios exclusivos:**\n"
            "• ✅ Descargas ILIMITADAS todos los días\n"
            "• ✅ Videos de cualquier tamaño (sin límite de 50MB)\n"
            "• ✅ Descargas de YouTube en video (no solo audio)\n"
            "• ✅ Prioridad en la cola de descargas\n"
            "• ✅ Sin anuncios ni restricciones\n\n"
            "💰 **Precio:** $4.99 USDT (pago único, vida útil)\n\n"
            "🔗 **Red:** BSC (BEP-20)\n"
            f"📍 **Wallet:** `{USDT_ADDRESS}`\n\n"
            "⚠️ Después de pagar, envía el hash de la transacción para activar tu premium.",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    elif callback_data.startswith(('tt_', 'yt_')):
        tipo, url = callback_data.split(':', 1)
        
        # Verificar límites
        if not puede_descargar(user_id):
            await query.edit_message_text(t['limit_reached'])
            return
        
        # Verificar límites de YouTube para usuarios gratuitos
        if tipo.startswith('yt_') and tipo.endswith('video') and not es_premium(user_id):
            await query.edit_message_text(t['youtube_premium_only'])
            return
        
        # Mostrar mensaje de procesamiento
        usuario = get_usuario(user_id)
        priority = 0 if es_premium(user_id) else 1
        
        if priority == 0:
            queue_msg = t['premium_priority']
        else:
            queue_position = download_queue_system.priority_queue.qsize() + 1
            queue_msg = t['queue_position'].format(queue_position)
        
        await query.edit_message_text(
            f"⏳ **Procesando tu solicitud...**\n\n"
            f"{queue_msg}\n\n"
            f"📊 Descargas disponibles hoy: {LIMIT_POR_DIA - usuario['descargas_hoy']}/{LIMIT_POR_DIA}\n"
            f"💰 Balance actual: ${usuario['balance']:.2f} USDT"
        )
        
        # Añadir a la cola
        job_id = await download_queue_system.add_task(priority, (f"job_{user_id}_{int(time.time())}", user_id, url, tipo, chat_id, message_id))
        
    elif callback_data == 'stats':
        usuario = get_usuario(user_id)
        hoy = datetime.now().date().isoformat()
        
        if usuario['last_reset'] != hoy:
            descargas_hoy = 0
            youtube_hoy = 0
        else:
            descargas_hoy = usuario['descargas_hoy']
            youtube_hoy = usuario['youtube_downloads']
        
        stats_text = f"""
📊 **TUS ESTADÍSTICAS**
━━━━━━━━━━━━━━━━
👤 Usuario: @{usuario['username'] or usuario['first_name']}
💰 Balance: ${usuario['balance']:.2f} USDT
💎 Premium: {'✅' if es_premium(user_id) else '❌'}
━━━━━━━━━━━━━━━━
⬇️ Descargas hoy: {descargas_hoy}/{LIMIT_POR_DIA}
🎵 YouTube hoy: {youtube_hoy}/{YOUTUBE_DAILY_LIMIT}
📈 Total descargas: {usuario['descargas_total']}
━━━━━━━━━━━━━━━━
"""
        keyboard = [
            [InlineKeyboardButton(t['menu_principal'], callback_data='menu_principal')],
            [InlineKeyboardButton("🎁 Reclamar Recompensas", url=RECOMPENSAS_URL)]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(stats_text, reply_markup=reply_markup)
    
    elif callback_data == 'referrals':
        usuario = get_usuario(user_id)
        referral_code = usuario['referral_code'] or f"REF{user_id}"
        referral_link = f"https://t.me/{(await context.bot.get_me()).username}?start={referral_code}"
        
        keyboard = [
            [InlineKeyboardButton("🔗 Copiar enlace de referido", callback_data='copy_referral')],
            [InlineKeyboardButton("👥 Ver referidos", callback_data='view_referrals')],
            [InlineKeyboardButton(t['menu_principal'], callback_data='menu_principal')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"👥 **PROGRAMA DE REFERIDOS**\n\n"
            f"💰 **Gana ${REFERRAL_REWARD} USDT por cada amigo que invites!**\n\n"
            f"🔗 **Tu enlace único:**\n`{referral_link}`\n\n"
            f"**Cómo funciona:**\n"
            f"1. Comparte tu enlace con amigos\n"
            f"2. Cuando usen tu enlace y descarguen su primer video\n"
            f"3. ¡Recibes ${REFERRAL_REWARD} USDT en tu balance!\n\n"
            f"⚠️ El referido también recibe ${REFERRAL_REWARD/2:.2f} USDT de bonificación.",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    elif callback_data == 'support':
        keyboard = [
            [InlineKeyboardButton(t['community'], url=COMUNIDAD_URL)],
            [InlineKeyboardButton(t['donate'], url=DONACION_URL)],
            [InlineKeyboardButton(t['menu_principal'], callback_data='menu_principal')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "🆘 **SOPORTE TÉCNICO**\n\n"
            "¿Tienes problemas con el bot?\n\n"
            "**Soluciones rápidas:**\n"
            "• Si no descarga: Verifica que el enlace sea público\n"
            "• Si es muy lento: Puede ser por alta demanda\n"
            "• Si no envía: El archivo puede ser muy grande (>500MB)\n\n"
            "**Para más ayuda:**",
            reply_markup=reply_markup
        )
    
    elif callback_data == 'withdraw':
        await withdraw_command(update, context)
    
    elif callback_data == 'language':
        keyboard = [
            [InlineKeyboardButton("🇪🇸 Español", callback_data='set_lang_es')],
            [InlineKeyboardButton("🇺🇸 English", callback_data='set_lang_en')],
            [InlineKeyboardButton(t['back'], callback_data='menu_principal')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "🌐 **IDIOMA / LANGUAGE**\n\n"
            "Selecciona tu idioma preferido:",
            reply_markup=reply_markup
        )
    
    elif callback_data.startswith('set_lang_'):
        lang_code = callback_data.split('_')[-1]
        
        conn = conectar_db()
        cursor = conn.cursor()
        cursor.execute('UPDATE usuarios SET language = ? WHERE user_id = ?', (lang_code, user_id))
        conn.commit()
        conn.close()
        
        t = translations[lang_code]
        await callback_handler(update, context)  # Recargar menú principal con nuevo idioma
    
    elif callback_data == 'menu_principal':
        keyboard = [
            [InlineKeyboardButton(t['download_content'], callback_data='download_content')],
            [InlineKeyboardButton(t['premium'], callback_data='premium'),
             InlineKeyboardButton(t['referrals'], callback_data='referrals')],
            [InlineKeyboardButton(t['stats'], callback_data='stats'),
             InlineKeyboardButton(t['support'], callback_data='support')],
            [InlineKeyboardButton(t['withdraw'], callback_data='withdraw'),
             InlineKeyboardButton(t['language'], callback_data='language')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"{t['welcome']}\n\n{t['download_options']}\n\n{t['select_option']}",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_event(f"❌ Error: {context.error}")
    stats["errors"] += 1
    
    try:
        if update and update.effective_user:
            await context.bot.send_message(
                chat_id=update.effective_user.id,
                text="❌ Ocurrió un error. Por favor, intenta de nuevo más tarde."
            )
    except:
        pass

async def mostrar_menu_post_descarga(app, chat_id, message_id, recompensa):
    try:
        user_id = chat_id
        lang = get_user_language(user_id)
        t = translations[lang]
        
        usuario = get_usuario(user_id)
        
        keyboard = [
            [InlineKeyboardButton("⬇️ Descargar otro video", callback_data='download_content')],
            [InlineKeyboardButton("📊 Ver estadísticas", callback_data='stats'),
             InlineKeyboardButton("💎 Premium", callback_data='premium')],
            [InlineKeyboardButton("👥 Invitar amigos", callback_data='referrals'),
             InlineKeyboardButton("🏠 Menú principal", callback_data='menu_principal')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await app.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=f"✅ **¡Descarga completada!**\n\n"
                 f"💰 Has ganado **${recompensa:.2f} USDT** por esta descarga.\n\n"
                 f"📊 **Resumen:**\n"
                 f"• Descargas hoy: {usuario['descargas_hoy']}/{LIMIT_POR_DIA}\n"
                 f"• Balance total: ${usuario['balance']:.2f} USDT\n\n"
                 f"¿Qué quieres hacer ahora?",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    except Exception as e:
        log_event(f"❌ Error mostrando menú post-descarga: {e}")

async def start_background_tasks(application):
    """Iniciar tareas en segundo plano"""
    download_queue_system.set_application(application)
    await download_queue_system.start()
    log_event("✅ Tareas en segundo plano iniciadas")

def main():
    crear_tabla()
    
    stats["start_time"] = time.time()
    print_stats()
    log_event("🤖 Iniciando bot de descargas...")
    
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
    
    # Iniciar sistema de colas en segundo plano
    loop = asyncio.get_event_loop()
    loop.create_task(start_background_tasks(application))
    
    log_event("🚀 Bot en ejecución...")
    
    try:
        application.run_polling()
    except KeyboardInterrupt:
        log_event("🛑 Bot detenido por el usuario")
    except Exception as e:
        log_event(f"❌ Error crítico: {e}")
    finally:
        executor.shutdown(wait=False)
        loop.run_until_complete(download_queue_system.stop())

if __name__ == "__main__":
    main()

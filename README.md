# 🚀 YouTube Server API

API completa para obtener información y enlaces de descarga de videos de YouTube, lista para desplegar en Render.com.

## 🌟 Características

- ✅ **API RESTful completa** con autenticación por API Key
- ✅ **Rate limiting** para prevenir abusos
- ✅ **CORS configurado** para uso desde navegadores
- ✅ **Logging completo** para debugging
- ✅ **Múltiples formatos** de video y audio
- ✅ **Health checks** para monitoreo
- ✅ **Documentación automática** de endpoints
- ✅ **Optimizado para Render.com** con configuración lista

## 🚀 Despliegue en Render.com

### Método 1: One-Click Deploy

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy)

### Método 2: Despliegue Manual

1. **Crear cuenta en [Render.com](https://render.com)**
2. **Crear nuevo Web Service**
3. **Conectar tu repositorio de GitHub**
4. **Configurar el servicio:**
   - **Nombre:** `youtube-server` (o el que prefieras)
   - **Runtime:** `Python 3`
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --threads 4`
   - **Plan:** `Free` (para empezar)

5. **Agregar variables de entorno:**
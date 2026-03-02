# Panel Arbitraje IOL - Deploy 24/7

Esta app puede correrse como servicio web con:

```bash
panel serve app.py
```

La entrada principal para deploy es `app.py`.

## Deploy automático en Render (recomendado)

1. Hacer push de este repo a GitHub.
2. En Render: **New +** → **Web Service**.
3. Conectar el repositorio GitHub.
4. Configurar:
   - **Environment**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `./start.sh`
5. Variables de entorno recomendadas:
   - `PYTHON_VERSION=3.11.9` (opcional)
   - `IOL_USER` (opcional, autocompleta usuario)
   - `IOL_PASS` (opcional, autocompleta password)
6. Crear el servicio y deployar.
7. Cada push a la rama configurada en GitHub dispara auto-deploy.

### WebSocket / Origin en Render

`start.sh` usa:

- `--address 0.0.0.0`
- `--port ${PORT:-10000}`
- `--allow-websocket-origin=${RENDER_EXTERNAL_HOSTNAME:-*}`

Con eso, en Render toma el hostname público automáticamente y si no existe, usa `*` como fallback.

## Alternativa: Fly.io con Docker

1. Instalar Fly CLI y autenticar:
   ```bash
   fly auth login
   ```
2. Desde la raíz del repo:
   ```bash
   fly launch --no-deploy
   ```
3. Validar `fly.toml` (si hace falta):
   - `internal_port = 8080`
4. Deploy:
   ```bash
   fly deploy
   ```

El `Dockerfile` ya corre:

```bash
panel serve app.py --address 0.0.0.0 --port 8080 --num-procs 1 --allow-websocket-origin="*"
```

## Variables de entorno opcionales

- `IOL_USER`
- `IOL_PASS`

Si se definen, solo precargan los widgets de login. El login manual sigue funcionando igual.

## Troubleshooting rápido

- Error `403` o `websocket connection failed`:
  - Verificar `--allow-websocket-origin`.
  - En Render, confirmar que `RENDER_EXTERNAL_HOSTNAME` exista en runtime.
- La app no levanta:
  - Verificar que el proceso escuche `0.0.0.0` y el `PORT` del host.
- Deploy falla en build:
  - Revisar versiones de Python y `requirements.txt`.
- Pantalla cargando infinito:
  - Revisar logs de Render/Fly por errores de import o auth a IOL.
- Login no persiste tras expirar token:
  - La app reintenta login con credenciales cargadas en widgets/env vars.

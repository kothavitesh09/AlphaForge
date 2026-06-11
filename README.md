# AlphaForge

AlphaForge is an AI-powered crypto market intelligence and paper trading platform.

## Prerequisites

- Python 3.12
- Node.js LTS
- MongoDB Community Server

## Environment Files

The local environment files are:

```powershell
backend\.env
frontend\.env
```

Backend local values:

```env
MONGODB_URI=mongodb://localhost:27017/alphaforge
JWT_SECRET=alphaforge-local-dev-secret-change-before-deployment
KOINBX_BASE_URL=https://api.koinbx.com
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
ALLOWED_ORIGINS=http://localhost:3000
```

Frontend local values:

```env
NEXT_PUBLIC_API_URL=http://localhost:8000/api
```

## Run Complete Project

Open PowerShell in the project root:

```powershell
cd "C:\Users\Kotha Vitesh\Desktop\AlphaForge"
```

### 1. Start MongoDB

```powershell
Get-Service MongoDB
Start-Service MongoDB
```

### 2. Install Backend Dependencies

```powershell
cd backend
python -m pip install -r requirements.txt
```

### 3. Start Backend

```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Backend URLs:

```text
http://127.0.0.1:8000
http://127.0.0.1:8000/health
http://127.0.0.1:8000/api/dashboard
```

### 4. Install Frontend Dependencies

Open a second PowerShell terminal:

```powershell
cd "C:\Users\Kotha Vitesh\Desktop\AlphaForge\frontend"
$env:PATH = "C:\Program Files\nodejs;$env:PATH"
npm install
```

### 5. Build Frontend

```powershell
npm run build
```

### 6. Start Frontend

```powershell
npm run start
```

Frontend URL:

```text
http://localhost:3000/dashboard
```

## Development Mode

Backend:

```powershell
cd "C:\Users\Kotha Vitesh\Desktop\AlphaForge\backend"
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Frontend:

```powershell
cd "C:\Users\Kotha Vitesh\Desktop\AlphaForge\frontend"
$env:PATH = "C:\Program Files\nodejs;$env:PATH"
npm run dev
```

## Run In Background

Backend:

```powershell
Start-Process -FilePath python -ArgumentList @('-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8000') -WorkingDirectory "C:\Users\Kotha Vitesh\Desktop\AlphaForge\backend" -RedirectStandardOutput "C:\Users\Kotha Vitesh\Desktop\AlphaForge\backend\backend.out.log" -RedirectStandardError "C:\Users\Kotha Vitesh\Desktop\AlphaForge\backend\backend.err.log" -WindowStyle Hidden
```

Frontend:

```powershell
Start-Process -FilePath cmd.exe -ArgumentList @('/c','set "PATH=C:\Program Files\nodejs;%PATH%" && "C:\Program Files\nodejs\npm.cmd" start') -WorkingDirectory "C:\Users\Kotha Vitesh\Desktop\AlphaForge\frontend" -RedirectStandardOutput "C:\Users\Kotha Vitesh\Desktop\AlphaForge\frontend\frontend.out.log" -RedirectStandardError "C:\Users\Kotha Vitesh\Desktop\AlphaForge\frontend\frontend.err.log" -WindowStyle Hidden
```

## Stop Running Servers

List processes:

```powershell
Get-Process python -ErrorAction SilentlyContinue
Get-Process node -ErrorAction SilentlyContinue
```

Stop by PID:

```powershell
Stop-Process -Id <PID> -Force
```

## Verification Commands

Backend syntax:

```powershell
cd "C:\Users\Kotha Vitesh\Desktop\AlphaForge"
python -B -c "import pathlib; [compile(p.read_text(), str(p), 'exec') for p in pathlib.Path('backend/app').rglob('*.py')]; print('backend syntax ok')"
```

Frontend build:

```powershell
cd "C:\Users\Kotha Vitesh\Desktop\AlphaForge\frontend"
$env:PATH = "C:\Program Files\nodejs;$env:PATH"
npm run build
```

API health:

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/health
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/api/dashboard
```

Frontend check:

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:3000/dashboard
```

## Main API Endpoints

```text
POST /api/auth/register
POST /api/auth/login
GET  /api/dashboard
GET  /api/coins
GET  /api/coins/{symbol}
GET  /api/signals
GET  /api/signals/{symbol}
POST /api/signals/evaluate
GET  /api/predictions
GET  /api/predictions/{symbol}
POST /api/paper-trade/buy
POST /api/paper-trade/sell
GET  /api/paper-trade/portfolio
```


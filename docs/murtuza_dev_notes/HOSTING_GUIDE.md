# Local Network Hosting Guide

> Host the backend API and frontend web app on your Ubuntu PC so every device on the same Wi-Fi / LAN can access them.

---

## Architecture

```
Your Ubuntu PC (server)
├── Docker  →  PostgreSQL :5432  +  Redis :6379
├── Java    →  Spring Boot API   :8080
└── Node    →  React Web App     :3000

Other PCs / phones on same network
└── Browser → http://<UBUNTU_IP>:3000   (web app)
                             ↓ API calls
            → http://<UBUNTU_IP>:8080   (backend)
```

---

## Step 0 — Find Your Ubuntu PC's Local IP

Run on your Ubuntu PC:

```bash
ip addr show | grep "inet " | grep -v 127.0.0.1
```

Example output:
```
inet 192.168.1.105/24 brd 192.168.1.255 scope global eth0
```

**Your IP is `192.168.1.105`** (yours will be different).  
Use this IP everywhere you see `<UBUNTU_IP>` in this guide.

You can also try:
```bash
hostname -I | awk '{print $1}'
```

---

## Step 1 — Start PostgreSQL and Redis (Docker)

The backend needs PostgreSQL and Redis. Run them via Docker.

### 1a — Create the docker-compose file

Navigate to the backend folder:

```bash
cd /path/to/new_ai_hospital_claude/backend/hos-backend
```

Create `docker-compose.yml`:

```bash
cat > docker-compose.yml << 'EOF'
version: '3.8'

services:
  postgres:
    image: postgres:15-alpine
    container_name: hos-postgres
    restart: unless-stopped
    environment:
      POSTGRES_DB: hos_db
      POSTGRES_USER: hos_user
      POSTGRES_PASSWORD: hos_password
    ports:
      - "5432:5432"
    volumes:
      - hos_postgres_data:/var/lib/postgresql/data

  redis:
    image: redis:7-alpine
    container_name: hos-redis
    restart: unless-stopped
    ports:
      - "6379:6379"
    volumes:
      - hos_redis_data:/data

volumes:
  hos_postgres_data:
  hos_redis_data:
EOF
```

### 1b — Start the containers

```bash
docker compose up -d
```

### 1c — Verify they are running

```bash
docker compose ps
```

Expected output:
```
NAME           STATUS
hos-postgres   running
hos-redis      running
```

Test PostgreSQL connection:
```bash
docker exec -it hos-postgres psql -U hos_user -d hos_db -c "SELECT 1;"
```

---

## Step 2 — Build and Run the Backend

### 2a — Navigate to the backend

```bash
cd /path/to/new_ai_hospital_claude/backend/hos-backend
```

### 2b — Build the JAR (skip tests for speed)

```bash
./mvnw clean package -DskipTests
```

This creates: `hos-app/target/hos-app-*.jar`

> **First run takes 2–5 minutes** to download Maven dependencies.  
> Subsequent builds are much faster.

### 2c — Run the backend

```bash
java -jar hos-app/target/hos-app-*.jar \
  --spring.profiles.active=dev \
  --server.address=0.0.0.0
```

**`--server.address=0.0.0.0`** makes the API accessible from all network interfaces (not just localhost).

### 2d — Verify the backend is running

Wait for this line in the logs:
```
Started HosApplication in X.XXX seconds
```

Then test from the Ubuntu PC itself:
```bash
curl http://localhost:8080/v3/api-docs | head -5
```

Test from **another PC** on the same network:
```bash
curl http://192.168.1.105:8080/v3/api-docs | head -5
```

You should get a JSON response. If you do, the backend is accessible on the network.

> **Swagger UI** is available at: `http://<UBUNTU_IP>:8080/swagger-ui.html`

---

## Step 3 — Build and Serve the Frontend

The frontend env variables are **baked in at build time** by Vite.  
You must build with your Ubuntu PC's IP — not `localhost` — or API calls will fail on other devices.

### 3a — Navigate to the frontend

```bash
cd /path/to/new_ai_hospital_claude/frontend/hospital-os-web
```

### 3b — Create a local network env file

```bash
cat > .env.local << EOF
VITE_API_BASE_URL=http://192.168.1.105:8080/api/v1
VITE_WS_URL=http://192.168.1.105:8080/ws
VITE_TENANT_ID=1
EOF
```

> Replace `192.168.1.105` with your actual Ubuntu IP from Step 0.  
> `.env.local` overrides `.env` and is gitignored by default.

### 3c — Install dependencies (first time only)

```bash
npm install
```

### 3d — Build the production bundle

```bash
npm run build
```

This creates the `dist/` folder with the compiled web app.

### 3e — Install a static file server

```bash
npm install -g serve
```

### 3f — Serve the built app

```bash
serve -s dist -l 3000
```

### 3g — Verify the frontend is accessible

From your Ubuntu PC:
```
http://localhost:3000
```

From **another PC** on the same network:
```
http://192.168.1.105:3000
```

You should see the Hospital OS login screen.

---

## Step 4 — Open Firewall Ports

If Ubuntu's firewall (`ufw`) is active, open the ports:

```bash
# Check if ufw is active
sudo ufw status

# If active, open the required ports
sudo ufw allow 8080/tcp comment "HOS Backend API"
sudo ufw allow 3000/tcp comment "HOS Frontend"

# Verify
sudo ufw status
```

---

## Step 5 — Test Everything End-to-End

From any device on the same network:

1. Open browser → `http://192.168.1.105:3000`
2. Login with admin credentials (e.g. `admin@greenfield.com` / `Admin@123`)
3. Verify the dashboard loads and data appears

**If the UI loads but API calls fail:**
- Open browser DevTools → Console/Network
- Look for failed requests — they should go to `192.168.1.105:8080`
- If they go to `localhost:8080`, your `.env.local` wasn't picked up → re-run `npm run build`

---

## Access URLs Summary

| Service | URL from Ubuntu | URL from other PCs |
|---------|----------------|-------------------|
| Web App | `http://localhost:3000` | `http://192.168.1.105:3000` |
| API | `http://localhost:8080/api/v1` | `http://192.168.1.105:8080/api/v1` |
| Swagger UI | `http://localhost:8080/swagger-ui.html` | `http://192.168.1.105:8080/swagger-ui.html` |
| PostgreSQL | `localhost:5432` | *(internal only)* |
| Redis | `localhost:6379` | *(internal only)* |

---

## Convenience Scripts

Save these to the project root for easy start/stop.

### `start-all.sh` — Start everything

```bash
cat > /path/to/new_ai_hospital_claude/start-all.sh << 'SCRIPT'
#!/bin/bash
set -e

UBUNTU_IP=$(hostname -I | awk '{print $1}')
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$PROJECT_DIR/backend/hos-backend"
FRONTEND_DIR="$PROJECT_DIR/frontend/hospital-os-web"

echo "========================================"
echo "  HOS — Local Network Startup"
echo "  Server IP: $UBUNTU_IP"
echo "========================================"

# 1. Start Docker services
echo ""
echo "[1/4] Starting PostgreSQL and Redis..."
cd "$BACKEND_DIR"
docker compose up -d
echo "      Done."

# 2. Wait for Postgres to be ready
echo "[2/4] Waiting for PostgreSQL to be ready..."
until docker exec hos-postgres pg_isready -U hos_user -d hos_db -q; do
  sleep 1
done
echo "      PostgreSQL is ready."

# 3. Start backend in background
echo "[3/4] Starting Spring Boot backend..."
cd "$BACKEND_DIR"
BUILD_JAR=$(ls hos-app/target/hos-app-*.jar 2>/dev/null | head -1)
if [ -z "$BUILD_JAR" ]; then
  echo "      No JAR found — building first (this may take a few minutes)..."
  ./mvnw clean package -DskipTests -q
  BUILD_JAR=$(ls hos-app/target/hos-app-*.jar | head -1)
fi
nohup java -jar "$BUILD_JAR" \
  --spring.profiles.active=dev \
  --server.address=0.0.0.0 \
  > /tmp/hos-backend.log 2>&1 &
echo $! > /tmp/hos-backend.pid
echo "      Backend PID: $(cat /tmp/hos-backend.pid)"
echo "      Logs: /tmp/hos-backend.log"

# 4. Build and serve frontend
echo "[4/4] Building frontend for $UBUNTU_IP..."
cd "$FRONTEND_DIR"
cat > .env.local << EOF
VITE_API_BASE_URL=http://$UBUNTU_IP:8080/api/v1
VITE_WS_URL=http://$UBUNTU_IP:8080/ws
VITE_TENANT_ID=1
EOF
npm run build --silent
nohup serve -s dist -l 3000 > /tmp/hos-frontend.log 2>&1 &
echo $! > /tmp/hos-frontend.pid
echo "      Frontend PID: $(cat /tmp/hos-frontend.pid)"
echo "      Logs: /tmp/hos-frontend.log"

echo ""
echo "========================================"
echo "  All services started!"
echo ""
echo "  Web App : http://$UBUNTU_IP:3000"
echo "  API     : http://$UBUNTU_IP:8080/api/v1"
echo "  Swagger : http://$UBUNTU_IP:8080/swagger-ui.html"
echo ""
echo "  Waiting for backend to finish starting..."
echo "  (watch logs: tail -f /tmp/hos-backend.log)"
echo "========================================"
SCRIPT

chmod +x /path/to/new_ai_hospital_claude/start-all.sh
```

### `stop-all.sh` — Stop everything

```bash
cat > /path/to/new_ai_hospital_claude/stop-all.sh << 'SCRIPT'
#!/bin/bash
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "Stopping HOS services..."

# Stop frontend
if [ -f /tmp/hos-frontend.pid ]; then
  kill $(cat /tmp/hos-frontend.pid) 2>/dev/null && echo "Frontend stopped."
  rm /tmp/hos-frontend.pid
fi

# Stop backend
if [ -f /tmp/hos-backend.pid ]; then
  kill $(cat /tmp/hos-backend.pid) 2>/dev/null && echo "Backend stopped."
  rm /tmp/hos-backend.pid
fi

# Stop Docker containers
cd "$PROJECT_DIR/backend/hos-backend"
docker compose stop
echo "PostgreSQL and Redis stopped."

echo "Done."
SCRIPT

chmod +x /path/to/new_ai_hospital_claude/stop-all.sh
```

> **Update `/path/to/new_ai_hospital_claude`** in both scripts to your actual project path.

---

## Optional — Auto-Start on Boot (systemd)

If you want the services to start automatically when Ubuntu boots:

### Backend service

```bash
sudo tee /etc/systemd/system/hos-backend.service > /dev/null << 'EOF'
[Unit]
Description=HOS Spring Boot Backend
After=network.target docker.service
Requires=docker.service

[Service]
Type=simple
User=mr
WorkingDirectory=/home/mr/workspace/ai_hospital_operating_system/backend/hos-backend

# Wait for postgres to be ready before starting Spring Boot
# ExecStartPre=/bin/bash -c 'until docker exec hos_postgres pg_isready -U hos_user -d hos_db -q; do sleep 1; done'

# Use bash -c because systemd does NOT expand globs (*.jar)
ExecStart=/bin/bash -c 'exec java -jar /home/mr/workspace/ai_hospital_operating_system/backend/hos-backend/hos-app/target/hos-app-*.jar --spring.profiles.active=dev --server.address=0.0.0.0'

Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl restart hos-backend
sudo systemctl status hos-backend
```

sudo journalctl -u hos-backend -f

### Frontend service

```bash
# Get the real paths first
SERVE_PATH=$(su - mr -c 'which serve')
NODE_BIN=$(su - mr -c 'dirname $(which node)')
echo "serve: $SERVE_PATH"
echo "node bin: $NODE_BIN"

# Now create the service with correct path
sudo tee /etc/systemd/system/hos-frontend.service > /dev/null << EOF
[Unit]
Description=HOS React Frontend
After=network.target

[Service]
Type=simple
User=mr
WorkingDirectory=/home/mr/workspace/ai_hospital_operating_system/frontend/hospital-os-web

# Add nvm node bin to PATH so systemd can find serve
Environment="PATH=$NODE_BIN:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

ExecStart=$SERVE_PATH -s dist -l 3000
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl restart hos-frontend
sudo systemctl status hos-frontend
```

---

## Troubleshooting

### Backend won't start

```bash
# Check backend logs
tail -100 /tmp/hos-backend.log

# Common causes:
# 1. PostgreSQL not ready yet — wait 10–15 seconds and retry
# 2. Port 8080 already in use
sudo lsof -i :8080
# Kill whatever is on port 8080
sudo kill $(sudo lsof -t -i:8080)
```

### Can't access from other PCs

```bash
# Check if backend is listening on 0.0.0.0 (not just 127.0.0.1)
sudo ss -tlnp | grep 8080
# Should show: 0.0.0.0:8080  not  127.0.0.1:8080

# Check firewall
sudo ufw status

# Try pinging the Ubuntu PC from the other device first
ping 192.168.1.105
```

### Frontend shows API errors on other devices

The most common cause: frontend was built with `localhost` in the API URL.

```bash
# Check what URL is baked into the bundle
grep -r "localhost:8080" dist/assets/*.js | head -3

# If found, re-build with correct IP
cat > frontend/hospital-os-web/.env.local << EOF
VITE_API_BASE_URL=http://192.168.1.105:8080/api/v1
VITE_WS_URL=http://192.168.1.105:8080/ws
VITE_TENANT_ID=1
EOF

cd frontend/hospital-os-web
npm run build
serve -s dist -l 3000
```

### Database connection failed

```bash
# Check containers are running
docker compose ps

# Check postgres logs
docker logs hos-postgres

# Test connection manually
docker exec -it hos-postgres psql -U hos_user -d hos_db -c "\dt"
```

### Port 3000 or 8080 blocked

```bash
# Open ports in ufw
sudo ufw allow 8080/tcp
sudo ufw allow 3000/tcp
sudo ufw reload

# Or disable ufw temporarily to test
sudo ufw disable
```

### Check what's using a port

```bash
sudo lsof -i :8080
sudo lsof -i :3000
sudo lsof -i :5432
```

---

## Quick Reference — Manual Commands

```bash
# ---- Docker (PostgreSQL + Redis) ----
cd backend/hos-backend
docker compose up -d          # start
docker compose stop           # stop (keeps data)
docker compose down           # stop and remove containers
docker compose down -v        # stop and DELETE ALL DATA

# ---- Backend ----
cd backend/hos-backend
./mvnw clean package -DskipTests                       # build JAR
java -jar hos-app/target/hos-app-*.jar \
  --spring.profiles.active=dev \
  --server.address=0.0.0.0                             # run
tail -f /tmp/hos-backend.log                           # watch logs

# ---- Frontend ----
cd frontend/hospital-os-web
npm run build                  # build (uses .env.local)
serve -s dist -l 3000          # serve built files
# OR for dev mode (no build needed, but hot-reload):
npm run dev -- --host          # dev server accessible on network

# ---- Useful checks ----
ip addr show                   # find Ubuntu IP
docker compose ps              # check Docker containers
sudo ss -tlnp | grep 8080      # check backend port
sudo ufw status                # check firewall
```

---

## Notes

- **IP changes on router restart**: If your router assigns a new IP to the Ubuntu PC, update `.env.local` and rebuild the frontend. To avoid this, assign a **static IP** to the Ubuntu PC in your router's DHCP settings.
- **Dev mode vs built mode**: `npm run dev -- --host` is faster (no build step, hot-reload), but uses `.env` not `.env.local`. `npm run build` + `serve` is what other devices will reliably access.
- **Seed data login**: See `phase-1-docs/sample_data.md` for default credentials from the V12 seed migration.
- **Swagger UI**: Once the backend is running, the full interactive API docs are at `http://<UBUNTU_IP>:8080/swagger-ui.html` — useful for testing individual endpoints from any browser.

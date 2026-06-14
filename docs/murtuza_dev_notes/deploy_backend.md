[Unit]
Description=HOS Backend — AI Hospital Operating System
After=network.target postgresql.service redis.service

[Service]
Type=simple
User=deploy
WorkingDirectory=/home/deploy/hos-backend

# ── Secrets ───────────────────────────────────────────────────────────────────
Environment="SPRING_PROFILES_ACTIVE=dev"
Environment="SPRING_DATASOURCE_PASSWORD=DbPassword123!"
Environment="SPRING_DATA_REDIS_PASSWORD=RedisPassword123!"
Environment="APP_JWT_SECRET=747af99b98442bcf01ba604f0f996a8625268c0a2bf0e4e75e45d10f36e1c216"
Environment="APP_API_KEY=dev-api-key-replace-in-production"

# ── Silence debug logging (env var names — underscores only, no hyphens) ──────
Environment="LOGGING_LEVEL_COM_CALLUSSOFT=INFO"
Environment="LOGGING_LEVEL_ORG_HIBERNATE_SQL=WARN"
Environment="LOGGING_LEVEL_ORG_HIBERNATE_ORM_JDBC_BIND=WARN"
Environment="LOGGING_LEVEL_ORG_SPRINGFRAMEWORK_SECURITY=WARN"

# ── JVM + Spring Boot CLI args ─────────────────────────────────────────────────
ExecStart=/usr/bin/java \
  -Xms256m -Xmx512m \
  -XX:+UseG1GC -XX:MaxGCPauseMillis=200 \
  -XX:+HeapDumpOnOutOfMemoryError \
  -XX:HeapDumpPath=/home/deploy/hos-backend/heapdump.hprof \
  -jar /home/deploy/hos-backend/hos-app-0.0.1-SNAPSHOT.jar \
  --server.port=8080 \
  --server.address=127.0.0.1 \
  --spring.jpa.show-sql=false \
  --app.logging.request-response=true \
  --app.notification.retry-delay-ms=86400000 \
  --app.notification.reminder-cron=- \
  --app.followup.outbound-trigger-url=https://c843-144-48-109-174.ngrok-free.app/api/outbound/trigger \
  --app.followup.outbound-trigger-api-key=your-strong-random-key-here \
  --app.followup.scheduler-fixed-delay-ms=60000 \
  --app.outbound-queue.engine-context-status-url=https://c843-144-48-109-174.ngrok-free.app/outbound/context-status \
  --app.outbound-queue.engine-health-token=your-health-api-token-here

Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=hos-backend

[Install]
WantedBy=multi-user.target
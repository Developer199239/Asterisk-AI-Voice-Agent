# Makefile for the Asterisk AI Voice Agent

# Default values - can be overridden from the command line
SERVER_USER := root
SERVER_HOST := voiprnd.nemtclouddispatch.com
PROJECT_PATH := /root/Asterisk-Agent-Develop
SERVICE ?= ai-engine

# ==============================================================================
# LOCAL DEVELOPMENT
# ==============================================================================

## build: Build or rebuild all service images
build:
	docker-compose build

## up: Start all services in the background
up:
	docker-compose up -d

## down: Stop and remove all services
down:
	docker-compose down --remove-orphans

## logs: Tail the logs of a specific service (default: ai-engine)
logs:
	docker-compose logs -f $(SERVICE)

## logs-all: Tail the logs of all services
logs-all:
	docker-compose logs -f

## ps: Show the status of running services
ps:
	docker-compose ps

# ==============================================================================
# DEPLOYMENT & SERVER MANAGEMENT
# ==============================================================================

## deploy: Pull latest code and deploy the ai-engine on the server
deploy:
	@echo "--> Deploying latest code to $(SERVER_HOST)..."
	ssh $(SERVER_USER)@$(SERVER_HOST) 'cd $(PROJECT_PATH) && git pull && docker-compose up --build -d ai-engine'

## deploy-full: Pull latest and rebuild all services on the server
deploy-full:
	@echo "--> Performing a full rebuild and deployment on $(SERVER_HOST)..."
	ssh $(SERVER_USER)@$(SERVER_HOST) 'cd $(PROJECT_PATH) && git pull && docker-compose up --build -d'

## deploy-force: Pull latest and force a no-cache rebuild of ai-engine
deploy-force:
	@echo "--> Forcing a no-cache rebuild and deployment of ai-engine on $(SERVER_HOST)..."
	ssh $(SERVER_USER)@$(SERVER_HOST) 'cd $(PROJECT_PATH) && git pull && docker-compose build --no-cache ai-engine && docker-compose up -d ai-engine'

## server-logs: View live logs for a service on the server (follow mode - use Ctrl+C to exit)
server-logs:
	ssh $(SERVER_USER)@$(SERVER_HOST) 'cd $(PROJECT_PATH) && docker-compose logs -f $(SERVICE)'

## server-logs-snapshot: View last N lines of logs and exit (default: 50)
server-logs-snapshot:
	ssh $(SERVER_USER)@$(SERVER_HOST) 'cd $(PROJECT_PATH) && docker-compose logs --tail=$(LINES) $(SERVICE)'

## server-status: Check the status of services on the server
server-status:
	ssh $(SERVER_USER)@$(SERVER_HOST) 'cd $(PROJECT_PATH) && docker-compose ps'

## server-clear-logs: Clear logs before testing
server-clear-logs:
	@echo "--> Clearing logs on $(SERVER_HOST)..."
	ssh $(SERVER_USER)@$(SERVER_HOST) 'cd $(PROJECT_PATH) && docker-compose logs --tail=0 ai-engine && docker-compose logs --tail=0 local-ai-server'

## server-health: Check deployment health (ARI, AudioSocket, Providers)
server-health:
	@echo "--> Checking deployment health on $(SERVER_HOST)..."
	ssh $(SERVER_USER)@$(SERVER_HOST) 'cd $(PROJECT_PATH) && docker-compose logs --tail=50 ai-engine | grep -E "(Successfully connected|AudioSocket server listening|Provider.*loaded|Engine started)"'

# ==============================================================================
# TESTING & VERIFICATION
# ==============================================================================

## test-local: Run local tests
test-local:
	docker-compose exec ai-engine python /app/test_ai_engine.py
	docker-compose exec local-ai-server python /app/test_local_ai_server.py

## test-integration: Run integration tests
test-integration:
	docker-compose exec ai-engine python /app/test_integration.py

## test-ari: Test ARI commands
test-ari:
	ssh $(SERVER_USER)@$(SERVER_HOST) 'cd $(PROJECT_PATH) && docker-compose exec ai-engine python /app/test_ari_commands.py'

## test-externalmedia: Test ExternalMedia + RTP implementation
test-externalmedia:
	@echo "--> Testing ExternalMedia + RTP implementation..."
	python3 scripts/validate_externalmedia_config.py
	python3 scripts/test_externalmedia_call.py

## monitor-externalmedia: Monitor ExternalMedia + RTP status
monitor-externalmedia:
	@echo "--> Starting ExternalMedia + RTP monitoring..."
	python3 scripts/monitor_externalmedia.py

## monitor-externalmedia-once: Check ExternalMedia + RTP status once
monitor-externalmedia-once:
	@echo "--> Checking ExternalMedia + RTP status..."
	python3 scripts/monitor_externalmedia.py --once

## capture-logs: Capture structured logs during test call (default: 40 seconds)
capture-logs:
	@echo "--> Starting structured log capture for test call..."
	@echo "📞 Make your test call now!"
	python3 scripts/capture_test_logs.py --duration 40

## capture-logs-short: Capture logs for 30 seconds
capture-logs-short:
	@echo "--> Starting 30-second log capture..."
	@echo "📞 Make your test call now!"
	python3 scripts/capture_test_logs.py --duration 30

## capture-logs-long: Capture logs for 60 seconds
capture-logs-long:
	@echo "--> Starting 60-second log capture..."
	@echo "📞 Make your test call now!"
	python3 scripts/capture_test_logs.py --duration 60

## analyze-logs: Analyze the most recent captured logs
analyze-logs:
	@echo "--> Analyzing most recent test call logs..."
	@if [ -d "logs" ] && [ "$$(ls -A logs/*.json 2>/dev/null)" ]; then \
		LATEST_LOG=$$(ls -t logs/*.json | head -1); \
		echo "📊 Analyzing: $$LATEST_LOG"; \
		python3 scripts/analyze_logs.py "$$LATEST_LOG"; \
	else \
		echo "❌ No log files found in logs/ directory"; \
	fi

## test-call: Complete test call workflow (capture + analyze)
test-call:
	@echo "--> Starting complete test call workflow..."
	@echo "📞 Make your test call now!"
	@echo "⏱️  Capturing logs for 40 seconds..."
	python3 scripts/capture_test_logs.py --duration 40
	@echo "🔍 Analyzing captured logs..."
	@if [ -d "logs" ] && [ "$$(ls -A logs/*.json 2>/dev/null)" ]; then \
		LATEST_LOG=$$(ls -t logs/*.json | head -1); \
		LATEST_FRAMEWORK=$$(ls -t logs/*.md | head -1); \
		echo "📊 Analysis complete!"; \
		echo "📁 JSON logs: $$LATEST_LOG"; \
		echo "📋 Framework analysis: $$LATEST_FRAMEWORK"; \
		echo "🔍 View framework analysis:"; \
		echo "   cat $$LATEST_FRAMEWORK"; \
	fi

# ==============================================================================
# UTILITIES & HELP
# ==============================================================================

## help: Show this help message
help:
	@echo "Usage: make [target]"
	@echo ""
	@echo "Targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

.PHONY: build up down logs logs-all ps deploy deploy-full deploy-force server-logs server-logs-snapshot server-status server-clear-logs server-health test-local test-integration test-ari test-externalmedia monitor-externalmedia monitor-externalmedia-once help

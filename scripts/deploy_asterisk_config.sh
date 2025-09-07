#!/bin/bash

# Asterisk Configuration Deployment Script
# For Asterisk AI Voice Agent v2.0

set -e

echo "🚀 Deploying Asterisk Configuration for AI Voice Agent v2.0..."

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "❌ Please run as root (use sudo)"
    exit 1
fi

# Check if Asterisk is installed
if ! command -v asterisk &> /dev/null; then
    echo "❌ Asterisk is not installed. Please install Asterisk first."
    exit 1
fi

# Backup existing configuration
echo "📦 Backing up existing configuration..."
mkdir -p /etc/asterisk/backup-$(date +%Y%m%d-%H%M%S)
BACKUP_DIR="/etc/asterisk/backup-$(date +%Y%m%d-%H%M%S)"

if [ -f "/etc/asterisk/ari.conf" ]; then
    cp /etc/asterisk/ari.conf "$BACKUP_DIR/"
    echo "✅ Backed up ari.conf"
fi

if [ -f "/etc/asterisk/http.conf" ]; then
    cp /etc/asterisk/http.conf "$BACKUP_DIR/"
    echo "✅ Backed up http.conf"
fi

if [ -f "/etc/asterisk/extensions.conf" ]; then
    cp /etc/asterisk/extensions.conf "$BACKUP_DIR/"
    echo "✅ Backed up extensions.conf"
fi

if [ -f "/etc/asterisk/pjsip.conf" ]; then
    cp /etc/asterisk/pjsip.conf "$BACKUP_DIR/"
    echo "✅ Backed up pjsip.conf"
fi

# Copy new configuration files
echo "📋 Copying new configuration files..."

if [ -f "asterisk_config/ari.conf" ]; then
    cp asterisk_config/ari.conf /etc/asterisk/
    chown asterisk:asterisk /etc/asterisk/ari.conf
    chmod 640 /etc/asterisk/ari.conf
    echo "✅ Installed ari.conf"
else
    echo "❌ ari.conf not found in asterisk_config/"
    exit 1
fi

if [ -f "asterisk_config/http.conf" ]; then
    cp asterisk_config/http.conf /etc/asterisk/
    chown asterisk:asterisk /etc/asterisk/http.conf
    chmod 640 /etc/asterisk/http.conf
    echo "✅ Installed http.conf"
else
    echo "❌ http.conf not found in asterisk_config/"
    exit 1
fi

if [ -f "asterisk_config/extensions.conf" ]; then
    cp asterisk_config/extensions.conf /etc/asterisk/
    chown asterisk:asterisk /etc/asterisk/extensions.conf
    chmod 640 /etc/asterisk/extensions.conf
    echo "✅ Installed extensions.conf"
else
    echo "❌ extensions.conf not found in asterisk_config/"
    exit 1
fi

if [ -f "asterisk_config/pjsip.conf" ]; then
    cp asterisk_config/pjsip.conf /etc/asterisk/
    chown asterisk:asterisk /etc/asterisk/pjsip.conf
    chmod 640 /etc/asterisk/pjsip.conf
    echo "✅ Installed pjsip.conf"
else
    echo "❌ pjsip.conf not found in asterisk_config/"
    exit 1
fi

# Check Asterisk configuration
echo "🔍 Checking Asterisk configuration..."
if asterisk -rx "core show version" > /dev/null 2>&1; then
    echo "✅ Asterisk is running"
else
    echo "❌ Asterisk is not running. Please start Asterisk first."
    exit 1
fi

# Reload configuration
echo "🔄 Reloading Asterisk configuration..."
asterisk -rx "core reload" > /dev/null 2>&1
if [ $? -eq 0 ]; then
    echo "✅ Configuration reloaded successfully"
else
    echo "❌ Failed to reload configuration. Check Asterisk logs."
    exit 1
fi

# Verify ARI is working
echo "🧪 Testing ARI configuration..."
if asterisk -rx "ari show applications" > /dev/null 2>&1; then
    echo "✅ ARI is working"
else
    echo "❌ ARI is not working. Check configuration."
    exit 1
fi

# Test HTTP interface
echo "🌐 Testing HTTP interface..."
if curl -s -u aiagent:c4d5359e2f9ddd394cd6aa116c1c6a96 http://localhost:8088/ari/asterisk/info > /dev/null 2>&1; then
    echo "✅ HTTP interface is working"
else
    echo "❌ HTTP interface is not working. Check http.conf and ari.conf"
    exit 1
fi

# Test PJSIP configuration
echo "📞 Testing PJSIP configuration..."
if asterisk -rx "pjsip show endpoints" > /dev/null 2>&1; then
    echo "✅ PJSIP is working"
else
    echo "❌ PJSIP is not working. Check pjsip.conf"
    exit 1
fi

echo ""
echo "🎉 Asterisk configuration deployed successfully!"
echo ""
echo "📋 Configuration Summary:"
echo "   - ARI enabled on port 8088"
echo "   - ARI user: aiagent"
echo "   - ARI password: c4d5359e2f9ddd394cd6aa116c1c6a96"
echo "   - Test extension: 3000"
echo "   - Stasis app: asterisk-ai-voice-agent"
echo ""
echo "🧪 Test the configuration:"
echo "   curl -u aiagent:c4d5359e2f9ddd394cd6aa116c1c6a96 http://localhost:8088/ari/asterisk/info"
echo ""
echo "📁 Backup location: $BACKUP_DIR"
echo ""
echo "✅ Ready for AI Voice Agent v2.0 deployment!"

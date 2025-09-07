# Asterisk Configuration for AI Voice Agent v2.0

This directory contains the updated Asterisk configuration files for the ARI-based AI Voice Agent v2.0.

## Configuration Files

### ari.conf
- Enables ARI (Asterisk REST Interface)
- Configures ARI user `aiagent` with password `c4d5359e2f9ddd394cd6aa116c1c6a96`
- Sets up CORS for web access
- Enables pretty JSON formatting

### http.conf
- Enables HTTP interface on port 8088
- Configures CORS headers for ARI access
- Enables static file serving

### extensions.conf
- Routes incoming calls to Stasis application `asterisk-ai-voice-agent`
- Provides test extension 3000 for direct AI agent access
- Includes contexts for inbound and outbound calls

### pjsip.conf
- Configures PJSIP transport (UDP/TCP on port 5060)
- Sets up AI agent endpoint for testing
- Includes example trunk configuration for external calls

## Installation Instructions

1. **Backup existing configuration:**
   ```bash
   cp /etc/asterisk/ari.conf /etc/asterisk/ari.conf.backup
   cp /etc/asterisk/http.conf /etc/asterisk/http.conf.backup
   cp /etc/asterisk/extensions.conf /etc/asterisk/extensions.conf.backup
   cp /etc/asterisk/pjsip.conf /etc/asterisk/pjsip.conf.backup
   ```

2. **Copy new configuration files:**
   ```bash
   cp asterisk_config/ari.conf /etc/asterisk/
   cp asterisk_config/http.conf /etc/asterisk/
   cp asterisk_config/extensions.conf /etc/asterisk/
   cp asterisk_config/pjsip.conf /etc/asterisk/
   ```

3. **Set proper permissions:**
   ```bash
   chown asterisk:asterisk /etc/asterisk/ari.conf
   chown asterisk:asterisk /etc/asterisk/http.conf
   chown asterisk:asterisk /etc/asterisk/extensions.conf
   chown asterisk:asterisk /etc/asterisk/pjsip.conf
   chmod 640 /etc/asterisk/*.conf
   ```

4. **Reload Asterisk configuration:**
   ```bash
   asterisk -rx "core reload"
   ```

5. **Verify ARI is working:**
   ```bash
   asterisk -rx "ari show applications"
   curl -u aiagent:c4d5359e2f9ddd394cd6aa116c1c6a96 http://localhost:8088/ari/asterisk/info
   ```

## Required Asterisk Modules

Ensure these modules are loaded:
- `res_ari` - ARI core module
- `res_stasis` - Stasis application framework
- `res_http_websocket` - WebSocket support for ARI
- `res_pjsip` - PJSIP stack
- `res_pjsip_session` - PJSIP session management

## Security Considerations

1. **ARI Access Control:**
   - Change default passwords in production
   - Use strong, unique passwords
   - Consider IP-based access restrictions

2. **Network Security:**
   - Use firewall rules to restrict ARI access
   - Consider VPN for remote access
   - Enable TLS for ARI if needed

3. **Authentication:**
   - Use strong passwords for ARI users
   - Regularly rotate credentials
   - Monitor ARI access logs

## Testing the Configuration

1. **Test ARI connection:**
   ```bash
   curl -u aiagent:c4d5359e2f9ddd394cd6aa116c1c6a96 http://localhost:8088/ari/asterisk/info
   ```

2. **Test WebSocket connection:**
   ```bash
   wscat -c "ws://localhost:8088/ari/events?api_key=aiagent:c4d5359e2f9ddd394cd6aa116c1c6a96&app=asterisk-ai-voice-agent"
   ```

3. **Test call routing:**
   - Make a test call to extension 3000
   - Verify the call enters the Stasis application
   - Check Asterisk logs for ARI events

## Migration from v1.0 (SIP-based)

The main changes from v1.0 to v2.0:

1. **Architecture Change:**
   - v1.0: Direct SIP client acting as phone endpoint
   - v2.0: ARI-based call control with media proxy

2. **Configuration Changes:**
   - Added ARI configuration
   - Updated dialplan to use Stasis application
   - Removed direct SIP client configuration

3. **Call Flow:**
   - v1.0: Call → SIP Client → AI Processing
   - v2.0: Call → Asterisk → Stasis App → ARI → AI Services

## Troubleshooting

### Common Issues

1. **ARI not accessible:**
   - Check if `res_ari` module is loaded
   - Verify HTTP interface is enabled
   - Check firewall settings

2. **Stasis application not found:**
   - Ensure `res_stasis` module is loaded
   - Check dialplan configuration
   - Verify application name matches

3. **WebSocket connection fails:**
   - Check `res_http_websocket` module
   - Verify CORS settings
   - Check network connectivity

### Logs to Check

- `/var/log/asterisk/full` - General Asterisk logs
- `/var/log/asterisk/ari` - ARI-specific logs
- `/var/log/asterisk/pjsip` - PJSIP logs

### Debug Commands

```bash
# Check loaded modules
asterisk -rx "module show like ari"
asterisk -rx "module show like stasis"

# Check ARI status
asterisk -rx "ari show applications"
asterisk -rx "ari show users"

# Check PJSIP status
asterisk -rx "pjsip show endpoints"
asterisk -rx "pjsip show transports"

# Test dialplan
asterisk -rx "dialplan show ai-agent-inbound"
```

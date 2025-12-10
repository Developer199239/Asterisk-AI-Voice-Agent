---
description: Deploy and test on the live server
---
1. Push changes to git develop branch
   ```bash
   git status
   git add .
   git commit -m "Update Admin UI: Dynamic Models, ElevenLabs Support, Config Warnings"
   git push origin develop
   ```

2. Login to server and deploy
   ```bash
   ssh root@voiprnd.nemtclouddispatch.com "cd /root/Asterisk-AI-Voice-Agent && git pull && docker compose up -d --force-recreate admin-ui"
   ```

3. Verify container status on server
   ```bash
   ssh root@voiprnd.nemtclouddispatch.com "docker ps | grep admin-ui"
   ```

4. Access UI and verify
   - URL: http://voiprnd.nemtclouddispatch.com:3003
   - Credentials: admin / admin2025
   - Verify: 
     - "Providers > Add Local" shows dynamic models
     - "ElevenLabs" provider shows Agent/TTS modes
     - "Configuration" page shows warning on save

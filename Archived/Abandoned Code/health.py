"""
Health Check Endpoint for Call Controller Service
"""

from aiohttp import web
import asyncio
import logging

logger = logging.getLogger(__name__)

async def health_check(request):
    """Health check endpoint"""
    return web.json_response({
        "status": "healthy",
        "service": "call_controller",
        "timestamp": asyncio.get_event_loop().time()
    })

def create_health_app():
    """Create health check web application"""
    app = web.Application()
    app.router.add_get('/health', health_check)
    return app

if __name__ == "__main__":
    # Run health check server
    app = create_health_app()
    web.run_app(app, host='0.0.0.0', port=8000)

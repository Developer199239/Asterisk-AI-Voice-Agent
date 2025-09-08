"""
Shared Health Check Module

This module provides a standardized way to create FastAPI health check endpoints
for all services in the Asterisk AI Voice Agent v2.0.
"""

from fastapi import FastAPI, Response
from pydantic import BaseModel, Field
import time
from typing import List, Optional, Dict, Any

class HealthCheckStatus(BaseModel):
    status: str = Field(..., description="Overall health status (healthy, unhealthy)")
    service: str = Field(..., description="Name of the service")
    timestamp: float = Field(default_factory=time.time, description="Timestamp of the health check")
    dependencies: Optional[List[Dict[str, Any]]] = Field(None, description="Status of dependencies")

def create_health_check_app(service_name: str, dependency_checks: Optional[List[callable]] = None) -> FastAPI:
    """
    Create a FastAPI application with a standardized health check endpoint.
    
    Args:
        service_name: The name of the service.
        dependency_checks: A list of async functions to check dependencies.
        
    Returns:
        A FastAPI application.
    """
    app = FastAPI()

    @app.get("/health", response_model=HealthCheckStatus)
    async def health_check(response: Response):
        """Health check endpoint"""
        healthy = True
        dependencies = []
        
        if dependency_checks:
            for check in dependency_checks:
                try:
                    dep_name, dep_status = await check()
                    dependencies.append({"name": dep_name, "status": "healthy" if dep_status else "unhealthy"})
                    if not dep_status:
                        healthy = False
                except Exception as e:
                    dependencies.append({"name": "unknown", "status": "unhealthy", "error": str(e)})
                    healthy = False
        
        status = "healthy" if healthy else "unhealthy"
        if not healthy:
            response.status_code = 503
            
        return HealthCheckStatus(
            status=status,
            service=service_name,
            dependencies=dependencies
        )
        
    return app

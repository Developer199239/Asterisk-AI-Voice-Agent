from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from api import config, system, wizard, logs, local_ai
import auth
import settings
from dotenv import load_dotenv

# Load environment variables (wizard will create .env from .env.example on first Next click)
load_dotenv(settings.ENV_PATH)

app = FastAPI(title="Asterisk AI Voice Agent Admin API")

# Initialize users (create default admin if needed)
auth.load_users()

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, this should be stricter
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
# Public routes
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])

# Protected routes
app.include_router(config.router, prefix="/api/config", tags=["config"], dependencies=[Depends(auth.get_current_user)])
app.include_router(system.router, prefix="/api/system", tags=["system"], dependencies=[Depends(auth.get_current_user)])
app.include_router(wizard.router, prefix="/api/wizard", tags=["wizard"], dependencies=[Depends(auth.get_current_user)])
app.include_router(logs.router, prefix="/api/logs", tags=["logs"], dependencies=[Depends(auth.get_current_user)])
app.include_router(local_ai.router, prefix="/api/local-ai", tags=["local-ai"], dependencies=[Depends(auth.get_current_user)])

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

# Serve static files (Frontend)
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os

# Mount static files if directory exists (production/docker)
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/assets", StaticFiles(directory=os.path.join(static_dir, "assets")), name="assets")
    
    @app.get("/{full_path:path}")
    async def serve_react_app(full_path: str):
        # API routes are already handled above
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")
            
        # Serve index.html for all other routes (SPA)
        response = FileResponse(os.path.join(static_dir, "index.html"))
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

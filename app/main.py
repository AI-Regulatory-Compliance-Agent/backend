from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.database import engine, Base
from app.config import get_settings
from app.routers import auth

settings = get_settings()

# create all tables on startup
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="AI Regulatory Compliance Agent",
    version="1.0.0"
)

# CORS — allows React frontend to call backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# routers
app.include_router(auth.router)


@app.get("/health")
def health():
    return {"status": "ok"}
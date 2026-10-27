"""Vercel's Flask entrypoint. No local server or migrations run on import."""
from app import create_app

app = create_app()

"""Pintu masuk Lambda untuk API (Function URL / API Gateway)."""
from mangum import Mangum

from .main import app

handler = Mangum(app, lifespan="off")

from fastapi import APIRouter

from app.api.v1.endpoints import audit, auth, google, gtm

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(google.router)
api_router.include_router(audit.router)
api_router.include_router(gtm.router)

from fastapi import APIRouter

from app.api.v1.endpoints import advisor, audit, auth, dev, google, gtm, websites

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(google.router)
api_router.include_router(websites.router)
api_router.include_router(audit.router)
api_router.include_router(gtm.router)
api_router.include_router(advisor.router)
api_router.include_router(dev.router)

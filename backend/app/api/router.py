from fastapi import APIRouter

from backend.app.api.routes.analytics import router as analytics_router
from backend.app.api.routes.applications import router as applications_router
from backend.app.api.routes.audit import router as audit_router
from backend.app.api.routes.auth import router as auth_router
from backend.app.api.routes.auth import users_router
from backend.app.api.routes.candidates import router as candidates_router
from backend.app.api.routes.health import router as health_router
from backend.app.api.routes.jobs import router as jobs_router
from backend.app.api.routes.resumes import router as resumes_router
from backend.app.api.routes.screening import router as screening_router

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(users_router)
api_router.include_router(candidates_router)
api_router.include_router(resumes_router)
api_router.include_router(jobs_router)
api_router.include_router(applications_router)
api_router.include_router(screening_router)
api_router.include_router(audit_router)
api_router.include_router(analytics_router)
api_router.include_router(health_router)

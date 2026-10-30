from fastapi import APIRouter

from .course_routes import router as course_router

# Add team endpoints to this router, e.g. @router.get('/...').
router = APIRouter(prefix="/api/team", tags=["team"])
router.include_router(course_router)

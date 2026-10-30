from fastapi import APIRouter

from .benefits.routes import router as benefits_router

# Team endpoints. main.py already registers this router.
# The router has no prefix so the benefits API keeps its requested /api/benefits path
# without editing main.py. Other team endpoints go under team_router (/api/team).
router = APIRouter()
team_router = APIRouter(prefix="/api/team", tags=["team"])

# Add team endpoints above this line, e.g. @team_router.get('/...').
router.include_router(team_router)
router.include_router(benefits_router)

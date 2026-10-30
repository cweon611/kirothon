from fastapi import APIRouter

from .benefit_bridge import BenefitsEnginePort
from .benefit_port import set_benefit_port
from .benefits.routes import router as benefits_router
from .course_routes import router as course_router

# Team endpoints. main.py already registers this router.
# The router has no prefix so the benefits API keeps its requested /api/benefits path
# without editing main.py. Other team endpoints go under team_router (/api/team).
router = APIRouter()
team_router = APIRouter(prefix="/api/team", tags=["team"])
team_router.include_router(course_router)

# F1/F2 read benefit verdicts from the benefits engine in-process (no I/O at import).
set_benefit_port(BenefitsEnginePort())

# Add team endpoints above this line, e.g. @team_router.get('/...').
router.include_router(team_router)
router.include_router(benefits_router)

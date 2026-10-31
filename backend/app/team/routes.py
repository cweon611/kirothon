from fastapi import APIRouter

from .benefit_bridge import BenefitsEnginePort
from .benefit_port import set_benefit_port
from .benefits.routes import router as benefits_router
from .course_routes import router as course_router
from .date_recommend import router as date_router
from .frontend_static import router as frontend_router

# Team endpoints. main.py already registers this router.
# The router has no prefix so the benefits API keeps its requested /api/benefits path
# without editing main.py. Other team endpoints go under team_router (/api/team).
router = APIRouter()
team_router = APIRouter(prefix="/api/team", tags=["team"])
team_router.include_router(course_router)
team_router.include_router(date_router)  # POST /api/team/date-recommendations

# F1/F2 read benefit verdicts from the benefits engine in-process (no I/O at import).
set_benefit_port(BenefitsEnginePort())

# Add team endpoints above this line, e.g. @team_router.get('/...').
router.include_router(team_router)
router.include_router(benefits_router)
# Built-frontend serving: no routes here; its lifespan appends a catch-all after all API routes,
# only when KIROTHON_FRONTEND_DIST is set (see frontend_static.py).
router.include_router(frontend_router)

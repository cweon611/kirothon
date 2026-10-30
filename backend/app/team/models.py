"""Define the team's new SQLModel table classes here.

They are registered before create_all. Existing deployed columns must not be
changed without a reviewed migration. Do not edit the base Record model just
to create a different service: define a separate, topic-specific table here.
"""
from .tourism_models import Course, HubRank, Place, RelatedPlace, TourismSyncRun  # noqa: F401

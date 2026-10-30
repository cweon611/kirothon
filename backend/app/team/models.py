"""Define the team's new SQLModel table classes here.

They are registered before create_all. Existing deployed columns must not be
changed without a reviewed migration. Do not edit the base Record model just
to create a different service: define a separate, topic-specific table here.
"""
from .benefits.store_models import (  # noqa: F401 -- register benefit sync tables
    BenefitRecordVersion, BenefitSourceRecord, BenefitSyncRun, BenefitSyncState,
)

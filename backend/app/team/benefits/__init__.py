"""Travel benefit (여행 지원제도) lookup and rule-based eligibility check.

Modules
- schemas:  program data model, request/response models
- regions:  region name normalization and matching
- registry: manually reviewed program entries (secondary data, not the API)
- gov24:    client for the 행정안전부 대한민국 공공서비스(혜택) 정보 API (api.odcloud.kr)
- engine:   deterministic eligibility and estimate logic
- routes:   /api/benefits endpoints

Nothing in this package performs network or database I/O at import time.
"""

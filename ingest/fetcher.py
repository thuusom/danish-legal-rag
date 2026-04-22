"""
Fetcher for Danish legal texts from retsinformation.dk.

Architecture supports real ingestion from retsinformation.dk API.
Falls back to local JSON files if the API is unavailable.

Retsinformation.dk provides a REST API for Danish law texts.
"""
from __future__ import annotations
import json
import logging
import os
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent / "data"

# Laws to ingest: (law_code, retsinformation document ID, fallback file)
# The corpus covers Danish tax, accounting, and corporate audit law:
# - Afskrivningsloven (AFL): Tax depreciation rules
# - Årsregnskabsloven (ARL): Financial reporting / accounting
# - Bogføringsloven (BOG): Bookkeeping requirements
# - Selskabsskatteloven (SEL): Corporate income tax
# - Momsloven (MOML): Value-added tax (VAT / moms)
# - Ligningsloven (LL): Personal and corporate income tax deductions
# - Skattekontrolloven (SKL): Tax reporting obligations and control
# - Revisorloven (REVL): Auditor regulation
# - Skatteforvaltningsloven (SFL): Tax administration, appeals, deadlines
LAWS_TO_INGEST = [
    {
        "law_code": "AFL",
        "retsinformation_id": "2016-1147",  # LBK nr 1147
        "fallback_file": DATA_DIR / "afskrivningsloven.json",
    },
    {
        "law_code": "ARL",
        "retsinformation_id": "2015-1580",  # LBK nr 1580
        "fallback_file": DATA_DIR / "aarsregnskabsloven.json",
    },
    {
        "law_code": "BOG",
        "retsinformation_id": "2022-700",  # LOV nr 700
        "fallback_file": DATA_DIR / "bogfoeringsloven.json",
    },
    {
        "law_code": "SEL",
        "retsinformation_id": "2022-1241",  # LBK nr 1241
        "fallback_file": DATA_DIR / "selskabsskatteloven.json",
    },
    {
        "law_code": "MOML",
        "retsinformation_id": "2019-1021",  # LBK nr 1021
        "fallback_file": DATA_DIR / "momsloven.json",
    },
    {
        "law_code": "LL",
        "retsinformation_id": "2021-1735",  # LBK nr 1735
        "fallback_file": DATA_DIR / "ligningsloven.json",
    },
    {
        "law_code": "SKL",
        "retsinformation_id": "2017-1535",  # LOV nr 1535
        "fallback_file": DATA_DIR / "skattekontrolloven.json",
    },
    {
        "law_code": "REVL",
        "retsinformation_id": "2024-25",  # LBK nr 25
        "fallback_file": DATA_DIR / "revisorloven.json",
    },
    {
        "law_code": "SFL",
        "retsinformation_id": "2022-835",  # LBK nr 835
        "fallback_file": DATA_DIR / "skatteforvaltningsloven.json",
    },
]


def load_from_file(path: Path) -> dict:
    """Load law data from local JSON file."""
    logger.info(f"Loading law data from file: {path}")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def fetch_from_retsinformation(doc_id: str) -> Optional[dict]:
    """
    Attempt to fetch law text from retsinformation.dk API.
    Returns None if unavailable (network error, API change, etc.).

    NOTE: retsinformation.dk does not have a public structured API for
    full law text in JSON. In a production system, you would:
    1. Use their søge-API to find documents
    2. Parse the HTML/XML response
    3. Structure into our domain model

    For this example, we use local fallback files with realistic content.
    """
    logger.info(f"Attempting to fetch from retsinformation.dk: {doc_id}")
    try:
        url = f"https://www.retsinformation.dk/api/document/{doc_id}"
        with httpx.Client(timeout=10.0) as client:
            response = client.get(url)
            if response.status_code == 200:
                logger.info(f"Successfully fetched {doc_id} from retsinformation.dk")
                return response.json()
            else:
                logger.warning(f"retsinformation.dk returned {response.status_code} for {doc_id}")
                return None
    except Exception as e:
        logger.warning(f"Could not fetch from retsinformation.dk: {e}")
        return None


def load_all_laws() -> list[dict]:
    """
    Load all configured laws.

    For each law:
    1. Try fetching from retsinformation.dk
    2. Fall back to local JSON file if unavailable

    Returns list of law data dicts.
    """
    laws = []
    for law_config in LAWS_TO_INGEST:
        law_code = law_config["law_code"]

        # Try live fetch (disabled for local dev unless FETCH_LIVE=true)
        law_data = None
        if os.environ.get("FETCH_LIVE", "false").lower() == "true":
            law_data = fetch_from_retsinformation(law_config["retsinformation_id"])

        # Fall back to local file
        if law_data is None:
            logger.info(f"Using local fallback data for {law_code}")
            law_data = load_from_file(law_config["fallback_file"])

        laws.append(law_data)
        logger.info(f"Loaded law: {law_data['law_name']} ({law_code})")

    return laws

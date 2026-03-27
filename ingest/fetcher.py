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
# We ingest:
# - Afskrivningsloven (AFL): The key law for tax depreciation of intangible assets incl. software
# - Årsregnskabsloven (ARL): For financial reporting rules on intangible assets
#
# NOTE: "Skatteloven" is not a single Danish law. The relevant laws for
# tax depreciation of software/intangible assets are:
# - Afskrivningsloven (AFL): Primary source for tax depreciation
# - Ligningsloven (LL): Additional deduction rules
# - Årsregnskabsloven (ARL): Accounting (GAAP) perspective
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

#!/usr/bin/env python3
import argparse
import json
from pathlib import Path
from typing import List, Optional

from sqlalchemy import select

import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import SyncSessionLocal
from app.models import LinkedInSession
from app.settings import FERNET, logger
from app.utils.cookie_sanitizer import sanitize_cookies


def decrypt_cookies(encrypted_value: str) -> Optional[List[dict]]:
    if not encrypted_value:
        return None
    try:
        decrypted = FERNET.decrypt(encrypted_value.encode()).decode()
        return json.loads(decrypted)
    except Exception as exc:
        logger.error("Failed to decrypt cookies payload: %s", exc)
        return None


def rewrite_session(session: LinkedInSession, dry_run: bool) -> bool:
    payload = decrypt_cookies(session.cookies)
    if payload is None:
        logger.warning("Skipping session %s: cannot decrypt cookies", session.id)
        return False
    sanitized = sanitize_cookies(payload)
    if not sanitized:
        logger.warning("Skipping session %s: sanitizer produced empty payload", session.id)
        return False
    if sanitized == payload:
        return False
    serialized = json.dumps(sanitized)
    if dry_run:
        logger.info(
            "DRY-RUN session %s sanitized (%d -> %d cookies)",
            session.id,
            len(payload),
            len(sanitized),
        )
        return True
    session.cookies = FERNET.encrypt(serialized.encode()).decode()
    logger.info(
        "Session %s sanitized (%d -> %d cookies)",
        session.id,
        len(payload),
        len(sanitized),
    )
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Normalize linkedin_sessions cookies using the shared sanitizer."
    )
    parser.add_argument(
        "--outreach-profile-id",
        type=int,
        action="append",
        help="Limit the repair to specific outreach_profile_id values.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Only process the first N sessions that match the filters.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report changes without writing them to the database.",
    )
    args = parser.parse_args()

    filters = args.outreach_profile_id or []
    processed = changed = 0

    with SyncSessionLocal() as db:
        stmt = select(LinkedInSession).order_by(LinkedInSession.id)
        if filters:
            stmt = stmt.filter(LinkedInSession.outreach_profile_id.in_(filters))
        if args.limit:
            stmt = stmt.limit(args.limit)
        for session in db.execute(stmt).scalars():
            processed += 1
            if rewrite_session(session, args.dry_run):
                changed += 1
        if args.dry_run:
            db.rollback()
        else:
            db.commit()

    logger.info(
        "Repair complete. Processed %d session(s), sanitized %d, dry_run=%s",
        processed,
        changed,
        args.dry_run,
    )


if __name__ == "__main__":
    main()







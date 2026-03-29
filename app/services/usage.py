from sqlalchemy.ext.asyncio import AsyncSession
from app.db import get_session
from app.models import ApiUsage
from sqlalchemy import case
from sqlalchemy.dialects.postgresql import insert
import logging
import math

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("app")

rate_tab = {}

FEATURE_MAP = {"chat" : "chat_count", "ingest" : "ingest_count", "query" : "query_count", "team" : "team_count"}

def extract_feature(path: str):
    logger.info("FEATURE_MAP %s", FEATURE_MAP)
    for key, feature in FEATURE_MAP.items():
        if key in path:
            return feature
    return None

def update_rate(team_id, current_time, tau=10.0):
    prev = rate_tab.get(team_id)

    # First request → initialize
    if prev is None:
        rate_tab[team_id] = (current_time, 1.0)  # assume 1 req/sec baseline
        return 1.0

    last_time, prev_rate = prev

    delta = current_time - last_time

    # Guard against tiny/zero delta
    if delta <= 1e-6:
        return prev_rate

    # Time decay
    decay = math.exp(-delta / tau)

    # Update rate
    new_rate = prev_rate * decay + (1 / delta)

    # Store updated state
    rate_tab[team_id] = (current_time, new_rate)

    return new_rate

async def log_api_usage(
    team_id,
    api_key_id,
    endpoint,
    start_time,
    latency_ms,
):
    logger.info("hello from log_api_usage")
    
    feature = extract_feature(endpoint)
    rate_cur = update_rate(team_id, start_time)
    
    # Build initial insert
    insert_values = {
        "team_id": team_id,
        "total_count": 1,
        "last_req" : endpoint,
        "latency_ms": latency_ms,
        "rate_max": rate_cur,  # initially same as rate_cur
    }
    if feature:
        insert_values[feature] = 1  # increment feature only if given

    stmt = insert(ApiUsage).values(**insert_values)

    # Build update dict for ON CONFLICT
    update_dict = {
        "total_count": ApiUsage.total_count + 1,
        "latency_ms": stmt.excluded.latency_ms,
        # update rate_max only if new rate_cur is higher
        "rate_max": case(
            (stmt.excluded.rate_max > ApiUsage.rate_max, stmt.excluded.rate_max),
            else_=ApiUsage.rate_max,
        )
    }

    if feature:
        # increment the feature counter if provided
        update_dict[feature] = getattr(ApiUsage, feature) + 1

    stmt = stmt.on_conflict_do_update(
        index_elements=["team_id"],
        set_=update_dict,
    )

    async for session in get_session():
        await session.execute(stmt)
        await session.commit()
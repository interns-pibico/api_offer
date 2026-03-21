"""Cleanup inactive accounts and stale shopping lists.

Two cleanup levels:
1. Lists cleanup (3 months): If a user hasn't logged in for 90 days, delete their shopping lists (account stays).
2. Account cleanup (1 year): If a user hasn't logged in for 365 days, delete account + lists entirely.

Run via cron weekly:
    cd /home/erpnext/.services/api_offer && /home/erpnext/api_offer_env/bin/python scripts/cleanup_inactive_accounts.py
"""

import asyncio
import os
import re
import sys


def _load_env(env_path: str) -> dict:
    env: dict = {}
    if not os.path.exists(env_path):
        return env
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, raw_val = line.partition("=")
            key = key.strip()
            raw_val = raw_val.strip()
            if (raw_val.startswith('"') and raw_val.endswith('"')) or (
                raw_val.startswith("'") and raw_val.endswith("'")
            ):
                raw_val = raw_val[1:-1]
            env[key] = raw_val
    return env


def _asyncpg_url(database_url: str) -> str:
    return re.sub(r"^postgresql\+asyncpg://", "postgresql://", database_url)


async def cleanup(database_url: str) -> None:
    try:
        import asyncpg
    except ImportError:
        print("ERROR: asyncpg not installed")
        sys.exit(1)

    conn = await asyncpg.connect(database_url)
    try:
        # ── Step 1: Delete lists from users inactive 3+ months (account stays) ──
        stale_list_users = await conn.fetch("""
            SELECT u.id, u.username, u.last_login_at,
                   (SELECT count(*) FROM shopping_lists sl WHERE sl.user_id = u.id) AS list_count
            FROM users u
            WHERE (u.last_login_at IS NOT NULL AND u.last_login_at < NOW() - INTERVAL '90 days')
               OR (u.last_login_at IS NULL AND u.created_at < NOW() - INTERVAL '90 days')
        """)

        lists_deleted_users = [r for r in stale_list_users if r["list_count"] > 0]

        if lists_deleted_users:
            user_ids = [r["id"] for r in lists_deleted_users]
            result = await conn.execute(
                "DELETE FROM shopping_lists WHERE user_id = ANY($1::int[])", user_ids
            )
            print(f"Lists cleanup (3 months): deleted lists for {len(lists_deleted_users)} user(s): {result}")
            for r in lists_deleted_users:
                print(f"  user={r['username']} lists={r['list_count']} last_login={r['last_login_at'] or 'never'}")
        else:
            print("Lists cleanup (3 months): no stale lists found.")

        # ── Step 2: Delete accounts inactive 1+ year ──
        old_accounts = await conn.fetch("""
            SELECT id, username, email, last_login_at, created_at
            FROM users
            WHERE (last_login_at IS NOT NULL AND last_login_at < NOW() - INTERVAL '365 days')
               OR (last_login_at IS NULL AND created_at < NOW() - INTERVAL '365 days')
        """)

        if old_accounts:
            user_ids = [r["id"] for r in old_accounts]
            await conn.execute(
                "DELETE FROM shopping_lists WHERE user_id = ANY($1::int[])", user_ids
            )
            deleted = await conn.execute(
                "DELETE FROM users WHERE id = ANY($1::int[])", user_ids
            )
            print(f"Account cleanup (1 year): deleted {len(old_accounts)} account(s): {deleted}")
            for r in old_accounts:
                print(f"  user={r['username']} email={r['email']} last_login={r['last_login_at'] or 'never'}")
        else:
            print("Account cleanup (1 year): no inactive accounts found.")

    finally:
        await conn.close()


def main() -> None:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    env_path = os.path.join(project_root, ".env")

    env = _load_env(env_path)
    raw_url = env.get("DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not raw_url:
        print(f"ERROR: DATABASE_URL not found in {env_path}")
        sys.exit(1)

    database_url = _asyncpg_url(raw_url)
    asyncio.run(cleanup(database_url))


if __name__ == "__main__":
    main()

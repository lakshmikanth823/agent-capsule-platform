"""
Single-Command Database Reset and Reseed Script
Drops all tables, runs migrations from scratch, and seeds initial data.
"""
import sys
import asyncio
from pathlib import Path

# Ensure src is in python path
src_dir = Path(__file__).resolve().parent.parent
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from alembic import command
from alembic.config import Config
from db.seed import seed_database


def run_alembic_upgrade():
    root_dir = Path(__file__).resolve().parent.parent.parent
    alembic_ini_path = root_dir / "alembic.ini"
    alembic_cfg = Config(str(alembic_ini_path))
    alembic_cfg.set_main_option("script_location", str(root_dir / "alembic"))

    print("[*] Running Alembic migrations downgrade to base...")
    try:
        command.downgrade(alembic_cfg, "base")
    except Exception as e:
        print(f"  Note: Downgrade notice: {e}")

    print("[*] Running Alembic migrations upgrade to head...")
    command.upgrade(alembic_cfg, "head")
    print("  + Migrations applied successfully!")


def main():
    print("==================================================")
    print("[*] Resetting and Reseeding Control Plane Database")
    print("==================================================")
    run_alembic_upgrade()
    asyncio.run(seed_database())
    print("==================================================")
    print("[+] Reset and Reseed Completed Successfully!")
    print("==================================================")


if __name__ == "__main__":
    main()

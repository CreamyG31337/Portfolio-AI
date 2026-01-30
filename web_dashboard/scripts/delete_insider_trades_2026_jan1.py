"""
Delete insider_trades with transaction_date on 2026-01-01 only (Supabase).
Run from repo root with venv.
"""
import sys
from pathlib import Path

_script_dir = Path(__file__).resolve().parent
_web_dashboard = _script_dir.parent
_project_root = _web_dashboard.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))
if str(_web_dashboard) not in sys.path:
    sys.path.insert(0, str(_web_dashboard))

try:
    from dotenv import load_dotenv
    load_dotenv(_project_root / ".env")
    load_dotenv(_web_dashboard / ".env")
except ImportError:
    pass


def main() -> None:
    try:
        from supabase_client import SupabaseClient
    except ImportError as e:
        print("Missing supabase_client:", e)
        sys.exit(1)
    client = SupabaseClient(use_service_role=True)
    client.supabase.table("insider_trades").delete().eq(
        "transaction_date", "2026-01-01"
    ).execute()
    print("Deleted insider_trades rows with transaction_date on 2026-01-01.")


if __name__ == "__main__":
    main()

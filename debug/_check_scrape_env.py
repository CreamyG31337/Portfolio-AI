from pathlib import Path
import os
from dotenv import load_dotenv

load_dotenv("web_dashboard/.env")
load_dotenv(".env")

candidates = [k for k in os.environ if "SUPABASE" in k.upper() or "CONGRESS" in k.upper() or "FLARE" in k.upper()]
for k in sorted(candidates):
    v = os.environ[k]
    print(f"{k}=SET len={len(v)}")

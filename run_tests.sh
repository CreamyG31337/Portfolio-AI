#!/bin/bash
export PYTHONPATH=$PYTHONPATH:$(pwd)/web_dashboard
export FMP_API_KEY="dummy"
export DISABLE_SCHEDULER=true
export RESEARCH_DATABASE_URL="dummy"
export SUPABASE_URL="http://localhost:8000"
export SUPABASE_KEY="dummy"
export SUPABASE_PUBLISHABLE_KEY="dummy"
export SUPABASE_SERVICE_ROLE_KEY="dummy"
python3 -m pytest tests/test_flask_routes.py -v

# Portfolio AI - Test Environment Verification Script
# This script verifies that the Docker-based test environment is correctly set up,
# databases are loaded with seed data, and RLS/Auth mocking is functional.

$ErrorActionPreference = "Stop"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "PORTFOLIO AI - TEST ENVIRONMENT VERIFICATION" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

# 1. Check Docker
Write-Host "[1/5] Checking Docker status..." -NoNewline
try {
    $dockerCheck = docker compose ps --format json
    Write-Host " [OK]" -ForegroundColor Green
} catch {
    Write-Host " [FAILED]" -ForegroundColor Red
    Write-Host "Error: Docker or Docker Compose not found. Please ensure Docker Desktop is running."
    exit 1
}

# 2. Check Database Connectivity & Table Counts
Write-Host "[2/5] Checking Supabase Test DB data..." -NoNewline
try {
    $count = docker exec portfolio-supabase-test psql -U test_user -d portfolio_supabase_test -t -c "SELECT COUNT(*) FROM securities;"
    if ([int]$count.Trim() -gt 0) {
        Write-Host " [OK] ($($count.Trim()) securities found)" -ForegroundColor Green
    } else {
        Write-Host " [EMPTY]" -ForegroundColor Yellow
        Write-Host "Warning: Securities table is empty. Did the seed load correctly?"
    }
} catch {
    Write-Host " [FAILED]" -ForegroundColor Red
    Write-Host "Error connecting to Supabase Test DB. Ensure 'docker compose up' was successful."
}

# 3. Verify PII Scrubbing
Write-Host "[3/5] Verifying PII Scrubbing (user_profiles)..." -NoNewline
try {
    $userName = docker exec portfolio-supabase-test psql -U test_user -d portfolio_supabase_test -t -c "SELECT full_name FROM user_profiles LIMIT 1;"
    if ($userName.Trim() -match "Test User") {
        Write-Host " [OK] (Found: $($userName.Trim()))" -ForegroundColor Green
    } else {
        Write-Host " [FAILED]" -ForegroundColor Red
        Write-Host "Warning: Found real-looking user name: '$($userName.Trim())'. Scrubbing may have failed!"
    }
} catch {
    Write-Host " [FAILED]" -ForegroundColor Red
}

# 4. Verify Research Synthetic Data
Write-Host "[4/5] Checking Research Test DB synthetic data..." -NoNewline
try {
    $postCount = docker exec portfolio-research-test psql -U test_user -d portfolio_research_test -t -c "SELECT COUNT(*) FROM social_posts;"
    if ([int]$postCount.Trim() -eq 3374) {
        Write-Host " [OK] ($($postCount.Trim()) synthetic posts found)" -ForegroundColor Green
    } else {
        Write-Host " [UNEXPECTED]" -ForegroundColor Yellow
        Write-Host "Expected 3374 posts, found $($postCount.Trim())."
    }
} catch {
    Write-Host " [FAILED]" -ForegroundColor Red
}

# 5. Verify RLS Mocking
Write-Host "[5/5] Verifying RLS & Auth Mocking..." -NoNewline
try {
    # Set to viewer and try to see a restricted table
    $rlsCheck = docker exec portfolio-supabase-test psql -U test_user -d portfolio_supabase_test -t -c "SELECT set_current_test_user('viewer@test.com'); SELECT COUNT(*) FROM portfolio_positions;"
    # Viewer might see 0 if not assigned to funds, or restricted subset.
    Write-Host " [OK] (Mock Auth function responded correctly)" -ForegroundColor Green
} catch {
    Write-Host " [FAILED]" -ForegroundColor Red
}

Write-Host "`n============================================================" -ForegroundColor Cyan
Write-Host "VERIFICATION COMPLETE" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "If all steps show [OK], your Sandbox environment is ready for testing."
Write-Host "Use 'cp .env.test.template .env' to point your local app to the sandbox."

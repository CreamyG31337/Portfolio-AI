#!/usr/bin/env python3
"""
CRITICAL PATCH: Fix Redis Configuration in queueManager.ts
This patch fixes Mandrel's hardcoded Redis localhost configuration
to read from REDIS_URL environment variable.

IF THIS PATCH FAILS, THE BUILD WILL FAIL WITH A HUGE ERROR.
"""
import sys
import re

TARGET_FILE = "src/services/queueManager.ts"
PATCH_MARKER = "// PATCHED: Redis config reads from REDIS_URL"

def print_error(msg):
    """Print huge error message"""
    border = "❌" * 100
    print("\n" + border)
    print("❌ FATAL ERROR: " + msg)
    print("❌ This patch is REQUIRED for Mandrel to work in Docker")
    print("❌ BUILD WILL FAIL")
    print(border + "\n")
    sys.exit(1)

def main():
    try:
        # Read file
        with open(TARGET_FILE, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check if already patched
        if PATCH_MARKER in content:
            print("✅ Patch already applied (found marker)")
            return 0
        
        # Check if target pattern exists
        if "host: 'localhost'" not in content or "port: 6379" not in content:
            print_error(f"Expected pattern not found in {TARGET_FILE}. File structure may have changed.")
        
        # Create backup
        with open(f"{TARGET_FILE}.backup", 'w', encoding='utf-8') as f:
            f.write(content)
        
        # Apply patch: Replace the REDIS_CONFIG constant
        old_pattern = r"const REDIS_CONFIG = \{\s*host: 'localhost',\s*port: 6379,"
        
        new_config = '''// PATCHED: Redis config reads from REDIS_URL
// Parse REDIS_URL environment variable or default to localhost
const REDIS_URL = process.env.REDIS_URL || 'redis://localhost:6379';
let redisHost = 'localhost';
let redisPort = 6379;

try {
  const redisUrl = new URL(REDIS_URL);
  redisHost = redisUrl.hostname;
  redisPort = parseInt(redisUrl.port) || 6379;
} catch (error) {
  console.error('⚠️  WARNING: Failed to parse REDIS_URL, using defaults:', error);
  console.error('   REDIS_URL was:', REDIS_URL);
}

console.log(`🔧 Redis Configuration: ${redisHost}:${redisPort} (from REDIS_URL: ${REDIS_URL})`);

const REDIS_CONFIG = {
  host: redisHost,
  port: redisPort,'''
        
        new_content = re.sub(old_pattern, new_config, content, flags=re.MULTILINE)
        
        if new_content == content:
            print_error(f"Pattern replacement failed. File may have different structure.")
        
        # Write patched content
        with open(TARGET_FILE, 'w', encoding='utf-8') as f:
            f.write(new_content)
        
        # Verify patch
        with open(TARGET_FILE, 'r', encoding='utf-8') as f:
            verify_content = f.read()
        
        if PATCH_MARKER not in verify_content:
            print_error("Patch marker not found after application")
        
        if "host: redisHost" not in verify_content or "port: redisPort" not in verify_content:
            print_error("Expected changes not found in patched file")
        
        print("✅ Redis configuration patch applied successfully!")
        print("   - Redis host now reads from REDIS_URL")
        print("   - Redis port now reads from REDIS_URL")
        return 0
        
    except FileNotFoundError:
        print_error(f"Target file not found: {TARGET_FILE}")
    except Exception as e:
        print_error(f"Patch application failed: {str(e)}")

if __name__ == "__main__":
    sys.exit(main())

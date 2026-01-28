#!/usr/bin/env python3
"""
In-memory log handler for capturing application logs.
Provides a thread-safe circular buffer for recent log messages.
"""

import json
import logging
from logging.handlers import RotatingFileHandler
from collections import deque
import threading
from datetime import datetime
from typing import List, Dict
import os


class DebugRotatingFileHandler(RotatingFileHandler):
    """RotatingFileHandler with debug logging to track rotation events.
    
    Logs to stderr (and a debug file) whenever rotation is triggered,
    including the file size and reason for rotation.
    """
    
    def doRollover(self):
        """Override to log rotation events before they happen."""
        import sys
        try:
            file_size = os.path.getsize(self.baseFilename) if os.path.exists(self.baseFilename) else 0
            msg = f"[ROTATION DEBUG] doRollover called! file={self.baseFilename}, size={file_size}, maxBytes={self.maxBytes}"
            print(msg, file=sys.stderr)
            # Also write to a debug file
            debug_log = os.path.join(os.path.dirname(self.baseFilename), 'rotation_debug.log')
            with open(debug_log, 'a') as f:
                f.write(f"{datetime.now().isoformat()} - {msg}\n")
        except Exception as e:
            print(f"[ROTATION DEBUG] Error logging rotation: {e}", file=sys.stderr)
        
        # Call the parent's doRollover
        super().doRollover()
    
    def shouldRollover(self, record):
        """Override to log when rollover check happens."""
        result = super().shouldRollover(record)
        if result:
            import sys
            try:
                file_size = os.path.getsize(self.baseFilename) if os.path.exists(self.baseFilename) else 0
                msg = f"[ROTATION DEBUG] shouldRollover=True! file={self.baseFilename}, size={file_size}, maxBytes={self.maxBytes}, record_len={len(self.format(record))}"
                print(msg, file=sys.stderr)
                debug_log = os.path.join(os.path.dirname(self.baseFilename), 'rotation_debug.log')
                with open(debug_log, 'a') as f:
                    f.write(f"{datetime.now().isoformat()} - {msg}\n")
            except Exception as e:
                print(f"[ROTATION DEBUG] Error logging shouldRollover: {e}", file=sys.stderr)
        return result

class WerkzeugAccessLogFilter(logging.Filter):
    """Filter out werkzeug HTTP access logs while preserving startup/debug messages.
    
    Suppresses: "IP - - [timestamp] \"METHOD /path HTTP/1.1\" STATUS"
    Preserves: "* Debugger is active!", "* Restarting with watchdog", warnings, etc.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if record.name != 'werkzeug':
            return True
        
        msg = record.getMessage()
        
        # Detect HTTP access logs by their distinctive format
        # Pattern: "IP - - [timestamp] \"METHOD /path HTTP/1.1\" STATUS"
        is_http_access_log = (
            ' - - [' in msg and  # Access log format (IP - - [timestamp])
            ('HTTP/1.' in msg or 'HTTP/2' in msg)  # HTTP version in request line
        )
        
        # Suppress all HTTP access logs, keep everything else (startup, debug, warnings)
        return not is_http_access_log


# Add custom PERF logging level (between DEBUG=10 and INFO=20)
PERF_LEVEL = 15
logging.addLevelName(PERF_LEVEL, 'PERF')

def perf(self, message, *args, **kwargs):
    """Log a message with PERF level."""
    if self.isEnabledFor(PERF_LEVEL):
        self._log(PERF_LEVEL, message, args, **kwargs)

# Add perf method to Logger class
logging.Logger.perf = perf


class PacificTimeFormatter(logging.Formatter):
    """Custom formatter that displays timestamps in Pacific Time."""
    
    def formatTime(self, record, datefmt=None):
        """Override formatTime to use Pacific Time."""
        try:
            from zoneinfo import ZoneInfo
            pacific = ZoneInfo("America/Vancouver")
            dt = datetime.fromtimestamp(record.created, tz=pacific)
        except (ImportError, Exception):
            # Fallback if zoneinfo not available
            from datetime import timezone, timedelta
            # Pacific is UTC-8 (PST) or UTC-7 (PDT)
            # This is a simple approximation - doesn't handle DST perfectly
            pacific_offset = timedelta(hours=-8)
            dt = datetime.fromtimestamp(record.created, tz=timezone(pacific_offset))
        
        if datefmt:
            return dt.strftime(datefmt)
        else:
            return dt.strftime('%Y-%m-%d %H:%M:%S')


class InMemoryLogHandler(logging.Handler):
    """Custom logging handler that stores recent log messages in memory.
    
    Thread-safe circular buffer with configurable size. Useful for
    displaying logs in web UI without file system access.
    """
    
    def __init__(self, maxlen=500):
        super().__init__()
        self.log_records = deque(maxlen=maxlen)
        self.lock = threading.Lock()
        
        # Set a formatter with Pacific Time
        formatter = PacificTimeFormatter(
            '%(asctime)s | %(levelname)-8s | %(name)-30s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        self.setFormatter(formatter)
    
    def emit(self, record):
        """Store formatted log record in buffer."""
        try:
            msg = self.format(record)
            with self.lock:
                self.log_records.append({
                    'timestamp': datetime.fromtimestamp(record.created),
                    'level': record.levelname,
                    'module': record.name,
                    'message': record.getMessage(),
                    'formatted': msg
                })
        except Exception:
            self.handleError(record)
    
    def get_logs(self, n=None, level=None, module=None, search=None, since_deployment=False) -> List[Dict]:
        """Get recent log records with optional filtering.
        
        Args:
            n: Number of recent logs to return (None = all)
            level: Filter by log level (str) or list of levels (e.g., ['INFO', 'ERROR'])
            module: Filter by module name (partial match)
            search: Filter by message, module, level, or full log text (case-insensitive)
            since_deployment: If True, only return logs since last deployment timestamp
            
        Returns:
            List of log record dictionaries
        """
        with self.lock:
            logs = list(self.log_records)
        
        # Apply filters
        if level:
            if isinstance(level, list):
                # Support multiple levels
                logs = [log for log in logs if log['level'] in level]
            else:
                # Single level filter
                logs = [log for log in logs if log['level'] == level]
        
        if module:
            logs = [log for log in logs if module.lower() in log['module'].lower()]
        
        if search:
            search_lower = search.lower()
            logs = [log for log in logs if (
                search_lower in log['message'].lower() or
                search_lower in log['module'].lower() or
                search_lower in log['level'].lower() or
                (log.get('formatted') and search_lower in log['formatted'].lower())
            )]
        
        if since_deployment:
            deployment_cutoff = get_deployment_timestamp()
            if deployment_cutoff:
                logs = [log for log in logs if log['timestamp'] >= deployment_cutoff]
        
        # Return last n logs
        if n:
            logs = logs[-n:]
        
        return logs
    
    def get_formatted_logs(self, n=None, level=None, module=None, search=None, since_deployment=False) -> List[str]:
        """Get formatted log strings (for download/display).
        
        Args:
            Same as get_logs()
            
        Returns:
            List of formatted log strings
        """
        logs = self.get_logs(n=n, level=level, module=module, search=search, since_deployment=since_deployment)
        return [log['formatted'] for log in logs]
    
    def clear(self):
        """Clear all log records."""
        with self.lock:
            self.log_records.clear()


# Global handler instance
_log_handler = None


def get_log_handler() -> InMemoryLogHandler:
    """Get the global in-memory log handler instance.
    
    Returns:
        InMemoryLogHandler instance
    """
    global _log_handler
    if _log_handler is None:
        _log_handler = InMemoryLogHandler(maxlen=500)
    return _log_handler


_setup_logging_called = False
_file_handler = None

def setup_logging(level=logging.INFO):
    """Setup logging with rotating file handler for app modules.
    
    Uses RotatingFileHandler to write to logs/app.log with automatic rotation.
    Logs rotate when they reach 10MB, keeping 5 backup files (50MB total).
    Attached only to app-specific loggers, not root logger.
    
    This function is idempotent - calling it multiple times will reuse
    the same RotatingFileHandler to avoid spurious rotations.
    
    Args:
        level: Log level (default: INFO)
    """
    global _setup_logging_called, _file_handler
    import os
    
    # Ensure logs directory exists
    log_dir = os.path.join(os.path.dirname(__file__), 'logs')
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, 'app.log')
    
    # Reuse existing handler if already created (prevents spurious rotations)
    if _setup_logging_called and _file_handler is not None:
        file_handler = _file_handler
    else:
        # Create rotating file handler with debug logging
        # Max 10MB per file, keep 5 backups = 50MB total log storage
        file_handler = DebugRotatingFileHandler(
            log_file,
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=5,  # Keep 5 rotated files
            encoding='utf-8'
        )
        _file_handler = file_handler
        _setup_logging_called = True
        # Log handler creation for debugging
        import sys
        print(f"[ROTATION DEBUG] Created DebugRotatingFileHandler for {log_file}", file=sys.stderr)
    file_handler.setFormatter(PacificTimeFormatter(
        '%(asctime)s | %(levelname)-8s | %(name)-30s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    ))
    # Set handler to DEBUG to capture PERF (15) and all other levels
    # Logger level will still control what gets logged
    file_handler.setLevel(logging.DEBUG)
    
    # List of our application module names to capture logs from
    app_modules = [
        'app',  # For log_message() calls from streamlit_app.py
        'werkzeug',  # Flask's internal logger for request/response logs
        'streamlit_utils',
        'chart_utils', 
        'auth_utils',
        'user_preferences',
        'supabase_client',
        'exchange_rates_utils',
        'scheduler',
        'scheduler.scheduler_core',
        'scheduler.scheduler_core.heartbeat',  # Heartbeat logger for filtering
        'scheduler.jobs',
        'log_handler',
        'ollama_client',  # AI integration
        '__main__',
        'web_dashboard',
        'web_dashboard.utils.background_rebuild',  # Background rebuild logging
        'web_dashboard.utils',  # Rebuild from date and other utils
        'web_dashboard.pages.admin',  # Admin page logging
        'web_dashboard.pages',  # All pages
        'pages',  # Top level pages if imported that way
        'market_data',  # Price fetching and caching
        'utils',  # Root utils (job_tracking, market_holidays)
        'config',  # Settings logging
        'admin_utils',
        'social_service',
        'research_report_service',
        'ai_service_client',
        'archive_service',
        'web_dashboard.routes.etf_routes',
        'scheduler.jobs_etf_watchtower',
    ]
    
    # Attach handler to each app module logger
    for module_name in app_modules:
        logger = logging.getLogger(module_name)
        
        # Remove existing handlers to avoid duplicates
        # We also remove StreamHandlers if any, to avoid console noise/lag
        for h in logger.handlers[:]:
            logger.removeHandler(h)
        
        # Add our file handler
        logger.addHandler(file_handler)
        # Set logger level to DEBUG to capture PERF (15) and all other levels
        # Users can filter by level in the UI
        logger.setLevel(logging.DEBUG)
        
        # Disable propagation to prevent Streamlit interference
        logger.propagate = False
        
    # Suppress werkzeug HTTP access logs (keep startup/debug messages)
    werkzeug_logger = logging.getLogger('werkzeug')
    for f in werkzeug_logger.filters[:]:
        if isinstance(f, WerkzeugAccessLogFilter):
            break
    else:
        werkzeug_logger.addFilter(WerkzeugAccessLogFilter())
        
    # Also initialize the global InMemoryLogHandler for backward compatibility
    # (some code might still use log_handler.log_records directly)
    # But it won't receive new logs unless we also attach it.
    # For now, let's just stick to FileHandler as the source of truth.


def get_deployment_timestamp() -> datetime:
    """Get the last deployment timestamp from build_stamp.json.
    
    Returns:
        datetime object of last deployment, or None if file doesn't exist
    """
    import os
    
    # Try both web_dashboard directory and parent directory
    build_stamp_paths = [
        os.path.join(os.path.dirname(__file__), 'build_stamp.json'),
        os.path.join(os.path.dirname(os.path.dirname(__file__)), 'build_stamp.json'),
        os.path.join(os.getcwd(), 'build_stamp.json')
    ]
    
    for build_stamp_path in build_stamp_paths:
        if os.path.exists(build_stamp_path):
            try:
                with open(build_stamp_path, 'r') as f:
                    build_info = json.load(f)
                    timestamp_str = build_info.get('timestamp')
                    if timestamp_str:
                        return datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
            except Exception:
                continue
    
    return None


def read_logs_from_file(n=100, level=None, search=None, return_all=False, exclude_modules=None, since_deployment=False) -> List[Dict]:
    """Read recent logs from the log file efficiently.
    
    Reads from the end of the file to avoid loading the entire file into memory.
    This is much faster for large log files.
    Now reads from both app.log (current) and app.log.1 (most recent rotated backup).
    
    Args:
        n: Number of recent logs to return (ignored if return_all=True)
        level: Filter by log level (str) or list of levels (e.g., ['INFO', 'ERROR'])
        search: Filter by message, module, level, or full log text (case-insensitive)
        return_all: If True, return all filtered logs (up to reasonable limit)
        exclude_modules: List of module/logger names to exclude (e.g., ['scheduler.scheduler_core.heartbeat'])
        since_deployment: If True, only return logs since last deployment timestamp
        
    Returns:
        List of dicts with timestamp, level, module, message keys
    """
    import os
    
    log_dir = os.path.join(os.path.dirname(__file__), 'logs')
    log_file = os.path.join(log_dir, 'app.log')
    
    # Get deployment timestamp if needed
    deployment_cutoff = get_deployment_timestamp() if since_deployment else None
        
    logs = []
    
    # Pre-process filters (used for both files)
    exclude_modules_set = set()
    if exclude_modules:
        if isinstance(exclude_modules, str):
            exclude_modules_set.add(exclude_modules)
        else:
            exclude_modules_set.update(exclude_modules)

    level_set = None
    if level:
        if isinstance(level, list):
            level_set = set(level)
        else:
            level_set = {level}

    search_lower = search.lower() if search else None
    
    def read_log_file(file_path, is_rotated=False):
        """Read and parse a single log file, returning list of log dicts."""
        if not os.path.exists(file_path):
            print(f"[LOG_READER] File not found: {file_path}")
            return []
        
        file_logs = []
        
        try:
            file_size = os.path.getsize(file_path)
            print(f"[LOG_READER] Reading {file_path}: size={file_size}, is_rotated={is_rotated}")
            if file_size == 0:
                return []
            
            # Read from end of file
            # For rotated file, read entire file (it's already a complete backup)
            # For current file, read up to 20MB if return_all, or smaller buffer if n is specified
            if is_rotated:
                buffer_size = file_size  # Read entire rotated file
            elif return_all:
                buffer_size = min(20 * 1024 * 1024, file_size)  # Read up to 20MB for pagination
            else:
                buffer_size = min(n * 3 * 150, 1024 * 1024, file_size)
            
            print(f"[LOG_READER] Buffer size: {buffer_size}")
            
            with open(file_path, 'rb') as f:
                # Seek to position from end
                f.seek(max(0, file_size - buffer_size))
                
                # Read the buffer
                buffer = f.read().decode('utf-8', errors='ignore')
                
                # Split into lines (skip first partial line if we didn't start at beginning)
                lines = buffer.split('\n')
                if file_size > buffer_size:
                    lines = lines[1:]  # Skip first partial line
            
            # Parse lines
            for line in lines:
                if not line.strip():
                    continue
                    
                try:
                    # Expected format: YYYY-MM-DD HH:MM:SS | LEVEL    | module | message
                    parts = line.split(' | ', 3)
                    if len(parts) == 4:
                        timestamp_str, level_str, module_str, message_str = parts
                        
                        # Clean strings
                        level_clean = level_str.strip()
                        module_clean = module_str.strip()
                        message_clean = message_str.strip()

                        # Apply filters EARLY (before expensive datetime parsing/dict creation)

                        # 1. Level filter
                        if level_set and level_clean not in level_set:
                            continue

                        # 2. Module filter
                        if exclude_modules_set and module_clean in exclude_modules_set:
                            continue

                        # 3. Search filter
                        if search_lower:
                            if (search_lower not in message_clean.lower() and
                                search_lower not in module_clean.lower() and
                                search_lower not in level_clean.lower() and
                                search_lower not in line.lower()):
                                continue

                        # 4. Timestamp parsing (most expensive operation)
                        timestamp = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')

                        # 5. Deployment cutoff filter
                        if deployment_cutoff and timestamp < deployment_cutoff:
                            continue

                        # Store (only if passed all filters)
                        file_logs.append({
                            'timestamp': timestamp,
                            'level': level_clean,
                            'module': module_clean,
                            'message': message_clean,
                            'formatted': line.strip()
                        })
                except Exception:
                    continue # Skip malformed lines
            
            return file_logs
            
        except Exception as e:
            print(f"Error reading log file {file_path}: {e}")
            return []
    
    try:
        # Read from all available log files: app.log and app.log.1 through app.log.5
        # RotatingFileHandler keeps 5 backups
        print(f"[LOG_READER] log_dir={log_dir}")
        print(f"[LOG_READER] log_file={log_file}, exists={os.path.exists(log_file)}")
        
        # Read current file first (newest logs)
        current_logs = read_log_file(log_file, is_rotated=False)
        logs.extend(current_logs)
        print(f"[LOG_READER] current_logs count: {len(current_logs)}")
        
        # Read ALL rotated backups (app.log.1 through app.log.5)
        for i in range(1, 6):
            rotated_file = os.path.join(log_dir, f'app.log.{i}')
            if os.path.exists(rotated_file):
                rotated_logs = read_log_file(rotated_file, is_rotated=True)
                logs.extend(rotated_logs)
                print(f"[LOG_READER] app.log.{i} count: {len(rotated_logs)}")
            else:
                print(f"[LOG_READER] app.log.{i} not found")
        
        # Sort all logs by timestamp (newest first)
        # Current file logs are already newer, but we want chronological order for proper sorting
        logs.sort(key=lambda x: x['timestamp'], reverse=True)
        
        # Return last n (unless return_all is True)
        if not return_all and n:
            logs = logs[:n]  # Already sorted newest first, so take first n
                
        return logs
            
    except Exception as e:
        print(f"Error reading log file: {e}")
        return []


def log_message(message: str, level: str = 'INFO', module: str = 'app'):
    """Convenience function to log a message."""
    logger = logging.getLogger(module)
    level_upper = level.upper()
    if level_upper == 'PERF':
        log_level = PERF_LEVEL
    elif hasattr(logging, level_upper):
        log_level = getattr(logging, level_upper)
    else:
        log_level = logging.INFO
    logger.log(log_level, message)


def log_execution_time(module_name=None):
    """Decorator to log execution time of functions.
    
    Args:
        module_name: Optional module name for log record. 
                    If None, uses function's module.
    """
    import time
    import functools
    
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                return result
            finally:
                duration = time.time() - start_time
                # Determine module name
                mod = module_name or func.__module__
                
                # Use PERF level for all performance logging
                msg = f"PERF: {func.__name__} took {duration:.3f}s"
                
                log_message(msg, level='PERF', module=mod)
        return wrapper
    return decorator

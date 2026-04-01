#!/usr/bin/env python3
"""
Postgres client for local database connections
Handles research articles storage with connection pooling
"""

import os
import logging
from typing import Optional, Dict, Any, List
from contextlib import contextmanager
from env_loader import load_project_dotenv

load_project_dotenv()

try:
    import psycopg2
    from psycopg2 import pool, sql
    from psycopg2.extras import RealDictCursor
    from psycopg2 import OperationalError, Error
except ImportError:
    print("[ERROR] psycopg2 not available")
    print("[SOLUTION] Install with: pip install psycopg2-binary")
    raise ImportError("psycopg2 not available. Install with: pip install psycopg2-binary")

logger = logging.getLogger(__name__)


class PostgresClient:
    """Client for interacting with local Postgres database"""
    
    _connection_pool: Optional[pool.SimpleConnectionPool] = None
    _min_connections = 1
    _max_connections = 5
    
    def __init__(self, database_url: Optional[str] = None):
        """Initialize Postgres client
        
        Args:
            database_url: Optional connection string. If not provided, uses RESEARCH_DATABASE_URL from environment.
        """
        self.database_url = database_url or os.getenv("RESEARCH_DATABASE_URL")
        
        if not self.database_url:
            raise ValueError("RESEARCH_DATABASE_URL must be set in environment or provided as parameter")
        
        # Initialize connection pool if not already created
        if PostgresClient._connection_pool is None:
            self._create_connection_pool()
    
    def _create_connection_pool(self) -> None:
        """Create connection pool for database connections"""
        try:
            PostgresClient._connection_pool = psycopg2.pool.SimpleConnectionPool(
                PostgresClient._min_connections,
                PostgresClient._max_connections,
                self.database_url
            )
            
            if not PostgresClient._connection_pool:
                raise ValueError("Failed to create connection pool")
                
        except psycopg2.OperationalError as e:
            logger.error(f"❌ Connection error: {e}")
            logger.error("   Check that:")
            logger.error("   - Postgres container is running")
            logger.error("   - RESEARCH_DATABASE_URL is correct (host, port, database name)")
            logger.error("   - Database 'trading_db' exists")
            logger.error("   - Port 5432 is accessible")
            logger.error("   - Hostname is correct for your environment:")
            logger.error("     * From workstation (Tailscale): use your Tailscale hostname")
            logger.error("     * From server host: use localhost")
            logger.error("     * From Docker container: use container name or host.docker.internal")
            raise
        except psycopg2.Error as e:
            logger.error(f"❌ Postgres error creating connection pool: {e}")
            raise
        except Exception as e:
            logger.error(f"❌ Unexpected error creating connection pool: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            raise
    
    def _mask_password(self, url: str) -> str:
        """Mask password in connection string for logging"""
        if '@' in url and ':' in url.split('@')[0]:
            # Format: postgresql://user:password@host:port/db
            parts = url.split('@')
            auth_part = parts[0]
            if ':' in auth_part:
                user_pass = auth_part.split('://', 1)[1]
                if ':' in user_pass:
                    user = user_pass.split(':')[0]
                    return url.replace(user_pass, f"{user}:***")
        return url
    
    @contextmanager
    def get_connection(self):
        """Get a connection from the pool (context manager)
        
        Usage:
            with postgres_client.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM ...")
        """
        if PostgresClient._connection_pool is None:
            self._create_connection_pool()
        
        conn = PostgresClient._connection_pool.getconn()
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"Database error: {e}")
            raise
        finally:
            PostgresClient._connection_pool.putconn(conn)
    
    def test_connection(self) -> bool:
        """Test database connection"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT version()")
                cursor.execute("SELECT current_database()")
                return True
        except psycopg2.OperationalError as e:
            logger.error(f"❌ Connection failed: {e}")
            logger.error("   Possible issues:")
            logger.error("   - Container not running")
            logger.error("   - Wrong host/port (check if 5432 is correct)")
            logger.error("   - Database doesn't exist")
            logger.error("   - Authentication failed (check password if required)")
            return False
        except psycopg2.Error as e:
            logger.error(f"❌ Postgres error: {e}")
            return False
        except Exception as e:
            logger.error(f"❌ Unexpected error testing connection: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return False
    
    def execute_query(self, query: str, params: Optional[tuple] = None) -> List[Dict[str, Any]]:
        """Execute a SELECT query and return results as list of dictionaries
        
        Args:
            query: SQL query string
            params: Optional tuple of parameters for parameterized query
            
        Returns:
            List of dictionaries (one per row)
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(cursor_factory=RealDictCursor)
                cursor.execute(query, params)
                results = cursor.fetchall()
                return [dict(row) for row in results]
        except Exception as e:
            logger.error(f"❌ Error executing query: {e}")
            raise
    
    def execute_update(self, query: str, params: Optional[tuple] = None) -> int:
        """Execute an INSERT/UPDATE/DELETE query
        
        Args:
            query: SQL query string
            params: Optional tuple of parameters for parameterized query
            
        Returns:
            Number of rows affected
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query, params)
                rows_affected = cursor.rowcount
                conn.commit()
                return rows_affected
        except Exception as e:
            logger.error(f"❌ Error executing update: {e}")
            raise
    
    def execute_many(self, query: str, params_list: List[tuple]) -> int:
        """Execute a query multiple times with different parameters
        
        Args:
            query: SQL query string
            params_list: List of parameter tuples
            
        Returns:
            Total number of rows affected
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.executemany(query, params_list)
                rows_affected = cursor.rowcount
                conn.commit()
                return rows_affected
        except Exception as e:
            logger.error(f"❌ Error executing batch update: {e}")
            raise
    
    def close_pool(self) -> None:
        """Close all connections in the pool"""
        if PostgresClient._connection_pool:
            PostgresClient._connection_pool.closeall()
            PostgresClient._connection_pool = None
    
    def __del__(self):
        """Cleanup on object destruction"""
        # Note: Don't close pool in __del__ as it may be called during garbage collection
        # when other objects still need connections. Use close_pool() explicitly if needed.
        pass


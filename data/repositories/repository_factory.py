"""Repository factory for creating repository instances."""

from __future__ import annotations

from typing import Dict, Any, Optional
import logging

from .base_repository import BaseRepository
from .csv_repository import CSVRepository
from .supabase_repository import SupabaseRepository

logger = logging.getLogger(__name__)


class RepositoryFactory:
    """Factory for creating repository instances based on configuration.
    
    This factory allows the system to switch between different repository
    implementations (CSV, database, etc.) based on configuration settings.
    """
    
    _repositories: Dict[str, type] = {
        'csv': CSVRepository,
        'supabase': SupabaseRepository,
        'dual-write': 'DualWriteRepository',  # Will be imported dynamically
        'supabase-dual-write': 'SupabaseDualWriteRepository',  # Will be imported dynamically
        # Future repository types can be added here
        # 'database': DatabaseRepository,
        # 'memory': InMemoryRepository,
    }
    
    @classmethod
    def create_repository(cls, repository_type: str = 'csv', **kwargs) -> BaseRepository:
        """Create a repository instance based on type.
        
        Args:
            repository_type: Type of repository to create ('csv', 'database', etc.)
            **kwargs: Additional arguments to pass to repository constructor
            
        Returns:
            Repository instance implementing BaseRepository interface
            
        Raises:
            ValueError: If repository type is not supported
        """
        if repository_type not in cls._repositories:
            available_types = list(cls._repositories.keys())
            raise ValueError(
                f"Unsupported repository type: {repository_type}. "
                f"Available types: {available_types}"
            )
        
        repository_class = cls._repositories[repository_type]
        
        # Handle dual-write repository creation
        if repository_type == 'dual-write':
            from .dual_write_repository import DualWriteRepository
            repository_class = DualWriteRepository
        elif repository_type == 'supabase-dual-write':
            from .supabase_dual_write_repository import SupabaseDualWriteRepository
            repository_class = SupabaseDualWriteRepository
        
        # Remove 'type' from kwargs if present (it's already extracted as repository_type)
        clean_kwargs = {k: v for k, v in kwargs.items() if k != 'type'}
        
        # Standardize parameter names - all repositories use fund_name
        if 'fund' in clean_kwargs and 'fund_name' not in clean_kwargs:
            clean_kwargs['fund_name'] = clean_kwargs.pop('fund')
        
        # Filter kwargs based on repository type to avoid unsupported parameters
        if repository_type == 'csv':
            # CSV repository accepts fund_name and optional data_directory
            clean_kwargs = {k: v for k, v in clean_kwargs.items() if k in ['fund_name', 'data_directory']}
        elif repository_type == 'supabase':
            # Supabase repository accepts fund_name and supabase config
            clean_kwargs = {k: v for k, v in clean_kwargs.items() if k in ['fund_name', 'url', 'key', 'supabase']}
        elif repository_type in ['dual-write', 'supabase-dual-write']:
            # Dual-write repositories accept fund_name and optional data_directory
            clean_kwargs = {k: v for k, v in clean_kwargs.items() if k in ['fund_name', 'data_directory']}
        
        try:
            logger.info(f"Creating {repository_type} repository with args: {clean_kwargs}")
            return repository_class(**clean_kwargs)
        except Exception as e:
            logger.error(f"Failed to create {repository_type} repository: {e}")
            raise
    
    @classmethod
    def register_repository(cls, name: str, repository_class: type) -> None:
        """Register a new repository type.
        
        Args:
            name: Name for the repository type
            repository_class: Repository class implementing BaseRepository
        """
        if not issubclass(repository_class, BaseRepository):
            raise ValueError(
                f"Repository class must implement BaseRepository interface: {repository_class}"
            )
        
        cls._repositories[name] = repository_class
        logger.info(f"Registered repository type: {name}")
    
    @classmethod
    def get_available_types(cls) -> list[str]:
        """Get list of available repository types.
        
        Returns:
            List of available repository type names
        """
        return list(cls._repositories.keys())
    
    @classmethod
    def create_dual_write_repository(cls, fund_name: str, data_directory: str = None) -> 'DualWriteRepository':
        """Create a dual-write repository with both CSV and Supabase repositories.
        
        CONSOLE APP ONLY: This creates a DualWriteRepository that reads from CSV.
        The web dashboard should use SupabaseRepository directly (no CSV on the server).
        
        Args:
            fund_name: Name of the fund (e.g. "RRSP Lance Webull").
                       IMPORTANT: This is a fund NAME, not a file path.
                       Always use named parameters to avoid accidentally swapping args.
            data_directory: Optional path to CSV data directory
                           (defaults to trading_data/funds/{fund_name}).
                           IMPORTANT: This is a directory PATH, not a fund name.
            
        Returns:
            DualWriteRepository instance for dual-write operations
            
        Usage:
            # CORRECT - use named parameters:
            RepositoryFactory.create_dual_write_repository(
                fund_name="MyFund", data_directory="/path/to/data"
            )
            # WRONG - positional args are easy to swap:
            RepositoryFactory.create_dual_write_repository(data_dir, fund)  # BUG!
        """
        from .dual_write_repository import DualWriteRepository
        
        # Create dual-write repository
        return DualWriteRepository(fund_name=fund_name, data_directory=data_directory)


class RepositoryContainer:
    """Dependency injection container for repository instances.
    
    This container manages repository instances and provides dependency
    injection for the trading system components.
    """
    
    def __init__(self):
        """Initialize the repository container."""
        self._repositories: Dict[str, BaseRepository] = {}
        self._config: Dict[str, Any] = {}
    
    def configure(self, config: Dict[str, Any]) -> None:
        """Configure the container with repository settings.
        
        Args:
            config: Configuration dictionary containing repository settings
        """
        self._config = config.copy()
        logger.info(f"Repository container configured with: {config}")
    
    def get_repository(self, name: str = 'default') -> BaseRepository:
        """Get a repository instance by name.
        
        Args:
            name: Name of the repository instance
            
        Returns:
            Repository instance
            
        Raises:
            ValueError: If repository is not configured
        """
        if name not in self._repositories:
            # Create repository on first access
            self._create_repository(name)
        
        return self._repositories[name]
    
    def set_repository(self, repository: BaseRepository, name: str = 'default') -> None:
        """Set a repository instance.
        
        Args:
            repository: Repository instance to set
            name: Name for the repository instance
        """
        self._repositories[name] = repository
        logger.info(f"Set repository instance: {name}")
    
    def _create_repository(self, name: str) -> None:
        """Create a repository instance based on configuration.
        
        Args:
            name: Name of the repository to create
        """
        # Get configuration for this repository
        repo_config = self._config.get(name, self._config.get('default', {}))
        
        if not repo_config:
            # No valid default - must have explicit configuration
            raise ValueError(
                f"No configuration found for repository '{name}'. "
                f"Repository must be configured with explicit settings including data_directory."
            )
        
        repository_type = repo_config.get('type', 'csv')
        
        # Remove 'type' from kwargs before passing to constructor
        kwargs = {k: v for k, v in repo_config.items() if k != 'type'}
        
        # Create repository instance - pass repository_type as positional arg
        repository = RepositoryFactory.create_repository(repository_type=repository_type, **kwargs)
        self._repositories[name] = repository
        
        logger.info(f"Created repository '{name}' of type '{repository_type}'")
    
    def clear(self) -> None:
        """Clear all repository instances."""
        self._repositories.clear()
        logger.info("Cleared all repository instances")


# Global repository container instance
_container = RepositoryContainer()


def get_repository_container() -> RepositoryContainer:
    """Get the global repository container instance.
    
    Returns:
        Global repository container
    """
    return _container


def configure_repositories(config: Dict[str, Any]) -> None:
    """Configure the global repository container.
    
    Args:
        config: Repository configuration dictionary
    """
    _container.configure(config)


def get_repository(name: str = 'default') -> BaseRepository:
    """Get a repository instance from the global container.
    
    Args:
        name: Name of the repository instance
        
    Returns:
        Repository instance
    """
    return _container.get_repository(name)


def set_repository(repository: BaseRepository, name: str = 'default') -> None:
    """Set a repository instance in the global container.
    
    Args:
        repository: Repository instance to set
        name: Name for the repository instance
    """
    _container.set_repository(repository, name)
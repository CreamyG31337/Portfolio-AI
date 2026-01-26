"""Tests for menu integration and script execution.

These tests validate that all menu options work correctly and don't have
import errors or missing function issues. This should catch the types of
bugs we just fixed.
"""

import pytest
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
import tempfile
import shutil

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


class TestMenuIntegration:
    """Test that all menu options execute without import errors."""
    
    def setup_method(self):
        """Set up test environment."""
        # Create isolated test directory - NEVER use real data
        self.test_data_dir = Path(tempfile.mkdtemp(prefix="test_trading_"))
        self.project_root = Path(__file__).parent.parent
        
        # Create minimal test data structure
        self.test_data_dir.mkdir(parents=True, exist_ok=True)
        (self.test_data_dir / "cash_balances.json").write_text('{"CAD": 0, "USD": 0, "last_updated": "2025-01-01T00:00:00Z"}')
        (self.test_data_dir / "fund_contributions.csv").write_text("Date,Amount,Currency,Type,Notes\n")
        (self.test_data_dir / "llm_trade_log.csv").write_text("Date,Ticker,Shares,Price,Cost Basis,PnL,Reason,Currency\n")
        (self.test_data_dir / "llm_portfolio_update.csv").write_text("Date,Ticker,Shares,Average Price,Cost Basis,Stop Loss,Current Price,Total Value,PnL,Action,Company,Currency\n")
    
    def teardown_method(self):
        """Clean up test environment."""
        # Clean up isolated test directory
        if self.test_data_dir.exists():
            shutil.rmtree(self.test_data_dir)
    
    def test_main_trading_script_imports(self):
        """Test that the main trading script can be imported without errors."""
        try:
            import trading_script
            assert hasattr(trading_script, 'main')
        except ImportError as e:
            pytest.fail(f"Failed to import trading_script: {e}")
    
    def test_prompt_generator_imports(self):
        """Test that prompt_generator can be imported without errors."""
        try:
            import prompt_generator
            assert hasattr(prompt_generator, 'PromptGenerator')
            assert hasattr(prompt_generator, 'generate_daily_prompt')
        except ImportError as e:
            pytest.fail(f"Failed to import prompt_generator: {e}")
    
    def test_update_cash_imports(self):
        """Test that update_cash can be imported without errors."""
        try:
            import update_cash
            assert hasattr(update_cash, 'main')
            assert hasattr(update_cash, 'calculate_fund_contributions_total')
        except ImportError as e:
            pytest.fail(f"Failed to import update_cash: {e}")
    
    def test_show_prompt_imports(self):
        """Test that show_prompt can be imported without errors."""
        try:
            import show_prompt
            # Check that key functions exist
            assert hasattr(show_prompt, 'calculate_position_metrics')
            assert hasattr(show_prompt, 'main')
        except ImportError as e:
            pytest.fail(f"Failed to import show_prompt: {e}")
    
    def test_prompt_generator_execution(self):
        """Test that prompt_generator can execute without crashing."""
        # Test that the script can at least start and validate command line arguments
        # without timing out on network requests
        cmd = [
            sys.executable, 
            str(self.project_root / "prompt_generator.py"),
            "--help"  # Just test help output to avoid network timeouts
        ]
        
        try:
            result = subprocess.run(
                cmd, 
                capture_output=True, 
                text=True, 
                timeout=10,  # Short timeout for help
                cwd=self.project_root
            )
            
            # Should not crash with import errors
            assert "ImportError" not in result.stderr
            assert "ModuleNotFoundError" not in result.stderr
            
            # Should show help output
            assert "usage:" in result.stdout.lower() or "generate llm trading prompts" in result.stdout.lower()
            
        except subprocess.TimeoutExpired:
            pytest.fail("prompt_generator.py --help execution timed out")
        except Exception as e:
            pytest.fail(f"Failed to execute prompt_generator.py --help: {e}")
    
    def test_update_cash_execution(self):
        """Test that update_cash can execute without crashing."""
        cmd = [
            sys.executable, 
            str(self.project_root / "update_cash.py"),
            "--data-dir", str(self.test_data_dir)
        ]
        
        try:
            # Use echo to provide 'q' input to quit immediately
            if sys.platform == "win32":
                echo_cmd = ["cmd", "/c", "echo", "q"]
            else:
                echo_cmd = ["echo", "q"]
            
            # Run echo and pipe to update_cash
            echo_process = subprocess.Popen(echo_cmd, stdout=subprocess.PIPE)
            result = subprocess.run(
                cmd,
                stdin=echo_process.stdout,
                capture_output=True,
                text=True,
                timeout=15,
                cwd=self.project_root
            )
            echo_process.stdout.close()
            
            # Should not crash with import errors
            assert "ImportError" not in result.stderr
            assert "ModuleNotFoundError" not in result.stderr
            
            # Should show the cash balance utility
            assert "Cash Balance Update Utility" in result.stdout
            
        except subprocess.TimeoutExpired:
            pytest.fail("update_cash.py execution timed out")
        except Exception as e:
            pytest.fail(f"Failed to execute update_cash.py: {e}")
    
    def test_show_prompt_execution(self):
        """Test that show_prompt can execute without crashing."""
        cmd = [
            sys.executable,
            str(self.project_root / "show_prompt.py"),
            "--data-dir", str(self.test_data_dir)
        ]
        
        try:
            result = subprocess.run(
                cmd, 
                capture_output=True, 
                text=True, 
                timeout=30,
                cwd=self.project_root
            )
            
            # Should not crash with import errors
            assert "ImportError" not in result.stderr
            assert "ModuleNotFoundError" not in result.stderr
            
            # Should produce some output
            assert len(result.stdout) > 0
            
            # Should contain expected elements
            assert "COMPLETE LLM PROMPT" in result.stdout
            assert "Daily Results" in result.stdout
            
        except subprocess.TimeoutExpired:
            pytest.fail("show_prompt.py execution timed out")
        except Exception as e:
            pytest.fail(f"Failed to execute show_prompt.py: {e}")
    
    def test_trading_script_execution_with_empty_input(self):
        """Test that trading_script can execute without crashing."""
        cmd = [
            sys.executable, 
            str(self.project_root / "trading_script.py"),
            str(self.test_data_dir)
        ]
        
        try:
            # Provide empty input (just Enter) to continue through the menu
            # Use UTF-8 encoding to handle Unicode characters properly on Windows
            result = subprocess.run(
                cmd,
                input="\\n",  # Just press Enter
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',  # Replace invalid characters instead of failing
                timeout=30,
                cwd=self.project_root
            )
            
            # Should not crash with import errors
            if result.stderr:
                assert "ImportError" not in result.stderr
                assert "ModuleNotFoundError" not in result.stderr
            
            # Should show portfolio summary (if stdout is available)
            if result.stdout:
                assert "Portfolio Summary" in result.stdout or "Trading Actions" in result.stdout
            else:
                # If stdout is None, check return code instead
                assert result.returncode == 0 or result.returncode is None
            
        except subprocess.TimeoutExpired:
            pytest.fail("trading_script.py execution timed out")
        except Exception as e:
            pytest.fail(f"Failed to execute trading_script.py: {e}")


class TestTradingInterfaceIntegration:
    """Test trading interface integration with actual components."""
    
    def setup_method(self):
        """Set up test environment."""
        # Create isolated test directory - NEVER use real data
        self.test_data_dir = Path(tempfile.mkdtemp(prefix="test_trading_"))
        self.test_data_dir.mkdir(parents=True, exist_ok=True)
        (self.test_data_dir / "cash_balances.json").write_text('{"CAD": 0, "USD": 0, "last_updated": "2025-01-01T00:00:00Z"}')
        (self.test_data_dir / "fund_contributions.csv").write_text("Date,Amount,Currency,Type,Notes\n")
        (self.test_data_dir / "llm_trade_log.csv").write_text("Date,Ticker,Shares,Price,Cost Basis,PnL,Reason,Currency\n")
        (self.test_data_dir / "llm_portfolio_update.csv").write_text("Date,Ticker,Shares,Average Price,Cost Basis,Stop Loss,Current Price,Total Value,PnL,Action,Company,Currency\n")
        
        # Import required modules
        from data.repositories.csv_repository import CSVRepository
        from portfolio.trade_processor import TradeProcessor
        from portfolio.trading_interface import TradingInterface
        
        self.repository = CSVRepository(fund_name="TEST", data_directory=str(self.test_data_dir))
        self.trade_processor = TradeProcessor(self.repository)
        self.trading_interface = TradingInterface(self.repository, self.trade_processor)
    
    def teardown_method(self):
        """Clean up test environment."""
        # Clean up isolated test directory
        if self.test_data_dir.exists():
            shutil.rmtree(self.test_data_dir)
    
    def test_trading_interface_initialization(self):
        """Test that trading interface initializes correctly."""
        assert self.trading_interface is not None
        assert self.trading_interface.repository is not None
        assert self.trading_interface.trade_processor is not None
    
    def test_contribution_logging_with_mock_input(self):
        """Test contribution logging with mocked user input."""
        # First set up a test contributor by creating fund_contributions.csv with contributor data
        fund_file = self.test_data_dir / "fund_contributions.csv"
        fund_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Create initial contributor data
        import pandas as pd
        test_contributors = pd.DataFrame({
            'Timestamp': ['2024-01-01 10:00:00'],
            'Contributor': ['Test Contributor'],
            'Amount': [0.01],  # Minimal setup amount
            'Type': ['CONTRIBUTION'],
            'Notes': ['Initial setup'],
            'Email': ['test@example.com']
        })
        test_contributors.to_csv(fund_file, index=False)
        
        with patch('builtins.input') as mock_input:
            mock_input.side_effect = ["1", "100.50", "Test contribution notes"]
            
            result = self.trading_interface.log_contribution()
            assert result is True
            
            # Verify contribution was saved
            assert fund_file.exists()
            
            # Verify the new contribution was added
            updated_df = pd.read_csv(fund_file)
            assert len(updated_df) == 2  # Original setup + new contribution
            assert updated_df.iloc[1]['Amount'] == 100.50
    
    def test_cash_balance_update_with_mock_input(self):
        """Test cash balance update with mocked user input."""
        with patch('builtins.input') as mock_input:
            mock_input.side_effect = ["a", "500.00", "Test deposit"]
            
            result = self.trading_interface.update_cash_balances()
            assert result is True
            
            # Verify cash balance was saved
            cash_file = self.test_data_dir / "cash_balances.json"
            assert cash_file.exists()


class TestModularComponentIntegration:
    """Test that modular components work together correctly."""
    
    def setup_method(self):
        """Set up test environment."""
        # Create isolated test directory - NEVER use real data
        self.test_data_dir = Path(tempfile.mkdtemp(prefix="test_trading_"))
        self.test_data_dir.mkdir(parents=True, exist_ok=True)
        (self.test_data_dir / "cash_balances.json").write_text('{"CAD": 0, "USD": 0, "last_updated": "2025-01-01T00:00:00Z"}')
        (self.test_data_dir / "fund_contributions.csv").write_text("Date,Amount,Currency,Type,Notes\n")
        (self.test_data_dir / "llm_trade_log.csv").write_text("Date,Ticker,Shares,Price,Cost Basis,PnL,Reason,Currency\n")
        (self.test_data_dir / "llm_portfolio_update.csv").write_text("Date,Ticker,Shares,Average Price,Cost Basis,Stop Loss,Current Price,Total Value,PnL,Action,Company,Currency\n")
    
    def test_portfolio_manager_with_repository(self):
        """Test portfolio manager integration with repository."""
        from data.repositories.csv_repository import CSVRepository
        from portfolio.portfolio_manager import PortfolioManager
        from portfolio.fund_manager import Fund
        
        repository = CSVRepository(fund_name="TEST", data_directory=str(self.test_data_dir))
        # Create a mock fund for testing
        mock_fund = Fund(
            id="test",
            name="TEST",
            description="Test Fund"
        )
        portfolio_manager = PortfolioManager(repository, mock_fund)
        
        # Should be able to load portfolio without errors
        snapshots = portfolio_manager.load_portfolio()
        assert isinstance(snapshots, list)
        
        # Should be able to get latest portfolio
        latest = portfolio_manager.get_latest_portfolio()
        # latest can be None if no data exists, that's okay
    
    def test_market_hours_functionality(self):
        """Test market hours component functionality."""
        from market_data.market_hours import MarketHours
        
        market_hours = MarketHours()
        
        # Should be able to get trading day window
        start, end = market_hours.trading_day_window()
        assert start is not None
        assert end is not None
        assert start <= end
        
        # Should be able to get last trading date
        last_date = market_hours.last_trading_date()
        assert last_date is not None
        
        # Should be able to get date string
        date_str = market_hours.last_trading_date_str()
        assert isinstance(date_str, str)
        assert len(date_str) > 0
    
    def test_market_data_fetcher_initialization(self):
        """Test market data fetcher initialization."""
        from market_data.data_fetcher import MarketDataFetcher
        from market_data.price_cache import PriceCache
        
        price_cache = PriceCache()
        market_data_fetcher = MarketDataFetcher(cache_instance=price_cache)
        
        assert market_data_fetcher is not None
        assert market_data_fetcher.cache is not None
    
    def test_settings_and_constants_availability(self):
        """Test that settings and constants are available."""
        from config.settings import get_settings
        from config.constants import VERSION, LOG_FILE
        
        settings = get_settings()
        assert settings is not None
        
        # Test that important constants are still available
        assert VERSION is not None
        assert isinstance(VERSION, str)
        assert LOG_FILE is not None
        assert isinstance(LOG_FILE, str)


class TestErrorHandlingAndValidation:
    """Test error handling and validation in menu scripts."""
    
    def test_prompt_generator_with_invalid_data_dir(self):
        """Test prompt generator handles invalid data directory gracefully."""
        from prompt_generator import PromptGenerator

        # Should not crash with non-existent directory
        invalid_dir = Path("non_existent_directory_12345")
        # PromptGenerator should now initialize successfully with fallback fund
        try:
            generator = PromptGenerator(invalid_dir)
            # Should initialize without failing
            assert generator is not None
            assert hasattr(generator, 'portfolio_manager')
        except Exception as e:
            # Should not fail during initialization
            pytest.fail(f"PromptGenerator failed to initialize: {e}")
        
        # Should handle missing portfolio data gracefully
        # This should not raise an exception
        try:
            generator.generate_daily_prompt()
        except SystemExit:
            # It's okay if it exits gracefully
            pass
        except Exception as e:
            # Should not crash with unhandled exceptions
            pytest.fail(f"PromptGenerator crashed with unhandled exception: {e}")
    
    def test_update_cash_with_invalid_data_dir(self):
        """Test update_cash handles invalid data directory gracefully."""
        from update_cash import calculate_fund_contributions_total
        
        # Should return 0.0 for non-existent directory
        invalid_dir = Path("non_existent_directory_12345")
        result = calculate_fund_contributions_total(invalid_dir)
        assert result == 0.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
"""Lot tracking models for FIFO-based P&L calculation.

This module implements industry-standard lot tracking for accurate
profit/loss calculation with partial sells and re-buys.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Dict, Optional, Any, List
from uuid import uuid4


@dataclass
class Lot:
    """Represents a single lot (purchase batch) of shares.
    
    Each lot tracks:
    - Original purchase details
    - Remaining shares (after partial sells)
    - Realized P&L from sells
    """
    lot_id: str
    ticker: str
    shares: Decimal  # Original shares purchased
    remaining_shares: Decimal  # Shares still held
    price: Decimal  # Purchase price per share
    cost_basis: Decimal  # Total cost basis for this lot
    purchase_date: datetime
    currency: str = "CAD"
    
    def __post_init__(self):
        """Calculate cost basis if not provided."""
        if self.cost_basis == 0:
            self.cost_basis = self.shares * self.price
    
    @property
    def is_fully_sold(self) -> bool:
        """Check if all shares in this lot have been sold."""
        return self.remaining_shares <= 0
    
    @property
    def remaining_cost_basis(self) -> Decimal:
        """Calculate remaining cost basis for unsold shares."""
        if self.shares == 0:
            return Decimal('0')
        return (self.remaining_shares / self.shares) * self.cost_basis
    
    def sell_shares(self, shares_to_sell: Decimal, sell_price: Decimal) -> Dict[str, Any]:
        """Sell shares from this lot using FIFO.
        
        Args:
            shares_to_sell: Number of shares to sell
            sell_price: Price per share at sale
            
        Returns:
            Dictionary with sale details and P&L
        """
        if shares_to_sell > self.remaining_shares:
            raise ValueError(f"Cannot sell {shares_to_sell} shares, only {self.remaining_shares} remaining")
        
        # Calculate cost basis for sold shares
        cost_basis_sold = (shares_to_sell / self.shares) * self.cost_basis
        proceeds = shares_to_sell * sell_price
        realized_pnl = proceeds - cost_basis_sold
        
        # Update remaining shares
        self.remaining_shares -= shares_to_sell
        
        return {
            'lot_id': self.lot_id,
            'ticker': self.ticker,
            'shares_sold': shares_to_sell,
            'sell_price': sell_price,
            'cost_basis_sold': cost_basis_sold,
            'proceeds': proceeds,
            'realized_pnl': realized_pnl,
            'remaining_shares': self.remaining_shares,
            'is_fully_sold': self.is_fully_sold
        }
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'lot_id': self.lot_id,
            'ticker': self.ticker,
            'shares': float(self.shares),
            'remaining_shares': float(self.remaining_shares),
            'price': float(self.price),
            'cost_basis': float(self.cost_basis),
            'purchase_date': self.purchase_date.isoformat(),
            'currency': self.currency
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Lot:
        """Create Lot from dictionary."""
        purchase_date = data['purchase_date']
        if isinstance(purchase_date, str):
            purchase_date = datetime.fromisoformat(purchase_date)
        
        return cls(
            lot_id=data['lot_id'],
            ticker=data['ticker'],
            shares=Decimal(str(data['shares'])),
            remaining_shares=Decimal(str(data['remaining_shares'])),
            price=Decimal(str(data['price'])),
            cost_basis=Decimal(str(data['cost_basis'])),
            purchase_date=purchase_date,
            currency=data.get('currency', 'CAD')
        )


@dataclass
class LotTracker:
    """Tracks lots for a specific ticker using FIFO method."""
    ticker: str
    lots: List[Lot] = None
    
    def __post_init__(self):
        if self.lots is None:
            self.lots = []
    
    def add_lot(self, shares: Decimal, price: Decimal, purchase_date: datetime, 
                currency: str = "CAD") -> Lot:
        """Add a new lot (purchase)."""
        lot = Lot(
            lot_id=str(uuid4()),
            ticker=self.ticker,
            shares=shares,
            remaining_shares=shares,
            price=price,
            cost_basis=shares * price,
            purchase_date=purchase_date,
            currency=currency
        )
        self.lots.append(lot)
        return lot
    
    def sell_shares_fifo(self, shares_to_sell: Decimal, sell_price: Decimal, 
                        sell_date: datetime) -> List[Dict[str, Any]]:
        """Sell shares using FIFO method.
        
        Args:
            shares_to_sell: Total shares to sell
            sell_price: Price per share
            sell_date: Date of sale
            
        Returns:
            List of sale details for each lot affected
        """
        remaining_to_sell = shares_to_sell
        sales = []
        
        # Sort lots by purchase date (FIFO)
        sorted_lots = sorted(self.lots, key=lambda x: x.purchase_date)
        
        for lot in sorted_lots:
            if remaining_to_sell <= 0:
                break
                
            if lot.remaining_shares > 0:
                # Sell from this lot
                shares_from_this_lot = min(remaining_to_sell, lot.remaining_shares)
                sale_details = lot.sell_shares(shares_from_this_lot, sell_price)
                sale_details['sell_date'] = sell_date.isoformat()
                sales.append(sale_details)
                remaining_to_sell -= shares_from_this_lot
        
        if remaining_to_sell > 0:
            raise ValueError(f"Insufficient shares to sell {shares_to_sell} shares of {self.ticker}")
        
        return sales
    
    def get_total_remaining_shares(self) -> Decimal:
        """Get total remaining shares across all lots."""
        return sum(lot.remaining_shares for lot in self.lots)
    
    def get_total_remaining_cost_basis(self) -> Decimal:
        """Get total remaining cost basis across all lots."""
        return sum(lot.remaining_cost_basis for lot in self.lots)
    
    def get_average_cost_basis(self) -> Decimal:
        """Get average cost basis for remaining shares."""
        total_shares = self.get_total_remaining_shares()
        if total_shares == 0:
            return Decimal('0')
        return self.get_total_remaining_cost_basis() / total_shares
    
    def get_realized_pnl_summary(self) -> Dict[str, Any]:
        """Not supported on LotTracker — use FIFOTradeProcessor instead.

        LotTracker only retains each lot's *remaining* shares; it never records
        sale proceeds, so realized P&L cannot be derived from its state. The
        working implementation is FIFOTradeProcessor.get_realized_pnl_summary(),
        which reads it back from trade history. Fail loud so a stray call can't
        silently return zeros.
        """
        raise NotImplementedError(
            "Use FIFOTradeProcessor.get_realized_pnl_summary(); LotTracker does not "
            "retain sale records to compute realized P&L."
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'ticker': self.ticker,
            'lots': [lot.to_dict() for lot in self.lots]
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> LotTracker:
        """Create LotTracker from dictionary."""
        lots = [Lot.from_dict(lot_data) for lot_data in data.get('lots', [])]
        return cls(
            ticker=data['ticker'],
            lots=lots
        )

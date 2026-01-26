# Webull Import System Documentation

## Overview

The Webull Import System allows you to import trade data from Webull's desktop application into the LLM Micro-Cap Trading Bot. Since Webull doesn't provide direct CSV export, this system is designed to work with CSV files created from Webull screenshots using AI conversion tools.

## Data Source

The import system is designed to work with trade data from the **Webull Desktop Application**. Since Webull doesn't provide direct CSV export functionality, the data must be obtained through:

**Screenshot to CSV Conversion**: Use AI tools to convert Webull screenshots to CSV format

## Screenshot to CSV Process

Since Webull doesn't offer direct CSV export, follow these steps:

1. **Open Webull Desktop App**: Navigate to your trade history
2. **Take Screenshots**: Capture screenshots of your trade data (you may need multiple screenshots for large datasets)
3. **Use AI Conversion**: Upload screenshots to an AI tool with a prompt like:
   ```
   Convert this Webull trade history screenshot to CSV format with these exact columns:
   Symbol,Side,Filled Qty,Limit Price,Order Type,Order Status,Average Filled Price,Filled Time
   
   Only include filled orders. Ensure timestamps include timezone (EDT/EST).
   ```
4. **Verify Format**: Check that the generated CSV matches the required format exactly
5. **Save and Import**: Save the CSV file and use the import system

## Supported CSV Format

The import system expects CSV files with the following exact column headers:

```csv
Symbol,Side,Filled Qty,Limit Price,Order Type,Order Status,Average Filled Price,Filled Time
```

### Column Descriptions

| Column | Description | Example | Required |
|--------|-------------|---------|----------|
| `Symbol` | Stock ticker symbol | `TSM`, `AMD`, `GOOGL` | Yes |
| `Side` | Trade direction | `Buy`, `Sell` | Yes |
| `Filled Qty` | Number of shares traded | `10`, `26`, `200` | Yes |
| `Limit Price` | Order limit price | `141.490`, `62.700` | Yes |
| `Order Type` | Type of order | `Limit`, `Market` | Yes |
| `Order Status` | Order execution status | `Filled`, `Partial` | Yes |
| `Average Filled Price` | Actual execution price | `141.500`, `62.700` | Yes |
| `Filled Time` | Execution timestamp | `09/03/2025 15:49:04 EDT` | Yes |

### Data Requirements

- **Order Status**: Only `Filled` orders are imported. Partial or unfilled orders are skipped.
- **Timestamp Format**: Must be in format `MM/DD/YYYY HH:MM:SS EDT/EST`
- **Price Format**: Decimal numbers (e.g., `141.500`, `62.700`)
- **Quantity Format**: Integer numbers (e.g., `10`, `26`, `200`)
- **Currency**: All prices are assumed to be in USD

## Example CSV Data

```csv
Symbol,Side,Filled Qty,Limit Price,Order Type,Order Status,Average Filled Price,Filled Time
TSM,Sell,10,141.490,Limit,Filled,141.500,09/03/2025 15:49:04 EDT
MU,Buy,10,141.500,Limit,Filled,141.500,09/03/2025 15:22:20 EDT
AMD,Buy,10,62.700,Limit,Filled,62.700,09/03/2025 14:10:01 EDT
GOOGL,Buy,4,180.000,Limit,Filled,180.000,09/03/2025 04:14:10 EDT
```

## Import Methods

### 1. Command Line Interface

Use the dedicated import script for batch processing:

```bash
# Preview import (dry run)
python scripts/webull_import.py webull_data.csv --dry-run

# Import into specific fund
python scripts/webull_import.py webull_data.csv --fund "RRSP Lance Webull"

# Import into active fund
python scripts/webull_import.py webull_data.csv

# List available funds
python scripts/webull_import.py --list-funds
```

### 2. Trading Bot Interface

Access through the main trading bot menu:

1. Run the trading bot: `python trading_script.py`
2. Select `4` (Configuration)
3. Select `4` (Fund Management)
4. Select `5` (Import Fund Data)
5. Select `1` (Import Webull Trade Data)
6. Enter the path to your CSV file
7. Choose to preview first or import directly

### 3. Programmatic Import

Use the import system in your own scripts:

```python
from utils.webull_importer import import_webull_data

# Preview import
results = import_webull_data("webull_data.csv", dry_run=True)

# Actual import
results = import_webull_data("webull_data.csv", fund_name="RRSP Lance Webull")
```

## Data Processing

### Trade Validation

The import system performs several validation checks:

- **Required Fields**: Ensures all required columns are present
- **Data Types**: Validates quantity and price formats
- **Order Status**: Only imports filled orders
- **Duplicate Detection**: Identifies potential duplicate trades
- **Price Validation**: Flags unusually high or low prices
- **Quantity Validation**: Ensures positive quantities

### Portfolio Updates

The system automatically updates your portfolio based on imported trades:

- **Buy Orders**: Add or increase positions
- **Sell Orders**: Reduce or close positions
- **Average Price Calculation**: Updates cost basis and average prices
- **P&L Calculation**: Recalculates profit/loss for each position

### Data Integration

Imported data is integrated into the existing trading system:

- **Trade Log**: All trades are added to `llm_trade_log.csv`
- **Portfolio**: Positions are updated in `llm_portfolio_update.csv`
- **Currency**: All prices are stored in USD (can be converted to fund currency)
- **Timestamps**: Converted to local timezone

## Error Handling

### Common Issues

1. **Invalid Timestamp Format**
   - Error: `Invalid timestamp format: 09/03/2025 15:49:04 EDT`
   - Solution: Ensure timestamp includes timezone (EDT/EST)

2. **Missing Required Fields**
   - Error: `Missing required fields`
   - Solution: Verify all required columns are present

3. **Invalid Order Status**
   - Error: `Order not filled (status: Partial)`
   - Solution: Only filled orders are imported

4. **File Not Found**
   - Error: `CSV file not found`
   - Solution: Check file path and permissions

### Validation Warnings

The system may show warnings for:

- Duplicate trades
- Unusually high/low prices
- Large quantities
- Missing data

These warnings don't prevent import but should be reviewed.

## Best Practices

### Data Preparation

1. **Screenshot from Webull**: Take screenshots of your trade history from the Webull desktop app
2. **AI Conversion**: Use AI tools to convert screenshots to CSV format
3. **Format Verification**: Ensure the converted CSV matches the required format exactly
4. **Data Validation**: Review the preview before importing
5. **Backup Data**: Always backup existing data before large imports

### Import Strategy

1. **Preview First**: Always use `--dry-run` or preview option first
2. **Small Batches**: Import data in smaller batches for large datasets
3. **Verify Results**: Check portfolio and trade log after import
4. **Test Environment**: Test imports on a copy of your data first

### File Management

1. **Naming Convention**: Use descriptive names like `webull_2025_09_03.csv`
2. **Storage Location**: Store import files in a dedicated `import_data/` folder
3. **Version Control**: Keep import files for audit purposes (but gitignore them)
4. **Cleanup**: Remove old import files after successful import

## Troubleshooting

### Import Fails

1. Check CSV format matches exactly
2. Verify all required columns are present
3. Ensure file permissions allow reading
4. Check for special characters in file path

### Data Issues

1. Review validation warnings
2. Check for duplicate trades
3. Verify timestamp formats
4. Ensure quantities are positive integers

### Portfolio Discrepancies

1. Compare with original Webull data
2. Check for missing trades
3. Verify average price calculations
4. Review sell order processing

## Support

For issues with the Webull import system:

1. Check the validation output for specific errors
2. Review the CSV format against the documentation
3. Test with a small sample of data first
4. Use the preview mode to identify issues

## Security Notes

- Import files are automatically gitignored to protect sensitive trading data
- All imported data is stored locally in the fund's directory
- No data is transmitted to external services during import
- Backup your data before performing large imports

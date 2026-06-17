# Plotly Serialization in Flask

## Overview

Flask API routes that return Plotly charts **must** use `plotly_utils.serialize_plotly_figure()` so numpy arrays become JSON-safe native types before the browser parses them.

## Why This Is Needed

`PlotlyJSONEncoder` can emit numpy arrays in a binary JSON shape (`dtype` + `bdata`). Browsers cannot parse that — charts show wrong values (e.g. 1, 2, 3 instead of real prices).

### The Problem

When `PlotlyJSONEncoder` encounters numpy arrays, it may serialize them as:
```json
{
  "dtype": "f8",
  "bdata": "base64-encoded-binary-data"
}
```

JavaScript's `JSON.parse()` cannot handle this format, causing:
- Chart values to be parsed incorrectly
- Sequential values like 1, 2, 3, 4 instead of actual data
- Charts failing to render properly

## Solution

Use the shared `plotly_utils` module to serialize Plotly figures:

```python
from plotly_utils import serialize_plotly_figure
from flask import Response

# Create your Plotly figure
fig = create_portfolio_value_chart(...)

# Serialize with proper numpy conversion
chart_json = serialize_plotly_figure(fig)

# Return as Flask Response
return Response(chart_json, mimetype='application/json')
```

## API Reference

### `serialize_plotly_figure(fig, pre_convert_traces=True)`

Serializes a Plotly figure to JSON string with proper numpy array conversion.

**Parameters:**
- `fig` (go.Figure): Plotly Figure object
- `pre_convert_traces` (bool): If True, converts numpy arrays in traces before JSON encoding (faster, but may miss nested structures). Default: True

**Returns:**
- `str`: JSON string ready for Flask Response

**Example:**
```python
from plotly_utils import serialize_plotly_figure
from chart_utils import create_portfolio_value_chart

fig = create_portfolio_value_chart(df, show_normalized=True)
chart_json = serialize_plotly_figure(fig)
return Response(chart_json, mimetype='application/json')
```

### `convert_numpy_to_list(obj)`

Recursively converts numpy arrays, numpy scalars, and datetime objects to Python native types.

**Parameters:**
- `obj`: Any object that may contain numpy types

**Returns:**
- Object with all numpy types converted to Python native types

**Use Cases:**
- Converting already-serialized chart data (e.g., after applying theme)
- Manual conversion of specific data structures

**Example:**
```python
from plotly_utils import convert_numpy_to_list
import json

# After applying theme to chart_data dict
chart_data = json.loads(json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder))
chart_data = convert_numpy_to_list(chart_data)  # Convert any remaining numpy types
return Response(json.dumps(chart_data), mimetype='application/json')
```

## Where to Use

**✅ ALWAYS use `serialize_plotly_figure()` when:**
- Creating new Flask routes that return Plotly charts
- Serializing Plotly figures for JSON responses
- Caching Plotly chart data

**✅ Use `convert_numpy_to_list()` when:**
- You've already serialized with `PlotlyJSONEncoder` and need to convert the result
- Applying theme changes to already-serialized chart data
- Working with chart data dictionaries directly

## Files Using This

- `web_dashboard/routes/dashboard_routes.py` - Performance and sector charts
- `web_dashboard/app.py` - Ticker price charts
- Any new routes that return Plotly charts

## Testing

After implementing, verify:
1. Charts display correct values (starting at 100 for normalized charts)
2. No console errors in browser developer tools
3. Chart data is valid JSON (check Network tab)
4. Values match expected chart data from tests or manual spot-check

## Common Mistakes

❌ **DON'T:**
```python
return json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)  # Missing conversion!
```

✅ **DO:**
```python
from plotly_utils import serialize_plotly_figure
return serialize_plotly_figure(fig)
```

## Related Files

- `web_dashboard/plotly_utils.py` — serialization utilities
- `web_dashboard/chart_utils.py` — chart creation functions

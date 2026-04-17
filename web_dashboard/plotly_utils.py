"""
Plotly Serialization Utilities for Flask
=========================================

When porting Plotly charts from Streamlit to Flask, numpy arrays must be explicitly
converted to Python native types before JSON serialization.

WHY THIS IS NEEDED:
-------------------
- Streamlit's `st.plotly_chart()` automatically handles numpy array conversion internally
- Flask requires manual serialization using `PlotlyJSONEncoder`, which can serialize
  numpy arrays in binary format that JavaScript cannot parse correctly
- This causes charts to display incorrect values (e.g., 1, 2, 3, 4 instead of 100, 101, 102)

USAGE:
------
    from plotly_utils import serialize_plotly_figure
    
    fig = create_portfolio_value_chart(...)
    chart_json = serialize_plotly_figure(fig)
    return Response(chart_json, mimetype='application/json')
"""

import json
import logging
import math
import numpy as np
import pandas as pd
from datetime import datetime as dt
from typing import Any, Union
import plotly.graph_objs as go

logger = logging.getLogger(__name__)


def convert_datetime_to_str(value: Any) -> Union[str, None]:
    """Convert various datetime types to ISO format string.
    
    Args:
        value: datetime object (pd.Timestamp, np.datetime64, datetime, or None)
        
    Returns:
        ISO format string or None
    """
    if pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, np.datetime64):
        return pd.Timestamp(value).isoformat()
    if isinstance(value, dt):
        return value.isoformat()
    return value


def _json_safe_python_float(value: float) -> float | None:
    """Return a finite float, or None for NaN/Inf (strict JSON has no NaN; browsers reject it)."""
    if math.isnan(value) or math.isinf(value):
        return None
    return value


def convert_numpy_to_list(obj: Any) -> Any:
    """Recursively convert numpy arrays, numpy scalars, and datetime objects to Python native types.
    
    This function handles:
    - numpy arrays (converted to lists)
    - numpy scalars (converted to float/int)
    - datetime objects (converted to ISO strings)
    - Binary-encoded numpy arrays from PlotlyJSONEncoder (decoded and converted)
    
    Args:
        obj: Any object that may contain numpy types
        
    Returns:
        Object with all numpy types converted to Python native types
    """
    if isinstance(obj, dict):
        # Check for numpy array binary format from PlotlyJSONEncoder (fallback)
        if 'dtype' in obj and 'bdata' in obj:
            try:
                import base64
                dtype_map = {'f8': 'd', 'i8': 'q', 'f4': 'f', 'i4': 'i', 'M8': 'M'}  # M8 is datetime64
                dtype_char = dtype_map.get(obj['dtype'], 'd')
                if dtype_char == 'M':
                    # Handle datetime64 arrays
                    decoded = base64.b64decode(obj['bdata'])
                    arr = np.frombuffer(decoded, dtype='datetime64[ns]')
                    return [convert_datetime_to_str(x) for x in arr]
                decoded = base64.b64decode(obj['bdata'])
                arr = np.frombuffer(decoded, dtype=dtype_char)
                return [convert_numpy_to_list(x) for x in arr.tolist()]
            except Exception as e:
                logger.warning(f"Failed to decode numpy array: {e}")
                return []
        return {k: convert_numpy_to_list(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_numpy_to_list(item) for item in obj]
    elif isinstance(obj, (pd.Timestamp, np.datetime64, dt)):
        return convert_datetime_to_str(obj)
    elif isinstance(obj, np.ndarray):
        # Check if it's a datetime64 array
        if np.issubdtype(obj.dtype, np.datetime64):
            return [convert_datetime_to_str(x) for x in obj]
        raw = obj.tolist() if hasattr(obj, 'tolist') else float(obj)
        if isinstance(raw, list):
            return [convert_numpy_to_list(x) for x in raw]
        return convert_numpy_to_list(raw)
    elif isinstance(obj, np.floating):
        return _json_safe_python_float(float(obj))
    elif isinstance(obj, np.integer):
        return int(obj)
    elif isinstance(obj, np.generic):
        conv = obj.tolist() if hasattr(obj, 'tolist') else float(obj)
        return convert_numpy_to_list(conv)
    elif isinstance(obj, float):
        return _json_safe_python_float(obj)
    else:
        return obj


def serialize_plotly_figure(fig: go.Figure, pre_convert_traces: bool = True) -> str:
    """Serialize a Plotly figure to JSON string with proper numpy array conversion.
    
    This is the recommended way to serialize Plotly figures in Flask routes.
    It ensures numpy arrays are converted to Python lists before JSON serialization,
    preventing frontend parsing errors.
    
    Args:
        fig: Plotly Figure object
        pre_convert_traces: If True, converts numpy arrays in traces before JSON encoding
                          (faster, but may miss nested structures)
        
    Returns:
        JSON string ready for Response
    """
    import plotly.utils
    
    # Pre-convert numpy arrays in traces for better performance
    if pre_convert_traces:
        for trace in fig.data:
            if hasattr(trace, 'y') and trace.y is not None:
                if isinstance(trace.y, np.ndarray):
                    trace.y = trace.y.tolist()
                elif hasattr(trace.y, '__iter__') and not isinstance(trace.y, (list, str)):
                    # Handle numpy array-like objects
                    trace.y = [float(x) if isinstance(x, (np.floating, np.integer)) else x for x in trace.y]
            if hasattr(trace, 'x') and trace.x is not None:
                # Convert x-axis (dates) to strings
                if isinstance(trace.x, np.ndarray):
                    # Check if it's datetime64 array
                    if np.issubdtype(trace.x.dtype, np.datetime64):
                        trace.x = [convert_datetime_to_str(x) for x in trace.x]
                    else:
                        trace.x = trace.x.tolist()
                elif hasattr(trace.x, '__iter__') and not isinstance(trace.x, (list, str)):
                    # Convert datetime objects to ISO strings
                    trace.x = [convert_datetime_to_str(x) if isinstance(x, (pd.Timestamp, np.datetime64, dt)) else x for x in trace.x]
    
    # Serialize to JSON using PlotlyJSONEncoder
    chart_data = json.loads(json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder))
    
    # Additional safety: Convert any remaining numpy types and datetime objects
    chart_data = convert_numpy_to_list(chart_data)

    # Browsers reject ``NaN``/``Infinity`` tokens; ``allow_nan=False`` catches any slip-through.
    return json.dumps(chart_data, allow_nan=False)

from fastapi import FastAPI, HTTPException
import httpx
from datetime import datetime, timedelta
import pytz
import logging
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Dict, Any, Optional
import re
import json
import hashlib
from pathlib import Path

app = FastAPI(title="Electricity Price API", 
              description="API that provides electricity price data and color-coded indicators")

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allow all methods
    allow_headers=["*"],  # Allow all headers
)

async def fetch_data(date_str: Optional[str] = None):
    """Fetch data from Elia's API for a given date."""
    if not date_str:
        # Use today's date if not specified
        date_str = datetime.now().strftime("%Y-%m-%d")
    
    url = f"https://griddata.elia.be/eliabecontrols.prod/interface/Interconnections/daily/auctionresultsqh/{date_str}"
    
    logger.info(f"Fetching data from URL: {url}")
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=10.0)
            response.raise_for_status()  # Raise an exception for HTTP errors
            
            # Log response status and size
            content = response.text
            logger.info(f"Response status: {response.status_code}, content size: {len(content)} bytes")
            
            # For debugging purposes, log a small sample of the response
            if content:
                sample = content[:100] + "..." if len(content) > 100 else content
                logger.info(f"Sample response: {sample}")
            else:
                logger.warning("Received empty response from Elia API")
            
            # Check if the response is JSON (which appears to be the case)
            try:
                # Try to parse as JSON first
                json_data = response.json()
                logger.info("Successfully parsed response as JSON")
                return json_data
            except:
                # If not JSON, check if it's XML and try to handle it
                if content.strip().startswith("<"):
                    logger.info("Response appears to be XML, not JSON")
                    raise HTTPException(status_code=415, 
                                        detail="Received XML response from Elia API, but JSON was expected. Try using wget or another tool to fetch the data.")
                # If not XML either, return the raw text
                logger.info("Response is not JSON or XML, returning raw text")
                return content
                
    except httpx.HTTPError as e:
        logger.error(f"HTTP error occurred: {e}")
        raise HTTPException(status_code=503, detail=f"Error fetching data from Elia API: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")

async def fetch_data_for_date_range(start_date: datetime, num_days: int = 3):
    """Fetch data for multiple consecutive days and combine the results."""
    all_data = []
    
    for day_offset in range(num_days):
        # Calculate the date for this offset
        current_date = start_date + timedelta(days=day_offset)
        date_str = current_date.strftime("%Y-%m-%d")
        
        try:
            # Fetch data for this date
            day_data = await fetch_data(date_str)
            if day_data:
                # Append to the combined results
                if isinstance(day_data, list):
                    all_data.extend(day_data)
                else:
                    logger.warning(f"Data for {date_str} is not a list: {type(day_data)}")
            else:
                logger.warning(f"No data available for {date_str}")
        except Exception as e:
            logger.error(f"Error fetching data for {date_str}: {e}")
    
    return all_data

# Global cache for committed colors
committed_colors_cache = {}
cache_file_path = Path("/tmp/committed_colors.json")

def load_committed_colors():
    """Load committed colors from file cache."""
    global committed_colors_cache
    try:
        if cache_file_path.exists():
            with open(cache_file_path, 'r') as f:
                committed_colors_cache = json.load(f)
            logger.info(f"Loaded {len(committed_colors_cache)} committed colors from cache")
        else:
            committed_colors_cache = {}
    except Exception as e:
        logger.error(f"Error loading committed colors: {e}")
        committed_colors_cache = {}

def save_committed_colors():
    """Save committed colors to file cache."""
    try:
        with open(cache_file_path, 'w') as f:
            json.dump(committed_colors_cache, f)
        logger.info(f"Saved {len(committed_colors_cache)} committed colors to cache")
    except Exception as e:
        logger.error(f"Error saving committed colors: {e}")

def get_committed_colors_for_window(commitment_hours: int = 8) -> Dict[str, str]:
    """Get committed colors for the next N hours."""
    now = datetime.now(pytz.UTC).replace(minute=0, second=0, microsecond=0)
    committed_colors = {}
    
    for i in range(commitment_hours):
        target_hour = now + timedelta(hours=i)
        target_key = target_hour.isoformat().replace('+00:00', 'Z')
        
        if target_key in committed_colors_cache:
            committed_colors[target_key] = committed_colors_cache[target_key]
    
    return committed_colors

def commit_colors_for_window(color_codes: List[Dict[str, Any]], commitment_hours: int = 8):
    """Commit colors for the next N hours to ensure stability."""
    global committed_colors_cache
    
    # Load existing committed colors
    load_committed_colors()
    
    # Only commit colors for the first N hours
    for i, color_data in enumerate(color_codes[:commitment_hours]):
        hour_key = color_data["hour"]
        
        # Only commit if not already committed
        if hour_key not in committed_colors_cache:
            committed_colors_cache[hour_key] = color_data["color_code"]
            logger.info(f"Committed color {color_data['color_code']} for hour {hour_key}")
    
    # Clean up old committed colors (older than current time)
    now = datetime.now(pytz.UTC).replace(minute=0, second=0, microsecond=0)
    old_keys = []
    for hour_key in committed_colors_cache:
        try:
            hour_time = datetime.fromisoformat(hour_key.replace('Z', '+00:00'))
            if hour_time < now:
                old_keys.append(hour_key)
        except Exception as e:
            logger.error(f"Error parsing hour key {hour_key}: {e}")
            old_keys.append(hour_key)
    
    for key in old_keys:
        del committed_colors_cache[key]
        logger.info(f"Removed old committed color for hour {key}")
    
    # Save to file
    save_committed_colors()

def apply_committed_colors(color_codes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Apply committed colors to the color codes, preserving stability."""
    committed_colors = get_committed_colors_for_window()
    
    for color_data in color_codes:
        hour_key = color_data["hour"]
        if hour_key in committed_colors:
            original_color = color_data["color_code"]
            committed_color = committed_colors[hour_key]
            
            if original_color != committed_color:
                logger.info(f"Using committed color {committed_color} instead of calculated {original_color} for hour {hour_key}")
                color_data["color_code"] = committed_color
                color_data["committed"] = True
            else:
                color_data["committed"] = True
        else:
            color_data["committed"] = False
    
    return color_codes

def group_entries_by_hour(entries: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Group 15-minute entries into hourly data points."""
    hourly_data = {}
    
    for entry in entries:
        # Extract the hour part from the timestamp
        dt = datetime.fromisoformat(entry["dateTime"].replace('Z', '+00:00'))
        hour_key = dt.replace(minute=0, second=0, microsecond=0).isoformat().replace('+00:00', 'Z')
        
        if hour_key not in hourly_data:
            hourly_data[hour_key] = {
                "dateTime": hour_key,
                "prices": [],
                "avgPrice": 0
            }
        
        hourly_data[hour_key]["prices"].append(entry["price"])
    
    # Calculate average price for each hour
    for hour_key, data in hourly_data.items():
        if data["prices"]:
            data["avgPrice"] = sum(data["prices"]) / len(data["prices"])
        
        # Remove the individual prices from the final output
        data.pop("prices")
    
    return hourly_data

def get_current_and_future_hours(hourly_data: Dict[str, Dict[str, Any]], hours: int = 12) -> List[Dict[str, Any]]:
    """Get current hour and future hours data."""
    now = datetime.now(pytz.UTC).replace(minute=0, second=0, microsecond=0)
    result = []
    
    for i in range(hours):
        target_hour = now + timedelta(hours=i)
        target_key = target_hour.isoformat().replace('+00:00', 'Z')
        
        if target_key in hourly_data:
            result.append(hourly_data[target_key])
        else:
            logger.warning(f"Data for hour {target_key} not found in dataset")
    
    return result

def determine_color_codes(hourly_data: List[Dict[str, Any]], reference_window_hours: int = 48) -> List[Dict[str, Any]]:
    """Determine color codes for all hours in the window using extended reference window."""
    if not hourly_data:
        raise HTTPException(status_code=404, detail="No data available for the requested time period")
    
    # Use extended reference window for more stable color calculations
    # This ensures colors are based on a broader price context
    reference_data = hourly_data[:reference_window_hours] if len(hourly_data) >= reference_window_hours else hourly_data
    
    # Extract prices from reference window
    reference_prices = [entry["avgPrice"] for entry in reference_data]
    
    # Find min and max prices across the reference window
    min_price = min(reference_prices)
    max_price = max(reference_prices)
    
    # Calculate range and thresholds based on the extended reference window
    price_range = max_price - min_price
    
    # Initialize result list
    hourly_color_codes = []
    
    # Determine color code for each hour
    for hour_data in hourly_data:
        hour_price = hour_data["avgPrice"]
        
        # Avoid division by zero if all prices are the same
        if price_range == 0:
            color_code = "G"  # Default to green if all prices are equal
        else:
            lower_threshold = min_price + (price_range / 3)
            upper_threshold = max_price - (price_range / 3)
            
            if hour_price <= lower_threshold:
                color_code = "G"  # Green for cheapest third
            elif hour_price <= upper_threshold:
                color_code = "Y"  # Yellow for middle third
            else:
                color_code = "R"  # Red for most expensive third
        
        # Add to result
        hourly_color_codes.append({
            "hour": hour_data["dateTime"],
            "color_code": color_code
        })
    
    return hourly_color_codes

@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "message": "Electricity Price API",
        "endpoints": {
            "/api/json": "Get electricity price data in JSON format (Optional query param: date=YYYY-MM-DD)",
            "/api/color-code": "Get color codes for current hour and next 11 hours (Optional query param: date=YYYY-MM-DD)",
            "/api/sample": "Get sample electricity price data for testing",
            "/api/sample-color-code": "Get sample color codes for current hour and next 11 hours",
            "/docs": "API documentation (Swagger UI)"
        }
    }

@app.get("/api/json")
async def get_json_data(date: Optional[str] = None):
    """
    Get electricity price data in JSON format.
    
    Optional query parameter:
    - date: Date in YYYY-MM-DD format
    """
    # Validate date format if provided
    if date and not re.match(r'^\d{4}-\d{2}-\d{2}$', date):
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
    
    # For testing, can use the sample data from the uploaded document
    use_sample_data = False  # Set to True to use sample data
    
    if use_sample_data:
        # Use sample data from the provided document
        try:
            with open("sample_data.json", "r") as f:
                json_data = json.load(f)
            logger.info("Using sample data from file")
        except Exception as e:
            logger.error(f"Error loading sample data: {e}")
            raise HTTPException(status_code=500, detail=f"Error loading sample data: {str(e)}")
    else:
        # Fetch from API - now handling JSON directly
        json_data = await fetch_data(date)
    
    try:
        return {"data": json_data}
    except Exception as e:
        logger.error(f"Unexpected error in get_json_data: {e}")
        raise HTTPException(status_code=500, detail=f"Error processing request: {str(e)}")

@app.get("/api/color-code")
async def get_color_code(date: Optional[str] = None):
    """
    Get color codes (G, Y, R) for the current hour and next 7 hours based on price analysis.
    Uses commitment-based stability - colors won't change once committed.
    
    Optional query parameter:
    - date: Date in YYYY-MM-DD format
    """
    # Validate date format if provided
    if date and not re.match(r'^\d{4}-\d{2}-\d{2}$', date):
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
    
    # Determine the start date
    if date:
        start_date = datetime.strptime(date, "%Y-%m-%d")
    else:
        start_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    
    # Fetch data for multiple days to ensure we have enough hours (3 days for extended reference window)
    json_data = await fetch_data_for_date_range(start_date, num_days=3)
    
    if not json_data:
        raise HTTPException(status_code=404, detail="No data available for the requested date range")
    
    # Group by hour
    hourly_data = group_entries_by_hour(json_data)
    
    # Get current and future hours (48 hours for extended reference window)
    extended_hours_data = get_current_and_future_hours(hourly_data, 48)
    
    if not extended_hours_data:
        raise HTTPException(status_code=404, detail="No data available for the requested time period")
    
    # Get the current hour
    current_hour = extended_hours_data[0]["dateTime"]
    
    # Determine color codes using extended reference window
    color_codes = determine_color_codes(extended_hours_data, reference_window_hours=48)
    
    # Apply commitment logic - preserve committed colors for stability
    color_codes = apply_committed_colors(color_codes)
    
    # Commit new colors for the next 8 hours if not already committed
    commit_colors_for_window(color_codes, commitment_hours=8)
    
    # Return only the first 8 hours for display (current + next 7)
    display_colors = color_codes[:8]
    
    # Add metadata about commitment status
    committed_count = sum(1 for color in display_colors if color.get("committed", False))
    
    # Return both the current hour and display color codes
    return {
        "current_hour": current_hour,
        "hour_color_codes": display_colors,
        "meta": {
            "total_hours": len(display_colors),
            "committed_hours": committed_count,
            "flexible_hours": len(display_colors) - committed_count,
            "reference_window_hours": 48,
            "commitment_window_hours": 8
        }
    }

@app.get("/api/sample")
async def get_sample_data():
    """
    Get sample electricity price data for testing.
    """
    # Create sample data that includes various price scenarios
    sample_data = []
    
    # Create a datetime series starting from yesterday and spanning 3 days
    start_date = datetime.now(pytz.UTC).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
    
    # Create sample data with realistic patterns:
    # - Higher prices in morning and evening peaks
    # - Lower prices during night and midday
    # - Occasional negative prices (solar/wind surplus)
    # - 15-minute intervals for each hour
    
    for day_offset in range(3):  # 3 days of data
        current_date = start_date + timedelta(days=day_offset)
        
        for hour in range(24):
            base_time = current_date.replace(hour=hour)
            
            # Create price patterns
            if 0 <= hour < 6:  # Night (low demand)
                base_price = 40.0 + (day_offset * 5)
            elif 6 <= hour < 9:  # Morning peak
                base_price = 120.0 + (day_offset * 10)
            elif 9 <= hour < 14:  # Midday (solar generation)
                # Occasionally negative prices during high solar/wind periods
                if hour == 12 and day_offset == 1:
                    base_price = -10.0
                else:
                    base_price = 30.0 + (day_offset * 5)
            elif 14 <= hour < 17:  # Afternoon
                base_price = 80.0 + (day_offset * 8)
            elif 17 <= hour < 22:  # Evening peak
                base_price = 150.0 + (day_offset * 15)
            else:  # Late evening
                base_price = 70.0 + (day_offset * 5)
                
            # Add some randomness to prices
            price_variation = (hash(f"{current_date.isoformat()}_{hour}") % 20) - 10
            hour_base_price = base_price + price_variation
            
            # Create 15-minute intervals
            for minute in [0, 15, 30, 45]:
                entry_time = base_time.replace(minute=minute)
                # Add slight variation within the hour
                minute_variation = (hash(f"{entry_time.isoformat()}") % 10) - 5
                price = round(hour_base_price + (minute_variation / 10), 4)
                
                sample_data.append({
                    "isVisible": True,
                    "dateTime": entry_time.isoformat().replace('+00:00', 'Z'),
                    "price": price
                })
    
    return {"data": sample_data}

@app.get("/api/sample-color-code")
async def get_sample_color_code():
    """
    Get sample color codes for the current hour and next 11 hours for testing.
    """
    # Get sample data from the sample endpoint that will span multiple days if needed
    sample_data_response = await get_sample_data()
    sample_data = sample_data_response["data"]
    
    # Group by hour
    hourly_data = group_entries_by_hour(sample_data)
    
    # Get current and future 11 hours (total 12 hours)
    hours_data = get_current_and_future_hours(hourly_data, 12)
    
    if not hours_data:
        raise HTTPException(status_code=404, detail="No sample data available for the requested time period")
    
    # Get the current hour
    current_hour = hours_data[0]["dateTime"]
    
    # Determine color codes for all hours
    color_codes = determine_color_codes(hours_data)
    
    # Return both the current hour and all hour color codes
    return {
        "current_hour": current_hour,
        "hour_color_codes": color_codes
    }

@app.get("/api/diagnostic")
async def get_diagnostic(date: Optional[str] = None):
    """
    Diagnostic endpoint to check available data.
    
    Optional query parameter:
    - date: Date in YYYY-MM-DD format
    """
    # Validate date format if provided
    if date and not re.match(r'^\d{4}-\d{2}-\d{2}$', date):
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
    
    # Determine the start date
    if date:
        start_date = datetime.strptime(date, "%Y-%m-%d")
    else:
        start_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    
    # Fetch data for multiple days to ensure we have enough hours
    json_data = await fetch_data_for_date_range(start_date, num_days=2)
    
    # Group by hour
    hourly_data = group_entries_by_hour(json_data)
    
    # Current time for reference
    now = datetime.now(pytz.UTC).replace(minute=0, second=0, microsecond=0)
    
    # Return diagnostic information
    return {
        "total_entries": len(json_data),
        "unique_hours": len(hourly_data),
        "current_time": now.isoformat().replace('+00:00', 'Z'),
        "available_hours": list(hourly_data.keys()),
        "hours_data": get_current_and_future_hours(hourly_data, 12)
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
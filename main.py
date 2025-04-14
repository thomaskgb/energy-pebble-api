from fastapi import FastAPI, HTTPException
import httpx
from datetime import datetime, timedelta
import pytz
import logging
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Dict, Any, Optional
import re
import json

app = FastAPI(title="Electricity color code API", 
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

def get_current_and_future_hours(hourly_data: Dict[str, Dict[str, Any]], hours: int = 8) -> List[Dict[str, Any]]:
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

def determine_color_code(hourly_data: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Determine color code based on price ranges."""
    if not hourly_data:
        raise HTTPException(status_code=404, detail="No data available for the requested time period")
    
    # Extract prices
    prices = [entry["avgPrice"] for entry in hourly_data]
    
    # Find min and max prices
    min_price = min(prices)
    max_price = max(prices)
    current_price = hourly_data[0]["avgPrice"]
    
    # Calculate range and thresholds
    price_range = max_price - min_price
    
    # Avoid division by zero if all prices are the same
    if price_range == 0:
        color_code = "G"  # Default to green if all prices are equal
    else:
        lower_threshold = min_price + (price_range / 3)
        upper_threshold = max_price - (price_range / 3)
        
        if current_price <= lower_threshold:
            color_code = "G"  # Green for cheapest third
        elif current_price <= upper_threshold:
            color_code = "Y"  # Yellow for middle third
        else:
            color_code = "R"  # Red for most expensive third
    
    # Prepare result
    return {
        "current_hour": hourly_data[0]["dateTime"],
        "current_price": current_price,
        "min_price": min_price,
        "max_price": max_price,
        "color_code": color_code,
        "hourly_data": hourly_data
    }

@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "message": "Electricity Price API",
        "endpoints": {
            "/api/json": "Get electricity price data in JSON format (Optional query param: date=YYYY-MM-DD)",
            "/api/color-code": "Get color code based on price analysis (Optional query param: date=YYYY-MM-DD)",
            "/api/sample": "Get sample electricity price data for testing",
            "/api/sample-color-code": "Get sample color code data for testing",
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
    Get color code (G, Y, R) based on price analysis.
    
    Optional query parameter:
    - date: Date in YYYY-MM-DD format
    """
    # Validate date format if provided
    if date and not re.match(r'^\d{4}-\d{2}-\d{2}$', date):
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
    
    # Get the data
    json_response = await get_json_data(date)
    json_data = json_response["data"]
    
    # Group by hour
    hourly_data = group_entries_by_hour(json_data)
    
    # Get current and future 7 hours (total 8 hours)
    hours_data = get_current_and_future_hours(hourly_data, 8)
    
    # Determine color code
    result = determine_color_code(hours_data)
    
    return result

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
    Get sample color code data for testing.
    """
    # Get sample data from the sample endpoint
    sample_data_response = await get_sample_data()
    sample_data = sample_data_response["data"]
    
    # Group by hour
    hourly_data = group_entries_by_hour(sample_data)
    
    # Get current and future 7 hours (total 8 hours)
    hours_data = get_current_and_future_hours(hourly_data, 8)
    
    # Determine color code
    result = determine_color_code(hours_data)
    
    return result

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
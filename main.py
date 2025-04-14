from fastapi import FastAPI, HTTPException
import httpx
from datetime import datetime, timedelta
import xml.etree.ElementTree as ET
import pytz
import logging
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Dict, Any, Optional
import re

app = FastAPI(title="Electricity Price API", 
              description="API that provides electricity price data and color-coded indicators")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allow all methods
    allow_headers=["*"],  # Allow all headers
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# XML namespaces used in the data
NAMESPACES = {
    'ns': 'http://schemas.datacontract.org/2004/07/Elia.EliaBeControls.WebApi.Interface.Dto.FileRepository',
    'ns2': 'http://schemas.datacontract.org/2004/07/Elia.EliaBeControls.WebApi.Interface.Dto'
}

async def fetch_xml_data(date_str: Optional[str] = None):
    """Fetch XML data from Elia's API for a given date."""
    if not date_str:
        # Use today's date if not specified
        date_str = datetime.now().strftime("%Y-%m-%d")
    
    url = f"https://griddata.elia.be/eliabecontrols.prod/interface/Interconnections/daily/auctionresultsqh/{date_str}"
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=10.0)
            response.raise_for_status()  # Raise an exception for HTTP errors
            return response.text
    except httpx.HTTPError as e:
        logger.error(f"HTTP error occurred: {e}")
        raise HTTPException(status_code=503, detail=f"Error fetching data from Elia API: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")

def parse_xml_to_json(xml_data: str) -> List[Dict[str, Any]]:
    """Parse XML data to JSON format."""
    try:
        root = ET.fromstring(xml_data)
        result = []
        
        for price_dto in root.findall('.//ns:DailyDayAheadPriceDto', NAMESPACES):
            # Extract values from XML
            is_visible = price_dto.find('.//ns2:IsVisible', NAMESPACES)
            date_time = price_dto.find('./ns:DateTime', NAMESPACES)
            price = price_dto.find('./ns:Price', NAMESPACES)
            
            # Skip incomplete entries
            if None in (is_visible, date_time, price):
                continue
            
            # Convert to appropriate types
            entry = {
                "isVisible": is_visible.text.lower() == 'true',
                "dateTime": date_time.text,
                "price": float(price.text)
            }
            result.append(entry)
        
        return result
    except ET.ParseError as e:
        logger.error(f"XML parsing error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to parse XML data: {str(e)}")
    except Exception as e:
        logger.error(f"Error processing XML: {e}")
        raise HTTPException(status_code=500, detail=f"Error processing data: {str(e)}")

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
            "/api/json": "Convert Elia XML data to JSON",
            "/api/color-code": "Get color code based on price analysis"
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
    
    xml_data = await fetch_xml_data(date)
    json_data = parse_xml_to_json(xml_data)
    return {"data": json_data}

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
    
    xml_data = await fetch_xml_data(date)
    json_data = parse_xml_to_json(xml_data)
    
    # Group by hour
    hourly_data = group_entries_by_hour(json_data)
    
    # Get current and future 7 hours (total 8 hours)
    hours_data = get_current_and_future_hours(hourly_data, 8)
    
    # Determine color code
    result = determine_color_code(hours_data)
    
    return result

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

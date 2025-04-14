## Update - Format Change

The Elia API is now returning data in JSON format rather than XML. The API has been updated to handle this format change, eliminating the need for XML parsing. Now the application:

1. Fetches the JSON data directly from Elia's API
2. Processes the data to determine hourly averages and color codes
3. Returns results through the same API endpoints

## Project Files

- `main.py`: The FastAPI application
- `requirements.txt`: Python dependencies
- `Dockerfile`: Docker container configuration
- `docker-compose.yml`: Docker Compose setup
- `sample_data.json`: Sample data for testing# Electricity Price Color Code API

This API fetches electricity price data from Elia's API and provides two endpoints:
1. `/api/json`: Converts the XML data to JSON format
2. `/api/color-code`: Analyzes the current and upcoming 7 hours of price data and outputs a color code (G, Y, R) based on price ranges

## How It Works

### Color Code Logic
- **G (Green)**: Current hour price is in the cheapest third of the price range for the 8-hour window
- **Y (Yellow)**: Current hour price is in the middle third of the price range
- **R (Red)**: Current hour price is in the most expensive third of the price range

### Data Processing
- The API fetches 15-minute interval data from Elia's API
- Data is grouped into hourly entries with average prices
- The current hour and the next 7 hours are analyzed to determine price ranges and color code

## Getting Started

### Prerequisites
- Docker and Docker Compose

### Running the API

1. Clone this repository
2. Navigate to the project directory
3. Start the application:
   ```
   docker-compose up -d
   ```
4. The API will be available at http://localhost:8000

## API Endpoints

### Root endpoint
- `GET /`: Shows basic information about the API

### JSON Data Endpoint
- `GET /api/json`: Returns electricity price data in JSON format
- Optional query parameter: `date` (format: YYYY-MM-DD)

### Color Code Endpoint
- `GET /api/color-code`: Returns color code and price analysis
- Optional query parameter: `date` (format: YYYY-MM-DD)

### Sample Data Endpoints (for testing)
- `GET /api/sample`: Returns sample electricity price data
- `GET /api/sample-color-code`: Returns sample color code data based on the sample price data

### API Documentation
- `GET /docs`: Swagger UI documentation for the API

## Example Response (Color Code)

```json
{
  "current_hour": "2025-03-02T12:00:00Z",
  "current_price": -6.97,
  "min_price": -6.97,
  "max_price": 146.57,
  "color_code": "G",
  "hourly_data": [
    {
      "dateTime": "2025-03-02T12:00:00Z",
      "avgPrice": -6.97
    },
    // Additional hours...
  ]
}
```

## Notes

- The API dynamically fetches the latest data from Elia's API
- If no date is specified, it defaults to the current date
- The color code is relative to the 8-hour window being analyzed, not absolute price levels
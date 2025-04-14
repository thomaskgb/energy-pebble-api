Electricity Price Color Code API
This API fetches electricity price data from Elia's API and provides two endpoints:

/api/json: Converts the XML data to JSON format
/api/color-code: Analyzes the current and upcoming 7 hours of price data and outputs a color code (G, Y, R) based on price ranges
How It Works
Color Code Logic
G (Green): Current hour price is in the cheapest third of the price range for the 8-hour window
Y (Yellow): Current hour price is in the middle third of the price range
R (Red): Current hour price is in the most expensive third of the price range
Data Processing
The API fetches 15-minute interval data from Elia's API
Data is grouped into hourly entries with average prices
The current hour and the next 7 hours are analyzed to determine price ranges and color code
Getting Started
Prerequisites
Docker and Docker Compose
Running the API
Clone this repository
Navigate to the project directory
Start the application:
docker-compose up -d
The API will be available at http://localhost:8000
API Endpoints
Root endpoint
GET /: Shows basic information about the API
JSON Data Endpoint
GET /api/json: Returns electricity price data in JSON format
Optional query parameter: date (format: YYYY-MM-DD)
Color Code Endpoint
GET /api/color-code: Returns color code and price analysis
Optional query parameter: date (format: YYYY-MM-DD)
Example Response (Color Code)
json
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
Notes
The API dynamically fetches the latest data from Elia's API
If no date is specified, it defaults to the current date
The color code is relative to the 8-hour window being analyzed, not absolute price levels


# Energy Pebble API
A simple REST API that provides electricity price color codes (Green, Yellow, Red) based on Day ahead prices published by Elia's grid data end-point.

## What It Does

This API fetches electricity price data and converts it to simple color codes to help users optimize their energy consumption:

- **Green (G)**: Indicates the cheapest hours to use electricity
- **Yellow (Y)**: Indicates medium-priced hours
- **Red (R)**: Indicates the most expensive hours to avoid using electricity

The API analyzes the current hour and the next 11 hours, comparing prices within this window to determine the optimal times for energy consumption.

## Project Files

- `main.py`: The FastAPI application
- `requirements.txt`: Python dependencies
- `Dockerfile`: Docker container configuration
- `docker-compose.yml`: Docker Compose setup
- `sample_data.json`: Sample data for testing

## API Endpoints

### Root endpoint
- `GET /`: Shows basic information about the API

### JSON Data Endpoint
- `GET /api/json`: Returns electricity price data in JSON format
- Optional query parameter: `date` (format: YYYY-MM-DD)

### Color Code Endpoint
- `GET /api/color-code`: Returns color codes for current hour and next 11 hours
- Optional query parameter: `date` (format: YYYY-MM-DD)

### Sample Data Endpoints (for testing)
- `GET /api/sample`: Returns sample electricity price data
- `GET /api/sample-color-code`: Returns sample color codes for current hour and next 11 hours

### API Documentation
- `GET /docs`: Swagger UI documentation for the API

## Example Response (Color Code)

```json
{
  "current_hour": "2025-04-14T17:00:00Z",
  "hour_color_codes": [
    {
      "hour": "2025-04-14T17:00:00Z",
      "color_code": "R"
    },
    {
      "hour": "2025-04-14T18:00:00Z",
      "color_code": "R"
    },
    {
      "hour": "2025-04-14T19:00:00Z",
      "color_code": "G"
    }
  ]
}
```

## Getting Started

### Prerequisites
- Docker and Docker Compose

### Running the API

1. Clone this repository
2. Navigate to the project directory
3. Start the application:
   ```
   docker compose up -d
   ```
4. The API will be available at http://localhost:8000
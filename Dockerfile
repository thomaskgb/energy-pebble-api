FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .
COPY sample_data.json .
COPY test_device_detection.py .

# Expose the port the app runs on
EXPOSE 8000

# Command to run the application  
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Set the working directory in the container
WORKDIR /app

RUN apt-get update && apt-get install -y build-essential

# Copy the requirements file and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application source code and all necessary assets
COPY src/ /app/src/
COPY config/ /app/config/
COPY models/ /app/models/
COPY main.py /app/

# Command to run the application
CMD ["python", "main.py"]

# Use the official Python image from the Docker Hub
FROM python:3.8-slim

# Set the working directory
WORKDIR /app

# Copy the requirements file into the container
COPY download_csv/requirements.txt ./download_csv/
COPY process_csv/requirements.txt ./process_csv/

# Install dependencies
RUN pip install --no-cache-dir -r download_csv/requirements.txt
RUN pip install --no-cache-dir -r process_csv/requirements.txt

# Copy the rest of the application code into the container
COPY . .

# Set the entry point to the serverless command
ENTRYPOINT ["serverless"]

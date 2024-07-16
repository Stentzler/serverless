FROM python:3.10-slim

WORKDIR /app

# COPY download_csv/requirements.txt ./download_csv/
# COPY process_csv/requirements.txt ./process_csv/

# RUN pip install --no-cache-dir -r download_csv/requirements.txt
# RUN pip install --no-cache-dir -r process_csv/requirements.txt

# Copy the rest of the application code into the container
COPY . .

# Set the entry point to the serverless command
ENTRYPOINT ["serverless"]

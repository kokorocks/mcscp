#!/bin/bash

# Exit immediately if a command exits with a non-zero status
set -e

# Update and install dependencies
sudo apt update
sudo apt install -y python3 python3-pip default-jdk

# Upgrade pip (recommended)
python3 -m pip install --upgrade pip

# Install packages from requirements.txt (run this in your project folder)
if [ -f "requirements.txt" ]; then
    pip3 install -r requirements.txt
else
    echo "Warning: requirements.txt not found. Skipping pip install."
fi

# -------------------------------------------------------------------
# SYSTEMD SERVICE CONFIGURATION
# -------------------------------------------------------------------

SERVICE_NAME="MCSCP"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

# Detect the actual user if run with sudo, otherwise use current user
RUN_USER=${SUDO_USER:-$(whoami)}
PROJECT_DIR=$(pwd)

echo "Creating systemd service for server.py..."

# Create the service file
sudo tee $SERVICE_FILE > /dev/null <<EOF
[Unit]
Description=Python Server 24/7 Service
After=network.target

[Service]
Type=simple
User=${RUN_USER}
WorkingDirectory=${PROJECT_DIR}
ExecStart=/usr/bin/python3 ${PROJECT_DIR}/server.py
Restart=always
RestartSec=3
StandardOutput=syslog
StandardError=syslog
SyslogIdentifier=${SERVICE_NAME}

[Install]
WantedBy=multi-user.target
EOF

echo "Reloading systemd daemon..."
sudo systemctl daemon-reload

echo "Enabling ${SERVICE_NAME} service to start on boot..."
sudo systemctl enable ${SERVICE_NAME}.service

echo "Starting ${SERVICE_NAME} service..."
sudo systemctl start ${SERVICE_NAME}.service

echo "Service successfully setup and started!"
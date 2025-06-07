# Okay, I've edited your Dockerfile to incorporate several best practices for security, efficiency, and production-readiness. The main changes include:

# 1.  **Non-root User:** Running applications as a non-root user inside the container is a crucial security measure.
# 2.  **Gunicorn for Production:** The Flask development server (`app.run()`) is not suitable for production. Gunicorn is a popular and robust WSGI server for Python web applications.
# 3.  **Healthcheck:** Added a `HEALTHCHECK` instruction, which Docker can use to determine if your application is running correctly.
# 4.  **Optimized Layering for Dependencies:** `requirements.txt` is copied and installed before the rest of the application code to better utilize Docker's build cache.
# 5.  **Clearer Structure:** Added comments to explain each step.

# Here's the edited `Dockerfile`:

# ```dockerfile
# # Base image
FROM python:3.9-slim-bullseye

# Environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV APP_USER=appuser
# APP_HOME is the designated home for the user, though the app itself will reside in /app
ENV APP_HOME=/home/$APP_USER

# Set the working directory for the application
WORKDIR /app

# Install system dependencies
# - curl is needed for the HEALTHCHECK
# - --no-install-recommends keeps the image lean
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user and group for the application
# -r creates a system user/group (no specific home dir created by default unless -m is used)
# -d specifies the home directory (for metadata, not necessarily where app lives)
# -s /sbin/nologin prevents shell login for this user
RUN groupadd -r ${APP_USER} && \
    useradd -r -g ${APP_USER} -d ${APP_HOME} -s /sbin/nologin -c "Application User" ${APP_USER}

# Copy requirements.txt first to leverage Docker cache
# If requirements.txt doesn't change, this layer won't be rebuilt
COPY requirements.txt .

# Install Python dependencies
# Make sure 'gunicorn' is included in your requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
# This includes app.py, templates/, static/ etc.
COPY . .

# Change ownership of the application directory and its contents to the non-root user
# This is important for security and proper file access
RUN chown -R ${APP_USER}:${APP_USER} /app
# Optionally, ensure correct permissions if specific execution is needed (though Gunicorn handles app.py)
# RUN chmod -R 755 /app

# Switch to the non-root user
USER ${APP_USER}

# Expose the port the app runs on
EXPOSE 5000

# Healthcheck
# Docker will periodically run this command to check if the container is healthy.
# It curls the root endpoint of your Flask app.
# -f/--fail: Fail silently (no output at all) on server errors.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -f http://localhost:5000/ || exit 1
  # If your app's root path changes or you have a dedicated /health endpoint, update this.

# Command to run the application using Gunicorn
# - "app:app": Refers to the 'app' Flask instance within the 'app.py' file.
# - "--bind 0.0.0.0:5000": Binds Gunicorn to all network interfaces on port 5000.
# - "--workers 3": A common starting point for the number of worker processes.
#   Adjust based on your application's needs and server resources (e.g., (2 * CPU cores) + 1).
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "3", "app:app"]

# To use the Flask development server (NOT FOR PRODUCTION):
# Remove or comment out the Gunicorn CMD above and uncomment the line below.
# Also, ensure your app.py has app.run(host='0.0.0.0', port=5000)
CMD ["python", "app.py"]
#```

# **Important Next Steps:**


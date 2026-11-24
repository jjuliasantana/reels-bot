FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg fonts-inter fonts-dejavu-core cron && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# Estado e saída em volume: -v bot_state:/app/state -v bot_out:/app/output
RUN printf '0 */4 * * * cd /app && python -m bot.main collect >> /app/output/cron.log 2>&1\n17 15 * * * cd /app && python -m bot.main run >> /app/output/cron.log 2>&1\n' > /etc/cron.d/reels && chmod 0644 /etc/cron.d/reels && crontab /etc/cron.d/reels
CMD ["cron", "-f"]

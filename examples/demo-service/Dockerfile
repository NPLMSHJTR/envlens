FROM python:3.13-slim

ARG BUILD_VERSION=dev
ENV APP_HOME=/app

WORKDIR $APP_HOME
COPY . .
CMD ["python", "-m", "app"]


# syntax=docker/dockerfile:1

FROM python:3.8-slim-buster

WORKDIR /app

ENV PYTHONUNBUFFERED=1
COPY requirements.txt requirements.txt
RUN pip3 install -r requirements.txt
COPY . .
RUN chmod +x /app/app.py

CMD [ "python3", "app.py"]
FROM python:3.9-slim

WORKDIR /app

COPY . .

RUN pip install pipenv && pipenv install --system --deploy

ENV PYTHONPATH /app

CMD ["/app/documentation.py"]

FROM python:3.9-slim

WORKDIR /documentation-tracker

COPY . .

RUN pip install pipenv && pipenv install --system --deploy

WORKDIR /workspace

ENTRYPOINT [ "python3", "/documentation-tracker/documentation.py"]

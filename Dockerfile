FROM python:3-slim

WORKDIR /action

COPY . .

RUN pip install pipenv && pipenv install --system --deploy

ENV PYTHONPATH /action

CMD ["/action/documentation.py"]

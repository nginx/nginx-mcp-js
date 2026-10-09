# Copyright (C) Dmitry Volyntsev
# Copyright (C) F5, Inc.

FROM python:3.13-slim@sha256:3dd7cc108ec1493442514f5c2a871af6af0ec31d768ff6e378a93340c3b3db5f

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY server.py ./

CMD ["python", "server.py"]

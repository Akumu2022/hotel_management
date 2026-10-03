FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY pyproject.toml ./
RUN pip install --no-cache-dir --upgrade pip \
 && python -c "import tomllib;d=tomllib.load(open('pyproject.toml','rb'))['project'];print('\n'.join(d['dependencies']+d['optional-dependencies']['dev']))" > /tmp/req.txt \
 && pip install --no-cache-dir -r /tmp/req.txt

COPY . .
# --no-access-log: live-update URLs carry a short-lived token; the app logs requests itself.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]

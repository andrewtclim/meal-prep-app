# could switch to python:3.11-slim once dependencies are settled, to shrink the image (maybe)
FROM python:3.12

WORKDIR /code

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ app/

# 0.0.0.0 so the server is reachable from outside the container.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

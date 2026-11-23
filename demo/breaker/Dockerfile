FROM python:3.12-slim
RUN useradd --uid 10001 app
COPY breaker.py /app/breaker.py
USER 10001
EXPOSE 8000
CMD ["python", "-u", "/app/breaker.py"]

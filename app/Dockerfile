FROM python:3.12-slim AS build
WORKDIR /src
RUN pip install --no-cache-dir build
COPY pyproject.toml ./
COPY src ./src
RUN python -m build --wheel --outdir /dist

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN useradd --uid 10001 --create-home app
COPY --from=build /dist/*.whl /tmp/
RUN pip install "$(ls /tmp/*.whl)[all]" && rm /tmp/*.whl
USER 10001
EXPOSE 8080
CMD ["alertscope"]

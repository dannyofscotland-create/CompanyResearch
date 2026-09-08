FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir -e .

ENV COMPANYRESEARCH_DATA=/data
ENV HOST=0.0.0.0
ENV PORT=8080
VOLUME ["/data"]
EXPOSE 8080

CMD ["python", "-m", "companyresearch", "--host", "0.0.0.0", "--port", "8080"]

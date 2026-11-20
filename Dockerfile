FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 DATA_DIR=/data
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt && useradd -m -u 10001 app && mkdir /data && chown app /data
COPY nesthost nesthost
USER app
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s CMD python -c "import urllib.request as u;u.urlopen('http://localhost:8000/healthz')"
CMD ["gunicorn","-b","0.0.0.0:8000","-w","2","--threads","4","--timeout","60","nesthost.app:wsgi()"]

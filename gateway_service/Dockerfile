# 构建时的"当前目录"必须是仓库根目录，不是 gateway_service 文件夹自己。
FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1
WORKDIR /app
COPY gateway_service/requirements.txt gateway_service/requirements.txt
RUN pip install --no-cache-dir -r gateway_service/requirements.txt
COPY gateway_service gateway_service
EXPOSE 8011
CMD ["python", "-m", "uvicorn", "gateway_service.main:app", "--host", "0.0.0.0", "--port", "8011"]

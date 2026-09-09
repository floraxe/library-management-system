# 构建时的"当前目录"必须是仓库根目录，不是 user_service 文件夹自己。
FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1
WORKDIR /app
COPY user_service/requirements.txt user_service/requirements.txt
RUN pip install --no-cache-dir -r user_service/requirements.txt
COPY user_service user_service
EXPOSE 8012
CMD ["python", "-m", "uvicorn", "user_service.main:app", "--host", "0.0.0.0", "--port", "8012"]

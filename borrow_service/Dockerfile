# 构建时的"当前目录"必须是仓库根目录，不是 borrow_service 文件夹自己。
FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1
WORKDIR /app
COPY borrow_service/requirements.txt borrow_service/requirements.txt
RUN pip install --no-cache-dir -r borrow_service/requirements.txt
COPY borrow_service borrow_service
EXPOSE 8003
CMD ["python", "-m", "uvicorn", "borrow_service.main:app", "--host", "0.0.0.0", "--port", "8003"]

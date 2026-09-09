# 构建时的"当前目录"必须是仓库根目录（跟 book_service、borrow_service 等文件夹平级的那一层），
# 不是 book_service 文件夹自己，因为下面的 COPY 路径是相对仓库根目录写的。
FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1
WORKDIR /app
COPY book_service/requirements.txt book_service/requirements.txt
RUN pip install --no-cache-dir -r book_service/requirements.txt
COPY book_service book_service
EXPOSE 8002
CMD ["python", "-m", "uvicorn", "book_service.main:app", "--host", "0.0.0.0", "--port", "8002"]

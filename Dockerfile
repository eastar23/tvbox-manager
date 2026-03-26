# 使用官方轻量级 Python 镜像作为基础
FROM python:3.11-slim

# 设置容器内工作目录
WORKDIR /app

# 设置环境变量，提升 Python 在容器内的表现
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
# 指定数据库文件存储在 /app/data 目录中，方便使用 Volume 挂载持久化
ENV DB_PATH=/app/data/database.db

# 复制依赖清单并安装
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制项目的所有代码到容器
COPY . .

# 提前创建 data 目录供 SQLite 使用，避免初次写入找不到路径
RUN mkdir -p /app/data

# 暴露 Flask 运行的 8089 端口
EXPOSE 8089

# 指定持久化卷，方便 NAS/GUI 工具（如群晖、1Panel 等）自动识别并填入 “/app/data”
# 这样用户在部署时，只需要点击选择自己的本地路径即可，装载路径会自动填好
VOLUME ["/app/data"]

# 运行应用
CMD ["python", "app.py"]

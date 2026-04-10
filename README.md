# TVBox 接口管理中心 (v1.0.6)

将 TVBox 接口（单仓/多仓）聚合为规范的 JSON 文件，并生成订阅链接，适配 TVBox, 影视仓，OK影视等。

## 🚀 快速部署 (Docker Compose)

这是最推荐的部署方式。您可以直接使用以下命令进行部署，并根据需要修改参数：

1. **本地新建目录并进入：**
   ```bash
   mkdir tvbox && cd tvbox
   ```

2. **创建 `docker-compose.yml`：**
   ```yaml
   version: '3.8'
   services:
     tvbox-manager:
       image: eastar23/tvbox-manager:latest
       container_name: tvbox-manager
       ports:
         - "8089:8089"
       volumes:
         - ./data:/app/data  # 冒号左边 ./data 是宿主机持久化目录，可自行修改
       environment:
         - REG_CODE=888888  # 注册邀请码，请务必修改
         - SECRET_KEY=your_random_secret_key
         # - BASE_URL=https://yourdomain.com  # 如果使用了反向代理且链接识别不准，请取消注释并填写
       restart: unless-stopped
   ```
   > [!TIP]
   - 如果您希望保持最快更新，请使用 `:latest` 标签。
   - 如果您希望更稳定且能收到更新提醒（群晖等 NAS 常用），可以指定版本号（如 `:v1.0.1`，需在 GitHub 发布对应的 Tag）。
   - 1Panel 用户：直接在“环境变量”处填写 `REG_CODE`，在“路径挂载”处将宿主机目录映射到 `/app/data`。

3. **启动：**
   ```bash
   docker-compose up -d
   ```

## ⚙️ 环境变量说明

| 变量名 | 说明 | 默认值 |
| :--- | :--- | :--- |
| `REG_CODE` | 注册账号所需的邀请码 | `888888` |
| `SECRET_KEY` | Flask Session 加密密钥 | `super-secret...` |
| `BASE_URL` | 外部访问的基础地址（如 https://tv.abc.com） | 自动识别 |

## 🆙 如何更新

1. **进入部署目录：** `cd tvbox`
2. **拉取最新镜像：** `docker-compose pull`
3. **重新部署：** `docker-compose up -d`
4. **清理旧文件：** `docker image prune -f` (可选)

由于我们已将数据挂载到 `./data` 目录，更新过程**不会丢失任何数据**。

## 🛠️ 关于反馈
如果您在使用过程中发现生成的订阅链接无法下载，请检查您的反向代理配置，或手动设置 `BASE_URL`。

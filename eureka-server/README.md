# eureka-server

指导书 2.3 节对应的 Eureka Server，最小实现，只做服务注册中心，不写任何业务代码。
项目里其余微服务都是 Python（FastAPI + py-eureka-client），这一个模块是纯 Java/Spring Boot，
用 IDEA 直接 Open 这个目录（或者在这个目录下用命令行 `mvn`）即可，不需要挂到 Python 那部分代码上。

## 环境要求

- JDK 17（IDEA 里 Project SDK 选 17，和指导书截图里的选项一致）
- Maven 3.6+（IDEA 自带即可）

## 本地运行

```bash
cd eureka-server
mvn spring-boot:run
```

或者打包成 jar 再运行（对应指导书 4.4 节"打包成 JAR"，这是本项目里唯一还需要走 JAR 打包这一步的模块）：

```bash
mvn clean package
java -jar target/eureka-server.jar
```

启动后访问 <http://localhost:8761/> 能看到 Eureka 自带的管理面板，`Instances currently registered with Eureka`
里会列出已经注册上来的服务（gateway-service / user-service / book-service / borrow-service）。

## 和 Python 那边怎么接上

Python 各服务的 `.env` 里配置：

```bash
EUREKA_SERVER=http://<eureka-server所在机器IP>:8761/eureka/
```

本地单机联调时用 `http://localhost:8761/eureka/` 或 `http://127.0.0.1:8761/eureka/` 即可，
和 README.md 里"Start services"一节的说明完全一致，不需要改 Python 代码。

## 部署到 k8s 时

后面第 4 章打镜像、写 Deployment 的时候，这个模块和其他四个 Python 服务一样，各自打成一个镜像，
在 k8s 里各自一个 Deployment + Service。给它写 Dockerfile 时可以直接用官方 `eclipse-temurin:17-jre`
作为运行时基础镜像，把 `target/eureka-server.jar` 拷进去，`ENTRYPOINT ["java","-jar","/app/eureka-server.jar"]`。
其余四个 Python 服务的 Deployment 里，`EUREKA_SERVER` 环境变量填成 k8s 里这个 Eureka Server 对应
Service 的域名，例如 `http://eureka-server:8761/eureka/`（Service 名字按你实际起的名字为准）。这部分属于
4.3/4.6 节的内容，下一步再展开。

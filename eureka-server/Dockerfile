# 多阶段构建：第一阶段用 maven 镜像把项目编译打包成 jar（对应指导书 4.4 节"打包成 JAR"），
# 第二阶段只把编译好的 jar 拷进一个纯运行时的小镜像里，不带整个 JDK/Maven，镜像更小。
FROM maven:3.9-eclipse-temurin-21 AS build
WORKDIR /build
# 用阿里云镜像下载依赖，跟你在 IDEA 里配的是同一个源，避免直连国外仓库很慢/卡住
COPY settings.xml /root/.m2/settings.xml
COPY pom.xml .
COPY src ./src
RUN mvn -q -DskipTests package

FROM eclipse-temurin:21-jre-jammy
WORKDIR /app
COPY --from=build /build/target/eureka-server.jar ./eureka-server.jar
EXPOSE 8761
ENTRYPOINT ["java", "-jar", "/app/eureka-server.jar"]

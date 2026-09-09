package cn.simplemicroservice.eurekaservice;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.cloud.netflix.eureka.server.EnableEurekaServer;

/**
 * 最小 Eureka Server 启动类，对应指导书 2.3 节。
 * 这里只是注册中心本身，不包含任何业务逻辑；
 * 真正的业务微服务（user/book/borrow/gateway）都是 Python 实现，
 * 通过 py-eureka-client 向这个 Server 注册和发现彼此。
 */
@SpringBootApplication
@EnableEurekaServer
public class EurekaServiceApplication {

    public static void main(String[] args) {
        SpringApplication.run(EurekaServiceApplication.class, args);
    }
}

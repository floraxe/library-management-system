-- 对应指导书 2.2 节"数据库的创建 / 在微服务架构中分库"。
-- 每个微服务一个独立的库，复用 4.2 节已经部署好的那个 MySQL 集群，
-- 不需要再单独起数据库实例。
--
-- 用法（在能连上 k8s 里 mysql 服务的地方执行，比如先 kubectl exec 进 mysql 的 pod，
-- 或者用你在 4.2 节里配的 NodePort 从外部连）：
--   mysql -h <mysql地址> -P 3306 -uroot -proot < mysql-provisioning.sql

CREATE DATABASE IF NOT EXISTS library_users   CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS library_books   CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS library_borrows CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- 沿用指导书 4.2/4.3 节示例里的 root/root，本地开发联调用这个即可。
-- 各服务代码里的表结构（books / borrows / users）会在服务启动时由 init_db()
-- 自动创建，这里只需要建好"库"这一层，不用手工建表。

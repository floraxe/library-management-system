# SQLite → MySQL 迁移说明

对应指导书 2.2 节"数据库的创建 / 在微服务架构中分库"，把 `user_service`、`book_service`、
`borrow_service` 的存储从各自的本地 SQLite 文件切换到 4.2 节已经部署好的 MySQL 集群，
每个服务一个独立的库（分库），复用同一个 MySQL 实例。

## 改了什么 / 没改什么

- 只替换了三个服务各自的 `database.py`，新增了对 `mysql://` 这种 `DATABASE_URL` 的支持，
  同时**完全保留**了原来的 `sqlite://` 分支。
- `models.py`、`main.py`、`schemas.py`、`tests/` 一行都没有改。原来 `models.py` 里写的
  `connection.execute("... WHERE id = ?", (id,))`、`row["available_copies"]`、`row.keys()`
  这些用法，两种后端都兼容（MySQL 那边用一个很薄的适配层把 PyMySQL 的连接包成和
  `sqlite3.Connection` 一样的用法，并把 SQL 里的 `?` 占位符换成 MySQL 需要的 `%s`）。
- pytest 用的是 `sqlite:///:memory:` 或临时文件，跟这次改动无关，**原有测试不用动，
  应该继续 9 passed**。真正切换到 MySQL 只发生在你在 `.env` / k8s 环境变量里把
  `DATABASE_URL` 换成 `mysql://...` 的时候。

## 需要你做的三件事

### 1. 建库

在能连上 4.2 节部署的那个 MySQL（`mysql-service` / NodePort）的地方执行 `docs/mysql-provisioning.sql`：

```bash
mysql -h <mysql地址> -P 3306 -uroot -proot < docs/mysql-provisioning.sql
```

建了 `library_users`、`library_books`、`library_borrows` 三个库，表结构不用手建，服务启动时
`init_db()` 会自动建表（`CREATE TABLE IF NOT EXISTS`）。

### 2. requirements.txt 加一行依赖

`book_service/requirements.txt`、`borrow_service/requirements.txt` 我已经帮你加好了
`pymysql>=1.1,<2.0` 这一行（見附件，直接整份覆盖即可）。

`user_service/requirements.txt` 我没拿到现在的完整内容，麻烦你自己在文件末尾加一行：

```text
pymysql>=1.1,<2.0
```

### 3. 改 `DATABASE_URL`

本地/测试环境不用动，`.env` 里继续保持 `DATABASE_URL=sqlite:///./data/xxx.db`（或者干脆不设，跑
pytest 时用的是各测试文件自己 mock/临时的库）。

部署到 k8s 的时候（下一步 4.3 节"环境变量配置文件"会具体讲），每个服务的 Deployment 里把
`DATABASE_URL` 环境变量设成对应的 MySQL 连接串，指向 4.2 节里那个 MySQL 的 k8s Service：

```bash
# user_service
DATABASE_URL=mysql://root:root@mysql:3306/library_users

# book_service
DATABASE_URL=mysql://root:root@mysql:3306/library_books

# borrow_service
DATABASE_URL=mysql://root:root@mysql:3306/library_borrows
```

`mysql` 是 4.2.3.6 节里 `mysql-service.yaml` 起的 Service 名字，跟 borrow_service 在同一个
k8s 命名空间时可以直接用这个短域名；如果不在同一个命名空间，要写全 `mysql.<namespace>.svc.cluster.local`。
本地不在 k8s 里单独跑某个服务联调时，把 `mysql` 换成 MySQL 所在机器的 IP，端口用 NodePort 暴露出来的那个即可。

## 本地验证步骤

1. 建库（见上面第 1 步），或者本地随便起一个 `docker run -d -p 3306:3306 -e MYSQL_ROOT_PASSWORD=root mysql:8.0.26` 先联调。
2. `.env` 里把某个服务的 `DATABASE_URL` 改成 `mysql://root:root@127.0.0.1:3306/library_books`。
3. 正常按 README 里的方式 `uvicorn book_service.main:app --port 8002` 启动，看日志里 `init_db()` 有没有报错。
4. `curl -i -X POST http://localhost:8002/api/books -d '{"title":"t","author":"a","isbn":"1","total_copies":1}' -H 'Content-Type: application/json'`，
   能拿到 `201` 并且能在 MySQL 里 `SELECT * FROM library_books.books;` 看到这条记录，就说明切换成功。
5. 跑 `pytest -q` 确认原有测试不受影响（应该还是全绿，因为测试用的是 sqlite 路径）。

## 关于 book_service 的 CHECK 约束

`total_copies >= 0`、`available_copies <= total_copies` 这两个 CHECK 约束用的是 MySQL 8.0.16+
才支持的语法，4.2 节里部署的镜像是 `mysql:8.0.26`，版本够，直接能用，不用改。

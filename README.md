# 海砾 · 采样账本 WAL 恢复演练
海砾计量数据保障组（8人）用可重放日志替代恢复演练时手工拼接的SQL片段和账本截图。

## 场景与模块
上游为事务日志样例，下游为值班复核人。原流程人工标记提交、表格算恢复余额、截图写结论；痛点是崩溃点不清、撤销顺序容易错、恢复证据缺失。模块为事务日志集 / 故障注入点 / 恢复队列 / 恢复证据，实体LogSet/CrashCase/Recovery贯穿全栈。扩展模块为超限警报台账 / 警报补偿对账，实体Alarm/Reconciliation/OutboxMessage/ReceiverState承接“断电前误报撤销、接收方确认后对账完成”。

**Python WAL教学模型，不注入真实PostgreSQL故障，不执行数据库物理恢复。** PostgreSQL真实保存业务输入、冻结快照、任务和结果，Redis实际用于worker互斥，后台Python实际演算恢复历史与对账投递。

## 启动
```bash
cp .env.example .env
docker compose up -d --build
# http://localhost:18246
# http://localhost:19246/docs
docker compose exec -T backend python -m scripts.seed_demo
docker compose down --remove-orphans
```
SEED_DEMO=true时启动自动执行种子；自然键查重，不覆盖用户修改。初始化失败显式阻止启动，不隐藏结构错误。删除数据需显式down -v。

|账号|密码|权限|典型动作|
|---|---|---|---|
|admin@haili.local|Recovery2026!|读写/导出/审计|查询审计记录|
|operator@haili.local|Recovery2026!|新增日志/场景/运行/导出|设置断电点10|
|viewer@haili.local|Recovery2026!|只读/导出|核对恢复账本|

## 一天的复核剧本
09:00操作员登录；09:05查看海砾采样账本-晚班（A100、B50）；09:10复制日志集保存shift-20261117；09:15在第10条日志后注入断电点；09:20提交恢复；09:25核对检查点LSN4、已提交T3、未提交T2两条写入逆序撤销，最终A60/B50；09:30下载JSON；09:40观察员核对且写操作403；10:00管理员查看/api/audits。

## 算法、格式和失败态
日志为JSON数组，操作为begin/write/commit/abort/checkpoint；write包含tx/key/value，其他事务操作包含tx，checkpoint不带tx。键必须在初始整数账本存在。事务ID不可复用；严格写锁直到commit/abort释放，同键重叠活动事务拒绝；检查点仅在无活动事务时允许。最多200条日志/30键/整数绝对值不超过10亿。

crash_after=N表示前N条日志已持久化。最近静止检查点保存全部数据页，检查点后数据页假定均未写回（no-force）。恢复重放日志写入和已abort的撤销，再按LSN倒序撤销未结束事务。独立oracle从检查点账本仅应用已提交事务写入，结果须相同。输出重做/撤销轨迹、事务集合、各阶段账本、SHA256和模型版本。空输入、未知键、事务顺序非法、检查点有活动事务、写锁冲突、崩溃点超限均拒绝。模型不涉及页LSN、CLR、模糊检查点或真实磁盘故障；不是完整ARIES实现。

## 超限警报与补偿对账
每条警报锚定一条write日志（LSN+采样键），阈值/实测值齐备，仅允许实测值大于阈值的超限警报；同一日志位置不重复建警。恢复演算完成后发起对账，系统按恢复结论判定：已提交事务写入的警报为`valid`有效保留；未提交（loser）或已回滚（aborted）写入的警报为`false_alarm`误报，向接收方补发撤警补偿；锚定写入在崩溃前缀之外、从未落盘的警报为`not_durable`，不产生任何消息。

发件箱（outbox）消息带确定性幂等键`message_id=sha256(对账+警报+消息类型)`，接收方按message_id去重、按alarm_id维护absent→active→withdrawn状态机：补偿先于原警报到达时直接登记withdrawn，迟到的原警报不能让误报复活；重复撤警无副作用。回执丢失仅令发件箱进入failed退避重试，接收方已落库的处理不重复执行。全部状态落PostgreSQL，worker重启后重新捞取reconciling对账的到期消息继续投递；`held`（迟到模拟）消息只能由演练页面显式放行。账本与过程任何角色可先看，全部消息回执且接收方终态与期望一致后状态才转`confirmed`，即对账完成。

演练页可勾选**模拟迟到**（原始警报先held、补偿先到）与**模拟丢回执**（首次投递接收方已处理但回执丢失），并在详情页核对发件箱状态、到达顺序、接收方警报状态与期望终态；对账证据可与恢复证据分别导出JSON。

## 工程与开发
前端原生HTML/CSS/JS+Nginx1.27；后端Python3.11+FastAPI+SQLAlchemy+PyJWT；PostgreSQL16和Redis7；5服务均healthcheck。持久任务队列在PG，单worker通过Redis锁互斥。20条待执行配额，审计记录写入操作，JWT8小时、PBKDF2随机盐密码。后端路由不含/api，Nginx/api/去前缀代理。

目录frontend/src/{api,stores,types,components/common,hooks,pages,router,utils,constants}与backend/src/{routes,controllers,services,models,schemas,middlewares,utils,constants,config}。本地开发安装backend/requirements.txt并设DATABASE_URL/REDIS_URL/JWT_SECRET，再运行uvicorn src.main:app；前端需代理/api。migrations记录初始化结构，暂无在线升级器。后端模型与HTTP测试位于backend/tests/（SQLite内存库，`DATABASE_URL='sqlite://' python3 tests/test_reconcile.py` 与 `tests/test_api.py`）。

环境COMPOSE_PROJECT_NAME控制命名，FRONTEND_PORT/BACKEND_PORT/DB_PORT为18246/19246/17746，DB_PASSWORD控制演示数据库密码，JWT_SECRET签名密钥，SEED_DEMO控制种子。命名卷db-data/redis-data/artifacts；共享artifacts预留，导出由冻结快照即时生成。Google Fonts需外网，业务离线可运行。默认凭据仅本地演示。

共享枚举roles、任务states、对账/发件箱/接收方状态定义于backend/src/constants/enums.py、frontend/src/constants/enums.js，状态使用models/entities.py/services/recovery_service.py/services/reconcile_service.py/worker.py/components/common/status.js；日志操作类型在schemas/log_set.py和pages/logs.js中声明/说明。MIT许可。真实验证见批次test-artifacts/gb-4107/TESTING.md。

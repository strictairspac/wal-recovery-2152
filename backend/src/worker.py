import logging, time
from pathlib import Path
from sqlalchemy import select
from redis import Redis
from src.config.database import Session
from src.config.settings import REDIS_URL
from src.models.entities import Recovery, Reconciliation
from src.services.wal_engine import recover
from src.services.outbox_service import deliver_due
redis = Redis.from_url(REDIS_URL)
logging.basicConfig(level=logging.INFO)
# Redis leadership lock ensures only one worker processes the durable DB queue.
while True:
    Path('/tmp/heartbeat').touch()
    lock = redis.lock('wal-worker', timeout=15, blocking_timeout=1)
    try:
        with lock:
            with Session() as db:
                job = db.scalar(select(Recovery).where(Recovery.status == 'queued').order_by(Recovery.id).with_for_update(skip_locked=True))
                if job:
                    job.status = 'running'
                    try:
                        job.result = recover(job.snapshot['log_set']['initial'],job.snapshot['log_set']['records'],job.snapshot['case']['crash_after'])
                        job.status = 'completed'
                    except ValueError as exc:
                        job.result = {'error': str(exc), 'simulation': True}
                        job.status = 'failed'
                    db.commit()
                    logging.info('recovery %s %s', job.id, job.status)
                # 重启后接着对账：发件箱与接收方状态都在 PostgreSQL，worker 重新捞取到期消息。
                # held（迟到模拟）消息必须由演练页面显式放行，worker 不代投。
                for rec in db.scalars(select(Reconciliation).where(Reconciliation.status == 'reconciling')).all():
                    results = deliver_due(db, rec)
                    if results:
                        db.commit()
                        logging.info('reconciliation %s delivered %s -> %s', rec.id, len(results), rec.status)
    except Exception:
        logging.exception('worker retry')
    time.sleep(1)

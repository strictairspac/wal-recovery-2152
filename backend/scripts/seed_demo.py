import os
from sqlalchemy import select
from src.config.database import Base,engine,Session
from src.models.entities import User,LogSet,CrashCase,Alarm
from src.utils.security import hash_password
RECORDS=[{'op':'begin','tx':'T1'},{'op':'write','tx':'T1','key':'sample_A','value':75},{'op':'commit','tx':'T1'},{'op':'checkpoint'},{'op':'begin','tx':'T2'},{'op':'write','tx':'T2','key':'sample_B','value':40},{'op':'begin','tx':'T3'},{'op':'write','tx':'T3','key':'sample_A','value':60},{'op':'commit','tx':'T3'},{'op':'write','tx':'T2','key':'sample_B','value':35},{'op':'commit','tx':'T2'}]
# 警报锚定 write 日志位置：LSN2（T1已提交，有效）、LSN8（T3已提交，有效）、LSN10（T2未提交，误报须撤警）
ALARMS=[(2,'sample_A',70,75,'T1写入后A超限，事务已提交'),(8,'sample_A',55,60,'T3写入后A超限，事务已提交'),(10,'sample_B',30,35,'T2末次写入B超限，断电时T2未提交')]
def seed():
    Base.metadata.create_all(engine)
    if os.getenv('SEED_DEMO','true').lower()!='true':return
    with Session() as db:
        for role in ('admin','operator','viewer'):
            email=role+'@haili.local'
            if not db.scalar(select(User).where(User.email==email)):db.add(User(email=email,role=role,password_hash=hash_password('Recovery2026!')))
        logs=db.scalar(select(LogSet).where(LogSet.name=='海砾采样账本-晚班'))
        if logs is None:
            logs=LogSet(name='海砾采样账本-晚班',description='A初始100份、B初始50份，T1提交后检查点，T2未提交，T3已提交',initial={'sample_A':100,'sample_B':50},records=RECORDS);db.add(logs);db.flush()
        for name,point in [('断电点10-撤销T2',10),('完整提交点11',11),('初始点0',0)]:
            if not db.scalar(select(CrashCase).where(CrashCase.name==name)):db.add(CrashCase(name=name,log_set_id=logs.id,crash_after=point))
        for lsn,key,threshold,observed,note in ALARMS:
            if not db.scalar(select(Alarm).where(Alarm.log_set_id==logs.id,Alarm.lsn==lsn)):
                db.add(Alarm(log_set_id=logs.id,lsn=lsn,key=key,threshold=threshold,observed=observed,note=note))
        db.commit()
if __name__=='__main__':seed()

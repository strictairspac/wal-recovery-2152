/**
 * @typedef {{id:number,log_set_id:number,lsn:number,key:string,threshold:number,observed:number,note:string}} Alarm
 * @typedef {{id:number,recovery_id:number,label:string,status:string,sim_late:boolean,sim_lost_ack:boolean,snapshot:object}} Reconciliation
 * @typedef {{id:number,reconciliation_id:number,alarm_id:number,message_id:string,msg_type:string,payload:object,status:string,attempts:number,last_error:string,acked_at:string|null}} OutboxMessage
 * @typedef {{alarm_id:number,message_id:string,msg_type:string,alarm_state:string,arrived_seq:number}} ReceiverState
 */
export {};

import {api} from './client.js';
export const logSetsAPI={list:()=>api('/log-sets'),create:data=>api('/log-sets',{method:'POST',body:JSON.stringify(data)})};
export const crashCasesAPI={list:()=>api('/crash-cases'),create:data=>api('/crash-cases',{method:'POST',body:JSON.stringify(data)})};
export const recoveriesAPI={list:()=>api('/recoveries'),get:id=>api('/recoveries/'+id),create:data=>api('/recoveries',{method:'POST',body:JSON.stringify(data)})};
export const alarmsAPI={list:()=>api('/alarms'),create:data=>api('/alarms',{method:'POST',body:JSON.stringify(data)})};
export const reconciliationsAPI={
 list:()=>api('/reconciliations'),
 get:id=>api('/reconciliations/'+id),
 create:data=>api('/reconciliations',{method:'POST',body:JSON.stringify(data)}),
 releaseLate:id=>api('/reconciliations/'+id+'/release-late',{method:'POST'}),
 deliver:id=>api('/reconciliations/'+id+'/deliver',{method:'POST'}),
};

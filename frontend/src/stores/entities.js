import {logSetsAPI,crashCasesAPI,recoveriesAPI,alarmsAPI,reconciliationsAPI} from '../api/entities.js';
export const store={logs:[],cases:[],runs:[],alarms:[],reconciliations:[],async refresh(){[this.logs,this.cases,this.runs,this.alarms,this.reconciliations]=await Promise.all([logSetsAPI.list(),crashCasesAPI.list(),recoveriesAPI.list(),alarmsAPI.list(),reconciliationsAPI.list()]);}};

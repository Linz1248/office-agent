import { ElMessage } from 'element-plus'
import router from '../router'
import config from "/config";
import axios from "axios";
import { useUserStore } from "@/stores/user";

const request = axios.create({
    // baseURL: `http://${config.docExtractServerUrl}`,
    timeout: 300000  // 后台接口超时时间设置，300秒
});


// request 拦截器
// 可以自请求发送前对请求做一些处理
// 比如统一加token，对请求参数统一加密
request.interceptors.request.use(cfg => {
    const server = cfg.serverName
    cfg.baseURL = config[server]
    console.log('请求的URL: '+cfg.baseURL)
    if (server != 'multimodel' && !(cfg.data instanceof FormData)){
      cfg.headers['Content-Type'] = 'application/json;charset=utf-8';
    }
    cfg.headers['Authorization'] = useUserStore().getBearerToken;  // 设置请求头
    return cfg
}, error => {
    return Promise.reject(error)
});

request.interceptors.response.use(
    response => {
        return response;
    },
    error => {
      // 如果是 HTTP 401（axios 抛出的异常）
      if (error.response && error.response.status === 401) {
        ElMessage.error(error.response.data?.detail || '登录已失效，请重新登录');
        useUserStore().clearLoginInfo();
        router.push("/login");
      }
      return Promise.reject(error);
    }
  );

export default request

# 本地 HTTPS 测试材料

`localhost-cert.pem` 和 `localhost-key.pem` 仅用于 127.0.0.1/localhost 的合成测试服务器。
私钥是公开测试材料，不是用户凭证，不可用于部署。客户端只在测试构造的 SSLContext
中信任此证书；生产辅助函数保留默认 TLS 验证，不设置 verify=False。

测试通过真实本地 TLS 连接观察取消后对端 EOF/连接重置，不调用模型服务。

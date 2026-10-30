// H5 业务域名（必须替换为你的 HTTPS 域名，并在微信公众平台配置业务域名 + 放置校验文件）
const H5_BASE = 'https://h5.your-domain.com';

Page({
  data: {
    url: H5_BASE,
  },
  onLoad(options) {
    // 支持深链：home 页可传 path，例如 /pages/webview/index?path=compare
    if (options.path) {
      this.setData({ url: H5_BASE + '/' + String(options.path).replace(/^\/+/, '') });
    }
  },
});

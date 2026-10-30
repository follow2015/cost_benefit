Page({
  enter() {
    // 跳转到 web-view 页；可带 path 参数做深链，如 enter({ detail: { path: 'compare' } })
    wx.navigateTo({ url: '/pages/webview/index' });
  },
});
